# -*- coding: utf-8 -*-
"""Is bucket 4 really bucket 4? Probing the address-keyed portals by date.

Spike A put three portals in bucket 4 - "search-only, needs a known address,
parcel or permit number" - and docs/design/history.md's 73.1% unit-weighted reachability
rests entirely on that bucket turning out to be acquirable. The Accela probes
settled bucket *3*, not this. Accela was never in bucket 4.

But Spike A's own `final_probe.json` records that St. Johns County FL renders
`TextBoxFromDt` and `TextBoxToDt` on its search form. A date range is not an
address. If a date-bounded POST returns a result set, St. Johns is bucket 3
and was misclassified, and the bucket-4 mass shrinks rather than the bucket-4
question being answered.

That distinction matters more than it sounds. Spike A recorded `rows: 15` for
its St. Johns POST, which reads like a result set. The saved bytes show the
form page has 44 `<tr>` in its *layout* tables and no result grid at all, so
that 15 was almost certainly counting chrome. Counting `<tr>` without checking
what table they belong to is the same proxy-metric failure as comparing page
sizes to test a date filter. This script reads the rows.

One tenancy per run, a handful of requests, no classification decided here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import aspnet                              # noqa: E402

DATE = aspnet.DATE

PORTALS = [
    # key, label, url, date fields, submit control, extra criteria
    ("stjohns", "St. Johns County FL (WATS .NET)",
     "https://webapp.sjcfl.us/watswebx/permit/SearchPermit.aspx",
     ("ctl00$cphBody$TextBoxFromDt", "ctl00$cphBody$TextBoxToDt"),
     ("ctl00$cphBody$btnSearch", "Search"), {}),
]

WINDOWS = [("wk 2026-03-02", "03/02/2026", "03/08/2026"),
           ("wk 2025-08-11", "08/11/2025", "08/17/2025"),
           ("day 2026-03-02", "03/02/2026", "03/02/2026")]


def describe(tag, html):
    gs = aspnet.result_grids(html)
    if not gs:
        print("     %-16s no result grid found  (%d bytes)" % (tag, len(html)))
        return None
    for tid, wide, dated in gs:
        ds = sorted({d for r in dated for d in DATE.findall(" ".join(r))})
        print("     %-16s grid=%-28s rows=%-4d dated=%-4d cols=%d"
              % (tag, tid[:28], len(wide), len(dated), max(len(r) for r in wide)))
        print("        dates %s .. %s" % (ds[0] if ds else "-", ds[-1] if ds else "-"))
        print("        header: %s" % " | ".join(wide[0])[:110])
        if len(wide) > 1:
            print("        row1  : %s" % " | ".join(wide[1])[:110])
    return gs


def run(key, label, url, datef, submit, extra):
    print("\n=== %s ===" % label)
    op = mf._opener()
    html, _ = mf.fetch(op, url, "b4_%s_form" % key, key, "wats", "T-SEARCH")
    if html is None:
        return
    hid = aspnet.hidden_fields(html)
    print("     hidden fields: %s" % ", ".join(sorted(hid)) or "none")

    def send(tag, body, name):
        data = aspnet.encode(body)
        h, _ = mf.fetch(op, url, name, key, "wats", "T-INDEX", data=data,
                        headers=aspnet.headers_for(url))
        return describe(tag, h) if h is not None else None

    base = dict(hid)
    base[submit[0]] = submit[1]
    base.update(extra)

    send("control (none)", dict(base), "b4_%s_control" % key)
    for tag, lo, hi in WINDOWS:
        b = dict(base)
        b[datef[0]], b[datef[1]] = lo, hi
        send(tag, b, "b4_%s_%s_%s" % (key, lo.replace("/", ""), hi.replace("/", "")))


def main():
    mf.retarget("step1")
    mf.BUDGET = 400
    print("=" * 86)
    print("BUCKET-4 RECLASSIFICATION PROBE - do the address-keyed portals "
          "accept a date range?")
    print("=" * 86)
    for p in PORTALS:
        run(*p)
    print("\nrequests spent: %d" % mf.spent())
    return 0


if __name__ == "__main__":
    sys.exit(main())
