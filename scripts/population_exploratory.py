# -*- coding: utf-8 -*-
"""The population run's exploratory results, none pre-registered, from the
released run records alone:

    python scripts/population_exploratory.py
    python scripts/population_exploratory.py --records <release>/runs/episodes.jsonl

1. **The agent at the loop's cap** (stage 6, run `eval-pop-1x`) against the
   loop (stage 4) and the agent at its best-of-5 cap (stage 5), cell by
   cell: a cell is a portal and a cheap model, the cells with room. Rates are
   per episode, so stage 6's 3 episodes a cell and stage 4's 5 compare
   directly. Differences are means over cells with a 95% interval from
   resampling portals (2,000 times).
2. **pass@k and best-of-k** for the one-shot arms: pass@k is the chance
   that at least one of k draws is perfect (the unbiased estimator of Chen
   et al. 2021, from n stored draws); best-of-k is the chance that the first
   draw the check accepts among k is perfect, which is what a pipeline
   without the answer key gets. The gap between them is what the check
   costs.
3. **How agent and loop episodes end**: the stop reason (submitted, or the
   spending cap) crossed with what the episode held.

All three are unweighted over the 17 test portals; the weighted population
views are the pre-registered analysis's (`scripts/population_analysis.py`).
Every figure is also given without Boise and Philadelphia, where the
check's record count is wrong.
"""
import argparse
import collections
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "data", "release", "extractor-bench-v1", "runs",
                       "episodes.jsonl")
CHEAP = ("openai/gpt-oss-120b", "google/gemini-3.5-flash-lite",
         "deepseek/deepseek-v4-flash", "openai/gpt-6-luna",
         "xiaomi/mimo-v2.6-flash")
STRONG = ("claude-opus-5-5", "google/gemini-3.8-flash")
CHECK_MISSES = ("p0104", "p0319")
SCORED = ("perfect", "imperfect", "raised", "exec_error", "refused",
          "no_code")
ARMS = {4: "loop", 5: "agent at best-of-5", 6: "agent at loop cap"}


def load(path):
    recs = [json.loads(x) for x in open(path, encoding="utf-8")]
    return [r for r in recs if r["outcome"] in SCORED]


def by_cell(recs, stage):
    out = collections.defaultdict(list)
    for r in recs:
        if r["stage"] == stage:
            out[(r["portal"], r["model"])].append(r)
    return out


def rate(rs, key="trusted"):
    return sum(bool(r[key]) for r in rs) / float(len(rs))


def summary(rs):
    n = len(rs)
    sub = [r for r in rs if r.get("submitted")]
    trusted = sum(bool(r["trusted"]) for r in rs)
    wrong = sum(1 for r in sub if r["accepted"] and r["outcome"] != "perfect")
    acc = sum(1 for r in sub if r["accepted"])
    return {"episodes": n, "trusted": trusted / float(n),
            "submitted": len(sub) / float(n),
            "wrong_of_accepted_submitted": wrong / float(acc) if acc else None,
            "list_usd": sum(r["list_usd"] for r in rs) / n,
            "usd": sum(r["usd"] for r in rs) / n,
            "list_per_trusted": (sum(r["list_usd"] for r in rs) / trusted
                                 if trusted else None),
            "usd_per_trusted": (sum(r["usd"] for r in rs) / trusted
                                if trusted else None)}


def paired(a, b, portals, rng, reps):
    """Mean over shared cells of a's trusted rate minus b's, and a 95%
    interval from resampling portals."""
    cells = sorted(set(a) & set(b))
    diff = {c: rate(a[c]) - rate(b[c]) for c in cells}
    by_p = collections.defaultdict(list)
    for (p, _m), d in diff.items():
        by_p[p].append(d)
    ps = sorted(p for p in by_p if p in portals)
    point = (sum(d for p in ps for d in by_p[p])
             / sum(len(by_p[p]) for p in ps)) if ps else None
    boots = []
    for _ in range(reps):
        draw = [rng.choice(ps) for _ in ps]
        boots.append(sum(d for p in draw for d in by_p[p])
                     / sum(len(by_p[p]) for p in draw))
    boots.sort()
    return {"diff": point, "ci": [boots[int(0.025 * reps)],
                                  boots[int(0.975 * reps) - 1]],
            "cells": sum(len(by_p[p]) for p in ps)}


