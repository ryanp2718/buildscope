# -*- coding: utf-8 -*-
"""Tier-2 rerun, decisive test: does Yakima County's Accela reach INSIDE Wapato?

Wapato WA is the one tier-2 place whose parent county runs an enumerable
(bucket 3) portal, so it is the only row in the stratum that could flip. But a
county portal normally covers the UNINCORPORATED county only - Weld County's
own page says so in as many words - and Wapato is an incorporated city.

The test has two halves, because neither alone is conclusive:
  1. Does the county Accela behave as bucket 3 at all (empty criteria -> rows)?
  2. Do any returned records carry a Wapato address, and does the county state
     its jurisdiction? A Wapato *mailing* address can sit outside city limits,
     so a hit here is suggestive, not proof; the stated scope decides.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spike_a_query_probe import accela, req, HTMLDIR  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "spike_a")

SCOPE = re.compile(
    r"[^.>]{0,120}(?:unincorporated|city limits|incorporated cit|"
    r"outside the cit|within the cit|interlocal)[^.<]{0,120}", re.I)


def strip_tags(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", h))


def main():
    if not os.path.isdir(HTMLDIR):
        os.makedirs(HTMLDIR)
    res = {}

    print("Yakima County WA - Accela ACA (the only tier-2 flip candidate)")
    res["yakima_accela"] = accela("https://aca-prod.accela.com", "YAKIMACO",
                                  label="YakimaCo")

    # Did any returned record carry a Wapato address?
    hits = {}
    for name in sorted(os.listdir(HTMLDIR)):
        if "YAKIMACO" not in name:
            continue
        txt = strip_tags(io.open(os.path.join(HTMLDIR, name),
                                 encoding="utf-8", errors="replace").read())
        hits[name] = {
            "wapato": len(re.findall(r"(?i)\bwapato\b", txt)),
            "yakima": len(re.findall(r"(?i)\byakima\b", txt)),
            "sample": sorted(set(re.findall(r"(?i)[A-Z0-9 ]{4,30}\bWAPATO\b", txt)))[:5]}
        print("  %-44s wapato=%-3d yakima=%-3d" % (name[:44], hits[name]["wapato"],
                                                   hits[name]["yakima"]))
    res["wapato_in_results"] = hits

    # What does the county say its building division covers?
    print("\nStated jurisdiction of Yakima County Building and Fire Safety")
    for url in ("https://www.yakimacounty.us/1181/Building",
                "https://www.yakimacounty.us/1182/Permits"):
        st, final, html = req(url)
        if st != 200:
            print("  HTTP %s  %s" % (st, url))
            res.setdefault("scope", {})[url] = {"status": st}
            continue
        txt = strip_tags(html)
        found = sorted({" ".join(m.split()) for m in SCOPE.findall(txt)})
        found = [f for f in found if len(f) > 40][:6]
        res.setdefault("scope", {})[url] = {"status": st, "statements": found}
        print("  %s" % url)
        for f in found:
            print("     * %s" % f[:190])
        if not found:
            print("     (no explicit jurisdiction statement on this page)")

    with io.open(os.path.join(OUT, "tier2_yakima.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1))
    print("\nwrote data/spike_a/tier2_yakima.json")


if __name__ == "__main__":
    main()
