# -*- coding: utf-8 -*-
"""Spike B step 5: score portal-derived unit counts against the BPS oracle.

`|ours - BPS| / BPS`, per jurisdiction-month, with the structure-type split
beside it - a large error concentrated in the 5+ column is a different
diagnosis from a uniform one.

Two rules from the protocol are enforced here rather than assumed:

  - the month is dropped unless its BPS `Source` code says the figure is a
    real report. Scoring an observation against Census's own model and booking
    the difference as our extraction error would corrupt the headline metric.
  - a jurisdiction that cannot produce unit counts produces NO error figure.
    It is reported in the field-availability table instead. Substituting
    permit counts for unit counts to fill a cell would be inventing a number.
"""
import csv
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "spike_b")
MONTHS = ("2601", "2602", "2603")


def main():
    bps = {}
    for r in csv.DictReader(io.open(os.path.join(OUT, "bps_months.csv"),
                                    newline="", encoding="utf-8")):
        bps[(r["state"], r["bps_id"], r["yymm"])] = r
    ex = json.load(io.open(os.path.join(OUT, "extract.json"), encoding="utf-8"))

    print("=" * 78)
    print("SPIKE B - reconciliation against the BPS oracle")
    print("=" * 78)
    print("%-22s %-6s %-7s %-8s %-8s %-9s %s"
          % ("jurisdiction", "month", "src", "ours", "BPS", "err", "BPS split 1/2/3-4/5+"))

    rows, errs = [], []
    for key, j in ex.items():
        for m in MONTHS:
            mm = j["months"].get(m, {})
            b = bps.get((j["state"], j["bps_id"], m))
            if b is None:
                continue
            split = "%s/%s/%s/%s" % (b["u1"], b["u2"], b["u34"], b["u5p"])
            if b["usable"] != "Y":
                print("%-22s %-6s %-7s %-8s %-8s %-9s  DROPPED: imputed month"
                      % (j["label"][:22], m, b["source"], "-", b["units"], "-"))
                continue
            if j["units_field"] is None:
                print("%-22s %-6s %-7s %-8s %-8s %-9s %s  (no unit field; "
                      "permits=%s)"
                      % (j["label"][:22], m, b["source"], "n/a", b["units"],
                         "n/a", split, mm.get("permits", "-")))
                continue
            if "error" in mm:
                print("%-22s %-6s %-7s %-8s %-8s %-9s %s  (%s)"
                      % (j["label"][:22], m, b["source"], "FAIL", b["units"],
                         "-", split, mm["error"][:28]))
                continue
            ours = mm.get("units") or 0
            ref = float(b["units"] or 0)
            err = abs(ours - ref) / ref if ref else float("nan")
            errs.append(err)
            print("%-22s %-6s %-7s %-8d %-8d %-9s %s"
                  % (j["label"][:22], m, b["source"], ours, ref,
                     "%.1f%%" % (100 * err) if ref else "n/a", split))
            rows.append(dict(jurisdiction=j["label"], state=j["state"],
                             bps_id=j["bps_id"], yymm=m, source=b["source"],
                             ours=ours, bps=int(ref),
                             abs_pct_err=round(100 * err, 1) if ref else "",
                             bps_u1=b["u1"], bps_u2=b["u2"], bps_u34=b["u34"],
                             bps_u5p=b["u5p"], rule=j["rule"]))

    if rows:
        p = os.path.join(OUT, "reconciliation.csv")
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print("\nwrote %s" % os.path.relpath(p, ROOT))

    # ---- the structure-type split, which is where the diagnosis lives -----
    # The protocol asks for this explicitly: "a large error concentrated in the
    # 5+ units column is a different diagnosis than a uniform one". It is not
    # uniform, and that turns out to be the main result of the spike.
    print("\n" + "=" * 78)
    print("ERROR BY STRUCTURE TYPE  (low-density = BPS 1-unit + 2 + 3-4)")
    print("=" * 78)
    print("%-22s %-6s %-22s %-22s" % ("jurisdiction", "month",
                                      "low-density ours/BPS", "5+ ours/BPS"))
    LOW = {"austin": ("R- 101", "R- 102", "R- 103", "R- 104"),
           "columbus": ("1,2,3 Family",)}
    HIGH = {"austin": ("C- 105", "R- 105"), "columbus": ("Multi Family",)}
    for key in ("austin", "columbus"):
        j = ex.get(key)
        if not j:
            continue
        for m in MONTHS:
            mm = j["months"].get(m, {})
            b = bps.get((j["state"], j["bps_id"], m))
            if not b or "split" not in mm:
                continue
            sp = mm["split"]

            def tot(prefixes):
                return sum(d.get("units") or 0 for k, d in sp.items()
                           if k.startswith(prefixes))
            lo = tot(tuple(LOW[key]))
            hi = tot(tuple(HIGH[key]))
            blo = int(b["u1"]) + int(b["u2"]) + int(b["u34"])
            bhi = int(b["u5p"])
            def pct(a, r):
                return "%.1f%%" % (100.0 * abs(a - r) / r) if r else "n/a"
            print("%-22s %-6s %-22s %-22s"
                  % (j["label"][:22], m,
                     "%d / %d  (%s)" % (lo, blo, pct(lo, blo)),
                     "%d / %d  (%s)" % (hi, bhi, pct(hi, bhi))))

    if errs:
        errs.sort()
        med = errs[len(errs) // 2]
        print("\nn months compared: %d   median |err|: %.1f%%   range %.1f%% - %.1f%%"
              % (len(errs), 100 * med, 100 * errs[0], 100 * errs[-1]))
        print("A median over %d months is a different claim from a median over "
              "15. Report n beside it, always." % len(errs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
