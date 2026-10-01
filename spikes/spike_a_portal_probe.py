# -*- coding: utf-8 -*-
"""Spike A, step 3: fetch each located permit portal and measure the signals the
bucket classification turns on.

The bucket taxonomy (docs/design/history.md, Spike A) asks four things this script can answer
mechanically:

  bucket 5 (JS-gated)   -> is the page's content server-rendered, or is it an
                           empty SPA shell with a script bundle?
  bucket 2 vs 3/4       -> is there a search form, and what inputs does it want?
                           A form whose only required input is a permit number or
                           address is bucket 4; a date range or an optional-
                           criteria form is a bucket-3 candidate.
  bucket 1              -> does the host expose a documented data API?
  robots posture        -> does robots.txt disallow the permit path?

It does NOT decide the bucket. Empty-query behaviour has to be probed per vendor
and is recorded by hand in classification.csv; this produces the evidence that
judgment is made against, and saves the HTML for Spike C.

Writes data/spike_a/portal_probe.json and data/spike_a/html/portal_*.html.
"""
import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits.crawler_identity import user_agent   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTALS = os.path.join(ROOT, "data", "spike_a", "portals.csv")
OUTDIR = os.path.join(ROOT, "data", "spike_a")
HTMLDIR = os.path.join(OUTDIR, "html")
OUT = os.path.join(OUTDIR, "portal_probe.json")

TIMEOUT = 30
PAUSE = 1.5

VENDORS = {
    "Accela": ["accela", "aca-prod", "citizen access"],
    "Tyler EnerGov": ["energov", "tylerhost", "selfservice", "tyler technologies"],
    "CentralSquare": ["centralsquare", "click2gov"],
    "eTRAKiT": ["etrakit"],
    "CityView": ["cityview"],
    "OpenGov/ViewPoint": ["viewpointcloud", "opengov.com"],
    "Citizenserve": ["citizenserve"],
    "CivicPlus": ["civicplus", "civicengage"],
    "SagesGov": ["sagesgov"],
    "CommunityCore": ["communitycore"],
    "SmartGov": ["smartgovcommunity"],
    "GovOffice": ["govoffice"],
    "Revize": ["revize"],
    "MyGov": ["mygov.us"],
    "Socrata": ["socrata", "/resource/"],
    "ArcGIS": ["arcgis.com", "featureserver", "/rest/services"],
    "Granicus": ["granicus"],
    "KraftCodeServices": ["kraftcodeservices"],
}

# SPA shells: content is not in the HTML, so a fetch-and-parse crawler sees nothing.
SPA = ["ng-app", "ng-controller", "data-reactroot", "__NEXT_DATA__", "id=\"root\"",
       "id=\"app\"", "vue-app", "angular.min.js", "react-dom", "blazor"]

API_HINT = ["/api/", "/resource/", "featureserver", "odata", "/rest/",
            "application/json", "opendata", "data.json"]


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": user_agent(),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return r.status, r.geturl(), r.read(900000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(200000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, url, body
    except Exception as e:
        return None, url, "ERR:%s: %s" % (type(e).__name__, e)


def strip(html):
    h = re.sub(r"(?is)<script.*?</script>", " ", html)
    h = re.sub(r"(?is)<style.*?</style>", " ", h)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def forms(html):
    out = []
    for m in re.finditer(r"(?is)<form\b([^>]*)>(.*?)</form>", html):
        attrs, inner = m.group(1), m.group(2)
        act = re.search(r'action=["\']([^"\']*)["\']', attrs)
        names = re.findall(r'(?is)<(?:input|select|textarea)\b[^>]*name=["\']([^"\']+)["\']',
                           inner)
        types = re.findall(r'(?is)<input\b[^>]*type=["\']([^"\']+)["\']', inner)
        names = [n for n in names if not n.startswith("__")]   # drop ASP.NET viewstate
        if names:
            out.append({"action": act.group(1) if act else "",
                        "inputs": names[:20],
                        "has_date": bool(re.search(r"date|from|to|begin|end|start",
                                                   " ".join(names), re.I)),
                        "has_submit": "submit" in types or "image" in types})
    return out[:6]


def main():
    rows = list(csv.DictReader(open(PORTALS, newline="", encoding="utf-8")))
    if not os.path.isdir(HTMLDIR):
        os.makedirs(HTMLDIR)
    res = {}

    for i, r in enumerate(rows, 1):
        url = r["portal_url"]
        key = "%s|%s" % (r["state"], r["bps_id"])
        st, final, html = fetch(url)
        time.sleep(PAUSE)

        text = strip(html) if html and not html.startswith("ERR:") else ""
        scripts = sum(len(m) for m in re.findall(r"(?is)<script.*?</script>", html or ""))
        hay = ((html or "") + " " + final).lower()

        rec = {
            "place": r["place_name"], "state": r["state"], "url": url,
            "status": st, "final": final,
            "bytes": len(html or ""), "text_bytes": len(text),
            "script_bytes": scripts,
            "text_ratio": round(len(text) / max(1, len(html or "")), 3),
            "vendors": sorted({v for v, s in VENDORS.items()
                               if any(x in hay for x in s)}),
            "spa_markers": sorted({m for m in SPA if m.lower() in hay}),
            "api_hints": sorted({a for a in API_HINT if a in hay}),
            "forms": forms(html or ""),
            "robots": "",
        }

        pr = urllib.parse.urlparse(final if final.startswith("http") else url)
        rst, _, rtxt = fetch("%s://%s/robots.txt" % (pr.scheme, pr.netloc))
        time.sleep(PAUSE)
        rec["robots"] = (rtxt[:800] if rst == 200 else "(%s)" % rst)
        rec["robots_blocks_path"] = bool(
            rst == 200 and re.search(r"(?im)^disallow:\s*/\s*$", rtxt or ""))

        if html and not html.startswith("ERR:"):
            fn = "portal_" + re.sub(r"[^a-z0-9]+", "_",
                                    (r["state"] + "_" + r["place_name"]).lower()) + ".html"
            open(os.path.join(HTMLDIR, fn), "w", encoding="utf-8").write(html)

        res[key] = rec
        print("[%2d/%2d] %-34s %-4s %7s b  text%%=%-5s vendors=%-22s spa=%-2d forms=%d"
              % (i, len(rows), r["place_name"][:34], str(st),
                 rec["bytes"], rec["text_ratio"],
                 ",".join(rec["vendors"])[:22] or "-",
                 len(rec["spa_markers"]), len(rec["forms"])))

    json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1)
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
