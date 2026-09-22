# -*- coding: utf-8 -*-
"""Tier-2 rerun, closing probes for the four places still open after round 1.

Ahnapee WI, Amador City CA (contractor WGA Inc), Eastbrook ME and Brownville NE
each needed one more page fetched before a bucket could be assigned at the
issuing level. The test applied is the same one used throughout Spike A: does
any reachable page expose a *search over issued records*, as opposed to
application forms to download?

Detection note: do NOT use a 'please enter...' style regex to decide that a
search returned nothing. Accela ships that string as a JavaScript constant on
every page, including pages that DID return results - it produced a false
negative in the first pass. The reliable discriminator is whether the result
list container and a row count are rendered in the markup.
"""
import io
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits.identity import user_agent   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "spike_a")
HTML = os.path.join(OUT, "html_tier2")
PAUSE = 1.5

SEARCH_UI = ("divsearchresultlist", "record results", "showing 1-", "gridview",
             "search results", "permit search", "search permits", "permit lookup",
             "record search", "search for a permit")
VENDORS = ("accela", "energov", "cityview", "etrakit", "sagesgov", "communitycore",
           "iworq", "avolvecloud", "citizenserve", "opengov", "mygovernmentonline",
           "smartgov", "municity", "buildingeye", "click2gov", "permittrax")

TARGETS = [
    ("55", "007500", "Ahnapee town, WI", "town licenses-and-permits page",
     "https://townofahnapee.org/licenses-and-permits/"),
    ("55", "007500", "Ahnapee town, WI", "Kewaunee County zoning forms",
     "https://www.kewauneeco.org/departments/land-water-conservation/zoning/"),
    ("06", "009000", "Amador City, CA", "contractor WGA Inc",
     "https://wgainc.net/"),
    ("06", "009000", "Amador City, CA", "city government/planning/building page",
     "https://amador-city.com/government-planning-building/"),
    ("23", "139000", "Eastbrook town, ME", "town website",
     "https://www.eastbrookme.com/"),
    ("23", "139000", "Eastbrook town, ME", "state code adoption list",
     "https://www.maine.gov/dps/fmo/building-codes/municipalities"),
    ("31", "064000", "Brownville village, NE", "village site",
     "https://www.brownville-ne.com/"),
    ("31", "064000", "Brownville village, NE", "county seat / Nemaha County",
     "https://nemahacountyne.gov/"),
]


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": user_agent(), "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        r = urllib.request.urlopen(req, timeout=20, context=ctx)
        return r.getcode(), r.geturl(), r.read(1500000)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(1500000)
        except Exception:
            body = b""
        return e.code, url, body
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
        return None, url, ("ERR:%s" % e).encode()


def main():
    if not os.path.isdir(HTML):
        os.makedirs(HTML)
    res = []
    for st, bid, place, label, url in TARGETS:
        code, final, body = fetch(url)
        err = body[:4] == b"ERR:"
        # strip scripts before looking for search UI, so a JS constant cannot
        # masquerade as rendered markup
        markup = re.sub(rb"(?is)<script.*?</script>", b" ", body)
        low = markup.lower()
        ui = sorted({k for k in SEARCH_UI if k.encode() in low})
        vend = sorted({v for v in VENDORS if v.encode() in body.lower()})
        pdfs = low.count(b".pdf")
        name = "%s_%s_%d.html" % (st, bid, abs(hash(url)) % 10 ** 8)
        if not err:
            io.open(os.path.join(HTML, name), "wb").write(body)
        res.append({"state": st, "bps_id": bid, "place": place, "label": label, "url": url,
                        "code": code, "bytes": len(body), "search_ui": ui, "vendors": vend,
                        "pdf_links": pdfs, "saved": None if err else name})
        print("%-22s %-32s %-4s %7db  ui=%-22s vend=%-14s pdf=%d"
              % (place[:22], label[:32], code, len(body),
                 ",".join(ui)[:22] or "-", ",".join(vend)[:14] or "-", pdfs))
        if err:
            print("   %s" % body[:110].decode("utf-8", "replace"))
        time.sleep(PAUSE)
    with io.open(os.path.join(OUT, "tier2_final.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1))
    print("\nwrote data/spike_a/tier2_final.json")


if __name__ == "__main__":
    main()
