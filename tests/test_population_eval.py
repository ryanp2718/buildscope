# -*- coding: utf-8 -*-
"""`scripts/population_eval.py`'s stage rules, with no model calls: which
cells get extension draws or episodes, the projections that cut them, and
the guard on paid runs."""
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import population_eval as PE                                  # noqa: E402
from permits.cells import Outcome                             # noqa: E402

PORTALS = [SimpleNamespace(key="p%04d" % o, order=o, product="Accela")
           for o in (1, 2, 3, 4)]


def _args(stage, limit, models=None):
    return SimpleNamespace(run_id="t", stage=stage, max_spend=limit,
                           models=models, registered="osf", project="dev")


class Fake:
    """Stands in for `run_one`: a draw passes where `passes(portal, model,
    episode)` says, at `usd` billed."""

    def __init__(self, passes, usd=0.01):
        self.passes, self.usd, self.calls = passes, usd, []

    def __call__(self, client, args, stage, portal, model, episode, saver,
                 cap):
        self.calls.append((stage, portal.order, model, episode, cap))
        ok = self.passes(portal.order, model, episode)
        return {"run_id": args.run_id, "stage": stage, "order": portal.order,
                "model": model, "episode": episode,
                "outcome": Outcome.PERFECT if ok else Outcome.IMPERFECT,
                "usd": self.usd, "list_usd": self.usd * 4, "accepted": ok,
                "trusted": ok, "field_perfect": ok, "turns": 1,
                "seconds": 0.0}


class StageCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patch = mock.patch.object(
            PE, "EPISODES", os.path.join(self.dir, "episodes.json"))
        self.patch.start()
        self.out = mock.patch("sys.stdout", new_callable=io.StringIO)
        self.out.start()

    def tearDown(self):
        self.out.stop()
        self.patch.stop()

    def run_stage(self, args, fake):
        with mock.patch.object(PE, "run_one", fake):
            PE.run_stage(None, args, PE.load_state(), PORTALS, None)
        return fake.calls


class TestHelpers(unittest.TestCase):

    def test_disagree_needs_both_outcomes(self):
        d = [PE.arms.Stored(i, 0, 0, True, p, p) for i, p in
             enumerate((True, True, False))]
        self.assertTrue(PE.disagree(d))
        self.assertFalse(PE.disagree(d[:2]))
        self.assertAlmostEqual(PE.pass_at_1(d), 2 / 3.0)


class TestStrongExtension(StageCase):

    @staticmethod
    def passes(order, model, e):
        # Portal 1 always passes, 2 never, 3 and 4 split.
        return {1: True, 2: False}.get(order, e % 2 == 0)

    def test_only_disagreeing_portals_get_more_draws(self):
        calls = self.run_stage(_args(3, 35.0), Fake(self.passes))
        more = {(o, m) for s, o, m, e, _ in calls if e >= PE.STRONG_DRAWS}
        self.assertEqual(more, {(o, m) for o in (3, 4) for m in PE.STRONG})
        self.assertEqual(len(calls), 2 * 4 * 5 + 2 * 2 * 5)

    def test_extensions_dropped_when_the_projection_passes_the_limit(self):
        # 20 base draws at $0.10, doubled for two models, times 1.5.
        calls = self.run_stage(_args(3, 5.0), Fake(self.passes, usd=0.10))
        self.assertFalse([c for c in calls if c[3] >= PE.STRONG_DRAWS])

    def test_a_partial_run_waits_for_the_first_model(self):
        gemini = PE.STRONG[1]
        calls = self.run_stage(_args(3, 35.0, [gemini]), Fake(self.passes))
        self.assertEqual({c[2] for c in calls}, {gemini})
        self.assertFalse([c for c in calls if c[3] >= PE.STRONG_DRAWS])


class TestEpisodesWhereThereIsRoom(StageCase):

    def _stage2(self, passes):
        self.run_stage(_args(2, 8.0), Fake(passes))

    def test_cells_at_pass_1_are_skipped_and_b5_is_the_agent_cap(self):
        # Portal 1 passes every draw for every model: no room.
        self._stage2(lambda o, m, e: o == 1 or e == 0)
        calls = self.run_stage(_args(5, 12.0), Fake(lambda o, m, e: False))
        self.assertNotIn(1, {c[1] for c in calls})
        self.assertEqual(len(calls), 5 * 3 * PE.EPISODES_PER_CELL)
        st = PE.load_state()
        b5 = PE.b5(PE.cell_draws(st, "t", PORTALS[1], PE.CHEAP[0]))
        self.assertTrue(all(abs(c[4] - b5) < 1e-12 for c in calls))

    def test_cut_to_three_episodes_after_the_first_model(self):
        self._stage2(lambda o, m, e: e == 0)
        calls = self.run_stage(_args(4, 0.5), Fake(lambda o, m, e: False,
                                                   usd=0.02))
        first = [c for c in calls if c[2] == PE.CHEAP[0]]
        rest = [c for c in calls if c[2] != PE.CHEAP[0]]
        self.assertEqual(len(first), 4 * PE.EPISODES_PER_CELL)
        self.assertEqual(len(rest), 4 * 4 * PE.EPISODES_CUT)
        self.assertTrue(all(c[4] == PE.LOOP_CAP for c in calls))

    def test_episodes_wait_for_stage_2(self):
        with self.assertRaises(SystemExit):
            self.run_stage(_args(4, 12.0), Fake(lambda o, m, e: False))


class TestGuard(unittest.TestCase):

    def test_a_paid_run_needs_the_registration(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            PE.parse_args(["--run-id", "eval-x", "--stage", "2", "--run"])
        a = PE.parse_args(["--run-id", "eval-x", "--stage", "2", "--run",
                           "--registered", "https://osf.io/x"])
        self.assertEqual(a.max_spend, 8.0)
        self.assertEqual(a.project, PE.arms.EVAL_PROJECT)

    def test_models_only_for_stage_3(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            PE.parse_args(["--run-id", "x", "--stage", "2",
                           "--models", PE.STRONG[0]])


if __name__ == "__main__":
    unittest.main()
