# -*- coding: utf-8 -*-
"""Normalization: the shared layer, and therefore the shared bug.

`norm_date` nulled **100% of St. Johns County's dates** while the adapter
looked like it was working, because a fixed-width slice took the first ten
characters of `"3/2/2026 11:06:49 PM"` and handed `strptime` the string
`"3/2/2026 1"`. Nothing raised. The adapter reported records, the records had
no dates, and the reconciliation had nothing to fold by.

This is the cost side of a shared emit interface that ADR-0009 names: one bug
in common code is one bug in every jurisdiction at once. The interface is still
worth having - that is the same property seen from the other side - but the
shared layer is where tests earn the most, so it gets the most here.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import emit                                # noqa: E402


class TestNormDate(unittest.TestCase):

    def test_stjohns_regression(self):
        """The exact string that produced the 100% null rate."""
        self.assertEqual(emit.norm_date("3/2/2026 11:06:49 PM"), "2026-03-02")

    def test_formats(self):
        cases = [
            # (input, expected) - every one of these appears in a real source
            ("2026-03-02", "2026-03-02"),
            ("03/02/2026", "2026-03-02"),
            ("3/2/2026", "2026-03-02"),
            ("2026/03/02", "2026-03-02"),
            ("02-Mar-2026", "2026-03-02"),
            ("03-02-2026", "2026-03-02"),
            ("2026-03-02T00:00:00", "2026-03-02"),
            ("2026-03-02 14:30:00", "2026-03-02"),
            ("Mar 02, 2026", "2026-03-02"),
            ("  2026-03-02  ", "2026-03-02"),
            # unpadded with a time, in several shapes - the regression family
            ("1/9/2026 9:05:00 AM", "2026-01-09"),
            ("12/31/2025 11:59:59 PM", "2025-12-31"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(emit.norm_date(raw), want)

    def test_arcgis_epoch_millis(self):
        """ArcGIS esriFieldTypeDate is epoch ms, UTC. A silent drop here
        empties a whole month."""
        self.assertEqual(emit.norm_date(1772409600000), "2026-03-02")
        self.assertEqual(emit.norm_date("1772409600000"), "2026-03-02")

    def test_junk_is_none_not_an_exception(self):
        for raw in (None, "", "   ", "n/a", "N/A", "--", "pending", "0",
                    "not issued", "TBD"):
            with self.subTest(raw=raw):
                self.assertIsNone(emit.norm_date(raw))

    def test_no_silent_year_invention(self):
        """A date with no year must not become one with a year."""
        for raw in ("03/02", "Mar 2", "02-Mar"):
            with self.subTest(raw=raw):
                self.assertIsNone(emit.norm_date(raw))


class TestNormInt(unittest.TestCase):

    def test_values(self):
        cases = [("12", 12), ("1,200", 1200), (7, 7), (7.9, 7), ("0", 0),
                 ("-3", -3), ("12 units", 12), ("approx 200 units", 200)]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(emit.norm_int(raw), want)

    def test_absent(self):
        for raw in (None, "", "none", "n/a", "many"):
            with self.subTest(raw=raw):
                self.assertIsNone(emit.norm_int(raw))

    def test_zero_is_not_none(self):
        """"0 units" and "no unit field" are different facts. If norm_int
        collapsed 0 to None the distinction would die before
        `unit_count_source` ever saw it."""
        self.assertEqual(emit.norm_int("0"), 0)
        self.assertIsNotNone(emit.norm_int("0"))


class TestNormText(unittest.TestCase):

    def test_whitespace_collapse(self):
        self.assertEqual(emit.norm_text("  NEW   SFR\n\tDETACHED "),
                         "NEW SFR DETACHED")

    def test_empty(self):
        self.assertIsNone(emit.norm_text(None))
        self.assertIsNone(emit.norm_text(""))


if __name__ == "__main__":
    unittest.main()
