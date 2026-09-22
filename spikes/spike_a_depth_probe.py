# -*- coding: utf-8 -*-
"""Spike A, step 5: follow each jurisdiction's building/permits page one level
deeper, looking for a searchable index rather than a PDF application form.

The distinction this settles is bucket 6 ('no online portal') versus buckets
2-5 ('a portal exists, of some kind'). A department page offering only a PDF to
print and mail is bucket 6 for our purposes: there is nothing to enumerate.

Records, per page: outbound links to known permit-portal vendors, counts of PDF
form links, and any text offering to search or look up permits.

Writes data/spike_a/depth_probe.json.
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
from permits.identity import user_agent   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "data", "spike_a")
HTMLDIR = os.path.join(OUTDIR, "html")
OUT = os.path.join(OUTDIR, "depth_probe.json")

PAUSE = 1.5

# place key -> pages to look at one level down
TARGETS = {
    "01|447000": ["https://cityview.madisoncountyal.gov/Portal",
                  "https://cityview.madisoncountyal.gov/Portal/PublicInformation/Search"],
    "22|433000": ["http://etrakit.lafayettela.gov/Etrakit2/Index.aspx",
                  "http://etrakit.lafayettela.gov/Etrakit2/Search/permit.aspx"],
    "13|720000": ["https://www.sagesgov.com/southfulton-ga",
                  "https://www.cityofsouthfultonga.gov/2887/Submit-an-Online-Permit-Application"],
    "08|029830": ["https://www.townofgardencity.com/building-permits"],
    "05|035290": ["https://jonesboro-ar-us.avolvecloud.com/"],
    "45|127000": ["https://caycesc.gov/building-services.php"],
    "49|048230": ["https://www.mapleton.org/departments/community_development/building/index.php"],
    "50|631000": ["https://www.stalbansvt.gov/departments/zoning/zoning.php"],
    "55|660000": ["https://townofahnapee.org/licenses-and-permits/"],
    "26|215370": ["https://chikaming.com/"],
    "34|325300": ["https://www.gallowaytwp-nj.gov/", "https://www.galloway.com/"],
    "42|857000": ["https://ontelauneetwp.net/resident-resources/building-zoning/"],
    "53|764000": ["https://wapato-city.org/business/licenses_and_permits.php"],
    "31|061000": ["https://www.brownvillenebraska.gov/residentresources"],
    "27|283000": ["https://hawley.govoffice.com/cityinfo"],
    "48|048768": ["https://missiontexas.us/210/Inspections-Division"],
    "19|763000": ["https://www.storycountyiowa.gov/425/Applications-and-Permits"],
    "18|076894": ["https://brazil.in.gov/"],
    "21|087000": ["https://www.bgky.org/ncs/building/permits"],
    "29|565000": ["https://www.stlouis-mo.gov/government/departments/public-safety/"
                  "building/permits/index.cfm"],
}

VENDOR_HOST = re.compile(
    r"(accela|etrakit|cityview|energov|tylerhost|citizenserve|viewpointcloud|"
    r"opengov\.com|sagesgov|communitycore|smartgovcommunity|mygov\.us|bsaonline|"
    r"cloudpermit|avolvecloud|permittrax|municity|govpilot|socrata|arcgis\.com|"
    r"click2gov|centralsquare|kraftcodeservices|camino|opencounter)", re.I)

SEARCHY = re.compile(
    r"(search (?:for )?(?:a )?permits?|permit (?:search|lookup|status|records)|"
    r"look ?up (?:a )?permits?|view (?:issued )?permits?|permit portal|"
    r"online permit|apply online|track your permit|inspection results)", re.I)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(url):
    r = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    try:
        with urllib.request.urlopen(r, timeout=30, context=ctx) as resp:
            return resp.status, resp.geturl(), resp.read(800000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception as e:
        return None, url, "ERR:%s" % type(e).__name__


def main():
    res = {}
    for key, urls in TARGETS.items():
        rec = {"pages": []}
        for u in urls:
            st, final, html = fetch(u)
            time.sleep(PAUSE)
            page = {"url": u, "status": st, "bytes": len(html or "")}
            if st == 200 and html:
                hosts = sorted({h.lower() for h in VENDOR_HOST.findall(html)})
                text = re.sub(r"\s+", " ", re.sub(r"(?is)<script.*?</script>|<[^>]+>", " ", html))
                page["vendor_hosts"] = hosts
                page["searchy_phrases"] = sorted({m.group(0).lower()
                                                  for m in SEARCHY.finditer(text)})[:6]
                page["pdf_links"] = len(re.findall(r'(?i)href="[^"]+\.pdf"', html))
                page["ext_portal_links"] = sorted({
                    urllib.parse.urljoin(final, m)
                    for m in re.findall(r'(?i)href="([^"]+)"', html)
                    if VENDOR_HOST.search(m)})[:6]
                fn = "depth_" + re.sub(r"[^a-z0-9]+", "_", key + "_" + u)[:80] + ".html"
                open(os.path.join(HTMLDIR, fn), "w", encoding="utf-8").write(html)
            rec["pages"].append(page)
            print("%-12s %-62s %-5s pdf=%-3s vend=%s"
                  % (key, u[:62], str(st), page.get("pdf_links", "-"),
                     ",".join(page.get("vendor_hosts", []))[:34] or "-"))
            if page.get("searchy_phrases"):
                print("             phrases: %s" % "; ".join(page["searchy_phrases"])[:100])
        res[key] = rec
    json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1)
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
