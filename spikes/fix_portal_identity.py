# -*- coding: utf-8 -*-
"""Correct the office ids in `data/spike_a/portals.csv` and register what the
downstream artifacts inherited.

The defect: `portals.csv` was assembled by hand during Spike A, and **all 28 of
its `bps_id` values are wrong**. Every place *name* is right and every name
resolves to exactly one office in the frame within its own state, so the
correct identity was recoverable for all 28 rows without a single request.

Why it went unnoticed for a day: `spike_a_probe.py` wrote correct keys (28/28
verified against the frame), and the hand-built `portals.csv` that replaced it
as the input to step 3 did not. Nothing compared them, because nothing knew it
should. Four artifacts keyed off the bad file and inherited it - portal_probe,
query_probe, final_probe and depth_probe.

Seven of the 28 wrong ids **resolve to a real, different office**:

    12|633000  recorded as St. Johns County FL   ->  is Okeechobee County FL
    01|447000  recorded as Madison County AL     ->  is Selma AL
    22|433000  recorded as Lafayette Parish LA   ->  is Marksville LA
    41|545000  recorded as McMinnville OR        ->  is Warrenton OR
    13|720000  recorded as South Fulton GA       ->  is Waynesboro GA
    31|061000  recorded as Brownville village NE ->  is Bristow village NE
    36|213000  recorded as Dresden village NY    ->  is East Hampton village NY

Those are the dangerous ones. An existence check passes on every one of them,
which is exactly ADR-0007's argument for why office identity must be assigned
from the frame rather than carried alongside a name and trusted. The other 21
do not resolve at all and would have failed any join loudly.

What this script does NOT do is rewrite the four probe JSONs. They are dated
working notes that ADR-0005 already declares non-authoritative, several scripts
read them by their existing keys, and silently re-keying a captured artifact is
the history rewrite D1 exists to prevent. Instead every inherited instance is
registered in `data/corrections.csv`, which `check_identity.py` reads, so the
wrong keys stay visible and stay accounted for.

`classification.csv` is unaffected: 28/28 of its keys, names and unit counts
match the frame exactly. It was built independently and correctly, which is the
measured basis for ADR-0005 naming it the single source of identity.
"""
import csv
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "data", "frame", "bps_frame.csv")
PORTALS = os.path.join(ROOT, "data", "spike_a", "portals.csv")
CORRECTIONS = os.path.join(ROOT, "data", "corrections.csv")
INHERITED = ["data/spike_a/portal_probe.json", "data/spike_a/query_probe.json",
             "data/spike_a/final_probe.json", "data/spike_a/depth_probe.json"]

CFIELDS = ["artifact", "key_as_recorded", "key_correct", "place_name",
           "collides_with", "recorded", "reason"]
REASON = ("portals.csv bps_id column filled by hand during Spike A; all 28 "
          "wrong. Correct id recovered by unique place_name match within "
          "state against data/frame/bps_frame.csv.")
TODAY = "2026-09-21"


def load_frame():
    by_key, by_name = {}, {}
    with io.open(FRAME, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            by_key[(r["state"], r["bps_id"])] = r["place_name"]
            by_name.setdefault((r["state"], r["place_name"].strip().lower()),
                               []).append(r["bps_id"])
    return by_key, by_name


def main():
    by_key, by_name = load_frame()
    with io.open(PORTALS, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    fixed, corrections, unresolved = [], [], []
    for r in rows:
        name = r["place_name"].strip().lower()
        cands = by_name.get((r["state"], name), [])
        if len(cands) != 1:
            unresolved.append((r["place_name"], len(cands)))
            r["bps_id_as_recorded"] = ""
            fixed.append(r)
            continue
        right = cands[0]
        wrong = r["bps_id"]
        if right == wrong:
            r["bps_id_as_recorded"] = ""
            fixed.append(r)
            continue
        collide = by_key.get((r["state"], wrong), "")
        r["bps_id"], r["bps_id_as_recorded"] = right, wrong
        fixed.append(r)
        for art in ["data/spike_a/portals.csv"] + INHERITED:
            corrections.append({
                "artifact": art,
                "key_as_recorded": "%s|%s" % (r["state"], wrong),
                "key_correct": "%s|%s" % (r["state"], right),
                "place_name": r["place_name"],
                "collides_with": collide,
                "recorded": TODAY,
                "reason": REASON})

    if unresolved:
        print("NOT corrected - place_name did not resolve uniquely:")
        for n, c in unresolved:
            print("   %-40s %d frame candidates" % (n, c))

    flds = list(rows[0].keys())
    if "bps_id_as_recorded" not in flds:
        flds.append("bps_id_as_recorded")
    with io.open(PORTALS, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=flds, lineterminator="\n")
        w.writeheader()
        for r in fixed:
            w.writerow(r)

    # Only register an inherited key that the artifact actually contains.
    live = []
    for c in corrections:
        path = os.path.join(ROOT, c["artifact"].replace("/", os.sep))
        if c["artifact"].endswith(".json"):
            try:
                if c["key_as_recorded"] not in json.load(
                        io.open(path, encoding="utf-8")):
                    continue
            except (IOError, ValueError):
                continue
        live.append(c)

    with io.open(CORRECTIONS, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CFIELDS, lineterminator="\n")
        w.writeheader()
        for c in sorted(live, key=lambda x: (x["artifact"],
                                             x["key_as_recorded"])):
            w.writerow(c)

    n_col = len(set(c["key_as_recorded"] for c in live if c["collides_with"]))
    print("portals.csv: %d rows, %d ids corrected"
          % (len(fixed), sum(1 for r in fixed if r["bps_id_as_recorded"])))
    print("corrections.csv: %d registered instances across %d artifacts, "
          "%d of which silently named a different real office"
          % (len(live), len(set(c["artifact"] for c in live)), n_col))
    return 0


if __name__ == "__main__":
    sys.exit(main())
