# -*- coding: utf-8 -*-
"""Portal population, step 2: fetch each located portal's front page once and
read off the vendor, whether the page is built in the browser, and whether it
asks for a login.

Input is `data/population/portals.csv`, kept by hand in draw order
(`population_draw.py`): one row per office in the sample (offices 1-150 and
the take-all stratum), with the portal URL found, or a status saying why
there is none. This script only reads what the
server sends back. It does not search the portal; whether a public query
returns a list of records is settled per portal when it is onboarded.

One GET per portal through `permits.capture`: robots.txt honoured, the
crawler's identity sent, the host's pause kept, the page saved with its
manifest row under `data/population/probe/`. A row already probed is skipped,
so re-running after adding rows fetches only the new ones.

Writes data/population/probe.json.

`--sample` builds the onboarding queue, data/population/sample.csv: the
portals of each product in draw order, with each one's place under the
pre-registered caps (Accela the first 10-12 usable, every other product the
first 3). Usability is read from data/population/usability.csv, kept as each
portal is checked (order, usable yes/no, pages, reason, checked_on), so the
queue moves on past a portal that fails.

Usage:
    python spikes/population_probe.py            # every unprobed located row
    python spikes/population_probe.py 2 6 9      # these draw-order rows again
    python spikes/population_probe.py --funnel
    python spikes/population_probe.py --sample
"""
import csv
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import capture  # noqa: E402
from permits import vendors  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "population")
PORTALS = os.path.join(DIR, "portals.csv")
DRAW = os.path.join(DIR, "draw.csv")
OUT = os.path.join(DIR, "probe.json")
OPEN_DATA = os.path.join(DIR, "open_data.json")   # population_open_data --check

# A stated ceiling for one process, as capture's own default is: one front
# page per portal, plus the robots.txt read per host.
BUDGET = 200

# Where locating stops (pre-registration, approved 2026-10-04): offices 1-150
# in draw order, plus the take-all stratum, the frame's 50 largest offices
# wherever they fall in the draw. A take-all office stands for itself; a drawn
# office outside it stands for (1,000 - 50) / (drawn offices outside it).
DRAWN = 150
TAKE_ALL = 50

# The sample (pre-registration, approved 2026-10-04): Accela's first 10-12
# usable portals, every other product's first 3. A city's own system is a
# product of its own. Development portals take no place, and the existing
# targets among the offices are recorded and skipped.
SAMPLE = os.path.join(DIR, "sample.csv")
USABILITY = os.path.join(DIR, "usability.csv")
CAPS = {"Accela": 12}
CAP = 3
DEVELOPMENT = {"24": "Kyle: the check's record-card development portal"}
SKIPPED = {"229": "St. Johns: an existing target",
           "951": "Clark: the Clark pilot's development portal"}
# Pages saved by hand cost the owner's time, so they are kept to what nothing
# else can supply (owner, 2026-10-05): a portal that refuses the crawler is
# replaced by the next one on its product that the crawler can fetch; a
# product only a browser can reach gets one portal saved by hand; an office's
# own system that refuses the crawler is not sampled, and its units are
# reported as behind a portal that refuses an identified crawler.
BROWSER_CAP = 1
# Portal outcomes with no public list to onboard.
NO_PORTAL = {"not_located", "none", "vendor_only", "pdf_only", "lookup_only",
             "login", "unprobed"}

PASSWORD = re.compile(r"<input[^>]+type=[\"']?password", re.I)
LOGIN_WORDS = re.compile(r"\b(log\s?in|sign\s?in)\b", re.I)
SEARCH_WORDS = re.compile(r"\b(search|look\s?up)\b[^<]{0,40}\b(permit|record|"
                          r"application|case)s?\b|\b(permit|record)s?\b[^<]{0,20}"
                          r"\bsearch\b", re.I)
TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
META_REFRESH = re.compile(r"(?i)<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]*"
                          r"content=[\"'][^\"']*url=([^\"']+)[\"']")
TAGS = re.compile(r"(?s)<[^>]+>")


