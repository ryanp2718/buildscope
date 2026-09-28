# -*- coding: utf-8 -*-
"""The variance experiment's records, `permits/cells.py`.

Two defects these replace. `run_cells` overwrote `args.synth_model` and
`args.draws` per cell and did not restore them, so whatever ran after a cell
loop saw the last cell's model. And every reader of a draw used
`.get("field")`, so a misspelled field read as missing instead of raising.
"""
import io
import json
import os
import sys
import unittest
from dataclasses import FrozenInstanceError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits.cells import (CellSpec, DrawRecord, Outcome,     # noqa: E402
                           RunConfig, curtail, draws_of)
from permits.models import Protocol                          # noqa: E402


def _cfg(**kw):
    base = {"synth_model": "claude-opus-5", "direct_model": "claude-opus-5",
            "synth_tokens": 16000, "synth_window": 24000,
            "synth_hint": False, "direct_pages": 2, "draws": 1}
    base.update(kw)
    return RunConfig(**base)


class TestCellSpec(unittest.TestCase):

    def test_a_colon_in_the_model_id_survives(self):
        c = CellSpec.parse("stjohns:openai/gpt-oss-120b:batch:20")
        self.assertEqual((c.target, c.model, c.draws),
                         ("stjohns", "openai/gpt-oss-120b:batch", 20))

    def test_bad_entries_raise(self):
        for bad in ("stjohns:20", "stjohns:qwen/qwen3-coder:many"):
            with self.assertRaises(ValueError):
                CellSpec.parse(bad)

    def test_the_hinted_cell_has_its_own_key(self):
        v1 = Protocol.V1
        self.assertEqual(CellSpec("clarkco", "z-ai/glm-5.2", 5, False, v1).key,
                         "clarkco|z-ai/glm-5.2")
        self.assertEqual(CellSpec("clarkco", "z-ai/glm-5.2", 5, True, v1).key,
                         "clarkco|z-ai/glm-5.2|hint")

    def test_a_v2_cell_is_keyed_apart_from_the_v1_cells_on_disk(self):
        self.assertEqual(CellSpec("clarkco", "z-ai/glm-5.2", 5).key,
                         "clarkco|z-ai/glm-5.2|v2")
        self.assertEqual(CellSpec("clarkco", "z-ai/glm-5.2", 5, True).key,
                         "clarkco|z-ai/glm-5.2|hint|v2")

    def test_an_effort_is_parsed_off_the_model_and_kept_in_the_key(self):
        c = CellSpec.parse("clarkco:z-ai/glm-5.3-flash@low:10")
        self.assertEqual((c.model, c.effort, c.draws),
                         ("z-ai/glm-5.3-flash", "low", 10))
        self.assertEqual(c.key, "clarkco|z-ai/glm-5.3-flash@low|v2")
        c = CellSpec.parse("stjohns:openai/gpt-oss-120b:batch@high:5")
        self.assertEqual((c.model, c.effort), ("openai/gpt-oss-120b:batch",
                                               "high"))

    def test_v1_has_no_effort(self):
        with self.assertRaises(ValueError):
            CellSpec.parse("clarkco:z-ai/glm-5.3-flash@low:10",
                           protocol=Protocol.V1)

    def test_a_two_stage_cell_is_priced_at_its_most_draws(self):
        c = CellSpec.parse("clarkco:z-ai/glm-5.3:10+10")
        self.assertEqual((c.draws, c.stage1, c.draws_label), (20, 10, "10+10"))
        self.assertEqual(c.key, "clarkco|z-ai/glm-5.3|v2",
                         "the stopping rule is not a condition")
        c = CellSpec.parse("stjohns:openai/gpt-oss-120b:batch:10")
        self.assertEqual((c.draws, c.stage1, c.draws_label), (10, None, "10"))

    def test_bad_two_stage_counts_raise(self):
        for bad in ("clarkco:m:10+", "clarkco:m:+10", "clarkco:m:0+10",
                    "clarkco:m:10+0", "clarkco:m:5+5+5", "clarkco:m:-3"):
            with self.assertRaises(ValueError, msg=bad):
                CellSpec.parse(bad)

    def test_a_cell_carries_its_stage1_into_the_config(self):
        cfg = _cfg().for_cell(CellSpec.parse("clarkco:z-ai/glm-5.3:10+10"))
        self.assertEqual((cfg.draws, cfg.stage1), (20, 10))
        cfg = _cfg(stage1=10).for_cell(CellSpec.parse("clarkco:m:5"))
        self.assertIsNone(cfg.stage1, "a fixed cell after a two-stage one")


