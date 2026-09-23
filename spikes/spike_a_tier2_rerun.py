# -*- coding: utf-8 -*-
"""Spike A tier-2 rerun: classify at the level that actually ISSUES the permit.

The first Spike A pass looked for a portal at the BPS *place* level. For tier-2
places the issuing function often sits elsewhere - the county, the parent town,
or a contracted private code-enforcement firm - so a place-level miss was
recorded as bucket 6. That biases the deciding figure downward.

This script re-probes each tier-2 row at its researched issuing authority.
Issuing authority was established by hand (web research, 2026-09-20); the
citation for each is in ISSUER[...]['basis'].
"""
import io
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits.crawler_identity import user_agent   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "spike_a")
HTML = os.path.join(OUT, "html_tier2")
PAUSE = 1.5
TIMEOUT = 25

VENDOR = {
    "accela": "Accela ACA", "energov": "Tyler EnerGov",
    "civicgov": "CivicGov", "cityview": "CityView", "etrakit": "eTRAKiT",
    "sagesgov": "SagesGov", "communitycore": "CommunityCore", "iworq": "iWorQ",
    "avolvecloud": "Avolve ProjectDox", "projectdox": "Avolve ProjectDox",
    "civicplus": "CivicPlus", "revize": "Revize", "govoffice": "GovOffice",
    "click2gov": "CentralSquare Click2Gov", "opengov": "OpenGov",
    "mygovernmentonline": "MyGovernmentOnline", "citizenserve": "Citizenserve",
    "smartgov": "SmartGov", "permittrax": "PermitTrax",
    "laserfiche": "Laserfiche", "municity": "MuniCity", "buildingeye": "BuildingEye",
}
PORTAL_HINT = ("permit search", "search permits", "permit lookup", "permit status",
               "online permit", "apply online", "citizen portal", "permit portal",
               "search for a permit", "record search")

# key -> researched issuing authority for that BPS place
ISSUER = {
    ("53", "573000"): {
        "place": "Wapato, WA", "issuer": "City of Wapato",
        "level": "place", "basis": "Incorporated city; wapato-city.org carries its own "
        "licenses/permits page. Yakima County Building and Fire Safety covers the "
        "UNINCORPORATED county only.",
        "urls": ["https://wapato-city.org/business/licenses_and_permits.php",
              "https://wapato-city.org/departments/city_hall.php",
              "https://www.yakimacounty.us/1181/Building"]},
    ("55", "007500"): {
        "place": "Ahnapee town, WI", "issuer": "Kewaunee County / town zoning administrator",
        "level": "county+contract", "basis": "Town has a named zoning administrator "
        "(an individual). Kewaunee County Land and Water Conservation issues zoning "
        "and sanitary permits. WI UDC 1-2 family permits run through a certified "
        "inspection agency.",
        "urls": ["https://townofahnapee.org/",
              "https://www.kewauneeco.org/departments/land-water-conservation/zoning/forms_and_documents/",
              "https://www.kewauneeco.org/"]},
    ("31", "064000"): {
        "place": "Brownville village, NE", "issuer": "Village of Brownville",
        "level": "place", "basis": "Village Hall issues. Nemaha County has no building "
        "department; Nebraska counties are not required to adopt building codes.",
        "urls": ["https://nemahacountyne.gov/"]},
    ("02", "329000"): {
        "place": "Kotzebue, AK", "issuer": "City of Kotzebue",
        "level": "place", "basis": "Northwest Arctic Borough Title 9 land use permits "
        "EXPLICITLY EXCLUDE the City of Kotzebue, so the borough is not an "
        "alternative issuing level here.",
        "urls": ["https://www.nwabor.org/departments/planning/title-9-permits/"]},
    ("08", "251000"): {
        "place": "Garden City town, CO", "issuer": "Town of Garden City",
        "level": "place", "basis": "Town Hall issues its own. Weld County Building "
        "serves the unincorporated county.",
        "urls": ["https://www.townofgardencity.com/building-permits",
              "https://www.weld.gov/Live-Work/Property/Permits-Records"]},
    ("23", "139000"): {
        "place": "Eastbrook town, ME", "issuer": "Town of Eastbrook (likely none)",
        "level": "none", "basis": "Pop 416. MUBEC adoption/enforcement is mandatory only "
        "at 4,000+; roughly 370 of Maine's 488 municipalities are under that and "
        "are not required to enforce codes or issue building permits at all.",
        "urls": ["https://www.maine.gov/dps/fmo/building-codes"]},
    ("06", "009000"): {
        "place": "Amador City, CA", "issuer": "Amador City, inspection contracted to WGA Inc",
        "level": "place+contract", "basis": "Amador City is incorporated and runs its own "
        "building office 9 hrs/week; the inspector's address is l.white@wgainc.net, "
        "a private firm. Amador County's portal serves the UNINCORPORATED county, "
        "so it does not cover Amador City.",
        "urls": ["https://www.amadorcounty.gov/departments/building",
              "https://wgainc.net/"]},
    ("36", "203500"): {
        "place": "Dresden village, NY", "issuer": "Town of Torrey code enforcement",
        "level": "parent_town", "basis": "Village of Dresden sits in the Town of Torrey; "
        "the Town Code Enforcement Officer issues building permits for it. This is "
        "a genuine level shift from the first pass.",
        "urls": ["https://www.townoftorrey.org/building-planning-zoning.php",
              "https://www.yatescountyny.gov/489/Towns-Villages-Resource-Directory"]},
}


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": user_agent(), "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        r = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
        return r.getcode(), r.geturl(), r.read(2000000)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(2000000)
        except Exception:
            body = b""
        return e.code, url, body
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
        return None, url, ("ERR:%s" % e).encode()


def main():
    if not os.path.isdir(HTML):
        os.makedirs(HTML)
    results = []
    for (st, bid), spec in sorted(ISSUER.items()):
        rec = {"state": st, "bps_id": bid, "place": spec["place"], "issuer": spec["issuer"],
                   "level": spec["level"], "basis": spec["basis"], "probes": []}
        print("\n=== %s  ->  %s [%s]" % (spec["place"], spec["issuer"], spec["level"]))
        for u in spec["urls"]:
            code, final, body = fetch(u)
            low = body.lower()
            vend = sorted({v for k, v in VENDOR.items() if k.encode() in low})
            hints = sorted({h for h in PORTAL_HINT if h.encode() in low})
            npdf = low.count(b".pdf")
            err = body[:4] == b"ERR:"
            name = "%s_%s_%d.html" % (st, bid, abs(hash(u)) % 10 ** 8)
            if not err:
                io.open(os.path.join(HTML, name), "wb").write(body)
            rec["probes"].append({
                "url": u, "code": code, "final": final, "bytes": len(body), "vendors": vend,
                "portal_hints": hints, "pdf_links": npdf, "saved": None if err else name})
            print("  %-4s %7d b  vend=%-26s hints=%-2d pdf=%-3d  %s"
                  % (code, len(body), ",".join(vend) or "-", len(hints), npdf, u[:58]))
            if err:
                print("       %s" % body[:120].decode("utf-8", "replace"))
            time.sleep(PAUSE)
        results.append(rec)
    with io.open(os.path.join(OUT, "tier2_rerun.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(results, indent=1))
    print("\nwrote data/spike_a/tier2_rerun.json  (%d places, html_tier2/)" % len(results))


if __name__ == "__main__":
    main()
