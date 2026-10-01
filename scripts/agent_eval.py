# -*- coding: utf-8 -*-
"""Run the agentic extractor's paid arms, score every draft they write, and
compare them with best-of-k on a cost-accuracy frontier.

    python scripts/agent_eval.py --run-id smoke-1 --cells clarkco:deepseek/deepseek-v4-flash:3
    python scripts/agent_eval.py --run-id smoke-1 --cells ... --run --max-spend 2

The plan is docs/evidence/2026-09-29-agentic-extractor-plan.md ("Arms").
Without `--run` nothing is sent: the stored best-of-k points, the model's
host prices and the run's worst case are printed, with the frontier of any
episodes this run id already has, and a worst case over `--max-spend` is
refused.

**Arms.** `agent` and `scripted` (`permits/agent/graph.py`), and `oneshot`:
fresh one-shot draws, the v2 request bought again in this run, as a check
for drift since the stored draws. Every episode gets the v2 one-shot request
as its first turn (the frozen synthesis prompt and the same excerpt of the
target's first page); the paid arms also get the target's whole stripped
corpus as their workspace.

**Spend is list-priced** (`infer.list_cost`): tokens at the model's list
price, every input token at the input rate, so it does not depend on the
host that served a call. Billed dollars from the ledger are kept beside it.

**One run gives every cap.** An agent or scripted episode runs once under
`--cap-usd` (list-priced, checked before each turn). Each turn's cumulative
spend and latest draft are recorded, every distinct draft is scored, and
`at_cap` reads the outcome at any B. The scripted loop is never told its
limit, so its episode stopped at B is exactly its first B. The agent is told
its budget and paces itself for `--cap-usd`, so below it an agent point is
the episode cut off at B, not an agent given B. The turn that
crosses B still runs and counts, as in a live run, and spend is reported as
incurred. An episode that stopped early on a host failure, or on the run's
own cap below B, is not observed at B and is counted apart.

**Best-of-k** is computed, not simulated, from the stored v2 draws of the same
model and target: their list-priced cost (the ledger row that bought each,
with the cut-off attempt of a re-drawn draw), the verifier's verdicts
(`spikes/verifier_offline.py`) and the scorer's outcome, with field agreement
from the field audit. Its interval is a bootstrap over those draws. The
frontier is read at the spend of best-of-1, 5, 10 and 20; best-of-5 is the
pre-registered primary point.

**Scoring** happens here, after the episode and outside it: each draft goes
through the v2 audit, runner and scorer (`permits.harness.score`) against the
adapter's parse of every page, so an outcome means what a v2 draw's does,
with field agreement (the v2 run's deviation 4) beside it. `permits/agent/`
never sees the references or the scorer.

**Where things go** (all under `data/agent/`, gitignored): `episodes.json`,
one record per episode keyed `run|arm|target|model|eNN`, saved after each
episode; scored drafts under `synth/<run>/`; LangGraph's SQLite checkpoints
in `checkpoints.sqlite`, so an interrupted episode resumes at its last node
without buying its turns again, and a finished one is not run again. Model
calls go through `permits.infer`: the ledger, the response cache (keyed by
run id and episode, so no response crosses between runs) and the
per-process ceiling.

**Two LangSmith projects:** `buildscope-agent-dev` by default, and
`buildscope-agent-eval` with `--eval`, which also requires a run id starting
`eval-` (and nothing else may use one). Traces are for reading episodes;
every number here comes from the ledger and the scorer.
"""
import argparse
import collections
import hashlib
import io
import math
import os
import random
import statistics
import sys
import time
import zlib
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from langgraph.checkpoint.sqlite import SqliteSaver           # noqa: E402
from permits import fileio, infer, rollup, sandbox            # noqa: E402
from permits import harness as H                              # noqa: E402
from permits.agent import graph as G                          # noqa: E402
from permits.agent import tools as T                          # noqa: E402
from permits.cells import CellSpec, Outcome                   # noqa: E402
from permits.models import Protocol                           # noqa: E402
from permits.stats import wilson                              # noqa: E402

