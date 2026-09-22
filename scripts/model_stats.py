# -*- coding: utf-8 -*-
"""Roll every model measurement in this project into one tidy table.

Until now the variance and drift numbers were computed inside
`scripts/conformance.py`, printed, and pasted into evidence reports by hand.
That works exactly once. It means the figures in a report can only be
re-derived by re-running the experiment that produced them, and it means the
per-model comparison - the thing anyone actually wants - exists only as prose.

This script reads the three artifacts that already exist and emits:

  data/infer/model_stats.csv    one row per observation, long format
  data/infer/model_stats.json   aggregates per (target, model) with intervals

Long format on purpose: one row is `experiment, target, model, unit, unit_id,
metric, value`, so a new metric is a new row rather than a new column, and
anything that reads CSV can group it without knowing what the experiment was.
The aggregate file is derived from the long table, never computed separately,
so the two cannot disagree.

No model calls. Reads only what is already on disk.

    python scripts/model_stats.py
    python scripts/model_stats.py --csv-only
"""
import argparse
import collections
import csv
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits.stats import failure_mode, pctile, wilson      # noqa: E402

OUT = os.path.join(ROOT, "data", "infer")
FIELDS = ["experiment", "target", "model", "unit", "unit_id", "metric",
          "value"]


def short(model):
    """`claude-haiku-4-5-20251001` -> `haiku-4-5`. The date is noise in a
    comparison table and the prefix is constant."""
    return model.replace("claude-", "").split("-20")[0]


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with io.open(p, encoding="utf-8") as fh:
        return json.load(fh)


def rows_from_variance(v):
    """One row per draw per metric. Draws that were never attempted are
    emitted as `attempted=0` rather than dropped: a cell that stopped on
    budget has a different denominator from one that ran out of successes,
    and dropping the row loses that distinction."""
    out = []
    for cell in v["cells"].values():
        target, model = cell["target"], cell["model"]
        for d in cell["detail"]:
            mode = failure_mode(d)
            uid = "d%02d" % d["draw"]
            if mode == "not_attempted":
                metrics = [("attempted", 0)]
            else:
                metrics = [
                    ("attempted", 1),
                    ("perfect", 1 if mode == "perfect" else 0),
                    ("silent_failure", 1 if mode.startswith("silent") else 0),
                    ("loud_failure", 1 if mode == "loud" else 0),
                    ("usd", d.get("usd", 0.0)),
                    ("output_tokens", d.get("output_tokens", 0)),
                    ("source_bytes", d.get("bytes", 0)),
                    ("truncated", 1 if d.get("truncated") else 0),
                ]
            for metric, value in metrics:
                out.append({"experiment": "variance", "target": target,
                            "model": model, "unit": "draw", "unit_id": uid,
                            "metric": metric, "value": value})
    return out


def rows_from_drift(dr):
    """One row per candidate per mutation. The `clean` column is excluded
    from survival: an extractor that was already broken before any mutation
    was applied has not been shown to be brittle, it has been shown to be
    broken, and folding the two together is how the published Haiku Accela
    extractor's 0/8 nearly became a drift finding."""
    out = []
    for target, t in dr["targets"].items():
        for mutation, results in t["mutations"].items():
            if mutation == "clean":
                continue
            for candidate, r in results.items():
                out.append(
                    {"experiment": "drift", "target": target,
                     "model": candidate, "unit": "extractor_mutation",
                     "unit_id": "%s|%s" % (candidate, mutation),
                     "metric": "survived",
                     "value": 1 if r.get("survived") else 0})
    return out


def rows_from_ledger(path):
    """One row per API call. `ok` is absent on rows written before
    2026-09-22 and reads as a success, which is what it was - the client of
    the day could not record anything else."""
    out = []
    if not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        target = (r.get("tag") or "").split("/")[0]
        for metric in ("usd", "seconds", "input_tokens", "output_tokens",
                       "cache_read_input_tokens"):
            out.append({"experiment": "ledger", "target": target,
                        "model": r.get("model", "?"), "unit": "call",
                        "unit_id": "c%04d" % i, "metric": metric,
                        "value": r.get(metric, 0)})
        out.append({"experiment": "ledger", "target": target,
                    "model": r.get("model", "?"), "unit": "call",
                    "unit_id": "c%04d" % i, "metric": "ok",
                    "value": 1 if r.get("ok", True) else 0})
    return out


def pick(rows, experiment, metric, target=None, model=None):
    return [r["value"] for r in rows
            if r["experiment"] == experiment and r["metric"] == metric
            and (target is None or r["target"] == target)
            and (model is None or r["model"] == model)]