def read_page(html):
    """What the front page says about itself, from markup alone."""
    body = capture.strip_scripts(html)
    text = re.sub(r"\s+", " ", TAGS.sub(" ", body)).strip()
    m = TITLE.search(html)
    return {
        "title": re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else "",
        "text_chars": len(text),
        # Visible text per byte of HTML. A page built by a script ships a
        # shell with little text (Spike A: 0.023 for CityView's).
        "text_ratio": round(len(text) / max(1, len(html)), 3),
        "password_field": bool(PASSWORD.search(html)),
        "login_words": len(LOGIN_WORDS.findall(text)),
        "search_words": len(SEARCH_WORDS.findall(text)),
        "tables": len(re.findall(r"(?i)<table\b", body)),
        "forms": len(re.findall(r"(?i)<form\b", body)),
    }


def reread(done):
    """Re-read every saved front page with the current fingerprints, without
    fetching anything."""
    for key, rec in done.items():
        name = "p%04d_%s" % (int(key), urllib.parse.urlsplit(rec["url"]).netloc)
        path = os.path.join(capture.PAGES, name + "_r.html")
        if not os.path.exists(path):
            path = os.path.join(capture.PAGES, name + ".html")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        rec["vendor"], rec["vendor_from"] = vendors.identify(rec["final_url"], html)
        rec.update(read_page(html))


def outcome(row, rec):
    """Where an office ends up in the funnel: the status recorded by hand,
    refined by what the probe got back from a located portal."""
    if row["status"] != "located":
        return row["status"]
    if rec is None:
        return "unprobed"
    if not rec.get("robots_ok", True):
        return "robots_disallow"
    status = str(rec.get("http_status") or "")
    if not status:
        return "unreachable"
    if status in ("401", "403", "429") or rec.get("title") == "Just a moment...":
        return "blocked"
    if not status.startswith("2"):
        return "http_" + status
    # The start page responded without a block. Whether the portal has a
    # usable list is settled at onboarding, not here.
    return "answered"


def open_data():
    """Offices whose government publishes their permits as a dataset that a
    polite crawler fetched and that holds permits issued in August 2026."""
    if not os.path.exists(OPEN_DATA):
        return set()
    with open(OPEN_DATA, encoding="utf-8") as fh:
        checked = json.load(fh)
    return {k for k, sets in checked.items()
            if any(d["robots_ok"] and str(d["http_status"]) == "200"
                   and (d["august_2026"] or 0) > 0 for d in sets)}


def weights(draw):
    """Design weight per draw order: 1 for a take-all office, the expansion
    weight for a drawn office outside the stratum; offices in neither are
    left out."""
    take_all = {r["order"] for r in draw if int(r["size_rank"]) <= TAKE_ALL}
    drawn = [r["order"] for r in draw
             if int(r["order"]) <= DRAWN and r["order"] not in take_all]
    w = dict.fromkeys(take_all, 1.0)
    w.update(dict.fromkeys(drawn, (len(draw) - len(take_all)) / len(drawn)))
    return w


