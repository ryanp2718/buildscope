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
               "openai/gpt-oss-120b:batch": "medium",
               # The step 6 roster, from the labs' docs and cards, 2026-09-27.
               "openai/gpt-6-sol": "medium", "openai/gpt-6-luna": "medium",
               "google/gemini-3.8-flash": "medium",
               "google/gemini-3.5-flash-lite": "minimal",
               "x-ai/grok-4.7": "high", "moonshotai/kimi-k3": "max",
               "z-ai/glm-5.3": "max", "qwen/qwen3.8-max-0902": "xhigh",
               "deepseek/deepseek-v4-pro-0813": "high",
               "deepseek/deepseek-v4.1-flash": "high",
               # Not the lab default (`no_think`): the card's setting for
               # coding, decided 2026-09-27 and disclosed in the entry.
               "tencent/hy3": "high"}
        effort = {s.id: models.lab_level(s, s.effort) for s in R.values()
                  if s.effort is not None}
        self.assertEqual(effort, lab)

    def test_every_level_name_is_for_a_listed_effort(self):
        for m, s in R.items():
            for sent, _ in s.levels:
                self.assertIn(sent, s.efforts, m)

    def test_the_listed_efforts_and_caps_match_the_catalogue(self):
        path = os.path.join(ROOT, "data", "audit",
                            "2026-09-27-openrouter-models.json")
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


def _snapshot(name):
    path = os.path.join(ROOT, "data", "audit", name)
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


# One day's endpoint listing for every OpenRouter model the registry measures
# (`spikes/fetch_roster_sources.py`).
ENDPOINTS = "2026-09-27-roster-endpoints.json"


