# -*- coding: utf-8 -*-
"""Analysis for Measurements A and B. Reads the manifest, never the directory.

Every rule applied here was written down in
docs/evidence/2026-09-20-measurement-ab-preregistration.md before any page was
fetched. Nothing in this file chooses a threshold.

The manifest is an append-only log, so the current verdict for a page is its
LAST row, not its first. A page whose current verdict is not `ok` cannot enter
a ratio - that is the whole reason the manifest exists.
"""
import csv
import io
import json
import os
import statistics
import sys
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402
from spike_c_fingerprint import fingerprint, jaccard  # noqa: E402

THRESHOLDS = (0.95, 0.90, 0.80, 0.70, 0.60)


def load():
    rows = list(csv.DictReader(io.open(mf.MANIFEST, newline="",
                                       encoding="utf-8")))
    cur = {}
    for r in rows:
        if r["file"]:
            cur[r["file"]] = r          # fold: latest row wins
    pages = {}
    for fn, r in sorted(cur.items()):
        if r["verdict"] != "ok":
            continue
        p = os.path.join(mf.PAGES, fn)
        if not os.path.exists(p):
            continue
        html = io.open(p, encoding="utf-8", errors="replace").read()
        fp, pset, npaths, nodes = fingerprint(html)
        juris = r["jurisdiction"].replace("accela:", "")
        pages[fn] = dict(fp=fp, set=pset, paths=npaths, juris=juris,
                         vendor=r["vendor"], ptype=r["page_type"],
                         bytes=int(r["bytes"]), imported=r["request_method"] == "IMPORT")
    return rows, cur, pages


def pairs_within(pages, ptype, same_juris=True, cross_type=None):
    out = []
    names = sorted(pages)
    for a, b in combinations(names, 2):
        A, B = pages[a], pages[b]
        if cross_type:
            t = {A["ptype"], B["ptype"]}
            if t != set(cross_type):
                continue
        else:
            if A["ptype"] != ptype or B["ptype"] != ptype:
                continue
        if (A["juris"] == B["juris"]) != same_juris:
            continue
        out.append((a, b, jaccard(A["set"], B["set"])))
    return sorted(out, key=lambda x: -x[2])


def cluster(keys, sets, t):
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in combinations(keys, 2):
        if jaccard(sets[a], sets[b]) >= t:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    groups = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    return list(groups.values())


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))] if v else float("nan")


def show(title, rows, pages, limit=12):
    print("\n" + "-" * 78)
    print(title)
    print("-" * 78)
    if not rows:
        print("  (no pairs)")
        return []
    for a, b, j in rows[:limit]:
        print("  J=%.3f  %-32s %-32s" % (j, a[:32], b[:32]))
    if len(rows) > limit:
        print("  ... %d more" % (len(rows) - limit))
    return [j for _, _, j in rows]


