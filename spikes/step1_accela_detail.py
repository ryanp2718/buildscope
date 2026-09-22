# -*- coding: utf-8 -*-
"""Do Accela record detail pages carry a dwelling-unit count, and what does
the index Date column actually mean?

Two questions, one small fetch, because both are answered by the same pages.

**Units.** The index grid has no unit column, so `unit_count_source` is
"absent" for every Accela record and the drift alarm blocks the jurisdiction
from producing an error figure. Recovering units needs one request per record,
which is affordable only if it is aimed: of 371 Clark County records on
2026-03-02, 24 classify BUILDING+NEW and 17 of those are already resolved to
BPS 101 by the type string "Residential Building New SFR Tract Home". Roughly
twelve rows a day are genuinely ambiguous.

An earlier look at four saved detail pages found no unit field anywhere, but
all four were a Miscellaneous Structure, a revision, a mechanical addition and
an extension request. Accela renders Application Specific Info per record
type, so that sample could not answer the question. These are new residential
building permits.

**Dates.** The index column is headed "Date" but the span behind it is
`lblUpdatedTime`, and rows with 2025 permit numbers appear inside a
2026-03-02 window. If the search filters on last-updated rather than issued,
every month boundary in the reconciliation is wrong, and it would be wrong in
a way that still produces plausible-looking totals. The detail page states the
record's own dates, so comparing them settles it.

Reads candidates from pages already on disk; spends requests only on details.
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

SRC = accela.AccelaSource(
    key="clarkco", state_fips="32", bps_id="021000",
    label="Clark County NV (unincorporated)",
    base="https://aca-prod.accela.com/clarkco")

DATE_LABEL = re.compile(r"date|opened|issued|expir|status", re.I)


def saved_rows(pattern):
    d = os.path.join(mf.OUT, "pages")
    rows = []
    for fn in sorted(os.listdir(d)):
        if not re.match(pattern, fn):
            continue
        h = io.open(os.path.join(d, fn), encoding="utf-8",
                    errors="replace").read()
        rows += accela.parse_index(h)[0]
    uniq = {}
    for r in rows:
        uniq.setdefault(r.get("number"), r)
    return list(uniq.values())


def main():
    mf.retarget("step1")
    mf.BUDGET = 60
    vb = accela.vocabulary_for(SRC)
    rows = saved_rows(r"acc_clarkco_20260302_p\d+\.html$")
    recs = [(r, accela.build(SRC, r, vb, "saved")) for r in rows]

    # A spread across the ambiguous type and the already-resolved one, so the
    # comparison shows whether a detail page adds anything the index did not.
    want = ["Residential Building New", "Residential Building New SFR Tract Home",
            "Commercial Building New"]
    picks = []
    for t in want:
        hits = [(r, rec) for r, rec in recs
                if (rec.native or {}).get("native_type") == t
                and r.get("detail_href")]
        picks += hits[:3 if t == "Residential Building New" else 2]

    print("=" * 88)
    print("ACCELA DETAIL PROBE - units, and what the index Date column means")
    print("=" * 88)
    print("candidates on disk: %d records, %d picked\n" % (len(recs), len(picks)))

    op = mf._opener()
    out = []
    unit_hits = collections.Counter()
    all_labels = collections.Counter()
    for r, rec in picks:
        href = r["detail_href"]
        url = href if href.startswith("http") else \
            "https://aca-prod.accela.com" + href
        html, _ = mf.fetch(op, url, "accd_%s" % re.sub(r"\W+", "_", rec.native_id),
                           SRC.key, SRC.platform, "T-DETAIL",
                           headers=aspnet.headers_for(SRC.home))
        if html is None:
            continue
        fields = accela.detail_fields(html)
        u, label = accela.units_from_detail(fields)
        unit_hits["found" if u is not None else "absent"] += 1
        for k in fields:
            all_labels[k] += 1
        dates = {k: v for k, v in fields.items() if DATE_LABEL.search(k)}
        print("-- %-22s  %s" % (rec.native_id, (r.get("type") or "")[:44]))
        print("     index Date column : %s" % r.get("date"))
        print("     detail date fields: %s" % (dates or "none found"))
        print("     units             : %s %s" % (u, "[%s]" % label if label else ""))
        print("     detail fields (%d): %s" % (
            len(fields), ", ".join(sorted(fields)[:14])))
        out.append({"native_id": rec.native_id, "type": r.get("type"),
                    "index_date": r.get("date"), "units": u, "unit_label": label,
                    "detail_dates": dates, "fields": fields})

    print("\nunit field present: %s" % dict(unit_hits))
    print("\nlabels across these detail pages:")
    for k, n in all_labels.most_common(40):
        print("   %-54s %d" % (k[:54], n))
    p = os.path.join(mf.OUT, "accela_detail_probe.json")
    json.dump(out, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\nwrote %s   |   requests spent: %d"
          % (os.path.relpath(p, mf.ROOT), mf.spent()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
