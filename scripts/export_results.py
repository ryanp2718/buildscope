# -*- coding: utf-8 -*-
"""Export the protocol v2 run to the one data file the results page reads.

    python scripts/export_results.py
    python scripts/export_results.py --out some/other/data.json

Writes `site/results/data.json`:

  models   one record per model on the run: lab, tier, list price
  cells    one record per (target, model, arm, protocol): pass@1 with its
           Wilson interval, cost per draw and per success, a simulated 95%
           range for cost per success, re-draws, host failures, hosts
  draws    one record per draw: outcome, tokens, what it cost to buy, host

Every rate and cost comes from `permits/rollup.py` (`aggregate`, and the
per-draw rows it is derived from), the functions `scripts/model_stats.py`
writes the stats table with, so the page, the report and the table cannot
disagree. The cost-per-success range is the method of
docs/evidence/2026-09-27-cost-per-success-intervals.md applied to one cell:
the pass rate drawn from a Beta posterior, the mean cost per draw from a
bootstrap of the cell's draws. It is seeded per cell, so a re-run with no
new draws writes identical bytes, and a new cell does not move the others.

What goes in is the step 6 roster and the seven v1 models re-run under v2
(docs/evidence/2026-09-27-v2-run-preregistration.md), their v2 cells, and
the v1 baseline cells of the seven, for the v1-to-v2 comparison. Nothing
from `data/` leaves except these figures: no source, no prompt, no path.

No model calls. Reads only what is already on disk.
"""
import argparse
import collections
import io
import json
import os
import random
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from permits import fileio, infer, models, rollup            # noqa: E402

OUT = os.path.join(ROOT, "site", "results", "data.json")
INFER = os.path.join(ROOT, "data", "infer")

# The step 6 roster and the v1 models re-run under v2, by registry id, in the
# pre-registration's order. `tests/test_export_results.py` checks this
# against `spikes/preregister_v2_run.py`, which the roster was published from.
ROSTER = [
    "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5-20251001",
    "openai/gpt-6-sol", "openai/gpt-6-luna",
    "google/gemini-3.8-flash", "google/gemini-3.5-flash-lite",
    "x-ai/grok-4.7", "moonshotai/kimi-k3",
    "z-ai/glm-5.3", "z-ai/glm-5.3-flash",
    "qwen/qwen3.8-max-0902", "qwen/qwen3.8-flash",
    "deepseek/deepseek-v4-pro-0813", "deepseek/deepseek-v4.1-flash",
    "xiaomi/mimo-v2.6-pro", "xiaomi/mimo-v2.6-flash",
    "minimax/minimax-m3", "tencent/hy3",
]
V1_RERUN = [
    "z-ai/glm-5.2", "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash",
    "moonshotai/kimi-k2-thinking", "openai/gpt-oss-120b",
    "qwen/qwen3.5-flash-02-23", "qwen/qwen3-coder",
]
TARGETS = {
    "clarkco": "Clark County, NV",
    "stjohns": "St. Johns County, FL",
    "santabarbara": "Santa Barbara County, CA",
}

N_SIM = 20000
SEED = 20260928
PRIORS = (("jeffreys", 0.5), ("uniform", 1.0))


def _r(x, places=6):
    return None if x is None else round(float(x), places)


def wanted(cell):
    """The cells the page draws from: every v2 cell of a model on the run,
    and the v1 baseline cell of each re-run v1 model."""
    if cell["model"] not in ROSTER and cell["model"] not in V1_RERUN:
        return False
    if cell["target"] not in TARGETS:
        return False
    cond = rollup.condition(cell)
    if cond in ("v2", "hint|v2"):
        return True
    return cond == "baseline" and cell["model"] in V1_RERUN


def arm_protocol(cond):
    """`hint|v2` -> (`hint`, `v2`); `baseline` (a v1 cell) -> (`baseline`,
    `v1`)."""
    parts = cond.split("|")
    arm = "hint" if "hint" in parts else "baseline"
    protocol = "v2" if "v2" in parts else "v1"
    return arm, protocol


def quantile(xs, f):
    return xs[int(f * (len(xs) - 1))]


def cost_per_success_range(key, k, n, costs):
    """Median and 95% range of cost per success for one cell, per prior.

    None when the cell never succeeded (no finite cost per success exists)
    or when any draw's purchase is unknown (a partial bill understates it).
    The seed is derived from the cell key, so cells are independent of the
    order they are exported in and of each other."""
    if k == 0 or not costs or any(c is None for c in costs):
        return None
    rng = random.Random(SEED ^ zlib.crc32(key.encode("utf-8")))
    out = {}
    for prior, a0 in PRIORS:
        sims = []
        for _ in range(N_SIM):
            p = rng.betavariate(k + a0, n - k + a0)
            mean = sum(rng.choice(costs) for _ in costs) / len(costs)
            sims.append(mean / p)
        sims.sort()
        out[prior] = [_r(quantile(sims, .025)), _r(quantile(sims, .5)),
                      _r(quantile(sims, .975))]
    return out


