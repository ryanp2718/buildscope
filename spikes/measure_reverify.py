# -*- coding: utf-8 -*-
"""Re-verify stored bytes under a corrected rule, append-only. No HTTP.

This is the D1 fold semantics at the smallest possible scale, and it exists
because the first Measurement A run hit exactly the case D1 was designed for.

The capture-time verifier rejected `oregon_detail2_MARION_CO.html` as "a result
list, not a record". It is not: it is permit 555-26-006952-ELEC, a Residential
Electrical record with status "Permit Issued". It was thrown away because the
rejection test matched `Showing 1-3 of 3`, which a genuine permit detail page
emits from its own inspections and related-records sub-grids. The rule was too
broad; the bytes were always fine.

The tempting fix is to edit the manifest row. That is exactly what D1 forbids.
Raw bytes are immutable and so is the record of what was believed about them at
capture time; a corrected judgement is a NEW row, and the current verdict for a
file is its LAST row. Reading the manifest as a fold rather than a table is what
makes the correction auditable instead of invisible.

Run after changing anything in permits.capture.verify().
"""
import csv
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402


def current(rows):
    """Fold the append-only log down to one row per file: the latest wins."""
    out = {}
    for r in rows:
        if r["file"]:
            out[r["file"]] = r
    return out


def main():
    # Each spike keeps its own provenance chain; say which one to re-verify.
    if len(sys.argv) > 1:
        mf.retarget(sys.argv[1])
    if not os.path.exists(mf.MANIFEST):
        raise SystemExit("no manifest - run scripts/measure_a_run.py first")
    rows = list(csv.DictReader(io.open(mf.MANIFEST, newline="",
                                       encoding="utf-8")))
    cur = current(rows)

    changed = []
    for fn, r in sorted(cur.items()):
        path = os.path.join(mf.PAGES, fn)
        if not os.path.exists(path):
            continue
        html = io.open(path, encoding="utf-8", errors="replace").read()
        status = int(r["http_status"]) if r["http_status"] else None
        verdict, reason = mf.verify(r["page_type"], html, status)
        if verdict != r["verdict"]:
            new = dict(r)
            new["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            new["verdict"] = verdict
            new["verdict_reason"] = ("re-verified from stored bytes under "
                                     "corrected rule (was %s: %s); %s"
                                     % (r["verdict"], r["verdict_reason"],
                                        reason))
            new["request_method"] = "REVERIFY"
            mf._write(new)
            changed.append((fn, r["verdict"], verdict))

    print("RE-VERIFY  %d files in the manifest, %d verdicts changed"
          % (len(cur), len(changed)))
    for fn, was, now in changed:
        print("  %-34s %s -> %s" % (fn, was, now))
    if not changed:
        print("  nothing changed; the rule and the stored bytes already agree")
    print("\nno HTTP requests were made; original rows are untouched")


if __name__ == "__main__":
    main()
