# -*- coding: utf-8 -*-
"""Is "Accela has no dwelling-unit field" a VENDOR fact or a TENANCY fact?

Clark County NV carries no unit count anywhere - not on the index grid, and
not on any of the seven new-residential detail pages fetched from it. That
blocks the jurisdiction from producing a BPS error figure, and the drift alarm
fires on it automatically. The open question is how far that generalizes,
because it decides what the whole bucket-3 mass is worth:

  - if it is a VENDOR fact, Accela - the largest US local-government
    permitting vendor - yields permit counts and never unit counts, and the
    reconciliation has to come from somewhere else entirely.
  - if it is a TENANCY fact, it is Clark County's Application Specific Info
    configuration, other agencies publish the field, and the fleet is worth
    crawling for units after a per-tenancy check.

Four detail pages already on disk from other tenancies cannot answer it. They
are a Building Amendment, a Residential Mechanical, a Residential Electrical
and a Revision - the same mistake that made the first Clark County look
conclusive when it was not. Accela renders Application Specific Info per
record type, so only a *new residential building* record tests the question.

Two things that cost nothing made this probe cheap. The saved search pages
carry each tenancy's own `ddlGSPermitType` vocabulary, so the exact option
value for "new residential" is readable off disk; and they say which tenancies
expose a date range at all (11 of the 13 that returned a real search form).
The three targeted here each publish an unambiguous new-residential type AND a
date range, in three different states.

**Why the type dropdown is used here and was deliberately not used for the
Clark County pull.** Those are different questions. A production filter chosen
before the type distribution is known silently redefines what "a permit"
means, which is what produced Spike B's Austin 726% error. This is a targeted
sample asking whether one field exists on one record type; narrowing to that
record type is the measurement, not a shortcut around it. Nothing here emits a
record or contributes to a count.

Usage: python scripts/step1_accela_units_probe.py
"""
import io
import json
import os
import re
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from permits import capture as mf  # noqa: E402
from permits import aspnet                          # noqa: E402
from permits.adapters import accela                 # noqa: E402

# (key, label, base, module, tab, ddlGSPermitType value)
# Every type value was read out of that tenancy's own saved search page, not
# guessed. The 4-level string is Accela's own hierarchy
# (Group/Type/Subtype/Category) and must be posted exactly.
TARGETS = [
    ("COSA", "San Antonio TX", "https://aca-prod.accela.com/COSA",
     "Building", "Building", "Building/Permits/Res Building Application/Application"),
    ("sbco", "Santa Barbara County CA", "https://aca-prod.accela.com/sbco",
     "Building", "Building", "Building/Building Permit/Residential/New"),
    ("POLKCO", "Polk County", "https://aca-prod.accela.com/POLKCO",
     "Building", "Building", "Building/Residential/New/NA"),
    # Santa Barbara *city*, deliberately, once the *county* turned out to be
    # the one tenancy of the first three that publishes a unit field. The two
    # are adjacent jurisdictions and a shared implementation would show up as
    # the same field label; an independent one would not. That distinguishes
    # "1 tenancy in 4 at random" from "the field travels with an
    # implementation cohort", and the second is a far more useful answer -
    # it would be predictable from a template fingerprint rather than needing
    # a detail fetch per tenancy to discover.
    ("santabarbara", "Santa Barbara CA (city)",
     "https://aca-prod.accela.com/santabarbara",
     "Building", "Building", "Building/Residential/New/NA"),
    ("SLCREF", "Salt Lake City UT", "https://aca-prod.accela.com/SLCREF",
     "Building", "Building", "Building/Permit/Residential/NA"),
]

WINDOW = ("08/01/2026", "08/31/2026")
DETAILS_PER_TENANCY = 3

# Fields that are not a unit count but are close enough that seeing them
# mislabelled as one would be the failure mode. Reported separately so the
# distinction stays visible rather than being resolved by a regex.
NEARBY = re.compile(
    r"(?i)construction type|category of construction|type of use|occupancy|"
    r"square f|sq\.? ?ft|unit size|quantity|bedroom|stories|structure")


