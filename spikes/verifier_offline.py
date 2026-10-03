# -*- coding: utf-8 -*-
"""Steps 1 and 2 of docs/evidence/2026-09-29-agentic-extractor-plan.md, on
the extractors the v2 run already bought. No model calls.

    python spikes/verifier_offline.py

1. **The verifier.** A production check that needs no reference: it sees a
   portal's pages and an extractor's output, never the adapter, the
   reference records or the scorer. Each stored v2 extractor that ran on
   every page is re-run on its target's stripped corpus and checked; its
   scored outcome in `variance.json` is used only to grade the check. Draws
   that raised, were refused by the audit or wrote no code are rejected by
   any check, and are counted apart.

   Checks, all per page:

   - rows: the number of rows returned equals the page's grid rows, counted
     by a generic rule fixed on the development targets before Santa Barbara
     was looked at: of the `<tr>` elements with at least four cells and at
     least one `<td>`, those whose cell count is the most common across the
     portal's pages. It matched the reference count on all 71 development
     pages (57 Clark, 14 St. Johns), 2026-09-29.
   - ids: every row has a non-empty `native_id`, and no two rows on a page
     share one.
   - clean: every value is a string or None, and none contains markup.
   - dates: at least 90% of the non-null `issued_date` values look like a
     date.

   Reported per target and pooled: of the extractors the check accepts, the
   share the scorer fails (escapes: silent failures that would ship), and of
   those the scorer passes, the share the check rejects. Each with a Wilson
   interval, and with each check left out in turn.

2. **Best-of-k.** Per cell, k draws in a random order, keeping the first the
   check accepts: the chance the kept extractor is perfect, the mean
   purchase cost of the draws looked at, and cost per success, for k = 1 to
   5, beside pass@k (an oracle picking the working draw, Chen et al. 2021).
   Averaged over 2,000 orders with a fixed seed.

Writes `data/infer/verifier/checks.json` (one entry per extractor re-run,
keyed by source path and content hash, so a re-run only runs new ones),
writes the per-cell best-of-k figures to `data/infer/verifier/best_of_k.json`
for the results page, and prints the tables.
"""
import collections
import hashlib
import io
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import conformance as cf                             # noqa: E402
from permits import infer, rollup, stats             # noqa: E402
from permits.agent.verify import (CHECK_NAMES, check_page,   # noqa: E402
                                  expected_rows)

OUT = os.path.join(cf.ROOT, "data", "infer", "verifier")
CHECKS = os.path.join(OUT, "checks.json")
BEST_OF_K = os.path.join(OUT, "best_of_k.json")
VARIANCE = os.path.join(cf.OUT, "variance.json")
LEDGER = os.path.join(cf.OUT, "ledger.jsonl")

RAN = ("perfect", "imperfect")
NEVER_RAN = ("raised", "refused", "no_code", "exec_error")
KS = (1, 2, 3, 4, 5)
ORDERS = 2000
SEED = 20260929

# ------------------------------------------------------------ the draws
def load_draws():
    """Every v2 draw that counts toward a rate, with its cell."""
    with io.open(VARIANCE, encoding="utf-8") as fh:
        cells = json.load(fh)["cells"]
    out = []
    for key, c in sorted(cells.items()):
        if not key.endswith("v2"):
            continue
        cond = "hint|v2" if c.get("synth_hint") else "v2"
        for d in c["detail"]:
            if d["outcome"] in ("infra_error", "not_attempted"):
                continue
            out.append(dict(d, cell=key, condition=cond))
    return out


def purchase_costs():
    """What each scored v2 draw cost to buy, replays priced at their first
    purchase: {(target, model, condition): {"d00": usd}}."""
    ledger = infer.Ledger(LEDGER).rows()
    with io.open(VARIANCE, encoding="utf-8") as fh:
        v = json.load(fh)
    out = collections.defaultdict(dict)
    for r in rollup.rows_from_variance(v, ledger):
        if (r["experiment"] == "variance" and r["metric"] == "usd_purchase"
                and r["condition"].endswith("v2")):
            out[(r["target"], r["model"], r["condition"])][r["unit_id"]] = r["value"]
    return out


