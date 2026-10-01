# -*- coding: utf-8 -*-
"""The data artifacts, and the numbers the documents quote from them.

This file exists because of the failure recorded at the top of
`docs/evidence/README.md`: the catalog sweep reported **112 offices / 5.0% of
units**, that figure was quoted onward, hand resolution later tripled it to
**180 / 16.63%**, and the original number was not wrong when written - it was
wrong when *re-quoted*, and nothing carried the date forward to say so.

A prose convention cannot prevent that. A test can: every headline figure in
`docs/design/history.md` is recomputed here from the artifact that produced it, and a change
to either side without the other fails the suite. That is the whole idea. These
assertions are *supposed* to fail when a measurement changes - the failure is
the reminder to write a new evidence report and update the prose, not a bug.

The other half is structural: D1's rule that **a page may not exist on disk
without a manifest row written in the same operation**, which is checked
against the actual trees rather than trusted.
"""
import csv
import io
import json
import os
import subprocess
import sys
import unittest

from tests import requires_raw_store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data")
CLASSIFICATION = os.path.join(DATA, "spike_a", "classification.csv")
FRAME = os.path.join(DATA, "frame", "bps_frame.csv")

# The bucket taxonomy, ADR-0004. `unresolved` is not a bucket; it is the
# absence of one, and it must never silently join a coverage aggregate.
BUCKETS = set("01234567")
ENUMERABLE = set("123")
ACQUIRABLE = set("45")


def rows(path):
    with io.open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def script(name, *args):
    """Run a tool or a spike by bare filename.

    `scripts/` holds the maintained tools and `spikes/` the lab notebook; a
    test that asserts on a script's exit code does not care which, so it does
    not have to spell the directory and does not break when one moves.
    """
    for d in ("scripts", "spikes"):
        path = os.path.join(ROOT, d, name)
        if os.path.exists(path):
            break
    else:
        raise AssertionError("no such script: %s" % name)
    return subprocess.run([sys.executable, path, *list(args)],
                          capture_output=True, text=True, cwd=ROOT)


class TestClassificationShape(unittest.TestCase):

    def setUp(self):
        self.rows = rows(CLASSIFICATION)

    def test_sample_size(self):
        self.assertEqual(len(self.rows), 28)

    def test_buckets_are_in_the_taxonomy(self):
        for r in self.rows:
            with self.subTest(office=r["place_name"]):
                self.assertIn(r["bucket"], BUCKETS | {"unresolved"})

    def test_status_is_provisional_or_confirmed(self):
        """ADR-0005: a form-read bucket is provisional; only a demonstrated
        query confirms one."""
        for r in self.rows:
            with self.subTest(office=r["place_name"]):
                self.assertIn(r["status"], ("provisional", "confirmed"))

    def test_confirmed_rows_have_a_demonstrated_basis(self):
        for r in self.rows:
            if r["status"] == "confirmed":
                with self.subTest(office=r["place_name"]):
                    self.assertIn(r["basis"],
                                  ("demonstrated", "mechanically confirmed"))

    def test_identity_matches_the_frame(self):
        """ADR-0007. The name is not the identity and must never be joined on,
        but as a redundant field it is the only thing that makes the identity
        falsifiable - which is how 7 silently-substituted offices were found.

        The classification table is published and the 20,069-row Census frame
        it joins against is not, so this one cross-check is the only test in
        the class that a fresh clone cannot run."""
        requires_raw_store(self, "the identity cross-check against the frame")
        frame = {(r["state"], r["bps_id"]): r for r in rows(FRAME)}
        for r in self.rows:
            key = (r["state"], r["bps_id"])
            with self.subTest(office=r["place_name"]):
                self.assertIn(key, frame, "%s does not resolve" % (key,))
                self.assertEqual(frame[key]["place_name"], r["place_name"])
                self.assertEqual(frame[key]["units_12mo"], r["units_12mo"])

    def test_bps_ids_keep_their_leading_zeros(self):
        for r in self.rows:
            with self.subTest(office=r["place_name"]):
                self.assertEqual(len(r["bps_id"]), 6)
                self.assertEqual(len(r["state"]), 2)

    def test_matches_the_recorded_verdicts(self):
        """A hand edit that contradicts a demonstrated verdict must fail rather
        than sit in the file looking authoritative."""
        p = script("spike_a_reclassify.py", "--check")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestGateArithmetic(unittest.TestCase):
    """The unit-weighted reachability metric, recomputed from the artifact.

    Published in `docs/evidence/2026-09-21-bucket4-resolution.md` and quoted in
    `docs/design/history.md` section 8. ADR-0005 governs how it may be read: **the metric
    may fire the gate but may not clear it.** At n=28 with one row carrying 28%
    of the units, it can catch a domain that is obviously unreachable and
    cannot certify one that is reachable.
    """

    GATE_THRESHOLD = 0.50

    def setUp(self):
        self.rows = rows(CLASSIFICATION)
        self.total = sum(int(r["units_12mo"] or 0) for r in self.rows)

    def share(self, buckets, status=None):
        n = sum(int(r["units_12mo"] or 0) for r in self.rows
                if r["bucket"] in buckets
                and (status is None or r["status"] == status))
        return round(100.0 * n / self.total, 1)

    def test_denominator(self):
        self.assertEqual(self.total, 12932)

    def test_published_shares(self):
        for label, buckets, want in [
                ("enumerable (1-3)", ENUMERABLE, 56.7),
                ("acquirable (4-5)", ACQUIRABLE, 12.9),
                ("reachable (1-5)", ENUMERABLE | ACQUIRABLE, 69.5),
                ("bucket 4 alone", set("4"), 2.3),
                ("fallback floor (1-3, 5)", ENUMERABLE | set("5"), 67.3)]:
            with self.subTest(aggregate=label):
                self.assertEqual(self.share(buckets), want)

    def test_unresolved_is_excluded_from_every_aggregate(self):
        """`unresolved` is the absence of a bucket. Counting it anywhere would
        improve a coverage statistic by not knowing something."""
        self.assertGreater(self.share({"unresolved"}), 0)
        self.assertEqual(
            round(self.share(ENUMERABLE | ACQUIRABLE)
                  + self.share(set("67")) + self.share({"unresolved"}), 1),
            100.0)

    def test_gate_does_not_fire(self):
        self.assertGreater(self.share(ENUMERABLE | ACQUIRABLE) / 100.0,
                           self.GATE_THRESHOLD)

    def test_gate_does_not_fire_even_on_confirmed_rows_alone(self):
        """The robustness statement worth more than the headline: if every
        provisional reachable row turned out wrong, the gate still would not
        fire. Confirmed-reachable alone is 58.9%."""
        confirmed = self.share(ENUMERABLE | ACQUIRABLE, status="confirmed")
        self.assertEqual(confirmed, 58.9)
        self.assertGreater(confirmed / 100.0, self.GATE_THRESHOLD)

    def test_all_enumerable_mass_is_confirmed(self):
        """The provisional rows sit in the unreachable buckets, so they can
        only move the number up. That is the safe direction of error."""
        self.assertEqual(self.share(ENUMERABLE),
                         self.share(ENUMERABLE, status="confirmed"))

    def test_bucket_zero_is_absent_and_that_is_deliberate(self):
        """ADR-0004: bucket 0 requires a positive basis, never absence of
        evidence, because it is the only cell that improves the coverage
        statistic by being assigned."""
        self.assertEqual([r for r in self.rows if r["bucket"] == "0"], [])


