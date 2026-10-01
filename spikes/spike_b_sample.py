# -*- coding: utf-8 -*-
"""Spike B, mechanical half: draw the sample and pull the BPS oracle months.

The protocol in docs/design/history.md says to draw 5 tier-1 jurisdictions from buckets 1-3
"in Spike A". That cannot be done: Spike A's 28-office sample yielded two
bucket-3 jurisdictions and zero in buckets 1-2, and **neither of the two is in
the clean-oracle set** - Clark County NV and McMinnville OR both have imputed
months in their 24-month history, so neither can be scored against. The sample
is therefore drawn fresh from the frame, against the two binding rules that do
survive:

  1. only offices with a fully reported 24-month history (the clean oracle),
  2. and the Source code checked per month, not per jurisdiction.

**Why the draw leans on bucket 1.** Spike B's question is whether portal data
can be aggregated into something comparable to BPS. The dominant risk in that
is *definitional* - telling new residential construction from alteration, and
getting housing units rather than permit counts - not extraction. Drawing from
bucket 1, where the data arrives already structured, isolates the definitional
question instead of confounding it with parsing error. Spike A also found
bucket 1 is 0.90% of offices but 16.6% of national units, so this is the
high-volume end of the distribution rather than a convenience sample of the
easy end.

Variation is deliberate: two Socrata and three ArcGIS publishers, five states,
four census regions, and a mix of municipal and unincorporated-county offices -
the latter because four of the ten highest-volume permit offices in the country
are unincorporated county areas (section 6).
"""
import csv
import io
import os
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "data", "frame", "bps_frame.csv")
B1 = os.path.join(ROOT, "data", "frame", "bucket1_candidates.csv")
BPS = os.path.join(ROOT, "data", "raw", "bps")
OUT = os.path.join(ROOT, "data", "spike_b")

# Source codes that mean "this is not an observation" (section 2).
IMPUTED_SOURCES = {"5", "9"}

# column positions in the BPS monthly place files
C_DATE, C_STATE, C_ID, C_SOURCE, C_NAME = 0, 1, 2, 15, 16
STRUCT = OrderedDict([("u1", 18), ("u2", 21), ("u34", 24), ("u5p", 27)])

# The draw. Each entry names why it is in the sample, because "we picked five"
# is not a sampling method anyone can check.
SAMPLE = [
    ("48", "033000", "Austin", "socrata", "tier1",
     "Socrata; Austin publishes permit_class AS the Census structure codes"),
    ("53", "475000", "Seattle", "socrata", "tier1",
     "Socrata; dataset is pre-filtered to new construction"),
    ("37", "379000", "Mecklenburg County", "arcgis", "tier1",
     "ArcGIS; also the office-boundary case - Charlotte reports as "
     "Mecklenburg County, testing D3's identity claim directly"),
    ("39", "135700", "Columbus", "arcgis", "tier1",
     "ArcGIS; GENERAL_TYPE separates New Structure explicitly"),
    ("47", "605000", "Nashville-Davidson", "arcgis", "tier1",
     "ArcGIS; included knowing it has no unit field - the 'permit counts "
     "only' case the protocol asks about"),
]


def rd(p):
    return list(csv.DictReader(io.open(p, newline="", encoding="utf-8")))


def num(x, k):
    try:
        return float(x[k] or 0)
    except (TypeError, ValueError):
        return 0.0


def clean_oracle(frame):
    """Offices where every month of the 24 is a true observation."""
    return {(x["state"], x["bps_id"]) for x in frame
            if num(x, "months_reported") == num(x, "months_present")
            and num(x, "months_present") >= 24}


def months_available():
    return sorted({f[2:6] for f in os.listdir(BPS) if f.endswith("c.txt")})


def pull(keys):
    """Every month on disk, for the requested (state, bps_id) keys.

    Returns {(state,id): {yymm: row}}. The Source code is carried per month
    because that is the only level at which it is meaningful.
    """
    want = set(keys)
    out = {k: {} for k in keys}
    for fn in sorted(os.listdir(BPS)):
        if not fn.endswith("c.txt"):
            continue
        yymm = fn[2:6]
        for line in io.open(os.path.join(BPS, fn), encoding="utf-8",
                            errors="replace"):
            p = line.rstrip("\n").split(",")
            if len(p) <= C_NAME + 12 or not p[C_DATE].strip().isdigit():
                continue
            k = (p[C_STATE].strip().zfill(2), p[C_ID].strip())
            if k not in want:
                continue
            row = {"yymm": yymm, "date": p[C_DATE].strip(),
                       "source": p[C_SOURCE].strip(), "name": p[C_NAME].strip()}
            tot = 0
            for lab, i in STRUCT.items():
                try:
                    v = int((p[i] or "0").strip() or 0)
                except ValueError:
                    v = 0
                row[lab] = v
                tot += v
            row["units"] = tot
            out[k][yymm] = row
    return out


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    frame = {(x["state"], x["bps_id"]): x for x in rd(FRAME)}
    clean = clean_oracle(frame.values())
    b1 = {(x["state"], x["bps_id"]): x for x in rd(B1)}

    keys = [(s, b) for s, b, _, _, _, _ in SAMPLE]
    missing = [k for k in keys if k not in frame]
    if missing:
        print("NOT IN FRAME (fix the draw before going further):")
        for k in missing:
            print("   %s" % (k,))
        return 1

    print("SPIKE B SAMPLE - draw and oracle pull")
    print("clean-oracle offices in frame: %d" % len(clean))
    print("months on disk: %s .. %s (%d)"
          % (months_available()[0], months_available()[-1],
             len(months_available())))
    print()
    print("%-34s %-4s %-8s %-7s %-7s %s"
          % ("office", "st", "bps_id", "units", "oracle", "bucket1"))
    for s, b, nm, cat, tier, why in SAMPLE:
        fr = frame[(s, b)]
        print("%-34s %-4s %-8s %-7d %-7s %s"
              % (fr["place_name"][:34], s, b, num(fr, "units_12mo"),
                 "YES" if (s, b) in clean else "NO",
                 "yes(%s)" % cat if (s, b) in b1 else "NO"))

    data = pull(keys)
    rows = []
    print("\nORACLE MONTHS (Source 5/9 = imputed, unusable for scoring)")
    for s, b, nm, cat, tier, why in SAMPLE:
        m = data[(s, b)]
        usable = [y for y in sorted(m) if m[y]["source"] not in IMPUTED_SOURCES]
        bad = [y for y in sorted(m) if m[y]["source"] in IMPUTED_SOURCES]
        print("  %-30s months=%2d usable=%2d imputed=%d  %s"
              % (frame[(s, b)]["place_name"][:30], len(m), len(usable),
                 len(bad), ("imputed: " + ",".join(bad)) if bad else ""))
        for y in sorted(m):
            r = m[y]
            rows.append({"state": s, "bps_id": b,
                             "place_name": frame[(s, b)]["place_name"],
                             "yymm": y, "survey_date": r["date"], "source": r["source"],
                             "usable": "Y" if r["source"] not in IMPUTED_SOURCES
                             else "N",
                             "units": r["units"], "u1": r["u1"], "u2": r["u2"],
                             "u34": r["u34"], "u5p": r["u5p"], "catalog": cat,
                             "tier": tier, "rationale": why})

    p = os.path.join(OUT, "bps_months.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\nwrote %s (%d rows)" % (os.path.relpath(p, ROOT), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
