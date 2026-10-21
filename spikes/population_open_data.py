# -*- coding: utf-8 -*-
"""Portal population, step 3: offices that publish their permits as open data.

An office that publishes its issued permits as a dataset needs no extractor:
a pipeline downloads it. New York City's DOB NOW finds one property at a time,
but the city publishes its approved permits as open data (owner's point,
2026-10-04). Without an outcome for that, such an office's units count as
uncovered, and coverage looks worse than a real pipeline would get.

An office counts as open data when its own government publishes, free and
without a login, a machine-readable dataset with one row per building permit
and an issue date, holding permits issued in August 2026 (the search rule's
window). Monthly totals and PDF reports do not count.

Two steps:

  --find   For each office in the sample, the data portals its own saved
           pages link to (population_links), plus any given as ORDER=HOST
           when the office's site can't be read and web search named one.
           Each portal is searched through its own catalog API for datasets
           about permits: Socrata, then CKAN, then ArcGIS Hub.
  --datagov  The second source, the same for every office: every dataset
           data.gov's catalog (which harvests city and county portals) returns
           for building or construction permits, matched to offices by the
           publisher's name.
           They write data/population/open_data_find.json and
           open_data_datagov.json; the datasets are reviewed by hand into
           data/population/open_data.csv.
  --check  For each dataset in open_data.csv (order, place, platform,
           dataset, query, date_field, found_by, note), its count query for
           permits issued in 2026-08: a URL written by hand per platform, or
           the file itself where only files may be fetched. A candidate turned
           down on review has no query and keeps its reason. Writes
           data/population/open_data.json.
  --match  For each tested office with a dataset, its rows for the permit
           numbers in the office's reference, compared field by field (MATCH).
           Writes data/population/open_data_match.json.

Same crawler as everything else: permits.capture, robots.txt honoured, the
crawler's identity sent, the host's pause kept.

Usage:
    python spikes/population_open_data.py --find [ORDER=HOST ...]
    python spikes/population_open_data.py --datagov [ORDER ...]
    python spikes/population_open_data.py --check
    python spikes/population_open_data.py --match   # the tested offices' references
"""
import csv
import datetime
import io
import json
import os
import re
import sys
import urllib.parse
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from permits import capture                    # noqa: E402

ROOT = os.path.dirname(HERE)
DIR = os.path.join(ROOT, "data", "population")
PAGES = os.path.join(DIR, "links", "pages")
PORTALS = os.path.join(DIR, "portals.csv")
FOUND = os.path.join(DIR, "open_data_find.json")
FOUND_DATAGOV = os.path.join(DIR, "open_data_datagov.json")
DATASETS = os.path.join(DIR, "open_data.csv")
OUT = os.path.join(DIR, "open_data.json")

BUDGET = 200

# --match: the second check of a reference that no model wrote. For each
# tested office whose government publishes its permits, the dataset's rows for
# the reference's permit numbers, and the fields both carry compared under a
# mapping written per dataset (pre-registration, "Open data, where the office
# publishes it"). Dates are compared as dates, an address as the dataset's
# street line at the start of the page's, the rest as text, case and spacing
# aside. Baltimore's and Tempe's portals list a record by the date it was
# opened and their datasets hold issued permits, so their dates are not
# compared and a record not yet issued is not in them. Austin's Sub Type / Work
# Type is its dataset's class and work class joined.
REFERENCE = os.path.join(DIR, "reference")
MATCH_OUT = os.path.join(DIR, "open_data_match.json")
MATCH = {
    "17": ("CaseNumber", {"address": "Address"}),
    "65": ("PermitNum", {"status": "StatusCurrent", "permit_type": "PermitTypeDesc"}),
    "190": ("permit_number", {"status": "status_current", "address": "original_address1",
                              "permit_type": ("permit_class", "work_class")}),
    "319": ("permitnumber", {"issued_date": "permitissuedate", "status": "status",
                             "address": "address", "permit_type": "permitdescription"}),
}

LINK = re.compile(r"(?is)<a\b[^>]*?href\s*=\s*[\"']([^\"'#][^\"']*)[\"'][^>]*>"
                  r"(.*?)</a>")
