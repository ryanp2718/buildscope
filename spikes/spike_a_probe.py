# -*- coding: utf-8 -*-
"""Spike A, step 2: locate each sampled jurisdiction's official site and
fingerprint its permitting platform.

Two stages, cheapest first:
  1. DNS-resolve a list of candidate hostnames per jurisdiction. Resolution is
     free and fast, so it filters ~90% of candidates before any HTTP.
  2. GET the survivors, save the HTML, fingerprint the permit-portal vendor from
     known signatures, and harvest candidate permit links for the next stage.

Politeness: one request at a time, 1s between requests to the same host, a
descriptive User-Agent, robots.txt fetched and recorded for every host touched.
These are small government servers.

Writes data/spike_a/probe.json and data/spike_a/html/*.html.
"""
import csv
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits.crawler_identity import user_agent   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "data", "spike_a", "sample.csv")
OUTDIR = os.path.join(ROOT, "data", "spike_a")
HTMLDIR = os.path.join(OUTDIR, "html")
OUT = os.path.join(OUTDIR, "probe.json")

TIMEOUT = 20
PAUSE = 1.0

# Permit-portal platform signatures. Key = vendor, value = substrings that
# appear in page HTML or in a portal URL.
VENDORS = {
    "Accela":         ["accela", "citizen access", "aca-prod", "/CAP/", "velocityhall"],
    "Tyler EnerGov":  ["energov", "tylerhost.net", "selfservice", "tyler technologies"],
    "Tyler Munis":    ["munis", "tylerapp"],
    "CentralSquare":  ["centralsquare", "click2gov", "communitydevelopment/"],
    "eTRAKiT":        ["etrakit"],
    "CityView":       ["cityviewportal", "cityview", "municipalsoftware"],
    "OpenGov/ViewPoint": ["viewpointcloud", "opengov.com", "cloud.viewpoint"],
    "Citizenserve":   ["citizenserve"],
    "CivicPlus":      ["civicplus", "civicengage", "civicclerk"],
    "MyGov":          ["mygov.us", "mygovhub"],
    "SmartGov":       ["smartgovcommunity"],
    "Municity":       ["municity"],
    "GovPilot":       ["govpilot"],
    "OpenCounter":    ["opencounter"],
    "Camino":         ["camino.ai", "gocamino"],
    "Socrata":        ["socrata", "/resource/", "opendata.socrata"],
    "ArcGIS":         ["arcgis.com", "featureserver", "hub.arcgis", "/rest/services"],
    "CKAN":           ["ckan", "/dataset/"],
    "Granicus":       ["granicus"],
    "Laserfiche":     ["laserfiche", "weblink"],
    "BS&A":           ["bsaonline", "bs&a software"],
    "Cloudpermit":    ["cloudpermit"],
    "PermitTrax":     ["permittrax"],
}

PERMIT_HINT = re.compile(
    r"(building|permit|inspection|code[\s-]?enforcement|planning|"
    r"development\s+services|community\s+development|land\s+use|zoning)", re.I)

SUFFIX = re.compile(
    r"\s+(unincorporated|township|town|village|city|borough|charter\s+township|"
    r"plantation|gore|grant|purchase|urban\s+county|consolidated\s+government)$", re.I)


def slugs(place, st):
    """Candidate hostname stems for a place name."""
    name = place
    for _ in range(3):                       # 'X County Unincorporated' -> 'X'
        name = SUFFIX.sub("", name).strip()
    bare = re.sub(r"[^a-z0-9]", "", name.lower())
    nocounty = re.sub(r"county$", "", bare)
    out = []

    def add(h):
        if h not in out:
            out.append(h)

    is_county = bool(re.search(r"count(y|ies)|parish", name, re.I))
    if is_county:
        for stem in (bare, nocounty):
            if not stem:
                continue
            add("www.%s.gov" % stem)
            add("www.%s%s.gov" % (stem, st.lower()))
            add("www.%scounty%s.gov" % (nocounty, st.lower()))
            add("www.%s.org" % stem)
            add("www.co.%s.%s.us" % (nocounty, st.lower()))
    else:
        add("www.%s.gov" % bare)
        add("www.%s%s.gov" % (bare, st.lower()))
        add("www.cityof%s.gov" % bare)
        add("www.cityof%s.com" % bare)
        add("www.cityof%s.org" % bare)
        add("www.townof%s.org" % bare)
        add("www.townof%s.com" % bare)
        add("www.villageof%s.org" % bare)
        add("www.%s.org" % bare)
        add("www.%s.com" % bare)
        add("www.ci.%s.%s.us" % (bare, st.lower()))
        add("www.%s%s.us" % (bare, st.lower()))
    return [h for h in out if len(h) > 10]


