# -*- coding: utf-8 -*-
"""Portal population, step 1b: find an office's portal from its own website.

Web-search summaries found a portal URL for 46 of the first 80 offices, and
the ones they missed hold 43% of those offices' units: the large offices.
They also gave addresses that do not exist (Hemet, Charleston County). The
office's own website is the better source: whatever it links to as its permit
search is the portal, by the office's own account.

Two steps, both rule-based so they can be rerun on any range of the draw:

  --sites   Match offices to their official domains in CISA's .gov registry
            (`data/population/links/pages/dotgov_current_full.html`, fetched
            once through permits.capture). Writes data/population/sites.csv,
            every candidate domain per office. An office with no .gov domain
            gets none; its site is added to sites.csv by hand.
  (crawl)   For each office in sites.csv: its home page, its /sitemap when
            the home page links one, and up to 3 of its own pages about
            permits, ranked by link text. Every link on those pages that
            matches a vendor fingerprint or reads like a permit search is a
            candidate. Writes data/population/links.json; candidates are
            reviewed by hand into portals.csv.

Same crawler as everything else: permits.capture, robots.txt honoured, the
crawler's identity sent, the host's pause kept.

Usage:
    python spikes/population_links.py --sites 1 150
    python spikes/population_links.py --sites --top 50  # the take-all stratum
    python spikes/population_links.py 5 12 17          # crawl these offices
    python spikes/population_links.py --page 698 https://www.houstonpermittingcenter.org/
"""
import csv
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
from permits import vendors                    # noqa: E402

ROOT = os.path.dirname(HERE)
DIR = os.path.join(ROOT, "data", "population")
DRAW = os.path.join(DIR, "draw.csv")
DOTGOV = os.path.join(DIR, "links", "pages", "dotgov_current_full.html")
SITES = os.path.join(DIR, "sites.csv")
OUT = os.path.join(DIR, "links.json")

# Per office: a home page tried at up to 3 domains with and without www,
# robots.txt per host, the sitemap, 3 permit pages.
PER_OFFICE = 14
PERMIT_PAGES = 3

PLACE_SUFFIX = re.compile(r"\s+(charter township|township|town|village|"
                          r"borough|city|CDP)$", re.I)
NOT_GENERAL = re.compile(r"court|police|sheriff|school|library|housing|water|"
                         r"fire|utilit|airport|transit|clerk|attorney|"
                         r"election|tourism|museum|park|sewer|port\b|jail|"
                         r"probate|treasurer|assessor|recorder|emergency|911|"
                         r"health|hospital|chamber|district|tax|job|family|"
                         r"veteran|apprais|propert|alert", re.I)
LINK = re.compile(r"(?is)<a\b[^>]*?href\s*=\s*[\"']([^\"'#][^\"']*)[\"'][^>]*>"
                  r"(.*?)</a>")
# An office's own page about permits, by its link text or path.
PERMIT_PAGE = re.compile(r"building|permit|inspection|development services|"
                         r"community development|planning|code enforcement|"
                         r"online services", re.I)
# A link that reads like the permit search itself.
PORTAL_WORDS = re.compile(r"citizen\s*access|self[\s-]*service|"
                          r"permit\w*\s*(search|portal|lookup|center|status)|"
                          r"(search|look\s*up|view)\s*(for\s*)?(a\s*)?permit|"
                          r"online\s*permit|e-?permit|permit\w*\s*online|"
                          r"\bportal\b|one\s*stop|publicaccess|citizen\s*portal",
                          re.I)
SKIP_HOST = re.compile(r"facebook|twitter|x\.com|instagram|youtube|linkedin|"
                       r"nextdoor|google\.|apple\.com|microsoft|adobe", re.I)


def office(r):
    """(kind, name, government) for a draw row: ('county', 'Moore County',
    'county'), ('place', 'Queen Creek', 'town'). The Census suffix says which
    government it is; no suffix is a city."""
    name = r["place_name"]
    if name.endswith(" Unincorporated Area"):
        name = name[:-len(" Unincorporated Area")]
    # Virginia's counties issue permits as places of their own ("Bedford
    # County"), with no "Unincorporated Area" suffix.
    if name.endswith((" County", " Parish")):
        return "county", name, name.split()[-1].lower()
    m = PLACE_SUFFIX.search(name)
    gov = m.group(1).lower() if m else "city"
    return "place", PLACE_SUFFIX.sub("", name), gov


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("saint ", "st ")
                  .replace("st. ", "st ")).strip()