class TestCaptureInvariant(unittest.TestCase):
    """D1, as implemented by the capture layer: a page may not exist on disk
    without a manifest row written in the same operation, and every analysis
    reads the manifest rather than the directory.

    Spike C found that Spike A's saved bytes did not carry their verdicts, so
    pages the verifier had rejected - an iron castings foundry among them -
    walked back into a downstream analysis as municipal websites.
    """

    TREES = ("measure", "spike_b", "step1")

    def trees(self):
        for t in self.TREES:
            man = os.path.join(DATA, t, "manifest.csv")
            if os.path.exists(man):
                yield t, man, os.path.join(DATA, t, "pages")

    def test_at_least_one_tree_exists(self):
        requires_raw_store(self, "the capture-invariant check")
        self.assertTrue(list(self.trees()), "no capture trees on disk")

    def test_no_page_without_a_manifest_row(self):
        for t, man, pages in self.trees():
            named = {r["file"] for r in rows(man) if r.get("file")}
            disk = set(os.listdir(pages)) if os.path.isdir(pages) else set()
            with self.subTest(tree=t):
                self.assertEqual(
                    sorted(disk - named), [],
                    "pages on disk with no manifest row: their verdicts do "
                    "not exist and an analysis reading the directory would "
                    "pick them up")

    def test_no_manifest_row_naming_a_missing_page(self):
        for t, man, pages in self.trees():
            named = {r["file"] for r in rows(man) if r.get("file")}
            disk = set(os.listdir(pages)) if os.path.isdir(pages) else set()
            with self.subTest(tree=t):
                self.assertEqual(sorted(named - disk), [])

    def test_every_row_carries_a_verdict(self):
        for t, man, _ in self.trees():
            for r in rows(man):
                with self.subTest(tree=t, url=r["url"][:60]):
                    self.assertTrue(r["verdict"])
                    self.assertIn(r["verdict"],
                                  ("ok", "rejected", "unknown"))

    def test_manifest_has_the_fingerprint_column(self):
        """Section 9, obligation 3. A fingerprint not taken at capture cannot
        be taken later for a page that has since changed."""
        for t, man, _ in self.trees():
            with self.subTest(tree=t):
                self.assertIn("fp", rows(man)[0].keys())

    def test_fingerprints_are_versioned_and_html_only(self):
        from permits import fingerprint as fp
        for t, man, _ in self.trees():
            for r in rows(man):
                if not r.get("fp"):
                    continue
                with self.subTest(tree=t, file=r.get("file")):
                    v, h = fp.parse(r["fp"])
                    self.assertEqual(v, fp.VERSION)
                    self.assertNotEqual(
                        h, "da39a3ee5e6b",
                        "the sha1 of an empty path set was stored as a "
                        "fingerprint; a body with no DOM has no template")


