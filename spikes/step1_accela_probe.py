# -*- coding: utf-8 -*-
"""Bucket-4 acquisition test: can an Accela tenancy be enumerated by date?

This is the measurement docs/design/history.md names as "the single most decision-relevant
unknown in this document". Unit-weighted reachability is 73.1% *only* if
bucket-4 portals can be enumerated by partitioned querying. If they cannot,
reachable collapses to 39.2% and the gate fires. Nothing in sections 9-10
scheduled it, so it is scheduled here, ahead of the Accela adapter, because
the answer determines what that adapter can be.

Four questions, in the order that makes later ones cheap:

  Q1  Does a date-bounded search return a STATED count, or the "100+" display
      cap Spike A saw on empty criteria? A stated count is the whole ballgame:
      it makes bisection terminating rather than hopeful.
  Q2  Does the result grid paginate past row 10, and by what postback? Spike
      A's saved pages show no pager, but they were taken on a capped result
      set, where ASP.NET GridView renders none.
  Q3  Is the "100+" a display cap or a hard result cap? If pagination walks
      past 100 rows the cap is cosmetic and partitioning is barely needed.
  Q4  The result grid carries a "Download results" button
      (`gdvPermitListtop4btnExport`). If it returns structured rows, every
      Accela agency is effectively bucket 1 and the HTML parser is optional.

Q4 is probed FIRST on a narrow range, because a positive answer makes Q2 and
the entire index parser moot, and it costs one request to find out.

Everything goes through the same D1 capture layer as Measurements A and B: no
page exists on disk without a manifest row written in the same operation.

Decides nothing about buckets. It measures mechanics and prints them.
"""
import re
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

PFX = "ctl00$PlaceHolderMain$generalSearchForm$"
GRID = "ctl00$PlaceHolderMain$dgvPermitList$gdvPermitList"
SEARCH_BTN = "ctl00$PlaceHolderMain$btnNewSearch"
EXPORT_BTN = GRID + "$gdvPermitListtop4btnExport"

HOME = "%s/Cap/CapHome.aspx?module=Building&TabName=Building"

TENANCIES = [
    ("clarkco", "Clark County NV", "https://aca-prod.accela.com/clarkco",
     "32", "021000"),
    ("oregon", "Oregon statewide", "https://aca-oregon.accela.com/oregon",
     None, None),
]

# Windows chosen to bracket the cap from both sides. Q1 needs a range that is
# plausibly under 100 records and one that is plainly over it.
WINDOWS = [("1d", "09/18/2026", "09/18/2026"),
           ("7d", "09/12/2026", "09/18/2026"),
           ("31d", "08/19/2026", "09/18/2026")]

HIDDEN = re.compile(
    r'<input[^>]+type="hidden"[^>]*name="(__[A-Z]+[A-Za-z]*)"[^>]*value="([^"]*)"',
    re.I)
HIDDEN2 = re.compile(
    r'<input[^>]+name="(__[A-Z]+[A-Za-z]*)"[^>]+value="([^"]*)"[^>]*type="hidden"',
    re.I)

SHOWING = re.compile(r"Showing\s*(\d+)\s*-\s*(\d+)\s*of\s*([\d,]+\+?)", re.I)
ROW = re.compile(r'<tr class="ACA_TabRow_(?:Odd|Even)[^"]*">', re.I)
PAGER = re.compile(r"__doPostBack\(&#39;([^&]*?)&#39;,&#39;(Page\$[^&]*?)&#39;\)")
DATEFIELD = re.compile(r'name="' + re.escape(PFX) + r'(txtGS\w*Date\w*)"', re.I)


def unesc(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))


def hidden_fields(html):
    d = {}
    for pat in (HIDDEN, HIDDEN2):
        for k, v in pat.findall(html):
            d.setdefault(k, unesc(v))
    return d


def describe(html):
    """What the server just told us about the size of the result set."""
    m = SHOWING.search(html)
    pagers = sorted(set(PAGER.findall(html)))
    return {"showing": (m.group(1), m.group(2), m.group(3)) if m else None,
            "rows": len(ROW.findall(html)),
            "pager_targets": [p[1] for p in pagers][:12],
            "pager_ctl": pagers[0][0] if pagers else None,
            "detail_links": len(re.findall(r"CapDetail\.aspx", html)),
            "bytes": len(html)}


def show(tag, d):
    s = d["showing"]
    print("     %-14s rows=%-3d showing=%-14s pager=%-22s links=%d  %dB"
          % (tag, d["rows"],
             ("%s-%s of %s" % s) if s else "none",
             ",".join(d["pager_targets"][:4]) or "none",
             d["detail_links"], d["bytes"]))


