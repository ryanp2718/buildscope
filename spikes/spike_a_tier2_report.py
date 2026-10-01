# -*- coding: utf-8 -*-
"""Recompute the Spike A weightings with tier 2 classified at the ISSUING level.

The first pass classified tier-2 rows at the BPS *place* level and recorded a
place-level miss as bucket 6. That could only bias the deciding figure
downward, so the figure was not trusted. This recomputes it after each tier-2
row was re-probed at the body that actually issues its permits.

It also reports the quantity that turns out to matter more than the threshold
itself: how many permitted units the tier-2 stratum actually contributes.
"""
import csv
import io
import os
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLS = os.path.join(ROOT, "data", "spike_a", "classification.csv")
RE2 = os.path.join(ROOT, "data", "spike_a", "tier2_reclassification.csv")

LABEL = {
    "0": "NO PERMIT ISSUED - no record exists at any level  [NEW]",
    "1": "bulk download or documented API",
    "2": "browsable index, no query required",
    "3": "search-only BUT broad query returns everything",
    "4": "search-only, needs a known address/parcel/permit no.",
    "5": "JS-gated, no endpoint without a browser",
    "6": "no online portal found",
    "7": "portal exists but requires registration/login",
    "unresolved": "not classified",
}
ENUMERABLE = {"1", "2", "3"}


def pct(a, b):
    return 0.0 if not b else 100.0 * a / b


def main():
    rows = list(csv.DictReader(io.open(CLS, newline="", encoding="utf-8")))
    new = {(r["state"], r["bps_id"]): r
           for r in csv.DictReader(io.open(RE2, newline="", encoding="utf-8"))}

    changed = []
    for r in rows:
        k = (r["state"], r["bps_id"])
        if k in new:
            before, after = r["bucket"], new[k]["bucket_after"]
            r["bucket"] = after
            r["issuing_level"] = new[k]["issuing_level"]
            r["issuer"] = new[k]["issuer"]
            if before != after:
                changed.append((new[k]["place_name"], before, after))

    missing = set(new) - {(r["state"], r["bps_id"]) for r in rows}
    assert not missing, "reclassified rows not present in classification: %s" % missing
    t2 = [r for r in rows if r["stratum"] == "tier2_imputed"]
    assert len(t2) == len(new), "expected %d tier-2 rows, matched %d" % (len(new), len(t2))

    n = len(rows)
    tot_u = sum(float(r["units_12mo"] or 0) for r in rows)
    by_b = Counter(r["bucket"] for r in rows)
    u_by_b = defaultdict(float)
    for r in rows:
        u_by_b[r["bucket"]] += float(r["units_12mo"] or 0)
    t2b = Counter(r["bucket"] for r in t2)
    t2_u = sum(float(r["units_12mo"] or 0) for r in t2)

    print("=" * 78)
    print("SPIKE A, TIER-2 RERUN AT THE PERMIT-ISSUING LEVEL   n=%d (tier 2: %d)"
          % (n, len(t2)))
    print("=" * 78)

    print("\nLEVEL AT WHICH EACH TIER-2 PLACE ACTUALLY ISSUES")
    lv = Counter(new[k]["issuing_level"] for k in new)
    for level, c in lv.most_common():
        who = [new[k]["place_name"] for k in new if new[k]["issuing_level"] == level]
        print("  %-16s %d   %s" % (level, c, ", ".join(who)))

    print("\nRECLASSIFICATIONS")
    if not changed:
        print("  none - every tier-2 row holds its bucket at the corrected level")
    for place, b, a in changed:
        print("  %-22s bucket %s -> %s   (%s)" % (place, b, a, LABEL[a][:44]))

    print("\n%-4s %-52s %5s %7s %7s" % ("bkt", "meaning", "n", "count%", "unit%"))
    for b in ["0", "1", "2", "3", "4", "5", "6", "7", "unresolved"]:
        if by_b.get(b):
            print("%-4s %-52s %5d %6.1f%% %6.1f%%"
                  % (b, LABEL[b][:52], by_b[b], pct(by_b[b], n),
                     pct(u_by_b[b], tot_u)))

    enum_n = sum(by_b.get(b, 0) for b in ENUMERABLE)
    enum_u = sum(u_by_b.get(b, 0) for b in ENUMERABLE)
    t2_enum = sum(t2b.get(b, 0) for b in ENUMERABLE)

    print("\n" + "-" * 78)
    print("THE THREE REQUIRED WEIGHTINGS (buckets 1-3 = enumerable)")
    print("-" * 78)
    print("  unit-weighted, whole sample      : %5.1f%%  (%d of %d units)"
          % (pct(enum_u, tot_u), enum_u, tot_u))
    print("  count-weighted, whole sample     : %5.1f%%  (%d of %d offices)"
          % (pct(enum_n, n), enum_n, n))
    print("  count-weighted, TIER 2 ONLY      : %5.1f%%  (%d of %d)   <-- DRIVES THE DECISION"
          % (pct(t2_enum, len(t2)), t2_enum, len(t2)))
    print("  ...now measured at the issuing level, so the downward bias is removed.")
    print("  Rule of three: 0 of %d still has a 95%% upper bound near %.0f%%."
          % (len(t2), 100.0 * 3 / len(t2)))

    print("\n" + "-" * 78)
    print("WHAT THE DECIDING STRATUM IS ACTUALLY WORTH")
    print("-" * 78)
    print("  tier-2 share of sample offices   : %5.1f%%  (%d of %d)"
          % (pct(len(t2), n), len(t2), n))
    print("  tier-2 share of sample UNITS     : %5.2f%%  (%d of %d units)"
          % (pct(t2_u, tot_u), t2_u, tot_u))
    print("  The stratum the threshold keys on contributes %.2f%% of the permitted"
          % pct(t2_u, tot_u))
    print("  units in the sample. A gate that can halt the project on a stratum")
    print("  worth that little is measuring reachability, not value.")

    noperm = [r for r in t2 if r["bucket"] == "0"]
    if noperm:
        print("\n" + "-" * 78)
        print("THE FINDING THAT CHANGES THE QUESTION")
        print("-" * 78)
        print("  %d of %d tier-2 places issue NO building permit at all."
              % (len(noperm), len(t2)))
        for r in noperm:
            print("    - %s (%s units in BPS, all imputed)"
                  % (r["place_name"], r["units_12mo"]))
        print("  BPS imputes these units; they were never permit documents anywhere.")
        print("  No crawler recovers a record that was never created, so part of the")
        print("  tier-2 gap is not a coverage problem and cannot be closed.")

    print("\n" + "-" * 78)
    print("DECISION THRESHOLDS (docs/design/history.md)")
    print("-" * 78)
    v = pct(t2_enum, len(t2))
    for label, cond in (
            ("buckets 1-3 >= 60%  -> proceed as designed, template induction", v >= 60),
            ("bucket 4 dominant   -> critical path is query partitioning",
             pct(t2b.get("4", 0), len(t2)) > 40),
            ("bucket 5 heavy      -> headless cost dominates, re-scope",
             pct(t2b.get("5", 0), len(t2)) > 40),
            ("buckets 1-3 < 30%   -> wrong domain, revisit procurement", v < 30)):
        print("  [%s] %s" % ("X" if cond else " ", label))


if __name__ == "__main__":
    main()
