# -*- coding: utf-8 -*-
"""Spike C: structural template collision over the HTML Spike A saved.

D8 claims that keying the extractor cache on DOM structure rather than domain
"collapses the amortization denominator from ~20,000 sites to plausibly a few
hundred distinct vendor templates". Every cost figure in DESIGN.md section 6
rests on it and nothing had tested it.

Fingerprint, per the protocol in DESIGN.md:
  1. normalized DOM skeleton - all text, attribute VALUES and ids stripped
  2. shingle over root-to-leaf tag paths
  3. hash

Two numbers are reported for every corpus, and the gap between them is the
point:

  * EXACT  - sha1 over the sorted unique path set. Brittle by construction: one
             extra menu item in a shared template mints a new fingerprint, so
             this is a LOWER bound on collapse.
  * JACCARD- single-linkage clustering on path-set overlap at several
             thresholds. This is what a real structure-keyed cache would do,
             and the threshold sensitivity IS the finding rather than noise
             around it.

Offline. No fetching. Stdlib only.
"""
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SPIKE = os.path.join(ROOT, "data", "spike_a")
CORPORA = [os.path.join(SPIKE, "html"), os.path.join(SPIKE, "html_tier2")]
CLS = os.path.join(SPIKE, "classification.csv")
OUT = os.path.join(SPIKE, "spike_c_fingerprints.json")

# ---------------------------------------------------------------------------
# The fingerprint itself now lives in `permits/fingerprint.py` - section 9,
# obligation 3. It was lifted there unchanged and verified to reproduce this
# file's hashes on all 137 pages of the Spike A and Measurement A/B corpora
# before this delegation was written, so every number in the Spike C report
# still reproduces from this script.
#
# `fingerprint` is bound to `raw`, which keeps the pre-lift 4-tuple shape
# (hash, paths, n_paths, n_nodes) that this script and `measure_analyze.py`
# unpack positionally.
# ---------------------------------------------------------------------------
from permits.fingerprint import (                       # noqa: E402
    Skeleton, cluster, jaccard, raw as fingerprint, OPAQUE, THRESHOLDS, VOID)

# Page-type classification stays here. It is a Spike C question about what a
# saved page *is*, not a property of the fingerprint, and lifting it alongside
# the skeleton would have put a spike's labelling heuristic into the library.
RESULTLIST = re.compile(
    r"(divSearchResultList|record results|showing\s*\d+\s*-\s*\d+)", re.I)

labels_by_state = {}


def load_labels():
    """state FIPS -> classification row. One place per state in this sample."""
    rows = list(csv.DictReader(io.open(CLS, newline="", encoding="utf-8")))
    states = [r["state"] for r in rows]
    assert len(set(states)) == len(rows), (
        "state FIPS is not unique across the sample (%d rows, %d states); "
        "the jurisdiction key must change" % (len(rows), len(set(states))))
    labels_by_state.update((r["state"], r) for r in rows)
    return labels_by_state


ABBR = {
    "al": "01", "ak": "02", "ar": "05", "ca": "06", "co": "08", "fl": "12",
    "ga": "13", "ia": "19", "in": "18", "ky": "21", "la": "22", "me": "23",
    "mi": "26", "mn": "27", "mo": "29", "ne": "31", "nj": "34", "ny": "36",
    "nv": "32", "or": "41", "pa": "42", "sc": "45", "tx": "48", "ut": "49",
    "vt": "50", "va": "51", "wa": "53", "wi": "55",
}
# query/form pages are named after the portal, not the place
QMAP = {"clarkco": "32", "oregon": "41", "yakimaco": "53",
        "stjohns": "12", "stlouis": "29"}


def state_of(base):
    """Recover the state FIPS from any of the filename conventions in use.

    The Spike A draw landed exactly one place per state, so state FIPS is a
    unique jurisdiction key here. asserted in main().
    """
    b = base.lower()
    m = re.match(r"^(?:portal|depth)_(\d\d)[_\b]", b) or re.match(r"^(\d\d)_\d+_", b)
    if m:
        return m.group(1)
    m = re.match(r"^([a-z]{2})_", b)
    if m and m.group(1) in ABBR:
        return ABBR[m.group(1)]
    for k, v in QMAP.items():
        if k in b:
            return v
    return None


def classify(name, html, labels):
    """-> (jurisdiction key, page class, vendor, stratum)"""
    base = name[:-5] if name.endswith(".html") else name
    st = state_of(base)

    if base.startswith(("q_", "final_")):
        cls = "result_index" if RESULTLIST.search(html) else "search_form"
    elif base.startswith("portal_"):
        cls = "portal"
    else:
        cls = "site"

    row = labels_by_state.get(st) if st else None
    juris = "%s %s" % (st, (row or {}).get("place_name", "?")) if st else base
    return juris, cls, (row or {}).get("vendor", "unknown"), \
        (row or {}).get("stratum", "unknown")


