# -*- coding: utf-8 -*-
"""Run the portal population run's paid arms on its 16 test portals and
score them: stages 2-5 of the pre-registration
(docs/evidence/2026-10-04-portal-population-preregistration.md, "Arms, the
check, the loop and the stages").

    python scripts/population_eval.py --run-id eval-pop-1 --stage 2
    python scripts/population_eval.py --run-id eval-pop-1 --stage 2 --run --registered <OSF link>
    python scripts/population_eval.py --run-id eval-pop-1 --report

Without `--run` nothing is sent: each portal's check and excerpt, and the
stage's cells, expected spend and limit, are printed. `--run` needs
`--registered`, the pre-registration's OSF link, which goes into every
record.

**Portals** come from the references (`data/population/reference/`): each
page's rows, keyed by the contract's fields, and the fields the portal has a
column for, which are the only ones scored (`H.score` with identity roles).
The arms see the v2 request: the frozen synthesis prompt and the v2 excerpt
of the portal's first saved page. Every module is run on every stripped page
and scored as a v2 draw is (`agent_eval.score_code`).

**The check** is v2's verifier with the generalized record count
(`verify.expected_records`), counted once per portal on its stripped pages.
Every module an arm hands back is checked after the arm, on the same
workspace the loop and the agent use, so a one-shot draw's verdict is the
one the loop would have seen. A trusted extractor is one the check accepts
that is perfect on every page; for the loop and the agent it must also be
the submitted module.

**Stages.** 2: the cheap models, 10 one-shot draws a portal. 3: the strong
models, 5 draws a portal, then 5 more where the first 5 disagree. 4: the
scripted repair loop, 5 episodes at a $0.15 list cap, for each cheap cell
with room (stage 2's pass@1 below 1). 5: the agent, 5 episodes told the
cell's B5 (best-of-5's expected list-priced spend from its stage-2 draws).
Models run one after another, so a stage that stops at its limit loses its
last model's cells first.

**Spend.** A stage's limit is billed dollars, as `infer.Budget` counts
them, and a stage resumed after a stop gets its limit less what its records
already spent. A call the limit would refuse stops the stage, and that draw
is not saved. Stage 3 drops its extension draws, and stages 4 and 5 drop to
3 episodes a cell, if the spend after the first model projects past the
limit; each decision is saved the first time it is made.

**Where things go** (all under `data/population/eval/`, gitignored):
`episodes.json`, one record per draw or episode keyed
`run|arm|pNNNN|model|eNN`, with the stage decisions; scored drafts under
`synth/`; workspaces under `work/`; LangGraph checkpoints in
`checkpoints.sqlite`. Each portal's calls use the run id `<run>-pNNNN`, so
the response cache and the checkpoints never cross portals. Traces go to
`buildscope-agent-eval` for a run id starting `eval-`.
"""
import argparse
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from langgraph.checkpoint.sqlite import SqliteSaver           # noqa: E402
from permits import arms, fileio, infer                       # noqa: E402
from permits import harness as H                              # noqa: E402
from permits.agent import graph as G                          # noqa: E402
from permits.agent import tools as T                          # noqa: E402
from permits.agent import verify                              # noqa: E402
from permits.cells import Outcome                             # noqa: E402

POP = os.path.join(ROOT, "data", "population")
REFS = os.path.join(POP, "reference")
PAGES = os.path.join(POP, "corpus", "pages")
OUT = os.path.join(POP, "eval")
EPISODES = os.path.join(OUT, "episodes.json")
CHECKPOINTS = os.path.join(OUT, "checkpoints.sqlite")

CHEAP = ("openai/gpt-oss-120b", "google/gemini-3.5-flash-lite",
         "deepseek/deepseek-v4-flash", "openai/gpt-6-luna",
         "xiaomi/mimo-v2.6-flash")
STRONG = ("claude-opus-5-5", "google/gemini-3.8-flash")
CHEAP_DRAWS = 10
STRONG_DRAWS = 5
STRONG_MORE = 5
EPISODES_PER_CELL = 5
EPISODES_CUT = 3
LOOP_CAP = 0.15
TURNS = 30
STAGES = {2: ("oneshot", CHEAP, 8.0), 3: ("oneshot", STRONG, 35.0),
          4: ("scripted", CHEAP, 12.0), 5: ("agent", CHEAP, 12.0)}
# The pre-registration's expected spend: the v2 cost per draw times 1.3.
PAD = 1.3
# Where the check's count misses the reference (measured after it was
# frozen): Boise and Philadelphia. Every result is also given without them.
CHECK_MISSES = (104, 319)
SCORED = (Outcome.PERFECT, Outcome.IMPERFECT, Outcome.RAISED,
          Outcome.EXEC_ERROR, Outcome.REFUSED, Outcome.NO_CODE)


