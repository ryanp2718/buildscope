# -*- coding: utf-8 -*-
"""Measurement A: fetch T-SEARCH / T-INDEX / T-DETAIL from the bucket-3 portals.

Spike A never fetched an individual permit record, so Spike C's 1.00 collision
ratio rests on municipal home pages and portal landing pages - a proxy for the
D8 claim rather than the claim itself. This fetches the two page types an
extractor actually sees.

Per tenancy, in one session, four requests:
    GET  Cap/CapHome.aspx              -> T-SEARCH
    POST the general search form       -> T-INDEX
    GET  two Cap/CapDetail.aspx links  -> T-DETAIL x2

The search form shape is per-tenancy - Yakima renders an address-shaped form
with no date fields at all, where Clark County and Oregon accept empty
criteria - so the criteria come from the tenancy table below rather than from
an assumption about Accela.

Decision rules: docs/evidence/2026-09-20-measurement-ab-preregistration.md,
fixed before this ran. This script decides nothing.
"""
import re
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

PFX = "ctl00$PlaceHolderMain$generalSearchForm$"
TARGET = "ctl00$PlaceHolderMain$btnNewSearch"

# jurisdiction key -> (label, base, vendor, criteria)
TENANCIES = [
    ("clarkco", "Clark County NV",
     "https://aca-prod.accela.com/clarkco",
     "accela-aca", {}),
    ("oregon", "Oregon statewide",
     "https://aca-oregon.accela.com/oregon",
     "accela-aca", {}),
    ("YAKIMACO", "Yakima County WA",
     "https://aca-prod.accela.com/YAKIMACO",
     "accela-aca", {"txtGSCity": "WAPATO"}),
]

HOME = "%s/Cap/CapHome.aspx?module=Building&TabName=Building"
HIDDEN = re.compile(
    r'<input[^>]+type="hidden"[^>]*name="(__[A-Z]+[A-Za-z]*)"[^>]*value="([^"]*)"',
    re.I)
HIDDEN2 = re.compile(
    r'<input[^>]+name="(__[A-Z]+[A-Za-z]*)"[^>]+value="([^"]*)"[^>]*type="hidden"',
    re.I)
DETAIL = re.compile(r'CapDetail\.aspx\?([^"\'>]*capID1=[^"\'>]*)', re.I)


def hidden_fields(html):
    d = {}
    for pat in (HIDDEN, HIDDEN2):
        for k, v in pat.findall(html):
            d.setdefault(k, _unesc(v))
    return d


def _unesc(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))


def detail_urls(html, base, limit=2):
    """Distinct records, preferring distinct agencyCode.

    The Oregon statewide tenancy returns rows belonging to several different
    agencies (YAMHILL_CO, OAKRIDGE, ...). Two records from *different*
    agencies inside one tenancy is a sharper test of cohort structure than two
    records from the same one, so prefer those when they exist.
    """
    seen, out, agencies = set(), [], set()
    raw = [_unesc(q) for q in DETAIL.findall(html)]
    scored = []
    for q in raw:
        p = urllib.parse.parse_qs(q)
        cid = (p.get("capID1", [""])[0], p.get("capID2", [""])[0],
               p.get("capID3", [""])[0])
        if cid in seen or not cid[0]:
            continue
        seen.add(cid)
        scored.append((p.get("agencyCode", [""])[0], q, cid))
    # first pass: one per distinct agency
    for ag, q, cid in scored:
        if ag not in agencies:
            agencies.add(ag)
            out.append((base + "/Cap/CapDetail.aspx?" + q, ag, cid))
        if len(out) >= limit:
            return out
    # second pass: fill from whatever remains
    for ag, q, cid in scored:
        u = base + "/Cap/CapDetail.aspx?" + q
        if u not in [o[0] for o in out]:
            out.append((u, ag, cid))
        if len(out) >= limit:
            break
    return out


def run_tenancy(key, label, base, vendor, criteria):
    print("\n%s  (%s)" % (label, key))
    op = mf._opener()
    home = HOME % base

    html, _ = mf.fetch(op, home, "%s_search" % key, key, vendor, "T-SEARCH")
    if html is None:
        return
    hid = hidden_fields(html)
    if "__VIEWSTATE" not in hid:
        print("  SKIP: no __VIEWSTATE on the rendered form")
        return

    body = dict(hid)
    body["__EVENTTARGET"] = TARGET
    body["__EVENTARGUMENT"] = ""
    for k, v in criteria.items():
        body[PFX + k] = v
    data = urllib.parse.urlencode(body).encode("utf-8")

    origin = "://".join(urllib.parse.urlsplit(home)[:2])
    idx, row = mf.fetch(op, home, "%s_index" % key, key, vendor, "T-INDEX",
                        data=data,
                        headers={"Referer": home, "Origin": origin})
    if idx is None or row["verdict"] != "ok":
        print("  SKIP details: index verdict is %r"
              % (row["verdict"] if row else "none"))
        return

    urls = detail_urls(idx, base, limit=2)
    if not urls:
        print("  SKIP details: no CapDetail links in the result page")
        return
    for i, (u, ag, cid) in enumerate(urls, 1):
        mf.fetch(op, u, "%s_detail%d_%s" % (key, i, ag or "na"),
                 key, vendor, "T-DETAIL", headers={"Referer": home})


def main():
    mf.ensure_dirs()
    print("MEASUREMENT A - index and detail pages from the bucket-3 portals")
    print("budget ceiling %d requests; pre-registration governs all rules"
          % mf.BUDGET)
    for t in TENANCIES:
        run_tenancy(*t)
    print("\nrequests spent: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
