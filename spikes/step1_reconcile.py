# -*- coding: utf-8 -*-
"""Step 1: reconcile materialized records against the BPS oracle.

The deliverable of step 1 is the reconciliation number. Offline - it folds the
JSONL records `step1_run.py` emitted and never touches the network, so the
rules can be argued with and the comparison re-run for free.

Three rules carried forward from Spike B, enforced rather than assumed:

  - a month is dropped unless its BPS `Source` code says the figure is a real
    report. Scoring against Census's own imputation and booking the difference
    as extraction error would corrupt the headline metric.
  - permit counts are never substituted for unit counts.
  - the structure-type split is reported alongside the total, because Spike B's
    entire result was that error is ~2-6% for low-density and unusable for 5+,
    and a blended median hides that.

One rule that is new, and it is the reason this script exists rather than
`spike_b_compare.py`: **a jurisdiction whose records cannot be classified
produces no error figure at all.** Charlotte's `work_class` is null in 100% of
Q1 2026 records, so nothing there can be identified as new construction. Spike
B reported that as a field-availability note. Here it is enforced by the same
drift alarm that detected it, so it cannot be forgotten.
"""
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import emit, sources                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "step1")
MONTHS = ("2601", "2602", "2603")
COLS = ("u1", "u2", "u34", "u5p")


class _Ident(object):
    """D3 identity for a source declared outside `permits.sources`."""

    def __init__(self, key, state_fips, bps_id, label):
        self.key, self.state_fips = key, state_fips
        self.bps_id, self.label = bps_id, label


def load_bps():
    bps = {}
    p = os.path.join(ROOT, "data", "spike_b", "bps_months.csv")
    for r in csv.DictReader(io.open(p, newline="", encoding="utf-8")):
        bps[(r["state"], r["bps_id"], r["yymm"])] = r
    return bps


def fold(key):
    """Records -> per-month unit totals per BPS column, plus the alternate."""
    p = os.path.join(OUT, "records", "%s.jsonl" % key)
    if not os.path.exists(p):
        return None
    out = {}
    for line in io.open(p, encoding="utf-8"):
        d = json.loads(line)
        iss = d.get("date_issued")
        if not iss:
            continue
        yymm = iss[2:4] + iss[5:7]
        m = out.setdefault(yymm, {"cols": dict.fromkeys(
            COLS + ("low_bundle",), 0), "n": 0, "alt": 0, "alt_seen": False,
            "unclassified": 0})
        m["n"] += 1
        u = d.get("countable_units") or 0
        c = d.get("bps_column")
        if u and c:
            m["cols"][c] = m["cols"].get(c, 0) + u
        elif d.get("work_class") == "NEW" and d.get("permit_kind") == "BUILDING" \
                and not c:
            m["unclassified"] += 1
        nat = d.get("native") or {}
        if nat.get("alt_units") is not None:
            m["alt_seen"] = True
            if d.get("permit_kind") == "BUILDING" and d.get("work_class") == "NEW":
                m["alt"] += nat["alt_units"]
    return out


def pct(a, r):
    return (100.0 * abs(a - r) / r) if r else None


def fmt(x):
    return "n/a" if x is None else "%.1f%%" % x