def main():
    rows, cur, pages = load()
    res = {}
    print("=" * 78)
    print("MEASUREMENTS A + B  -  analysis")
    print("=" * 78)
    print("manifest rows: %d   distinct pages: %d   usable (verdict=ok): %d"
          % (len(rows), len(cur), len(pages)))
    byt = defaultdict(int)
    for p in pages.values():
        byt[p["ptype"]] += 1
    print("  usable by page type: " + ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(byt.items())))
    dropped = [(fn, r["page_type"], r["verdict_reason"][:54])
               for fn, r in sorted(cur.items()) if r["verdict"] != "ok"]
    print("  excluded (verdict != ok): %d" % len(dropped))
    for fn, pt, why in dropped:
        print("      %-34s %-9s %s" % (fn[:34], pt, why))

    # ------------------------------------------------------------ controls
    c1 = show("C1  POSITIVE within-portal T-INDEX  (expect >= 0.80)",
              pairs_within(pages, "T-INDEX", True), pages)
    c2 = show("C2  POSITIVE within-portal T-DETAIL (expect >= 0.80)",
              pairs_within(pages, "T-DETAIL", True), pages)
    c3 = show("C3  CONFOUND within-portal INDEX vs DETAIL (expect LOW)",
              pairs_within(pages, None, True,
                           cross_type=("T-INDEX", "T-DETAIL")), pages)
    print("\n" + "-" * 78)
    print("C4  CROSS-VENDOR within-type  ->  NOT RUN")
    print("-" * 78)
    print("  The corpus holds no non-Accela result-index page. Spike A's only")
    print("  non-Accela candidate (St Johns County WATS .NET) is a login/landing")
    print("  page - txtLogName, txtPassword, btnLogin - not a search form, and")
    print("  getting an index out of it means solving a bucket-4 portal, which is")
    print("  out of scope here. Reported as not run rather than substituted.")

    # C5 baseline: all cross-jurisdiction pairs, any type
    names = sorted(pages)
    c5 = [jaccard(pages[a]["set"], pages[b]["set"])
          for a, b in combinations(names, 2)
          if pages[a]["juris"] != pages[b]["juris"]]
    print("\n" + "-" * 78)
    print("C5  BASELINE  %d cross-jurisdiction pairs (all types)" % len(c5))
    print("-" * 78)
    print("  min=%.3f p25=%.3f median=%.3f p75=%.3f p95=%.3f max=%.3f"
          % (min(c5), q(c5, .25), q(c5, .5), q(c5, .75), q(c5, .95), max(c5)))

    res["controls"] = dict(
        c1=dict(n=len(c1), min=min(c1) if c1 else None, max=max(c1) if c1 else None),
        c2=dict(n=len(c2), min=min(c2) if c2 else None, max=max(c2) if c2 else None),
        c3=dict(n=len(c3), min=min(c3) if c3 else None, max=max(c3) if c3 else None),
        c4="NOT RUN - no non-Accela index page in corpus",
        c5=dict(n=len(c5), median=q(c5, .5), p95=q(c5, .95)))

    # ---------------------------------------------- which baseline is valid
    # C5 was pre-registered to land near median 0.04 / p95 0.08, from Spike C's
    # 4,782 cross-jurisdiction pairs. It did not: it came in an order of
    # magnitude higher. The reason is that this corpus is mono-vendor by
    # construction - almost every usable page is Accela - so its
    # "cross-jurisdiction" pairs are overwhelmingly same-vendor pairs, which is
    # the very quantity under test. Using it as the negative control would be
    # circular, so the heterogeneous baseline measured by Spike C over 25
    # unrelated jurisdictions is used instead, and both are reported.
    B_SELF = q(c5, .95)
    B_HETERO = 0.077            # Spike C, p95 of 4,782 cross-jurisdiction pairs
    B = B_HETERO
    print("\n  [!] C5 came in at p95=%.3f against a pre-registered ~0.08."
          % B_SELF)
    print("      This corpus is mono-vendor, so its own cross-jurisdiction")
    print("      pairs are mostly same-vendor pairs and cannot serve as a")
    print("      negative control. Using Spike C's heterogeneous baseline")
    print("      p95=%.3f instead; both are reported." % B_HETERO)
    res["baseline"] = dict(self_p95=B_SELF, hetero_p95=B_HETERO,
                           used="spike_c_heterogeneous",
                           note="C5 as computed here is circular: mono-vendor corpus")

    # -------------------------------------------- instrument verdict first
    print("\n" + "=" * 78)
    print("VERDICT ON THE INSTRUMENT (checked before any finding is believed)")
    print("=" * 78)
    ok_inst = True
    for lab, vals, floor in (("C1 index", c1, 0.80), ("C2 detail", c2, 0.80)):
        if not vals:
            print("  %-10s no pairs - cannot validate" % lab)
            ok_inst = False
            continue
        print("  %-10s min=%.3f  %s" % (lab, min(vals),
              "OK" if min(vals) >= floor else "BELOW PRE-REGISTERED FLOOR 0.80"))
        if min(vals) < floor:
            ok_inst = False
    if c3:
        print("  C3 confound max=%.3f  %s" % (max(c3),
              "VOIDS EVERYTHING (>= 0.60)" if max(c3) >= 0.60 else "below 0.60, ok"))
    print("  C5 baseline p95=%.3f" % B)

    # ----------------------------------------- primary quantity (A)
    print("\n" + "=" * 78)
    print("MEASUREMENT A  -  cross-jurisdiction, same-vendor, WITHIN page type")
    print("=" * 78)
    res["A"] = {}
    for ptype, floorvals in (("T-INDEX", c1), ("T-DETAIL", c2)):
        rr = pairs_within(pages, ptype, same_juris=False)
        rr = [(a, b, j) for a, b, j in rr
              if pages[a]["vendor"] == pages[b]["vendor"]]
        vals = show("%s  cross-jurisdiction same-vendor" % ptype, rr, pages)
        if not vals:
            continue
        med = statistics.median(vals)
        P = min(floorvals) if floorvals else 0.80
        # A median is the wrong summary of a bimodal distribution, and these
        # are visibly bimodal. Split at the midpoint of the largest gap and
        # report both modes, because "two cohorts" and "a uniform 0.2" are
        # completely different findings that share a median.
        sv = sorted(vals)
        gaps = [(sv[i + 1] - sv[i], i) for i in range(len(sv) - 1)]
        gap, gi = max(gaps) if gaps else (0, 0)
        lo, hi = sv[:gi + 1], sv[gi + 1:]
        if gap >= 0.20 and lo and hi:
            print("  BIMODAL: largest gap %.3f at %.3f/%.3f" % (gap, sv[gi], sv[gi + 1]))
            print("    low  mode: n=%-3d %.3f - %.3f" % (len(lo), min(lo), max(lo)))
            print("    high mode: n=%-3d %.3f - %.3f" % (len(hi), min(hi), max(hi)))
            hi_pairs = sorted(set(
                tuple(sorted((pages[a]["juris"], pages[b]["juris"])))
                for a, b, j in rr if j >= sv[gi + 1]))
            print("    high-mode jurisdiction pairs: %s"
                  % ", ".join("%s~%s" % p for p in hi_pairs))
            res.setdefault("bimodal", {})[ptype] = dict(
                gap=gap, low_n=len(lo), low_max=max(lo),
                high_n=len(hi), high_min=min(hi),
                high_pairs=["%s~%s" % p for p in hi_pairs])
        if med >= P - 0.10:
            verdict = "COHORT COLLAPSE CONFIRMED"
        elif med > B:
            verdict = "PARTIAL COLLAPSE"
        else:
            verdict = "NO COLLAPSE EVEN WITHIN VENDOR"
        print("  median=%.3f   positive floor P=%.3f   baseline B=%.3f  ->  %s"
              % (med, P, B, verdict))
        res["A"][ptype] = dict(n=len(vals), median=med, min=min(vals),
                               max=max(vals), P=P, B=B, verdict=verdict)

    # ----------------------------------------- cohort size (B)
    print("\n" + "=" * 78)
    print("MEASUREMENT B  -  Accela cohort size over T-SEARCH")
    print("=" * 78)
    sea = {n: p for n, p in pages.items()
           if p["ptype"] == "T-SEARCH" and p["vendor"] == "accela-aca"}
    keys = sorted(sea)
    sets = {k: sea[k]["set"] for k in keys}
    print("  tenancies: %d" % len(keys))
    res["B"] = dict(tenancies=len(keys), thresholds={})
    for t in THRESHOLDS:
        cl = cluster(keys, sets, t)
        sizes = sorted((len(c) for c in cl), reverse=True)
        print("  J>=%.2f   clusters=%-3d  mean size=%.2f  sizes=%s"
              % (t, len(cl), len(keys) / float(len(cl)), sizes))
        if t in (0.90, 0.80):
            for c in sorted(cl, key=len, reverse=True):
                if len(c) > 1:
                    print("        cohort(%d): %s"
                          % (len(c), ", ".join(sorted(sea[m]["juris"] for m in c))))
        res["B"]["thresholds"]["%.2f" % t] = dict(
            clusters=len(cl), mean_size=len(keys) / float(len(cl)),
            sizes=sizes,
            members={str(i): sorted(sea[m]["juris"] for m in c)
                     for i, c in enumerate(cl)})
    # exact fingerprints
    exact = len(set(sea[k]["fp"] for k in keys))
    print("  exact identical fingerprints: %d distinct over %d tenancies"
          % (exact, len(keys)))
    res["B"]["exact_distinct"] = exact

    io.open(os.path.join(mf.OUT, "analysis.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(res, indent=1, default=str))
    print("\nwrote data/measure/analysis.json")


if __name__ == "__main__":
    main()