def digest(path):
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def run_checks(draws):
    """Re-run each extractor that ran everywhere and check its output.
    Cached by source path and content hash."""
    os.makedirs(OUT, exist_ok=True)
    cache = {}
    if os.path.exists(CHECKS):
        with io.open(CHECKS, encoding="utf-8") as fh:
            cache = json.load(fh)
    corpora = {}
    todo = [d for d in draws if d["outcome"] in RAN]
    fresh = 0
    for i, d in enumerate(todo):
        src = d["source"]
        key = "%s#%s" % (os.path.relpath(src, cf.ROOT), digest(src))
        if key in cache:
            d["failed"] = cache[key]
            continue
        t = cf.TARGETS[d["target"]]
        if t.key not in corpora:
            paths = [q for _, q in cf.stripped_corpus(t, cf.corpus(t))]
            corpora[t.key] = (paths, expected_rows([cf.read(q) for q in paths]))
        paths, want = corpora[t.key]
        res, err = cf.run_synth(src, paths, runner_name="_verifier_runner.py",
                                runner_dir=OUT)
        if err:
            failed = {"run": [err[:200]]}
        else:
            per = collections.defaultdict(list)
            for n, (page, w) in enumerate(zip(res, want, strict=True)):
                if not page["ok"]:
                    per["run"].append(n)
                    continue
                for name in check_page(page["rows"], w):
                    per[name].append(n)
            failed = dict(per)
        d["failed"] = cache[key] = failed
        fresh += 1
        if fresh % 25 == 0:
            print("  re-ran %d (%d of %d)" % (fresh, i + 1, len(todo)), flush=True)
            _save(cache)
    _save(cache)
    print("  re-ran %d extractors, %d from the cache" % (fresh, len(todo) - fresh))


def _save(cache):
    tmp = CHECKS + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
    os.replace(tmp, CHECKS)


def accepted(d, drop=()):
    """Whether the check accepts a draw, with the checks in `drop` left out."""
    if d["outcome"] not in RAN:
        return False
    return not any(k not in drop for k in d["failed"])


# ------------------------------------------------------------ reporting
def ci(k, n):
    if not n:
        return "     -        "
    lo, hi = stats.wilson(k, n)
    return "%5.1f%% [%4.1f, %4.1f]" % (100.0 * k / n, 100 * lo, 100 * hi)


def verifier_table(draws):
    print("\n== 1. The verifier on %d scored v2 draws" % len(draws))
    groups = [("all", draws)] + [
        (t, [d for d in draws if d["target"] == t])
        for t in ("clarkco", "stjohns", "santabarbara")]
    print("  %-13s %5s %6s %5s %6s %5s  %-22s %-22s %s"
          % ("target", "draws", "never", "ran", "perfect", "acc",
             "escapes / accepted", "rejected / perfect", "silent caught"))
    for name, ds in groups:
        ran = [d for d in ds if d["outcome"] in RAN]
        perf = [d for d in ran if d["outcome"] == "perfect"]
        imp = [d for d in ran if d["outcome"] == "imperfect"]
        acc = [d for d in ran if accepted(d)]
        esc = [d for d in acc if d["outcome"] != "perfect"]
        rej = [d for d in perf if not accepted(d)]
        caught = [d for d in imp if not accepted(d)]
        print("  %-13s %5d %6d %5d %6d %5d  %-22s %-22s %s"
              % (name, len(ds), len(ds) - len(ran), len(ran), len(perf),
                 len(acc), ci(len(esc), len(acc)), ci(len(rej), len(perf)),
                 ci(len(caught), len(imp))))
    print("  Santa Barbara is held out: the row rule was fixed on Clark and St. Johns.")

    print("\n  each check left out in turn (all targets):")
    ran = [d for d in draws if d["outcome"] in RAN]
    for drop in [()] + [(c,) for c in CHECK_NAMES]:
        acc = [d for d in ran if accepted(d, drop)]
        esc = sum(1 for d in acc if d["outcome"] != "perfect")
        rej = sum(1 for d in ran if d["outcome"] == "perfect" and not accepted(d, drop))
        print("    %-18s accepted %4d  escapes %-22s false rejects %d"
              % ("without " + drop[0] if drop else "all checks", len(acc),
                 ci(esc, len(acc)), rej))
    fails = collections.Counter()
    for d in ran:
        for k in d["failed"]:
            fails[(d["outcome"], k)] += 1
    print("  failed checks by outcome: %s" % dict(sorted(fails.items())))


