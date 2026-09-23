# -*- coding: utf-8 -*-
"""Spike A, step 4: the bucket-3 test.

'Bucket 3 is the one people miss. Many nominally search-only portals accept an
empty criteria set or a broad date range. Test this deliberately on every
bucket-4 candidate before classifying it as 4.' (DESIGN.md, Spike A)

So: submit the broadest query each portal will accept and see whether it returns
a result set or demands a specific identifier. Also look for the result cap,
because a capped index is not enumerable without partitioning queries until each
partition falls under the cap.

Accela ACA is ASP.NET WebForms, so a search is a POST carrying __VIEWSTATE and
__EVENTVALIDATION harvested from a prior GET. That is implemented properly here
because Accela is the dominant vendor in the sample and guessing its behaviour
would be the weakest link in the whole spike.

One request at a time, 2s apart, single date-range query per portal. This is a
handful of requests against each host, not a crawl.

Writes data/spike_a/query_probe.json.
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
OUT = os.path.join(OUTDIR, "query_probe.json")

TIMEOUT = 45
PAUSE = 2.0

CAP = re.compile(
    r"(exceed\w*\s+(?:the\s+)?(?:maximum|limit)|too many (?:results|records)|"
    r"only the first|narrow your search|refine your search|maximum of\s*[\d,]+|"
    r"more than\s*[\d,]+\s*(?:results|records)|first\s*[\d,]+\s*(?:results|records))",
    re.I)
NORESULT = re.compile(
    r"(no records? (?:were )?found|no results|0 records|did not return any|"
    r"enter (?:at least|a) |required field|please enter)", re.I)
ROWCOUNT = re.compile(r"([\d,]+)\s*(?:records?|results?|permits?)\s*(?:found|returned|match)", re.I)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
JAR = {}


def req(url, data=None, referer=None):
    headers = {"User-Agent": user_agent(),
               "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    host = urllib.parse.urlparse(url).netloc
    if JAR.get(host):
        headers["Cookie"] = JAR[host]
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(data).encode()
    r = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=TIMEOUT, context=ctx) as resp:
            sc = resp.headers.get_all("Set-Cookie") or []
            if sc:
                JAR[host] = "; ".join(c.split(";")[0] for c in sc)
            return resp.status, resp.geturl(), resp.read(1500000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, url, e.read(400000).decode("utf-8", "replace")
        except Exception:
            return e.code, url, ""
    except Exception as e:
        return None, url, "ERR:%s: %s" % (type(e).__name__, e)


def hidden(html):
    out = {}
    for m in re.finditer(
            r'(?is)<input[^>]*type=["\']hidden["\'][^>]*>', html):
        tag = m.group(0)
        n = re.search(r'name=["\']([^"\']+)["\']', tag)
        v = re.search(r'value=["\']([^"\']*)["\']', tag)
        if n:
            out[n.group(1)] = v.group(1) if v else ""
    return out


def rows(html):
    """Count plausible result rows in the biggest table on the page."""
    best = 0
    for t in re.findall(r"(?is)<table.*?</table>", html):
        n = len(re.findall(r"(?i)<tr[\s>]", t))
        best = max(best, n)
    return best


# A result list that is actually RENDERED. This is the reliable positive
# signal; absence-of-results phrasing is not, see strip_scripts below.
RESULTLIST = re.compile(
    r"(divSearchResultList|record results|showing\s*\d+\s*-\s*\d+|"
    r"результ|GridView\w*ResultList)", re.I)


def strip_scripts(html):
    """Drop <script>/<style> before looking for human-facing messages.

    Accela ships 'Please enter a key word with more than 2 characters.' as a
    JS constant on every page, including pages that returned 100+ records.
    Matching NORESULT against raw HTML therefore reports 'no results' on
    successful searches - a false negative that nearly inverted the headline
    Accela finding, and did produce a wrong call on Yakima in the tier-2 rerun.
    """
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    return re.sub(r"(?is)<style.*?</style>", " ", html)


def diag(html, label, save=None):
    if save:
        open(os.path.join(HTMLDIR, save), "w", encoding="utf-8").write(html)
    markup = strip_scripts(html)
    cap = CAP.search(markup)
    nores = NORESULT.search(markup)
    rc = ROWCOUNT.search(markup)
    has_list = RESULTLIST.search(markup)
    d = {"bytes": len(html),
         "cap_message": cap.group(0)[:90] if cap else None,
         "no_result_message": nores.group(0)[:60] if nores else None,
         "result_list_rendered": bool(has_list),
         "stated_count": rc.group(1) if rc else None,
         "table_rows": rows(html)}
    # A rendered result list beats any 'please enter...' phrasing.
    if has_list:
        d["no_result_message"] = None
    print("    %-26s rows=%-4d count=%-8s cap=%-28s norec=%s"
          % (label, d["table_rows"], d["stated_count"] or "-",
             (d["cap_message"] or "-")[:28], (d["no_result_message"] or "-")[:22]))
    return d


def accela(base, agency, module="Building", label=""):
    """Accela ACA general search over a broad date range."""
    home = "%s/%s/Cap/CapHome.aspx?module=%s&TabName=%s" % (base, agency, module, module)
    st, final, html = req(home)
    time.sleep(PAUSE)
    if st != 200:
        return {"error": "home %s" % st, "home": home}
    out = {"home": home, "home_status": st, "home_bytes": len(html)}

    h = hidden(html)
    out["has_viewstate"] = "__VIEWSTATE" in h
    # Find the general-search date fields Accela renders (names vary by version).
    # Accela names the general-search date range txtGSStartDate / txtGSEndDate,
    # and the submit is an <a> firing __doPostBack on btnNewSearch, not an
    # <input type=submit>.
    fields = re.findall(r'name=["\']([^"\']*(?:txtGS|ddlGS)[^"\']*)["\']', html)
    fields = [f for f in fields if "ClientState" not in f and "watermark" not in f]
    out["search_fields"] = sorted(set(fields))[:16]

    dfrom = next((f for f in fields if f.endswith("txtGSStartDate")), None)
    dto = next((f for f in fields if f.endswith("txtGSEndDate")), None)
    target = "ctl00$PlaceHolderMain$btnNewSearch"
    frm = None
    if not (h.get("__VIEWSTATE") and dfrom and dto):
        out["probe"] = "could not locate date-range fields on the rendered form"
        return out

    # Two probes, in order of how much they would establish:
    #   1. date range ONLY - if this returns rows, the portal is bucket 3
    #   2. entirely empty criteria - the strongest form of the same question
    for tag, extra in (("date-range only", {dfrom: "01/01/2025", dto: "01/31/2025"}),
                       ("empty criteria", {})):
        data = dict(h)
        data.update(extra)
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
        st2, _, html2 = req(home, data=data, referer=home)
        time.sleep(PAUSE)
        key = tag.replace(" ", "_").replace("-", "_")
        out[key + "_status"] = st2
        if st2 == 200:
            out[key] = diag(html2, "%s %s" % (label, tag),
                            save="q_%s_accela_%s.html" % (agency, key))
        else:
            print("    %-26s HTTP %s" % (label + " " + tag, st2))
    return out


def simple_get(url, label, save):
    st, final, html = req(url)
    time.sleep(PAUSE)
    if st != 200:
        print("    %-26s HTTP %s" % (label, st))
        return {"url": url, "status": st}
    return {"url": url, "status": st, "final": final,
            "result": diag(html, label, save=save)}


def main():
    if not os.path.isdir(HTMLDIR):
        os.makedirs(HTMLDIR)
    res = {}

    print("Clark County NV - Accela ACA (dominant vendor in sample)")
    res["32|140000"] = accela("https://aca-prod.accela.com", "clarkco",
                              label="ClarkCo")

    print("\nMcMinnville OR - Oregon statewide Accela ePermitting")
    res["41|545000"] = accela("https://aca-oregon.accela.com", "oregon",
                              label="OregonState")

    print("\nMadison County AL - CityView public information search")
    res["01|447000"] = simple_get(
        "https://cityview.madisoncountyal.gov/Portal/Ad-Hoc-Search/Search-Permits",
        "CityView adhoc", "q_madisonco_cityview.html")

    print("\nLafayette Parish LA - eTRAKiT (retry over https)")
    res["22|433000"] = simple_get(
        "https://etrakit.lafayettela.gov/Etrakit2/Search/permit.aspx",
        "eTRAKiT permit search", "q_lafayette_etrakit.html")

    print("\nSt. Johns County FL - custom WATS permit search")
    res["12|633000"] = simple_get(
        "https://webapp.sjcfl.us/watswebx/permit/SearchPermit.aspx",
        "WATS search form", "q_stjohns_wats.html")

    print("\nSt. Louis MO - address-based permit search")
    res["29|565000"] = simple_get(
        "https://www.stlouis-mo.gov/government/departments/public-safety/building/"
        "permits/search-building-permits-by-address.cfm",
        "STL address search", "q_stlouis.html")

    print("\nBowling Green KY - city permit status application")
    res["21|087000"] = simple_get("https://www2.bgky.org/ncs/PermitsPlanReviewsInspections.php",
                                  "BG permits page", "q_bgky.html")

    json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1)
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
