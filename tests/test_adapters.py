# -*- coding: utf-8 -*-
"""Adapters, replayed against the bytes actually on disk.

This is the part of the suite that is not a unit test. D1 makes the raw store
the source of truth and every downstream stage a pure function of it, which
means the corpus in `data/step1/pages/` is a golden set that cost nothing to
build and can be replayed for free. Replay has already paid for itself three
times in this project - the Clark milestone vocabulary bug (20 of 371 records),
the `norm_date` null-out, and the truncated page - each caught at zero requests.

Three properties are asserted and they are not interchangeable:

  **Structural.** The index grid still parses, and the column order is still
  what the adapter asserts. St. Johns' grid is positional, so a reordered
  column would silently swap address into PropUse and classify every record off
  a street name.

  **Volumetric.** A page that yielded N rows yesterday yields N today. This is
  what catches a regex that still matches but matches less.

  **Semantic.** `page_is_complete` still reads the vendor's truncation banner.
  A manifest verdict of `ok` means the *fetch* succeeded, not that the content
  is complete - ADR-0006's boundary - and only an adapter can tell the
  difference.

If the corpus is absent these skip rather than fail. A missing raw store is a
different problem from a broken adapter and should not masquerade as one.
"""
import glob
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import emit, vocab                         # noqa: E402
from permits.adapters import accela, stjohns            # noqa: E402

PAGES = os.path.join(ROOT, "data", "step1", "pages")


