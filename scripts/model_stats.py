# -*- coding: utf-8 -*-
"""Roll every model measurement in this project into one tidy table.

Until now the variance and drift numbers were computed inside
`scripts/conformance.py`, printed, and pasted into evidence reports by hand.
That works exactly once. It means the figures in a report can only be
re-derived by re-running the experiment that produced them, and it means the
per-model comparison - the thing anyone actually wants - exists only as prose.

This script reads the three artifacts that already exist and emits:

  data/infer/model_stats.csv    one row per observation, long format
  data/infer/model_stats.json   aggregates per cell with intervals

Long format on purpose: one row is `experiment, target, model, condition,
unit, unit_id, metric, value`, so a new metric is a new row rather than a new column, and
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

from permits import fileio, infer                           # noqa: E402
from permits.rollup import (                                 # noqa: E402
    FIELDS, aggregate, field_verdicts, rows_from_drift, rows_from_ledger,
    rows_from_variance, short, unclaimed)

OUT = os.path.join(ROOT, "data", "infer")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    return fileio.read_json(p)


def read_ledger(path):
    """Ledger rows in file order. Line position is the row id."""
    return infer.Ledger(path).rows() if os.path.exists(path) else []


def report(agg):
    print("\nper-cell model statistics   (success = perfect agreement on "
          "every page)")
    print("%-9s %-20s %-8s %5s %5s %8s %-16s %8s %9s %9s %7s"
          % ("target", "model", "cond", "n", "infra", "success", "95% CI",
             "silent", "$/success", "drift", "p95 s"))
    for _, e in sorted(agg.items()):
        sil = ("%d/%d" % (e["silent_failures"], e["failures"])
               if e["failures"] else "-")
        dr = ("%.2f (n=%d)" % (e["drift_survival"], e["drift_n"])
              if "drift_survival" in e else "-")
        print("%-9s %-20s %-8s %5d %5d %7.0f%% [%.2f, %.2f]      %8s %9s %9s %7s"
              % (e["target"], short(e["model"]), e["condition"],
                 e["draws_scored"], e["draws_infra_error"],
                 100 * (e["success_rate"] or 0),
                 e["success_ci95"][0], e["success_ci95"][1], sil,
                 ("$%.4f" % e["usd_per_success"]
                  if e["usd_per_success"]
                  else ("unpriced" if e["draws_unpriced"] else "never")),
                 dr,
                 ("%.0f" % e["latency_p95_s"]
                  if e["latency_p95_s"] is not None else "-")))
    print("\n  $/success is what the cell's draws cost to buy, over "
          "extractors that passed\n  conformance. A cell that never "
          "succeeded has no cost per success, only a bill.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-only", action="store_true")
    args = ap.parse_args()

    rows = []
    ledger = read_ledger(os.path.join(OUT, "ledger.jsonl"))
    v = load("variance.json")
    audit = load(os.path.join("verifier", "field_audit.json"))
    if v:
        rows += rows_from_variance(
            v, ledger, field_verdicts(audit) if audit is not None else None)
    dr = load("drift.json")
    if dr:
        rows += rows_from_drift(dr)
    rows += rows_from_ledger(ledger)
    if not rows:
        raise SystemExit("no artifacts in %s; run the experiments first" % OUT)

    cpath = os.path.join(OUT, "model_stats.csv")
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\r\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    fileio.atomic_write(cpath, buf.getvalue(), newline="")
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
        spare = unclaimed(v, ledger) if v else []
        if spare:
            print("\n  %d variance calls ($%.4f) bought a response no scored "
                  "draw uses:\n  superseded by a later ceiling, or bought "
                  "twice. Not counted in any cell."
                  % (len(spare), sum(ledger[i].usd
                                     for i in spare)))


if __name__ == "__main__":
    main()
