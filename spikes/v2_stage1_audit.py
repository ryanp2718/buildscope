# -*- coding: utf-8 -*-
"""Stage 1 of the protocol v2 run, checked from the ledger before its
results are used, and stages 2 and 3 re-projected from what it measured.

Offline. Reads:

    data/infer/ledger.jsonl
    data/infer/variance.json

    python spikes/v2_stage1_audit.py

Prints; writes nothing. Sections:

  1. Successful calls with no stop reason under the cap. Deviation 2 of
     docs/evidence/2026-09-27-v2-run-preregistration.md promised this
     search over every model before stage 1's results are used.
  2. Failed calls, per model and host, by kind: a stream the host closed
     early (`cut_by_host`), a stream that ended with no usage at all, the
     one-hour client timeout, rate limits and connection errors; what each
     billed and how long it ran. The counts for the deviation 2 addendum.
  3. Calls per host for each model with a host failure: how many finished
     and how many the host cut, which is what a routing exclusion rests on.
  4. What is left of stage 1: planned draws against scored draws per cell.
     Cells closed at their completed draws (deviation 3) need none.
  5. Spend so far, and stages 2 and 3 re-projected. The pre-registration
     projected from assumed output tokens for 16 of 26 models and said to
     re-project from measured ones. Each mid and top model has one measured
     draw, its smoke draw. The finished models say how well one draw
     predicts a model's whole bill: for each model in RATIO_TIERS, the
     ratio of its mean cost per scored draw (failed calls and re-draws
     included) to its first Clark draw. The median ratio gives the typical
     projection and the 90th percentile the heavy one. Worst is the
     pre-registration's: every call at the 64,000 cap and every two-stage
     cell at 20 draws. w is one call at that cap, the headroom a process's
     spend limit needs above its expected cost (docs/evidence/
     2026-09-29-v2-stage3-plan.md). The per-model table has the cuts
     already applied (APPLIED) taken out.
  6. The whole run against the cap, with the pre-registered cuts
     applied cumulatively from none, and for each the sum over processes
     still to run of typical cost plus w.
"""
import collections
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import infer, models, rollup  # noqa: E402

LEDGER = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
VARIANCE = os.path.join(ROOT, "data", "infer", "variance.json")

CAP = 64000
TIMEOUT_S = 3000       # the client gives up at 3,600 s; nothing else runs this long unbilled
CAP_USD = 50.0         # the cap on the whole run: $45 pre-registered, $50 from amendment 3

# Tiers as the pre-registration's ROSTER gives them (lab positioning), by
# registry id, and the v1 models re-run under v2. Copied rather than imported:
# a spike may not gain a sibling importer (tests/test_structure.py).
TIER = {
    "claude-opus-5-5": "top", "claude-sonnet-5": "mid", "claude-haiku-4-5-20251001": "cheap",
    "openai/gpt-6-sol": "mid", "openai/gpt-6-luna": "cheap",
    "google/gemini-3.8-flash": "mid", "google/gemini-3.5-flash-lite": "cheap",
    "x-ai/grok-4.7": "top", "moonshotai/kimi-k3": "top",
    "z-ai/glm-5.3": "top", "z-ai/glm-5.3-flash": "cheap",
    "qwen/qwen3.8-max-0902": "top", "qwen/qwen3.8-flash": "cheap",
    "deepseek/deepseek-v4-pro-0813": "mid", "deepseek/deepseek-v4.1-flash": "cheap",
    "xiaomi/mimo-v2.6-pro": "mid", "xiaomi/mimo-v2.6-flash": "cheap",
    "minimax/minimax-m3": "mid", "tencent/hy3": "cheap",
    "z-ai/glm-5.2": "v1", "deepseek/deepseek-v4-pro": "v1",
    "deepseek/deepseek-v4-flash": "v1", "moonshotai/kimi-k2-thinking": "v1",
    "openai/gpt-oss-120b": "v1", "qwen/qwen3.5-flash-02-23": "v1", "qwen/qwen3-coder": "v1",
}
ROSTER_TIERS = {"top", "mid", "cheap"}
# (target, condition as rollup names it, draws or "two-stage", tiers)
PLAN = [
    ("clarkco", "v2", "two-stage", ROSTER_TIERS | {"v1"}),
    ("stjohns", "v2", 10, ROSTER_TIERS | {"v1"}),
    ("clarkco", "hint|v2", 10, {"mid", "cheap", "v1"}),
    ("santabarbara", "v2", 5, ROSTER_TIERS),
]
STAGES = [("1", {"cheap", "v1"}), ("2", {"mid"}), ("3", {"top"})]
# Finished tiers: costed at their measured mean, and the source of the
# ratio that projects the rest. Stage 2 finished 2026-09-29.
RATIO_TIERS = {"cheap", "v1", "mid"}
# Models whose smoke draw is re-bought under new routing (stage 3 plan).
REBUY = {"z-ai/glm-5.3"}
# The pre-registration's projection, typical / heavy, for comparison.
PREREG = {"1": (6.04, 12.44), "2": (10.96, 26.49), "3": (18.05, 46.84)}


