# -*- coding: utf-8 -*-
"""Every table in the v2 run's results report. No model calls.

    python spikes/v2_results.py > out.md
    python spikes/v2_results.py --caption     # also the caption-table test

Reads what the results page reads: the cells, draws and pairs that
`scripts/export_results.py` builds from `variance.json`, the ledger and the
field audit, so the report and the page cannot disagree. Per-draw detail
(recall, precision, reasoning tokens, seconds) comes from the same records.

Sections follow docs/evidence/2026-09-27-v2-run-preregistration.md: the
five questions in order, with the analysis it fixed; then the reporting
additions of docs/evidence/2026-09-28-v2-results-and-visualization-plan.md,
labelled as not pre-registered; then the method appendix.

`--caption` re-runs every silently empty Clark extractor on the Clark pages
with the small table inside the grid's caption removed, and counts the ones
that then return rows and the ones that pass. Exploratory. It executes
stored extractors in a subprocess, as the harness does, and writes the
counts to `data/infer/verifier/caption.json` for the results page.
"""
import argparse
import collections
import io
import json
import math
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import export_results as X                                  # noqa: E402
from permits import fileio, harness as H, infer, models     # noqa: E402
from permits import rollup, sandbox                         # noqa: E402
from permits.stats import newcombe, wilson                  # noqa: E402

INFER = os.path.join(ROOT, "data", "infer")
SEED = 20261001
CAPTION_OUT = os.path.join(INFER, "verifier", "caption.json")
Z = 1.959964


# ------------------------------------------------------------- statistics
def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra)
                    * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def comb(n, k):
    return math.comb(n, k) if 0 <= k <= n else 0


def pass_at(n, c, k):
    """At least one of k draws passes (Chen et al. 2021, unbiased)."""
    if k > n:
        return None
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat(n, c, k):
    """All k draws pass (Yao et al. 2024, pass^k)."""
    if k > n:
        return None
    return comb(c, k) / comb(n, k)


def mde(n1, n2, p=0.5):
    """Minimum detectable difference at 80% power, two-sided 5%, near p."""
    return (Z + 0.841621) * math.sqrt(p * (1 - p) * (1.0 / n1 + 1.0 / n2))


# ------------------------------------------------------------ formatting
def pct(x):
    return "-" if x is None else "%.2f" % x


def ci(c):
    return "[%.2f, %.2f]" % tuple(c) if c else "-"


def usd(x):
    if x is None:
        return "-"
    return "$%.4f" % x if x < 0.1 else "$%.3f" % x


def table(head, rows):
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" if i == 0 else "---:"
                          for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def h(title):
    print("\n## %s\n" % title)


# ------------------------------------------------------------------ data
class Run:
    def __init__(self):
        self.v = fileio.read_json(os.path.join(INFER, "variance.json"))
        self.ledger = infer.Ledger(os.path.join(INFER, "ledger.jsonl")).rows()
        self.audit = fileio.read_json(
            os.path.join(INFER, "verifier", "field_audit.json"))
        self.data = X.build(self.v, self.ledger, self.audit)
        self.cells = {(c["target"], c["model"], c["arm"], c["protocol"]): c
                      for c in self.data["cells"]}
        self.bought = rollup.purchases(self.v, self.ledger)
        self.names = {m["id"]: m["name"] for m in self.data["models"]}
        self.price = {m["id"]: m["price_out"] for m in self.data["models"]}
        self.tier = {m["id"]: m["tier"] for m in self.data["models"]}

    def cell(self, target, model, arm="baseline", protocol="v2"):
        return self.cells.get((target, model, arm, protocol))

    def draws(self, c):
        """Stored draws of an exported cell, excluded draws left out."""
        cell = self.v["cells"][c["key"]]
        return [d for d in rollup.draws_of(cell)
                if (c["key"], d.draw) not in rollup.EXCLUDED]

    def seconds(self, c, d):
        i = self.bought.get((c["key"], d.draw))
        return self.ledger[i].seconds if i is not None else None

    def name(self, m):
        return self.names[m]


def near_miss(d):
    """A failing draw with recall at least 0.98 at precision 1.0. Recall is
    the mean over the target's pages, which is what `variance.json` keeps
    beside the worst page. Clark's 57 pages hold 561 records, about 10
    each, so the mean is close to the share of all records."""
    return (d.outcome == "imperfect" and (d.recall_mean or 0) >= 0.98
            and d.precision_min == 1.0)


