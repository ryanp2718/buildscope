# -*- coding: utf-8 -*-
"""Spike B step 3: what values do the work-type fields actually take?

This is the part of Spike B that was always going to carry the uncertainty.
Deciding what counts as "new residential construction" is a judgement made
against a controlled vocabulary that differs in every jurisdiction, and the
only honest way to make it is to print the vocabulary first and write the rule
against what is there - rather than to write a rule that sounds reasonable and
let it silently match nothing.

Every vocabulary printed here goes into the evidence report, so the reader can
disagree with the classification without re-running anything.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

SOCRATA = [
    ("austin", "https://data.austintexas.gov/resource/3syk-w9eu.json",
     ["permit_class", "work_class"]),
    ("seattle", "https://data.seattle.gov/resource/8tqq-u7ib.json",
     ["permitclassmapped", "permittypedesc"]),
]
ARCGIS = [
    ("charlotte",
     "https://meckgis.mecklenburgcountync.gov/server/rest/services/"
     "BuildingPermits/FeatureServer/0",
     ["worktype", "permittype"]),
    ("columbus",
     "https://services1.arcgis.com/9yy6msODkIBzkUXU/arcgis/rest/services/"
     "Building_Permits/FeatureServer/0",
     ["B1_PER_TYPE", "GENERAL_TYPE"]),
    ("nashville",
     "https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/services/"
     "Building_Permits_Issued_2/FeatureServer/0",
     ["Permit_Type_Description"]),
]


def soc_url(base, fields):
    sel = ",".join(fields) + ",count(*) as n"
    return base + "?" + urllib.parse.urlencode(
        {"$select": sel, "$group": ",".join(fields), "$order": "n DESC",
         "$limit": 40})


def arc_url(base, fields):
    return base + "/query?" + urllib.parse.urlencode({
        "where": "1=1", "f": "json",
        "groupByFieldsForStatistics": ",".join(fields),
        "outStatistics": json.dumps([{"statisticType": "count",
                                      "onStatisticField": fields[0],
                                      "outStatisticFieldName": "n"}]),
        "orderByFields": "n DESC", "resultRecordCount": 40})


def main():
    mf.retarget("spike_b")
    op = mf._opener()
    out = {}
    print("SPIKE B - work-type vocabularies\n")

    for key, base, fields in SOCRATA:
        html, row = mf.fetch(op, soc_url(base, fields), "val_%s" % key,
                             key, "socrata", "API-DATA")
        if html is None or row["verdict"] != "ok":
            continue
        rows = json.loads(html)
        out[key] = rows
        print("\n%s  (%s)" % (key.upper(), " x ".join(fields)))
        for r in rows[:22]:
            vals = " | ".join(str(r.get(f, ""))[:34] for f in fields)
            print("   %-62s %s" % (vals[:62], r.get("n", "")))

    for key, base, fields in ARCGIS:
        html, row = mf.fetch(op, arc_url(base, fields), "val_%s" % key,
                             key, "arcgis", "API-DATA")
        if html is None or row["verdict"] != "ok":
            continue
        feats = json.loads(html).get("features", [])
        rows = [f.get("attributes", {}) for f in feats]
        rows.sort(key=lambda r: -(r.get("n") or 0))
        out[key] = rows
        print("\n%s  (%s)" % (key.upper(), " x ".join(fields)))
        for r in rows[:22]:
            vals = " | ".join(str(r.get(f, ""))[:34] for f in fields)
            print("   %-62s %s" % (vals[:62], r.get("n", "")))

    p = os.path.join(mf.OUT, "vocabularies.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("\nwrote %s" % os.path.relpath(p, mf.ROOT))
    print("requests spent: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