def section(title):
    print("\n== %s" % title)


def load():
    with io.open(LEDGER, encoding="utf-8") as fh:
        raw = [json.loads(line) for line in fh if line.strip()]
    with io.open(VARIANCE, encoding="utf-8") as fh:
        v = json.load(fh)
    return raw, v


def kind(r):
    """What a failed call was. `_HostError` with tokens is the stream the
    host closed early; without tokens, one that ended with no usage."""
    e = r.get("error_type")
    if e == "_HostError":
        return "host cut" if r.get("output_tokens") else "no usage"
    if e == "APIError" and r.get("seconds", 0) >= TIMEOUT_S:
        return "1 h timeout"
    return {"APIError": "api error", "RateLimitError": "rate limit",
            "APIConnectionError": "connection"}.get(e, e or "?")


def target_of(r):
    return r.get("tag", "").split("/")[0]


def stop_reasons(v2):
    section("1. Successful v2 calls with no stop reason and fewer tokens than the cap")
    seen = collections.Counter((r["model"], r.get("stop_reason")) for r in v2 if r["ok"])
    odd = [r for r in v2 if r["ok"] and r.get("stop_reason") is None
           and r["output_tokens"] < r.get("max_tokens", CAP)]
    print("  stop reasons on successful calls: %s"
          % dict(collections.Counter(r.get("stop_reason") for r in v2 if r["ok"])))
    print("  %d successful calls with no stop reason under the cap:" % len(odd))
    for r in odd:
        print("    %s  %-30s %-12s %-18s draw %2d  out %6d  %7.1f s  $%.4f"
              % (r["at"], r["model"], r.get("host"), r.get("tag"), r["draw"],
                 r["output_tokens"], r["seconds"], r["usd"]))
    by_model = collections.Counter(r["model"] for r in odd)
    print("  by model: %s" % dict(by_model))
    # The other direction: a host that stops on `max_tokens` short of the cap
    # the request set, so its own limit, not the protocol's, cut the answer.
    short = [r for r in v2 if r["ok"] and r.get("stop_reason") == "max_tokens"
             and r["output_tokens"] < r.get("max_tokens", CAP)]
    print("  %d successful calls stopped on max_tokens below the requested cap:" % len(short))
    for r in short:
        print("    %s  %-30s %-12s %-18s draw %2d  out %6d of %6d"
              % (r["at"], r["model"], r.get("host"), r.get("tag"), r["draw"],
                 r["output_tokens"], r["max_tokens"]))
    return seen


def failures(v2):
    section("2. Failed v2 calls by model, host and kind")
    groups = collections.defaultdict(list)
    for r in v2:
        if not r["ok"]:
            groups[(r["model"], r.get("host") or "-", kind(r))].append(r)
    print("  %-30s %-14s %-12s %3s %8s %8s  %s"
          % ("model", "host", "kind", "n", "tokens", "billed", "seconds"))
    for (m, h, k), rs in sorted(groups.items()):
        print("  %-30s %-14s %-12s %3d %8d %8.4f  %s"
              % (m, h, k, len(rs), sum(r["output_tokens"] for r in rs),
                 sum(r["usd"] for r in rs),
                 ", ".join("%.0f" % r["seconds"] for r in rs)))
    fails = [r for r in v2 if not r["ok"]]
    print("  total: %d failed calls, %d billed, $%.4f"
          % (len(fails), sum(1 for r in fails if r["usd"]), sum(r["usd"] for r in fails)))
    tally = collections.Counter(kind(r) for r in fails)
    print("  by kind: %s" % dict(tally))