OUT = os.path.join(ROOT, "data", "agent")
EPISODES = os.path.join(OUT, "episodes.json")
CHECKPOINTS = os.path.join(OUT, "checkpoints.sqlite")
VERIFIER_CHECKS = os.path.join(H.OUT, "verifier", "checks.json")
FIELD_AUDIT = os.path.join(H.OUT, "verifier", "field_audit.json")
VARIANCE = os.path.join(H.OUT, "variance.json")
LEDGER = os.path.join(H.OUT, "ledger.jsonl")

ARMS = ("agent", "scripted", "oneshot")
GRAPH_ARMS = ("agent", "scripted")
DEV_PROJECT = "buildscope-agent-dev"
EVAL_PROJECT = "buildscope-agent-eval"
EVAL_PREFIX = "eval-"
FIELDS = [role for role, _ in H.ROLES]
# The one-shot request's excerpt size: `--synth-window`'s default in
# conformance.py, which every v2 draw was bought with.
SYNTH_WINDOW = 24000
RAN = (Outcome.PERFECT, Outcome.IMPERFECT)
# The frontier's points: the spend of best-of-k at these k. PRIMARY_K is the
# pre-registered comparison; the others are descriptive.
KS = (1, 5, 10, 20)
PRIMARY_K = 5
BOOTSTRAP = 2000
# Stops that end an episode for a reason unrelated to its limit: at any
# larger cap the episode would have gone on, so it is not observed there.
CENSORING = ("infra_error", "refused")


# ----------------------------------------------------------- the cells
@dataclass(frozen=True)
class Cell:
    target: str
    model: str
    episodes: int

    @classmethod
    def parse(cls, entry):
        try:
            target, model, n = entry.strip().rsplit(":", 2)
            n = int(n)
        except ValueError:
            raise ValueError("bad cell %r: want target:model:episodes"
                             % entry) from None
        if target not in H.TARGETS:
            raise ValueError("unknown target %r in %r" % (target, entry))
        infer.spec(model)
        if n < 1:
            raise ValueError("no episodes in %r" % entry)
        return cls(target, model, n)


def episode_key(run_id, arm, target, model, episode):
    return "%s|%s|%s|%s|e%02d" % (run_id, arm, target, model, episode)


# ------------------------------------------------------------ best-of-k
@dataclass(frozen=True)
class Stored:
    """One stored v2 draw, as best-of-k sees it."""
    draw: int
    list_usd: float
    usd: float
    accepted: bool
    perfect: bool
    field_perfect: bool | None


def expected_spend(prices, accepted, k):
    """The expected cost of best-of-k over one cell's stored draws: look at
    the draws in a uniformly random order, paying for each, and stop at the
    first the verifier accepts or after k. Exact, not simulated.

    Draw j is looked at in position p (1-based, p <= k) when it lands there,
    with probability 1/n, and the p-1 draws before it, a uniform subset of
    the other n-1, are all rejected: C(m_j, p-1) / C(n-1, p-1), where m_j is
    the number of rejected draws other than j."""
    n = len(prices)
    if n != len(accepted) or not n:
        raise ValueError("need one price and one verdict per draw")
    k = min(k, n)
    rejected = sum(1 for a in accepted if not a)
    total = 0.0
    for price, ok in zip(prices, accepted, strict=True):
        m = rejected - (0 if ok else 1)
        seen = sum(math.comb(m, p - 1) / math.comb(n - 1, p - 1)
                   for p in range(1, k + 1))
        total += price * seen / n
    return total


def kept_chance(n, rejected, k):
    """The chance a given accepted draw is the one best-of-k keeps: it is
    looked at before any other accepted draw, within the first k."""
    k = min(k, n)
    return sum(math.comb(rejected, p - 1) / math.comb(n - 1, p - 1)
               for p in range(1, k + 1)) / n


