# -*- coding: utf-8 -*-
"""Spike B step 0: find the actual permit dataset for each sampled office.

The catalog sweep that produced `bucket1_candidates.csv` matched **publishers**,
not datasets - `bucket1_audit.csv` carries a publisher name and an empty
`datasets` column for every one of the sampled five. So "bucket 1" currently
means *this jurisdiction runs an open-data portal*, which is not the same claim
as *this jurisdiction publishes building permits*.

That gap matters beyond Spike B: section 8's headline that bucket 1 covers
**16.6% of national units** is a publisher-level figure, and if publishers
routinely lack a permit dataset then that number is an overstatement. Testing
it on five offices does not settle it, but it is the first evidence either way.

Discovery uses each platform's own catalog API rather than guessing URLs:
  Socrata -> api.us.socrata.com/api/catalog/v1
  ArcGIS  -> hub.arcgis.com/api/v3/datasets

Every response is captured through the Measurement provenance layer, so each
one lands on disk with a verdict written in the same operation.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

SOCRATA = "https://api.us.socrata.com/api/catalog/v1?%s"
ARCGIS = "https://hub.arcgis.com/api/v3/datasets?%s"

# (key, label, platform, domain-or-org, query)
# For ArcGIS the `domain` slot carries the PUBLISHER name recorded by the
# catalog sweep in bucket1_audit.csv, and the query is scoped to it with
# filter[source]. An unscoped keyword search is worthless here: it returned
# "New Construction Permits in Charlotte County" (Florida) for Charlotte NC and
# "Madison Temperature" from a Texas college for Madison WI. Name-similarity
# matching has now failed in this project at least four times - Marina/Marin in
# the catalog sweep, Bowling Green KY matching a Virginia town, Brazil IN
# matching the country - and the fix is always to scope to an authoritative
# attribute instead.
TARGETS = [
    ("37_379000", "Mecklenburg County NC", "arcgis", "City of Charlotte", "permits"),
    ("12_651000", "Osceola County FL", "arcgis", "OsceolaGIS", "permits"),
    ("55_516500", "Madison WI", "arcgis", "City of Madison Map Data", "permits"),
    ("55_516500b", "Madison WI (alt org)", "arcgis", "City of Madison, WI", "permits"),
]


def socrata_url(domain, q):
    return SOCRATA % urllib.parse.urlencode(
        {"q": q, "domains": domain, "search_context": domain, "limit": 25})


def arcgis_url(q, source=None):
    # Hub v3 is JSON:API shaped: page size is page[size], not num. The first
    # attempt used num and earned a clean 400 saying so, which the manifest
    # still records.
    d = {"q": q, "page[size]": 20}
    if source:
        d["filter[source]"] = source
    return ARCGIS % urllib.parse.urlencode(d)


def summarise(path, platform):
    """Print what came back, so the choice of dataset is visible not asserted."""
    j = json.load(open(path, encoding="utf-8"))
    out = []
    if platform == "socrata":
        for r in j.get("results", []):
            res = r.get("resource", {})
            out.append((res.get("name", ""), res.get("id", ""),
                        res.get("type", ""),
                        (r.get("metadata", {}) or {}).get("domain", "")))
    else:
        for r in j.get("data", []):
            a = r.get("attributes", {})
            out.append((a.get("name", ""), r.get("id", ""),
                        a.get("recordCount", a.get("type", "")),
                        a.get("orgName", "") or a.get("source", "")))
    return out


def main():
    mf.retarget("spike_b")
    op = mf._opener()
    print("SPIKE B - dataset discovery (catalog APIs, no URL guessing)\n")
    found = {}
    for key, label, platform, domain, q in TARGETS:
        url = (socrata_url(domain, q) if platform == "socrata"
               else arcgis_url(q, domain))
        name = "cat_%s_%s" % (platform, key)
        html, row = mf.fetch(op, url, name, key, platform, "API-CATALOG")
        if html is None or row["verdict"] != "ok":
            continue
        try:
            hits = summarise(os.path.join(mf.PAGES, name + ".html"), platform)
        except Exception as e:
            print("    parse failed: %s" % e)
            continue
        found[key] = hits
        print("  %s  -> %d catalog hits" % (label, len(hits)))
        for nm, did, typ, dom in hits[:8]:
            print("      %-52s %-22s %s" % (nm[:52], did[:22], dom[:28]))
        print()
    print("requests spent: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
