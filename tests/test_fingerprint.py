# -*- coding: utf-8 -*-
"""Structural fingerprints, and the two ways a fingerprint lies.

Spike C's headline - 1.00 fingerprints per jurisdiction at every threshold down
to J = 0.60 - killed D8's cost model, so the fingerprinter is load-bearing for a
*negative* result. A negative result computed by a broken parser is worthless,
which is why `test_reproduces_spike_c` pins the published number to the corpus
on disk rather than to a remembered figure.

The two lies:

  **Collision on absence.** A JSON body has no DOM, so it yields zero paths and
  the sha1 of the empty string, which every JSON body shares. The first
  back-fill over the raw store duly reported a template "shared across" Austin,
  Charlotte, Columbus, Nashville and Seattle - five unrelated open-data APIs
  with no HTML in common because they have no HTML at all.

  **Comparison across rule changes.** `VOID` and `OPAQUE` are exactly the kind
  of thing that gets tuned later. A stored hash that does not say which rules
  produced it is the same failure as a quoted number that does not say when it
  was measured.
"""
import glob
import io
import os
import sys
import unittest

from tests import requires_raw_store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import fingerprint as fp                   # noqa: E402

PAGE = """<html><body><div class="a" id="x"><ul>
<li>Permit 1</li><li>Permit 2</li></ul><p>text</p></div></body></html>"""


class TestSkeleton(unittest.TestCase):

    def test_text_and_attributes_do_not_affect_the_hash(self):
        """The fingerprint is structure. Two pages differing only in content
        must be the same template."""
        other = """<html><body><div class="ZZZ" id="q"><ul>
<li>Permit 9999</li><li>Totally different</li></ul><p>x</p></div></body></html>"""
        self.assertEqual(fp.fingerprint(PAGE).hash, fp.fingerprint(other).hash)

    def test_structure_changes_do_affect_the_hash(self):
        changed = PAGE.replace("<p>text</p>", "<table><tr><td>t</td></tr></table>")
        self.assertNotEqual(fp.fingerprint(PAGE).hash,
                            fp.fingerprint(changed).hash)

    def test_scripts_and_styles_are_opaque(self):
        noisy = PAGE.replace("<p>text</p>",
                             "<script>var a=[1,2,3];</script>"
                             "<style>.a{color:red}</style><p>text</p>")
        self.assertEqual(fp.fingerprint(PAGE).hash, fp.fingerprint(noisy).hash)

    def test_malformed_markup_does_not_raise(self):
        """Municipal HTML is not well-formed. A parser that gives up on the
        first stray </div> fingerprints nothing."""
        for bad in ("<div><span></div></span>", "<p><p><p>", "</div></div>",
                    "<table><tr><td>x", "<<>>", "<div " + "a" * 5000):
            with self.subTest(html=bad[:24]):
                f = fp.fingerprint(bad)
                self.assertIsInstance(f.hash, str)

    def test_pathological_nesting_is_bounded(self):
        deep = "<div>" * 5000 + "x" + "</div>" * 5000
        f = fp.fingerprint(deep)
        self.assertTrue(f.is_structural)

    def test_deterministic(self):
        self.assertEqual(fp.fingerprint(PAGE).hash, fp.fingerprint(PAGE).hash)


class TestAbsence(unittest.TestCase):

    def test_no_dom_is_not_a_template(self):
        for body in ('{"a": 1, "b": [2,3]}', "", "   ", "plain text",
                     '[{"permit":"x"}]'):
            with self.subTest(body=body[:20]):
                f = fp.fingerprint(body)
                self.assertFalse(f.is_structural)
                self.assertEqual(f.mark(), "")

    def test_json_bodies_do_not_collide_into_a_finding(self):
        """The defect the first back-fill produced, as a test."""
        marks = {fp.fingerprint('{"austin": 1}').mark(),
                 fp.fingerprint('{"seattle": 2}').mark(),
                 fp.fingerprint('{"columbus": 3}').mark()}
        self.assertEqual(marks, {""})

    def test_real_html_is_structural(self):
        f = fp.fingerprint(PAGE)
        self.assertTrue(f.is_structural)
        self.assertTrue(f.mark().startswith(fp.VERSION + ":"))