def best_of_k(draws, k):
    """Best-of-k's success rate (record agreement, and field agreement where
    every kept draw's is known) and its mean spend per task, exactly."""
    n = len(draws)
    acc = [d.accepted for d in draws]
    rejected = n - sum(acc)
    keep = kept_chance(n, rejected, k)
    fields = [d.field_perfect for d in draws if d.accepted and d.perfect]
    return {"k": min(k, n),
            "success": keep * sum(1 for d in draws if d.accepted and d.perfect),
            "field_success": (keep * sum(1 for f in fields if f)
                              if None not in fields else None),
            "list_usd": expected_spend([d.list_usd for d in draws], acc, k),
            "usd": expected_spend([d.usd for d in draws], acc, k)}


def best_of_k_interval(draws, k, seed):
    """A 95% percentile interval on best-of-k's success rate, resampling the
    stored draws with replacement."""
    rng = random.Random(seed)
    xs = sorted(best_of_k([rng.choice(draws) for _ in draws], k)["success"]
                for _ in range(BOOTSTRAP))
    return xs[int(0.025 * BOOTSTRAP)], xs[int(0.975 * BOOTSTRAP) - 1]


def _checks_key(source):
    """`spikes/verifier_offline.py`'s key: the path and a hash of the bytes
    on disk."""
    with io.open(source, "rb") as fh:
        h = hashlib.sha256(fh.read()).hexdigest()[:16]
    return "%s#%s" % (os.path.relpath(source, ROOT), h)


def _row_usage(r):
    return infer.Usage(r.input_tokens, r.output_tokens,
                       r.cache_read_input_tokens or 0,
                       r.cache_creation_input_tokens or 0)


def stored_draws(cells):
    """{(target, model): [Stored]} for the stored v2 one-shot cells."""
    v = fileio.read_json(VARIANCE)
    checks = fileio.read_json(VERIFIER_CHECKS)
    audit = {(a["cell"], a["draw"]): a for a in fileio.read_json(FIELD_AUDIT)}
    ledger = infer.Ledger(LEDGER).rows()
    bought = rollup.purchases(v, ledger)
    out = {}
    for c in cells:
        key = CellSpec(c.target, c.model, 0, False, Protocol.V2).key
        cell = v["cells"].get(key)
        if cell is None:
            raise SystemExit("no stored v2 cell %s to compare with" % key)
        draws = []
        for d in cell["detail"]:
            if d["outcome"] in ("infra_error", "not_attempted"):
                continue
            rows = [bought.get((key, d["draw"])),
                    bought.get((key, d["draw"], "cut"))]
            if rows[0] is None:
                raise SystemExit("draw %d of %s has no purchase row"
                                 % (d["draw"], key))
            rows = [ledger[i] for i in rows if i is not None]
            accepted = False
            if d["outcome"] in RAN:
                failed = checks.get(_checks_key(d["source"]))
                if failed is None:
                    raise SystemExit("draw %d of %s has no verifier verdict: "
                                     "run spikes/verifier_offline.py first"
                                     % (d["draw"], key))
                accepted = not failed
            perfect = d["outcome"] == Outcome.PERFECT
            fa = audit.get((key, d["draw"]))
            field = ((fa["ids_still_perfect"]
                      and not sum(fa["disagree"].values()))
                     if fa else None) if perfect else False
            draws.append(Stored(
                d["draw"],
                sum(infer.list_cost(c.model, _row_usage(r)) for r in rows),
                sum(r.usd for r in rows), accepted, perfect, field))
        out[(c.target, c.model)] = draws
    return out


def host_prices(model):
    """Per host, the model's v2 draws: count and the median ratio of billed
    to list-priced cost. This runner's own calls are left out: a multi-turn
    episode is mostly cached input, so its ratio is not a draw's."""
    ratios = collections.defaultdict(list)
    for r in infer.Ledger(LEDGER).rows():
        if (r.model == model and r.protocol == "v2" and r.ok
                and r.call_class not in ARMS):
            lst = infer.list_cost(model, _row_usage(r))
            if lst:
                ratios[r.host or "?"].append(r.usd / lst)
    return {h: (len(x), statistics.median(x)) for h, x in ratios.items()}


