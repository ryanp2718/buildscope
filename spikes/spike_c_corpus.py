# -*- coding: utf-8 -*-
"""Build a TRUSTED page corpus for Spike C, and say what was dropped and why.

Spike A saved every page it fetched, including pages its own verifier later
rejected. Three of the saved `*_home.html` files are not municipal sites at
all - an iron castings foundry, a C-suite media network, and a bot-check
interstitial - because the URL-pattern probe had a 75% false-positive rate and
the rejects were written to disk alongside the hits.

Fingerprinting a corpus that contains a foundry's website answers no question
anyone asked, so the corpus is filtered here rather than inside the analysis,
and the manifest is written out so the filtering itself can be audited.

Rules, in order of how much they drop:
  1. `*_home.html` is kept only for jurisdictions the Spike A verifier passed
     (`probe.json` -> verified == true). 21 of 28 pattern hits failed.
  2. Pages whose <title> marks them as non-content - interstitials, 403/404,
     "just a moment", "authentication required" - are dropped. A Cloudflare
     challenge page has a real DOM and would cluster with other challenge
     pages, which would be a finding about Cloudflare, not about permits.
  3. Pages from third-party aggregator hosts are dropped; they are not the
     jurisdiction's own rendering.
  4. Pages with fewer than 15 unique root-to-leaf paths are dropped as
     degenerate - too little structure to fingerprint meaningfully.
  5. Jurisdictions recorded `unresolved` in the classification are dropped
     entirely; Spike A declined to say what their portal is, so neither can this.
"""
import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spike_c_fingerprint import fingerprint, state_of  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPIKE = os.path.join(ROOT, "data", "spike_a")
CORPORA = [os.path.join(SPIKE, "html"), os.path.join(SPIKE, "html_tier2")]
MANIFEST = os.path.join(SPIKE, "spike_c_corpus.csv")

NON_CONTENT = re.compile(
    r"(just a moment|checking your browser|attention required|"
    r"authentication required|access denied|forbidden|"
    r"\b404\b|page not found|page/url requested wasn.t found|"
    r"error|are you a robot|verify you are human)", re.I)
AGGREGATOR = re.compile(
    r"(citydirectory|permitsearch|countypermit|building-permits\.net|"
    r"code-enforcement\.org|building-codes\.org|211helpline|yellowpages)", re.I)
MIN_PATHS = 15


def title_of(html):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not m:
        return ""
    return " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split())


def verified_states():
    p = json.load(io.open(os.path.join(SPIKE, "probe.json"), encoding="utf-8"))
    out = set()
    for k, v in p.items():
        if v.get("verified"):
            out.add(k.split("|")[0])
    return out


def unresolved_states():
    out = set()
    for r in csv.DictReader(io.open(os.path.join(SPIKE, "classification.csv"),
                                    newline="", encoding="utf-8")):
        if r["bucket"] == "unresolved":
            out.add(r["state"])
    return out


def main():
    ver, unres = verified_states(), unresolved_states()
    rows, kept = [], 0
    for d in CORPORA:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".html"):
                continue
            path = os.path.join(d, name)
            html = io.open(path, encoding="utf-8", errors="replace").read()
            base = name[:-5]
            st = state_of(base)
            title = title_of(html)
            _, pset, _, _ = fingerprint(html)

            drop = None
            if st is None:
                drop = "no state key"
            elif st in unres:
                drop = "jurisdiction unresolved in Spike A"
            elif base.endswith("_home") and st not in ver:
                drop = "pattern-probe hit that Spike A's verifier REJECTED"
            elif NON_CONTENT.search(title):
                drop = "non-content page: %s" % title[:40]
            elif AGGREGATOR.search(base) or AGGREGATOR.search(title):
                drop = "third-party aggregator, not the jurisdiction"
            elif len(pset) < MIN_PATHS:
                drop = "degenerate: %d unique paths" % len(pset)
            else:
                kept += 1
            rows.append({"file": name, "dir": os.path.basename(d), "state": st or "",
                             "title": title[:70], "paths": len(pset),
                             "keep": "" if drop else "Y", "drop_reason": drop or ""})

    with io.open(MANIFEST, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "dir", "state", "title",
                                          "paths", "keep", "drop_reason"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print("SPIKE C CORPUS FILTER")
    print("  pages seen   : %d" % len(rows))
    print("  pages kept   : %d" % kept)
    print("  pages dropped: %d" % (len(rows) - kept))
    reasons = {}
    for r in rows:
        if r["drop_reason"]:
            key = r["drop_reason"].split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    print("\n  DROPPED BY REASON")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("    %-50s %3d" % (k, v))
    print("\n  KEPT JURISDICTIONS: %d"
          % len({r["state"] for r in rows if r["keep"]}))
    print("\n  examples of what was dropped as not-a-municipal-site:")
    for r in rows:
        if "REJECTED" in r["drop_reason"] and r["title"]:
            print("    %-34s %s" % (r["file"][:34], r["title"][:44]))
    print("\nwrote %s" % os.path.relpath(MANIFEST, ROOT))


if __name__ == "__main__":
    main()