class StageStopped(Exception):
    """The stage's limit refused a call."""


# ------------------------------------------------------------ portals
class Portal:
    """One test portal: its reference, stripped pages, excerpt and check."""

    def __init__(self, path):
        d = fileio.read_json(path)
        self.order, self.place = int(d["order"]), d["place"]
        self.product, self.source = d["product"], d["source"]
        self.key = "p%04d" % self.order
        self.target = H.Target(self.key, self.key, self.product, None,
                               {f: f for f in sorted(d["fields"])},
                               self.place, split="test")
        raw = [(p["file"], os.path.join(PAGES, p["file"])) for p in d["pages"]]
        self.corpus = [q for _, q in H.stripped_corpus(self.target, raw)]
        self.refs = {p["file"]: p["rows"] for p in d["pages"]}
        bad = [nm for nm, ok in H.validate_scorer(self.target,
                                                  d["pages"][0]["rows"])
               if not ok]
        if bad:
            raise SystemExit("scorer broken for %s: %s; no calls made"
                             % (self.key, ", ".join(bad)))
        self.expected = verify.expected_records(
            [H.read(q) for q in self.corpus])
        self.window, _frac, _at = H.window(H.read(raw[0][1]), arms.SYNTH_WINDOW)
        self.user = ("Portal page excerpt (one page of the result grid, "
                     "stripped of scripts, styles and non-structural "
                     "attributes):\n\n" + self.window)
        self._ws = None

    @property
    def loaded(self):
        return self.target, self.corpus, self.refs, self.user

    def counts(self):
        """Records per page in the reference."""
        return [len(self.refs[os.path.basename(q)]) for q in self.corpus]

    def in_window(self):
        """Reference records of the first page whose permit number is in
        the excerpt: an excerpt with none shows the model no record."""
        rows = self.refs[os.path.basename(self.corpus[0])]
        return sum(1 for r in rows if r["native_id"] in self.window), len(rows)

    def check(self, path):
        """The check's verdict on a module on disk: (accepted, what failed)."""
        if self._ws is None:
            self._ws = T.Workspace(self.corpus,
                                   os.path.join(OUT, "work", "check", self.key),
                                   expected=list(self.expected))
        res = self._ws.run(H.read(path))
        failed = sorted(res.failed)
        if res.audit:
            failed.append("audit")
        if res.error:
            failed.append("error")
        return res.accepted, failed


def load_portals(orders=None):
    out = []
    for f in sorted(glob.glob(os.path.join(REFS, "ref_*.json"))):
        p = Portal(f)
        if orders is None or p.order in orders:
            out.append(p)
    return out


# ------------------------------------------------------------ records
def portal_run(run_id, portal):
    return "%s-%s" % (run_id, portal.key)


def record_key(run_id, arm, portal, model, episode):
    return arms.episode_key(run_id, arm, portal.key, model, episode)


def load_state():
    if not os.path.exists(EPISODES):
        return {"episodes": {}, "decisions": {}}
    d = fileio.read_json(EPISODES)
    d.setdefault("episodes", {})
    d.setdefault("decisions", {})
    return d


def save_record(key, rec):
    def merge(cur):
        cur.setdefault("episodes", {})[key] = rec
        return cur
    fileio.update_json(EPISODES, merge, default={"episodes": {}})


def decide(state, run_id, stage, name, value):
    """A stage decision, made once and then read back on every resume."""
    k = "%s|%d|%s" % (run_id, stage, name)
    if k in state["decisions"]:
        return state["decisions"][k]

    def merge(cur):
        cur.setdefault("decisions", {}).setdefault(k, value)
        return cur
    state["decisions"] = fileio.update_json(
        EPISODES, merge, default={"episodes": {}})["decisions"]
    return state["decisions"][k]


def records(state, run_id, stage=None, model=None, portal=None):
    return [r for r in state["episodes"].values()
            if r["run_id"] == run_id
            and (stage is None or r["stage"] == stage)
            and (model is None or r["model"] == model)
            and (portal is None or r["order"] == portal.order)
            and r["outcome"] in SCORED]


def spent(recs):
    return sum(r["usd"] for r in recs)


def cell_draws(state, run_id, portal, model, stage=2):
    """A cell's scored one-shot draws, as best-of-k reads them."""
    return [arms.Stored(r["episode"], r["list_usd"], r["usd"], r["accepted"],
                      r["outcome"] == Outcome.PERFECT,
                      bool(r.get("field_perfect")))
            for r in sorted(records(state, run_id, stage, model, portal),
                            key=lambda r: r["episode"])]