def pass_at_k(n, c, k):
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def best_of_k(draws, costs):
    print("\n== 2. Best-of-k with the verifier as the selector, per cell")
    rng = random.Random(SEED)
    by_cell = collections.defaultdict(list)
    for d in draws:
        by_cell[(d["target"], d["model"], d["condition"])].append(d)
    print("  %-13s %-30s %-7s %3s  %s" % ("target", "model", "cond", "n",
          "   ".join("k=%d  succ   $/succ  (pass@k)" % k for k in (1, 3, 5))))
    ratio, gain, rescued, rows = [], [], 0, []
    for cell, ds in sorted(by_cell.items()):
        per = costs.get(cell, {})
        price = [per.get("d%02d" % d["draw"]) for d in ds]
        if len(ds) < 5 or any(p is None for p in price):
            continue
        n, c = len(ds), sum(1 for d in ds if d["outcome"] == "perfect")
        res = {}
        for k in KS:
            ok = spent = 0.0
            for _ in range(ORDERS):
                order = rng.sample(range(n), k)
                for j in order:
                    spent += price[j]
                    if accepted(ds[j]):
                        ok += ds[j]["outcome"] == "perfect"
                        break
            p, usd = ok / ORDERS, spent / ORDERS
            res[k] = (p, usd / p if p else None, pass_at_k(n, c, k))
        rows.append({"target": cell[0], "model": cell[1], "condition": cell[2],
                     "n": n, "perfect": c,
                     "k": {str(k): {"success": round(res[k][0], 4),
                                    "usd_per_success": (round(res[k][1], 6)
                                                        if res[k][1] else None),
                                    "pass_at_k": round(res[k][2], 4)}
                           for k in KS}})
        cols = []
        for k in (1, 3, 5):
            p, cps, pk = res[k]
            cols.append("%4.2f %8s  (%4.2f)" % (p, "%.3f" % cps if cps else "-", pk))
        print("  %-13s %-30s %-7s %3d  %s" % (cell[0], cell[1][:30], cell[2], n,
                                             "   ".join(cols)))
        if 0 < c < n:
            one = (sum(price) / n) / (c / n)
            # No success at k = 5 happens when the verifier rejects the
            # cell's only perfect draws: no cost per success to compare.
            if res[5][1] is not None:
                ratio.append(res[5][1] / one)
            gain.append(res[5][0] - c / n)
        elif c == 0 and res[5][0]:
            rescued += 1
    if ratio:
        ratio.sort()
        gain.sort()
        print("  %d cells with 0 < pass@1 < 1: best-of-5 success minus pass@1, median %+.2f"
              " (range %+.2f to %+.2f); best-of-5 cost per success over one-shot's,"
              " median %.2f (range %.2f to %.2f)"
              % (len(ratio), gain[len(gain) // 2], gain[0], gain[-1],
                 ratio[len(ratio) // 2], ratio[0], ratio[-1]))
    print("  cells at pass@1 = 0 that best-of-k rescues: %d" % rescued)
    tmp = BEST_OF_K + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"source": "spikes/verifier_offline.py", "seed": SEED, "orders": ORDERS,
                   "cells": rows}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, BEST_OF_K)
    print("  succ: chance the kept extractor is perfect (0 if none of k is accepted);")
    print("  $/succ: mean purchase cost of the draws looked at over succ; pass@k: an oracle's.")


def main():
    draws = load_draws()
    print("%d scored v2 draws in %d cells" % (len(draws), len({d["cell"] for d in draws})))
    run_checks(draws)
    for d in draws:
        d.setdefault("failed", {"never ran": []})
    verifier_table(draws)
    best_of_k(draws, purchase_costs())


if __name__ == "__main__":
    main()