# A data portal's own address. A link to an "Open Data" page on the office's
# own site names no portal; those are given as ORDER=HOST.
DATA_HOST = re.compile(r"(?i)^(data|opendata|open-data)\.|\.opendata\.arcgis\.com$|"
                       r"\.hub\.arcgis\.com$|opendata\.com$")
NOT_DATA = re.compile(r"(?i)finance\.socrata|connect\.socrata|cleargov|mapgeo|"
                      r"dashboard|dallascitydata")
DATA_TEXT = re.compile(r"(?i)\bopen\s*data\b")
# Each platform's own catalog search, tried in turn.
# Socrata's catalog answers for every Socrata site unless told which one
# (Everett's returned Chicago's and Calgary's permits, 2026-10-04).
CATALOGS = [
    ("socrata", "https://{h}/api/catalog/v1?domains={h}&q=permits"
                "&only=datasets&limit=50"),
    ("ckan", "https://{h}/api/3/action/package_search?q=permits&rows=50"),
    ("arcgis_hub", "https://{h}/api/search/v1/collections/dataset/items"
                   "?q=permits&limit=50"),
]


def portal_hosts():
    """{order: {host}} for the data portals each office's saved pages link."""
    out = {}
    for f in os.listdir(PAGES):
        m = re.match(r"s(\d{4})_", f)
        if not m:
            continue
        key = str(int(m.group(1)))
        with open(os.path.join(PAGES, f), encoding="utf-8",
                  errors="replace") as fh:
            html = fh.read()
        for href, _ in LINK.findall(html):
            url = unescape(href).strip()
            host = urllib.parse.urlsplit(url).netloc.lower()
            if host and DATA_HOST.search(host) and not NOT_DATA.search(url):
                out.setdefault(key, set()).add(host)
    return out


def data_pages():
    """{order: {url}} for the pages on an office's own site that its saved
    pages link as "Open Data" (Durham's /4559/Open-Data-Portal): one hop
    further, those name the portal."""
    out = {}
    for f in os.listdir(PAGES):
        m = re.match(r"s(\d{4})_([^_]+)_", f)
        if not m:
            continue
        key, site = str(int(m.group(1))), m.group(2)
        with open(os.path.join(PAGES, f), encoding="utf-8",
                  errors="replace") as fh:
            html = fh.read()
        for href, text in LINK.findall(html):
            text = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", text))
            if not DATA_TEXT.search(text):
                continue
            url = urllib.parse.urljoin("https://%s/" % site,
                                       unescape(href).strip())
            host = urllib.parse.urlsplit(url).netloc.lower()
            if host.split(".", 1)[-1] == site.split(".", 1)[-1]:
                out.setdefault(key, set()).add(url)
    return out


def titles(platform, body):
    """(title, address) of each dataset a catalog answered with."""
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    if platform == "socrata" and isinstance(doc, dict) and "results" in doc:
        return [(r["resource"]["name"], r.get("link", ""))
                for r in doc["results"]]
    if platform == "ckan" and isinstance(doc, dict) and doc.get("success"):
        return [(p.get("title", ""), p.get("name", ""))
                for p in doc["result"]["results"]]
    if platform == "arcgis_hub" and isinstance(doc, dict) and "features" in doc:
        return [(f["properties"].get("title", ""),
                 f["properties"].get("url", "") or f.get("id", ""))
                for f in doc["features"]]
    return None