def main():
    bps = load_bps()
    summary = json.load(open(os.path.join(OUT, "pull_summary.json"),
                             encoding="utf-8"))
    rows = []
    blocked = []
    qualified = []

    print("=" * 94)
    print("STEP 1 - RECONCILIATION AGAINST THE BPS ORACLE  (folded from "
          "materialized records)")
    print("=" * 94)
    print("%-22s %-6s %-4s %8s %8s %9s %10s %10s"
          % ("jurisdiction", "month", "src", "ours", "BPS", "err",
             "low-dens", "5+"))

    # Anything that was pulled and alarmed, whether or not it is in the
    # open-data source list. Clark County is an Accela source declared in its
    # own run script, so iterating `sources.SOURCES` alone made the one
    # jurisdiction that failed loudest invisible in the report that decides
    # what may be quoted - a blocked source that nothing prints is a blocked
    # source nobody knows about. The summary is the record of what actually
    # ran, so the summary is what gets enumerated.
    keyed = dict((s.key, s) for s in sources.SOURCES)
    for key in sorted(summary):
        s = summary.get(key, {})
        alarm = s.get("alarm", {})
        if alarm.get("tripped"):
            blocked.append((s.get("label") or getattr(keyed.get(key), "label",
                                                      key),
                            alarm["tripped"][0]))
            continue
        for q in alarm.get("qualified", []):
            qualified.append((s.get("label") or key, q))
        src = keyed.get(key)
        if src is None:
            # Not an open-data source, but the summary already carries D3's
            # `(state_fips, bps_id)` and a label because every run script
            # writes them. Skipping here would silently exclude every
            # HTML-adapter jurisdiction from the comparison - the sources this
            # step exists to test - on the technicality of which list they are
            # declared in.
            if not (s.get("state") and s.get("bps_id")):
                continue
            src = _Ident(key, s["state"], s["bps_id"],
                         s.get("label") or key)
        got = fold(src.key)
        if not got:
            continue
        for yymm in MONTHS:
            b = bps.get((src.state_fips, src.bps_id, yymm))
            m = got.get(yymm)
            if b is None or m is None:
                continue
            if b["usable"] != "Y":
                print("%-22s %-6s %-4s %8s %8s   DROPPED: imputed month"
                      % (src.label[:22], yymm, b["source"], "-", b["units"]))
                continue
            ours = sum(m["cols"].get(c, 0) for c in COLS) \
                + m["cols"].get("low_bundle", 0)
            ref = int(b["units"] or 0)
            lo_ours = sum(m["cols"].get(c, 0) for c in ("u1", "u2", "u34")) \
                + m["cols"].get("low_bundle", 0)
            lo_ref = sum(int(b[c] or 0) for c in ("u1", "u2", "u34"))
            hi_ours, hi_ref = m["cols"].get("u5p", 0), int(b["u5p"] or 0)
            e = pct(ours, ref)
            q = bool(alarm.get("qualified"))
            print("%-22s %-6s %-4s %8d %8d %9s %10s %10s%s"
                  % (src.label[:22], yymm, b["source"], ours, ref, fmt(e),
                     fmt(pct(lo_ours, lo_ref)), fmt(pct(hi_ours, hi_ref)),
                     "  *" if q else ""))
            rows.append(dict(qualified="Y" if q else "", jurisdiction=src.label, state=src.state_fips,
                             bps_id=src.bps_id, yymm=yymm, source=b["source"],
                             ours=ours, bps=ref, abs_pct_err=e,
                             low_ours=lo_ours, low_bps=lo_ref,
                             low_err=pct(lo_ours, lo_ref),
                             high_ours=hi_ours, high_bps=hi_ref,
                             high_err=pct(hi_ours, hi_ref),
                             records=m["n"],
                             new_building_unclassified=m["unclassified"]))

    # ---- the Seattle unit-field experiment ------------------------------
    got = fold("seattle")
    if got and any(v["alt_seen"] for v in got.values()):
        print("\n" + "-" * 94)
        print("SEATTLE: housingunits (what Spike B used) vs housingunitsadded "
              "(what BPS counts)")
        for yymm in MONTHS:
            b = bps.get(("53", "475000", yymm))
            m = got.get(yymm)
            if not b or not m or b["usable"] != "Y":
                continue
            ours = sum(m["cols"].get(c, 0) for c in COLS)
            print("   %-6s BPS=%-5s housingunits=%-5d (%6s)   "
                  "housingunitsadded=%-5d (%6s)"
                  % (yymm, b["units"], ours, fmt(pct(ours, int(b["units"]))),
                     m["alt"], fmt(pct(m["alt"], int(b["units"])))))

    if qualified:
        print("\n" + "-" * 94)
        print("*  FIGURE PRODUCED BUT QUALIFIED - real, and not quotable bare:")
        for label, why in qualified:
            print("   %-24s %s" % (label[:24], why))

    if blocked:
        print("\n" + "-" * 94)
        print("NO ERROR FIGURE PRODUCED - the drift alarm blocked these:")
        for label, why in blocked:
            print("   %-24s %s" % (label, why))

    # ---- summary --------------------------------------------------------
    def med(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else None

    # The headline medians are the MEASURED sources only. A qualified source
    # is reported beside them, never inside them: folding a figure whose units
    # were implied into the same median as figures whose units were stated
    # would make the qualification unrecoverable from the number.
    meas = [r for r in rows if not r.get("qualified")]
    qual = [r for r in rows if r.get("qualified")]
    tot = [r["abs_pct_err"] for r in meas]
    lo = [r["low_err"] for r in meas]
    hi = [r["high_err"] for r in meas]
    print("\n" + "=" * 94)
    print("MEASURED sources only")
    print("n = %d jurisdiction-months over %d jurisdictions"
          % (len(meas), len(set(r["jurisdiction"] for r in meas))))
    print("   median |err| blended     : %s   <- do not quote alone" % fmt(med(tot)))
    print("   median |err| low-density : %s   (n=%d)"
          % (fmt(med(lo)), len([x for x in lo if x is not None])))
    print("   median |err| 5+ units    : %s   (n=%d)"
          % (fmt(med(hi)), len([x for x in hi if x is not None])))

    if qual:
        print("\n   QUALIFIED, reported separately (units implied from a "
              "published structure class):")
        for r in qual:
            print("      %-24s %-6s ours=%-6d BPS=%-6d %s"
                  % (r["jurisdiction"][:24], r["yymm"], r["ours"], r["bps"],
                     fmt(r["abs_pct_err"])))
        print("      median |err| low-density : %s   (n=%d)"
              % (fmt(med([r["low_err"] for r in qual])), len(qual)))

    if rows:
        p = os.path.join(OUT, "reconciliation.csv")
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print("\nwrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
