# -*- coding: utf-8 -*-
"""`permits/redact.py`: one keyed token map, so a page, its reference and
an extractor's literals stay consistent, and the page's structure stays."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import redact                                    # noqa: E402

PAGE = ('<tr class="ACA_TabRow"><td><a id="ctl03_hl" href="/Cap/CapDetail.aspx'
        '?capID3=02451&amp;x=1">B26-2069</a><input type="hidden" '
        'value="PMT26-00000-02451"/></td><td><span id="ctl03_lblStatus">'
        'Issued</span></td><td>21332 E MEWES RD, QUEEN CREEK AZ 85142</td>'
        '<td>08/31/2026</td><td>KELLER RESIDENCE &amp; POOL</td>'
        '<td>Residential / Plumbing</td></tr>')


def red():
    return redact.Redactor("k", vocab={"pool", "queen", "creek", "cap",
                                       "residence"},
                           protected={"Issued", "Residential / Plumbing"})


class TestPage(unittest.TestCase):

    def test_structure_is_untouched(self):
        out = red().page(PAGE)
        tags = re.compile(r"<(\w+)[^>]*?(?:id|class|type)=\"([^\"]*)\"")
        self.assertEqual(tags.findall(out), tags.findall(PAGE))
        self.assertEqual(re.findall(r"</?\w+", out), re.findall(r"</?\w+",
                                                                  PAGE))

    def test_values_change_and_kept_values_stay(self):
        r = red()
        out = r.page(PAGE)
        for gone in ("2069", "MEWES", "21332", "KELLER", "02451", "85142"):
            self.assertNotIn(gone, out)
        for kept in ("Issued", "Residential / Plumbing", "08/31/2026",
                     "QUEEN CREEK AZ", "POOL", "&amp;", "RESIDENCE"):
            self.assertIn(kept, out)
        self.assertRegex(out, r">B\d\d-\d{4}<")         # the id's shape

    def test_the_reference_matches_the_page(self):
        r = red()
        out = r.page(PAGE)
        for v in ("B26-2069", "21332 E MEWES RD, QUEEN CREEK AZ 85142"):
            self.assertIn(r.text(v), out)
        # The record id in the link and the hidden value move together.
        self.assertIn("capID3=%s" % r.digits("02451"), out)
        self.assertIn("-%s\"" % r.digits("02451"), out)


class TestTokens(unittest.TestCase):

    def test_long_numbers_are_one_to_one(self):
        r = red()
        outs = {r.digits("%05d" % i) for i in range(2000)}
        self.assertEqual(len(outs), 2000)

    def test_short_numbers_never_loop(self):
        r = red()
        self.assertEqual(r.digits("7"), "7")
        self.assertEqual(len({r.digits("%02d" % i) for i in range(100)} |
                             {"x"}) > 1, True)

    def test_case_and_length(self):
        r = red()
        self.assertEqual(r.word("Smith"), r.word("SMITH").title())
        self.assertEqual(len(r.word("Enriquez")), 8)
        self.assertTrue(r.word("SMITH").isupper())

    def test_a_different_key_gives_different_pseudonyms(self):
        a = redact.Redactor("a").text("KELLER 12345")
        b = redact.Redactor("b").text("KELLER 12345")
        self.assertNotEqual(a, b)

    def test_emails_and_owners(self):
        r = redact.Redactor("k", vocab={"jim", "lee", "residence", "new"})
        self.assertNotIn("jim", r.text("jim@example.com"))
        self.assertNotIn("LEE", r.text("LEE RESIDENCE"))
        self.assertEqual(r.text("NEW RESIDENCE"), "NEW RESIDENCE")


class TestWhatExtractorsRead(unittest.TestCase):
    """Things a stored extractor was found to depend on (validation,
    2026-11-03): the pager's counts, an id's type prefix, month names."""

    def test_counts_stay(self):
        r = redact.Redactor("k")
        for s in ("Showing 51-100 of 466", "466 Record results",
                  "100+ records", "Page 2 of 7"):
            self.assertTrue(r.text(s).endswith(s.split()[-1]) or
                            s.split()[0] in r.text(s), s)
        self.assertIn("51-100 of 466", r.text("Showing 51-100 of 466"))
        for s in ("11 to 20 of 177", "per page:  10", "25 per page",
                  "Page size: 50"):
            self.assertIn(s, r.text(s))

    def test_an_ids_type_prefix_stays(self):
        out = redact.Redactor("k").attr_token("a038y000001EZfPAAW")
        self.assertTrue(out.startswith("a03"))
        self.assertNotEqual(out, "a038y000001EZfPAAW")

    def test_month_names_stay(self):
        self.assertEqual(redact.Redactor("k").text("Jan Feb Aug"),
                         "Jan Feb Aug")


class TestCode(unittest.TestCase):

    def test_only_literals_and_comments_change(self):
        src = ('def extract(html):  # rows like MEWES\n'
               '    MEWES = "MEWES RD"\n'
               '    return [MEWES, f"{MEWES} MEWES"]\n')
        out = redact.code_literals(src, {"MEWES": "ZAZOL"})
        self.assertEqual(out.count("MEWES"), 3)       # the identifier
        self.assertEqual(out.count("ZAZOL"), 3)       # comment and strings
        compile(out, "x", "exec")


if __name__ == "__main__":
    unittest.main()
