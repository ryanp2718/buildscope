# -*- coding: utf-8 -*-
"""Apply demonstrated bucket verdicts to `data/spike_a/classification.csv`.

ADR-0005 makes `classification.csv` the single source of bucket and identity,
and distinguishes a `provisional` bucket - read off a rendered search form -
from a `confirmed` one, which requires a demonstrated pull or a demonstrated
refusal. Until this script ran, the file carried no such column and every row
looked equally certain, including the twenty-six nobody has ever queried.

This is idempotent and declarative: `VERDICTS` below is the whole change, each
entry citing the evidence report that demonstrated it. Re-running it rewrites
the same file with the same content. Rows not named here become `provisional`
without their bucket changing, which is a statement about what is *known*
rather than a change of classification.

Run with `--check` to verify the file already matches; that mode is what the
test suite calls, so a hand edit that contradicts a demonstrated verdict fails
rather than sitting there looking authoritative.
"""
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "spike_a", "classification.csv")

# (state, bps_id) -> (bucket, vendor, confidence, basis, note)
#
# `confirmed` means a query was sent and the *response* settles the bucket -
# records came back, or a refusal was demonstrated. It does not mean a human
# looked at the search form and formed a view. Everything else is
# `provisional`, which is a conservative label: it covers both pure form reads
# and probes whose response was read wrongly.
#
# That conservatism is not theoretical. St. Johns' `probed` note read "empty
# criteria returned the form, not a result set", which was true and led to the
# wrong bucket, because nobody tried a date range. A basis of `probed` has
# already produced one false bucket worth 28% of the sample's units, so it does
# not clear the bar.
#
# Every entry below was demonstrated by a request whose bytes are in
# data/step1/pages/ with a manifest row in data/step1/manifest.csv.
VERDICTS = {
    ("32", "021000"): (
        "3", "Accela ACA", "high", "demonstrated",
        "empty-criteria POST returns a result set; 531 records pulled across "
        "57 index pages. Cap indicator '100+' means date partitioning is "
        "required, not that enumeration fails."),
    ("41", "323000"): (
        "3", "Accela ACA (statewide tenancy)", "medium", "mechanically confirmed",
        "served by aca-oregon.accela.com, a statewide Accela instance; empty "
        "criteria returned a result set. Query demonstrated, records never "
        "pulled - confirmed as enumerable, unconfirmed as extractable."),
    ("12", "803000"): (
        "3", "custom (WATS .NET)", "high", "demonstrated",
        "date-range POST returns a full result set; 3,872 records pulled and "
        "reconciled against BPS. Was provisional bucket 4 on a form read."),
    ("29", "607000"): (
        "4", "custom (ColdFusion)", "high", "demonstrated",
        "parcel-keyed two-step: empty and wildcard streetAddress both refused, "
        "a known address returns a parcel-disambiguation table, not permits. "
        "The 2026 portal stlcitypermits.com is apply-and-pay only, no record "
        "search. Note that the old form posts to itself, not searchresults.cfm."),
    ("21", "045000"): (
        "7", "Tyler eSuite", "high", "demonstrated",
        "portal is esuites.bgky.org (Tyler eSuite), not the unreachable "
        "www2.bgky.org recorded earlier - the real host was in Spike A's own "
        "saved bytes. Contractor login, electrical permits only, apply and pay; "
        "no permit record search exists for any visitor. Registration is not "
        "expected to yield records, which bucket 7 does not distinguish."),
}

FIELDS = ["state", "bps_id", "county", "state_abbr", "place_name", "stratum",
          "units_12mo", "bucket", "status", "vendor", "confidence", "basis",
          "note"]


def build(rows):
    out = []
    for r in rows:
        r = dict(r)
        v = VERDICTS.get((r["state"], r["bps_id"]))
        if v:
            r["bucket"], r["vendor"], r["confidence"], r["basis"], r["note"] = v
            r["status"] = "confirmed"
        else:
            r.setdefault("status", "provisional")
            r["status"] = "provisional"
        out.append(dict((f, r.get(f, "")) for f in FIELDS))
    return out


def render(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def main(argv):
    with io.open(PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    want = render(build(rows))
    have = io.open(PATH, encoding="utf-8").read()
    if "--check" in argv:
        if have.replace("\r\n", "\n") != want:
            sys.stderr.write(
                "classification.csv does not match the demonstrated verdicts "
                "in spike_a_reclassify.py; run the script without --check\n")
            return 1
        print("classification.csv matches %d demonstrated verdicts"
              % len(VERDICTS))
        return 0
    with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(want)
    conf = sum(1 for r in build(rows) if r["status"] == "confirmed")
    print("wrote %s: %d rows, %d confirmed, %d provisional"
          % (os.path.relpath(PATH, ROOT), len(rows), conf, len(rows) - conf))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
