# -*- coding: utf-8 -*-
"""Run and score the arms that write extractors: fresh one-shot draws, and
the scripted repair loop's and the agent's episodes (`permits/agent/graph.py`),
with best-of-k read exactly from scored draws.

Shared by `scripts/agent_eval.py` (the agent run, on the v2 targets) and
`scripts/population_eval.py` (the portal population run, on its test
portals). Moved here from `scripts/agent_eval.py` on 2026-10-27, unchanged
but for the output directory, which the caller now passes in.

**Scoring** happens after the episode and outside it: each draft goes
through the v2 audit, runner and scorer (`harness.score`) against the
reference rows of every page, so an outcome means what a v2 draw's does,
with field agreement beside it. `permits/agent/` never sees the references
or the scorer.
"""
import collections
import io
import math
import os
import statistics
import time
from dataclasses import dataclass

from permits import harness as H
from permits import infer, sandbox
from permits.agent import graph as G
from permits.agent import tools as T
from permits.cells import Outcome

LEDGER = os.path.join(H.OUT, "ledger.jsonl")
ARMS = ("agent", "scripted", "oneshot")
DEV_PROJECT = "buildscope-agent-dev"
EVAL_PROJECT = "buildscope-agent-eval"
EVAL_PREFIX = "eval-"
# The one-shot request's excerpt size: `--synth-window`'s default in
# conformance.py, which every v2 draw was bought with.
SYNTH_WINDOW = 24000
# Best-of-5 is the pre-registered comparison point.
PRIMARY_K = 5


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
    """One scored draw, as best-of-k sees it."""
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


def row_usage(r):
    return infer.Usage(r.input_tokens, r.output_tokens,
                       r.cache_read_input_tokens or 0,
                       r.cache_creation_input_tokens or 0)


def host_prices(model):
    """Per host, the model's v2 draws: count and the median ratio of billed
    to list-priced cost. The arms' own calls are left out: a multi-turn
    episode is mostly cached input, so its ratio is not a draw's."""
    ratios = collections.defaultdict(list)
    for r in infer.Ledger(LEDGER).rows():
        if (r.model == model and r.protocol == "v2" and r.ok
                and r.call_class not in ARMS):
            lst = infer.list_cost(model, row_usage(r))
            if lst:
                ratios[r.host or "?"].append(r.usd / lst)
    return {h: (len(x), statistics.median(x)) for h, x in ratios.items()}


# ------------------------------------------------------------ scoring
def score_code(target, code, corpus, refs, path):
    """Score one module as a v2 draw is scored (`_run_variance` in
    scripts/conformance.py): the audit, then every page, then agreement with
    the reference. Returns the outcome and the figures beside it. The same
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


def finish(summary, target, corpus, refs, stem):
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


# ------------------------------------------------------------ episodes
def episode_name(cell, arm, episode):
    return "%s_%s_%s_e%02d" % (cell.target, infer.short_model(cell.model),
                               arm, episode)


def run_episode(client, run_id, project, arm, cell, loaded, limits, episode,
                saver, out, expected=None):
    """Run (or resume) one agent or scripted episode, score it and return
    its record. Drafts go under `out`/synth, the workspace under `out`/work.
    `expected` is the check's records per page; by default the workspace
    counts grid rows (`verify.expected_rows`)."""
    target, corpus, refs, user = loaded
    name = episode_name(cell, arm, episode)
    ep = G.Episode(
        client=client, model=cell.model, system=H.SYNTH_SYSTEM, user=user,
        workspace=T.Workspace(corpus, os.path.join(
            out, "work", run_id, name), expected=list(expected or [])),
        run_id=run_id, episode=episode, call_class=arm,
        tag="%s/%s/%s/e%02d" % (run_id, arm, cell.target, episode),
        limits=limits)
    t0 = time.time()
    summary = G.run(ep, arm, checkpointer=saver, project=project)
    seconds = round(time.time() - t0, 1)
    rec = finish(summary, target, corpus, refs,
                 os.path.join(out, "synth", run_id, name))
    return dict(rec, run_id=run_id, arm=arm, target=cell.target,
                model=cell.model, episode=episode, cap_usd=limits.usd,
                limit_turns=limits.turns, seconds=seconds, project=project)


def run_oneshot(client, run_id, project, cell, loaded, episode, out):
    """One fresh one-shot draw: the v2 request, re-drawn once at the
    model's larger cap when cut off, as in the v2 run."""
    target, corpus, refs, user = loaded
    cap, redraw = infer.output_cap(cell.model), infer.redraw_cap(cell.model)
    tag = "%s/oneshot/%s/e%02d" % (run_id, cell.target, episode)
    traj, usd, list_usd, stop, error, turn = [], 0.0, 0.0, None, None, None
    t0 = time.time()
    for max_tokens in (cap, redraw):
        try:
            turn = client.converse(
                cell.model, H.SYNTH_SYSTEM,
                [{"role": "user", "content": user}], [],
                max_tokens=max_tokens, call_class="oneshot",
                run_id=run_id, episode=episode,
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
    rec = finish(summary, target, corpus, refs, os.path.join(
        out, "synth", run_id, episode_name(cell, "oneshot", episode)))
    return dict(rec, run_id=run_id, arm="oneshot", target=cell.target,
                model=cell.model, episode=episode, cap_usd=None,
                limit_turns=None, seconds=round(time.time() - t0, 1),
                project=project)
