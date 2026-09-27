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
                           RunConfig, draws_of)


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
        self.assertEqual(CellSpec("clarkco", "z-ai/glm-5.2", 5).key,
                         "clarkco|z-ai/glm-5.2")
        self.assertEqual(CellSpec("clarkco", "z-ai/glm-5.2", 5, True).key,
                         "clarkco|z-ai/glm-5.2|hint")


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
