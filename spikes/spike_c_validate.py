# -*- coding: utf-8 -*-
"""Control tests for the Spike C fingerprint, run BEFORE trusting its verdict.

Spike C reports ~1.00 fingerprints-per-jurisdiction at every clustering
threshold. That is either a real finding about template collapse or a broken
fingerprint, and the two are indistinguishable from the headline number alone.

This measures whether the fingerprint discriminates at all:

  POSITIVE CONTROL - pages that MUST be structurally near-identical:
      the same portal fetched twice with different query parameters.
      If these do not score high, the fingerprint is too brittle to use.
  KNOWN-VENDOR PAIRS - two sites on the same commercial CMS.
      These are the cases where collapse is genuinely expected.
  NEGATIVE CONTROL - the full pairwise distribution across unrelated
      jurisdictions. This is the baseline any real signal must beat.

A fingerprint is usable only if positive-control similarity sits well above the
negative-control distribution. If same-vendor pairs then land near baseline,
THAT is the finding.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spike_c_fingerprint import (fingerprint, jaccard, CORPORA,  # noqa: E402
                                 load_labels, classify)

PAIRS_POS = [
    ("q_clarkco_accela_date_range_only.html", "q_clarkco_accela_empty_criteria.html",
     "same Accela portal, two different queries"),
    ("q_oregon_accela_date_range_only.html", "q_oregon_accela_empty_criteria.html",
     "same Accela portal, two different queries"),
    ("q_YAKIMACO_empty.html", "q_YAKIMACO_wapato.html",
     "same Accela portal, empty vs city query"),
]
PAIRS_VENDOR = [
    ("q_clarkco_accela_empty_criteria.html", "q_oregon_accela_empty_criteria.html",
     "Accela tenancy vs Accela tenancy (Clark County NV / Oregon statewide)"),
    ("q_clarkco_accela_empty_criteria.html", "q_YAKIMACO_wapato.html",
     "Accela tenancy vs Accela tenancy (Clark County NV / Yakima County WA)"),
    ("q_oregon_accela_empty_criteria.html", "q_YAKIMACO_wapato.html",
     "Accela tenancy vs Accela tenancy (Oregon / Yakima County WA)"),
    ("tx_mission_home.html", "portal_19_story_county_unincorporated_area.html",
     "CivicPlus vs CivicPlus"),
    ("wa_wapato_home.html", "va_west_point_town_home.html",
     "Revize vs Revize"),
]


def load_all():
    idx, fps = {}, {}
    for d in CORPORA:
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.endswith(".html"):
                idx[n] = os.path.join(d, n)
    for n, p in idx.items():
        html = io.open(p, encoding="utf-8", errors="replace").read()
        fp, s, npaths, nodes = fingerprint(html)
        fps[n] = {"fp": fp, "set": s, "paths": npaths, "nodes": nodes, "bytes": len(html)}
    return fps


def show(title, pairs, fps):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    vals = []
    for a, b, why in pairs:
        if a not in fps or b not in fps:
            print("  SKIP (missing file): %s / %s" % (a, b))
            continue
        j = jaccard(fps[a]["set"], fps[b]["set"])
        vals.append(j)
        print("  J=%.3f  |A|=%-5d |B|=%-5d  %s"
              % (j, len(fps[a]["set"]), len(fps[b]["set"]), why))
    return vals


def main():
    fps = load_all()
    sizes = sorted(len(v["set"]) for v in fps.values())
    print("SPIKE C FINGERPRINT VALIDATION     %d pages" % len(fps))
    print("  unique root-to-leaf paths per page: min=%d median=%d max=%d"
          % (sizes[0], sizes[len(sizes) // 2], sizes[-1]))

    pos = show("POSITIVE CONTROL - same portal, different query. MUST score high.",
               PAIRS_POS, fps)
    ven = show("SAME-VENDOR PAIRS - where collapse is expected", PAIRS_VENDOR, fps)

    # negative control: all pairs across distinct jurisdictions
    labels = load_labels()
    juris = {}
    for n in fps:
        html = ""
        j, cls, vendor, stratum = classify(n, html, labels)
        juris[n] = j
    names = sorted(fps)
    neg = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if juris[a] != juris[b]:
                neg.append(jaccard(fps[a]["set"], fps[b]["set"]))
    neg.sort()

    def q(v, p):
        return v[min(len(v) - 1, int(p * len(v)))] if v else float("nan")

    print("\n" + "=" * 78)
    print("NEGATIVE CONTROL - %d cross-jurisdiction pairs" % len(neg))
    print("=" * 78)
    print("  min=%.3f  p25=%.3f  median=%.3f  p75=%.3f  p95=%.3f  p99=%.3f  max=%.3f"
          % (neg[0], q(neg, .25), q(neg, .5), q(neg, .75), q(neg, .95),
             q(neg, .99), neg[-1]))

    print("\n" + "-" * 78)
    print("VERDICT ON THE INSTRUMENT")
    print("-" * 78)
    if not pos:
        print("  inconclusive - no positive control pairs available")
        return
    pmin = min(pos)
    base = q(neg, .95)
    print("  positive control minimum : %.3f" % pmin)
    print("  cross-jurisdiction p95   : %.3f" % base)
    print("  same-vendor range        : %.3f - %.3f"
          % (min(ven), max(ven)) if ven else "  same-vendor range: n/a")
    if pmin < 0.70:
        print("\n  [X] FINGERPRINT IS TOO BRITTLE. Pages that are the same template")
        print("      score below 0.70. The ~1.00 ratio is an artifact of the")
        print("      instrument and must NOT be reported as a finding.")
    elif pmin - base < 0.20:
        print("\n  [X] FINGERPRINT DOES NOT DISCRIMINATE. Known-identical pages score")
        print("      no better than unrelated ones. The ratio is meaningless.")
    else:
        print("\n  [OK] Fingerprint discriminates: identical templates score %.3f while"
              % pmin)
        print("       unrelated pages sit at %.3f (p95). A same-vendor pair landing" % base)
        print("       near the baseline is therefore a real absence of collapse.")


if __name__ == "__main__":
    main()