# ------------------------------------------------------------ scoring
def score_code(target, code, corpus, refs, path):
    """Score one module as a v2 draw is scored (`_run_variance` in
    scripts/conformance.py): the audit, then every page, then agreement with
    the adapter. Returns the outcome and the figures beside it. The same
    steps as that function's, after its code block is extracted, with the
    same audit, runner and scorer; the steps are not shared with it, because
    it was running stage 3 of the v2 run while this was written.
    `tests/test_agent_eval.py` pins each outcome."""
    if not code or "def extract(" not in code:
        return {"outcome": Outcome.NO_CODE, "field_perfect": False}
    problems, _imports = sandbox.audit(code)
    if problems:
        return {"outcome": Outcome.REFUSED, "audit_problems": problems,
                "field_perfect": False}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(code)
    res, err = sandbox.run_synth(path, corpus, os.path.dirname(path))
    if err:
        return {"outcome": Outcome.EXEC_ERROR, "error": err[:300],
                "field_perfect": False, "source": path}
    raised = [i for i in res if not i["ok"]]
    if raised:
        return {"outcome": Outcome.RAISED, "raised_on": len(raised),
                "error": (raised[0].get("error") or "")[:200],
                "field_perfect": False, "source": path}
    sc = [H.score(target, refs[os.path.basename(i["page"])], i["rows"])
          for i in res]
    rr = [x["recall"] or 0.0 for x in sc]
    pp = [x["precision"] or 0.0 for x in sc]
    perfect = min(rr) == 1.0 and min(pp) == 1.0
    disagree = collections.Counter()
    for x in sc:
        for role, f in x["fields"].items():
            disagree[role] += f["compared"] - f["agree"]
    return {"outcome": Outcome.PERFECT if perfect else Outcome.IMPERFECT,
            "recall_min": min(rr), "precision_min": min(pp),
            "pages_scored": len(sc),
            "field_disagreements": dict(sorted(disagree.items())),
            "field_perfect": perfect and not sum(disagree.values()),
            "source": path}


def score_drafts(target, drafts, corpus, refs, stem):
    """{digest: score} for every distinct draft of an episode."""
    return {h: score_code(target, code, corpus, refs,
                          "%s_%s.py" % (stem, h))
            for h, code in sorted(drafts.items())}


# ---------------------------------------------------------- the frontier
def at_cap(rec, cap):
    """What the episode would have handed back had its limit been `cap`:
    {"perfect", "field_perfect", "list_usd"}, or None when the episode was
    not observed that far. The limit is checked before each turn, so the
    turns that run are those that start below `cap`."""
    traj = rec.get("trajectory") or []
    spent, last, n = 0.0, None, 0
    for step in traj:
        if spent >= cap:
            break
        last, spent, n = step, step["list_usd"], n + 1
    # Every turn ran and the spend is still below the cap: a live run at
    # this cap would have tried another turn. Unless the episode had ended
    # for its own reasons (submitted, the turn limit, no tool call), what
    # that turn would have done is not known: a host failure, a refusal or
    # the run's own cap stopped it first.
    if (n == len(traj) and spent < cap
            and (rec["stop"] in CENSORING or rec["stop"] in ("budget", None))):
        return None
    s = (rec.get("draft_scores") or {}).get(last["draft"]) if last and \
        last.get("draft") else None
    return {"perfect": bool(s and s["outcome"] == Outcome.PERFECT),
            "field_perfect": bool(s and s.get("field_perfect")),
            "list_usd": spent}


def frontier_point(recs, cap):
    seen = [x for x in (at_cap(r, cap) for r in recs) if x is not None]
    ok = sum(1 for x in seen if x["perfect"])
    fok = sum(1 for x in seen if x["field_perfect"])
    return {"n": len(seen), "unobserved": len(recs) - len(seen), "ok": ok,
            "field_ok": fok, "ci": wilson(ok, len(seen)),
            "list_usd": (sum(x["list_usd"] for x in seen) / len(seen)
                         if seen else None)}


def _cell_seed(target, model, k):
    return zlib.crc32(("%s|%s|%d" % (target, model, k)).encode("utf-8"))