class TestSamplingAndRouting(unittest.TestCase):
    """Protocol v2 sends these on every OpenRouter request, so a missing
    value would leave the serving host's default in charge (finding F6)."""

    def test_every_model_with_third_party_hosts_has_explicit_sampling(self):
        """A closed-weight model with no published sampling sends none, and
        runs at its lab's own default. Anything a third party may host
        carries the values explicitly."""
        for s in models.measured():
            if (s.provider is models.Provider.OPENROUTER
                    and s.quantizations is not None):
                self.assertIsNotNone(s.temperature, s.id)
                self.assertIsNotNone(s.top_p, s.id)

    def test_claude_sampling_is_the_fixed_thinking_temperature(self):
        for s in models.measured():
            if s.provider is models.Provider.ANTHROPIC:
                self.assertEqual((s.temperature, s.top_p), (1.0, None), s.id)

    def test_routing_admits_unknown_precision_only_for_a_lab_run_host(self):
        """`unknown` includes hosts that may serve anything. qwen3.5-flash is
        the exception because its single host is Alibaba's own. No filter at
        all is for a model whose every endpoint reports `unknown`: closed
        weights, served only by the lab or its licensed clouds."""
        eps = _snapshot(ENDPOINTS)
        for s in models.measured():
            if s.provider is not models.Provider.OPENROUTER:
                continue
            with self.subTest(model=s.id):
                if s.quantizations is None:
                    if eps is None:
                        continue
                    self.assertEqual(
                        {e.get("quantization")
                         for e in eps[s.id]["data"]["endpoints"]},
                        {"unknown"})
                elif s.id == "qwen/qwen3.5-flash-02-23":
                    self.assertIn("unknown", s.quantizations)
                else:
                    self.assertNotIn("unknown", s.quantizations)

    def test_hosts_that_ignore_effort_are_excluded(self):
        """Measured 2026-09-27: these endpoints render one prompt whatever
        effort is sent, so a cell routed there is not at the level asked.
        Carried over to the later V4 ids, which were not re-measured."""
        pro = {"novita", "parasail"}
        flash = {"gmicloud", "siliconflow", "parasail"}
        for m, hosts in (("deepseek/deepseek-v4-pro", pro),
                         ("deepseek/deepseek-v4-pro-0813", pro),
                         ("deepseek/deepseek-v4-flash", flash),
                         ("deepseek/deepseek-v4.1-flash", flash)):
            self.assertLessEqual(hosts, set(R[m].ignore), m)

    def test_hosts_that_closed_streams_early_are_excluded(self):
        """2026-09-28: AtlasCloud closed glm-5.3-flash streams at 301 s and
        Phala at 602 s, mid-reasoning (step 6 pre-registration, deviation
        2)."""
        s = R["z-ai/glm-5.3-flash"]
        self.assertLessEqual({"atlas-cloud", "phala"}, set(s.ignore))
        eps = _snapshot(ENDPOINTS)
        if eps is None:
            return
        tags = {e["tag"] for e in models.routed(
            s, eps[s.id]["data"]["endpoints"])}
        self.assertFalse({"atlas-cloud/fp8", "phala/fp8"} & tags)
        self.assertIn("streamlake/fp8", tags)

    def test_glm_5_3_avoids_the_hosts_that_failed_its_flash_model(self):
        """Stage 3 plan, 2026-09-29: the five hosts that closed glm-5.3-flash
        streams early or stopped them below the cap are excluded for glm-5.3.
        Of the 12 hosts its precision and parameter filters leave in the
        2026-09-27 listing, 8 remain."""
        bad = {"atlas-cloud", "phala", "gmicloud", "io-net", "siliconflow"}
        s = R["z-ai/glm-5.3"]
        self.assertLessEqual(bad, set(s.ignore))
        eps = _snapshot(ENDPOINTS)
        if eps is None:
            return
        listed = eps[s.id]["data"]["endpoints"]
        self.assertLessEqual(bad, {e["tag"].split("/")[0] for e in listed})
        tags = {e["tag"] for e in models.routed(s, listed)}
        self.assertFalse({t.split("/")[0] for t in tags} & bad)
        self.assertIn("sail-research/fp8", tags)
        self.assertEqual(len(tags), 8)

    def _routed(self):
        eps = _snapshot(ENDPOINTS)
        if eps is None:
            self.skipTest("no endpoint snapshot on this checkout")
        for s in models.measured():
            if s.provider is models.Provider.OPENROUTER and s.id in eps:
                yield s, models.routed(s, eps[s.id]["data"]["endpoints"])

    def test_the_snapshot_covers_every_openrouter_model(self):
        eps = _snapshot(ENDPOINTS)
        if eps is None:
            self.skipTest("no endpoint snapshot on this checkout")
        missing = {s.id for s in models.measured()
                   if s.provider is models.Provider.OPENROUTER} - set(eps)
        # :batch is an asynchronous variant with no endpoint listing of its own.
        self.assertEqual(missing, {"openai/gpt-oss-120b:batch"})

    def test_every_model_keeps_a_host(self):
        """A filter that matches no endpoint routes the model nowhere."""
        for s, hosts in self._routed():
            with self.subTest(model=s.id):
                self.assertTrue(hosts)

    def test_every_routed_host_can_emit_the_cap(self):
        """One output cap for every model is finding F1's fix. A host whose
        `max_completion_tokens` is lower would cut a draw short at its own
        limit, and OpenRouter does not document routing around it."""
        for s, hosts in self._routed():
            for e in hosts:
                with self.subTest(model=s.id, host=e["tag"]):
                    self.assertGreaterEqual(
                        e.get("max_completion_tokens") or models.OUTPUT_CAP,
                        models.output_cap(s))

    def test_every_ceiling_bounds_the_routed_hosts(self):
        """`price` is what `Budget` authorizes against. Below any host a
        request can land on, it is not a ceiling."""
        for s, hosts in self._routed():
            for e in hosts:
                with self.subTest(model=s.id, host=e["tag"]):
                    self.assertGreaterEqual(
                        s.price[0], float(e["pricing"]["prompt"]) * 1e6 - 1e-9)
                    self.assertGreaterEqual(
                        s.price[1],
                        float(e["pricing"]["completion"]) * 1e6 - 1e-9)


