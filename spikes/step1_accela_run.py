# -*- coding: utf-8 -*-
"""Step 1, bucket-3 path: pull a month of Accela records and reconcile them.

Run unfiltered first, deliberately. Accela's search form offers a
`ddlGSPermitType` select that would let the server drop the electrical,
plumbing, low-voltage and revision records before they are ever fetched, and
that is worth several-fold in requests. It is also exactly the move that
produced Spike B's Austin 726% error: a type filter chosen before anyone had
seen the type distribution, which silently changed what "a permit" meant. So
the first pull takes everything and the filter is designed against measured
counts rather than against an assumption about what the vendor calls things.

Two passes:

  index   walk the date window to exhaustion, ten records per page, emitting
          every row through `permits.emit`.
  detail  for the rows that classify as new residential building work, fetch
          the record detail page and look for a dwelling-unit field.

The detail pass is separate and narrow because it costs one request per
record against ten records per request for the index. Which rows deserve one
is a classification decision, and it is made from the index row, recorded, and
auditable - not hidden in a query string.

Usage:
    python scripts/step1_accela_run.py calibrate            # one day
    python scripts/step1_accela_run.py month 03/01/2026 03/31/2026
"""
import json
import os
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from permits import capture as mf  # noqa: E402
from permits import aspnet, emit                    # noqa: E402
from permits.adapters import accela                 # noqa: E402

SRC = accela.AccelaSource(
    key="clarkco", state_fips="32", bps_id="021000",
    label="Clark County NV (unincorporated)",
    base="https://aca-prod.accela.com/clarkco",
    note="Spike A bucket 3; BPS office has 3,653 units/12mo")

OUT = None


def make_fetch(op, src):
    def f(url, name, page_type, data=None, headers=None):
        return mf.fetch(op, url, name, src.key, src.platform, page_type,
                        data=data, headers=headers)
    return f


def day_windows(lo, hi):
    """Closed one-day windows across [lo, hi], MM/DD/YYYY.

    Day partitioning rather than one month-long walk: a walk that dies at page
    40 loses one day instead of the month, and each day's ViewState stays
    fresh. The extra cost is one search POST per day against ~50 page
    postbacks, which is noise.
    """
    import datetime
    d0 = datetime.datetime.strptime(lo, "%m/%d/%Y").date()
    d1 = datetime.datetime.strptime(hi, "%m/%d/%Y").date()
    out = []
    while d0 <= d1:
        s = d0.strftime("%m/%d/%Y")
        out.append((s, s, d0.strftime("%Y%m%d")))
        d0 += datetime.timedelta(days=1)
    return out


def index_pass(lo, hi, budget_note=""):
    op = mf._opener()
    fetch = make_fetch(op, SRC)
    vb = accela.vocabulary_for(SRC)
    path = os.path.join(mf.OUT, "records", "%s.jsonl" % SRC.key)
    if os.path.exists(path):
        os.remove(path)
    em = emit.Emitter(path, SRC.source_id)

    windows = day_windows(lo, hi)
    print("-- %s  %s .. %s   (%d day windows) %s"
          % (SRC.label, lo, hi, len(windows), budget_note))
    all_rows, per_day = [], {}
    for wlo, whi, tag in windows:
        s = accela.pull_window(SRC, wlo, whi, fetch, em, vb, tag=tag)
        if s.get("error"):
            print("   %s  ERROR %s" % (tag, s["error"]))
            per_day[tag] = s
            continue
        recs = s.pop("records", [])
        all_rows.extend(recs)
        per_day[tag] = s
        print("   %s  rows=%-5d emitted=%-5d pages=%-3d stated=%s%s"
              % (tag, s["rows_seen"], s["emitted"], s["pages"],
                 s["stated_total"], "+" if s["display_capped"] else ""))
    alarm = em.close()
    return all_rows, per_day, alarm, vb


def summarize(rows):
    kinds = collections.Counter(r.permit_kind for r in rows)
    works = collections.Counter(r.work_class for r in rows)
    types = collections.Counter((r.native or {}).get("native_type") for r in rows)
    print("\n   permit_kind : %s" % dict(kinds.most_common()))
    print("   work_class  : %s" % dict(works.most_common()))
    print("\n   native permit types, by count (this is what a server-side "
          "filter would be chosen from):")
    for t, n in types.most_common(40):
        print("      %-44s %5d" % ((t or "(blank)")[:44], n))
    return types


