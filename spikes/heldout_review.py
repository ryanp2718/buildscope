# -*- coding: utf-8 -*-
"""Held-out targets: the sheet for hand-checking the reference.

The adapter's parse of a page is the reference every model is scored against,
so on a held-out target it has to be checked before a single draw is scored.
This writes one CSV per target, one row per record, carrying exactly the
fields the scorer compares (the target's `roles`), in page order. Open each
page named in the `file` column in a browser, read the grid, and mark `ok`
y or n per row, with a note on any n.

Writing the sheet needs no network: it reads the manifest and the saved
pages. `--summary` reads the sheets back and says what is left to check.

Usage:
    python spikes/heldout_review.py                 # write sheets
    python spikes/heldout_review.py --check         # adapter vs a second parse
    python spikes/heldout_review.py --pages         # script-free copies to open
    python spikes/heldout_review.py --summary       # progress and problems
"""
import csv
import io
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import conformance as cf                             # noqa: E402

OUT = os.path.join(cf.ROOT, "data", "step1", "heldout_review")
ORDER = ["native_id", "issued_date", "permit_type", "status", "address",
         "structure_code", "contractor"]


def sheet_path(key):
    return os.path.join(OUT, "%s.csv" % key)


def write(target):
    pages = cf.corpus(target)
    if not pages:
        print("%-14s no pages in the manifest yet" % target.key)
        return
    path = sheet_path(target.key)
    if os.path.exists(path):
        # A sheet may already carry someone's marks. Never overwrite it.
        print("%-14s %s exists; left as is" % (target.key,
                                              os.path.relpath(path, cf.ROOT)))
        return
    roles = [r for r in ORDER if r in target.roles]
    n = 0
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "row"] + roles + ["ok", "note"])
        for fn, p in pages:
            for i, rec in enumerate(target.reference(cf.read(p)), 1):
                w.writerow([fn, i] + [rec.get(target.roles[r]) or ""
                                      for r in roles] + ["", ""])
                n += 1
    print("%-14s %d records over %d pages -> %s"
          % (target.key, n, len(pages), os.path.relpath(path, cf.ROOT)))


def summary(target):
    path = sheet_path(target.key)
    if not os.path.exists(path):
        print("%-14s no sheet" % target.key)
        return
    rows = list(csv.DictReader(io.open(path, encoding="utf-8")))
    marks = [r["ok"].strip().lower() for r in rows]
    bad = [r for r in rows if r["ok"].strip().lower() == "n"]
    print("%-14s %d records: %d y, %d n, %d unchecked"
          % (target.key, len(rows), marks.count("y"), len(bad),
             len(rows) - marks.count("y") - len(bad)))
    for r in bad:
        print("    %s row %s  %s  %s"
              % (r["file"], r["row"], r["native_id"], r["note"]))


# ------------------------------------------------ a second, independent parse
# Differential testing: a second implementation that shares no code with the
# adapter, compared record by record. The adapter selects rows by regex on
# the `ACA_TabRow_Odd/Even` class and assigns columns by header substring;
# this walks the DOM with the standard library's HTMLParser, takes every row
# of the grid table at its own nesting depth, and assigns columns by exact
# header text. Where both agree, a person need not compare the value by eye;
# where they disagree, a person decides which is right. Both being wrong the
# same way is what the semantic check in the review protocol is for.
GRID_ID = "gdvPermitList"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
HEADERS = {
    "native_id": {"record number", "permit number",
                  "permit/application number", "case number"},
    "issued_date": {"date", "opened"},
    "permit_type": {"record type", "permit type"},
    "status": {"status"},
    "address": {"address"},
}


# Grid rows that are not records on every Accela page seen: the counter and
# the pager. Anything else in the grid is reported.
EXPECTED_OTHER = re.compile(r"Showing \d+-\d+ of|< Prev\b")


def _hidden(attrs):
    a = dict(attrs)
    style = (a.get("style") or "").replace(" ", "").lower()
    return "display:none" in style or "hidden" in a


