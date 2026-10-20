# -*- coding: utf-8 -*-
"""Portal population: bring result pages a person saved in a browser into the
corpus, with the same manifest row a crawled page gets.

Some portals refuse the crawler (a bot challenge, or a plain 403 on Tyler's
hosting) or disallow it in robots.txt. The crawler's identity is not changed
to get past them. A person opens the portal in their own browser instead, runs
the pre-set search, and saves each result page with "Save page as > Webpage,
Complete", which writes the page as the browser shows it, after its scripts
ran. Dropping those portals instead would tilt the sample away from the
vendors that block, Tyler EnerGov among them.

Layout, one folder per portal, named by draw order:

    data/population/manual/0024_kyle_tx/
        notes.txt         the search that was run, filled in by hand
        p1.html .. p4.html
        p1.csv .. p4.csv  the portal's own export of each page, if it has one
        all.csv           an export of the whole search, if saved
        p1_files/ ..      saved alongside by the browser; ignored

Each page is copied to data/population/corpus/pages/ and gets a manifest row:
request_method BROWSER, robots_ok empty (a person browsing is not a crawler),
fetched_at the file's save time, and capture's own verdict. Each export is
copied to data/population/corpus/exports/ with a row in exports.csv: its row
count, and for a page's export how many of its permit numbers are on the saved
page and whether they appear in the same order. An export is the reference
where there is one, so a page whose export does not line up with it is caught
here, before anything is scored. A file already imported is skipped, so
re-running after more folders are filled imports only the new ones.

Usage:
    python spikes/population_import.py
"""
import csv
import datetime
import glob
import hashlib
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import capture                    # noqa: E402
from permits import fingerprint as fp          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, "data", "population", "manual")
# Chrome and Edge mark a page saved as "Webpage, Complete" with its address.
SAVED_FROM = re.compile(r"<!--\s*saved from url=\(\d+\)(\S+?)\s*-->")
EXPORT = re.compile(r"^(p[0-9]|all)\.csv$")
EXPORT_FIELDS = ["file", "order", "export", "rows", "id_column", "on_page",
                 "in_order", "sha256", "saved_at"]
# The export column that holds the permit number: EnerGov's "Case Number",
# Accela's "Record Number", or a plain "Permit #".
ID_HEADER = re.compile(r"(?i)\b(case|record|permit|application)\s*(number|no\.?|#|id)\b")


def notes(folder):
    out = {}
    path = os.path.join(folder, "notes.txt")
    if os.path.exists(path):
        for line in io.open(path, encoding="utf-8"):
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def exports(folder, order):
    """Copy a portal's exports into the corpus, one index row each."""
    index = os.path.join(capture.OUT, "exports.csv")
    have = set()
    if os.path.exists(index):
        with io.open(index, newline="", encoding="utf-8") as fh:
            have = {r["file"] for r in csv.DictReader(fh)}
    out_dir = os.path.join(capture.OUT, "exports")
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        name = os.path.basename(path)
        fn = "man_%04d_%s" % (order, name)
        if not EXPORT.match(name) or fn in have:
            continue
        raw = open(path, "rb").read()
        with io.open(path, newline="", encoding="utf-8-sig",
                     errors="replace") as fh:
            rows = list(csv.reader(fh))
        header, body = rows[0], [r for r in rows[1:] if any(r)]
        col = next((i for i, h in enumerate(header) if ID_HEADER.search(h)), 0)
        on_page = in_order = ""
        page = os.path.join(folder, name[:-4] + ".html")
        if os.path.exists(page):
            text = open(page, encoding="utf-8", errors="replace").read()
            at = [text.find(r[col]) for r in body if r[col]]
            found = [i for i in at if i >= 0]
            on_page = len(found)
            in_order = "yes" if found == sorted(found) else "no"
        row = {"file": fn, "order": order, "export": name[:-4],
               "rows": len(body), "id_column": header[col],
               "on_page": on_page, "in_order": in_order,
               "sha256": hashlib.sha256(raw).hexdigest(),
               "saved_at": datetime.datetime.fromtimestamp(
                   os.path.getmtime(path), datetime.timezone.utc).strftime(
                       "%Y-%m-%dT%H:%M:%SZ")}
        os.makedirs(out_dir, exist_ok=True)
        new = not os.path.exists(index)
        with io.open(index, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        with open(os.path.join(out_dir, fn), "wb") as fh:
            fh.write(raw)
        print("  %-8s %-22s %4d rows  %s" % (
            "EXPORT", fn, len(body), "" if on_page == "" else
            "%d of %d on the page, in order: %s" % (on_page, len(body), in_order)))


def main():
    capture.retarget(os.path.join("population", "corpus"))
    have = set()
    if os.path.exists(capture.MANIFEST):
        have = {r["file"] for r in csv.DictReader(
            io.open(capture.MANIFEST, encoding="utf-8"))}
    for folder in sorted(glob.glob(os.path.join(MANUAL, "[0-9]" * 4 + "_*"))):
        order = int(os.path.basename(folder)[:4])
        info = notes(folder)
        pages = sorted(glob.glob(os.path.join(folder, "p[0-9].html")))
        print("%s: %d pages, outcome %r" % (os.path.basename(folder),
                                             len(pages), info.get("outcome")))
        for path in pages:
            n = os.path.basename(path)[1:-5]
            fn = "man_%04d_p%s.html" % (order, n)
            if fn in have:
                continue
            raw = open(path, "rb").read()
            html = raw.decode("utf-8", "replace")
            m = SAVED_FROM.search(html[:2000])
            url = m.group(1) if m else info.get("search_url", "")
            verdict, reason = capture.verify("T-INDEX", html, 200)
            row = capture._row(url, url, 200, "text/html", len(raw),
                               hashlib.sha256(raw).hexdigest(),
                               "pop%04d" % order, info.get("vendor", ""),
                               "T-INDEX", verdict, reason, "BROWSER", "", fn,
                               fp.fingerprint(html).mark())
            row["fetched_at"] = datetime.datetime.fromtimestamp(
                os.path.getmtime(path), datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
            # Row first, then the page, as capture.fetch does: a page on disk
            # without a row is the failure the manifest exists to prevent.
            capture._write(row)
            with open(os.path.join(capture.PAGES, fn), "wb") as fh:
                fh.write(raw)
            print("  %-8s %-22s %7dB  %s" % (verdict.upper(), fn, len(raw),
                                              reason))
        exports(folder, order)


if __name__ == "__main__":
    main()