def match_sites(rows, registry):
    """Every .gov domain whose registered organization is this office's
    general government: same state, the name as a whole phrase, and none of
    the words that mark a court, a utility or a school."""
    out = []
    for r in rows:
        kind, name, gov = office(r)
        n = norm(name)
        if kind == "county":
            base = re.escape(n.rsplit(" ", 1)[0])
            named = re.compile(r"^(the )?(%s (county|parish)|(county|parish) "
                               r"of %s)\b" % (base, base))
        else:
            named = re.compile(r"^(the )?((city|town|village|borough|"
                               r"charter township|township) of %s|%s (city|"
                               r"town|village|borough|charter township|"
                               r"township))\b" % (re.escape(n), re.escape(n)))
        hits = []
        for d in registry:
            if d["State"] != r["state_abbr"]:
                continue
            if NOT_GENERAL.search(d["Organization name"]):
                continue
            want = "County" if kind == "county" else "City"
            org = norm(d["Organization name"])
            if d["Domain type"] == want and named.search(org):
                # Plymouth charter township is not the City of Plymouth.
                hits.append((gov not in org, d["Domain name"].lower()))
        # The right government first, then the domain that spells the name,
        # then the shortest.
        key = n.replace(" ", "")
        hits = [h for _, h in sorted(hits, key=lambda x: (
            x[0], key[:6] not in x[1], len(x[1])))]
        out.append({"order": r["order"], "place": r["place_name"],
                    "state": r["state_abbr"], "kind": kind,
                    "domains": " ".join(hits)})
    return out


def links(html, base):
    out = []
    for href, text in LINK.findall(html or ""):
        text = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", text)).strip()
        url = urllib.parse.urljoin(base, unescape(href).strip())
        if url.startswith("http"):
            out.append((text, url))
    return out


def crawl(op, sites, key):
    """Home page, sitemap, then the office's own permit pages; every
    portal-like link on any of them."""
    host = urllib.parse.urlsplit(sites[0]).netloc

    def same_site(url):
        h = urllib.parse.urlsplit(url).netloc
        return h == host or h.split(".", 1)[-1] == host.split(".", 1)[-1]

    pages, pool, seen = [], [], set()

    def get(url, tag):
        name = "s%04d_%s_%s" % (int(key), host, tag)
        html, row = capture.fetch(op, url, name, "links", "", "LANDING")
        pages.append({"url": url, "final": row["final_url"],
                      "status": row["http_status"],
                      "reason": row["verdict_reason"]})
        return html, row["final_url"]

    # A registered domain is not always the live site (friscotx.gov and
    # galtca.gov have no address; Mansfield's live one is its second), and
    # some answer only at www. First home page that comes back wins.
    html = None
    for i, s in enumerate(sites):
        host = urllib.parse.urlsplit(s).netloc
        tries = [s] + ([] if host.startswith("www.")
                       else ["https://www.%s/" % host])
        for j, url in enumerate(tries):
            html, final = get(url, "home%d%s" % (i, "w" * j))
            if html is not None or pages[-1]["status"]:
                break
        if html is not None:
            break
    if html is None:
        return pages, []
    host = urllib.parse.urlsplit(final).netloc or host
    home_links = links(html, final)
    pool.extend((t, u, "home") for t, u in home_links)
    # The sitemap when the home page links one, or when its own markup has
    # no link about permits: CivicPlus sites build their menus in a script
    # (Pflugerville, Camarillo, Buncombe County, 2026-10-04) but serve
    # /sitemap all the same.
    if any(urllib.parse.urlsplit(u).path.lower().rstrip("/") == "/sitemap"
           for _, u in home_links) or not any(
               PERMIT_PAGE.search(t) for t, _ in home_links):
        sm, sfinal = get(urllib.parse.urljoin(final, "/sitemap"), "sitemap")
        pool.extend((t, u, "sitemap") for t, u in links(sm, sfinal))
    # The office's own pages about permits, best-named first.
    ranked = []
    for t, u, _ in pool:
        if not same_site(u) or u in seen:
            continue
        seen.add(u)
        score = len(PERMIT_PAGE.findall(t)) * 2 + len(PERMIT_PAGE.findall(
            urllib.parse.urlsplit(u).path))
        if re.search(r"building\s*permit|permit", t, re.I):
            score += 3
        if score:
            ranked.append((-score, len(u), t, u))
    for i, (_, _, t, u) in enumerate(sorted(ranked)[:PERMIT_PAGES]):
        ph, pfinal = get(u, "p%d" % (i + 1))
        pool.extend((tt, uu, "page:" + t[:40]) for tt, uu in links(ph, pfinal))
    cands, kept = [], set()
    for t, u, src in pool:
        if SKIP_HOST.search(urllib.parse.urlsplit(u).netloc) or u in kept:
            continue
        v = vendors.from_url(u)
        if v or PORTAL_WORDS.search(t) or PORTAL_WORDS.search(u):
            kept.add(u)
            cands.append({"text": t[:80], "url": u, "vendor": v,
                          "from": src, "offsite": not same_site(u)})
    # Offsite vendor links first: those are the portals.
    cands.sort(key=lambda c: (not c["vendor"], not c["offsite"]))
    return pages, cands