def hosts(v2):
    section("3. Calls per host, for models with a failure a host caused")
    hit = sorted({r["model"] for r in v2 if not r["ok"]
                  and kind(r) in ("host cut", "no usage", "1 h timeout")})
    for m in hit:
        per = collections.defaultdict(collections.Counter)
        for r in v2:
            if r["model"] == m:
                per[r.get("host") or "(none recorded)"]["ok" if r["ok"] else kind(r)] += 1
        print("  %s" % m)
        for h, c in sorted(per.items(), key=lambda x: -sum(x[1].values())):
            print("    %-18s %s" % (h, ", ".join("%s %d" % kv for kv in sorted(c.items()))))
    print("  A timeout or a stream with no usage has no host recorded: the call never")
    print("  returned the chunk that names one.")


def cells(v, rows):
    """Aggregated v2 cells keyed (target, model, condition)."""
    agg = rollup.aggregate(rows)
    return {(e["target"], e["model"], e["condition"]): e
            for e in agg.values() if e["condition"].endswith("v2")}


# The pre-registered cut order, applied cumulatively when a re-projection
# puts the run over the cap. "Never cut: any roster model's first 10 Clark
# draws, and any Santa Barbara cell."
CUTS = [
    ("mid_hint", "1. the hint arm on the mid tier"),
    ("v1_dear", "2. the v1 re-runs of kimi-k2-thinking and glm-5.2"),
    ("top_sj5", "3. St. Johns for the top tier, 10 draws to 5"),
    ("top_clark10", "4. Clark for the top tier stops at 10"),
]
V1_DEAR = ("moonshotai/kimi-k2-thinking", "z-ai/glm-5.2")
# Cuts decided so far (the pre-registration's "Cuts under the cap").
APPLIED = ("mid_hint",)
# Cells closed at their completed draws, (target, model, condition):
# deviation 3, time-boxed rather than re-run.
CLOSED = {
    ("clarkco", "z-ai/glm-5.3-flash", "v2"),
    ("clarkco", "z-ai/glm-5.3-flash", "hint|v2"),
    ("stjohns", "z-ai/glm-5.3-flash", "v2"),
}


def plan_for(m, cuts=()):
    """(target, condition, rule) for each cell this model runs, after cuts.
    A cut v1 re-run keeps the draws already bought and buys no more."""
    tier = TIER[m]
    out = []
    for tgt, cond, rule, tiers in PLAN:
        if tier not in tiers:
            continue
        if "mid_hint" in cuts and tier == "mid" and cond == "hint|v2":
            continue
        if "v1_dear" in cuts and m in V1_DEAR:
            rule = 0
        if "top_sj5" in cuts and tier == "top" and tgt == "stjohns":
            rule = 5
        if "top_clark10" in cuts and tier == "top" and rule == "two-stage":
            rule = 10
        if (tgt, m, cond) in CLOSED:
            rule = "closed"
        out.append((tgt, cond, rule))
    return out


def left(e, rule, e_clark):
    """Draws a cell still needs, (typical, heavy). A two-stage cell past its
    first 10 has its answer; before that, typical is the expected count."""
    done = e["draws_scored"] if e else 0
    if rule == "closed":
        return 0, 0
    if rule != "two-stage":
        return (max(rule - done, 0),) * 2
    if done >= 10:
        want = 10 if done == 10 and e["perfect"] in (0, 10) else 20
        return (max(want - done, 0),) * 2
    return max(e_clark - done, 0), 20 - done