class Grid(HTMLParser):
    """Rows of the result grid: [{"cells": [(visible, hidden)], "th": bool,
    "link": bool}]."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.depth = 0          # table nesting depth inside the grid; 0 = out
        self.rows = []
        self.cell = None
        self.stack = []         # (tag, hidden) for open elements in a cell

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif GRID_ID in (dict(attrs).get("id") or ""):
                self.depth = 1
            return
        if not self.depth:
            return
        if self.depth == 1 and tag == "tr":
            self.rows.append({"cells": [], "th": False, "link": False})
            self.cell = None
        elif self.depth == 1 and tag in ("td", "th") and self.rows:
            self.cell = [[], []]
            self.rows[-1]["cells"].append(self.cell)
            self.rows[-1]["th"] |= tag == "th"
            self.stack = [(tag, _hidden(attrs))]
        elif self.cell is not None and tag not in VOID:
            self.stack.append((tag, _hidden(attrs)))
        if tag == "a" and "CapDetail" in (dict(attrs).get("href") or ""):
            if self.rows:
                self.rows[-1]["link"] = True

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            return
        if self.cell is None or tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if not self.stack:
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            hidden = any(h for _, h in self.stack)
            self.cell[1 if hidden else 0].append(data)


def _join(parts):
    return cf.norm(" ".join(parts))


def independent(html):
    """(records, other_rows, hidden) from the grid, by exact header text."""
    g = Grid()
    g.feed(html)
    head = next((r for r in g.rows if r["th"]), None)
    if head is None:
        raise ValueError("no header row in the grid")
    labels = [(_join(v) or "").lower() for v, _h in head["cells"]]
    col = {}
    for role, names in HEADERS.items():
        hits = [i for i, lab in enumerate(labels) if lab in names]
        if len(hits) == 1:
            col[role] = hits[0]
    recs, other, hidden = [], [], []
    for r in g.rows:
        if r is head or r["th"]:
            continue
        if len(r["cells"]) != len(labels):
            text = " | ".join(filter(None, (_join(v) for v, _h in r["cells"])))
            if text:
                other.append(text)
            continue
        rec = {role: _join(r["cells"][i][0]) for role, i in col.items()}
        rec["_link"] = r["link"]
        recs.append(rec)
        for i, (_v, h) in enumerate(r["cells"]):
            if _join(h):
                hidden.append((rec.get("native_id"), labels[i], _join(h)))
    return recs, other, hidden, labels, col


def check(target):
    """Compare adapter and independent parse; print what a person must see."""
    print("\n=== %s" % target.key)
    n_agree = n_fields = 0
    for fn, p in cf.corpus(target):
        html = cf.read(p)
        ref = target.reference(html)
        ind, other, hidden, labels, col = independent(html)
        issues = []
        missing = [r for r in HEADERS if r in target.roles and r not in col]
        if missing:
            issues.append("no unique header for %s in %s" % (missing, labels))
        if len(ref) != len(ind):
            issues.append("row count: adapter %d, independent %d"
                          % (len(ref), len(ind)))
        for i, (a, b) in enumerate(zip(ref, ind, strict=False), 1):
            for role in (r for r in ORDER if r in target.roles):
                if role not in col:
                    continue
                n_fields += 1
                va, vb = cf.norm(a.get(target.roles[role])), b.get(role)
                if va == vb:
                    n_agree += 1
                else:
                    issues.append("row %d %s: adapter %r, independent %r"
                                  % (i, role, va, vb))
        for t in other:
            if not EXPECTED_OTHER.match(t):
                issues.append("non-record row in grid: %s" % t[:100])
        for nid, lab, h in hidden:
            issues.append("hidden text in %s / %s: %r" % (nid, lab, h[:80]))
        unlinked = sum(1 for b in ind if not b["_link"])
        print("  %-40s %2d rows, %d without a detail link%s"
              % (fn, len(ind), unlinked, "" if issues else ", agree"))
        for s in issues:
            print("      " + s)
    print("  fields agreeing: %d of %d" % (n_agree, n_fields))


# ------------------------------------------------------------ review copies
BANNER = """<div style="position:sticky;top:0;z-index:9999;background:#ffd;
border-bottom:2px solid #c90;padding:6px 10px;font:14px sans-serif">
REVIEW COPY: %s &middot; target %s &middot; scripts removed; grid rows are
numbered to match the sheet's <b>row</b> column.</div>
<style>table[id$="%s"]{counter-reset:r}
table[id$="%s"] tr[class*="TabRow_Odd"],table[id$="%s"] tr[class*="TabRow_Even"]
{counter-increment:r}
table[id$="%s"] tr[class*="TabRow_Odd"]>td:first-child::before,
table[id$="%s"] tr[class*="TabRow_Even"]>td:first-child::before
{content:counter(r);font:bold 13px sans-serif;background:#c90;color:#fff;
padding:1px 5px;margin-right:4px}</style>
"""


def copies(target):
    """Script-free copies of each page, to open in a browser.

    Scripts go because a saved Accela page runs its JavaScript against a
    file:// origin and can rewrite or hide the grid. A `<base>` pointing at
    the portal lets the stylesheets load, so hidden columns stay hidden as
    they are on the live site; that is the only network the copy makes.
    """
    rows = {r["file"]: r for r in csv.DictReader(
        io.open(cf.MANIFEST, encoding="utf-8"))}
    d = os.path.join(OUT, "pages")
    if not os.path.isdir(d):
        os.makedirs(d)
    for fn, p in cf.corpus(target):
        html = re.sub(r"(?is)<script\b.*?</script>", "", cf.read(p))
        url = rows[fn]["final_url"] or rows[fn]["url"]
        base = '<base href="%s">' % url.rsplit("/", 1)[0].replace('"', "")
        html = re.sub(r"(?i)<head[^>]*>", lambda m: m.group(0) + base, html,
                      count=1)
        banner = BANNER % ((fn, target.key) + (GRID_ID,) * 5)
        html = re.sub(r"(?i)<body[^>]*>", lambda m: m.group(0) + banner, html,
                      count=1)
        with io.open(os.path.join(d, fn), "w", encoding="utf-8") as fh:
            fh.write(html)
    print("%-14s review copies -> %s" % (target.key, os.path.relpath(d, cf.ROOT)))


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    held = [t for t in cf.TARGETS.values() if t.split == "test"]
    mode = next((a for a in sys.argv[1:] if a.startswith("--")), None)
    for t in held:
        {"--summary": summary, "--check": check,
         "--pages": copies}.get(mode, write)(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
