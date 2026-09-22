# -*- coding: utf-8 -*-
"""Re-derive records from stored bytes, without touching the network.

This is what D1's raw retention is actually for. An adapter bug does not mean
a re-crawl: the bytes are on disk, each with a manifest row carrying its
sha256, so a corrected extractor can be replayed over them for free. The first
Clark County run emitted 20 records out of 371 because `build()` called a
milestone name that is not in D6's vocabulary; fixing the adapter and
replaying costs nothing and produces the same records the crawl would have.

It also enforces the D1 rule the capture layer exists for: pages are found by
reading the manifest, never by listing the directory. A page with no manifest
row is not input.

Usage: python scripts/step1_rebuild.py clarkco
"""
import csv
import io
import json
import os
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from permits import capture as mf  # noqa: E402
from permits import emit                            # noqa: E402
from permits.adapters import accela                 # noqa: E402
from permits.adapters import stjohns                # noqa: E402

# (source, adapter module). The adapter supplies `parse_index`, `build` and
# `vocabulary_for`, which is the whole interface a replay needs - so a second
# platform costs one line here rather than a second replay tool.
SOURCES = {
    "clarkco": (accela.AccelaSource(
        key="clarkco", state_fips="32", bps_id="021000",
        label="Clark County NV (unincorporated)",
        base="https://aca-prod.accela.com/clarkco"), accela),
    "stjohns": (stjohns.StJohnsSource(), stjohns),
}


def manifest_pages(key, page_type="T-INDEX"):
    """(file, sha256) for every usable page this source captured.

    Ordered by fetch time so a replay sees pages in the order the crawl did.
    `unknown` is included and `rejected` is not: a rejected page was judged
    unusable at capture and reversing that here would be exactly the
    downstream re-litigation D1 forbids.
    """
    rows = []
    with io.open(mf.MANIFEST, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["jurisdiction"] != key or r["page_type"] != page_type:
                continue
            if r["verdict"] == "rejected" or not r["file"]:
                continue
            rows.append(r)
    rows.sort(key=lambda r: r["fetched_at"])
    return rows


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "clarkco"
    mf.retarget("step1")
    src, ad = SOURCES[key]
    vb = ad.vocabulary_for(src)
    path = os.path.join(mf.OUT, "records", "%s.jsonl" % key)
    if os.path.exists(path):
        os.remove(path)
    em = emit.Emitter(path, src.source_id)

    rows = manifest_pages(key)
    print("replaying %d stored pages for %s (no network)" % (len(rows), src.label))
    seen = set()
    n_rows = n_emit = n_dup = n_noid = n_incomplete = 0
    types = collections.Counter()
    for r in rows:
        p = os.path.join(mf.PAGES, r["file"])
        if not os.path.exists(p):
            continue
        html = io.open(p, encoding="utf-8", errors="replace").read()
        if not ad.page_is_complete(html):
            n_incomplete += 1
            continue
        parsed = ad.parse_index(html)[0]
        for row in parsed:
            n_rows += 1
            num = row.get("number")
            if num in seen:
                n_dup += 1
                continue
            seen.add(num)
            try:
                rec = ad.build(src, row, vb, r["sha256"])
                em.emit(rec)
                types[(rec.native or {}).get("native_type")] += 1
                n_emit += 1
            except emit.MissingIdentifier:
                n_noid += 1
    alarm = em.close()

    print("  rows parsed %d | distinct %d | emitted %d | dup %d | no-id %d"
          % (n_rows, len(seen), n_emit, n_dup, n_noid))
    if n_incomplete:
        print("  %d stored page(s) skipped: the portal declared the result "
              "set truncated, so replaying them would inject an arbitrary "
              "slice of records belonging to no window" % n_incomplete)
    print("  null rates: %s" % ", ".join(
        "%s=%.0f%%" % (k, 100 * v) for k, v in sorted(alarm["rates"].items())))
    if alarm["by_bps_column"]:
        print("  countable units by BPS column: %s"
              % json.dumps(alarm["by_bps_column"]))
    for t in alarm["tripped"]:
        print("  *** DRIFT ALARM: %s" % t)

    sp = os.path.join(mf.OUT, "pull_summary.json")
    summary = json.load(io.open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    summary[key] = {"label": src.label, "state": src.state_fips,
                    "bps_id": src.bps_id, "alarm": alarm,
                    "rebuilt_from_stored_pages": len(rows) - n_incomplete,
                    "skipped_incomplete_pages": n_incomplete,
                    "native_types": dict(types.most_common()),
                    "vocab": vb.report()}
    json.dump(summary, io.open(sp, "w", encoding="utf-8"), indent=1, default=str)
    print("\nwrote %s and %s"
          % (os.path.relpath(path, mf.ROOT), os.path.relpath(sp, mf.ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