class TestVersioning(unittest.TestCase):

    def test_mark_carries_the_version(self):
        v, h = fp.parse(fp.fingerprint(PAGE).mark())
        self.assertEqual(v, fp.VERSION)
        self.assertEqual(h, fp.fingerprint(PAGE).hash)

    def test_cross_version_similarity_is_refused(self):
        a, b = fp.fingerprint(PAGE), fp.fingerprint(PAGE)
        b.version = "fp-other"
        with self.assertRaises(ValueError):
            a.similarity(b)

    def test_comparable(self):
        self.assertTrue(fp.comparable("fp1:aabbccdd", "fp1:11223344"))
        self.assertFalse(fp.comparable("fp1:aabbccdd", "fp2:aabbccdd"))
        self.assertFalse(fp.comparable("fp1:aabbccdd", ""))

    def test_parse_rejects_junk(self):
        for s in ("", "abc", "fp1:", ":aabbcc", "aabbccdd"):
            with self.subTest(s=s):
                with self.assertRaises(ValueError):
                    fp.parse(s)


class TestSimilarity(unittest.TestCase):

    def test_identical_pages_score_one(self):
        self.assertEqual(fp.fingerprint(PAGE).similarity(fp.fingerprint(PAGE)),
                         1.0)

    def test_disjoint_pages_score_low(self):
        a = fp.fingerprint("<html><body><table><tr><td>x</td></tr></table></body></html>")
        b = fp.fingerprint("<html><body><form><select><option>y</option></select></form></body></html>")
        self.assertLess(a.similarity(b), 0.5)

    def test_cluster_is_single_linkage(self):
        """Chaining is a stated weakness, not a bug: one intermediate page can
        merge two groups that do not resemble each other. Spike C used the
        generous method deliberately, because a generous method that still
        finds no collapse is a stronger negative result."""
        sets = {"a": frozenset("12345678"), "b": frozenset("45678901"),
                "c": frozenset("abcdefgh")}
        groups = fp.cluster(["a", "b", "c"], sets, 0.5)
        sizes = sorted(len(g) for g in groups)
        self.assertEqual(sizes, [1, 2])

    def test_cluster_at_impossible_threshold_is_all_singletons(self):
        sets = {"a": frozenset("12"), "b": frozenset("34")}
        self.assertEqual(len(fp.cluster(["a", "b"], sets, 1.01)), 2)


class TestSpikeCReproduces(unittest.TestCase):
    """The published negative result, pinned to the corpus on disk."""

    def corpus(self):
        files = sorted(glob.glob(os.path.join(ROOT, "data", "spike_a", "html",
                                              "*.html")))
        return files

    def test_corpus_present(self):
        requires_raw_store(self, "the Spike C reproduction")
        self.assertGreater(len(self.corpus()), 20,
                           "Spike A corpus missing; the published fingerprint "
                           "numbers cannot be reproduced without it")

    def test_no_collapse_at_any_threshold(self):
        """1.00 fingerprints per page at J >= 0.60. If this ever stops being
        true, ADR-0009's withdrawal of the DOM-fingerprint premise needs
        revisiting - and so does every cost figure that rested on it."""
        files = self.corpus()[:25]
        sets, keys = {}, []
        for f in files:
            with io.open(f, encoding="utf-8", errors="replace") as fh:
                g = fp.fingerprint(fh.read())
            if not g.is_structural:
                continue
            keys.append(f)
            sets[f] = g.paths
        groups = fp.cluster(keys, sets, 0.60)
        self.assertEqual(len(groups), len(keys),
                         "pages merged at J >= 0.60, which contradicts the "
                         "Spike C result the D8 withdrawal rests on")


if __name__ == "__main__":
    unittest.main()
