# -*- coding: utf-8 -*-
"""Measure the token cost of a real portal page, raw and stripped.

Section 6 of DESIGN.md prices every inference call off two constants:

    PAGE = 3000      # one permit page AFTER stripping (~30k raw)

Both are `[F]`. They are also the terms the whole cost model is most sensitive
to - price per token is quoted by vendors and is the *least* uncertain input,
while tokens per page is a guess that multiplies straight through every figure
in the section. Lever 4 ("do not send raw HTML - routinely an order-of-magnitude
reduction") has never been checked against a municipal portal page either.

There are 37 real pages in the raw store already. This measures them. No HTTP,
no model calls.

On the token estimate: there is no tokenizer here and adding a dependency to
check an order of magnitude is not worth it. Plain English runs ~4 chars/token
on a BPE vocabulary; HTML is denser in punctuation and runs nearer 3. Both
bounds are printed and the wider one is the one to quote. This is deliberately
an estimate with its range shown rather than a precise-looking single number.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import strip as _strip                          # noqa: E402

# [2026-09-21] The stripper moved to `permits/strip.py`. It is library code -
# `permits/infer.py`'s call path needs it too, and a second copy would have
# been a second copy of a bug. What stays here is the measurement.
#
# **This script keeps the ORIGINAL keep-list on purpose.** The default one
# gained `class`, because dropping it deleted every row marker from an Accela
# grid; but the token figures this script published were measured without it,
# and silently re-deriving a published figure under changed inputs is the
# re-quoting failure `docs/evidence/README.md` exists to prevent. To see the
# cost of the new default, run with `--keep-class`.
KEEP_ATTR = _strip.LEGACY_KEEP
VIEWSTATE = _strip.VIEWSTATE
viewstate_bytes = _strip.viewstate_bytes


def levels(html, keep=KEEP_ATTR):
    return _strip.levels(html, keep)


def tok(n):
    return "%6.1fk-%.1fk" % (n / 3000.0, n / 4000.0)


def classify(fn, html):
    """A JSON API response and an ASP.NET portal page are not the same animal.

    The first pass of this script averaged them together and a single 16 MB
    ArcGIS Hub catalogue response moved the mean per-page figure by 30x. Mean
    over a heavy-tailed mixture is not a summary, it is an artifact - the same
    failure the Measurement A analyzer hit with a concealed bimodal median.
    """
    h = html.lstrip()[:1]
    if h in "{[":
        return "json-api"
    if re.search(r"__VIEWSTATE", html):
        det = re.search(r"detail|CapDetail", fn, re.I)
        return "accela-detail (per-record)" if det else "accela-index/search"
    return "html-other"


def stats(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2], sum(v) / float(n), v[0], v[-1]


def main():
    dirs = [os.path.join(ROOT, "data", "measure", "pages"),
            os.path.join(ROOT, "data", "spike_b", "pages"),
            os.path.join(ROOT, "data", "spike_a", "pages")]
    files = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith((".html", ".htm")):
                files.append(os.path.join(d, fn))
    if not files:
        raise SystemExit("no stored pages found")

    LV = ("raw", "no-js/css", "attrs-stripped", "text-only")
    by = {}
    vs_tot = vs_n = 0
    raw_tot = 0
    for p in files:
        html = io.open(p, encoding="utf-8", errors="replace").read()
        L = levels(html)
        c = classify(os.path.basename(p), html)
        by.setdefault(c, {k: [] for k in LV})
        for k in LV:
            by[c][k].append(len(L[k]))
        v = viewstate_bytes(html)
        raw_tot += len(html)
        if v:
            vs_tot += v
            vs_n += 1

    print("=" * 92)
    print("TOKEN COST OF A REAL PORTAL PAGE  (n=%d stored pages, no HTTP, no "
          "model calls)" % len(files))
    print("=" * 92)
    print("Medians, because the corpus is heavy-tailed. Tokens estimated at "
          "3-4 chars/token;\nno tokenizer here, so the range is the honest "
          "form and the wider bound is the one to quote.\n")

    for c in sorted(by):
        n = len(by[c]["raw"])
        print("-- %s  (n=%d)" % (c, n))
        print("   %-16s %11s %11s %16s %8s" %
              ("level", "med chars", "mean", "est. tokens (med)", "vs raw"))
        basem = stats(by[c]["raw"])[0]
        for k in LV:
            med, mean, lo, hi = stats(by[c][k])
            print("   %-16s %11.0f %11.0f %16s %7.2fx" %
                  (k, med, mean, tok(med).strip(), basem / med if med else 0))
        print()

    print("=" * 92)
    key = "accela-index/search"
    if key in by:
        med = stats(by[key]["attrs-stripped"])[0]
        rawmed = stats(by[key]["raw"])[0]
        print("DESIGN.md section 6 assumes PAGE = 3000 tokens stripped, ~30k raw.")
        print("An Accela index page measures %s tokens stripped, %s raw."
              % (tok(med).strip(), tok(rawmed).strip()))
    if "accela-detail (per-record)" in by:
        med = stats(by["accela-detail (per-record)"]["attrs-stripped"])[0]
        rawmed = stats(by["accela-detail (per-record)"]["raw"])[0]
        print("An Accela DETAIL page - the one a per-record call would read -")
        print("measures %s tokens stripped, %s raw."
              % (tok(med).strip(), tok(rawmed).strip()))
    if vs_tot:
        print("\n__VIEWSTATE and friends: %.0f KB across %d pages, %.1f%% of all "
              "raw bytes stored." % (vs_tot / 1024.0, vs_n,
                                     100.0 * vs_tot / raw_tot))
        print("A base64 blob required to POST the next request, carrying no "
              "permit data at all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
