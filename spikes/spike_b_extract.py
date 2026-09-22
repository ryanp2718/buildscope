# -*- coding: utf-8 -*-
"""Spike B step 4: count new residential units per month, per jurisdiction.

The classification rule for each jurisdiction is written out in full below,
against the vocabulary printed by `spike_b_values.py`. This is the judgement
call Spike B exists to test, so it is stated rather than buried:

  AUSTIN     permittype = 'BP' and work_class = 'New' and permit_class in the
             Census structure classes. **The permittype filter is the whole
             ballgame.** Austin issues an Electrical, Mechanical and Plumbing
             sub-permit alongside each Building Permit, and every one of them
             carries a populated housing_units value. Summing without it
             counts a dwelling up to four times: 732 permits / 3,991 units
             against a BPS figure of 483. Filtering to BP alone gives 185
             permits / 488 units - a 1.0% error against the same month. This
             is the single largest definitional trap found in Spike B, it is
             invisible unless you look at the permit-type breakdown, and it
             would have silently discredited the headline metric.

             The original rule, for the record, was: work_class = 'New' and
             permit_class in the Census structure
             classes. Austin publishes permit_class as "R- 101 Single Family
             Houses", "R- 103 Two Family Bldgs", "C- 105 Five or More Family
             Bldgs" - these ARE the BPS structure-type codes (101/102/103/104/
             105), so Austin's own taxonomy is already the comparison
             taxonomy. Excludes "R- 329 Res Structures Other Than Buildings"
             and "Res. Driveway & Sidewalk", which are residential-adjacent
             but are not dwellings.
  SEATTLE    permitclassmapped = 'Residential' and permittypedesc = 'New'.
             The dataset is already restricted to new construction.
  CHARLOTTE  worktype = 'New' and numunits > 0. Charlotte's permittype splits
             One/Two Family from Commercial and files apartment buildings
             under Commercial, so permittype alone would drop multifamily;
             a positive unit count is the residential test that survives that.
  COLUMBUS   GENERAL_TYPE in ('1,2,3 Family - New Structure',
             'Multi Family - New Structure').
  NASHVILLE  Permit_Type_Description = 'Building Residential - New'.
             **No unit field exists**, so Nashville yields permit counts only
             and cannot produce an error figure against BPS units.

Aggregates are computed server-side (count and sum) rather than by pulling
rows, which keeps this to two requests per jurisdiction-month.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

MONTHS = [("2601", "2026-01-01", "2026-02-01"),
          ("2602", "2026-02-01", "2026-03-01"),
          ("2603", "2026-03-01", "2026-04-01")]

AUSTIN_CLASSES = ("R- 101", "R- 102", "R- 103", "R- 104", "C- 105", "R- 105")

JOBS = [
    {"key": "austin", "state": "48", "bps_id": "033000", "label": "Austin TX",
         "platform": "socrata",
         "base": "https://data.austintexas.gov/resource/3syk-w9eu.json",
         "date": "issue_date", "units": "housing_units",
         "where": "permittype='BP' AND work_class='New' AND (" + " OR ".join(
             "starts_with(permit_class,'%s')" % c for c in AUSTIN_CLASSES) + ")",
         "group": "permit_class"},
    {"key": "seattle", "state": "53", "bps_id": "475000", "label": "Seattle WA",
         "platform": "socrata",
         "base": "https://data.seattle.gov/resource/8tqq-u7ib.json",
         "date": "issueddate", "units": "housingunits",
         "where": "permitclassmapped='Residential' AND permittypedesc='New'",
         "group": None},
    {"key": "charlotte", "state": "37", "bps_id": "379000",
         "label": "Mecklenburg County NC", "platform": "arcgis",
         "base": "https://meckgis.mecklenburgcountync.gov/server/rest/services/"
              "BuildingPermits/FeatureServer/0",
         "date": "issuedate", "units": "numunits",
         "where": "worktype='New' AND numunits>0", "group": "permittype"},
    {"key": "columbus", "state": "39", "bps_id": "135700", "label": "Columbus OH",
         "platform": "arcgis",
         "base": "https://services1.arcgis.com/9yy6msODkIBzkUXU/arcgis/rest/"
              "services/Building_Permits/FeatureServer/0",
         "date": "ISSUED_DT", "units": "UNITS",
         "where": "GENERAL_TYPE IN ('1,2,3 Family - New Structure',"
               "'Multi Family - New Structure')", "group": "GENERAL_TYPE"},
    {"key": "nashville", "state": "47", "bps_id": "605000",
         "label": "Nashville-Davidson TN", "platform": "arcgis",
         "base": "https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/"
              "services/Building_Permits_Issued_2/FeatureServer/0",
         "date": "Date_Issued", "units": None,
         "where": "Permit_Type_Description='Building Residential - New'",
         "group": "Permit_Subtype_Description"},
]


def soc(job, lo, hi):
    sel = "count(*) as n"
    if job["units"]:
        sel += ", sum(%s) as units" % job["units"]
    w = "%s AND %s >= '%sT00:00:00' AND %s < '%sT00:00:00'" % (
        job["where"], job["date"], lo, job["date"], hi)
    d = {"$select": sel, "$where": w, "$limit": 200}
    if job["group"]:
        d["$select"] = job["group"] + ", " + sel
        d["$group"] = job["group"]
    return job["base"] + "?" + urllib.parse.urlencode(d)


def arc(job, lo, hi):
    stats = [{"statisticType": "count", "onStatisticField": job["date"],
              "outStatisticFieldName": "n"}]
    if job["units"]:
        stats.append({"statisticType": "sum", "onStatisticField": job["units"],
                      "outStatisticFieldName": "units"})
    w = ("%s AND %s >= TIMESTAMP '%s 00:00:00' AND %s < TIMESTAMP '%s 00:00:00'"
         % (job["where"], job["date"], lo, job["date"], hi))
    d = {"where": w, "f": "json", "outStatistics": json.dumps(stats)}
    if job["group"]:
        d["groupByFieldsForStatistics"] = job["group"]
    return job["base"] + "/query?" + urllib.parse.urlencode(d)


def parse(html, platform, group):
    rows = (json.loads(html) if platform == "socrata"
            else [f.get("attributes", {})
                  for f in json.loads(html).get("features", [])])
    n = units = 0
    split = {}
    for r in rows:
        c = int(float(r.get("n") or 0))
        u = r.get("units")
        u = int(float(u)) if u not in (None, "") else None
        n += c
        if u:
            units += u
        if group:
            split[str(r.get(group, ""))[:44]] = {"n": c, "units": u}
    return n, units, split


def main():
    mf.retarget("spike_b")
    op = mf._opener()
    out = {}
    print("SPIKE B - new residential units by month\n")
    for job in JOBS:
        print("\n%s  [%s]" % (job["label"], job["platform"]))
        out[job["key"]] = {"label": job["label"], "state": job["state"],
                               "bps_id": job["bps_id"], "months": {},
                               "units_field": job["units"], "rule": job["where"]}
        for yymm, lo, hi in MONTHS:
            url = (soc(job, lo, hi) if job["platform"] == "socrata"
                   else arc(job, lo, hi))
            html, row = mf.fetch(op, url, "ex_%s_%s" % (job["key"], yymm),
                                 job["key"], job["platform"], "API-DATA")
            if html is None or row["verdict"] != "ok":
                out[job["key"]]["months"][yymm] = {
                    "error": row["verdict_reason"] if row else "no response"}
                continue
            n, units, split = parse(html, job["platform"], job["group"])
            out[job["key"]]["months"][yymm] = {"permits": n, "units": units,
                                                   "split": split}
            print("    %s  permits=%-6d units=%s" %
                  (yymm, n, units if job["units"] else "n/a (no unit field)"))

    p = os.path.join(mf.OUT, "extract.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("\nwrote %s" % os.path.relpath(p, mf.ROOT))
    print("requests spent: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
