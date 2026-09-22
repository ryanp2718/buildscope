# -*- coding: utf-8 -*-
"""Spike A, step 1: draw the stratified portal-enumerability sample.

Per the Spike A protocol in DESIGN.md:
  - ~10 from the top BPS unit-volume decile (tier-1 / 'collected')
  - ~10 mid-volume tier-1
  - ~8 tier-2 ('imputed_tier', low average annual units)
  - spread across at least 8 states, both coasts and interior
  - drawn from the offices the catalog sweep did NOT resolve

Stratified, not uniform random: picking the 500 easiest jurisdictions builds a
system that works on the 500 easiest. The seed is fixed so the draw is
reproducible; re-running with the same frame gives the same 28 rows.

Writes data/spike_a/sample.csv.
"""
import csv
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "data", "frame", "bps_frame.csv")
RESOLVED = os.path.join(ROOT, "data", "frame", "bucket1_candidates.csv")
OUTDIR = os.path.join(ROOT, "data", "spike_a")
OUT = os.path.join(OUTDIR, "sample.csv")

SEED = 20260920
N_TOP, N_MID, N_T2 = 10, 10, 8
MIN_STATES = 8

# Census region -> label, for the coastal/interior spread check.
REGION = {"1": "Northeast", "2": "Midwest", "3": "South", "4": "West"}

FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def main():
    rows = list(csv.DictReader(open(FRAME, newline="", encoding="utf-8")))

    # Exclude offices the catalog sweep already resolved: Spike A's question is
    # about the ~19,890 offices open-data catalogs cannot see.
    resolved = set()
    if os.path.exists(RESOLVED):
        for r in csv.DictReader(open(RESOLVED, newline="", encoding="utf-8")):
            resolved.add((r["state"], r["bps_id"]))

    pool = [r for r in rows if (r["state"], r["bps_id"]) not in resolved]
    print("frame %d, resolved %d, pool %d" % (len(rows), len(resolved), len(pool)))

    t1 = sorted([r for r in pool if r["bps_tier"] == "collected"],
                key=lambda r: -f(r["units_12mo"]))
    t2 = [r for r in pool
          if r["bps_tier"] == "imputed_tier" and f(r["avg_annual_units"]) < 6]

    decile = t1[:max(1, len(t1) // 10)]
    mid_lo, mid_hi = int(len(t1) * 0.40), int(len(t1) * 0.60)
    mid = t1[mid_lo:mid_hi]
    print("tier1 %d (top decile %d, mid band %d), tier2<6u %d"
          % (len(t1), len(decile), len(mid), len(t2)))

    rng = random.Random(SEED)

    def spread(cands, n, seen_states):
        """Pick n, preferring states not yet represented, then shuffling."""
        pick, pool_ = [], cands[:]
        rng.shuffle(pool_)
        for r in pool_:
            if len(pick) >= n:
                break
            if r["state"] not in seen_states:
                pick.append(r)
                seen_states.add(r["state"])
        for r in pool_:
            if len(pick) >= n:
                break
            if r not in pick:
                pick.append(r)
        return pick

    seen = set()
    sample = []
    for cands, n, stratum in ((decile, N_TOP, "tier1_top_decile"),
                              (mid, N_MID, "tier1_mid"),
                              (t2, N_T2, "tier2_imputed")):
        for r in spread(cands, n, seen):
            r = dict(r)
            r["stratum"] = stratum
            sample.append(r)

    states = {r["state"] for r in sample}
    regions = {r["region"] for r in sample}
    print("\nsample %d rows, %d states, regions %s"
          % (len(sample), len(states), sorted(REGION.get(x, x) for x in regions)))
    if len(states) < MIN_STATES:
        print("WARNING: only %d states, protocol wants >= %d" % (len(states), MIN_STATES))
    if len(regions) < 4:
        print("WARNING: regions %s - protocol wants coasts and interior" % sorted(regions))

    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    cols = ["stratum", "state_abbr", "state", "bps_id", "place_name", "county",
            "region_name", "pop", "units_12mo", "avg_annual_units", "bps_tier",
            "pct_reported"]
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sample:
            r["state_abbr"] = FIPS.get(r["state"], r["state"])
            r["region_name"] = REGION.get(r["region"], r["region"])
            w.writerow(r)

    print("\n%-18s %-22s %-4s %9s %9s" % ("stratum", "place", "st", "units", "pop"))
    for r in sample:
        print("%-18s %-22s %-4s %9s %9s"
              % (r["stratum"][:18], r["place_name"][:22], r["state_abbr"],
                 r["units_12mo"], r["pop"]))
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
