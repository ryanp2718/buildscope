# -*- coding: utf-8 -*-
"""The model registry, `permits/models.py`.

The registry replaced seven hand-kept tables on 2026-09-26. The failure it
exists to prevent is a model that is in one table and not another, which gets
a different experiment without anyone choosing it: finding F2 in
`docs/evidence/2026-09-26-model-comparison-fairness-audit.md` is two models
that reason being run as models that do not.

The request bytes are pinned elsewhere (`tests/test_providers.py`,
`tests/test_infer.py`). These tests pin the registry's own invariants and
the protocol v2 settings against the sources the audit took them from.
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
            if s.reasoning in (models.ReasoningControl.EFFORT,
                               models.ReasoningControl.SWITCH):
                self.assertIs(s.provider, models.Provider.OPENROUTER, m)

    def test_no_model_is_asked_to_reason_that_cannot(self):
        for m, s in R.items():
            if s.reasoning is not models.ReasoningControl.NONE:
                self.assertTrue(s.supports_reasoning, m)

    def test_every_model_that_reasons_is_asked_to(self):
        """F2, closed by protocol v2: qwen3.5-flash and gpt-oss-120b reason
        and v1 sent them nothing. A model added the same way fails here."""
        gap = {s.id for s in models.measured()
               if s.supports_reasoning
               and s.reasoning is models.ReasoningControl.NONE}
        self.assertEqual(gap, set())

    def test_an_effort_model_names_a_default_it_accepts(self):
        """v1 sent "medium" to four models whose catalogue entries do not
        list it. The default sent now has to be one of the listed levels."""
        for m, s in R.items():
            if s.reasoning is models.ReasoningControl.EFFORT:
                self.assertIn(s.effort, s.efforts, m)
            else:
                self.assertIsNone(s.effort, m)

    def test_the_default_effort_reaches_the_labs_default_level(self):
        """Protocol v2 asks for the lab's default, not the catalogue's
        (docs/evidence/2026-09-27-openrouter-reasoning-effort.md). The two
        differ for glm-5.2: the catalogue says `high`, Z.ai says `max`."""
        lab = {"z-ai/glm-5.2": "max", "z-ai/glm-5.3-flash": "max",
               "deepseek/deepseek-v4-pro": "high",
               "deepseek/deepseek-v4-flash": "high",
               "openai/gpt-oss-120b": "medium",
               "openai/gpt-oss-120b:batch": "medium"}
        effort = {s.id: models.lab_level(s, s.effort) for s in R.values()
                  if s.effort is not None}
        self.assertEqual(effort, lab)

    def test_every_level_name_is_for_a_listed_effort(self):
        for m, s in R.items():
            for sent, _ in s.levels:
                self.assertIn(sent, s.efforts, m)

    def test_the_listed_efforts_and_caps_match_the_catalogue(self):
        path = os.path.join(ROOT, "data", "audit",
                            "2026-09-25-openrouter-models.json")
        if not os.path.exists(path):
            self.skipTest("no catalogue snapshot on this checkout")
        with io.open(path, encoding="utf-8") as fh:
            cat = json.load(fh)
        by = {m["id"]: m for m in (cat["data"] if isinstance(cat, dict)
                                   else cat)}
        for s in models.measured():
            if s.provider is not models.Provider.OPENROUTER:
                continue
            with self.subTest(model=s.id):
                r = by[s.id].get("reasoning") or {}
                self.assertEqual(set(s.efforts),
                                 set(r.get("supported_efforts") or ()))
                self.assertEqual(
                    s.max_output,
                    by[s.id]["top_provider"]["max_completion_tokens"])


class TestSamplingAndRouting(unittest.TestCase):
    """Protocol v2 sends these on every OpenRouter request, so a missing
    value would leave the serving host's default in charge (finding F6)."""

    def test_every_open_model_has_explicit_sampling(self):
        for s in models.measured():
            if s.provider is models.Provider.OPENROUTER:
                self.assertIsNotNone(s.temperature, s.id)
                self.assertIsNotNone(s.top_p, s.id)

    def test_claude_sampling_is_the_fixed_thinking_temperature(self):
        for s in models.measured():
            if s.provider is models.Provider.ANTHROPIC:
                self.assertEqual((s.temperature, s.top_p), (1.0, None), s.id)

    def test_routing_admits_unknown_precision_only_for_a_lab_run_host(self):
        """`unknown` includes hosts that may serve anything. qwen3.5-flash is
        the exception because its single host is Alibaba's own."""
        for s in models.measured():
            if s.provider is not models.Provider.OPENROUTER:
                continue
            with self.subTest(model=s.id):
                self.assertIsNotNone(s.quantizations)
                if s.id == "qwen/qwen3.5-flash-02-23":
                    self.assertIn("unknown", s.quantizations)
                else:
                    self.assertNotIn("unknown", s.quantizations)

    def test_hosts_that_ignore_effort_are_excluded(self):
        """Measured 2026-09-27: these endpoints render one prompt whatever
        effort is sent, so a cell routed there is not at the level asked."""
        self.assertEqual(R["deepseek/deepseek-v4-pro"].ignore,
                         ("novita", "parasail"))
        self.assertEqual(R["deepseek/deepseek-v4-flash"].ignore,
                         ("gmicloud", "siliconflow", "parasail"))

    def test_every_filtered_model_keeps_a_host(self):
        """A filter that matches no endpoint routes the model nowhere."""
        path = os.path.join(ROOT, "data", "audit",
                            "2026-09-26-openrouter-endpoints.json")
        if not os.path.exists(path):
            self.skipTest("no endpoint snapshot on this checkout")
        with io.open(path, encoding="utf-8") as fh:
            eps = json.load(fh)
        for s in models.measured():
            if s.quantizations is None or s.id not in eps:
                continue
            with self.subTest(model=s.id):
                hosts = [e for e in eps[s.id]["data"]["endpoints"]
                         if e.get("quantization") in s.quantizations
                         and e["tag"].split("/")[0] not in s.ignore]
                self.assertTrue(hosts)


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