def format_failure(d):
    return d.outcome in ("no_code", "refused")


# ------------------------------------------------------------- sections
def summary(R):
    h("Run summary")
    v2 = [r for r in R.ledger if r.protocol == "v2"
          and r.call_class == "synthesis" and r.tag.endswith("/var")]
    ok = [r for r in v2 if r.ok]
    cells = [c for c in R.data["cells"] if c["protocol"] == "v2"]
    scored = sum(c["n"] for c in cells)
    print("- v2 cells exported: %d; scored draws: %d; perfect: %d"
          % (len(cells), scored, sum(c["k"] for c in cells)))
    print("- v2 variance synthesis calls in the ledger: %d (%d ok, %d failed);"
          " billed $%.2f, of which failed calls $%.2f"
          % (len(v2), len(ok), len(v2) - len(ok), sum(r.usd for r in v2),
             sum(r.usd for r in v2 if not r.ok)))
    print("- agent smoke runs, not part of this run: $%.2f"
          % sum(r.usd for r in R.ledger if r.protocol == "v2"
                and r.tag.startswith("smoke-")))
    print("- infra-error draws: %d; re-drawn after a cut-off: %d; still "
          "truncated: %d; excluded: %d (%s)"
          % (sum(c["draws_infra_error"] for c in cells),
             sum(c["draws_redrawn"] for c in cells),
             sum(c["draws_truncated"] for c in cells),
             len(R.data["excluded"]),
             ", ".join("%s d%d" % (e["cell"], e["draw"])
                       for e in R.data["excluded"])))
    print("- first and last v2 synthesis call: %s, %s"
          % (min(r.at for r in v2), max(r.at for r in v2)))