class TestRouted(unittest.TestCase):
    """`models.routed` mirrors the `provider` object `build_chat` sends."""

    SPEC = models.ModelSpec(
        "x/y", models.Provider.OPENROUTER, "x", models.Tier.CHEAP, "y",
        date(2026, 1, 1), (1.0, 1.0), (1.0, 1.0),
        models.ReasoningControl.EFFORT, supports_reasoning=True,
        temperature=1.0, top_p=None, effort="high", efforts=("high",),
        quantizations=("fp8",), ignore=("bad", "mixed/fp8"))
    ALL = ["reasoning", "temperature", "top_p"]

    def ep(self, tag, q="fp8", params=None):
        return {"tag": tag, "quantization": q,
                "supported_parameters": self.ALL if params is None else params}

    def tags(self, *eps):
        return [e["tag"] for e in models.routed(self.SPEC, list(eps))]

    def test_filters(self):
        self.assertEqual(self.tags(
            self.ep("ok/fp8"),
            self.ep("low/fp4", q="fp4"),              # below the precision
            self.ep("bad/fp8"),                       # base slug ignored
            self.ep("mixed/fp8"),                     # one endpoint ignored
            self.ep("mixed/bf16", q="bf16"),          # ...not its sibling
            self.ep("ok/fast"),                       # a service tier
            self.ep("google-vertex/global/flex"),     # a service tier
            self.ep("notemp/fp8", params=["reasoning", "top_p"]),
            self.ep("notop/fp8", params=["reasoning", "temperature"]),
            self.ep("noreason/fp8", params=["temperature"])),
            ["ok/fp8", "notop/fp8"])

    def test_a_filter_of_none_admits_every_precision(self):
        spec = models.ModelSpec(
            "x/z", models.Provider.OPENROUTER, "x", models.Tier.CHEAP, "z",
            date(2026, 1, 1), (1.0, 1.0), (1.0, 1.0))
        self.assertEqual(
            len(models.routed(spec, [self.ep("a", q="unknown"),
                                     self.ep("b", q="fp4")])), 2)


class TestCacheReadPrice(unittest.TestCase):

    def test_opus_5_5_reads_bill_at_five_percent(self):
        """Every other Claude model bills a cache hit at 0.1x input."""
        from permits import infer
        usage = infer.Usage(input_tokens=0, output_tokens=0,
                            cache_read_input_tokens=1_000_000)
        self.assertAlmostEqual(infer.cost("claude-opus-5-5", usage), 0.20)
        self.assertAlmostEqual(infer.cost("claude-sonnet-5", usage), 0.20)
        self.assertAlmostEqual(infer.cost("claude-opus-5", usage), 0.50)


class TestTiersMatchTheAudit(unittest.TestCase):
    """The roster table in the 2026-09-26 audit (finding F9), and the step 6
    roster's lab positioning. A tier is a judgement, so it is written down
    once and checked here rather than re-derived from price in each report."""

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
            # docs/evidence/2026-09-27-v2-run-preregistration.md
            "claude-opus-5-5": "top",
            "x-ai/grok-4.7": "top",
            "moonshotai/kimi-k3": "top",
            "z-ai/glm-5.3": "top",
            "qwen/qwen3.8-max-0902": "top",
            "openai/gpt-6-sol": "mid",
            "google/gemini-3.8-flash": "mid",
            "deepseek/deepseek-v4-pro-0813": "mid",
            "xiaomi/mimo-v2.6-pro": "mid",
            "minimax/minimax-m3": "mid",
            "openai/gpt-6-luna": "cheap",
            "google/gemini-3.5-flash-lite": "cheap",
            "qwen/qwen3.8-flash": "cheap",
            "deepseek/deepseek-v4.1-flash": "cheap",
            "xiaomi/mimo-v2.6-flash": "cheap",
            "tencent/hy3": "cheap",
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