def print_frontier(cell, draws, recs_by_arm, cap_usd):
    tier = infer.short_model(cell.model)
    n, ok = len(draws), sum(1 for d in draws if d.perfect)
    print("\n  %s x %s: %d stored v2 draws, pass@1 %d/%d, verifier accepts %d"
          % (cell.target, tier, n, ok, n, sum(1 for d in draws if d.accepted)))
    arms = [a for a in GRAPH_ARMS if recs_by_arm.get(a)]
    print("    %-5s %-9s %-26s %s" % ("point", "spend", "best-of-k [95%]",
                                     "   ".join("%-30s" % a for a in arms)))
    for k in KS:
        b = best_of_k(draws, k)
        lo, hi = best_of_k_interval(draws, k, _cell_seed(cell.target,
                                                         cell.model, k))
        field = ("%.2f" % b["field_success"]
                 if b["field_success"] is not None else "-")
        cols = ["%-30s" % "above the run's cap" if b["list_usd"] > cap_usd
                else _arm_col(frontier_point(recs_by_arm[a], b["list_usd"]))
                for a in arms]
        print("    k=%-2d%s $%.4f  %.2f [%.2f,%.2f] f%s   %s"
              % (b["k"], "*" if k == PRIMARY_K else " ", b["list_usd"],
                 b["success"], lo, hi, field, "   ".join(cols)))
    # The run's own cap: the one point where the agent was told the budget it
    # is read at, so its only point that is not a cut-off. Best-of-k there
    # would take more draws than are stored unless its spend is reached. The
    # agent was told an unsubmitted module does not count, so the perfect
    # modules it submitted are printed beside its last drafts.
    top = best_of_k(draws, KS[-1])
    print("    cap   $%.4f  %-26s   %s"
          % (cap_usd, "k=%d spends $%.4f" % (top["k"], top["list_usd"])
             if top["list_usd"] < cap_usd else "-",
             "   ".join(_arm_col(frontier_point(recs_by_arm[a], cap_usd),
                                 submitted_perfect(recs_by_arm[a]))
                        for a in arms)))
    one = recs_by_arm.get("oneshot") or []
    scored = [r for r in one if r["outcome"] not in
              (Outcome.INFRA_ERROR, Outcome.NOT_ATTEMPTED)]
    if one:
        k1 = sum(1 for r in scored if r["outcome"] == Outcome.PERFECT)
        lo, hi = wilson(k1, len(scored))
        print("    one-shot control: %d/%d perfect [%.2f,%.2f], mean $%.4f list "
              "(stored pass@1 %.2f)"
              % (k1, len(scored), lo, hi,
                 sum(r["list_usd"] for r in scored) / max(1, len(scored)),
                 ok / float(n)))
    print("    * the primary point. spend: best-of-k's mean list-priced spend "
          "per task, the cap the arms are read at; f: field-level successes")
    if recs_by_arm.get("agent"):
        print("    the agent was told a $%.2f budget; below it, its points are "
              "episodes cut off there, and the cap row is its exact point; "
              "sub: perfect modules submitted" % cap_usd)


def submitted_perfect(recs):
    """Episodes whose submitted module is perfect."""
    return sum(1 for r in recs
               if r.get("submitted") and r["outcome"] == Outcome.PERFECT)


def _arm_col(p, submitted=None):
    """One arm's cell of the frontier table."""
    return "%-30s" % (
        "%d/%d [%.2f,%.2f] f%d $%.4f%s%s" % (
            p["ok"], p["n"], p["ci"][0], p["ci"][1], p["field_ok"],
            p["list_usd"] or 0.0,
            " (%d unobs)" % p["unobserved"] if p["unobserved"] else "",
            "" if submitted is None else " sub %d" % submitted)
        if p["n"] else "no episodes observed")


