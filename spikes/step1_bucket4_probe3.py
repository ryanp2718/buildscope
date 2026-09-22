# -*- coding: utf-8 -*-
"""Bucket-4 probe, second hop: the pages the entry pages pointed at.

Probe II found two things one hop in:

  Bowling Green runs **eSuite** at `esuites.bgky.org`, not "unknown vendor,
  host unreachable". Its WelcomePage carries a contractor login and a service-
  address box and no date criterion, which would make it bucket 4 - but a
  vendor welcome page is a landing page, and the question is what the permit
  search behind it accepts.

  St. Louis's permit page links `https://www.stlcitypermits.com/`, which is the
  "new portal announced 2026" that classification.csv recorded as not yet
  probed. The old address-keyed `.cfm` form is bucket 4; the new portal is
  unclassified and is what the office will actually be crawled through.

One correction carried forward from probe II. Its field classifier matched
date-ness by substring, and `contractorLogin` contains `to`, so three login
controls were reported as date fields. Substring matching on field names is
the same failure family as Accela's "Please enter" JS constant and Spike C's
`<tr>` count: a discriminator that fires on something every page has. Field
names are matched on token boundaries here.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import capture as mf  # noqa: E402
from permits import aspnet                              # noqa: E402

# Token-boundary matching. A field name is split on non-alphanumerics and on
# camelCase humps, then whole tokens are compared - `contractorLogin` yields
# ("contractor","login") and matches neither `to` nor `date`.
SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")
DATE_TOK = {"date", "dt", "from", "to", "begin", "end", "start", "issued",
            "issue", "applied", "apply", "daterange", "fromdt", "todt"}
ADDR_TOK = {"address", "addr", "street", "st", "parcel", "apn", "owner",
            "location"}
NUM_TOK = {"permitno", "permitnum", "permitnumber", "caseno", "casenumber",
           "recordno", "recordnumber", "number", "num", "no", "permit"}


def tokens(name):
    return set(t.lower() for t in SPLIT.split(name) if t)


def classify(names):
    named = [n for n in names if not n.startswith("__")]
    hit = lambda toks: sorted(n for n in named if tokens(n) & toks)  # noqa: E731
    return {"n": len(named), "date": hit(DATE_TOK), "address": hit(ADDR_TOK),
            "number": hit(NUM_TOK)}


def report_form(html, where):
    hid = aspnet.hidden_fields(html)
    names = list(aspnet.form_fields(html)) + list(hid)
    c = classify(names)
    short = lambda xs: [x.split("$")[-1] for x in xs]                # noqa: E731
    print("     %-34s inputs=%-3d date=%s addr=%s num=%s"
          % (where[:34], c["n"], short(c["date"]) or "-",
             short(c["address"]) or "-", short(c["number"]) or "-"))
    return c


LINK = re.compile(r'(?i)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
SEARCHY = re.compile(r"(?i)search|lookup|look up|find|status|inquir|report|"
                     r"permit list|issued")


def searchy_links(html, base):
    out = []
    seen = set()
    for href, label in LINK.findall(html or ""):
        txt = re.sub(r"<[^>]+>", " ", label)
        txt = re.sub(r"\s+", " ", txt).strip()
        if not txt or not SEARCHY.search(txt + " " + href):
            continue
        url = href if href.startswith("http") else None
        if url is None:
            if href.startswith("/"):
                url = "/".join(base.split("/")[:3]) + href
            elif not href.startswith(("#", "mailto:", "javascript:")):
                url = base.rsplit("/", 1)[0] + "/" + href
        if url and url not in seen:
            seen.add(url)
            out.append((url, txt[:60]))
    return out[:20]


def run(key, label, vendor, url, follow):
    print("\n" + "=" * 78)
    print("%s  [%s]" % (label, key))
    print("=" * 78)
    op = mf._opener()
    slug = key.replace("|", "_")
    html, row = mf.fetch(op, url, "b4c_%s_entry" % slug, label, vendor,
                         "T-SEARCH")
    if html is None:
        print("  unavailable: %s" % (row or {}).get("verdict_reason"))
        return
    print("  %s -> %d bytes" % (url, len(html)))
    report_form(html, "entry page")
    cands = searchy_links(html, url)
    print("  candidate search links:")
    for u, t in cands:
        print("     %-62s %s" % (u[:62], t))

    for i, (u, t) in enumerate(cands[:follow]):
        h, r = mf.fetch(op, u, "b4c_%s_hop%d" % (slug, i), label, vendor,
                        "T-SEARCH")
        if h is None:
            print("     hop%d unavailable: %s" % (i, (r or {}).get("verdict_reason")))
            continue
        print("  hop%d %s -> %d bytes" % (i, u[:58], len(h)))
        report_form(h, t)


def main():
    mf.retarget("step1")
    mf.BUDGET = 40
    print("=" * 78)
    print("BUCKET-4 PROBE III - one hop past the landing pages")
    print("=" * 78)
    run("21|045000", "Bowling Green KY", "esuite",
        "https://esuites.bgky.org/eSuite.permits/WelcomePage.aspx", follow=4)
    run("29|607000", "St. Louis MO", "stlcitypermits",
        "https://www.stlcitypermits.com/", follow=4)
    print("\nrequests spent: %d of %d" % (mf.spent(), mf.BUDGET))
    return 0


if __name__ == "__main__":
    sys.exit(main())