def search(op, key, base, module, tab, ptype):
    home = accela.HOME % (base.rstrip("/"), module, tab)
    hdrs = aspnet.headers_for(home)
    html, _ = mf.fetch(op, home, "u_%s_home" % key, key, "accela-aca",
                       "T-SEARCH")
    if html is None:
        return None, None
    hidden = aspnet.hidden_fields(html)
    crit = {accela.PFX + "txtGSStartDate": WINDOW[0],
            accela.PFX + "txtGSEndDate": WINDOW[1],
            accela.PFX + "ddlGSPermitType": ptype}
    body = aspnet.body(hidden, event_target=accela.SEARCH_BTN,
                       event_argument="", criteria=crit)
    html, prov = mf.fetch(op, home, "u_%s_idx" % key, key, "accela-aca",
                          "T-INDEX", data=aspnet.encode(body), headers=hdrs)
    return html, home


def main():
    mf.retarget("step1")
    mf.BUDGET = 24
    op = mf._opener()
    print("=" * 84)
    print("ACCELA UNIT-FIELD PROBE - vendor fact or tenancy fact?")
    print("window %s .. %s, narrowed to each tenancy's new-residential type"
          % WINDOW)
    print("=" * 84)

    # Named tenancies only, so a re-run does not re-fetch what is already on
    # disk. The saved pages are replayed for free by the caller instead.
    only = set(sys.argv[1:])
    out = []
    verdicts = collections.Counter()
    for key, label, base, module, tab, ptype in TARGETS:
        if only and key not in only:
            continue
        print("\n### %s (%s)\n    type filter: %s" % (label, key, ptype))
        html, home = search(op, key, base, module, tab, ptype)
        if html is None:
            print("    search failed - no index page")
            verdicts["no_index"] += 1
            continue
        rows, total, capped = accela.parse_index(html)
        roles, raw = accela.headers(html)
        print("    grid headers : %s" % " | ".join(h for h in raw if h)[:96])
        print("    rows on p1   : %d   stated total: %s%s"
              % (len(rows), total, "+" if capped else ""))
        if not rows:
            print("    no records in window - cannot test")
            verdicts["no_rows"] += 1
            continue

        host = re.match(r"https?://[^/]+", base).group(0)
        picked = [r for r in rows if r.get("detail_href")][:DETAILS_PER_TENANCY]
        for r in picked:
            href = r["detail_href"]
            url = href if href.startswith("http") else host + href
            nid = re.sub(r"\W+", "_", r.get("number") or "x")
            h2, _ = mf.fetch(op, url, "u_%s_d_%s" % (key, nid), key,
                             "accela-aca", "T-DETAIL",
                             headers=aspnet.headers_for(home))
            if h2 is None:
                continue
            fields = accela.detail_fields(h2)
            u, lab = accela.units_from_detail(fields)
            near = {k: v for k, v in fields.items() if NEARBY.search(k)}
            verdicts["units_found" if u is not None else "no_unit_field"] += 1
            print("    -- %-20s %s" % ((r.get("number") or "?")[:20],
                                       (r.get("type") or "")[:44]))
            print("         units  : %s %s"
                  % (u, "[%s]" % lab if lab else ""))
            print("         nearby : %s" % (json.dumps(near)[:180] if near
                                            else "none"))
            print("         all    : %s" % ", ".join(sorted(fields))[:190])
            out.append({"tenancy": key, "label": label, "native_id":
                        r.get("number"), "native_type": r.get("type"),
                        "units": u, "unit_label": lab, "nearby": near,
                        "fields": fields})

    print("\n" + "=" * 84)
    print("VERDICT this run: %s" % dict(verdicts))
    # Merged, not overwritten: a second run adds tenancies to the sample
    # rather than replacing it, and re-running one tenancy replaces only its
    # own rows.
    p = os.path.join(mf.OUT, "accela_units_probe.json")
    prev = []
    if os.path.exists(p):
        prev = json.load(io.open(p, encoding="utf-8")).get("records", [])
    done = set(r["tenancy"] for r in out)
    out = [r for r in prev if r["tenancy"] not in done] + out
    json.dump({"window": WINDOW, "targets": sorted(set(r["tenancy"]
                                                       for r in out)),
               "verdicts": dict(verdicts), "records": out},
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("wrote %s   |   requests spent: %d"
          % (os.path.relpath(p, mf.ROOT), mf.spent()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