def funnel(rows, done):
    """Counts by outcome, and by vendor among the offices whose vendor is
    known, from the probe or else from what the office's own pages named.
    Each outcome also carries its share of the offices' 12-month units, since
    an office's weight in "how much US housing can be read" is its units.

    Two tables: offices 1-150 as drawn, and the estimate for the 1,000
    largest offices, which adds the take-all stratum and applies the design
    weights. The second lists the offices that weigh most in it."""
    import collections
    with open(DRAW, newline="", encoding="utf-8") as fh:
        draw = list(csv.DictReader(fh))
    units = {r["order"]: float(r["units_12mo"] or 0) for r in draw}
    w = weights(draw)
    missing = sorted(set(w) - {r["order"] for r in rows}, key=int)
    by_outcome = collections.Counter()
    by_units = collections.Counter()
    est_offices = collections.Counter()
    est_units = collections.Counter()
    portal_units = collections.Counter()      # without open data's precedence
    contrib = {}
    by_vendor = collections.defaultdict(collections.Counter)
    published = open_data()
    behind_open = collections.Counter()
    for row in rows:
        rec = done.get(row["order"])
        out = outcome(row, rec)
        if row["order"] in w:
            portal_units[out] += w[row["order"]] * units.get(row["order"], 0)
        # Open data takes precedence; the portal outcome is kept beside it.
        if row["order"] in published:
            behind_open[out] += 1
            out = "open_data"
        if row["order"] in w:
            est_offices[out] += w[row["order"]]
            est_units[out] += w[row["order"]] * units.get(row["order"], 0)
            contrib[row["order"]] = (w[row["order"]] * units.get(row["order"], 0),
                                     row["place"], out)
        name = (rec or {}).get("vendor") or ""
        if not name:
            for n, rx in vendors.VENDOR_RES:
                if rx.search(row["note"]) or rx.search(row["url"]):
                    name = n
                    break
        if out not in ("none", "not_located") or name:
            by_vendor[name or "custom/unknown"][out] += 1
        if int(row["order"]) <= DRAWN:
            by_outcome[out] += 1
            by_units[out] += units.get(row["order"], 0)
    total = sum(by_units.values())
    print("\noffices 1-%d in draw order: %d, %d units in 12 months"
          % (DRAWN, sum(by_outcome.values()), total))
    print("  %-16s %7s %7s" % ("outcome", "offices", "units"))
    for out, n in by_outcome.most_common():
        print("  %-16s %7d %6.1f%%" % (out, n, 100 * by_units[out] / total))
    if behind_open:
        print("\nopen data offices' portal outcomes: %s" % ", ".join(
            "%s %d" % kv for kv in behind_open.most_common()))
    print("\n%-26s %s" % ("vendor", "outcomes (every office located, "
                                     "unweighted)"))
    for name, c in sorted(by_vendor.items(), key=lambda kv: -sum(kv[1].values())):
        print("  %-24s %3d  %s" % (name, sum(c.values()),
                                   ", ".join("%s %d" % kv for kv in c.most_common())))

    if missing:
        print("\nno frame estimate: %d offices in the sample have no row: %s"
              % (len(missing), " ".join(missing)))
        return
    total = sum(est_units.values())
    print("\nestimate for the %d largest offices (take-all %d, drawn 1-%d, "
          "design-weighted)" % (len(draw), TAKE_ALL, DRAWN))
    print("  %-16s %7s %7s" % ("outcome", "offices", "units"))
    for out, u in est_units.most_common():
        print("  %-16s %7.0f %6.1f%%" % (out, est_offices[out], 100 * u / total))
    print("\n  largest contributors to the units:")
    top = sorted(contrib.values(), reverse=True)
    for u, place, out in top[:5]:
        print("    %5.1f%%  %-34s %s" % (100 * u / total, place[:34], out))
    u0, _, out0 = top[0]
    reach = est_units["answered"] - (u0 if out0 == "answered" else 0)
    print("  answered without the largest: %.1f%% (with it %.1f%%)"
          % (100 * reach / (total - u0), 100 * est_units["answered"] / total))
    print("  without open data: answered %.1f%%, blocked %.1f%%; answered or "
          "open data: %.1f%%" % (
              100 * portal_units["answered"] / total,
              100 * portal_units["blocked"] / total,
              100 * (est_units["answered"] + est_units["open_data"]) / total))


def product(row, rec):
    """The product a portal runs: the vendor read from its page or named in
    the office's note, MyGov split by interface, else the office's own system
    keyed by its host."""
    name = (rec or {}).get("vendor") or ""
    if not name:
        for n, rx in vendors.VENDOR_RES:
            if rx.search(row["note"]) or rx.search(row["url"]):
                name = n
                break
    if name == "MyGov":
        # public.mygov.us (an application form at Mansfield and Midlothian)
        # and MGO Connect are different interfaces.
        name = "MyGov MGO Connect" if "mgoconnect" in row["url"].lower() \
            else "MyGov public.mygov.us"
    return name or "own: " + portal_key(row["url"]).split("/")[0]