def pass_at_1(draws):
    return sum(1 for d in draws if d.perfect) / float(len(draws))


def b5(draws):
    return arms.best_of_k(draws, arms.PRIMARY_K)["list_usd"]


def disagree(draws):
    """The first draws neither all pass nor all fail."""
    return 0 < sum(1 for d in draws if d.perfect) < len(draws)


# ------------------------------------------------------------ running
def run_one(client, args, stage, portal, model, episode, saver, cap):
    arm = STAGES[stage][0]
    cell = arms.Cell(portal.key, model, 1)
    run = portal_run(args.run_id, portal)
    if arm == "oneshot":
        rec = arms.run_oneshot(client, run, args.project, cell,
                               portal.loaded, episode, OUT)
    else:
        limits = G.Limits(turns=TURNS, usd=cap,
                          max_tokens=infer.output_cap(model))
        rec = arms.run_episode(client, run, args.project, arm, cell,
                               portal.loaded, limits, episode, saver, OUT,
                               expected=portal.expected)
    accepted, failed = (portal.check(rec["source"]) if rec.get("source")
                        else (False, []))
    trusted = accepted and rec["outcome"] == Outcome.PERFECT and (
        arm == "oneshot" or bool(rec.get("submitted")))
    return dict(rec, run_id=args.run_id, cache_run=run, stage=stage,
                order=portal.order, product=portal.product,
                accepted=accepted, check_failed=failed, trusted=trusted,
                registered=args.registered)


def run_cell(client, args, state, stage, portal, model, episodes, saver,
             cap=None):
    arm = STAGES[stage][0]
    for e in episodes:
        key = record_key(args.run_id, arm, portal, model, e)
        old = state["episodes"].get(key)
        if old is not None and old["outcome"] in SCORED:
            continue
        rec = run_one(client, args, stage, portal, model, e, saver, cap)
        if rec["outcome"] == Outcome.NOT_ATTEMPTED:
            raise StageStopped(rec.get("error") or "refused")
        save_record(key, rec)
        state["episodes"][key] = rec
        print("    %-8s %-6s %-26s e%02d  %-11s %s  turns %2d  $%.4f list "
              "$%.4f billed  %.0f s"
              % (arm, portal.key, infer.short_model(model), e, rec["outcome"],
                 "trusted " if rec["trusted"] else
                 "accepted" if rec["accepted"] else "rejected",
                 rec["turns"], rec["list_usd"], rec["usd"], rec["seconds"]))


def room(state, args, portals, model):
    """The cells with room for one cheap model: (portal, stage-2 draws)."""
    out = []
    for p in portals:
        draws = cell_draws(state, args.run_id, p, model)
        if len(draws) < CHEAP_DRAWS:
            raise SystemExit("%s x %s has %d of %d stage-2 draws: finish "
                             "stage 2 first" % (p.key, model, len(draws),
                                                CHEAP_DRAWS))
        if pass_at_1(draws) < 1:
            out.append((p, draws))
    return out


def run_stage(client, args, state, portals, saver):
    stage, limit = args.stage, args.max_spend
    arm, models, _ = STAGES[stage]
    if stage == 2:
        for m in models:
            for p in portals:
                run_cell(client, args, state, 2, p, m, range(CHEAP_DRAWS),
                         saver)
        return
    if stage == 3:
        # `--models` runs part of the stage (Opus bills to Anthropic, Gemini
        # through OpenRouter). The extension decision is made once the first
        # model's base draws are in, and nothing is extended before that.
        run_models = [m for m in models if m in (args.models or models)]
        more = None
        for m in run_models:
            for p in portals:
                run_cell(client, args, state, 3, p, m, range(STRONG_DRAWS),
                         saver)
            if m == models[0]:
                first = records(state, args.run_id, 3, m)
                ext = sum(1 for p in portals if disagree(
                    cell_draws(state, args.run_id, p, m, 3)))
                proj = (spent(first) * len(models)
                        * (1 + ext / float(len(portals))))
                more = decide(state, args.run_id, 3, "extend", proj <= limit)
                print("  stage 3 after %s: $%.2f billed, projected $%.2f "
                      "against $%.2f: extension draws %s"
                      % (infer.short_model(m), spent(first), proj, limit,
                         "kept" if more else "dropped"))
        if more is None:
            more = state["decisions"].get("%s|3|extend" % args.run_id)
        if not more:
            return
        for m in run_models:
            for p in portals:
                first5 = [d for d in cell_draws(state, args.run_id, p, m, 3)
                          if d.draw < STRONG_DRAWS]
                if disagree(first5):
                    run_cell(client, args, state, 3, p, m,
                             range(STRONG_DRAWS, STRONG_DRAWS + STRONG_MORE),
                             saver)
        return
    # Stages 4 and 5: the cheap cells with room.
    cells = [(m, room(state, args, portals, m)) for m in models]
    total = sum(len(c) for _, c in cells)
    n = EPISODES_PER_CELL
    first = None
    for m, cs in cells:
        for p, draws in cs:
            cap = LOOP_CAP if arm == "scripted" else b5(draws)
            run_cell(client, args, state, stage, p, m, range(n), saver, cap)
        if cs and first is None:
            first = m
            got = records(state, args.run_id, stage, m)
            proj = spent(got) / len(cs) * total
            full = decide(state, args.run_id, stage, "full", proj <= limit)
            n = EPISODES_PER_CELL if full else EPISODES_CUT
            print("  stage %d after %s: $%.2f billed, projected $%.2f "
                  "against $%.2f: %d episodes a cell from here"
                  % (stage, infer.short_model(m), spent(got), proj, limit, n))


