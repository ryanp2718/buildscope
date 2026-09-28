# -*- coding: utf-8 -*-
"""Held-out test targets for the step 6 model comparison: fetch the pages.

Clark County and St. Johns County are development targets. Every prompt
change, and the Clark-derived hint in particular, was written while looking at
their pages and at model output on them, so a pass rate on them measures fit
to those two portals as much as capability. A held-out target is one whose
pages no prompt was written against. Its only job is to be scored.

What makes a good one here:

  - **Same vendor, different template.** Accela tenancies share the platform
    and differ in column set and order (see `permits/adapters/accela.py`).
    That tests whether a synthesized extractor learned the grid or learned
    Clark's column order.
  - **Several pages of one closed past window.** Synthesis sees a window of
    page 1; the extractor is then scored on every page. Pages 2+ are what
    catch an extractor that hard-codes page 1's content.
  - **Reference output a person has checked.** The adapter produces the
    reference; a held-out target is not a reference until someone has read
    the adapter's rows against the rendered page.

The walk is the adapter's own search POST and `Page$N` postback, capped at
`max_pages` because hand-checking the reference is the binding cost, not
requests. Nothing is emitted as a permit record; the pages and their manifest
rows are the output.

Usage:
    python spikes/heldout_fetch.py                 # every tenancy below
    python spikes/heldout_fetch.py santabarbara
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import aspnet                           # noqa: E402
from permits import capture as mf                    # noqa: E402
from permits.adapters import accela                  # noqa: E402

# key -> (source, lo, hi, max_pages, criteria). Windows are closed, in the past, and
# chosen before looking at any row in them. The window is set in the tag so a
# second window on the same tenancy never overwrites the first.
#
# lo = hi = None: no date filter, so the most recent records, date-descending,
# tagged with the fetch date. For a tenancy whose search form has no date
# fields. Santa Barbara's has none, and answers both a date POST and an empty
# search with the form and no result list (2026-09-27); it wants at least one
# criterion, so it gets one permit type from its own `ddlGSPermitType`,
# chosen for volume before any row was read. The pages are a snapshot; the
# corpus is the saved pages, not the window, so records moving between pages
# later does not matter.
TENANCIES = {
    "santabarbara": (
        accela.AccelaSource(
            key="santabarbara", state_fips="06", bps_id="",
            label="Santa Barbara CA (city)",
            base="https://aca-prod.accela.com/santabarbara"),
        None, None, 5,
        {accela.PFX + "ddlGSPermitType": "Building/Residential/Alteration/NA"}),
    # Record Number first and Date sixth: the column order is not Clark's.
    "POLKCO": (
        accela.AccelaSource(
            key="POLKCO", state_fips="", bps_id="",
            label="Polk County",
            base="https://aca-prod.accela.com/POLKCO"),
        "08/03/2026", "08/14/2026", 4, {}),
    # A different template cohort from Clark (Spike C: Jaccard 0.155), a
    # different host, and an Agency column. Its pages were read while the
    # adapter was written, never while a prompt was.
    "oregon": (
        accela.AccelaSource(
            key="oregon", state_fips="41", bps_id="",
            label="Oregon statewide",
            base="https://aca-oregon.accela.com/oregon"),
        "08/03/2026", "08/14/2026", 4, {}),
}


def walk(src, lo, hi, max_pages, criteria):
    op = mf._opener()

    def fetch(url, name, page_type, data=None, headers=None):
        return mf.fetch(op, url, name, src.key, src.platform, page_type,
                        data=data, headers=headers)

    if lo is None:
        tag = "ho" + datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d")
    else:
        tag = "ho%s%s" % (lo[6:] + lo[:2] + lo[3:5], hi[:2] + hi[3:5])
    home = src.home
    hdrs = aspnet.headers_for(home)
    html, _ = fetch(home, "acc_%s_%s_home" % (src.key, tag), "T-SEARCH")
    if html is None:
        return {"error": "no search page"}
    hidden = aspnet.hidden_fields(html)
    if lo is None:
        body = aspnet.body(hidden, event_target=accela.SEARCH_BTN,
                           criteria=criteria)
    elif accela.PFX + "txtGSStartDate" not in html:
        return {"error": "search form has no date fields; use lo=hi=None"}
    else:
        body = dict(accela.search_body(hidden, lo, hi), **criteria)
    html, _ = fetch(home, "acc_%s_%s_p1" % (src.key, tag), "T-INDEX",
                    data=aspnet.encode(body), headers=hdrs)
    seen, pages, stated = set(), [], None
    page = 1
    while html is not None:
        rows, total, capped = accela.parse_index(html)
        if stated is None:
            stated = "%s%s" % (total, "+" if capped else "")
        fresh = [r for r in rows if r.get("number") not in seen]
        seen.update(r.get("number") for r in fresh)
        pages.append((page, len(rows), len(fresh)))
        print("   page %d: %d rows, %d new" % (page, len(rows), len(fresh)))
        if (not fresh or len(rows) < accela.ROWS_PER_PAGE
                or page >= max_pages):
            break
        page += 1
        html, _ = fetch(home, "acc_%s_%s_p%d" % (src.key, tag, page),
                        "T-INDEX",
                        data=aspnet.encode(accela.page_body(
                            aspnet.hidden_fields(html), page)),
                        headers=hdrs)
    return {"tag": tag, "stated_total": stated, "pages": pages,
            "records": len(seen)}


def main():
    mf.retarget("step1")
    keys = sys.argv[1:] or list(TENANCIES)
    for key in keys:
        src, lo, hi, max_pages, criteria = TENANCIES[key]
        # robots.txt + search page + one POST per page, and one spare.
        mf.BUDGET = mf.spent() + max_pages + 3
        print("-- %s  %s  (at most %d pages)"
              % (src.label, "%s .. %s" % (lo, hi) if lo else "most recent",
                 max_pages))
        print("   %s" % walk(src, lo, hi, max_pages, criteria))
    print("requests spent: %d" % mf.spent())
    return 0


if __name__ == "__main__":
    sys.exit(main())