def report(title, items, fps, sets, note=""):
    print("\n" + "=" * 78)
    print(title)
    if note:
        print(note)
    print("=" * 78)
    jur = sorted(set(i["juris"] for i in items))
    if not jur:
        print("  (empty corpus)")
        return {}
    # one representative page per jurisdiction: the largest, to avoid counting
    # a jurisdiction twice for having two pages saved
    pick = {}
    for i in items:
        j = i["juris"]
        if j not in pick or i["paths"] > pick[j]["paths"]:
            pick[j] = i
    keys = sorted(pick)
    exact = set(pick[k]["fp"] for k in keys)
    print("  jurisdictions=%d  pages=%d  distinct EXACT fingerprints=%d"
          % (len(keys), len(items), len(exact)))
    print("  EXACT fingerprints / jurisdictions = %.2f" % (len(exact) / float(len(keys))))

    res = {"jurisdictions": len(keys), "pages": len(items),
           "exact_fingerprints": len(exact),
           "exact_ratio": len(exact) / float(len(keys)), "thresholds": {}}

    print("\n  %-10s %-8s %-8s %-9s %s" % ("jaccard", "clusters", "ratio",
                                           "median", "cluster sizes"))
    setmap = {k: pick[k]["set"] for k in keys}
    for t in THRESHOLDS:
        cl = cluster(keys, setmap, t)
        sizes = sorted((len(c) for c in cl), reverse=True)
        med = sizes[len(sizes) // 2]
        ratio = len(cl) / float(len(keys))
        print("  >=%-8.2f %-8d %-8.2f %-9d %s"
              % (t, len(cl), ratio, med,
                 " ".join(str(s) for s in sizes[:14])))
        res["thresholds"][str(t)] = {"clusters": len(cl), "ratio": ratio,
                                     "median_cluster": med, "sizes": sizes}
    return res


def vendor_crosstab(items):
    print("\n" + "-" * 78)
    print("VENDOR CROSS-TAB  - the deciding cell is same-vendor / different-fingerprint")
    print("-" * 78)
    pick = {}
    for i in items:
        j = i["juris"]
        if j not in pick or i["paths"] > pick[j]["paths"]:
            pick[j] = i
    by_v = defaultdict(list)
    for i in pick.values():
        by_v[i["vendor"]].append(i)
    print("  %-30s %5s %6s %8s  %s" % ("vendor", "juris", "distinct", "ratio", "verdict"))
    out = {}
    for v, rows in sorted(by_v.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < 2:
            continue
        fps = set(r["fp"] for r in rows)
        keys = [r["juris"] for r in rows]
        sm = {r["juris"]: r["set"] for r in rows}
        cl80 = len(cluster(keys, sm, 0.80))
        verdict = ("collapses" if cl80 == 1 else
                   "partial" if cl80 < len(rows) else "NO collapse")
        print("  %-30s %5d %6d %8.2f  %s (at J>=0.80: %d clusters)"
              % (v[:30], len(rows), len(fps), len(fps) / float(len(rows)),
                 verdict, cl80))
        out[v] = {"jurisdictions": len(rows), "exact": len(fps),
                  "clusters_at_080": cl80}
    if not out:
        print("  (no vendor appears at 2+ jurisdictions in this corpus)")
    return out


def trusted():
    """Files the corpus filter kept. Absent manifest -> run spike_c_corpus.py."""
    man = os.path.join(SPIKE, "spike_c_corpus.csv")
    if not os.path.exists(man):
        raise SystemExit("run scripts/spike_c_corpus.py first - it builds the "
                         "trusted-page manifest this analysis reads")
    keep = {}
    for r in csv.DictReader(io.open(man, newline="", encoding="utf-8")):
        if r["keep"] == "Y":
            keep[(r["dir"], r["file"])] = r
    return keep


def main():
    labels = load_labels()
    keep = trusted()
    items = []
    for d in CORPORA:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".html"):
                continue
            if (os.path.basename(d), name) not in keep:
                continue
            html = io.open(os.path.join(d, name), encoding="utf-8",
                           errors="replace").read()
            fp, s, npaths, nodes = fingerprint(html)
            juris, cls, vendor, stratum = classify(name, html, labels)
            items.append(dict(file=name, dir=os.path.basename(d), juris=juris,
                              cls=cls, vendor=vendor, stratum=stratum, fp=fp,
                              set=s, paths=npaths, nodes=nodes, bytes=len(html)))

    unmapped = [i["file"] for i in items if i["stratum"] == "unknown"]
    print("SPIKE C - TEMPLATE COLLISION   TRUSTED corpus: %d pages, %.1f MB"
          % (len(items), sum(i["bytes"] for i in items) / 1e6))
    print("unmapped files (excluded, would otherwise inflate the ratio): %d%s"
          % (len(unmapped), "  " + ", ".join(unmapped[:6]) if unmapped else ""))
    items = [i for i in items if i["stratum"] != "unknown"]
    print("\nPAGE CLASS INVENTORY")
    cc = Counter(i["cls"] for i in items)
    for c, n in cc.most_common():
        print("  %-14s %3d" % (c, n))
    print("\n  NOTE: the protocol asks for index pages and DETAIL pages fingerprinted")
    print("  separately. This corpus contains %d result-index pages and NO detail"
          % cc.get("result_index", 0))
    print("  pages - Spike A never fetched an individual permit record. See the")
    print("  evidence report for what that does and does not allow.")

    res = {"inventory": dict(cc)}

    site = [i for i in items if i["cls"] == "site"]
    res["municipal_sites"] = report(
        "A. MUNICIPAL WEBSITES (n jurisdictions)", site, None, None,
        note="Tests CMS-template collapse, NOT the D8 permit-page claim.")

    portal = [i for i in items if i["cls"] == "portal"]
    res["portals"] = report("B. PERMIT PORTAL LANDING PAGES", portal, None, None)

    idx = [i for i in items if i["cls"] == "result_index"]
    res["result_index"] = report(
        "C. PERMIT RESULT-INDEX PAGES  <-- closest thing to the D8 claim",
        idx, None, None,
        note="Tiny n. One-sided test only: divergence here is strong evidence\n"
             "against collapse; agreement is weak evidence for it.")

    for label, stratum in (("D. TIER-1 SITES", "tier1"), ("E. TIER-2 SITES", "tier2")):
        sub = [i for i in site if i["stratum"].startswith(stratum)]
        res[stratum] = report("%s" % label, sub, None, None)

    res["vendor_crosstab"] = vendor_crosstab(site + portal)

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1))
    print("\nwrote %s" % os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