def pass_at_k(n, c, k):
    """Chen et al. (2021): 1 - C(n-c, k) / C(n, k)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def best_of_k(draws, k):
    """Mean over the n!/(n-k)! orderings' first k draws, exactly: the chance
    that the first accepted draw of k random draws is perfect. Draws are
    (accepted, perfect)."""
    n = len(draws)
    acc_ok = sum(1 for a, p in draws if a and p)
    acc = sum(1 for a, _ in draws if a)
    rej = n - acc
    if not acc:
        return 0.0
    # P(at least one accepted among k) * P(that first accepted is perfect),
    # by symmetry the first accepted is a uniform pick of the accepted ones.
    p_any = 1.0 - (math.comb(rej, k) / math.comb(n, k) if rej >= k else 0.0)
    return p_any * acc_ok / float(acc)


def oneshot_curves(recs, portals):
    out = {}
    for stage, models in ((2, CHEAP), (3, STRONG)):
        cells = by_cell(recs, stage)
        for m in models:
            cs = [rs for (p, mm), rs in cells.items()
                  if mm == m and p in portals]
            if not cs:
                continue
            nmin = min(len(rs) for rs in cs)
            curve = []
            for k in range(1, nmin + 1):
                pk = sum(pass_at_k(len(rs), sum(r["outcome"] == "perfect"
                                                 for r in rs), k)
                         for rs in cs) / len(cs)
                bk = sum(best_of_k([(bool(r["accepted"]),
                                     r["outcome"] == "perfect") for r in rs], k)
                         for rs in cs) / len(cs)
                curve.append({"k": k, "pass_at_k": pk, "best_of_k": bk})
            out[m] = curve
    return out


def ending(r):
    """One episode's ending, for the failure taxonomy."""
    if r.get("submitted"):
        if r["trusted"]:
            return "submitted, trusted"
        if r["accepted"]:
            return "submitted, accepted but wrong"
        return ("submitted, rejected but perfect" if r["outcome"] == "perfect"
                else "submitted, rejected")
    held = r["outcome"]
    if held == "perfect":
        return ("cap hit holding a perfect extractor the check accepts"
                if r["accepted"] else
                "cap hit holding a perfect extractor the check rejects")
    if held == "no_code":
        return "cap hit before any extractor"
    if held in ("raised", "exec_error"):
        return "cap hit holding an extractor that crashes"
    if held == "refused":
        return "cap hit holding an extractor the sandbox refuses"
    return "cap hit holding a wrong extractor"


def taxonomy(recs, portals):
    out = {}
    for stage, label in ARMS.items():
        rs = [r for r in recs if r["stage"] == stage and r["portal"] in portals]
        if rs:
            c = collections.Counter(ending(r) for r in rs)
            out[label] = {"episodes": len(rs),
                          "endings": dict(c.most_common()),
                          "stop": dict(collections.Counter(
                              r.get("stop") for r in rs))}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--records", default=RECORDS)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261103)
    ap.add_argument("--out", default=None,
                    help="write the results as JSON here")
    args = ap.parse_args(argv)
    recs = load(args.records)
    allp = sorted({r["portal"] for r in recs})
    views = {"all 17": set(allp),
             "without Boise and Philadelphia": set(allp) - set(CHECK_MISSES)}
    res = {}
    for view, portals in views.items():
        rng = random.Random(args.seed)
        cells = {s: by_cell(recs, s) for s in ARMS}
        arms = {}
        for s, label in ARMS.items():
            for m in (*CHEAP, "pooled"):
                rs = [r for (p, mm), x in cells[s].items() for r in x
                      if p in portals and (m == "pooled" or mm == m)]
                if rs:
                    arms["%s | %s" % (label, m.split("/")[-1])] = summary(rs)
        res[view] = {
            "arms": arms,
            "agent at loop cap minus loop": paired(cells[6], cells[4],
                                                   portals, rng, args.boot),
            "agent at loop cap minus agent at best-of-5": paired(
                cells[6], cells[5], portals, rng, args.boot),
            "pass_at_k": oneshot_curves(recs, portals),
            "taxonomy": taxonomy(recs, portals)}
    report(res)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
    return 0


def report(res):
    for view, r in res.items():
        print("\n== %s" % view)
        print("%-36s %8s %8s %9s %10s %12s %12s" % (
            "arm | model", "episodes", "trusted", "submitted", "wrong/acc",
            "list/trusted", "billed/trust"))
        for k, s in r["arms"].items():
            print("%-36s %8d %8.3f %9.3f %10s %12s %12s" % (
                k, s["episodes"], s["trusted"], s["submitted"],
                "%.3f" % s["wrong_of_accepted_submitted"]
                if s["wrong_of_accepted_submitted"] is not None else "-",
                "$%.4f" % s["list_per_trusted"] if s["list_per_trusted"]
                else "none",
                "$%.4f" % s["usd_per_trusted"] if s["usd_per_trusted"]
                else "none"))
        for k in ("agent at loop cap minus loop",
                  "agent at loop cap minus agent at best-of-5"):
            d = r[k]
            print("%s: %+.3f [%+.3f, %+.3f] over %d cells"
                  % (k, d["diff"], d["ci"][0], d["ci"][1], d["cells"]))
        print("pass@k / best-of-k (mean over portals):")
        for m, curve in r["pass_at_k"].items():
            print("  %-24s %s" % (m.split("/")[-1], "  ".join(
                "k=%d %.2f/%.2f" % (c["k"], c["pass_at_k"], c["best_of_k"])
                for c in curve if c["k"] in (1, 2, 3, 5, 10))))
        print("how episodes end:")
        for arm, t in r["taxonomy"].items():
            print("  %s (%d episodes, stop %s)" % (arm, t["episodes"],
                                                   t["stop"]))
            for e, n in t["endings"].items():
                print("    %4d  %5.1f%%  %s" % (n, 100.0 * n / t["episodes"],
                                                e))


if __name__ == "__main__":
    sys.exit(main())
