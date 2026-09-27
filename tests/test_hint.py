"""Tests for the --synth-hint arm of the synthesis experiment.

The hint exists to answer one question: is the clarkco failure a capability
limit or a prompt gap? Every clarkco near miss, in each of the six models
that produces one, returns 555 of 561 records at precision 1.0 and drops the
same row class - the rows whose identifier renders as plain text because they
have no detail page to link to.

Two things can go wrong with an experiment like this and neither shows up as
a failing run.

The first is *invalidating the control*. The baseline draws are already
bought, and they resolve out of the response cache by a hash of the request.
Any edit that changes the default prompt by one byte orphans every one of
them and silently turns a comparison into two separate experiments. So the
default prompt is asserted byte-identical here, not merely equivalent.

The second is *teaching to the test*. A hint naming the permit prefix, the
column or the jurisdiction would measure whether the answer can be handed
over, which nobody needs measured. The hint states a structural fact about
grids and the model has to get to its own selector from there, so these
tests assert the absence of the giveaways rather than the presence of the
prose.
"""
import argparse
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from permits import infer, models                                 # noqa: E402


def args(**kw):
    """An args namespace with the fields the prompt accessors read."""
    base = {"synth_hint": False, "synth_model": "claude-opus-5",
            "synth_tokens": 8000, "synth_window": 24000}
    base.update(kw)
    return argparse.Namespace(**base)


class TestTheDefaultPromptDoesNotMove(unittest.TestCase):
    """The control arm has to stay the control arm."""

    def setUp(self):
        import conformance
        self.C = conformance

    def test_hint_off_is_byte_identical_to_the_bare_prompt(self):
        # Not `assertEqual(len(...))`, not "starts with". Byte-for-byte: the
        # cache key is a hash of the request and every draw already paid for
        # hangs off it.
        self.assertEqual(self.C.synth_system(args()), self.C.SYNTH_SYSTEM)

    def test_the_hint_is_appended_not_substituted(self):
        on = self.C.synth_system(args(synth_hint=True))
        self.assertTrue(on.startswith(self.C.SYNTH_SYSTEM))
        self.assertEqual(on, self.C.SYNTH_SYSTEM + self.C.SYNTH_HINT)

    def test_the_two_arms_are_different_requests(self):
        # If these hashed alike the hinted run would replay the baseline's
        # answers and report the hint as a perfect no-op.
        self.assertNotEqual(self.C.synth_system(args()),
                            self.C.synth_system(args(synth_hint=True)))

    def test_the_contract_survives_the_hint(self):
        # The three rules are what the scorer scores. Appending must not
        # push them out or reorder them.
        on = self.C.synth_system(args(synth_hint=True))
        self.assertIn("Values are returned EXACTLY AS RENDERED", on)
        self.assertIn("def extract(html: str) -> list[dict]", on)
        self.assertLess(on.index("def extract(html: str)"),
                        on.index("ROW STATE"))


class TestTheHintDoesNotHandOverTheAnswer(unittest.TestCase):
    """A hint that names the row class measures nothing worth knowing."""

    def setUp(self):
        import conformance
        self.hint = conformance.SYNTH_HINT.lower()

    def test_it_names_no_permit_prefix(self):
        # The four rows every model drops all begin `26TMP-`.
        self.assertNotIn("26tmp", self.hint)
        self.assertNotIn("tmp-", self.hint)

    def test_it_names_no_jurisdiction_or_target(self):
        for token in ("clark", "stjohns", "st. johns", "nevada", "florida"):
            self.assertNotIn(token, self.hint)

    def test_it_names_no_field_or_column_from_the_schema(self):
        # `native_id` and `detail_href` are the two that would give it away.
        for token in ("native_id", "detail_href", "permit number",
                      "permit no"):
            self.assertNotIn(token, self.hint)

    def test_it_states_the_structural_fact_it_is_supposed_to(self):
        for token in ("hyperlink", "plain text", "row container", "state"):
            self.assertIn(token, self.hint)

    def test_it_is_one_short_paragraph(self):
        # Length is the tell for scope creep. A hint that grows into a
        # second contract stops being one variable.
        body = [ln for ln in self.hint.strip().splitlines() if ln.strip()]
        self.assertLessEqual(len(body), 8)


