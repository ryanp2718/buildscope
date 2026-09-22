# -*- coding: utf-8 -*-
"""Yakima County Accela: empty-criteria and city=WAPATO searches.

The generic Accela probe assumed a date-range general search (txtGSStartDate /
txtGSEndDate), which is what Clark County NV and Oregon render. Yakima renders
an ADDRESS-shaped general search instead - no date fields, but a txtGSCity
field. That variation matters twice over:

  * it gives a direct test of whether the county tenancy holds records inside
    the incorporated city of Wapato, and
  * it means an Accela extractor cannot assume field names across tenancies;
    it has to read the rendered form. Recorded as a finding in its own right.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spike_a_query_probe import req, hidden, diag, HTMLDIR, PAUSE  # noqa: E402
import time  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "spike_a")
HOME = ("https://aca-prod.accela.com/YAKIMACO/Cap/CapHome.aspx"
        "?module=Building&TabName=Building")
PFX = "ctl00$PlaceHolderMain$generalSearchForm$"
TARGET = "ctl00$PlaceHolderMain$btnNewSearch"


def strip_tags(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", h))


def run(label, extra, save):
    st, _, html = req(HOME)
    time.sleep(PAUSE)
    if st != 200:
        print("  %-18s home HTTP %s" % (label, st))
        return {"error": "home %s" % st}
    data = dict(hidden(html))
    data.update(extra)
    data["__EVENTTARGET"] = TARGET
    data["__EVENTARGUMENT"] = ""
    st2, _, html2 = req(HOME, data=data, referer=HOME)
    time.sleep(PAUSE)
    if st2 != 200:
        print("  %-18s HTTP %s" % (label, st2))
        return {"status": st2}
    d = diag(html2, label, save=save)
    txt = strip_tags(html2)
    d["wapato_mentions"] = len(re.findall(r"(?i)\bwapato\b", txt))
    d["record_ids"] = sorted(set(re.findall(r"\b[A-Z]{2,5}[-/]?\d{2,4}[-/]\d{3,6}\b",
                                            txt)))[:8]
    d["cities_seen"] = sorted({
        c.upper() for c in re.findall(
            r"(?i)\b(WAPATO|YAKIMA|TOPPENISH|SUNNYSIDE|SELAH|UNION GAP|ZILLAH|"
            r"GRANDVIEW|MOXEE|TIETON|NACHES|HARRAH|MABTON|GRANGER)\b", txt)})
    print("     wapato=%-3d ids=%s" % (d["wapato_mentions"], ",".join(d["record_ids"][:4])))
    print("     cities in result page: %s" % (", ".join(d["cities_seen"]) or "-"))
    return d


def main():
    if not os.path.isdir(HTMLDIR):
        os.makedirs(HTMLDIR)
    res = {}
    print("Yakima County Accela - empty criteria (is it bucket 3 at all?)")
    res["empty"] = run("empty criteria", {}, "q_YAKIMACO_empty.html")

    print("\nYakima County Accela - city = WAPATO (does the county reach inside?)")
    res["city_wapato"] = run("city=WAPATO", {PFX + "txtGSCity": "WAPATO"},
                             "q_YAKIMACO_wapato.html")

    with io.open(os.path.join(OUT, "tier2_yakima2.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1))
    print("\nwrote data/spike_a/tier2_yakima2.json")


if __name__ == "__main__":
    main()