def _draws(outcomes):
    return [DrawRecord(d, "m", "clarkco", o) for d, o in enumerate(outcomes)]


P, F, X = Outcome.PERFECT, Outcome.IMPERFECT, Outcome.INFRA_ERROR


class TestCurtail(unittest.TestCase):
    """The step 6 pre-registration's two-stage rule: stop after 10 draws at
    0/10 or 10/10, otherwise continue to 20."""

    def test_a_unanimous_stage1_stops(self):
        self.assertTrue(curtail(_draws([P] * 10), 10))
        self.assertTrue(curtail(_draws([F] * 10), 10))
        self.assertTrue(curtail(_draws([Outcome.NO_CODE, Outcome.RAISED,
                                         Outcome.REFUSED] + [F] * 7), 10),
                        "every way of failing is a failure")

    def test_a_split_stage1_continues(self):
        self.assertFalse(curtail(_draws([P] * 9 + [F]), 10))
        self.assertFalse(curtail(_draws([F] * 9 + [P]), 10))

    def test_only_stage1_draws_decide(self):
        self.assertTrue(curtail(_draws([P] * 10 + [F] * 5), 10))

    def test_an_infra_error_is_left_out(self):
        self.assertTrue(curtail(_draws([P] * 9 + [X]), 10))
        self.assertFalse(curtail(_draws([P] * 8 + [X, F]), 10))

    def test_no_scored_draw_stops(self):
        self.assertTrue(curtail(_draws([X] * 10), 10))

    def test_a_retry_can_only_turn_a_stop_into_a_continue(self):
        """The property that makes deciding on a stage 1 with an infra error
        safe: whatever the retried draw does, a split stage 1 stays split."""
        for retried in (P, F):
            before = [P, F] + [P] * 7 + [X]
            after = [*before[:-1], retried]
            self.assertFalse(curtail(_draws(before), 10))
            self.assertFalse(curtail(_draws(after), 10))


class TestRunConfig(unittest.TestCase):

    def test_a_cell_gets_a_copy_and_the_run_is_untouched(self):
        cfg = _cfg()
        cell = cfg.for_cell(CellSpec("clarkco", "z-ai/glm-5.2", 7, True))
        self.assertEqual((cell.synth_model, cell.draws, cell.synth_hint),
                         ("z-ai/glm-5.2", 7, True))
        self.assertEqual((cfg.synth_model, cfg.draws, cfg.synth_hint),
                         ("claude-opus-5", 1, False))

    def test_it_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            _cfg().synth_model = "x"  # type: ignore[misc]


class TestDrawRecord(unittest.TestCase):

    def test_every_draw_on_disk_round_trips(self):
        """The typed layer must not change a byte of the measurements."""
        path = os.path.join(ROOT, "data", "infer", "variance.json")
        if not os.path.exists(path):
            self.skipTest("no variance.json on this checkout")
        with io.open(path, encoding="utf-8") as fh:
            cells = json.load(fh)["cells"]
        n = 0
        for key, cell in cells.items():
            for raw, rec in zip(cell["detail"], draws_of(cell), strict=True):
                with self.subTest(cell=key, draw=raw["draw"]):
                    self.assertEqual(json.dumps(rec.to_dict(), sort_keys=True),
                                     json.dumps(raw, sort_keys=True))
                n += 1
        self.assertGreater(n, 200)

    def test_a_misspelled_field_raises(self):
        with self.assertRaises(ValueError):
            DrawRecord.from_dict({"draw": 0, "model": "m", "target": "t",
                                  "outcome": "perfect", "recal_min": 1.0})

    def test_an_unknown_outcome_raises(self):
        with self.assertRaises(ValueError):
            DrawRecord.from_dict({"draw": 0, "model": "m", "target": "t",
                                  "outcome": "sort_of"})

    def test_an_attempted_draw_with_no_spend_is_malformed_not_free(self):
        d = DrawRecord(0, "m", "t", Outcome.RAISED)
        with self.assertRaises(ValueError):
            d.spend()
        self.assertEqual(
            DrawRecord(0, "m", "t", Outcome.NOT_ATTEMPTED).spend(), 0.0)

    def test_outcomes_serialize_as_their_strings(self):
        d = DrawRecord(0, "m", "t", Outcome.PERFECT, usd=0.1)
        self.assertEqual(json.loads(json.dumps(d.to_dict()))["outcome"],
                         "perfect")


if __name__ == "__main__":
    unittest.main()
