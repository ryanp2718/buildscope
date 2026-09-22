# -*- coding: utf-8 -*-
"""Spike A, step 2b: reject the URL-pattern probe's false positives.

The pattern probe in spike_a_probe.py guesses hostnames from the place name,
which is name-similarity matching with no authoritative attribute - the exact
method that produced the Marina/Marin County error in the catalog sweep. It
reproduces the same failure here: 'Bowling Green KY' resolves to a Virginia
town's site, 'Brazil IN' to a site about the country, 'Amador City CA' to a
person's homepage.

So every hit is verified against an attribute the place name cannot fake:

  +3  hostname ends .gov or .<st>.us          (municipal TLDs are not squatted)
  +3  page names the correct state, spelled out or as ', ST'
  +2  page names the place
  -4  page names a DIFFERENT state alongside the place ('Bowling Green, VA')
  -5  domain-parking / for-sale / unrelated-business markers

Verified at >= 5 and no negative marker. Everything else goes to manual search.
Writes the verdict back into probe.json.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "data", "spike_a", "probe.json")
HTMLDIR = os.path.join(ROOT, "data", "spike_a", "html")

STATE = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

PARKED = re.compile(
    r"(for sale|domain (is )?(for sale|parking)|buy this domain|spaceship\.com|"
    r"godaddy|sedo\.com|hugedomains|chamber of commerce|realty|real estate|"
    r"church|rod &(amp;)? gun|castings|the media network)", re.I)

SUFFIX = re.compile(
    r"\s+(unincorporated|township|town|village|city|borough|parish)$", re.I)


def core(place):
    n = place
    for _ in range(3):
        n = SUFFIX.sub("", n).strip()
    return n


def main():
    probe = json.load(open(PROBE, encoding="utf-8"))
    ok = bad = none = 0

    for key, rec in sorted(probe.items()):
        if not rec.get("site"):
            rec["verified"] = False
            rec["verdict"] = "no site found by pattern"
            none += 1
            continue

        st = rec["state"]
        full = STATE.get(st, st)
        name = core(rec["place"])
        fn = re.sub(r"[^a-z0-9]+", "_", (st + "_" + rec["place"]).lower()) + "_home.html"
        path = os.path.join(HTMLDIR, fn)
        html = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        hay = (html + " " + rec["site"] + " " + rec["title"])
        host = rec["site"].split("/")[2].lower() if "://" in rec["site"] else ""

        score, why = 0, []
        if host.endswith(".gov") or host.endswith(".%s.us" % st.lower()):
            score += 3
            why.append("+3 gov TLD")
        if re.search(r"\b%s\b" % re.escape(full), hay, re.I) or \
           re.search(r",\s*%s\b" % st, hay):
            score += 3
            why.append("+3 correct state")
        if re.search(r"\b%s\b" % re.escape(name), hay, re.I):
            score += 2
            why.append("+2 place named")

        wrong = [a for a, f_ in STATE.items()
                 if a != st and (re.search(r"%s,\s*%s\b" % (re.escape(name), a), hay)
                                 or re.search(r"%s,\s*%s\b" % (re.escape(name), re.escape(f_)),
                                              hay, re.I))]
        if wrong:
            score -= 4
            why.append("-4 names %s, %s" % (name, "/".join(sorted(set(wrong))[:3])))

        p = PARKED.search(rec["title"]) or PARKED.search(html[:4000])
        if p:
            score -= 5
            why.append("-5 marker %r" % p.group(0)[:30])

        rec["verify_score"] = score
        rec["verified"] = score >= 5 and not wrong and not p
        rec["verdict"] = "; ".join(why) or "no signal"
        if rec["verified"]:
            ok += 1
        else:
            bad += 1
            rec["site_rejected"] = rec.pop("site")
            rec["site"] = None

    json.dump(probe, open(PROBE, "w", encoding="utf-8"), indent=1)

    print("%-30s %-4s %-6s %s" % ("place", "st", "score", "verdict"))
    print("-" * 100)
    for key, rec in sorted(probe.items(), key=lambda kv: -kv[1].get("verify_score", -99)):
        mark = "OK  " if rec.get("verified") else "REJ "
        print("%s %-29s %-4s %-6s %s" % (mark, rec["place"][:29], rec["state"],
                                         rec.get("verify_score", "-"),
                                         rec["verdict"][:60]))
    print("\nverified %d, rejected %d, never found %d, to search by hand %d"
          % (ok, bad, none, bad + none))


if __name__ == "__main__":
    main()
