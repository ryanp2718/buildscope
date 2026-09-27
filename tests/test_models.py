# -*- coding: utf-8 -*-
"""The model registry, `permits/models.py`.

The registry replaced seven hand-kept tables on 2026-09-26. The failure it
exists to prevent is a model that is in one table and not another, which gets
a different experiment without anyone choosing it: finding F2 in
`docs/evidence/2026-09-26-model-comparison-fairness-audit.md` is two models
that reason being run as models that do not.

The request bytes are pinned elsewhere (`tests/test_providers.py`,
`tests/test_infer.py`). These tests pin the registry's own invariants and the
known gaps, which may only shrink.
"""
import json
import io
import os
import sys
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import models                                   # noqa: E402

R = models.REGISTRY


class TestTheRegistryIsComplete(unittest.TestCase):

    def test_ids_are_keys(self):
        for m, s in R.items():
            self.assertEqual(m, s.id)

    def test_entries_are_frozen(self):
        s = R["claude-opus-5"]
        with self.assertRaises(AttributeError):
            s.price = (0.0, 0.0)  # type: ignore[misc]

    def test_every_release_date_is_real(self):
        for m, s in R.items():
            self.assertIsInstance(s.released, date, m)
            self.assertLessEqual(s.released, date(2026, 9, 26), m)

    def test_every_model_the_harness_ever_called_resolves(self):
        """The ledger and the variance cells are named by model id, and the
        registry is historical so that they keep resolving."""
        seen = set()
        ledger = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
        variance = os.path.join(ROOT, "data", "infer", "variance.json")
        if not (os.path.exists(ledger) and os.path.exists(variance)):
            self.skipTest("no ledger or variance file on this checkout")
        with io.open(ledger, encoding="utf-8") as fh:
            seen |= {json.loads(line)["model"] for line in fh if line.strip()}
        with io.open(variance, encoding="utf-8") as fh:
            seen |= {c["model"] for c in json.load(fh)["cells"].values()}
        self.assertEqual(sorted(seen - set(R)), [])


class TestReasoningControlFitsTheProvider(unittest.TestCase):

    def test_anthropic_controls_are_anthropic(self):
        anthropic_only = {models.ReasoningControl.ADAPTIVE,
                          models.ReasoningControl.BUDGET}
        for m, s in R.items():
            if s.reasoning in anthropic_only:
                self.assertIs(s.provider, models.Provider.ANTHROPIC, m)
            if s.reasoning is models.ReasoningControl.EFFORT:
                self.assertIs(s.provider, models.Provider.OPENROUTER, m)

    def test_no_model_is_asked_to_reason_that_cannot(self):
        for m, s in R.items():
            if s.reasoning is not models.ReasoningControl.NONE:
                self.assertTrue(s.supports_reasoning, m)

    def test_the_known_reasoning_gap_only_shrinks(self):
        """F2: the catalogue lists `reasoning` for these and the harness sends
        none. Step 3 of the audit closes the gap; remove each id from this set
        as it does. A model joining the set is a new gap and fails here."""
        gap = {s.id for s in models.measured()
               if s.supports_reasoning
               and s.reasoning is models.ReasoningControl.NONE}
        self.assertLessEqual(gap, {"qwen/qwen3.5-flash-02-23",
                                   "openai/gpt-oss-120b",
                                   "openai/gpt-oss-120b:batch"})


class TestTiersMatchTheAudit(unittest.TestCase):
    """The roster table in the 2026-09-26 audit (finding F9). A tier is a
    judgement, so it is written down once and checked here rather than
    re-derived from price in each report."""

    def test_tiers(self):
        expect = {
            "claude-opus-5": "top",
            "claude-sonnet-5": "mid",
            "z-ai/glm-5.2": "mid",
            "deepseek/deepseek-v4-pro": "mid",
            "claude-haiku-4-5-20251001": "cheap",
            "qwen/qwen3-coder": "cheap",
            "openai/gpt-oss-120b": "cheap",
            "moonshotai/kimi-k2-thinking": "cheap",
            "qwen/qwen3.5-flash-02-23": "cheap",
            "z-ai/glm-5.3-flash": "cheap",
            "deepseek/deepseek-v4-flash": "cheap",
        }
        for m, tier in expect.items():
            self.assertEqual(R[m].tier, tier, m)


class TestUnknownModels(unittest.TestCase):

    def test_an_unknown_id_raises_with_the_fix(self):
        with self.assertRaises(models.UnknownModel) as cm:
            models.get("nobody/nothing")
        self.assertIn("permits/models.py", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