def remaining(cell_e):
    section("4. What is left of stage 1 (cheap tier and v1 models)")
    print("  %-30s %-13s %-8s %6s %6s %6s %6s"
          % ("model", "target", "cond", "plan", "scored", "infra", "left"))
    n = 0
    for m, tier in TIER.items():
        if tier not in ("cheap", "v1"):
            continue
        for tgt, cond, rule in plan_for(m):
            e = cell_e.get((tgt, m, cond))
            k, _ = left(e, rule, 20)
            infra = e["draws_infra_error"] if e else 0
            if k or infra or rule == "closed":
                n += k
                print("  %-30s %-13s %-8s %6s %6d %6d %6d"
                      % (m, tgt, cond, rule, e["draws_scored"] if e else 0, infra, k))
    print("  %d draws left. A closed cell's infra-error draws are reported with bounds,"
          " not retried." % n)


def draw_costs(rows):
    """Purchase cost of each scored v2 draw, keyed (target, model, condition)."""
    out = collections.defaultdict(dict)
    for r in rows:
        if (r["experiment"] == "variance" and r["metric"] == "usd_purchase"
                and r["condition"].endswith("v2")):
            out[(r["target"], r["model"], r["condition"])][r["unit_id"]] = r["value"]
    return out


def projection(v2, rows, cell_e):
    section("5. Spend so far, and what the rest of the run is projected to cost,"
            " with the cuts applied so far")
    spent = collections.Counter()
    for r in v2:
        spent["anthropic" if r["provider"] == "anthropic" else "openrouter"] += r["usd"]
    total_spent = sum(spent.values())
    print("  v2 spend in the ledger: $%.2f (Anthropic $%.2f, OpenRouter $%.2f), %d calls"
          % (total_spent, spent["anthropic"], spent["openrouter"], len(v2)))
    failed = collections.Counter()
    for r in v2:
        if not r["ok"]:
            failed[r["model"]] += r["usd"]

    costs = draw_costs(rows)
    first = {m: costs.get(("clarkco", m, "v2"), {}).get("d00") for m in TIER}
    mean = {}
    ratios = {}
    stage1 = collections.Counter()
    for m, tier in TIER.items():
        mine = [c for (_t, mm, _c), per in costs.items() if mm == m for c in per.values()]
        if tier in ("cheap", "v1"):
            stage1[tier] += sum(r["usd"] for r in v2 if r["model"] == m)
        if mine:
            mean[m] = (sum(mine) + failed[m]) / len(mine)
        if tier in RATIO_TIERS and first[m] and len(mine) >= 10:
            ratios[m] = mean[m] / first[m]
    print("\n  stage 1 so far: $%.2f (cheap $%.2f, v1 $%.2f). Pre-registered for the whole"
          " stage: $%.2f typical, $%.2f heavy"
          % (sum(stage1.values()), stage1["cheap"], stage1["v1"], *PREREG["1"]))
    stage2 = sum(r["usd"] for r in v2 if TIER.get(r["model"]) == "mid")
    print("  stage 2 so far: $%.2f. Pre-registered: $%.2f typical, $%.2f heavy"
          % (stage2, *PREREG["2"]))
    print("\n  finished models (%s): mean cost per scored draw (failed calls and re-draws"
          " in), over the first Clark draw" % ", ".join(sorted(RATIO_TIERS)))
    for m, x in sorted(ratios.items(), key=lambda kv: kv[1]):
        print("    %-30s %5.2f   first $%.4f  mean $%.4f" % (m, x, first[m], mean[m]))
    rs = sorted(ratios.values())
    typ_r = statistics.median(rs)
    heavy_r = rs[int(0.9 * (len(rs) - 1))]
    print("  median %.2f, 90th percentile %.2f, over %d models" % (typ_r, heavy_r, len(rs)))

    two = [e for (t, m, c), e in cell_e.items() if t == "clarkco" and c == "v2"
           and TIER.get(m) in RATIO_TIERS and e["draws_scored"] >= 10]
    stopped = sum(1 for e in two if e["draws_scored"] == 10 and e["perfect"] in (0, 10))
    e_clark = 10 + 10 * (1 - stopped / len(two))
    print("\n  two-stage: %d of %d finished Clark cells stopped at 10, so %.1f draws expected"
          % (stopped, len(two), e_clark))

    def model_cost(m, cuts=()):
        """(typical, heavy, worst, draws typical, draws heavy, w) for the
        draws this model still needs. Finished tiers are costed at their
        measured mean per draw; the rest at their first draw times the
        ratio. Worst is the registry's price ceiling at the 64,000 cap for
        every heavy draw, and w one such call."""
        n_typ = n_heavy = 0
        for tgt, cond, rule in plan_for(m, cuts):
            a, b = left(cell_e.get((tgt, m, cond)), rule, e_clark)
            n_typ += a
            n_heavy += b
        if n_heavy and m in REBUY:
            n_typ += 1
            n_heavy += 1
        if TIER[m] in RATIO_TIERS:
            per_typ = per_heavy = mean[m]
        else:
            per_typ, per_heavy = first[m] * typ_r, first[m] * heavy_r
        n_in = next((r["input_tokens"] + r["cache_read_input_tokens"]
                     + r["cache_creation_input_tokens"] for r in v2
                     if r["model"] == m and r["ok"]), 9000)
        w = infer.estimate(m, n_in, CAP)
        return (per_typ * n_typ, per_heavy * n_heavy, w * n_heavy, n_typ, n_heavy, w)

    print("\n  %-30s %-5s %9s %6s %6s %8s %8s %8s %6s %8s"
          % ("model", "tier", "1st draw", "draws", "heavy", "typical", "heavy", "worst",
             "w", "typ + w"))
    by_stage = collections.defaultdict(collections.Counter)
    for stage, tiers in STAGES:
        for m, tier in TIER.items():
            if tier not in tiers:
                continue
            t_, h_, w_, n_t, n_h, w1 = model_cost(m, APPLIED)
            if not n_h:
                continue
            bill = "anthropic" if models.get(m).provider == "anthropic" else "openrouter"
            for w, x in (("typ", t_), ("heavy", h_), ("worst", w_)):
                by_stage[stage][(bill, w)] += x
            print("  %-30s %-5s %9.4f %6.1f %6d %8.2f %8.2f %8.2f %6.2f %8.2f"
                  % (m, tier, first[m] or 0, n_t, n_h, t_, h_, w_, w1, t_ + w1))
    print("\n  %-6s %-10s %8s %8s %8s   pre-registered typical / heavy (whole stage)"
          % ("stage", "billed by", "typical", "heavy", "worst"))
    for stage, tot in by_stage.items():
        for bill in ("anthropic", "openrouter"):
            print("  %-6s %-10s %8.2f %8.2f %8.2f"
                  % (stage, bill, tot[(bill, "typ")], tot[(bill, "heavy")],
                     tot[(bill, "worst")]))
        print("  %-6s %-10s %8.2f %8.2f %8.2f   $%.2f / $%.2f"
              % (stage, "both", *(sum(v for (b, w), v in tot.items() if w == ww)
                                  for ww in ("typ", "heavy", "worst")), *PREREG[stage]))

    section("6. The whole run against the $%.0f cap, with the pre-registered cuts" % CAP_USD)
    print("  spent so far plus everything still to buy, cuts applied cumulatively;")
    print("  room is the cap less spend, and typ + w sums each process still to run")
    print("  %-52s %9s %9s %9s %9s" % ("", "typical", "heavy", "room", "typ + w"))
    cuts = []
    for key, name in [(None, "no cuts")] + CUTS:
        if key:
            cuts.append(key)
        t_ = h_ = tw = 0.0
        for m in TIER:
            a, b, _w, _n1, n2, w1 = model_cost(m, tuple(cuts))
            t_ += a
            h_ += b
            if n2:
                tw += a + w1
        print("  %-52s %9.2f %9.2f %9.2f %9.2f"
              % (name, total_spent + t_, total_spent + h_, CAP_USD - total_spent, tw))


def main():
    raw, v = load()
    v2 = [r for r in raw if r.get("protocol") == "v2"]
    ledger = infer.Ledger(LEDGER).rows()
    rows = rollup.rows_from_variance(v, ledger) + rollup.rows_from_ledger(ledger)
    cell_e = cells(v, rows)
    stop_reasons(v2)
    failures(v2)
    hosts(v2)
    remaining(cell_e)
    projection(v2, rows, cell_e)


if __name__ == "__main__":
    main()
