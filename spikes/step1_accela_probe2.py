# -*- coding: utf-8 -*-
"""Bucket-4 acquisition test, part 2: is the date filter real, and where is
the cap?

Probe 1 established that the GridView paging contract works - `Page$2` returns
rows 11-20 even though Accela renders no pager on a capped result set. It also
returned byte-identical pages for a 1-day, 7-day and 31-day window, which has
two very different explanations:

  (a) the date criteria are being ignored, or
  (b) the criteria work fine and all three windows share the same ten most
      recent rows, because the grid sorts by date descending and every window
      ends on the same day.

(a) kills date partitioning. (b) is harmless. Telling them apart needs a
window that CANNOT share rows with the default set, so this asks for an old
month and reads the dates off the returned rows. Reading the rows rather than
comparing page sizes is the point: probe 1's byte comparison could not
distinguish these, and a byte comparison is exactly the kind of proxy metric
this project keeps finding to be wrong.

Then two things the answer unlocks:

  Q3  Is "100+" a display cap or a hard result cap? Walk the pager past
      row 100 and see whether rows keep coming.
  Q5  Does a narrow window ever produce a STATED count (e.g. "1-10 of 47")
      instead of "100+"? A stated count makes bisection terminating.
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
HOME = "%s/Cap/CapHome.aspx?module=Building&TabName=Building"

BASE = {"clarkco": "https://aca-prod.accela.com/clarkco",
        "oregon": "https://aca-oregon.accela.com/oregon"}

HIDDEN = re.compile(
    r'<input[^>]+type="hidden"[^>]*name="(__[A-Z]+[A-Za-z]*)"[^>]*value="([^"]*)"',
    re.I)
HIDDEN2 = re.compile(
    r'<input[^>]+name="(__[A-Z]+[A-Za-z]*)"[^>]+value="([^"]*)"[^>]*type="hidden"',
    re.I)
SHOWING = re.compile(r"Showing\s*(\d+)\s*-\s*(\d+)\s*of\s*([\d,]+\+?)", re.I)
ROWPAT = re.compile(r'<tr class="ACA_TabRow_(?:Odd|Even)[^"]*">(.*?)</tr>',
                    re.I | re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def unesc(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))


def hidden_fields(html):
    d = {}
    for pat in (HIDDEN, HIDDEN2):
        for k, v in pat.findall(html):
            d.setdefault(k, unesc(v))
    return d


def text(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def rows(html):
    """(permit_number, date, cells) per result row.

    Column order differs per tenancy - Clark County is
    Date|Number|Type|... while Oregon is |Number|Status|Type|Agency|... - so
    the permit number is taken from the CapDetail anchor and the date by
    pattern, never by position. Positional parsing is what would make this
    adapter break silently on the next tenancy.
    """
    out = []
    for r in ROWPAT.findall(html):
        cells = [text(c) for c in CELL.findall(r)]
        num = re.search(r"lblPermitNumber1?[^>]*>([^<]+)", r)
        if not num:
            num = re.search(r'CapDetail\.aspx[^>]*>\s*(?:<[^>]+>\s*)*([^<\s][^<]*)', r)
        d = DATE.search(" ".join(cells))
        out.append(((num.group(1).strip() if num else ""),
                    (d.group(1) if d else ""), cells))
    return out


def post(op, key, body, name):
    home = HOME % BASE[key]
    origin = "://".join(urllib.parse.urlsplit(home)[:2])
    data = urllib.parse.urlencode(body).encode("utf-8")
    return mf.fetch(op, home, name, key, "accela-aca", "T-INDEX", data=data,
                    headers={"Referer": home, "Origin": origin})


def criteria(hid, lo=None, hi=None):
    b = dict(hid)
    b["__EVENTTARGET"] = SEARCH_BTN
    b["__EVENTARGUMENT"] = ""
    if lo:
        b[PFX + "txtGSStartDate"] = lo
    if hi:
        b[PFX + "txtGSEndDate"] = hi
    return b


def report(tag, html):
    m = SHOWING.search(html)
    rs = rows(html)
    ds = [d for _, d, _ in rs if d]
    print("     %-22s rows=%-3d showing=%-15s dates %s .. %s   e.g. %s"
          % (tag, len(rs), ("%s-%s of %s" % m.groups()) if m else "none",
             min(ds) if ds else "-", max(ds) if ds else "-",
             ", ".join(n for n, _, _ in rs[:2])))
    return rs, (m.group(3) if m else None)


def run(key):
    print("\n=== %s ===" % key)
    op = mf._opener()
    home = HOME % BASE[key]
    html, _ = mf.fetch(op, home, "acc2_%s_home" % key, key, "accela-aca",
                       "T-SEARCH")
    if html is None:
        return
    hid = hidden_fields(html)

    # ---- is the filter real? ----------------------------------------------
    ctrl, _ = post(op, key, criteria(hid), "acc2_%s_nodate" % key)
    if ctrl is None:
        return
    report("control (no dates)", ctrl)

    for tag, lo, hi in [("old 2026-03-02", "03/02/2026", "03/02/2026"),
                        ("old 2025-08-11", "08/11/2025", "08/11/2025")]:
        h, _ = post(op, key, criteria(hid, lo, hi),
                    "acc2_%s_%s" % (key, lo.replace("/", "")))
        if h is None:
            continue
        rs, stated = report(tag, h)
        ds = {d for _, d, _ in rs if d}
        inside = {d for d in ds if d == lo}
        print("        -> %d/%d rows carry the requested date  %s"
              % (len(inside), len(ds),
                 "FILTER WORKS" if inside and len(ds) <= 2
                 else "FILTER IGNORED" if not inside else "mixed"))
        if stated and not stated.endswith("+"):
            print("        -> STATED COUNT %s - bisection can terminate"
                  % stated)

    # ---- Q3: walk past row 100 --------------------------------------------
    last = ctrl
    seen = set()
    print("     walking the pager on the unfiltered set:")
    for page in range(2, 14):
        pb = dict(hidden_fields(last))
        pb["__EVENTTARGET"] = GRID
        pb["__EVENTARGUMENT"] = "Page$%d" % page
        h, _ = post(op, key, pb, "acc2_%s_p%d" % (key, page))
        if h is None:
            break
        m = SHOWING.search(h)
        rs = rows(h)
        nums = {n for n, _, _ in rs if n}
        new = nums - seen
        seen |= nums
        print("        page %-3d showing=%-15s rows=%-3d new=%-3d"
              % (page, ("%s-%s of %s" % m.groups()) if m else "none",
                 len(rs), len(new)))
        if not new:
            print("        -> no new records; the cap is HARD at ~%d" % len(seen))
            break
        last = h
    else:
        print("        -> still returning new records past row %d; the '100+'"
              " is a DISPLAY cap" % (len(seen)))


def main():
    mf.retarget("step1")
    mf.BUDGET = 400
    print("=" * 86)
    print("BUCKET-4 ACQUISITION TEST 2 - is the date filter real, and where "
          "is the cap?")
    print("=" * 86)
    for k in ("clarkco",):
        run(k)
    print("\nrequests spent: %d" % mf.spent())
    return 0


if __name__ == "__main__":
    sys.exit(main())