# ------------------------------------------------------------ the plan
def v2_cost(model):
    """A model's mean billed cost per v2 draw, from the ledger."""
    xs = [r.usd for r in infer.Ledger(arms.LEDGER).rows()
          if r.model == model and r.protocol == "v2" and r.ok
          and r.call_class not in arms.ARMS]
    return sum(xs) / len(xs) if xs else None


def print_portals(portals):
    print("  %-6s %-24s %-18s %-7s %-17s %-17s %s"
          % ("portal", "place", "product", "key", "reference", "check",
             "excerpt"))
    for p in portals:
        got, of = p.in_window()
        ok = p.expected == p.counts()
        print("  %-6s %-24s %-18s %-7s %-17s %-17s %d of %d page-1 records%s"
              % (p.key, p.place[:24], p.product[:18], p.source,
                 p.counts(), "%s%s" % (p.expected, "" if ok else " MISS"),
                 got, of, "" if got else "  NONE"))


def print_plan(args, state, portals):
    stage = args.stage
    arm, models, limit = STAGES[stage]
    prior = spent(records(state, args.run_id, stage))
    print("\nstage %d (%s), limit $%.2f billed, $%.2f spent by this run id"
          % (stage, arm, limit, prior))
    total = 0.0
    for m in models:
        per = v2_cost(m)
        if stage in (2, 3):
            n = (CHEAP_DRAWS if stage == 2 else STRONG_DRAWS) * len(portals)
            done = len(records(state, args.run_id, stage, m))
            est = per * PAD * max(0, n - done) if per else None
            print("  %-28s %3d draws (%d done), v2 $%s a draw, expected "
                  "$%s%s" % (m, n, done, "%.4f" % per if per else "?",
                             "%.2f" % est if est is not None else "?",
                             " before any extension" if stage == 3 else ""))
        else:
            try:
                cs = room(state, args, portals, m)
            except SystemExit as e:
                print("  %-28s %s" % (m, e))
                continue
            caps = [LOOP_CAP if arm == "scripted" else b5(d) for _, d in cs]
            hosts = arms.host_prices(m)
            ratio = (sum(n * r for n, r in hosts.values())
                     / sum(n for n, _ in hosts.values())) if hosts else 1.0
            est = sum(caps) * EPISODES_PER_CELL * ratio
            print("  %-28s %2d cells with room, caps $%.4f-%.4f list, at "
                  "most $%.2f billed at v2's billed/list %.2f"
                  % (m, len(cs), min(caps or [0]), max(caps or [0]), est,
                     ratio))
        total += est or 0.0
    print("  expected about $%.2f billed against the $%.2f limit"
          % (total, limit))