def find(extra):
    with open(PORTALS, newline="", encoding="utf-8") as fh:
        sample = {r["order"]: r for r in csv.DictReader(fh)}
    hosts = {k: v for k, v in portal_hosts().items() if k in sample}
    for pair in extra:
        key, host = pair.split("=", 1)
        hosts.setdefault(key, set()).add(host)
    done = {}
    if os.path.exists(FOUND):
        with open(FOUND, encoding="utf-8") as fh:
            done = json.load(fh)
    capture.retarget(os.path.join("population", "open_data"))
    capture.BUDGET = BUDGET
    op = capture._opener()
    # One hop from the office's own "Open Data" pages to the portal they name.
    for key, urls in sorted(data_pages().items(), key=lambda kv: int(kv[0])):
        if key not in sample:
            continue
        rec = done.setdefault(key, {"place": sample[key]["place"],
                                    "hosts": {}})
        seen = rec.setdefault("data_pages", {})
        for url in sorted(urls)[:2]:
            if url not in seen:
                name = "d%04d_%s" % (int(key), urllib.parse.urlsplit(url).netloc)
                body, row = capture.fetch(op, url, name, sample[key]["place"],
                                          "", "LANDING")
                # Denver's page redirects to the portal itself.
                landed = urllib.parse.urlsplit(row["final_url"]).netloc.lower()
                seen[url] = sorted({
                    urllib.parse.urlsplit(unescape(h)).netloc.lower()
                    for h, _ in LINK.findall(body or "")
                    if DATA_HOST.search(urllib.parse.urlsplit(
                        unescape(h)).netloc.lower())
                    and not NOT_DATA.search(h)}
                    | ({landed} if DATA_HOST.search(landed) else set()))
                print("-- %s %s  open data page %s: %s" % (
                    key, sample[key]["place"], url, seen[url] or "none"))
            hosts.setdefault(key, set()).update(seen[url])
    for key in sorted(hosts, key=int):
        rec = done.setdefault(key, {"place": sample[key]["place"],
                                    "hosts": {}})
        for host in sorted(hosts[key]):
            if host in rec["hosts"]:
                continue
            got = {"platform": "", "datasets": []}
            # An ArcGIS Hub site answers only its own search, and slowly
            # refuses the others.
            hub = re.search(r"(?i)\.(hub|opendata)\.arcgis\.com$", host)
            for platform, pattern in CATALOGS:
                if hub and platform != "arcgis_hub":
                    continue
                name = "c%04d_%s_%s" % (int(key), host, platform)
                body, row = capture.fetch(op, pattern.format(h=host), name,
                                          sample[key]["place"], "", "LANDING")
                found = titles(platform, body or "")
                if found is not None:
                    got = {"platform": platform, "datasets": [
                        {"title": t, "url": u} for t, u in found
                        if re.search(r"(?i)permit", t)]}
                    break
            rec["hosts"][host] = got
            with open(FOUND, "w", encoding="utf-8") as fh:
                json.dump(done, fh, indent=1, sort_keys=True)
            print("-- %s %s  %s  %s" % (key, sample[key]["place"], host,
                                       got["platform"] or "no catalog"))
            for d in got["datasets"][:12]:
                print("     %-60s %s" % (d["title"][:60], d["url"]))


DATAGOV = "https://catalog.data.gov/search?q=%s"
DATAGOV_QUERIES = ["building permits", "construction permits"]
DATAGOV_PAGES = 80        # 20 datasets a page, per query
# The name a government publishes under, where the BPS names a part of it.
ALIAS = {"Brooklyn borough": "City of New York",
         "Bronx borough": "City of New York",
         "Queens borough": "City of New York",
         "Manhattan borough": "City of New York",
         "Staten Island borough": "City of New York",
         "Jacksonville-Duval County": "Jacksonville",
         "Nashville-Davidson": "Nashville"}
SUFFIX = re.compile(r"\s+(Unincorporated Area|charter township|township|town|"
                    r"village|borough|city|CDP)$", re.I)