def read(name):
    p = os.path.join(PAGES, name)
    if not os.path.exists(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def some(pattern):
    return sorted(glob.glob(os.path.join(PAGES, pattern)))


def stjohns_pages():
    """Weekly index captures, named sj_stjohns_MMDDYYYY_MMDDYYYY.html.

    Excludes sj_stjohns_form*.html, which are search forms rather than result
    grids. The first version of this glob was `sj_stjohns_2*.html`, which
    matched nothing because the names start with a zero-padded month - and the
    suite reported `OK (skipped=5)`, which is what a disabled test looks like
    when nobody is checking.
    """
    return [f for f in some("sj_stjohns_[0-9]*.html")
            if "_form" not in os.path.basename(f)]


# Page families the replay tests depend on. Named here so that a rename makes
# `TestGoldenCorpus` fail loudly instead of turning the replay suite into a row
# of silent skips.
GOLDEN = {"St. Johns weekly index": ("sj_stjohns_[0-9]*.html", 10),
          "Accela index": ("acc_clarkco_20260302_p*.html", 10),
          "St. Johns truncated control": ("b4_stjohns_control.html", 1)}


class TestStJohnsIndex(unittest.TestCase):

    def setUp(self):
        self.files = stjohns_pages()
        if not self.files:
            self.skipTest("no St. Johns index pages in the raw store")

    def test_every_stored_index_parses(self):
        total = 0
        for f in self.files:
            with io.open(f, encoding="utf-8", errors="replace") as fh:
                rows, trunc = stjohns.parse_index(fh.read())
            with self.subTest(page=os.path.basename(f)):
                self.assertIsInstance(rows, list)
                total += len(rows)
        self.assertGreater(total, 100,
                           "the stored St. Johns corpus yielded almost no "
                           "rows; the grid regex or the column assertion has "
                           "drifted")

    def _mutate_header(self, html, old, new):
        """Rewrite a header cell inside the result grid only.

        The first attempt at this replaced the first `PermitNo` anywhere in the
        document, which lands in a `__doPostBack` sort handler thousands of
        bytes above the grid - so the header was untouched and the test failed
        by passing the wrong page in. Mutating the grid segment is the
        difference between testing the assertion and testing a string replace.
        """
        i = html.find(stjohns.GRID)
        self.assertGreaterEqual(i, 0, "grid marker absent from this capture")
        head, seg = html[:i], html[i:i + 4000]
        self.assertIn(old, seg, "header %r not in the grid segment" % old)
        return head + seg.replace(old, new, 1) + html[i + 4000:]

    def test_renamed_column_raises(self):
        """A renamed column must raise, not silently mis-map. The grid carries
        no role markers, so nothing downstream could notice."""
        html = read(os.path.basename(self.files[0]))
        with self.assertRaises(ValueError):
            stjohns.parse_index(self._mutate_header(html, "PermitNo", "ZZZ"))

    def test_reordered_columns_raise(self):
        """The failure that actually costs money: the columns are all still
        there, in the wrong order, so every record gets classified off a street
        name instead of a property-use code."""
        html = read(os.path.basename(self.files[0]))
        swapped = self._mutate_header(html, ">Addr<", ">__TMP__<")
        swapped = self._mutate_header(swapped, ">PropUse<", ">Addr<")
        swapped = self._mutate_header(swapped, ">__TMP__<", ">PropUse<")
        self.assertEqual(stjohns.headers(swapped)[1:3], ["propuse", "addr"])
        with self.assertRaises(ValueError):
            stjohns.parse_index(swapped)

    def test_unmodified_capture_does_not_raise(self):
        """The other half of the assertion: it must not fire on a good page."""
        html = read(os.path.basename(self.files[0]))
        rows, _ = stjohns.parse_index(html)
        self.assertIsInstance(rows, list)

    def test_rows_carry_identifiers(self):
        with io.open(self.files[0], encoding="utf-8", errors="replace") as fh:
            rows, _ = stjohns.parse_index(fh.read())
        if not rows:
            self.skipTest("this capture has no rows")
        for r in rows:
            self.assertTrue(r.get("number"))
            self.assertEqual(set(stjohns.COLUMNS) - set(r), set())

    def test_dates_survive_normalization(self):
        """The regression that mattered: St. Johns renders
        "3/2/2026 11:06:49 PM" and every date came back None."""
        with io.open(self.files[0], encoding="utf-8", errors="replace") as fh:
            rows, _ = stjohns.parse_index(fh.read())
        dated = [r for r in rows if r.get("issued")]
        if not dated:
            self.skipTest("this capture has no issued dates")
        got = [emit.norm_date(r["issued"]) for r in dated]
        self.assertTrue(all(g is not None for g in got),
                        "norm_date nulled a St. Johns date again")


class TestTruncationDetection(unittest.TestCase):
    """ADR-0006: `ok` means the fetch succeeded, not that the content is
    complete. Completeness is an adapter question."""

    def test_the_truncated_capture_is_detected(self):
        html = read("b4_stjohns_control.html")
        if html is None:
            self.skipTest("truncated control capture not present")
        self.assertFalse(stjohns.page_is_complete(html),
                         "the known-truncated page no longer reads as "
                         "truncated; the vendor banner regex has drifted")

    def test_a_normal_capture_is_complete(self):
        files = stjohns_pages()
        if not files:
            self.skipTest("no St. Johns index pages")
        ok = []
        for f in files:
            with io.open(f, encoding="utf-8", errors="replace") as fh:
                if stjohns.page_is_complete(fh.read()):
                    ok.append(f)
        self.assertTrue(ok, "every stored page reads as truncated, which "
                            "means the banner regex now matches everything")

    def test_truncation_is_reported_by_parse_index_too(self):
        html = read("b4_stjohns_control.html")
        if html is None:
            self.skipTest("truncated control capture not present")
        _, trunc = stjohns.parse_index(html)
        self.assertTrue(trunc)


class TestAccelaIndex(unittest.TestCase):

    def setUp(self):
        self.files = some("acc_clarkco_20260302_p*.html")
        if not self.files:
            self.skipTest("no Accela index pages in the raw store")

    def test_every_stored_index_parses(self):
        total = 0
        for f in self.files:
            with io.open(f, encoding="utf-8", errors="replace") as fh:
                rows = accela.parse_index(fh.read())
            total += len(rows if isinstance(rows, list) else rows[0])
        self.assertGreater(total, 100,
                           "the stored Clark County corpus yielded almost no "
                           "rows")

    def test_page_completeness_hook_exists(self):
        """Both HTML adapters must answer the completeness question; a
        synthesized extractor at step 4 has to as well."""
        for mod in (accela, stjohns):
            with self.subTest(adapter=mod.__name__):
                self.assertTrue(callable(getattr(mod, "page_is_complete", None)))


class TestAdapterInterface(unittest.TestCase):
    """D8's shared emit interface, checked as an interface rather than
    described as one. Three platforms now implement it - open-data, Accela and
    St. Johns' WATS/.NET - and the third needed one new `UNIT_SOURCES` value
    and no schema change."""

    ADAPTERS = ("opendata", "accela", "stjohns")

    def test_all_adapters_expose_the_same_surface(self):
        import importlib
        for name in self.ADAPTERS:
            mod = importlib.import_module("permits.adapters." + name)
            with self.subTest(adapter=name):
                for attr in ("build", "vocabulary_for", "ADAPTER_VERSION"):
                    self.assertTrue(hasattr(mod, attr),
                                    "%s is missing %s" % (name, attr))

    def test_adapter_versions_are_namespaced(self):
        import importlib
        seen = set()
        for name in self.ADAPTERS:
            mod = importlib.import_module("permits.adapters." + name)
            v = mod.ADAPTER_VERSION
            self.assertIn("/", v, "%s version %r has no platform prefix"
                          % (name, v))
            self.assertNotIn(v, seen, "duplicate ADAPTER_VERSION %r" % v)
            seen.add(v)

    def test_vocabulary_tallies_unmapped_strings(self):
        """A classifier returning UNKNOWN for 40% of a jurisdiction has not
        classified it, and the only way to know is to keep the strings it
        failed on."""
        vb = vocab.Vocabulary("test", "test")
        self.assertEqual(vb.unmapped, {})
        vb.by_code("NOT-A-REAL-CODE")
        self.assertTrue(vb.unmapped)

    def test_code_table_is_exact_not_prefix(self):
        """St. Johns publishes 329 (pool) and 329E (pool enclosure), 435
        (residential roof) and 435C (commercial roof). A prefix match merges a
        code with its own variants."""
        table = {"329": vocab.spec("pool"), "329E": vocab.spec("pool encl")}
        vb = vocab.Vocabulary("test", "test", code_table=table)
        self.assertEqual(vb.by_code("329")[0].label, "pool")
        self.assertEqual(vb.by_code("329E")[0].label, "pool encl")
        self.assertEqual(vb.by_code("329X")[0], None)


class TestStJohnsCodeTable(unittest.TestCase):
    """The published-vocabulary finding: St. Johns' entire structure
    classification comes from a code table the county renders in its own
    search form, fetched for zero extra requests."""

    def test_only_determinate_codes_imply_units(self):
        bad = []
        for code, spec in stjohns.PROPUSE.items():
            if spec.units is None:
                continue
            if spec.structure not in emit.IMPLIED_UNITS:
                bad.append((code, spec.structure, spec.units))
            elif emit.IMPLIED_UNITS[spec.structure] != spec.units:
                bad.append((code, spec.structure, spec.units))
        self.assertEqual(bad, [],
                         "a code implies a unit count its BPS class does not: "
                         "104 is 'three OR four' and 105 is 'five or more'")

    def test_structure_codes_are_in_the_closed_vocabulary(self):
        for code, spec in stjohns.PROPUSE.items():
            if spec.structure is None:
                continue
            with self.subTest(code=code):
                self.assertIn(spec.structure, emit.STRUCTURE_TYPES)

    def test_kinds_and_work_classes_are_in_the_closed_vocabulary(self):
        for code, spec in stjohns.PROPUSE.items():
            with self.subTest(code=code):
                self.assertIn(spec.kind, emit.PERMIT_KINDS)
                self.assertIn(spec.work, emit.WORK_CLASSES)


class TestGoldenCorpus(unittest.TestCase):
    """The replay suite is only worth having if it is actually running.

    Every other class here skips when its pages are missing, which is right -
    an absent raw store is a different problem from a broken adapter. But a
    suite of skips reports `OK`, so the absence has to be asserted somewhere,
    once, loudly. This is that place.
    """

    def test_raw_store_present(self):
        self.assertTrue(os.path.isdir(PAGES),
                        "data/step1/pages/ is missing: every replay test in "
                        "this file is silently skipping")

    def test_expected_page_families_present(self):
        for label, (pattern, least) in sorted(GOLDEN.items()):
            with self.subTest(family=label):
                found = len(some(pattern))
                self.assertGreaterEqual(
                    found, least,
                    "%s: expected at least %d pages matching %r, found %d. "
                    "If the captures were renamed, update GOLDEN - do not "
                    "leave the replay tests skipping."
                    % (label, least, pattern, found))


if __name__ == "__main__":
    unittest.main()