class TestRecordStore(unittest.TestCase):

    def jsonl(self):
        d = os.path.join(DATA, "step1", "records")
        if not os.path.isdir(d):
            return []
        return [os.path.join(d, f) for f in sorted(os.listdir(d))
                if f.endswith(".jsonl")]

    def test_records_exist(self):
        requires_raw_store(self, "the record-store check")
        self.assertTrue(self.jsonl(), "no step-1 record files")

    def test_every_record_is_wellformed_and_identified(self):
        from permits import emit
        for path in self.jsonl():
            with io.open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 2000:                 # a sample is enough per file
                        break
                    d = json.loads(line)
                    with self.subTest(file=os.path.basename(path), line=i):
                        self.assertTrue(d["observation_key"])
                        self.assertEqual(len(d["state_fips"]), 2)
                        self.assertEqual(len(d["bps_id"]), 6)
                        self.assertIn(d["permit_kind"], emit.PERMIT_KINDS)
                        self.assertIn(d["work_class"], emit.WORK_CLASSES)
                        self.assertIn(d["unit_count_source"],
                                      emit.UNIT_SOURCES)

    def test_absent_never_carries_a_count(self):
        for path in self.jsonl():
            with io.open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 2000:
                        break
                    d = json.loads(line)
                    if d["unit_count_source"] == "absent":
                        with self.subTest(file=os.path.basename(path), line=i):
                            self.assertIsNone(d["unit_count"])

    def test_implied_units_match_their_class(self):
        from permits import emit
        for path in self.jsonl():
            with io.open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 2000:
                        break
                    d = json.loads(line)
                    if d["unit_count_source"] != "implied_by_structure_code":
                        continue
                    with self.subTest(file=os.path.basename(path), line=i):
                        self.assertEqual(d["unit_count"],
                                         emit.IMPLIED_UNITS.get(
                                             d["structure_type"]))

    def test_non_building_permits_contribute_no_units(self):
        """The Austin 726% trap, checked against what was actually written."""
        for path in self.jsonl():
            with io.open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 2000:
                        break
                    d = json.loads(line)
                    if d["permit_kind"] != "BUILDING" or d["work_class"] != "NEW":
                        with self.subTest(file=os.path.basename(path), line=i):
                            self.assertEqual(d["countable_units"], 0)


class TestNoStaleCopies(unittest.TestCase):
    """No undated backup copies of authoritative artifacts.

    `data/spike_a/classification.csv.bak` sat beside the file ADR-0005 names
    as the single source of bucket and identity. It held the same 28 offices
    with the same buckets and **all 28 office ids wrong** - the state before
    the identity correction - with no date and nothing marking it superseded.
    That is precisely the shape of the 112-to-180 re-quoting failure: a
    plausible artifact that was correct once.

    `check_identity.py` did not catch it either, because it scans `.csv` and
    `.json` and that file ends in `.bak`. A suffix is not a quarantine. The
    rule is simpler than teaching the checker every extension: authoritative
    artifacts do not get shadow copies, and a superseded state is recorded in
    a dated evidence report rather than in a sibling file.
    """

    SUFFIXES = (".bak", ".old", ".orig", ".copy", ".save", "~")

    def test_no_backup_files_in_data(self):
        found = []
        for dirpath, _, files in os.walk(DATA):
            for f in files:
                if f.endswith(self.SUFFIXES) or ".csv." in f or ".json." in f:
                    found.append(os.path.relpath(os.path.join(dirpath, f),
                                                 ROOT))
        self.assertEqual(
            sorted(found), [],
            "undated shadow copies of data artifacts: %s. Record the "
            "superseded state in a dated evidence report, not in a sibling "
            "file that looks authoritative." % ", ".join(sorted(found)))


class TestCheckersPass(unittest.TestCase):
    """The standing checks, run as tests so that `run_tests.py` is the single
    thing to run rather than three things to remember."""

    def test_docs(self):
        p = script("check_docs.py")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_identity(self):
        p = script("check_identity.py")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_internal(self):
        """INTERNAL/ is prep material, not part of the project -- but a stale
        figure there is quoted out loud to someone who can check it, which is
        the one place this project cannot afford to be wrong. `numbers.md`
        carried "$0 total inference spend" as a headline after $1.2751 had
        been spent, and nothing caught it."""
        p = script("check_internal.py")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
