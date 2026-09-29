# -*- coding: utf-8 -*-
"""Every table in docs/evidence/2026-09-27-cost-per-success-intervals.md.

For each pair of protocol v1 baseline cells on the same target, both with at
least one perfect draw and at least 3 scored draws, how sure can we be which
model is cheaper per working extractor?

Two readings:
  - Wilson extremes: cost per draw over the ends of each rate's Wilson 95%
    interval. What the 2026-09-22 report's "the direction survives" did, for
    one end of one cell.
  - Simulation: each rate drawn from a Beta posterior (uniform and Jeffreys
    priors), each cell's mean cost per draw from a bootstrap of its draws.
    Reports the median ratio, its 95% range and P(first model cheaper),
    with the model cheaper per success at the point estimate listed first.

Reads data/infer/model_stats.csv (run scripts/model_stats.py first) and list
prices from permits/models.py. No model calls. Seeded, so reruns print the
same tables.

    python spikes/cost_per_success_intervals.py
"""
import collections
import csv
import io
import itertools
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import models                       # noqa: E402

CSV = os.path.join(ROOT, "data", "infer", "model_stats.csv")
N_SIM = 100000
SEED = 20260927
PRIORS = (("uniform", 1.0), ("Jeffreys", 0.5))


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def load_cells():
    draws = collections.defaultdict(lambda: collections.defaultdict(dict))
    with io.open(CSV, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r["experiment"], r["condition"], r["unit"]) != (
                    "variance", "baseline", "draw") or r["value"] == "":
                continue
            draws[(r["target"], r["model"])][r["unit_id"]][r["metric"]] = float(r["value"])
    cells = {}
    for key, ds in draws.items():
        scored = [d for d in ds.values() if d.get("attempted") == 1]
        k = int(sum(d["perfect"] for d in scored))
        if len(scored) >= 3 and k >= 1:
            cells[key] = (k, len(scored), [d["usd_purchase"] for d in scored])
    return cells


def token_price(cheaper, dearer):
    """Whether the model cheaper per success is also cheaper per token."""
    a, b = models.get(cheaper).list_price, models.get(dearer).list_price
    if a[0] <= b[0] and a[1] <= b[1]:
        return "also cheaper"
    if a[0] >= b[0] and a[1] >= b[1]:
        return "**dearer (inverts)**"
    return "mixed"


def short(model):
    return model.split("/")[-1].replace("claude-", "").replace("-20251001", "")


def quantile(xs, f):
    return xs[int(f * (len(xs) - 1))]


def main():
    rng = random.Random(SEED)
    cells = load_cells()

    print("## cells (baseline, n >= 3, at least one perfect draw)\n")
    print("| target | model | k/n | Wilson 95% | $/draw | $/success | $/success at Wilson ends |")
    print("|---|---|---:|---|---:|---:|---|")
    for (t, m), (k, n, costs) in sorted(cells.items()):
        lo, hi = wilson(k, n)
        c = sum(costs) / n
        print("| %s | %s | %d/%d | [%.3f, %.3f] | %.4f | %.4f | [%.4f, %.4f] |"
              % (t, short(m), k, n, lo, hi, c, c * n / k, c / hi, c / lo))

    print("\n## pairs, cheaper per success (point estimate) first\n")
    print("ratio = how many times cheaper per success the first model is; "
          "P = P(first is cheaper); token price compares list input and "
          "output prices\n")
    print("| target | cheaper | dearer | token price | point | Wilson ends | prior "
          "| median | 95% range | P |")
    print("|---|---|---|---|---:|---|---|---:|---|---:|")
    by_target = collections.defaultdict(list)
    for (t, m) in cells:
        by_target[t].append(m)
    for t in sorted(by_target):
        for a, b in itertools.combinations(sorted(by_target[t]), 2):
            cps = {m: sum(cells[(t, m)][2]) / cells[(t, m)][0] for m in (a, b)}
            if cps[a] > cps[b]:
                a, b = b, a
            ka, na, ca = cells[(t, a)]
            kb, nb, cb = cells[(t, b)]
            mean_a, mean_b = sum(ca) / na, sum(cb) / nb
            point = cps[b] / cps[a]
            (la, ha), (lb, hb) = wilson(ka, na), wilson(kb, nb)
            ends = ((mean_b / hb) / (mean_a / la), (mean_b / lb) / (mean_a / ha))
            for prior, a0 in PRIORS:
                ratios = []
                for _ in range(N_SIM):
                    pa = rng.betavariate(ka + a0, na - ka + a0)
                    pb = rng.betavariate(kb + a0, nb - kb + a0)
                    sa = sum(rng.choice(ca) for _ in ca) / na
                    sb = sum(rng.choice(cb) for _ in cb) / nb
                    ratios.append((sb / pb) / (sa / pa))
                ratios.sort()
                p = sum(r > 1 for r in ratios) / N_SIM
                print("| %s | %s | %s | %s | %.2f | [%.2f, %.2f] | %s | %.2f | [%.2f, %.2f] | %.3f |"
                      % (t, short(a), short(b), token_price(a, b), point,
                         ends[0], ends[1], prior, quantile(ratios, .5),
                         quantile(ratios, .025), quantile(ratios, .975), p))


if __name__ == "__main__":
    main()
