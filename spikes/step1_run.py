# -*- coding: utf-8 -*-
"""Step 1: pull permit records and emit them through the shared interface.

Unlike Spike B, this materializes rows. Spike B asked the server for COUNT and
SUM and compared totals, so its classification rule lived entirely inside a
`where` clause that nothing downstream could inspect - which is how Austin's
sub-permit overcount survived until someone pulled the breakdown by hand. Here
the rule that fired is attached to each record and the totals are a fold.

Raw bytes are retained with provenance attached at capture (section 9
obligation 2), via the same D1 capture layer Measurements A and B used.

Usage:  python scripts/step1_run.py [months] [source_key ...]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from permits import capture as mf  # noqa: E402
from permits import emit, sources                # noqa: E402
from permits.adapters import opendata            # noqa: E402

# The three months Spike B scored, so the numbers are directly comparable.
# Extending the window is a parameter, not a rewrite.
MONTHS = [("2601", "2026-01-01", "2026-02-01"),
          ("2602", "2026-02-01", "2026-03-01"),
          ("2603", "2026-03-01", "2026-04-01")]


def main():
    keys = [a for a in sys.argv[1:] if not a.isdigit()]
    mf.retarget("step1")
    # Step 1 pulls records rather than aggregates, so it needs more than the
    # 60-request measurement ceiling. Still bounded, still enforced.
    mf.BUDGET = 400
    op = mf._opener()

    probe_path = os.path.join(mf.OUT, "field_probe.json")
    probe = {}
    if os.path.exists(probe_path):
        probe = json.load(open(probe_path, encoding="utf-8"))

    recdir = os.path.join(mf.OUT, "records")
    # Merge rather than overwrite: running one source must not erase the
    # summary rows for the others.
    sp = os.path.join(mf.OUT, "pull_summary.json")
    summary = json.load(open(sp, encoding="utf-8"))         if os.path.exists(sp) else {}

    def make_fetch(src):
        def f(url, name, page_type):
            return mf.fetch(op, url, name, src.key, src.platform, page_type)
        return f

    print("=" * 86)
    print("STEP 1 - materializing permit records through permits.emit")
    print("=" * 86)

    for src in sources.SOURCES:
        if keys and src.key not in keys:
            continue
        pr = probe.get(src.key)
        if pr and not pr.get("ok"):
            print("\n-- %-24s SKIPPED: field map did not validate (%s)"
                  % (src.label, ", ".join(pr.get("missing", {}))))
            summary[src.key] = {"skipped": "field map invalid"}
            continue

        path = os.path.join(recdir, "%s.jsonl" % src.key)
        if os.path.exists(path):
            os.remove(path)          # a pull is a rebuild, not an append
        vb = opendata.vocabulary_for(src)
        em = emit.Emitter(path, src.source_id)
        print("\n-- %s  [%s]  %s" % (src.label, src.platform, src.note or ""))
        per_month = {}
        for yymm, lo, hi in MONTHS:
            try:
                s = opendata.pull(src, lo, hi, make_fetch(src), em, vb)
            except Exception as e:                  # noqa: BLE001
                print("     %s  ERROR %s" % (yymm, str(e)[:90]))
                per_month[yymm] = {"error": str(e)[:200]}
                continue
            per_month[yymm] = s
            flag = "  SERVER TRUNCATED" if s["server_truncated"] else ""
            print("     %s  rows=%-6d emitted=%-6d no-id=%-4d pages=%d%s"
                  % (yymm, s["rows_seen"], s["emitted"],
                     s["rejected_no_id"], s["pages"], flag))
        alarm = em.close()
        summary[src.key] = {"label": src.label, "state": src.state_fips,
                            "bps_id": src.bps_id, "months": per_month,
                            "alarm": alarm, "vocab": vb.report()}
        print("     null rates: %s" % ", ".join(
            "%s=%.0f%%" % (k, 100 * v) for k, v in
            sorted(alarm["rates"].items())))
        if alarm["by_bps_column"]:
            print("     countable units by BPS column: %s"
                  % json.dumps(alarm["by_bps_column"]))
        for t in alarm["tripped"]:
            print("     *** DRIFT ALARM: %s" % t)

    p = sp
    with open(p, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print("\nwrote %s   |   requests spent: %d"
          % (os.path.relpath(p, mf.ROOT), mf.spent()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
