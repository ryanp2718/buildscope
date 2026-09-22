# -*- coding: utf-8 -*-
"""Spike B step 2: learn each dataset's schema before asking it anything.

The three questions the protocol wants answered per jurisdiction are schema
questions, and they are answered here rather than guessed:

  - Can new residential construction be distinguished from alteration and
    addition from portal data alone? By what field?
  - Can housing UNIT counts be obtained at all, or only permit counts?
  - Does the portal expose an issue date distinct from an application date?

Nothing is inferred from a dataset's title. A dataset called "Building Permits
Issued" may carry an application date and no issue date, and may have no unit
field at all - in which case the honest answer to question two is "permit
counts only", which is a finding, not a failure.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

ENDPOINTS = [
    ("austin", "Austin TX", "socrata",
     "https://data.austintexas.gov/resource/3syk-w9eu.json"),
    ("seattle", "Seattle WA", "socrata",
     "https://data.seattle.gov/resource/76t5-zqzr.json"),
    ("charlotte", "Mecklenburg County NC", "arcgis", None),   # resolved below
    ("columbus", "Columbus OH", "arcgis",
     "https://services1.arcgis.com/9yy6msODkIBzkUXU/arcgis/rest/services/"
     "Building_Permits/FeatureServer/0"),
    ("nashville", "Nashville-Davidson TN", "arcgis",
     "https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/services/"
     "Building_Permits_Issued_2/FeatureServer/0"),
]

HUB = "https://hub.arcgis.com/api/v3/datasets?%s"

# fields whose NAME suggests they answer one of the protocol's questions.
# Matching on name is a starting point for a human read, never a conclusion.
HINT = {
    "unit": ("unit", "dwelling", "du_", "numunits", "no_of_units", "housing"),
    "worktype": ("worktype", "work_type", "permit_type", "permittype",
                 "permit_class", "permitclass", "subtype", "work_class",
                 "workclass", "description", "category", "type"),
    "date": ("issue", "issued", "applied", "application", "file", "final",
             "date", "status_date"),
}


def hub(source, q):
    return HUB % urllib.parse.urlencode(
        {"filter[source]": source, "q": q, "page[size]": 20})


def resolve_charlotte(op):
    html, row = mf.fetch(op, hub("City of Charlotte", "building permits"),
                         "ep_hub_charlotte_retry", "charlotte", "arcgis",
                         "API-CATALOG")
    if html is None or row["verdict"] != "ok":
        return None
    for r in json.loads(html).get("data", []):
        a = r.get("attributes", {})
        nm = (a.get("name") or "").lower()
        url = a.get("url") or ""
        if nm == "building permits" and "rest/services" in url:
            print("      resolved: %s  rc=%s" % (url, a.get("recordCount")))
            return url
    return None


def classify(fields):
    out = {k: [] for k in HINT}
    for f in fields:
        low = f.lower()
        for k, pats in HINT.items():
            if any(p in low for p in pats):
                out[k].append(f)
    return out


def main():
    mf.retarget("spike_b")
    op = mf._opener()
    schema = {}
    print("SPIKE B - schema probe\n")

    eps = []
    for key, label, plat, url in ENDPOINTS:
        if key == "charlotte" and url is None:
            print("  charlotte: re-resolving (previous attempt timed out)")
            url = resolve_charlotte(op)
            if not url:
                print("      still unresolved; recorded and skipped")
                continue
        eps.append((key, label, plat, url))

    for key, label, plat, url in eps:
        print("\n%s  [%s]" % (label, plat))
        if plat == "socrata":
            q = url + "?$limit=3"
            html, row = mf.fetch(op, q, "sch_%s" % key, key, plat, "API-DATA")
            if html is None or row["verdict"] != "ok":
                continue
            rows = json.loads(html)
            fields = sorted(rows[0].keys()) if rows else []
            sample = rows[0] if rows else {}
        else:
            q = url + "/query?" + urllib.parse.urlencode(
                {"where": "1=1", "outFields": "*", "resultRecordCount": 3,
                 "f": "json"})
            html, row = mf.fetch(op, q, "sch_%s" % key, key, plat, "API-DATA")
            if html is None or row["verdict"] != "ok":
                continue
            j = json.loads(html)
            feats = j.get("features", [])
            fields = sorted(f["name"] for f in j.get("fields", []))
            sample = feats[0].get("attributes", {}) if feats else {}

        hits = classify(fields)
        print("  fields: %d" % len(fields))
        for k in ("unit", "worktype", "date"):
            print("    %-9s %s" % (k, ", ".join(hits[k][:9]) or "NONE FOUND"))
        schema[key] = dict(label=label, platform=plat, url=url,
                           fields=fields, hints=hits,
                           sample={k: str(v)[:60] for k, v in
                                   list(sample.items())[:40]})

    p = os.path.join(mf.OUT, "schema.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=1)
    print("\nwrote %s" % os.path.relpath(p, mf.ROOT))
    print("requests spent: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