# ------------------------------------------------------------ episodes
def load_target(key):
    target = H.TARGETS[key]
    pages = H.corpus(target)
    refs = {fn: target.reference(H.read(p)) for fn, p in pages}
    bad = [nm for nm, ok in H.validate_scorer(target, refs[pages[0][0]])
           if not ok]
    if bad:
        raise SystemExit("scorer broken for %s: %s; no calls made"
                         % (key, ", ".join(bad)))
    corpus = [q for _, q in H.stripped_corpus(target, pages)]
    win, _frac, _at = H.window(H.read(pages[0][1]), SYNTH_WINDOW)
    user = ("Portal page excerpt (one page of the result grid, stripped of "
            "scripts, styles and non-structural attributes):\n\n" + win)
    return target, corpus, refs, user


def _name(cell, arm, episode):
    return "%s_%s_%s_e%02d" % (cell.target, infer.short_model(cell.model),
                               arm, episode)


def _finish(summary, target, corpus, refs, stem):
    """Score every draft, and the episode's own module, into the record."""
    code = summary.pop("code")
    drafts = summary.pop("drafts")
    scores = score_drafts(target, drafts, corpus, refs, stem)
    if summary["stop"] == "infra_error":
        final = {"outcome": Outcome.INFRA_ERROR}
    elif summary["stop"] == "refused":
        final = {"outcome": Outcome.NOT_ATTEMPTED}
    elif code:
        # Every module an episode hands back is one of its drafts; scored
        # directly if a path ever breaks that.
        final = scores.get(T.digest(code)) or score_code(
            target, code, corpus, refs, "%s_final.py" % stem)
    else:
        final = {"outcome": Outcome.NO_CODE, "field_perfect": False}
    return dict(summary, **final, draft_scores={
        h: {"outcome": s["outcome"], "field_perfect": s["field_perfect"]}
        for h, s in scores.items()})


def run_episode(client, args, arm, cell, loaded, limits, episode, saver):
    """Run (or resume) one agent or scripted episode, score it and return
    its record."""
    target, corpus, refs, user = loaded
    name = _name(cell, arm, episode)
    ep = G.Episode(
        client=client, model=cell.model, system=H.SYNTH_SYSTEM, user=user,
        workspace=T.Workspace(corpus, FIELDS, os.path.join(
            OUT, "work", args.run_id, name)),
        run_id=args.run_id, episode=episode, call_class=arm,
        tag="%s/%s/%s/e%02d" % (args.run_id, arm, cell.target, episode),
        limits=limits)
    t0 = time.time()
    summary = G.run(ep, arm, checkpointer=saver, project=args.project)
    seconds = round(time.time() - t0, 1)
    rec = _finish(summary, target, corpus, refs,
                  os.path.join(OUT, "synth", args.run_id, name))
    return dict(rec, run_id=args.run_id, arm=arm, target=cell.target,
                model=cell.model, episode=episode, cap_usd=limits.usd,
                limit_turns=limits.turns, seconds=seconds,
                project=args.project)


