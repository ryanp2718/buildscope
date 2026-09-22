# -*- coding: utf-8 -*-
"""Step 1: pull St. Johns County FL and reconcile it against BPS.

This is the source that can actually produce an error figure for the
HTML-adapter path. Clark County cannot: it publishes no unit count anywhere
and its index date is the record's opened date, not its issue date, so the
drift alarm blocks it and is right to. St. Johns publishes a per-record
structure class and an explicit "Issue Dt", which is everything the
reconciliation join needs except the unit count itself - and for the classes
this county actually issues, the class names the count.

**Weekly windows, and the reason is measured rather than chosen.** The portal
caps a result set at ~500 rows and announces the cap; a week of St. Johns ran
245 and 277 rows in the two weeks sampled, and a month would be roughly 1,100.
So a week sits comfortably inside the cap with room for a busy one, and
`pull_window` bisects anything that still comes back truncated rather than
accepting it short. Windows are clipped to the month so a record is never
pulled under a month it does not belong to.

Two requests per window - a form GET for fresh ViewState, then the search POST
- against roughly 250 records. That is ~125 records per request, against
Accela's 10.

Usage:
    python scripts/step1_stjohns_run.py 2601 2602 2603
"""
import datetime
import io
import json
import os
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from permits import capture as mf  # noqa: E402
from permits import emit                            # noqa: E402
from permits.adapters import stjohns as sj          # noqa: E402

SRC = sj.StJohnsSource(
    note="Spike A bucket 4 (misclassified: it accepts a date range and is "
         "bucket 3); BPS office has 3,637 units/12mo")

WINDOW_DAYS = 7


def month_windows(yymm, days=WINDOW_DAYS):
    """Closed windows covering one YYMM, clipped to the month."""
    y, m = 2000 + int(yymm[:2]), int(yymm[2:])
    d0 = datetime.date(y, m, 1)
    last = datetime.date(y + (m == 12), (m % 12) + 1, 1) - \
        datetime.timedelta(days=1)
    out = []
    while d0 <= last:
        d1 = min(d0 + datetime.timedelta(days=days - 1), last)
        out.append((d0.strftime("%m/%d/%Y"), d1.strftime("%m/%d/%Y")))
        d0 = d1 + datetime.timedelta(days=1)
    return out


def make_fetch(op):
    def f(url, name, page_type, data=None, headers=None):
        return mf.fetch(op, url, name, SRC.key, SRC.platform, page_type,
                        data=data, headers=headers)
    return f


def main():
    mf.retarget("step1")
    mf.BUDGET = int(os.environ.get("PERMITS_BUDGET", "120"))
    months = sys.argv[1:] or ["2601", "2602", "2603"]

    op = mf._opener()
    fetch = make_fetch(op)
    vb = sj.vocabulary_for(SRC)
    path = os.path.join(mf.OUT, "records", "%s.jsonl" % SRC.key)
    if os.path.exists(path):
        os.remove(path)
    em = emit.Emitter(path, SRC.source_id)

    print("=" * 84)
    print("ST. JOHNS COUNTY FL - %s   (%s)" % (SRC.label, SRC.source_id))
    print("=" * 84)

    per_month, codes = {}, collections.Counter()
    for yymm in months:
        wins = month_windows(yymm)
        print("\n-- %s: %d windows" % (yymm, len(wins)))
        st = None
        for lo, hi in wins:
            st = sj.pull_window(SRC, lo, hi, fetch, em, vb, tag=yymm,
                                stats=st)
            w = st["windows"][-1] if st["windows"] else {}
            print("   %s .. %s  rows=%-4s  (cum rows=%d emitted=%d splits=%d)"
                  % (lo, hi, w.get("rows", "-"), st["rows"], st["emitted"],
                     st["splits"]))
        st.pop("seen", None)
        per_month[yymm] = st

    alarm = em.close()
    print("\n" + "-" * 84)
    print("null rates: %s" % ", ".join(
        "%s=%.0f%%" % (k, 100 * v) for k, v in sorted(alarm["rates"].items())))
    print("countable units by BPS column: %s" % json.dumps(
        alarm["by_bps_column"]))
    print("   of which implied            : %s" % json.dumps(
        alarm["by_bps_column_implied"]))
    for t in alarm["tripped"]:
        print("   *** DRIFT ALARM: %s" % t)

    rep = vb.report()
    if rep["unmapped"]:
        print("\nUNMAPPED PROPERTY-USE CODES (the county added a code):")
        for k, n in rep["unmapped"].items():
            print("   %-40s %d" % (k, n))

    sp = os.path.join(mf.OUT, "pull_summary.json")
    summary = json.load(io.open(sp, encoding="utf-8")) \
        if os.path.exists(sp) else {}
    summary[SRC.key] = {"label": SRC.label, "state": SRC.state_fips,
                        "bps_id": SRC.bps_id, "alarm": alarm,
                        "per_month": per_month, "vocab": rep,
                        "note": SRC.note}
    json.dump(summary, io.open(sp, "w", encoding="utf-8"), indent=1,
              default=str)
    print("\nwrote %s and %s   |   requests spent: %d"
          % (os.path.relpath(path, mf.ROOT), os.path.relpath(sp, mf.ROOT),
             mf.spent()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