class TestTheArmsAreScoredApart(unittest.TestCase):
    """Two prompts pooled into one rate is one wrong number, not two."""

    def setUp(self):
        import conformance
        self.C = conformance

    def test_the_baseline_cell_key_is_unchanged(self):
        # Every cell already in variance.json is keyed this way.
        self.assertEqual(
            self.C.cell_key("clarkco", "z-ai/glm-5.2", args()),
            "clarkco|z-ai/glm-5.2")

    def test_the_hinted_cell_gets_its_own_key(self):
        self.assertEqual(
            self.C.cell_key("clarkco", "z-ai/glm-5.2",
                            args(synth_hint=True)),
            "clarkco|z-ai/glm-5.2|hint")

    def test_a_model_id_with_a_colon_still_keys_cleanly(self):
        self.assertEqual(
            self.C.cell_key("stjohns", "openai/gpt-oss-120b:batch",
                            args(synth_hint=True)),
            "stjohns|openai/gpt-oss-120b:batch|hint")

    def test_the_hinted_run_writes_its_extractors_elsewhere(self):
        # The baseline sources are the evidence: re-scoring them per record
        # is what identified the dropped row class. A hinted run that reused
        # the filenames would overwrite them in place.
        import inspect
        src = inspect.getsource(self.C.run_variance)
        self.assertIn('"_hint" if cfg.synth_hint else ""', src)


class TestTheProjectionPricesWhatIsSent(unittest.TestCase):
    """The budget check and the wire have to quote one prompt."""

    def setUp(self):
        import conformance
        self.C = conformance

    def test_no_call_site_reaches_past_the_accessor(self):
        # `plan`, `matrix`, `run_variance` and `run_target` all used to name
        # SYNTH_SYSTEM directly. Any that still does prices the short prompt
        # and may send the long one.
        import inspect
        for fn in (self.C.plan, self.C.matrix, self.C.run_variance,
                   self.C.run_target):
            src = inspect.getsource(fn)
            self.assertNotIn("SYNTH_SYSTEM", src,
                             "%s bypasses synth_system()" % fn.__name__)

    def test_the_hint_costs_input_tokens_and_the_estimate_sees_them(self):
        off = infer.tokens(self.C.synth_system(args()))
        on = infer.tokens(self.C.synth_system(args(synth_hint=True)))
        self.assertGreater(on, off)


class TestTheNewCheapTierIsDeclared(unittest.TestCase):
    """Both current-generation cheap models reason, and were probed for it."""

    CHEAP = ("z-ai/glm-5.3-flash", "deepseek/deepseek-v4-flash")

    def test_both_are_registered(self):
        for m in self.CHEAP:
            self.assertIn(m, models.REGISTRY)

    def test_both_are_declared_reasoning(self):
        # Probed 2026-09-25: both return a populated `reasoning` field and
        # non-zero `reasoning_tokens` with no reasoning parameter sent.
        for m in self.CHEAP:
            self.assertIs(models.get(m).reasoning,
                          models.ReasoningControl.EFFORT)

    def test_both_therefore_get_the_headroom(self):
        for m in self.CHEAP:
            self.assertEqual(infer.ceiling_for(m, 16000),
                             16000 + infer.REASONING_HEADROOM)

    def test_the_ceiling_clears_list_price(self):
        # Stale-high is safe, stale-low is not a ceiling. Every entry must
        # sit above the published rate it was taken from.
        for m, lst in ((self.CHEAP[0], (0.045, 0.140)),
                       (self.CHEAP[1], (0.047, 0.095))):
            pin, pout = infer.price(m)
            self.assertGreater(pin, lst[0])
            self.assertGreater(pout, lst[1])

    def test_they_route_to_openrouter(self):
        for m in self.CHEAP:
            self.assertEqual(infer.provider_for(m), "openrouter")


if __name__ == "__main__":
    unittest.main()
