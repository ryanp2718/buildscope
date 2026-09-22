# -*- coding: utf-8 -*-
"""Measurement B: how many distinct templates does one vendor's fleet have?

Spike C found Clark County NV and Yakima County WA Accela result pages at
Jaccard 0.766 while Oregon's statewide tenancy scored 0.155 and 0.213 against
them. So Accela cohorts exist, and nobody knows whether Accela is two cohorts
or fifty. That single number carries most of the amortization estimate, which
is why this is worth twenty HTTP requests.

One GET per tenancy, of the module search page (T-SEARCH).

**Slugs are discovered, never guessed.** Every entry below came from a public
reference to that portal - a search result, a jurisdiction's own link. Brute
forcing agency codes would mean 404-spamming a vendor that has done nothing
wrong, and would also silently bias the sample toward short slugs.

The `module` and `TabName` parameters differ per tenancy (Indianapolis runs
`module=Permits`, not `module=Building`). That is configuration, and
configuration is exactly what this measurement is trying to see, so the
discovered URL is used as-is rather than normalized into a house style.

Decision rules: docs/evidence/2026-09-20-measurement-ab-preregistration.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

ACA = "https://aca-prod.accela.com/%s/Cap/CapHome.aspx?%s"

# (key, label, url) - provenance for every slug is in the report
TENANCIES = [
    ("SACRAMENTO", "Sacramento CA", ACA % ("SACRAMENTO", "module=Building&TabName=HOME")),
    ("INDY", "Indianapolis IN", ACA % ("INDY", "module=Permits&TabName=HOME")),
    ("SLCREF", "Salt Lake City UT", ACA % ("SLCREF", "module=Building&TabName=HOME")),
    ("MONTEREY", "Monterey County CA", ACA % ("MONTEREY", "module=Building&TabName=Home")),
    ("WC", "Walnut Creek CA", ACA % ("WC", "module=Building&TabName=Building")),
    ("BOCC", "BOCC", ACA % ("BOCC", "module=Building")),
    ("PIMA", "Pima County AZ", ACA % ("PIMA", "module=Building")),
    ("POLKCO", "Polk County", ACA % ("POLKCO", "module=Building")),
    ("santabarbara", "Santa Barbara CA (city)", ACA % ("santabarbara", "module=Building")),
    ("sbco", "Santa Barbara County CA", ACA % ("sbco", "module=Building")),
    ("sccgov", "Santa Clara County CA", ACA % ("sccgov", "module=Building")),
    ("aaco", "Anne Arundel County MD", ACA % ("aaco", "module=Building")),
    ("PLACERCO", "Placer County CA", ACA % ("PLACERCO", "module=Building")),
    ("COHP", "High Point NC", ACA % ("COHP", "module=Building")),
    ("CFW", "Fort Worth TX", ACA % ("CFW", "module=Building")),
    ("COSA", "San Antonio TX", ACA % ("COSA", "module=Building")),
    ("ONE", "ONE", ACA % ("ONE", "module=Building")),
    # self-hosted ACA on the jurisdiction's own domain - tests whether the
    # hosting arrangement changes the rendered template
    ("nevadaco", "Nevada County CA (self-hosted ACA)",
     "https://permits.nevadacountyca.gov/citizenaccess/Cap/CapHome.aspx?module=Building"),
]


def main():
    mf.ensure_dirs()
    print("MEASUREMENT B - Accela cohort size across %d tenancies" % len(TENANCIES))
    print("one T-SEARCH GET each; slugs discovered from public references\n")
    op = mf._opener()
    for key, label, url in TENANCIES:
        mf.fetch(op, url, "b_%s_search" % key, "accela:%s" % key,
                 "accela-aca", "T-SEARCH")
    print("\nrequests spent this run: %d" % mf.spent())


if __name__ == "__main__":
    sys.exit(main())