def portal_key(url):
    """One key per portal: host and first path segment. Accela tenancies
    differ by segment; one portal serving several offices (MGO Connect, NYC's
    DOB NOW) shares one."""
    u = urllib.parse.urlsplit(url.strip().lower())
    host = u.netloc.removeprefix("www.")
    return host + "/" + u.path.strip("/").split("/")[0]


def sample(rows, done):
    """The onboarding queue, one row per portal in draw order within its
    product, and what each portal is waiting on."""
    import collections
    with open(DRAW, newline="", encoding="utf-8") as fh:
        units = {r["order"]: float(r["units_12mo"] or 0)
                 for r in csv.DictReader(fh)}
    usable = {}
    if os.path.exists(USABILITY):
        with open(USABILITY, newline="", encoding="utf-8") as fh:
            usable = {r["order"]: r for r in csv.DictReader(fh)}
    portals = {}
    # Products whose one hand-saved try is spent: the owner opened a portal in
    # a browser and found no list, so no other portal of it is tried. And
    # products the crawler reached even where onboarding then found no list
    # (Cityworks: every portal a sign-in), so none of theirs is saved by hand.
    # A robots.txt refusal found at onboarding (EnerGov's script CDN) is not
    # one of these: it binds only a crawler, so the portal stays in the queue
    # for a browser, and a hand-saved try could still find a list.
    hand_tried, reached = set(), set()
    for row in sorted(rows, key=lambda r: int(r["order"])):
        out = outcome(row, done.get(row["order"]))
        if out in NO_PORTAL:
            if row["note"].startswith("owner checked in a browser"):
                hand_tried.add(product(row, done.get(row["order"])))
            elif row["note"].startswith("onboarding check"):
                reached.add(product(row, done.get(row["order"])))
            continue
        key = portal_key(row["url"])
        if key in portals:
            p = portals[key]
            p["offices"].append(row["order"])
            p["units"] += units.get(row["order"], 0)
            continue
        portals[key] = {
            "order": row["order"], "place": row["place"], "state": row["state"],
            "product": product(row, done.get(row["order"])), "url": row["url"],
            "outcome": out, "offices": [row["order"]],
            "units": units.get(row["order"], 0),
            "access": "crawler" if out == "answered" else "browser"}
    by_product = collections.defaultdict(list)
    for p in portals.values():
        by_product[p["product"]].append(p)
    for name, group in by_product.items():
        crawled = name in reached or any(
            p["access"] == "crawler" and p["order"] not in SKIPPED for p in group)
        cap = CAPS.get(name, CAP) if crawled else BROWSER_CAP
        tested = pending = 0
        tried = name in hand_tried
        for p in group:
            u = usable.get(p["order"], {}).get("usable", "")
            p["needs"] = usable.get(p["order"], {}).get("needs", "")
            if p["order"] in SKIPPED:
                p["role"], p["why"] = "skipped", SKIPPED[p["order"]]
            elif p["order"] in DEVELOPMENT:
                p["role"], p["why"] = "development", DEVELOPMENT[p["order"]]
            elif p["access"] == "browser" and crawled:
                p["role"], p["why"] = "replaced", ("refuses the crawler; the next "
                                                   "portal it can fetch takes the place")
            elif p["access"] == "browser" and name.startswith("own: "):
                p["role"], p["why"] = "not sampled", ("own system that refuses the "
                                                      "crawler")
            elif p["access"] == "browser" and tried:
                # One attempt by hand per product only a browser can reach.
                p["role"], p["why"] = "not sampled", "one hand-saved try per product"
            elif p["access"] == "browser" and u == "no":
                tried = 1
                p["role"], p["why"] = "not usable", usable[p["order"]]["reason"]
            elif u == "no":
                p["role"], p["why"] = "not usable", usable[p["order"]]["reason"]
            elif tested >= cap:
                p["role"], p["why"] = "capped", ""
            elif u == "yes":
                p["role"], p["why"] = "tested", ""
                tested += 1
            elif tested + pending < cap:
                p["role"], p["why"] = "check", ""
                pending += 1
                tried = p["access"] == "browser"
            else:
                p["role"], p["why"] = "waiting", "takes a place if a check ahead fails"
    fields = ["product", "order", "place", "state", "role", "access", "needs",
              "outcome", "url", "offices", "units", "why"]
    with open(SAMPLE, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for name in sorted(by_product, key=lambda n: (n.startswith("own: "), n)):
            for p in by_product[name]:
                w.writerow(dict(p, offices=" ".join(p["offices"]),
                                units=int(p["units"])))
    roles = collections.Counter((p["role"], p["access"]) for p in portals.values())
    print("%d portals over %d products (%d own systems) -> %s"
          % (len(portals), len(by_product),
             sum(n.startswith("own: ") for n in by_product), SAMPLE))
    for (role, access), n in sorted(roles.items()):
        print("  %-12s %-8s %3d" % (role, access, n))
    print("\n%-26s %s" % ("product", "portals in draw order: role"))
    for name in sorted(by_product, key=lambda n: (n.startswith("own: "), n)):
        print("  %-24s %s" % (name[:24], ", ".join(
            "%s %s%s" % (p["order"], p["role"], "" if p["access"] == "crawler"
                         else " (browser)") + (" [needs %s]" % p["needs"]
                                               if p["needs"] == "owner" else "")
            for p in by_product[name])))


def main(argv):
    if argv[:1] == ["--sample"]:
        with open(PORTALS, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        with open(OUT, encoding="utf-8") as fh:
            sample(rows, json.load(fh))
        return
    if argv[:1] == ["--funnel"]:
        with open(PORTALS, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        with open(OUT, encoding="utf-8") as fh:
            funnel(rows, json.load(fh))
        return
    rereading = argv[:1] == ["--reread"]
    only = {int(a) for a in argv if a != "--reread"}
    with open(PORTALS, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    done = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            done = json.load(fh)

    capture.retarget(os.path.join("population", "probe"))
    if rereading:
        reread(done)
        rows = []
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(done, fh, indent=1, sort_keys=True)
    capture.BUDGET = BUDGET
    op = capture._opener()
    for r in rows:
        key = r["order"]
        if r["status"] != "located" or not r["url"]:
            continue
        if (only and int(key) not in only) or (not only and key in done):
            continue
        name = "p%04d_%s" % (int(key), urllib.parse.urlsplit(r["url"]).netloc)
        html, row = capture.fetch(op, r["url"], name, r["place"], "",
                                  "LANDING")
        # One meta-refresh hop: several portals' front pages are a stub that
        # forwards to the application (Volusia's ConnectLive).
        m = META_REFRESH.search(html or "")
        if m:
            nxt = urllib.parse.urljoin(row["final_url"], m.group(1).strip())
            html, row = capture.fetch(op, nxt, name + "_r", r["place"], "",
                                      "LANDING")
        rec = {"place": r["place"], "state": r["state"], "url": r["url"],
               "final_url": row["final_url"], "http_status": row["http_status"],
               "bytes": row["bytes"], "robots_ok": row["robots_ok"],
               "verdict_reason": row["verdict_reason"]}
        if html is not None:
            rec["vendor"], rec["vendor_from"] = vendors.identify(row["final_url"], html)
            rec.update(read_page(html))
        done[key] = rec
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(done, fh, indent=1, sort_keys=True)

    print("\n%5s %-28s %-4s %-24s %5s %7s %6s %4s %4s  %s"
          % ("order", "place", "st", "vendor", "http", "bytes", "ratio",
             "pw", "srch", "title"))
    for key in sorted(done, key=int):
        d = done[key]
        print("%5s %-28s %-4s %-24s %5s %7s %6s %4s %4s  %s"
              % (key, d["place"][:28], d["state"], (d.get("vendor") or "?")[:24],
                 d["http_status"], d["bytes"], d.get("text_ratio", ""),
                 "Y" if d.get("password_field") else "",
                 d.get("search_words", ""), d.get("title", "")[:50]))


if __name__ == "__main__":
    main(sys.argv[1:])