def q1(R, target="clarkco", title="Question 1: Clark baseline pass@1"):
    h(title)
    rows, cs = [], []
    for group in (X.ROSTER, X.V1_RERUN):
        for m in sorted(group, key=lambda m: (R.price[m], m)):
            c = R.cell(target, m)
            if c is None:
                rows.append([R.name(m), R.tier[m], "$%.2f" % R.price[m],
                             "no cell"] + [""] * 8)
                continue
            ds = R.draws(c)
            fails = [d for d in ds if d.scored() and d.outcome != "perfect"]
            cs.append(c)
            rows.append([
                R.name(m) + ("" if m in X.ROSTER else " (v1 model)"),
                R.tier[m], "$%.2f" % R.price[m],
                "%d/%d" % (c["k"], c["n"]), "%s %s" % (pct(c["rate"]),
                                                       ci(c["ci95"])),
                ("%d/%d %s" % (c["k_field"], c["n"], ci(c["ci95_field"]))
                 if c["k_field"] is not None else "-"),
                sum(1 for d in fails if near_miss(d)),
                sum(1 for d in fails if d.outcome == "imperfect"),
                sum(1 for d in fails if format_failure(d)),
                sum(1 for d in fails if d.outcome in ("raised",
                                                      "exec_error")),
                usd(c["usd_per_draw"]), usd(c["usd_per_success"])])
    print(table(["model", "tier", "$/M out", "k/n", "pass@1 [95%]",
                 "field-level", "near miss", "silent", "format", "raised",
                 "$/draw", "$/success"], rows))
    roster = [c for c in cs if c["model"] in X.ROSTER]
    sep = [(a, b) for a in roster for b in roster
           if a["ci95"][0] > b["ci95"][1]]
    print("\nRoster pairs whose intervals do not overlap: %d of %d. "
          "Models whose lower bound is above some other model's upper bound:"
          % (len(sep), len(roster) * (len(roster) - 1) // 2))
    above = collections.Counter(a["model"] for a, _ in sep)
    for m, n in above.most_common():
        print("  - %s beats %d" % (R.name(m), n))
    return cs


def cps_interval(c):
    """Cost per success from the Wilson bounds (the pre-registered
    interval): cost per draw over the upper and lower bound."""
    if not c["k"] or c["usd_per_draw"] is None:
        return None
    lo, hi = c["ci95"]
    return (c["usd_per_draw"] / hi, c["usd_per_draw"] / lo)


def q2(R):
    h("Question 2: price per token against cost per success, Clark baseline")
    cs = [R.cell("clarkco", m) for m in X.ROSTER]
    cs = [c for c in cs if c]
    worked = sorted([c for c in cs if c["k"]],
                    key=lambda c: c["usd_per_success"])
    never = [c for c in cs if not c["k"]]
    rows = []
    for i, c in enumerate(worked, 1):
        iv = cps_interval(c)
        rows.append([i, R.name(c["model"]), "$%.2f" % R.price[c["model"]],
                     "%d/%d" % (c["k"], c["n"]), usd(c["usd_per_success"]),
                     "%s to %s" % (usd(iv[0]), usd(iv[1])),
                     usd(c["usd_per_field_success"])])
    for c in sorted(never, key=lambda c: R.price[c["model"]]):
        rows.append(["last, tied", R.name(c["model"]),
                     "$%.2f" % R.price[c["model"]], "0/%d" % c["n"],
                     "none", "-", "-"])
    print(table(["rank", "model", "$/M out", "k/n", "$/success",
                 "interval (Wilson bounds)", "$/field success"], rows))
    # Opposite order with non-overlapping intervals: a dearer model per
    # token that is cheaper per success, the interval of each clear of the
    # other's. Models at 0/n are last and have no interval.
    rev = []
    for a in worked:
        for b in worked:
            if R.price[a["model"]] > R.price[b["model"]] and \
                    a["usd_per_success"] < b["usd_per_success"]:
                ia, ib = cps_interval(a), cps_interval(b)
                if ia[1] < ib[0]:
                    rev.append((a, b, ib[0] / ia[1]))
    print("\nReversals with non-overlapping intervals (dearer per token, "
          "cheaper per success): %d" % len(rev))
    for a, b, gap in sorted(rev, key=lambda t: -t[2])[:12]:
        print("  - %s ($%.2f/M, %s per success) vs %s ($%.2f/M, %s)"
              % (R.name(a["model"]), R.price[a["model"]],
                 usd(a["usd_per_success"]), R.name(b["model"]),
                 R.price[b["model"]], usd(b["usd_per_success"])))
    # Secondary: the intervals method's settled pairs, roster only.
    pairs = [p for p in R.data["pairs"] if p["target"] == "clarkco"
             and p["arm"] == "baseline" and p["protocol"] == "v2"
             and p["a"] in X.ROSTER and p["b"] in X.ROSTER]
    settled = [p for p in pairs if p["settled"]]
    srev = [p for p in settled if R.price[p["a"]] > R.price[p["b"]]]
    fdr = (sum(1 - min(p["p_a_cheaper"].values()) for p in settled)
           / len(settled)) if settled else None
    print("\nIntervals method (simulated, P >= 0.975 under both priors), "
          "roster pairs on Clark baseline with n >= 3: %d compared, %d "
          "settled, %d settled reversals of the price order. Expected share "
          "of wrong calls among the settled (exploratory): %.4f"
          % (len(pairs), len(settled), len(srev), fdr or 0))
    for p in sorted(srev, key=lambda p: -p["ratio"]["jeffreys"][1])[:10]:
        print("  - %s cheaper per success than %s: %.1fx [%.1f, %.1f]"
              % (R.name(p["a"]), R.name(p["b"]), *[
                  p["ratio"]["jeffreys"][i] for i in (1, 0, 2)]))
    allp = [p for p in R.data["pairs"] if p["settled"]]
    print("\nAll pairs on the page (every target, arm, protocol): %d, "
          "settled %d; expected wrong calls among settled: %.2f"
          % (len(R.data["pairs"]), len(allp),
             sum(1 - min(p["p_a_cheaper"].values()) for p in allp)))


def q3(R):
    h("Question 3: Santa Barbara (held out) beside Clark")
    rows, a, b = [], [], []
    for m in sorted(X.ROSTER, key=lambda m: (R.price[m], m)):
        cl, sb = R.cell("clarkco", m), R.cell("santabarbara", m)
        rows.append([R.name(m), "%d/%d %s" % (cl["k"], cl["n"], ci(cl["ci95"])),
                     ("%d/%d %s" % (sb["k"], sb["n"], ci(sb["ci95"]))
                      if sb else "no cell"),
                     ("%d/%d" % (sb["k_field"], sb["n"])
                      if sb and sb["k_field"] is not None else "-")])
        if sb and sb["n"]:
            a.append(cl["rate"])
            b.append(sb["rate"])
    print(table(["model", "Clark", "Santa Barbara", "SB field-level"], rows))
    pass_fail = [m for m in X.ROSTER if R.cell("santabarbara", m)
                 and R.cell("clarkco", m)["ci95"][0] >= 0.5
                 and R.cell("santabarbara", m)["k"] == 0]
    fail_pass = [m for m in X.ROSTER if R.cell("santabarbara", m)
                 and R.cell("clarkco", m)["k"] == 0
                 and R.cell("santabarbara", m)["ci95"][0] >= 0.5]
    print("\nPass Clark reliably (lower bound >= 0.5) and fail Santa Barbara "
          "reliably (0/n): %d %s" % (len(pass_fail),
                                     [R.name(m) for m in pass_fail]))
    print("The reverse (0 on Clark, lower bound >= 0.5 on Santa Barbara): "
          "%d %s" % (len(fail_pass), [R.name(m) for m in fail_pass]))
    rho = spearman(a, b)
    rng = random.Random(SEED)
    boots = []
    for _ in range(5000):
        idx = [rng.randrange(len(a)) for _ in a]
        r = spearman([a[i] for i in idx], [b[i] for i in idx])
        if not math.isnan(r):
            boots.append(r)
    boots.sort()
    print("Spearman rho, Clark against Santa Barbara, %d models: %.2f, "
          "bootstrap 95%% [%.2f, %.2f] (5,000 resamples of models)"
          % (len(a), rho, boots[int(.025 * len(boots))],
             boots[int(.975 * len(boots))]))


def q4(R):
    h("Question 4: v2 minus v1, the seven re-run models")
    rows = []
    for m in X.V1_RERUN:
        for t in ("clarkco", "stjohns"):
            c2 = R.cell(t, m)
            c1 = R.cell(t, m, protocol="v1")
            if not (c1 and c2 and c1["n"] and c2["n"]):
                rows.append([R.name(m), t, "-", "-", "-", ""])
                continue
            d, lo, hi = newcombe(c2["k"], c2["n"], c1["k"], c1["n"])
            rows.append([R.name(m), t, "%d/%d" % (c1["k"], c1["n"]),
                         "%d/%d" % (c2["k"], c2["n"]),
                         "%+.2f [%+.2f, %+.2f]" % (d, lo, hi),
                         "claimed" if lo > 0 or hi < 0 else ""])
    print(table(["model", "target", "v1", "v2", "v2 - v1 (Newcombe)",
                 "effect"], rows))
    c1 = R.cell("clarkco", "moonshotai/kimi-k2-thinking", protocol="v1")
    if c1:
        ds = R.draws(c1)
        k = sum(1 for d in ds if d.outcome == "perfect" and d.draw != 7)
        n = sum(1 for d in ds if d.scored() and d.draw != 7)
        c2 = R.cell("clarkco", "moonshotai/kimi-k2-thinking")
        d, lo, hi = newcombe(c2["k"], c2["n"], k, n)
        print("\nkimi-k2-thinking v1 Clark as published %d/%d; without draw "
              "7 (host error scored no_code, deviation 2) %d/%d; v2 - v1 then"
              " %+.2f [%+.2f, %+.2f]" % (c1["k"], c1["n"], k, n, d, lo, hi))
    print("\nMinimum detectable difference near 50%%, 80%% power, two-sided "
          "5%%: 10 v 10 %.0f points, 10 v 20 %.0f, 20 v 20 %.0f"
          % (100 * mde(10, 10), 100 * mde(10, 20), 100 * mde(20, 20)))


def q5(R):
    h("Question 5: the hint, Clark")
    rows = []
    for m in X.ROSTER + X.V1_RERUN:
        ch = R.cell("clarkco", m, arm="hint")
        cb = R.cell("clarkco", m)
        if not ch:
            continue
        d, lo, hi = newcombe(ch["k"], ch["n"], cb["k"], cb["n"])
        hb = ", ".join("%s %d" % kv for kv in sorted(cb["hosts"].items()))
        hh = ", ".join("%s %d" % kv for kv in sorted(ch["hosts"].items()))
        rows.append([R.name(m), "%d/%d" % (cb["k"], cb["n"]),
                     "%d/%d" % (ch["k"], ch["n"]),
                     "%+.2f [%+.2f, %+.2f]" % (d, lo, hi),
                     "claimed" if lo > 0 or hi < 0 else "", hb, hh])
    print(table(["model", "baseline", "hint", "hint - baseline (Newcombe)",
                 "effect", "baseline hosts", "hint hosts"], rows))
    print("\n%d models. Minimum detectable difference near 50%%: 10 v 10 "
          "%.0f points, 10 v 20 %.0f." % (len(rows), 100 * mde(10, 10),
                                          100 * mde(10, 20)))


def field_level(R):
    h("Field-level pass@1 (deviation 4)")
    by = collections.defaultdict(lambda: [0, 0])
    fields = collections.defaultdict(collections.Counter)
    for e in R.audit:
        if (e["cell"], e["draw"]) in rollup.EXCLUDED or "error" in e:
            continue
        by[e["target"]][0] += 1
        by[e["target"]][1] += bool(rollup.field_perfect(e))
        for f, n in e["disagree"].items():
            if n:
                fields[e["target"]][f] += 1
    for t, (n, k) in sorted(by.items()):
        print("- %s: %d of %d perfect draws also agree on every field; "
              "fields disagreeing, in draws: %s"
              % (t, k, n, dict(fields[t].most_common())))
    print("- audit entries with an error: %d"
          % sum(1 for e in R.audit if "error" in e))
    moved = []
    for c in R.data["cells"]:
        if c["protocol"] == "v2" and c["k_field"] is not None \
                and c["k_field"] < c["k"]:
            moved.append([R.name(c["model"]), c["target"], c["arm"],
                          "%d/%d" % (c["k"], c["n"]),
                          "%d/%d" % (c["k_field"], c["n"])])
    print()
    print(table(["model", "target", "arm", "pass@1", "field-level"],
                sorted(moved, key=lambda r: (r[1], r[0]))))


def both_rules(R):
    """Questions 1-3's claims under the field-level rule (deviation 4)."""
    h("Questions 1-3 under the field-level rule (deviation 4)")
    cl = [R.cell("clarkco", m) for m in X.ROSTER]
    for name, kf in (("pass@1", "k"), ("field-level", "k_field")):
        iv = {c["model"]: wilson(c[kf], c["n"]) for c in cl}
        sep = sum(1 for a in cl for b in cl
                  if iv[a["model"]][0] > iv[b["model"]][1])
        cps = {c["model"]: (c["usd_per_draw"] / iv[c["model"]][1],
                            c["usd_per_draw"] / iv[c["model"]][0])
               for c in cl if c[kf]}
        point = {c["model"]: c["usd_per_draw"] * c["n"] / c[kf]
                 for c in cl if c[kf]}
        rev = sum(1 for a in cps for b in cps
                  if R.price[a] > R.price[b] and point[a] < point[b]
                  and cps[a][1] < cps[b][0])
        sb = {m: R.cell("santabarbara", m) for m in X.ROSTER}
        xs = [c[kf] / c["n"] for c in cl if sb[c["model"]]]
        ys = [sb[c["model"]][kf] / sb[c["model"]]["n"] for c in cl
              if sb[c["model"]]]
        pf = sum(1 for c in cl if sb[c["model"]]
                 and wilson(c[kf], c["n"])[0] >= 0.5
                 and sb[c["model"]][kf] == 0)
        fp = sum(1 for c in cl if sb[c["model"]] and c[kf] == 0
                 and wilson(sb[c["model"]][kf], sb[c["model"]]["n"])[0]
                 >= 0.5)
        print("- %s: Q1 separable roster pairs %d; Q2 reversals with "
              "non-overlapping intervals %d; Q3 pass-Clark-fail-SB %d, "
              "reverse %d, Spearman %.2f"
              % (name, sep, rev, pf, fp, spearman(xs, ys)))


def missing(R):
    h("Missing draws, by cause (reporting addition)")
    rows = []
    for c in R.data["cells"]:
        if c["protocol"] != "v2":
            continue
        cell = R.v["cells"][c["key"]]
        ds = rollup.draws_of(cell)
        never = sum(1 for d in ds if d.outcome == "not_attempted")
        infra = c["draws_infra_error"]
        if not (never or infra or c["draws_excluded"]):
            continue
        n, k = c["n"], c["k"]
        b = ""
        if infra:
            b = "%d/%d %s to %d/%d %s" % (
                k, n + infra, ci(wilson(k, n + infra)), k + infra, n + infra,
                ci(wilson(k + infra, n + infra)))
        rows.append([R.name(c["model"]), c["target"], c["arm"],
                     "%d/%d %s" % (k, n, ci(c["ci95"])), infra, never,
                     c["draws_excluded"], b])
    print(table(["model", "target", "arm", "reported", "host failure",
                 "never attempted", "excluded", "bounds (host failures as "
                 "fail, as pass)"], rows))


def reliability(R):
    h("Reliability and economics, Clark baseline (reporting addition)")
    rows = []
    for m in sorted(X.ROSTER + X.V1_RERUN, key=lambda m: (R.price[m], m)):
        c = R.cell("clarkco", m)
        ds = [d for d in R.draws(c) if d.scored()]
        n, k = c["n"], c["k"]
        secs = [R.seconds(c, d) for d in ds]
        tps = (sum(secs) / n / (k / n)
               if k and None not in secs else None)
        silent = sum(1 for d in ds if d.outcome == "imperfect")
        rows.append([R.name(m), "%d/%d" % (k, n)]
                    + [pct(pass_at(n, k, j)) for j in (3, 5)]
                    + [pct(pass_hat(n, k, j)) for j in (3, 5)]
                    + ["%.2f" % (silent / n), usd(c["usd_per_success"]),
                       "-" if tps is None else "%.0f s" % tps])
    print(table(["model", "k/n", "pass@3", "pass@5", "pass^3", "pass^5",
                 "silent rate", "$/success", "time/success"], rows))


def reasoning(R):
    h("Reasoning length by outcome, and the hint's effect on it "
      "(exploratory)")
    by = collections.defaultdict(list)
    hint = collections.defaultdict(lambda: ([], []))
    for c in R.data["cells"]:
        if c["protocol"] != "v2":
            continue
        for d in R.draws(c):
            if not d.scored() or d.reasoning_tokens is None:
                continue
            by[rollup.failure_mode(d)].append(d.reasoning_tokens)
            if c["target"] == "clarkco":
                hint[c["model"]][c["arm"] == "hint"].append(d.reasoning_tokens)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None  # noqa: E731
    for mode, xs in sorted(by.items()):
        print("- %s: %d draws, median %s reasoning tokens"
              % (mode, len(xs), med(xs)))
    ratios = []
    for m, (b, hh) in sorted(hint.items()):
        if b and hh and med(b):
            ratios.append((med(hh) / med(b), m))
    ratios.sort()
    if ratios:
        print("- hint over baseline, median reasoning tokens per model "
              "(%d models): median ratio %.2f, range %.2f (%s) to %.2f (%s)"
              % (len(ratios), ratios[len(ratios) // 2][0], ratios[0][0],
                 R.name(ratios[0][1]), ratios[-1][0], R.name(ratios[-1][1])))


def hosts(R):
    h("Method appendix: settings, hosts, re-draws, host failures")
    rows = []
    for m in X.ROSTER + X.V1_RERUN:
        s = models.get(m)
        cs = [c for c in R.data["cells"] if c["model"] == m
              and c["protocol"] == "v2"]
        hs = collections.Counter()
        for c in cs:
            hs.update(c["hosts"])
        rows.append([R.name(m), s.effort or "default",
                     "-" if s.temperature is None else s.temperature,
                     "-" if s.top_p is None else s.top_p,
                     sum(c["draws_redrawn"] for c in cs),
                     sum(c["draws_truncated"] for c in cs),
                     sum(c["draws_infra_error"] for c in cs),
                     usd(sum(c["usd_failed_calls"] or 0 for c in cs)),
                     ", ".join("%s %d" % kv for kv in hs.most_common())])
    print(table(["model", "effort sent", "temperature", "top_p", "re-drawn",
                 "still cut off", "host failures", "$ failed calls",
                 "hosts (scored draws)"], rows))
    fails = collections.Counter()
    for r in R.ledger:
        if r.protocol == "v2" and not r.ok and r.tag.endswith("/var"):
            fails[(r.model, r.host or "?")] += 1
    print("\nFailed v2 variance calls by model and host: %s"
          % ", ".join("%s on %s %d" % (infer.short_model(m), hst, n)
                      for (m, hst), n in fails.most_common()))


def deepseek_hosts(R):
    h("deepseek-v4-flash by host (failure case 10)")
    m = "deepseek/deepseek-v4-flash"
    rows = []
    for c in R.data["cells"]:
        if c["model"] != m or c["protocol"] != "v2":
            continue
        by = collections.defaultdict(lambda: [0, 0])
        for d in R.draws(c):
            if d.scored():
                by[d.host][0] += 1
                by[d.host][1] += d.outcome == "perfect"
        for hst, (n, k) in sorted(by.items()):
            rows.append([c["target"], c["arm"], hst, "%d/%d" % (k, n)])
    print(table(["target", "arm", "host", "k/n"], rows))


# --------------------------------------------------- caption-table test
CAPTION = re.compile(r'(<div class="aca_gridview_caption">)\s*<table\b.*?'
                     r'</table>', re.S | re.I)


def caption(R):
    h("The caption table (exploratory)")
    t = H.TARGETS["clarkco"]
    pages = H.corpus(t)
    stripped = [q for _, q in H.stripped_corpus(t, pages)]
    refs = [t.reference(H.read(p)) for _, p in pages]
    tmp = tempfile.mkdtemp(prefix="caption_")
    cut = []
    for q in stripped:
        s = H.read(q)
        s2, n = CAPTION.subn(r"\1", s)
        assert n == 1, (q, n)
        p = os.path.join(tmp, os.path.basename(q))
        with io.open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(s2)
        cut.append(p)
    tried = rows_back = recovered = 0
    by_model = collections.Counter()
    for c in R.data["cells"]:
        if c["target"] != "clarkco" or c["protocol"] != "v2":
            continue
        for d in R.draws(c):
            if d.outcome != "imperfect" or d.recall_min != 0.0:
                continue
            tried += 1
            res, err = sandbox.run_synth(d.source, cut, tmp)
            if err or not all(r["ok"] for r in res):
                continue
            sc = [H.score(t, ref, r["rows"])
                  for r, ref in zip(res, refs, strict=True)]
            rows_back += all((s["recall"] or 0) > 0 for s in sc)
            ok = all(s["recall"] == 1.0 and s["precision"] == 1.0
                     for s in sc)
            recovered += ok
            by_model[c["model"]] += ok
    print("Silently empty v2 Clark draws (recall 0 on some page): %d. With "
          "the caption's table removed, %d return matching rows on every "
          "page, and %d pass on every page."
          % (tried, rows_back, recovered))
    # What the model was shown: the 24,000-character excerpt of page 1.
    for key in ("clarkco", "santabarbara", "stjohns"):
        tg = H.TARGETS[key]
        page = H.read(H.corpus(tg)[0][1])
        win = H.window(page, 24000)[0]
        print("%s: nested caption table on page 1 %s; in the excerpt %s"
              % (key, "aca_gridview_caption" in page,
                 "aca_gridview_caption" in win))
    print("Passing, by model: %s"
          % ", ".join("%s %d" % (R.name(m), n)
                      for m, n in by_model.most_common() if n))
    # For the results page, which quotes only what its data file carries.
    fileio.atomic_write(CAPTION_OUT, json.dumps({
        "source": "spikes/v2_results.py --caption",
        "silent_empty": tried, "rows_back": rows_back, "pass": recovered,
    }, indent=1) + "\n", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--caption", action="store_true")
    args = ap.parse_args()
    R = Run()
    print("# v2 run: report tables, data as of %s" % R.data["as_of"])
    summary(R)
    q1(R)
    q2(R)
    q3(R)
    q1(R, "stjohns", "St. Johns baseline pass@1 (development target)")
    q4(R)
    q5(R)
    field_level(R)
    both_rules(R)
    missing(R)
    reliability(R)
    reasoning(R)
    deepseek_hosts(R)
    hosts(R)
    if args.caption:
        caption(R)


if __name__ == "__main__":
    main()