def datagov(keys):
    """The second source, the same for every office: every dataset in
    data.gov's catalog (which harvests city and county portals) that a search
    for building or construction permits returns, matched to offices by the
    publishing organization's name. The catalog's search does not read the
    publisher ("raleigh permits" finds nothing, 2026-10-04), so the results
    are paged through whole. Matches are reviewed by hand: only a dataset the
    office's own government publishes counts."""
    capture.retarget(os.path.join("population", "open_data_datagov"))
    capture.BUDGET = DATAGOV_PAGES * len(DATAGOV_QUERIES) + 5
    op = capture._opener()
    seen = {}
    for q in DATAGOV_QUERIES:
        after = None
        for page in range(DATAGOV_PAGES):
            url = DATAGOV % urllib.parse.quote(q)
            if after:
                url += "&after=" + urllib.parse.quote(after)
            body, _ = capture.fetch(op, url, "g_%s_%03d" % (q.split()[0], page),
                                    "data.gov", "", "LANDING")
            try:
                doc = json.loads(body or "")
            except ValueError:
                break
            for r in doc.get("results", []):
                dcat = r.get("dcat") or {}
                # Harvested records vary: a landing page can be an object.
                landing = dcat.get("landingPage") or ""
                if not isinstance(landing, str):
                    landing = json.dumps(landing)
                key = landing or str(r.get("identifier") or r.get("slug"))
                seen[key] = {
                    "title": str(r.get("title") or dcat.get("title", "")),
                    "organization": str((r.get("organization") or {})
                                        .get("name", "")),
                    "publisher": str(r.get("publisher") or ""),
                    "modified": str(dcat.get("modified", ""))[:10],
                    "landing": landing}
            after = doc.get("after")
            if not after or not doc.get("results"):
                break
        print("%s: %d datasets so far" % (q, len(seen)))
    with open(PORTALS, newline="", encoding="utf-8") as fh:
        sample = [r for r in csv.DictReader(fh)
                  if not keys or r["order"] in keys]
    offices = {}
    for r in sample:
        name = ALIAS.get(r["place"]) or SUFFIX.sub("", r["place"])
        rx = re.compile(r"(?i)\b%s\b" % re.escape(name))
        hits = [d for d in seen.values() if re.search(r"(?i)permit", d["title"])
                and rx.search(d["organization"] + " | " + d["publisher"])]
        if hits:
            offices[r["order"]] = {"place": r["place"], "datasets": hits}
            print("-- %s %s (%s): %d" % (r["order"], r["place"], name, len(hits)))
            for d in hits[:8]:
                print("     %-55s %-26s %s" % (d["title"][:55],
                                              d["organization"][:26],
                                              d["landing"][:60]))
    with open(FOUND_DATAGOV, "w", encoding="utf-8") as fh:
        json.dump({"datasets": seen, "offices": offices}, fh, indent=1,
                  sort_keys=True)


AUGUST = re.compile(r"^(2026-08-\d\d|0?8/\d{1,2}/2026)")


