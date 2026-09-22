# -*- coding: utf-8 -*-
"""Add an office's BPS months to the oracle, from the raw files already on disk.

`data/spike_b/bps_months.csv` holds the five offices Spike B drew. Step 1 has
since pulled jurisdictions outside that draw - St. Johns County FL is the
first - and a jurisdiction with no oracle row silently produces no comparison
row, which reads exactly like a jurisdiction that matched nothing.

Zero network: the monthly place files for 2024-07 through 2026-06 are in
`data/raw/bps`. This reuses `spike_b_sample.pull` and its `IMPUTED_SOURCES`
set rather than reimplementing either, because "usable" has to mean the same
thing for a jurisdiction added later as it did for the original five. Source
codes 5 and 9 are imputations, not observations, and a month carrying one is
written with `usable=N` and dropped at comparison time.

Appends; it does not rewrite the existing rows. Re-running for an office that
is already present replaces only that office's rows.

Usage: python scripts/step1_oracle_add.py 12 803000
"""
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import spike_b_sample as S                             # noqa: E402

OUT = os.path.join(S.ROOT, "data", "spike_b", "bps_months.csv")
FIELDS = ["state", "bps_id", "place_name", "yymm", "survey_date", "source",
          "usable", "units", "u1", "u2", "u34", "u5p", "catalog", "tier",
          "rationale"]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    state, bps_id = sys.argv[1].zfill(2), sys.argv[2]
    frame = dict(((x["state"], x["bps_id"]), x) for x in S.rd(S.FRAME))
    fr = frame.get((state, bps_id))
    if fr is None:
        print("%s|%s is not in the BPS frame - refusing to invent an office"
              % (state, bps_id))
        return 1

    months = S.pull([(state, bps_id)])[(state, bps_id)]
    if not months:
        print("no months found on disk for %s|%s" % (state, bps_id))
        return 1

    existing = []
    if os.path.exists(OUT):
        existing = [r for r in csv.DictReader(
            io.open(OUT, newline="", encoding="utf-8"))
            if not (r["state"] == state and r["bps_id"] == bps_id)]

    added = []
    for y in sorted(months):
        r = months[y]
        usable = "N" if r["source"] in S.IMPUTED_SOURCES else "Y"
        added.append(dict(
            state=state, bps_id=bps_id, place_name=fr["place_name"], yymm=y,
            survey_date=r["date"], source=r["source"], usable=usable,
            units=r["units"], u1=r["u1"], u2=r["u2"], u34=r["u34"],
            u5p=r["u5p"], catalog="", tier=fr.get("bps_tier", ""),
            rationale="added by step1_oracle_add"))

    with io.open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in existing + added:
            w.writerow(dict((k, r.get(k, "")) for k in FIELDS))

    ok = sum(1 for r in added if r["usable"] == "Y")
    print("%s  %s|%s" % (fr["place_name"], state, bps_id))
    print("  %d months added, %d usable, %d imputed and unusable"
          % (len(added), ok, len(added) - ok))
    print("  %s -> %d rows total" % (os.path.relpath(OUT, S.ROOT),
                                     len(existing) + len(added)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
