# -*- coding: utf-8 -*-
"""Spike A, step 7: compute the bucket distribution all three ways.

'Report the distribution three ways: unit-weighted over the whole sample,
count-weighted over the whole sample, and count-weighted over tier-2 alone. The
tier-2 count-weighted figure drives the decision.' (DESIGN.md, Spike A)

Also reconstructs the unconditional office-weighted figure, because the sample
was deliberately drawn from the 19,886 offices the catalog sweep did NOT
resolve - so a raw percentage here understates enumerability across the whole
frame and must have the 183 known bucket-1 offices added back.
"""
import csv
import os
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLS = os.path.join(ROOT, "data", "spike_a", "classification.csv")
FRAME = os.path.join(ROOT, "data", "frame", "bps_frame.csv")

BUCKET_LABEL = {
    "1": "bulk download or documented API",
    "2": "browsable index, no query required",
    "3": "search-only BUT broad query returns everything",
    "4": "search-only, needs a known address/parcel/permit no.",
    "5": "JS-gated, no endpoint without a browser",
    "6": "no online portal found",
    "7": "portal exists but requires registration/login  [NEW]",
    "unresolved": "not classified",
}
ENUMERABLE = {"1", "2", "3"}

N_FRAME = 20069
N_BUCKET1 = 183          # offices the catalog sweep resolved, excluded from this sample
N_POOL = N_FRAME - N_BUCKET1


def pct(a, b):
    return 0.0 if not b else 100.0 * a / b


def main():
    rows = list(csv.DictReader(open(CLS, newline="", encoding="utf-8")))
    n = len(rows)
    units = {r["state"] + r["bps_id"]: float(r["units_12mo"] or 0) for r in rows}
    tot_units = sum(units.values())

    by_bucket = Counter(r["bucket"] for r in rows)
    units_by_bucket = defaultdict(float)
    for r in rows:
        units_by_bucket[r["bucket"]] += float(r["units_12mo"] or 0)

    t2 = [r for r in rows if r["stratum"] == "tier2_imputed"]
    t1 = [r for r in rows if r["stratum"] != "tier2_imputed"]
    t2_bucket = Counter(r["bucket"] for r in t2)

    print("=" * 78)
    print("SPIKE A - PORTAL ENUMERABILITY, n=%d" % n)
    print("=" * 78)
    print("\n%-4s %-52s %5s %7s %7s" % ("bkt", "meaning", "n", "count%", "unit%"))
    for b in ["1", "2", "3", "4", "5", "6", "7", "unresolved"]:
        if by_bucket.get(b):
            print("%-4s %-52s %5d %6.1f%% %6.1f%%"
                  % (b, BUCKET_LABEL[b][:52], by_bucket[b],
                     pct(by_bucket[b], n), pct(units_by_bucket[b], tot_units)))

    enum_n = sum(by_bucket.get(b, 0) for b in ENUMERABLE)
    enum_u = sum(units_by_bucket.get(b, 0) for b in ENUMERABLE)
    t2_enum = sum(t2_bucket.get(b, 0) for b in ENUMERABLE)

    print("\n" + "-" * 78)
    print("THE THREE REQUIRED WEIGHTINGS (buckets 1-3 = enumerable)")
    print("-" * 78)
    print("  unit-weighted, whole sample      : %5.1f%%  (%d of %d units)"
          % (pct(enum_u, tot_units), enum_u, tot_units))
    print("  count-weighted, whole sample     : %5.1f%%  (%d of %d offices)"
          % (pct(enum_n, n), enum_n, n))
    print("  count-weighted, TIER 2 ONLY      : %5.1f%%  (%d of %d)   <-- DRIVES THE DECISION"
          % (pct(t2_enum, len(t2)), t2_enum, len(t2)))
    print("  count-weighted, tier 1 only      : %5.1f%%  (%d of %d)"
          % (pct(sum(Counter(r["bucket"] for r in t1).get(b, 0) for b in ENUMERABLE),
                 len(t1)),
             sum(Counter(r["bucket"] for r in t1).get(b, 0) for b in ENUMERABLE), len(t1)))

    print("\n" + "-" * 78)
    print("UNCONDITIONAL RECONSTRUCTION")
    print("-" * 78)
    print("  The sample excluded the %d offices the catalog sweep resolved, so the" % N_BUCKET1)
    print("  figures above are conditional on 'not already known to be bucket 1'.")
    rate = enum_n / float(n)
    est = N_BUCKET1 + rate * N_POOL
    print("  point estimate, whole frame      : %5.1f%%  (%d + %.0f%% x %d = ~%.0f offices)"
          % (pct(est, N_FRAME), N_BUCKET1, rate * 100, N_POOL, est))
    lo, hi = max(0.0, rate - 0.18), min(1.0, rate + 0.18)
    print("  same, at +/-18pp sampling error  : %5.1f%% to %5.1f%%"
          % (pct(N_BUCKET1 + lo * N_POOL, N_FRAME),
             pct(N_BUCKET1 + hi * N_POOL, N_FRAME)))
    print("  NOTE: that interval is so wide it is not a usable planning number.")

    print("\n" + "-" * 78)
    print("DECISION THRESHOLDS (DESIGN.md), read as directional, not computed")
    print("-" * 78)
    v = pct(t2_enum, len(t2))
    for label, cond in (
            ("buckets 1-3 >= 60%  -> proceed as designed, template induction", v >= 60),
            ("bucket 4 dominant   -> critical path is query partitioning",
             pct(t2_bucket.get("4", 0), len(t2)) > 40),
            ("bucket 5 heavy      -> headless cost dominates, re-scope",
             pct(t2_bucket.get("5", 0), len(t2)) > 40),
            ("buckets 1-3 < 30%   -> wrong domain, revisit procurement", v < 30)):
        print("  [%s] %s" % ("X" if cond else " ", label))

    print("\n  Taxonomy gap found: %d of %d portals (%.0f%%) exist but sit behind"
          % (by_bucket.get("7", 0), n, pct(by_bucket.get("7", 0), n)))
    print("  registration/login. The original 6-bucket taxonomy has no cell for this.")
    print("  Unresolved: %d of %d (%.0f%%) - not guessed."
          % (by_bucket.get("unresolved", 0), n, pct(by_bucket.get("unresolved", 0), n)))


if __name__ == "__main__":
    main()