# ------------------------------------------------------------ the report
def report(args, state, portals):
    """Per arm and model: pass@1, the check, trusted rate and cost per
    trusted extractor, over all 16 portals and without the check's misses.
    Unweighted over portals; the weighted views are the analysis's."""
    for label, ps in (("all portals", portals),
                      ("without Boise and Philadelphia",
                       [p for p in portals if p.order not in CHECK_MISSES])):
        print("\n%s (%d)" % (label, len(ps)))
        print("  %-5s %-8s %-26s %5s %7s %8s %8s %9s %12s"
              % ("stage", "arm", "model", "draws", "pass@1", "accepted",
                 "trusted", "billed", "per trusted"))
        for stage, (arm, models, _) in sorted(STAGES.items()):
            for m in models:
                per = [(p, records(state, args.run_id, stage, m, p))
                       for p in ps]
                per = [(p, rs) for p, rs in per if rs]
                if not per:
                    continue
                n = sum(len(rs) for _, rs in per)
                p1 = sum(sum(r["outcome"] == Outcome.PERFECT for r in rs)
                         / float(len(rs)) for _, rs in per) / len(per)
                acc = sum(r["accepted"] for _, rs in per for r in rs) / float(n)
                tr = sum(r["trusted"] for _, rs in per for r in rs) / float(n)
                if arm == "oneshot":
                    bs = [arms.best_of_k(cell_draws(state, args.run_id, p, m,
                                                  stage), len(rs))
                          for p, rs in per]
                    cost, wins = sum(b["usd"] for b in bs), sum(
                        b["success"] for b in bs)
                else:
                    cost = sum(spent(rs) for _, rs in per) / n * len(per)
                    wins = sum(sum(r["trusted"] for r in rs) / float(len(rs))
                               for _, rs in per)
                print("  %-5d %-8s %-26s %5d %7.2f %8.2f %8.2f %9.4f %12s"
                      % (stage, arm, infer.short_model(m), n, p1, acc, tr,
                         sum(spent(rs) for _, rs in per),
                         "$%.4f" % (cost / wins) if wins else "none"))
    print("\n  pass@1: mean over portals of each portal's perfect share. "
          "per trusted: one-shot draws until the check accepts (best-of-k "
          "over the stored draws), pooled; episodes, mean spend over the "
          "trusted rate, pooled.")


# ---------------------------------------------------------------- main
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--stage", type=int, choices=sorted(STAGES))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--portals", default=None,
                    help="office orders, comma separated; default all 16")
    ap.add_argument("--run", action="store_true",
                    help="make model calls. Without this nothing is sent.")
    ap.add_argument("--registered", default=None,
                    help="the pre-registration's OSF link; needed with --run")
    ap.add_argument("--max-spend", type=float, default=None,
                    help="billed limit; the stage's own by default")
    ap.add_argument("--models", default=None,
                    help="stage 3 only: the strong models to run now, comma "
                         "separated, in the stage's order")
    ap.add_argument("--no-trace", action="store_true")
    args = ap.parse_args(argv)
    if not args.report and args.stage is None:
        ap.error("give --stage or --report")
    if args.run and not args.registered:
        ap.error("--run spends on the test portals: give --registered, the "
                 "pre-registration's OSF link")
    if args.stage is not None and args.max_spend is None:
        args.max_spend = STAGES[args.stage][2]
    args.project = (arms.EVAL_PROJECT if args.run_id.startswith(arms.EVAL_PREFIX)
                    else arms.DEV_PROJECT)
    args.portals = ({int(x) for x in args.portals.split(",")}
                    if args.portals else None)
    if args.models:
        args.models = [m.strip() for m in args.models.split(",")]
        if args.stage != 3 or set(args.models) - set(STRONG):
            ap.error("--models is for stage 3 and takes %s"
                     % ", ".join(STRONG))
    return args


def main(argv=None):
    args = parse_args(argv)
    portals = load_portals(args.portals)
    state = load_state()
    print("run %s, %d portals, traces to %s"
          % (args.run_id, len(portals), args.project))
    if args.report:
        report(args, state, portals)
        return 0
    print_portals(portals)
    print_plan(args, state, portals)
    if not args.run:
        print("\ndry run: nothing sent. Add --run to spend.")
        return 0
    prior = spent(records(state, args.run_id, args.stage))
    client = infer.Client(ROOT, max(0.0, args.max_spend - prior))
    for m in args.models or STAGES[args.stage][1]:
        if not client.key_for(m):
            raise SystemExit("no key for %s. Nothing has been sent." % m)
    if not args.no_trace:
        print("tracing: %s" % ("on" if G.enable_tracing() else
                               "off (no LangSmith key)"))
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    code = 0
    with fileio.run_lock(os.path.join(OUT, "%s.run" % args.run_id),
                         "run %s" % args.run_id), \
            SqliteSaver.from_conn_string(CHECKPOINTS) as saver:
        try:
            run_stage(client, args, state, portals, saver)
        except StageStopped as e:
            print("  STAGE STOPPED at its limit: %s" % e)
            code = 1
    print("stage %d: $%.4f billed this session, $%.4f by this run id, "
          "%.0f min" % (args.stage, client.budget.spent,
                        spent(records(state, args.run_id, args.stage)),
                        (time.time() - t0) / 60))
    report(args, state, portals)
    return code


if __name__ == "__main__":
    sys.exit(main())
