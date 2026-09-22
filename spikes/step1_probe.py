# -*- coding: utf-8 -*-
"""Verify every declared field in the source registry against the live schema.

Runs before any pull. A source whose field map does not validate is not pulled
at all - a missing field silently reads as None, which becomes an UNKNOWN
classification, which becomes a quiet undercount that looks like real data.

This exists because `data/spike_b/schema.json` is stale for Seattle and says so
nowhere: it holds the schema of the first dataset tried, which has no date
field. Re-probing costs one request per source.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from permits import capture as mf  # noqa: E402
from permits import sources     # noqa: E402


def probe_url(src):
    if src.platform == "socrata":
        return src.base + "?" + urllib.parse.urlencode({"$limit": 1})
    return src.base + "/query?" + urllib.parse.urlencode(
        {"where": "1=1", "resultRecordCount": 1, "outFields": "*",
         "f": "json", "returnGeometry": "false"})


def live_fields(body, platform):
    d = json.loads(body)
    if platform == "socrata":
        return set(d[0].keys()) if d else set()
    if "error" in d:
        raise RuntimeError(json.dumps(d["error"])[:300])
    names = {f["name"] for f in d.get("fields", [])}
    for f in d.get("features", []):
        names |= set(f.get("attributes", {}).keys())
    return names


def declared(src):
    out = {"id_field": (src.id_field,), "issued_field": (src.issued_field,),
           "structure_fields": src.structure_fields,
           "work_fields": src.work_fields, "kind_fields": src.kind_fields,
           "desc_fields": src.desc_fields}
    if src.applied_field:
        out["applied_field"] = (src.applied_field,)
    if src.units_field:
        out["units_field"] = (src.units_field,)
    if src.address_field:
        out["address_field"] = (src.address_field,)
    return out


def main():
    mf.retarget("step1")
    op = mf._opener()
    report = {}
    print("=" * 84)
    print("STEP 1 - field-map validation against live schemas")
    print("=" * 84)
    for src in sources.SOURCES:
        body, prov = mf.fetch(op, probe_url(src), "probe_%s" % src.key,
                              src.key, src.platform, "API-CATALOG")
        if body is None:
            print("\n-- %-24s FETCH FAILED: %s"
                  % (src.label, (prov or {}).get("verdict_reason", "?")))
            report[src.key] = {"ok": False, "reason": "fetch failed"}
            continue
        try:
            have = live_fields(body, src.platform)
        except Exception as e:                       # noqa: BLE001
            print("\n-- %-24s SCHEMA ERROR: %s" % (src.label, e))
            report[src.key] = {"ok": False, "reason": str(e)[:200]}
            continue

        missing = {}
        for slot, names in declared(src).items():
            gone = [n for n in names if n and n not in have]
            if gone:
                missing[slot] = gone
        status = "OK" if not missing else "FIELDS MISSING"
        print("\n-- %-24s %-16s %d live fields" % (src.label, status,
                                                  len(have)))
        for slot, gone in sorted(missing.items()):
            crit = slot in ("id_field", "issued_field")
            print("     %-18s %-34s %s" % (slot, ", ".join(gone),
                                           "CRITICAL" if crit else ""))
        if missing:
            # Show nearby names so the fix is a lookup, not a guess.
            print("     live field names: %s"
                  % ", ".join(sorted(have))[:600])
        report[src.key] = {"ok": not missing, "missing": missing,
                           "n_live_fields": len(have),
                           "live": sorted(have)}

    p = os.path.join(mf.OUT, "field_probe.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    ok = sum(1 for v in report.values() if v.get("ok"))
    print("\n%d/%d sources validated. requests spent: %d"
          % (ok, len(report), mf.spent()))
    print("wrote %s" % os.path.relpath(p, mf.ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
