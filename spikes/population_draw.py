# -*- coding: utf-8 -*-
"""Portal population, step 1: draw the order in which offices are located.

The extractor study needs portals no prompt was written against, chosen by a
rule rather than by hand, so that the vendor mix is what is out there. The
frame is the 1,000 permit offices with the most units in the Census BPS's last
12 months: about 72% of the country's permitted units, and the size band where
an online portal is common (Spike A found portals mostly absent below it).

Every one of the 1,000 is put in a random order with a fixed seed. Offices are
then located and classified in that order (`population_portals.csv`, by hand
and by `population_probe.py`), and the groups are filled from the front of the
order, so no portal is picked for being convenient. An office whose portal is
already a target (Clark, St. Johns, Santa Barbara, Polk, Oregon statewide), or
is the same portal as an office earlier in the order, is recorded and skipped.

Writes data/population/draw.csv.
"""
import csv
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "data", "frame", "bps_frame.csv")
OUTDIR = os.path.join(ROOT, "data", "population")
OUT = os.path.join(OUTDIR, "draw.csv")

SEED = 20261003
N_LARGEST = 1000

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


def units(r):
    try:
        return float(r["units_12mo"])
    except (TypeError, ValueError):
        return 0.0


def main():
    with open(FRAME, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    total = sum(units(r) for r in rows)
    # Ties at the cut are broken by the frame's own key, so the 1,000 do not
    # depend on file order.
    largest = sorted(rows, key=lambda r: (-units(r), r["state"], r["bps_id"]))
    largest = largest[:N_LARGEST]
    for i, r in enumerate(largest, 1):
        r["size_rank"] = i
    share = sum(units(r) for r in largest) / total
    print("frame %d offices; the %d largest hold %.1f%% of 12-month units "
          "(cut at %d units)" % (len(rows), N_LARGEST, 100 * share,
                                 units(largest[-1])))

    order = largest[:]
    random.Random(SEED).shuffle(order)

    os.makedirs(OUTDIR, exist_ok=True)
    cols = ["order", "size_rank", "state_abbr", "state", "bps_id",
            "place_name", "county", "pop", "units_12mo"]
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(order, 1):
            r["order"] = i
            r["state_abbr"] = FIPS.get(r["state"], r["state"])
            w.writerow(r)
    print("wrote %s" % OUT)
    for r in order[:40]:
        print("%4d  #%-4d %-40s %-3s %6s units"
              % (r["order"], r["size_rank"], r["place_name"][:40],
                 r["state_abbr"], r["units_12mo"]))


if __name__ == "__main__":
    main()
