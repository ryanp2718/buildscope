# -*- coding: utf-8 -*-
"""The two bucket-4 offices St. Johns left behind: St. Louis MO and Bowling
Green KY, 749 units between them and 5.8% of the gate denominator.

ADR-0005 makes this the cheapest measurement that can still move the
reachability number, because bucket 4 is the only cell whose contents are
still guesses. Both rows are `probed`/`inferred` at medium and low confidence
respectively, and neither was ever sent a query.

Two things found on disk before a single request was made here, both of which
change what this script has to do:

  Bowling Green was classified `vendor: unknown, basis: inferred` with the note
  "www2.bgky.org did not respond to our client". The saved Spike A page for
  that office - `data/spike_a/html/depth_21_087000_*.html`, already on disk -
  contains `https://esuites.bgky.org/eSuite.permits/WelcomePage.aspx`. The
  portal was never unreachable. It was never looked for in the bytes we had.
  That is a replay finding, not a crawl finding, and it is the fourth time in
  this project that re-reading stored bytes beat re-fetching them.

  St. Louis's saved form carries `streetAddress` and `findByAddress` posting to
  `/searchresults.cfm`, with no required-field marker. Whether an address-keyed
  form is bucket 4 or bucket 3 depends entirely on what it does with an empty
  or wildcard criterion, which is exactly what Spike A did not test.

Discovery plus at most one query each. No bucket is decided here; the verdict
goes to classification.csv by hand, per ADR-0005.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import capture as mf  # noqa: E402
from permits import aspnet                              # noqa: E402

DATE_FIELD = re.compile(r"(?i)date|from|to|begin|end|start|issued|applied")
ADDR_FIELD = re.compile(r"(?i)address|street|parcel|apn|owner")
NUM_FIELD = re.compile(r"(?i)permit.*(no|num|#)|case.*(no|num)|record.*(no|num)")

TARGETS = [
    ("21|045000", "Bowling Green KY", "esuite",
     "https://esuites.bgky.org/eSuite.permits/WelcomePage.aspx"),
    ("29|607000", "St. Louis MO", "coldfusion",
     "https://www.stlouis-mo.gov/government/departments/public-safety/"
     "building/permits/search-building-permits-by-address.cfm"),
]


def classify_form(names):
    """What criteria does this form accept? The bucket-3/4 discriminator."""
    named = [n for n in names if not n.startswith("__")]
    return {
        "n_inputs": len(named),
        "date": sorted(n for n in named if DATE_FIELD.search(n)),
        "address": sorted(n for n in named if ADDR_FIELD.search(n)),
        "number": sorted(n for n in named if NUM_FIELD.search(n)),
    }


def describe_grid(tag, html):
    grids = aspnet.result_grids(html)
    if not grids:
        rows = len(re.findall(r"(?is)<tr\b", html))
        print("     %-22s no result grid  (%d bytes, %d raw <tr>)"
              % (tag, len(html), rows))
        return 0
    total = 0
    for tid, wide, dated in grids:
        total += len(wide)
        print("     %-22s grid=%-24s rows=%-4d dated=%d"
              % (tag, tid[:24], len(wide), len(dated)))
        print("        header: %s" % " | ".join(wide[0])[:100])
        if len(wide) > 1:
            print("        row1  : %s" % " | ".join(wide[1])[:100])
    return total


def links_to_portals(html, base):
    """Vendor-hosted portal links. The 'new portal announced 2026' check."""
    hosts = ("accela", "aca-prod", "energov", "tylerhost", "etrakit",
             "cityview", "viewpointcloud", "opengov", "citizenserve",
             "esuite", "click2gov", "centralsquare", "mygov.us", "smartgov",
             "permits", "camalot", "govbuilt", "cloudpermit")
    out = set()
    for href in re.findall(r'(?i)href="([^"]+)"', html or ""):
        low = href.lower()
        if low.startswith("http") and any(h in low for h in hosts):
            if base.split("/")[2] not in low or "permit" in low:
                out.add(href.split("?")[0])
    return sorted(out)[:12]


def probe(key, label, vendor, url):
    print("\n" + "=" * 78)
    print("%s  [%s]  %s" % (label, key, vendor))
    print("=" * 78)
    op = mf._opener()
    slug = key.replace("|", "_")
    html, row = mf.fetch(op, url, "b4b_%s_entry" % slug, label, vendor,
                         "T-SEARCH")
    if html is None:
        print("  entry page unavailable: %s" % (row or {}).get("verdict_reason"))
        return
    print("  entry %d bytes, verdict=%s" % (len(html), row["verdict"]))

    ext = links_to_portals(html, url)
    if ext:
        print("  outbound portal links:")
        for e in ext:
            print("     %s" % e)

    hid = aspnet.hidden_fields(html)
    names = aspnet.form_fields(html)
    form = classify_form(list(names) + list(hid))
    print("  form inputs: %d   date=%s   address=%s   number=%s"
          % (form["n_inputs"], form["date"] or "-", form["address"] or "-",
             form["number"] or "-"))
    if not form["date"] and not form["address"] and not form["number"]:
        print("  no permit-search criteria on the entry page; this is a "
              "landing page, not the search form")
    return {"form": form, "hidden": sorted(hid), "ext": ext,
            "bytes": len(html), "html": html, "op": op}


def main():
    mf.retarget("step1")
    mf.BUDGET = 40
    print("=" * 78)
    print("BUCKET-4 PROBE II - the two offices left in bucket 4 after "
          "St. Johns moved")
    print("749 units, 5.8% of the gate denominator")
    print("=" * 78)
    out = {}
    for key, label, vendor, url in TARGETS:
        try:
            out[key] = probe(key, label, vendor, url)
        except SystemExit:
            raise
        except Exception as exc:                        # noqa: BLE001
            print("  FAILED: %s: %s" % (type(exc).__name__, exc))
    print("\nrequests spent: %d of %d" % (mf.spent(), mf.BUDGET))
    return 0


if __name__ == "__main__":
    sys.exit(main())
