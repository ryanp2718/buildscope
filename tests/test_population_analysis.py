# -*- coding: utf-8 -*-
"""`scripts/population_analysis.py`'s pieces, on made-up cells: matched
spend, the attempt rules, P2's count and verdict, and the weights."""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import population_analysis as PA                              # noqa: E402
from permits.cells import Outcome                             # noqa: E402


def rec(order, model, arm, ep, ok, accepted=None, usd=0.01, submitted=True):
    acc = ok if accepted is None else accepted
    return {"order": order, "model": model, "arm": arm, "episode": ep,
            "outcome": Outcome.PERFECT if ok else Outcome.IMPERFECT,
            "accepted": acc, "submitted": submitted,
            "trusted": acc and ok and (arm == "oneshot" or submitted),
            "list_usd": usd, "usd": usd / 2, "field_perfect": ok}


M = PA.CHEAP[0]


class TestMatchedSpend(unittest.TestCase):

    def test_interpolates_between_whole_k(self):
        # Two draws, one accepted and perfect: k=1 spends 0.01, succeeds
        # half the time; k=2 spends 0.015 and always succeeds.
        draws = PA.stored([rec(1, M, "oneshot", 0, True),
                           rec(1, M, "oneshot", 1, False)])
        self.assertAlmostEqual(PA.bok_at(draws, 0.005), 0.25)
        self.assertAlmostEqual(PA.bok_at(draws, 0.0125), 0.75)
        self.assertAlmostEqual(PA.bok_at(draws, 1.0), 1.0)


class TestAttempts(unittest.TestCase):

    def test_a_cell_without_room_takes_its_one_shot_result(self):
        cs = PA.cells([rec(1, M, "oneshot", e, True) for e in range(3)])
        self.assertEqual(PA.attempt(cs, 1, M, "scripted", "list_usd"),
                         PA.attempt(cs, 1, M, "oneshot", "list_usd"))

    def test_an_episode_counts_only_if_submitted(self):
        cs = PA.cells([rec(1, M, "scripted", 0, True, submitted=False),
                       rec(1, M, "scripted", 1, True)])
        self.assertEqual(PA.attempt(cs, 1, M, "scripted", "list_usd")[1], 0.5)


class TestP2(unittest.TestCase):

    def test_counts_accepted_wrong_extractors(self):
        cs = PA.cells([rec(1, M, "oneshot", 0, False, accepted=True),
                       rec(1, M, "oneshot", 1, True),
                       rec(1, M, "scripted", 0, False, accepted=True,
                           submitted=False),
                       rec(1, M, "scripted", 1, False, accepted=False)])
        self.assertEqual(PA.p2(cs, [1]), (1, 2))

    def test_verdicts(self):
        self.assertEqual(PA.verdict_p2(0.03, [0.01, 0.04]), "confirmed")
        self.assertEqual(PA.verdict_p2(0.03, [0.01, 0.06]), "consistent")
        self.assertEqual(PA.verdict_p2(0.05, [0.03, 0.07]), "refuted")


class TestWeights(unittest.TestCase):

    ROWS = [{"order": 1, "product": "A", "take_all": False, "fetchable": True,
             "open_data": False, "usable": 1.0},
            {"order": 2, "product": "A", "take_all": True, "fetchable": True,
             "open_data": True, "usable": 1.0},
            {"order": 3, "product": "B", "take_all": False,
             "fetchable": False, "open_data": False, "usable": 0.5}]

    def test_views(self):
        w = PA.weights(self.ROWS)
        self.assertAlmostEqual(w["layout"]["A"], PA.DRAWN_W + 1)
        self.assertAlmostEqual(w["layout"]["B"], PA.DRAWN_W * 0.5)
        self.assertAlmostEqual(w["pipeline"]["A"], PA.DRAWN_W)
        self.assertNotIn("B", w["pipeline"])

    def test_an_office_left_out_of_a_replicate_weighs_nothing(self):
        w = PA.weights(self.ROWS, counts={3: 2})
        self.assertAlmostEqual(w["layout"]["A"], 1.0)
        self.assertAlmostEqual(w["layout"]["B"], 2 * PA.DRAWN_W * 0.5)

    def test_resample_keeps_one_portal_products(self):
        cs = PA.cells([rec(1, M, "oneshot", 0, True)])
        portals = {1: {"product": "A", "place": "x", "access": "crawler"}}
        bc, bp, _ = PA.resample(cs, portals, [1, 2], random.Random(1))
        self.assertEqual(list(bp.values()), [portals[1]])
        self.assertEqual(len(bc), 1)


if __name__ == "__main__":
    unittest.main()