def resolves(host):
    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False
    except Exception:
        return False


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": user_agent(),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE       # many municipal sites have chain issues
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            raw = r.read(600000)
            return r.status, r.geturl(), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception as e:
        return None, url, "ERR:%s" % type(e).__name__


def fingerprint(text, url=""):
    hay = (text + " " + url).lower()
    return sorted({v for v, sigs in VENDORS.items() if any(s.lower() in hay for s in sigs)})


def permit_links(html, base):
    out = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         html, re.I | re.S):
        href, label = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", label).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if PERMIT_HINT.search(label) or PERMIT_HINT.search(href):
            out.append({"url": urllib.parse.urljoin(base, href), "label": label[:120]})
    seen, ded = set(), []
    for l in out:
        if l["url"] not in seen:
            seen.add(l["url"])
            ded.append(l)
    return ded[:25]


def title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()[:160] if m else ""


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = list(csv.DictReader(open(SAMPLE, newline="", encoding="utf-8")))
    if only:
        rows = [r for r in rows if only.lower() in r["place_name"].lower()]
    for d in (OUTDIR, HTMLDIR):
        if not os.path.isdir(d):
            os.makedirs(d)

    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT, encoding="utf-8"))

    for i, r in enumerate(rows, 1):
        key = "%s|%s" % (r["state"], r["bps_id"])
        if key in results and results[key].get("site"):
            print("[%2d/%d] %-28s cached" % (i, len(rows), r["place_name"][:28]))
            continue

        cands = slugs(r["place_name"], r["state_abbr"])
        live = [h for h in cands if resolves(h)]
        rec = {"place": r["place_name"], "state": r["state_abbr"],
               "stratum": r["stratum"], "units_12mo": r["units_12mo"],
               "candidates": cands, "resolved": live, "site": None,
               "title": "", "vendors": [], "permit_links": [], "robots": ""}
        print("[%2d/%d] %-28s %-3s  %d/%d hosts resolve"
              % (i, len(rows), r["place_name"][:28], r["state_abbr"],
                 len(live), len(cands)))

        for host in live[:4]:
            url = "https://%s/" % host
            st, final, html = fetch(url)
            time.sleep(PAUSE)
            if st == 200 and len(html) > 500:
                rec["site"] = final
                rec["title"] = title(html)
                rec["vendors"] = fingerprint(html, final)
                rec["permit_links"] = permit_links(html, final)
                fn = re.sub(r"[^a-z0-9]+", "_", (r["state_abbr"] + "_" +
                                                 r["place_name"]).lower())
                path = os.path.join(HTMLDIR, fn + "_home.html")
                open(path, "w", encoding="utf-8").write(html)
                rst, _, rtxt = fetch("https://%s/robots.txt" % host)
                time.sleep(PAUSE)
                rec["robots"] = rtxt[:1500] if rst == 200 else "(%s)" % rst
                print("        -> %s | %s | vendors=%s | %d permit links"
                      % (final, rec["title"][:50], rec["vendors"] or "-",
                         len(rec["permit_links"])))
                break
            else:
                print("        x  %s (%s)" % (url, st))

        if not rec["site"]:
            print("        !! no official site found by pattern")
        results[key] = rec
        json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1)

    found = sum(1 for v in results.values() if v.get("site"))
    print("\n%d/%d located by URL pattern; %s" % (found, len(results), OUT))


if __name__ == "__main__":
    main()