def aggregate(rows):
    """Per (target, model) summary, derived from the long table only."""
    cells = sorted({(r["target"], r["model"]) for r in rows
                    if r["experiment"] == "variance"})
    out = {}
    for target, model in cells:
        att = pick(rows, "variance", "attempted", target, model)
        perf = pick(rows, "variance", "perfect", target, model)
        silent = pick(rows, "variance", "silent_failure", target, model)
        n, k = len(perf), sum(perf)
        fails = n - k
        n_silent = sum(silent)
        lat = pick(rows, "ledger", "seconds", target, model)
        errs = pick(rows, "ledger", "ok", target, model)
        usd = sum(pick(rows, "variance", "usd", target, model))
        # Survival is pooled over the draws of this model on this target.
        # Candidate names in drift.json carry the tier, not the model id.
        tag = short(model)
        surv = [r["value"] for r in rows
                if r["experiment"] == "drift" and r["target"] == target
                and r["model"].startswith("draw %s " % tag)]
        lo, hi = wilson(k, n)
        e = {
            "target": target, "model": model,
            "draws_attempted": sum(att), "draws_scored": n,
            "perfect": k,
            "success_rate": (float(k) / n) if n else None,
            "success_ci95": [round(lo, 4), round(hi, 4)],
            "failures": fails, "silent_failures": n_silent,
            "usd_total": round(usd, 6),
            # Cost per extractor that actually worked. The headline cost of a
            # cheap model is per call; the cost that matters is per success,
            # and on a 5% cell those differ by twentyfold.
            "usd_per_success": round(usd / k, 6) if k else None,
            "latency_p50_s": pctile(lat, 0.50),
            "latency_p95_s": pctile(lat, 0.95),
            "api_calls": len(errs),
            "api_error_rate": (1.0 - float(sum(errs)) / len(errs)
                               if errs else None),
        }
        if fails:
            slo, shi = wilson(n_silent, fails)
            e["silent_share_of_failures"] = round(float(n_silent) / fails, 4)
            e["silent_ci95"] = [round(slo, 4), round(shi, 4)]
        if surv:
            dlo, dhi = wilson(sum(surv), len(surv))
            e["drift_survival"] = round(float(sum(surv)) / len(surv), 4)
            e["drift_n"] = len(surv)
            e["drift_ci95"] = [round(dlo, 4), round(dhi, 4)]
        out["%s|%s" % (target, model)] = e
    return out


def report(agg):
    print("\nper-cell model statistics   (success = perfect agreement on "
          "every page)")
    print("%-9s %-12s %5s %8s %-16s %8s %9s %9s %7s"
          % ("target", "model", "n", "success", "95% CI", "silent",
             "$/success", "drift", "p95 s"))
    for _, e in sorted(agg.items()):
        sil = ("%d/%d" % (e["silent_failures"], e["failures"])
               if e["failures"] else "-")
        dr = ("%.2f (n=%d)" % (e["drift_survival"], e["drift_n"])
              if "drift_survival" in e else "-")
        print("%-9s %-12s %5d %7.0f%% [%.2f, %.2f]      %8s %9s %9s %7s"
              % (e["target"], short(e["model"]), e["draws_scored"],
                 100 * (e["success_rate"] or 0),
                 e["success_ci95"][0], e["success_ci95"][1], sil,
                 ("$%.4f" % e["usd_per_success"]
                  if e["usd_per_success"] else "never"),
                 dr,
                 ("%.0f" % e["latency_p95_s"]
                  if e["latency_p95_s"] is not None else "-")))
    print("\n  $/success is total cell spend over extractors that passed "
          "conformance.\n  A cell that never succeeded has no cost per "
          "success, only a bill.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-only", action="store_true")
    args = ap.parse_args()

    rows = []
    v = load("variance.json")
    if v:
        rows += rows_from_variance(v)
    dr = load("drift.json")
    if dr:
        rows += rows_from_drift(dr)
    rows += rows_from_ledger(os.path.join(OUT, "ledger.jsonl"))
    if not rows:
        raise SystemExit("no artifacts in %s; run the experiments first" % OUT)

    cpath = os.path.join(OUT, "model_stats.csv")
    with io.open(cpath, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    counts = collections.Counter(r["experiment"] for r in rows)
    print("wrote %s  (%d rows: %s)"
          % (os.path.relpath(cpath, ROOT), len(rows),
             ", ".join("%s %d" % kv for kv in sorted(counts.items()))))

    agg = aggregate(rows)
    jpath = os.path.join(OUT, "model_stats.json")
    with io.open(jpath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"cells": agg,
                             "note": "Derived from model_stats.csv. Every "
                                     "rate carries a Wilson 95% interval; "
                                     "agreement with a hand-written adapter "
                                     "is not accuracy."},
                            indent=1, sort_keys=True))
    print("wrote %s  (%d cells)" % (os.path.relpath(jpath, ROOT), len(agg)))
    if not args.csv_only:
        report(agg)


if __name__ == "__main__":
    main()
