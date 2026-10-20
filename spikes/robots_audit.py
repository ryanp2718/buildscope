# -*- coding: utf-8 -*-
"""Audit: what the robots.txt parser got wrong before 2026-10-20.

Until 2026-10-20 `permits.capture` matched robots.txt with the standard
library's parser, which drops a rule's query (Google's `Disallow: /?` read as
`Disallow: /`) and ignores the `*` and `$` wildcards, and it asked for
robots.txt as HTML, which a server that honours Accept answered with 406 (read
as "no rules"). This re-reads every host the project has fetched from and
judges every recorded request three ways:

- recorded: what the crawler decided at the time (the manifest's robots_ok);
- stdlib:   the old parser on today's robots.txt;
- rfc:      RFC 9309 (Protego, as `capture` now uses) on today's robots.txt.

recorded != stdlib means the file changed since (or the old Accept got a
different answer); stdlib != rfc is the parser's error. Each host's
robots.txt is fetched once, as text, with the crawler's identity, and saved
to data/robots_audit/ (private). Writes data/robots_audit/rows.csv and prints
the summary the evidence report quotes.

Usage:
    python spikes/robots_audit.py            # fetch robots.txt, then judge
    python spikes/robots_audit.py --offline  # judge from the saved copies
"""
import collections
import csv
import glob
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protego import Protego                    # noqa: E402

from permits import capture                    # noqa: E402
from permits.crawler_identity import NAME      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "robots_audit")
INDEX = os.path.join(OUT, "hosts.json")


def manifest_rows():
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "**", "manifest.csv"),
                                 recursive=True)):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("url", "").startswith("http"):
                    yield os.path.relpath(path, ROOT), r


def host_key(url):
    u = urllib.parse.urlsplit(url)
    return "%s://%s" % (u.scheme, u.netloc)


def fetch_all(hosts):
    """One robots.txt request per host, as `capture.robots_for` now makes it."""
    os.makedirs(OUT, exist_ok=True)
    op = capture._opener()
    index = {}
    for i, key in enumerate(sorted(hosts)):
        name = urllib.parse.urlsplit(key).netloc.replace(":", "_")
        req = urllib.request.Request(key + "/robots.txt",
                                     headers={"Accept": capture.ROBOTS_ACCEPT})
        rec = {"file": name + ".txt", "status": None, "error": ""}
        try:
            r = op.open(req, timeout=capture.TIMEOUT)
            rec["status"] = r.getcode()
            body = r.read(500000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            rec["status"], body = e.code, ""
        except Exception as e:
            rec["error"], body = type(e).__name__, ""
        with open(os.path.join(OUT, rec["file"]), "w", encoding="utf-8") as fh:
            fh.write(body)
        index[key] = rec
        if i % 25 == 0:
            print("  %d/%d %s %s" % (i, len(hosts), key, rec["status"] or rec["error"]))
    with open(INDEX, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1, sort_keys=True)
    return index


def parsers(rec):
    """(stdlib, rfc) for one host's saved robots.txt, under each parser's own
    reading of a missing or failed file."""
    with open(os.path.join(OUT, rec["file"]), encoding="utf-8") as fh:
        text = fh.read()
    old = urllib.robotparser.RobotFileParser()
    old.parse(text.splitlines())          # the old code read any failure as no rules
    status = rec["status"]
    if status and 200 <= status < 300:
        new = Protego.parse(text.removeprefix("﻿"))   # as capture now reads it
    elif status and 400 <= status < 500:
        new = capture.ALLOW_ALL
    else:
        new = capture.DISALLOW_ALL
    return old, new


def main(argv):
    rows = list(manifest_rows())
    hosts = {host_key(r["url"]) for _, r in rows}
    if "--offline" in argv:
        with open(INDEX, encoding="utf-8") as fh:
            index = json.load(fh)
    else:
        index = fetch_all(hosts)
    judged, per_host = [], {}
    for path, r in rows:
        key = host_key(r["url"])
        if key not in per_host:
            per_host[key] = parsers(index[key])
        old, new = per_host[key]
        # A request counts as fetched only where a server answered it; a
        # transport failure is recorded with robots_ok True but got nothing.
        recorded = r.get("robots_ok") != "False"
        answered = bool(r.get("http_status"))
        stdlib = old.can_fetch(NAME, r["url"])
        rfc = new.can_fetch(r["url"], NAME)
        status = index[key]["status"]
        basis = ("" if rfc else "a rule" if status and 200 <= status < 300
                 else "robots.txt %s today" % (status or "unanswered"))
        judged.append({"manifest": path, "fetched_at": r.get("fetched_at", ""),
                       "url": r["url"], "method": r.get("request_method", ""),
                       "verdict_reason": r.get("verdict_reason", "")[:80],
                       "robots_status": status or index[key]["error"],
                       "recorded": recorded, "answered": answered,
                       "stdlib": stdlib, "rfc": rfc, "rfc_basis": basis})
    with open(os.path.join(OUT, "rows.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(judged[0]))
        w.writeheader()
        w.writerows(judged)

    print("\n%d recorded requests over %d hosts" % (len(judged), len(hosts)))
    status = collections.Counter(str(v["status"] or v["error"]) for v in index.values())
    print("robots.txt today:", dict(status.most_common()))
    fetched = [j for j in judged if j["recorded"] and j["answered"]]
    refused = [j for j in judged if not j["recorded"]]
    print("fetched %d, refused for robots.txt %d, no answer %d" % (
        len(fetched), len(refused), len(judged) - len(fetched) - len(refused)))
    groups = (
        ("fetched, a rule disallows today",
         [j for j in fetched if j["rfc_basis"] == "a rule"]),
        ("  the old parser allows it today too (its error)",
         [j for j in fetched if j["rfc_basis"] == "a rule" and j["stdlib"]]),
        ("fetched, robots.txt unanswered or 5xx today",
         [j for j in fetched if j["rfc_basis"] not in ("", "a rule")]),
        ("refused, RFC 9309 allows today", [j for j in refused if j["rfc"]]),
        ("  the old parser refuses it today too (its error)",
         [j for j in refused if j["rfc"] and not j["stdlib"]]))
    for label, hit in groups:
        print("%-50s %5d requests, %3d hosts" % (
            label, len(hit), len({host_key(j["url"]) for j in hit})))
    for label, hit in (groups[0], groups[3]):
        print("\n%s, by host:" % label)
        by = collections.Counter(host_key(j["url"]) for j in hit)
        for k, n in by.most_common():
            ex = next(j for j in hit if host_key(j["url"]) == k)
            print("  %4d  %-45s stdlib %-5s e.g. %s" % (
                n, k, ex["stdlib"], urllib.parse.urlsplit(ex["url"]).path[:60]))


if __name__ == "__main__":
    main(sys.argv[1:])