def detail_candidates(rows):
    """Rows worth one request each: new building work, detail link present."""
    out = []
    for r in rows:
        n = r.native or {}
        if not n.get("detail_href"):
            continue
        if r.permit_kind == "BUILDING" and r.work_class == "NEW":
            out.append(r)
    return out


def detail_pass(rows, limit=None):
    op = mf._opener()
    fetch = make_fetch(op, SRC)
    print("\n-- detail pass: %d candidates%s"
          % (len(rows), "" if limit is None else " (limit %d)" % limit))
    found = collections.Counter()
    labels = collections.Counter()
    results = []
    for i, r in enumerate(rows if limit is None else rows[:limit], 1):
        href = (r.native or {})["detail_href"]
        url = href if href.startswith("http") else (
            "https://aca-prod.accela.com" + href)
        html, prov = fetch(url, "accd_%s_%s" % (SRC.key, r.native_id),
                           "T-DETAIL", headers=aspnet.headers_for(SRC.home))
        if html is None:
            found["fetch_failed"] += 1
            continue
        fields = accela.detail_fields(html)
        u, label = accela.units_from_detail(fields)
        for k in fields:
            labels[k] += 1
        results.append({"native_id": r.native_id, "units": u, "label": label,
                        "n_fields": len(fields),
                        "native_type": (r.native or {}).get("native_type"),
                        "fields": fields})
        found["units_found" if u is not None else "no_unit_field"] += 1
        print("   %-22s type=%-28s fields=%-3d units=%s %s"
              % (r.native_id[:22], ((r.native or {}).get("native_type") or "")[:28],
                 len(fields), u, ("[%s]" % label) if label else ""))
    print("\n   %s" % dict(found))
    print("\n   labels seen across detail pages (top 30):")
    for k, n in labels.most_common(30):
        print("      %-52s %3d" % (k[:52], n))
    return results


def main():
    mf.retarget("step1")
    mode = sys.argv[1] if len(sys.argv) > 1 else "calibrate"

    if mode == "calibrate":
        mf.BUDGET = 80
        rows, per_day, alarm, vb = index_pass("03/02/2026", "03/02/2026",
                                              "[calibration]")
        types = summarize(rows)
        cands = detail_candidates(rows)
        print("\n   detail candidates (BUILDING+NEW with a link): %d of %d"
              % (len(cands), len(rows)))
        res = detail_pass(cands, limit=4)
        out = os.path.join(mf.OUT, "accela_calibration.json")
        json.dump({"per_day": per_day, "alarm": alarm,
                   "native_types": dict(types),
                   "n_rows": len(rows), "n_candidates": len(cands),
                   "detail_probe": res},
                  open(out, "w", encoding="utf-8"), indent=1, default=str)
        print("\nwrote %s" % os.path.relpath(out, mf.ROOT))
        print("requests spent: %d" % mf.spent())
        est = len(rows) * 31 / 10.0 + 31
        print("\nEXTRAPOLATION: %d records/day -> ~%d index requests for a "
              "31-day month, plus %d detail requests at this candidate rate."
              % (len(rows), est, len(cands) * 31))
        return 0

    if mode == "month":
        lo, hi = sys.argv[2], sys.argv[3]
        mf.BUDGET = int(os.environ.get("PERMITS_BUDGET", "1200"))
        rows, per_day, alarm, vb = index_pass(lo, hi)
        types = summarize(rows)
        print("\n   null rates: %s" % ", ".join(
            "%s=%.0f%%" % (k, 100 * v) for k, v in sorted(alarm["rates"].items())))
        for t in alarm["tripped"]:
            print("   *** DRIFT ALARM: %s" % t)
        out = os.path.join(mf.OUT, "accela_month.json")
        json.dump({"window": [lo, hi], "per_day": per_day, "alarm": alarm,
                   "native_types": dict(types), "n_rows": len(rows),
                   "vocab": vb.report()},
                  open(out, "w", encoding="utf-8"), indent=1, default=str)
        print("\nwrote %s   |   requests spent: %d"
              % (os.path.relpath(out, mf.ROOT), mf.spent()))
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