def build(v, ledger):
    cells = {k: c for k, c in v["cells"].items() if wanted(c)}
    rows = rollup.rows_from_variance({"cells": cells}, ledger)
    rows += rollup.rows_from_ledger(ledger)
    agg = rollup.aggregate(rows)

    per_draw = collections.defaultdict(dict)
    for r in rows:
        if r["experiment"] == "variance":
            key = rollup.cell_name(r["target"], r["model"],
                                        r["condition"])
            per_draw[(key, r["unit_id"])][r["metric"]] = r["value"]

    out_cells, out_draws = [], []
    for key in sorted(cells):
        cell = cells[key]
        e = agg[key]
        arm, protocol = arm_protocol(e["condition"])
        draws = rollup.draws_of(cell)
        hosts = collections.Counter(d.host for d in draws
                                    if d.scored() and d.host)
        costs = [per_draw[(key, "d%02d" % d.draw)].get("usd_purchase")
                 for d in draws if d.scored()]
        n, k = e["draws_scored"], e["perfect"]
        known = [c for c in costs if c is not None]
        out_cells.append({
            "key": key, "target": cell["target"], "model": cell["model"],
            "arm": arm, "protocol": protocol,
            "n": n, "k": k,
            "rate": _r(e["success_rate"], 4),
            "ci95": e["success_ci95"],
            "usd_total": _r(e["usd_total"]),
            "usd_per_draw": (_r(sum(known) / n)
                             if n and len(known) == n else None),
            "usd_per_success": _r(e["usd_per_success"]),
            "usd_per_success_range": cost_per_success_range(key, k, n, costs),
            "draws_unpriced": e["draws_unpriced"],
            "draws_redrawn": e["draws_redrawn"],
            "draws_truncated": e["draws_truncated"],
            "draws_infra_error": e["draws_infra_error"],
            "usd_failed_calls": _r(e["usd_failed_calls"]),
            "silent_failures": e["silent_failures"],
            "reasoning_tokens_p50": e["reasoning_tokens_p50"],
            "hosts": dict(sorted(hosts.items())),
        })
        for d in draws:
            m = per_draw[(key, "d%02d" % d.draw)]
            out_draws.append({
                "cell": key, "draw": d.draw,
                "outcome": rollup.failure_mode(d),
                "output_tokens": d.output_tokens,
                "reasoning_tokens": d.reasoning_tokens,
                "usd": _r(m.get("usd_purchase")),
                "seconds": _r(m.get("seconds"), 1),
                "host": d.host,
                "redrawn": bool(d.redraw_max_tokens),
                "recall_min": _r(d.recall_min, 4),
            })

    on_run = set(ROSTER) | set(V1_RERUN)
    out_models = []
    for mid in ROSTER + V1_RERUN:
        s = models.get(mid)
        out_models.append({
            "id": mid, "short": s.short, "lab": s.lab, "tier": str(s.tier),
            "group": "roster" if mid in ROSTER else "v1_rerun",
            "price_in": s.list_price[0], "price_out": s.list_price[1],
        })
    assert {m["id"] for m in out_models} == on_run

    return {
        "as_of": max((r.at for r in ledger), default=None),
        "note": ("pass@1 is perfect agreement with a hand-written adapter on "
                 "every page of the target; agreement is not accuracy. Costs "
                 "are what each draw cost to buy, in USD. Prices are list "
                 "USD per million tokens (input, output)."),
        "method": {
            "interval": "Wilson 95%",
            "cost_per_success_range": ("Beta posterior on the rate x "
                                       "bootstrap of cost per draw, "
                                       "2.5/50/97.5 percentiles"),
            "priors": [p for p, _ in PRIORS], "n_sim": N_SIM, "seed": SEED,
        },
        "targets": TARGETS,
        "models": out_models,
        "cells": out_cells,
        "draws": out_draws,
    }


def render(data):
    """Bytes as written: sorted keys, one level of indent, a final newline,
    so a re-run with nothing new is byte-identical and a diff is readable."""
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    vpath = os.path.join(INFER, "variance.json")
    if not os.path.exists(vpath):
        raise SystemExit("no data/infer/variance.json; run the experiments first")
    v = fileio.read_json(vpath)
    lpath = os.path.join(INFER, "ledger.jsonl")
    ledger = infer.Ledger(lpath).rows() if os.path.exists(lpath) else []
    data = build(v, ledger)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(data))
    print("wrote %s  (%d models, %d cells, %d draws, as of %s)"
          % (os.path.relpath(args.out, ROOT), len(data["models"]),
             len(data["cells"]), len(data["draws"]), data["as_of"]))


if __name__ == "__main__":
    main()