def main(argv):
    with open(DRAW, newline="", encoding="utf-8") as fh:
        draw = list(csv.DictReader(fh))
    if argv[:1] == ["--sites"]:
        with io.open(DOTGOV, encoding="utf-8") as fh:
            registry = list(csv.DictReader(fh))
        if argv[1] == "--top":
            # The take-all stratum: the frame's largest offices, wherever
            # they fall in the draw.
            rows = [r for r in draw if int(r["size_rank"]) <= int(argv[2])]
        else:
            lo, hi = int(argv[1]), int(argv[2])
            rows = [r for r in draw if lo <= int(r["order"]) <= hi]
        found = match_sites(rows, registry)
        have = {}
        if os.path.exists(SITES):
            with open(SITES, newline="", encoding="utf-8") as fh:
                have = {r["order"]: r for r in csv.DictReader(fh)}
        for f in found:
            # A site entered by hand (source "hand") is kept over the
            # registry's guess.
            if have.get(f["order"], {}).get("source") == "hand":
                continue
            f["site"] = ("https://" + f["domains"].split()[0]
                         if f["domains"] else "")
            f["source"] = "dotgov" if f["domains"] else ""
            have[f["order"]] = f
        cols = ["order", "place", "state", "kind", "site", "source",
                "domains"]
        with open(SITES, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for k in sorted(have, key=int):
                w.writerow(have[k])
        n = sum(1 for f in found if f["domains"])
        print("%d of %d offices matched a .gov domain" % (n, len(found)))
        return
    with open(SITES, newline="", encoding="utf-8") as fh:
        sites = {r["order"]: r for r in csv.DictReader(fh)}
    done = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            done = json.load(fh)
    capture.retarget(os.path.join("population", "links"))
    if argv[:1] == ["--page"]:
        # A second hop: one of the office's own pages that the first crawl
        # found but did not follow far enough (a "Permit Center" page, a
        # department's own site), crawled as if it were the home page. Kept
        # beside the first crawl, not over it.
        pairs = list(zip(argv[1::2], argv[2::2], strict=True))
        capture.BUDGET = capture.spent() + PER_OFFICE * len(pairs)
        op = capture._opener()
        for key, url in pairs:
            print("-- %s %s  %s" % (key, done.get(key, {}).get("place", ""),
                                    url))
            pages, cands = crawl(op, [url], key)
            done.setdefault(key, {}).setdefault("from_page", {})[url] = {
                "pages": pages, "candidates": cands}
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(done, fh, indent=1, sort_keys=True)
            for c in cands[:12]:
                print("   %-22s %-40s %s" % (c["vendor"][:22], c["text"][:40],
                                             c["url"]))
        return
    only = list(argv)
    capture.BUDGET = capture.spent() + PER_OFFICE * max(1, len(only))
    op = capture._opener()
    for key in only:
        s = sites.get(key)
        if not s or not s["site"]:
            print("%s: no site" % key)
            continue
        print("-- %s %s %s  %s" % (key, s["place"], s["state"], s["site"]))
        others = ["https://" + d for d in s["domains"].split()
                  if d not in s["site"]]
        pages, cands = crawl(op, ([s["site"]] + others)[:3], key)
        done[key] = {"place": s["place"], "state": s["state"],
                     "site": s["site"], "pages": pages, "candidates": cands}
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(done, fh, indent=1, sort_keys=True)
        for c in cands[:12]:
            print("   %-22s %-40s %s" % (c["vendor"][:22], c["text"][:40],
                                         c["url"]))


if __name__ == "__main__":
    main(sys.argv[1:])
