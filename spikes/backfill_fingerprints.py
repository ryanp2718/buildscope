# -*- coding: utf-8 -*-
"""Fingerprint every page already in the raw store, and migrate the manifests.

Section 9, obligation 3 asks for fingerprinting *at capture*, which
`permits/capture.py` now does. This handles the pages captured before it did.

Back-filling is legitimate here and it is worth being precise about why, since
this project refuses back-filled `observed_at` on exactly the same subject. A
fingerprint is a pure function of bytes that D1 holds immutable, so recomputing
it from the raw store gives the same answer it would have given at capture. A
transaction timestamp is not a function of the bytes - it is a fact about an
event that is over - and cannot be recovered from them at all. That asymmetry,
not convenience, is what makes one of these fine and the other forbidden.

What is *not* recoverable is a fingerprint for a page that was fetched and
never saved, or saved and since overwritten. Those are gone, and the count of
manifest rows with no readable file is reported rather than passed over.
"""
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from permits import fingerprint as fp                   # noqa: E402
from permits import capture as mf  # noqa: E402

TREES = ["measure", "spike_b", "step1"]


def run(tree):
    out = os.path.join(ROOT, "data", tree)
    manifest = os.path.join(out, "manifest.csv")
    pages = os.path.join(out, "pages")
    if not os.path.exists(manifest):
        return None
    with io.open(manifest, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    done = missing = already = nostruct = 0
    seen = {}
    for r in rows:
        if r.get("fp"):
            already += 1
            seen[r["fp"]] = seen.get(r["fp"], 0) + 1
            continue
        fn = r.get("file") or ""
        path = os.path.join(pages, fn)
        if not fn or not os.path.exists(path):
            missing += 1
            continue
        html = io.open(path, encoding="utf-8", errors="replace").read()
        mark = fp.fingerprint(html).mark()
        if not mark:
            nostruct += 1
            continue
        r["fp"] = mark
        seen[mark] = seen.get(mark, 0) + 1
        done += 1

    with io.open(manifest, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=mf.FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(dict((k, r.get(k, "")) for k in mf.FIELDS))

    print("  %-9s %4d rows  %4d fingerprinted  %3d already  %3d no saved file"
          "  %3d no DOM  -> %d distinct templates"
          % (tree, len(rows), done, already, missing, nostruct, len(seen)))
    return rows, seen


def main():
    print("BACK-FILL: structural fingerprints over the raw store "
          "(obligation 3)")
    allrows = []
    for t in TREES:
        got = run(t)
        if got:
            allrows.extend(got[0])

    # What the fingerprint is actually for: noticing that one source's pages
    # are not all the same template, and that two sources' are.
    bysrc = {}
    for r in allrows:
        if not r.get("fp"):
            continue
        k = (r.get("jurisdiction", ""), r.get("page_type", ""))
        bysrc.setdefault(k, set()).add(r["fp"])
    print("\n  templates per (jurisdiction, page_type), where > 1:")
    multi = sorted(((len(v), k) for k, v in bysrc.items()), reverse=True)
    for n, k in multi[:12]:
        if n > 1:
            print("     %-22s %-10s %d distinct" % (k[0][:22], k[1][:10], n))

    shared = {}
    for k, v in bysrc.items():
        for f_ in v:
            shared.setdefault(f_, set()).add(k[0])
    cross = {f_: j for f_, j in shared.items() if len(j) > 1}
    print("\n  fingerprints shared across jurisdictions: %d" % len(cross))
    for f_, j in sorted(cross.items(), key=lambda x: -len(x[1]))[:8]:
        print("     %-16s %s" % (f_, ", ".join(sorted(j))[:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