def count_of(platform, body, date_field=""):
    """The count a platform's count query answered, or None. A portal whose
    robots.txt disallows its API but not its files (San Jose's CKAN) is read
    from the file: its rows with an August 2026 date are counted."""
    if platform == "csv":
        rows = list(csv.DictReader(io.StringIO(body)))
        if not rows or date_field not in rows[0]:
            return None
        return sum(1 for r in rows if AUGUST.match(r[date_field].strip()))
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    try:
        if platform == "socrata":
            return int(doc[0]["count"])
        if platform == "arcgis":
            return int(doc["count"])
        if platform == "carto":
            return int(doc["rows"][0]["count"])
        if platform == "ckan":
            return int(doc["result"]["records"][0]["count"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def check():
    with open(DATASETS, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    capture.retarget(os.path.join("population", "open_data"))
    capture.BUDGET = BUDGET
    op = capture._opener()
    out = {}
    for r in rows:
        # A candidate turned down on review keeps its row and its reason.
        if not r["query"]:
            out.setdefault(r["order"], []).append({
                "place": r["place"], "dataset": r["dataset"], "query": "",
                "http_status": "", "robots_ok": False, "august_2026": None,
                "note": r["note"]})
            print("%5s %-26s %-8s %6s  %s: %s" % (r["order"], r["place"][:26],
                                                  "-", "-", r["dataset"][:40],
                                                  r["note"][:60]))
            continue
        name = "q%04d_%s" % (int(r["order"]),
                             urllib.parse.urlsplit(r["query"]).netloc)
        body, row = capture.fetch(op, r["query"], name, r["place"], "",
                                  "LANDING")
        n = count_of(r["platform"], body or "", r["date_field"])
        out.setdefault(r["order"], []).append({
            "place": r["place"], "dataset": r["dataset"], "query": r["query"],
            "http_status": row["http_status"], "robots_ok": row["robots_ok"],
            "august_2026": n, "note": r["note"]})
        print("%5s %-26s %-8s %6s  %s" % (r["order"], r["place"][:26],
                                          row["http_status"] or "-",
                                          "?" if n is None else n,
                                          r["dataset"][:60]))
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)


def as_date(v):
    """A date from a page's or a dataset's way of writing it, or None."""
    if isinstance(v, (int, float)):         # ArcGIS: ms since 1970, local midnight
        return datetime.datetime.fromtimestamp(v / 1000.0, datetime.timezone.utc).date()
    s = str(v).strip()
    for fmt, n in (("%m/%d/%Y", 10), ("%b %d, %Y", 12), ("%Y-%m-%d", 10)):
        try:
            return datetime.datetime.strptime(s[:n], fmt).date()
        except ValueError:
            pass
    return None


def agrees(field, ref, val):
    if field == "issued_date":
        return as_date(ref) == as_date(val)
    a, b = " ".join(str(ref).split()).upper(), " ".join(str(val).split()).upper()
    return a.startswith(b) if field == "address" else a == b


def match():
    with open(DATASETS, newline="", encoding="utf-8") as fh:
        datasets = {r["order"]: r for r in csv.DictReader(fh) if r["query"]}
    capture.retarget(os.path.join("population", "open_data"))
    capture.BUDGET = capture.spent() + 2 * len(MATCH)
    op = capture._opener()
    out = {}
    for order, (id_col, fields) in MATCH.items():
        d = datasets[order]
        with open(os.path.join(REFERENCE, "ref_%04d.json" % int(order)),
                  encoding="utf-8") as fh:
            ref = json.load(fh)
        rows = [r for p in ref["pages"] for r in p["rows"]]
        ids = ",".join("'%s'" % r["native_id"].replace("'", "''") for r in rows)
        base = d["query"].split("?")[0]
        if d["platform"] == "arcgis":
            url = "%s?where=%s&outFields=*&f=json" % (
                base, urllib.parse.quote("%s IN (%s)" % (id_col, ids)))
        elif d["platform"] == "socrata":
            url = "%s?$limit=5000&$where=%s" % (
                base, urllib.parse.quote("%s in (%s)" % (id_col, ids)))
        else:
            url = "%s?q=%s" % (base, urllib.parse.quote(
                "SELECT * FROM permits WHERE %s IN (%s)" % (id_col, ids)))
        body, row = capture.fetch(op, url, "match_%04d" % int(order), d["place"], "",
                                  "LANDING")
        try:
            doc = json.loads(body or "")
        except ValueError:
            doc = None
        found = ([f["attributes"] for f in doc.get("features", [])] if isinstance(doc, dict)
                 and "features" in doc else doc if isinstance(doc, list)
                 else (doc or {}).get("rows", []))
        by_id, repeats = {}, 0
        for f in found:
            repeats += f.get(id_col) in by_id
            by_id.setdefault(f.get(id_col), f)
        tally = {k: [0, 0] for k in fields}
        mismatches = []
        for r in rows:
            f = by_id.get(r["native_id"])
            if f is None:
                continue
            for field, col in fields.items():
                val = (" - ".join(str(f.get(c) or "") for c in col) if isinstance(col, tuple)
                       else f.get(col))
                if r.get(field) is None or val in (None, ""):
                    continue
                tally[field][1] += 1
                if agrees(field, r[field], val):
                    tally[field][0] += 1
                else:
                    mismatches.append([r["native_id"], field, r[field], val])
        out[order] = {"place": d["place"], "dataset": d["dataset"],
                      "http_status": row["http_status"], "reference_rows": len(rows),
                      "in_dataset": sum(r["native_id"] in by_id for r in rows),
                      "repeated_ids": repeats, "fields": tally, "mismatches": mismatches}
        print("%5s %-14s %3d of %3d in the dataset; %s" % (
            order, d["place"][:14], out[order]["in_dataset"], len(rows), "; ".join(
                "%s %d of %d" % (k, a, n) for k, (a, n) in tally.items())))
    with open(MATCH_OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=str)


def main(argv):
    if argv[:1] == ["--match"]:
        return match()
    if argv[:1] == ["--find"]:
        find(argv[1:])
    elif argv[:1] == ["--datagov"]:
        datagov(set(argv[1:]))
    elif argv[:1] == ["--check"]:
        check()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
