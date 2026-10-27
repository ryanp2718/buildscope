# -*- coding: utf-8 -*-
"""`scripts/population_check.py`'s page rendering and comparison, with no
model calls."""
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import population_check as PC                                 # noqa: E402


class TestBarePage(unittest.TestCase):

    def test_attributes_and_option_lists_go_and_empty_cells_stay(self):
        page = ("<table class='g'><tr id='r1'><td class='a'>B-1</td><td></td>"
                "<td>Issued</td></tr></table><select name='s'><option>One"
                "</option></select>")
        self.assertEqual(PC.bare(page), "<table><tr><td>B-1</td><td></td>"
                                        "<td>Issued</td></tr></table> ")


class TestCompare(unittest.TestCase):

    def test_fields_agree_disagree_and_missing_records(self):
        portal = SimpleNamespace(order=7, target=SimpleNamespace(
            roles={"native_id": "native_id", "status": "status"}),
            refs={"p1.html": [{"native_id": "B-1", "status": "Issued"},
                              {"native_id": "B-2", "status": "Final"}]})
        res = PC.compare(portal, "p1.html", [
            {"native_id": "B-1", "status": "Issued "},
            {"native_id": "B-3", "status": "Void"}])
        self.assertEqual(res["matched"], 1)
        self.assertEqual(res["missed"], ["B-2"])
        self.assertEqual(res["extra"], ["B-3"])
        self.assertEqual(res["fields"], {"status": [1, 1]})
        self.assertEqual(res["diffs"], [])

    def test_unreadable_reply_matches_nothing(self):
        portal = SimpleNamespace(order=7, target=SimpleNamespace(
            roles={"native_id": "native_id"}),
            refs={"p1.html": [{"native_id": "B-1"}]})
        self.assertEqual(PC.compare(portal, "p1.html", None)["missed"], ["B-1"])


if __name__ == "__main__":
    unittest.main()