def run_oneshot(client, args, cell, loaded, episode):
    """One fresh one-shot draw: the v2 request, re-drawn once at the
    model's larger cap when cut off, as in the v2 run."""
    target, corpus, refs, user = loaded
    cap, redraw = infer.output_cap(cell.model), infer.redraw_cap(cell.model)
    tag = "%s/oneshot/%s/e%02d" % (args.run_id, cell.target, episode)
    traj, usd, list_usd, stop, error, turn = [], 0.0, 0.0, None, None, None
    t0 = time.time()
    for max_tokens in (cap, redraw):
        try:
            turn = client.converse(
                cell.model, H.SYNTH_SYSTEM,
                [{"role": "user", "content": user}], [],
                max_tokens=max_tokens, call_class="oneshot",
                run_id=args.run_id, episode=episode,
                tag="%s/t%02d" % (tag, len(traj)))
        except infer.TransientError as e:
            stop, error = "infra_error", str(e)[:300]
            break
        except infer.Refused as e:
            stop, error = "refused", str(e)[:300]
            break
        c = turn.completion
        usd, list_usd = usd + turn.purchase_usd, list_usd + turn.list_usd
        traj.append({"turn": len(traj) + 1, "usd": round(usd, 6),
                     "list_usd": round(list_usd, 6), "host": c.host,
                     "input_tokens": c.usage.input_tokens,
                     "cache_read_input_tokens": c.usage.cache_read_input_tokens,
                     "output_tokens": c.usage.output_tokens,
                     "truncated": c.truncated, "draft": None})
        if not (c.truncated and redraw > max_tokens):
            break
    code = (sandbox.extract_block(turn.completion.text, sandbox.CODEBLOCK,
                                  "def extract(")
            if turn is not None and stop is None else "")
    drafts = {}
    if code:
        drafts[T.digest(code)] = code
        traj[-1]["draft"] = T.digest(code)
    summary = {"stop": stop or "answered", "error": error, "turns": len(traj),
               "usd": round(usd, 6), "list_usd": round(list_usd, 6),
               "trajectory": traj, "drafts": drafts, "code": code,
               "submitted": bool(code), "checked_before_submit": None,
               "accepted_at_submit": None, "nudges": 0, "tool_calls": 0,
               "tool_errors": 0, "checks": 0, "pages_read": 0}
    rec = _finish(summary, target, corpus, refs, os.path.join(
        OUT, "synth", args.run_id, _name(cell, "oneshot", episode)))
    return dict(rec, run_id=args.run_id, arm="oneshot", target=cell.target,
                model=cell.model, episode=episode, cap_usd=None,
                limit_turns=None, seconds=round(time.time() - t0, 1),
                project=args.project)


def save_episode(key, rec):
    def merge(cur):
        cur.setdefault("episodes", {})[key] = rec
        return cur
    fileio.update_json(EPISODES, merge, default={"episodes": {}})


def done_episodes():
    if not os.path.exists(EPISODES):
        return {}
    return fileio.read_json(EPISODES).get("episodes", {})


# ---------------------------------------------------------------- main
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-id", required=True,
                    help="names the run; part of every cache key, so "
                         "responses never replay across runs")
    ap.add_argument("--cells", required=True,
                    help="target:model:episodes, comma separated; the "
                         "episodes are per arm")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--run", action="store_true",
                    help="make model calls. Without this nothing is sent.")
    ap.add_argument("--max-spend", type=float, default=1.00)
    ap.add_argument("--cap-usd", type=float, default=G.Limits.usd,
                    help="each agent or scripted episode's list-priced cap")
    ap.add_argument("--turns", type=int, default=G.Limits.turns)
    ap.add_argument("--eval", action="store_true",
                    help="a pre-registered run: traces go to %s and the run "
                         "id must start %r" % (EVAL_PROJECT, EVAL_PREFIX))
    ap.add_argument("--no-trace", action="store_true")
    ap.add_argument("--key-file", default=None)
    ap.add_argument("--openrouter-key-file", default=None)
    args = ap.parse_args(argv)
    if args.eval != args.run_id.startswith(EVAL_PREFIX):
        ap.error("--eval and a run id starting %r go together"
                 % EVAL_PREFIX)
    args.project = EVAL_PROJECT if args.eval else DEV_PROJECT
    args.arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if not args.arms or set(args.arms) - set(ARMS):
        ap.error("--arms takes %s" % ", ".join(ARMS))
    try:
        args.cells = [Cell.parse(e) for e in args.cells.split(",")]
    except (ValueError, infer.Refused) as e:
        ap.error(str(e))
    return args


