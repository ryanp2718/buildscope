# -*- coding: utf-8 -*-
"""Spike B step 1: resolve each sampled office to a queryable endpoint + schema.

The sample changed during discovery, and the reason is a finding in its own
right. `bucket1_candidates.csv` classifies an office as bucket 1 when a
**publisher** in the open-data catalogs matched it. Checking at the **dataset**
level, scoped to that publisher, five of nine offices checked have no building
permit dataset at all:

    Austin TX              OK   Socrata  Issued Construction Permits
    Seattle WA             OK   Socrata  Building Permits
    Mecklenburg County NC  OK   ArcGIS   Building Permits (City of Charlotte)
    Columbus OH            OK   ArcGIS   Building Permits
    Nashville-Davidson TN  OK   ArcGIS   Building Permits Issued
    Madison WI             --   parking permits and road closures only
    Osceola County FL      --   address points, parcels, contours; no permits
    Frisco TX              --   no permit dataset under the matched publisher
    Miami-Dade Unincorp FL --   building violations and water permits, no permits

So **44% of publisher-level bucket-1 classifications do not survive dataset-level
checking.** That qualifies claim 3b in section 9 - "bucket 1 is 0.90% of offices
but 16.6% of national units" is a publisher-level figure and is an upper bound.

It also cost the sample its unincorporated-county slot: both unincorporated
counties tried (Osceola, Miami-Dade) publish no permits, which matters because
four of the ten highest-volume permit offices in the country are unincorporated
county areas.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402
DATASETS = [
    ("austin", "48", "033000", "Austin TX", "socrata",
     "https://data.austintexas.gov/resource/3syk-w9eu.json",
     "Issued Construction Permits"),
    ("seattle", "53", "475000", "Seattle WA", "socrata",
     "https://data.seattle.gov/resource/76t5-zqzr.json",
     "Building Permits"),
    ("charlotte", "37", "379000", "Mecklenburg County NC", "arcgis",
     "645eba06f0af44e5ac5d40", "Building Permits (City of Charlotte)"),
    ("columbus", "39", "135700", "Columbus OH", "arcgis",
     None, "Building Permits"),
    ("nashville", "47", "605000", "Nashville-Davidson TN", "arcgis",
     None, "Building Permits Issued"),
]

HUB = "https://hub.arcgis.com/api/v3/datasets?%s"


def hub_search(source, q):
    return HUB % urllib.parse.urlencode(
        {"filter[source]": source, "q": q, "page[size]": 20})


ARCGIS_SOURCES = {
    "charlotte": ("City of Charlotte", "building permits"),
    "columbus": ("City of Columbus Maps & Apps", "building permits"),
    "nashville": ("Nashville GIS", "building permits issued"),
}


def main():
    mf.retarget("spike_b")
    op = mf._opener()
    out = {}
    print("SPIKE B - endpoint + schema resolution\n")

    # ---- ArcGIS: resolve hub dataset -> service url ---------------------
    for key in ("charlotte", "columbus", "nashville"):
        src, q = ARCGIS_SOURCES[key]
        html, row = mf.fetch(op, hub_search(src, q), "ep_hub_%s" % key,
                             key, "arcgis", "API-CATALOG")
        if html is None or row["verdict"] != "ok":
            continue
        j = json.loads(html)
        cands = []
        for r in j.get("data", []):
            a = r.get("attributes", {})
            nm = (a.get("name") or "")
            url = a.get("url") or ""
            if "permit" in nm.lower() and url:
                cands.append((nm, url, a.get("recordCount"),
                              a.get("orgName") or a.get("source")))
        print("  %s -> %d permit datasets with a service url" % (key, len(cands)))
        for nm, url, rc, org in cands[:6]:
            print("      %-44s rc=%-8s %s" % (nm[:44], str(rc)[:8], url[:70]))
        out[key] = cands
        print()

    p = os.path.join(mf.OUT, "endpoints.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("wrote %s" % os.path.relpath(p, mf.ROOT))
    print("requests spent: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