def post(op, key, home, body, name, page_type="T-INDEX"):
    origin = "://".join(urllib.parse.urlsplit(home)[:2])
    data = urllib.parse.urlencode(body).encode("utf-8")
    return mf.fetch(op, home, name, key, "accela-aca", page_type, data=data,
                    headers={"Referer": home, "Origin": origin})


def search_body(hidden, start_field, end_field, lo, hi):
    b = dict(hidden)
    b["__EVENTTARGET"] = SEARCH_BTN
    b["__EVENTARGUMENT"] = ""
    if start_field and lo:
        b[PFX + start_field] = lo
    if end_field and hi:
        b[PFX + end_field] = hi
    return b


def run(key, label, base, state, bps_id):
    print("\n%s  (%s)" % (label, key))
    op = mf._opener()
    home = HOME % base

    html, _ = mf.fetch(op, home, "acc_%s_home" % key, key, "accela-aca",
                       "T-SEARCH")
    if html is None:
        return
    hid = hidden_fields(html)
    if "__VIEWSTATE" not in hid:
        print("  SKIP: no __VIEWSTATE")
        return

    fields = sorted(set(DATEFIELD.findall(html)))
    print("     date fields on the form: %s" % (fields or "NONE FOUND"))
    start_field = next((f for f in fields if "start" in f.lower()), None)
    end_field = next((f for f in fields if "end" in f.lower()), None)
    if not (start_field and end_field):
        print("     SKIP: this tenancy renders no date range; it is a genuine"
              " bucket-4 address-keyed form")
        return

    # ---- Q4 first: one request decides whether the parser is even needed ---
    lo, hi = WINDOWS[0][1], WINDOWS[0][2]
    b = search_body(hid, start_field, end_field, lo, hi)
    idx, row = post(op, key, home, b, "acc_%s_1d" % key)
    if idx is None:
        return
    d = describe(idx)
    show("1d", d)

    hid2 = hidden_fields(idx)
    exp_body = dict(hid2)
    exp_body["__EVENTTARGET"] = EXPORT_BTN
    exp_body["__EVENTARGUMENT"] = ""
    body, erow = post(op, key, home, exp_body, "acc_%s_export" % key,
                      page_type="T-EXPORT")
    if erow:
        ct = erow.get("content_type") or ""
        head = (body or "")[:160].replace("\n", " ").replace("\r", " ")
        print("     EXPORT  content_type=%-28s %dB" % (ct, erow.get("bytes", 0)))
        print("             head: %s" % head[:120])

    # ---- Q1/Q3: widen the window and watch the count ----------------------
    for tag, lo, hi in WINDOWS[1:]:
        b = search_body(hid, start_field, end_field, lo, hi)
        idx2, _ = post(op, key, home, b, "acc_%s_%s" % (key, tag))
        if idx2 is None:
            continue
        show(tag, describe(idx2))
        last = idx2

    # ---- Q2: try to walk the pager -----------------------------------------
    d = describe(last)
    targets = d["pager_targets"]
    ctl = d["pager_ctl"] or GRID
    if not targets:
        # ASP.NET GridView renders no pager on a capped set, but the postback
        # contract is fixed. Trying it blind is one request and settles Q3.
        targets = ["Page$2"]
        print("     no pager rendered; trying the GridView contract blind")
    pb = dict(hidden_fields(last))
    pb["__EVENTTARGET"] = ctl
    pb["__EVENTARGUMENT"] = targets[0]
    p2, _ = post(op, key, home, pb, "acc_%s_page2" % key)
    if p2 is not None:
        d2 = describe(p2)
        show("page2", d2)
        ids = set(re.findall(r"capID1=([^&\"']+)", last))
        ids2 = set(re.findall(r"capID1=([^&\"']+)", p2))
        print("     page2 distinct from page1: %s  (overlap %d of %d)"
              % (bool(ids2 - ids), len(ids & ids2), len(ids2) or 0))


def main():
    mf.retarget("step1")
    mf.BUDGET = 400
    print("=" * 86)
    print("BUCKET-4 ACQUISITION TEST - can an Accela tenancy be enumerated "
          "by date partitioning?")
    print("=" * 86)
    for t in TENANCIES:
        run(*t)
    print("\nrequests spent: %d" % mf.spent())
    return 0


if __name__ == "__main__":
    sys.exit(main())