def worst_turn(model, loaded, max_tokens):
    """The most one turn can cost at list price, with the first request's
    input: a later turn's input is larger, so this is a floor, not a bound.
    The per-process ceiling (`infer.Budget`) holds each call to its own
    worst case."""
    return infer.estimate(model, len(loaded[3]) // 3, max_tokens)


def worst_episode(arm, model, loaded, cap_usd):
    if arm == "oneshot":
        return (worst_turn(model, loaded, infer.output_cap(model))
                + worst_turn(model, loaded, infer.redraw_cap(model)))
    return cap_usd + worst_turn(model, loaded, infer.output_cap(model))


def main(argv=None):
    args = parse_args(argv)
    loaded, worst = {}, 0.0
    stored = stored_draws(args.cells)
    print("run %s, arms %s, cap $%.4f list-priced per episode, traces to %s"
          % (args.run_id, ",".join(args.arms), args.cap_usd, args.project))
    for c in args.cells:
        if c.target not in loaded:
            loaded[c.target] = load_target(c.target)
        per = {a: worst_episode(a, c.model, loaded[c.target], args.cap_usd)
               for a in args.arms}
        worst += sum(per.values()) * c.episodes
        print("  %-13s %-32s %2d episodes per arm; worst per episode %s"
              % (c.target, c.model, c.episodes,
                 ", ".join("%s $%.4f" % kv for kv in per.items())))
        hosts = host_prices(c.model)
        print("    billed / list price by host, v2 draws: %s" % (", ".join(
            "%s %.2f (n=%d)" % (h, r, n) for h, (n, r) in sorted(
                hosts.items(), key=lambda x: -x[1][0])) or "none"))
        top = best_of_k(stored[(c.target, c.model)], max(KS))
        if top["list_usd"] > args.cap_usd:
            print("    best-of-%d spends $%.4f, above the cap: that point "
                  "will not be observed" % (top["k"], top["list_usd"]))
    print("  worst case $%.2f against --max-spend $%.2f"
          % (worst, args.max_spend))
    done = done_episodes()
    if not args.run:
        report(args, stored, done)
        print("\ndry run: nothing sent. Add --run to spend.")
        return 0
    if worst > args.max_spend:
        raise SystemExit("worst case over --max-spend; nothing sent")

    client = infer.Client(ROOT, args.max_spend, dry_run=False,
                          key_file=args.key_file,
                          openrouter_key_file=args.openrouter_key_file)
    for m in sorted({c.model for c in args.cells}):
        if not client.key_for(m):
            raise SystemExit("no key for %s. Nothing has been sent." % m)
    if not args.no_trace:
        print("tracing: %s" % ("on" if G.enable_tracing() else
                               "off (no LangSmith key)"))
    os.makedirs(OUT, exist_ok=True)
    with fileio.run_lock(os.path.join(OUT, "%s.run" % args.run_id),
                         "run %s" % args.run_id), \
            SqliteSaver.from_conn_string(CHECKPOINTS) as saver:
        for c in args.cells:
            for arm in args.arms:
                limits = G.Limits(turns=args.turns, usd=args.cap_usd,
                                  max_tokens=infer.output_cap(c.model))
                for e in range(c.episodes):
                    key = episode_key(args.run_id, arm, c.target, c.model, e)
                    if key in done:
                        continue
                    if arm == "oneshot":
                        rec = run_oneshot(client, args, c, loaded[c.target], e)
                    else:
                        rec = run_episode(client, args, arm, c,
                                          loaded[c.target], limits, e, saver)
                    save_episode(key, rec)
                    done[key] = rec
                    print("    %-8s %-12s e%02d  %-12s turns %2d  $%.4f list "
                          "$%.4f billed  stop %-12s checked %s  %.0f s"
                          % (arm, c.target, e, rec["outcome"], rec["turns"],
                             rec["list_usd"], rec["usd"], rec["stop"],
                             rec["checked_before_submit"], rec["seconds"]))
                    if rec["outcome"] == Outcome.NOT_ATTEMPTED:
                        print("    STOPPED: %s" % rec["error"])
                        report(args, stored, done)
                        return 1
    report(args, stored, done)
    print("spent $%.4f this session" % client.budget.spent)
    return 0


def report(args, stored, done):
    """The frontier of every cell, from what this run id has on record."""
    for c in args.cells:
        by_arm = collections.defaultdict(list)
        for e in range(c.episodes):
            for arm in args.arms:
                rec = done.get(episode_key(args.run_id, arm, c.target,
                                           c.model, e))
                if rec is not None:
                    by_arm[arm].append(rec)
        print_frontier(c, stored[(c.target, c.model)], by_arm, args.cap_usd)


if __name__ == "__main__":
    sys.exit(main())
