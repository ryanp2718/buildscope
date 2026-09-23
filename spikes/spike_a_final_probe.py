# -*- coding: utf-8 -*-
"""Spike A, step 6: settle the remaining bucket-3-versus-4 questions by actually
submitting the broadest query each portal accepts.

Covers the portals the earlier steps located but did not resolve: CityView
(Madison County AL), iWorQ (St. Albans VT), the custom WATS application
(St. Johns County FL), and the address-keyed search at St. Louis MO.

Writes data/spike_a/final_probe.json.
"""
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
OUTDIR = os.path.join(ROOT, "data", "spike_a")
HTMLDIR = os.path.join(OUTDIR, "html")
OUT = os.path.join(OUTDIR, "final_probe.json")

PAUSE = 1.5
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
JAR = {}

CANDIDATE_PATHS = {
    "cityview": [
        "/Portal/PublicInformation", "/Portal/Search", "/Portal/AdHocSearch",
        "/Portal/PropertySearch", "/Portal/PublicInfo/Search",
        "/Portal/Home/Search", "/Portal/Permits/Search",
    ],
    "iworq": ["", "/search", "/permits"],
}


def req(url, data=None, referer=None):
    h = {"User-Agent": user_agent(), "Accept": "text/html,*/*;q=0.8"}
    if referer:
        h["Referer"] = referer
    host = urllib.parse.urlparse(url).netloc
    if JAR.get(host):
        h["Cookie"] = JAR[host]
    if data is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(data).encode()
    r = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=35, context=ctx) as resp:
            sc = resp.headers.get_all("Set-Cookie") or []
            if sc:
                JAR[host] = "; ".join(c.split(";")[0] for c in sc)
            return resp.status, resp.geturl(), resp.read(1200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception as e:
        return None, url, "ERR:%s" % type(e).__name__


def hidden(html):
    out = {}
    for m in re.finditer(r'(?is)<input[^>]*type=["\']hidden["\'][^>]*>', html):
        t = m.group(0)
        n = re.search(r'name=["\']([^"\']+)["\']', t)
        v = re.search(r'value=["\']([^"\']*)["\']', t)
        if n:
            out[n.group(1)] = v.group(1) if v else ""
    return out


def rows(html):
    best = 0
    for t in re.findall(r"(?is)<table.*?</table>", html):
        best = max(best, len(re.findall(r"(?i)<tr[\s>]", t)))
    return best


def save(html, name):
    open(os.path.join(HTMLDIR, name), "w", encoding="utf-8").write(html)


def main():
    res = {}

    # ---- Madison County AL: hunt for a reachable CityView search endpoint
    print("Madison County AL - CityView path hunt")
    base = "https://cityview.madisoncountyal.gov"
    hits = []
    for p in CANDIDATE_PATHS["cityview"]:
        st, final, html = req(base + p)
        time.sleep(PAUSE)
        print("   %-34s %s  %s b" % (p, st, len(html or "")))
        if st == 200 and len(html or "") > 2000:
            hits.append({"path": p, "bytes": len(html), "rows": rows(html),
                         "has_form": "<form" in html.lower()})
            save(html, "final_madisonco_%s.html" % re.sub(r"\W+", "_", p))
    res["01|447000"] = {"vendor": "CityView", "reachable_paths": hits}

    # ---- St. Albans VT: iWorQ portal
    print("\nSt. Albans VT - iWorQ portal")
    u = "https://stalbans_permit.portal.iworq.net/portalhome/stalbans_permit"
    st, final, html = req(u)
    time.sleep(PAUSE)
    print("   home %s %s b" % (st, len(html or "")))
    rec = {"vendor": "iWorQ", "url": u, "status": st, "bytes": len(html or "")}
    if st == 200:
        save(html, "final_stalbans_iworq.html")
        text = re.sub(r"\s+", " ", re.sub(r"(?is)<script.*?</script>|<[^>]+>", " ", html))
        rec["searchy"] = sorted({m.lower() for m in re.findall(
            r"(?i)(search[^.<]{0,28}permit|permit[^.<]{0,18}search|"
            r"look ?up|public (?:records|search))", text)})[:6]
        rec["links"] = sorted({t.strip()[:50] for _, t in re.findall(
            r'(?i)<a[^>]*href="([^"]+)"[^>]*>([^<]{2,50})</a>', html)})[:18]
        print("   searchy:", rec["searchy"])
        print("   links  :", rec["links"][:10])
    res["50|631000"] = rec

    # ---- St. Johns County FL: submit the WATS search with no criteria
    print("\nSt. Johns County FL - WATS empty search")
    u = "https://webapp.sjcfl.us/watswebx/permit/SearchPermit.aspx"
    st, final, html = req(u)
    time.sleep(PAUSE)
    rec = {"vendor": "custom (WATS)", "url": u, "form_status": st}
    if st == 200:
        h = hidden(html)
        names = [n for n in re.findall(
            r'(?is)<(?:input|select)\b[^>]*name=["\']([^"\']+)["\']', html)
            if not n.startswith("__")]
        rec["fields"] = sorted(set(names))[:16]
        btn = re.search(r'name=["\']([^"\']*(?:btnSearch|Search)[^"\']*)["\'][^>]*type=["\']submit',
                        html, re.I) or \
            re.search(r'type=["\']submit["\'][^>]*name=["\']([^"\']+)["\']', html, re.I)
        data = dict(h)
        if btn:
            data[btn.group(1)] = "Search"
        st2, _, html2 = req(u, data=data, referer=u)
        time.sleep(PAUSE)
        rec["post_status"] = st2
        if st2 == 200:
            save(html2, "final_stjohns_empty.html")
            rec["rows"] = rows(html2)
            rec["bytes"] = len(html2)
            msg = re.search(r"(?i)(no records?[^<]{0,50}|please (?:enter|select)[^<]{0,60}|"
                            r"[\d,]+\s*(?:records?|permits?)\s*found)", html2)
            rec["message"] = msg.group(0)[:80] if msg else None
            print("   POST %s  rows=%s  msg=%s" % (st2, rec["rows"], rec["message"]))
    res["12|633000"] = rec

    # ---- St. Louis MO: is the permit search address-required?
    print("\nSt. Louis MO - address-keyed search")
    u = ("https://www.stlouis-mo.gov/government/departments/public-safety/building/"
         "permits/search-building-permits-by-address.cfm")
    st, final, html = req(u)
    time.sleep(PAUSE)
    rec = {"url": u, "status": st}
    if st == 200:
        save(html, "final_stlouis_form.html")
        rec["forms"] = re.findall(r'(?is)<form[^>]*action=["\']([^"\']*)["\']', html)[:5]
        rec["inputs"] = sorted(set(re.findall(
            r'(?is)<input[^>]*name=["\']([^"\']+)["\']', html)))[:14]
        rec["required_hint"] = bool(re.search(r"(?i)enter a (?:street|address|house)", html))
        print("   forms:", rec["forms"])
        print("   inputs:", rec["inputs"][:10], "| address required:", rec["required_hint"])
    res["29|565000"] = rec

    json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1)
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
