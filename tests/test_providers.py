# -*- coding: utf-8 -*-
"""The second provider: routing, the wire-format translation, and the money.

`permits/infer.py` spoke to one vendor until 2026-09-23. It now speaks to two,
because the model axis was three Claude tiers - a 5x price band - and a finding
about cost per success measured only inside that band cannot say whether it
survives outside it. Open-weight models reached through OpenRouter are roughly
90x cheaper per draw, which is the spread the claim actually needs.

Adding a provider to a module that prices its own calls creates exactly the
failure family `docs/design/testing.md` is about: code that runs, produces a
number, and the number is wrong. Four of them are specific and each has a test
here.

- **A cached token counted twice.** OpenAI's `prompt_tokens` includes the
  cached prefix; Anthropic's `input_tokens` excludes it and reports it
  separately. Copying the field across without subtracting inflates every
  token sum over the ledger, and the ledger is one table read by `by_class`,
  by the variance analysis and by `scripts/check_internal.py` alike.
- **A truncated response that reads as complete.** OpenAI says `length` where
  Anthropic says `max_tokens`. Every caller tests the `truncated` flag, that
  flag tests the Anthropic spelling, and a synthesis draw that ran out of room
  would otherwise be scored as a bad extractor rather than a short one.
- **Billing from a stale table instead of the invoice.** OpenRouter returns
  what it actually charged. A local table of 459 models whose prices move
  weekly is the hand-maintained vendor capability table
  [ADR-0017](../docs/adr/0017-the-inference-layer-uses-the-vendor-sdk.md) was
  written about, so the reported figure wins and the table is left to do the
  one job it is safe at - the pre-call worst case, where stale-high stops a
  run early.
- **Orphaning 67 paid responses.** The cache is keyed on the request body. If
  the Anthropic body changed by a byte, every response bought before today
  would stop resolving and the variance experiment would have to be paid for
  again. `TestTheAnthropicPathIsUnchanged` pins it.

Nothing here needs the raw store or a credential, and nothing here sends.
"""
import json
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import openai                                                # noqa: E402

from permits import infer                                    # noqa: E402
from tests import requires_raw_store                         # noqa: E402


# --------------------------------------------------------------- fakes
class _FakeUsage(object):
    """An OpenAI usage block. `model_dump` is what the real object offers."""

    def __init__(self, **kw):
        self.kw = kw

    def model_dump(self, mode=None):
        return dict(self.kw)


class _FakeChoice(object):
    def __init__(self, text, finish_reason="stop"):
        self.finish_reason = finish_reason
        self.message = type("M", (), {"content": text})()


class _FakeResponse(object):
    def __init__(self, text="ok", finish_reason="stop", model="x/y",
                 usage=None, choices=None):
        self.model = model
        self.usage = usage
        self.choices = (choices if choices is not None
                        else [_FakeChoice(text, finish_reason)])


class _FakeCompletions(object):
    def __init__(self, result):
        self.result = result
        self.bodies = []

    def create(self, **body):
        self.bodies.append(body)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FakeOAI(object):
    def __init__(self, result):
        self.chat = type("C", (), {"completions": _FakeCompletions(result)})()


class _OAErr(openai.APIError):
    """A vendor error carrying a status, built without a live response."""

    def __init__(self, message, status):
        self.status_code = status
        Exception.__init__(self, message)


class ClientCase(unittest.TestCase):
    """A Client on a temp root, with no credential unless a test sets one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = infer.Client(self.tmp, 10.0, api_key="a",
                                   openrouter_key="b")

    def rows(self):
        return self.client.ledger.rows()

    def install(self, result):
        fake = _FakeOAI(result)
        self.client._oai = fake
        return fake.chat.completions


# ------------------------------------------------- the invariant that pays
class TestTheAnthropicPathIsUnchanged(unittest.TestCase):
    """The 67 responses in `data/infer/cache` are worth $4.34 and must resolve.

    ADR-0017 made this the binding constraint on how the SDK swap could be
    made, and it is the binding constraint on adding a provider too. These are
    golden values: if `build` or `_key_for` changes for an Anthropic model,
    they fail, and that failure is the reminder that every paid response just
    became unreachable.
    """

    def setUp(self):
        self.c = infer.Client.__new__(infer.Client)

    def test_the_request_body_is_what_it_has_always_been(self):
        self.assertEqual(
            self.c.build("claude-opus-5", "SYS", "USER", 8000, True, None),
            {"model": "claude-opus-5",
             "max_tokens": 8000,
             "system": [{"type": "text", "text": "SYS",
                         "cache_control": {"type": "ephemeral"}}],
             "messages": [{"role": "user", "content": "USER"}],
             "thinking": {"type": "adaptive"}})

    def test_a_known_key_still_hashes_the_same(self):
        body = self.c.build("claude-opus-5", "SYS", "USER", 8000, True, None)
        self.assertEqual(self.c._key_for(body, 0), "a06bc393976057fe82f3d860")
        self.assertEqual(self.c._key_for(body, 3), "1225906a28138fdc57fd1358")

    def test_every_response_on_disk_is_still_addressable(self):
        """Not a replay - a shape check that the store was not invalidated.

        A cache file whose name is not 24 hex characters would mean the key
        function changed length or alphabet, which orphans the lot at once.

        Gated on the raw store rather than on the cache directory existing:
        `Client.__init__` creates that directory, so another test constructing
        a client at ROOT makes an empty one appear, and "empty" would then
        read as "every paid response is gone". That is the published-slice
        confusion `tests/__init__.PUBLISHED` exists to prevent, met again.
        """
        requires_raw_store(self, "the cache-key format check")
        d = os.path.join(ROOT, "data", "infer", "cache")
        names = [f[:-5] for f in os.listdir(d) if f.endswith(".json")]
        self.assertTrue(names, "cache directory is empty")
        for n in names:
            self.assertEqual(len(n), 24, "%s is not a current-format key" % n)
            int(n, 16)


# ------------------------------------------------------------- routing
class TestProviderRouting(unittest.TestCase):

    def test_a_slash_selects_openrouter(self):
        for m in ("qwen/qwen3-coder", "openai/gpt-oss-120b:batch",
                  "deepseek/deepseek-v4-pro"):
            self.assertEqual(infer.provider_for(m), infer.OPENROUTER)

    def test_a_first_party_id_selects_anthropic(self):
        for m in infer.PRICES:
            self.assertEqual(infer.provider_for(m), infer.ANTHROPIC)

    def test_the_same_question_to_two_providers_is_two_cache_entries(self):
        """Otherwise the second provider reads the first one's answer.

        The bodies differ in shape and both carry `model`, so this holds
        without a migration - but it is the property the whole design rests
        on, so it is asserted rather than assumed.
        """
        c = infer.Client.__new__(infer.Client)
        a = c._key_for(c.build("claude-opus-5", "S", "U", 100), 0)
        o = c._key_for(c.build_chat("qwen/qwen3-coder", "S", "U", 100), 0)
        self.assertNotEqual(a, o)

    def test_short_model_is_filename_safe(self):
        """It names files under `data/infer/synth`; a slash is a directory."""
        for m in list(infer.OPENROUTER_PRICES) + list(infer.PRICES):
            self.assertNotIn("/", infer.short_model(m))
            self.assertTrue(infer.short_model(m))

    def test_short_model_did_not_move_for_anthropic(self):
        """Artifacts already on disk are named by it; renaming orphans them."""
        self.assertEqual(infer.short_model("claude-haiku-4-5-20251001"),
                         "haiku-4-5")
        self.assertEqual(infer.short_model("claude-opus-5"), "opus-5")
        self.assertEqual(infer.short_model("claude-sonnet-5"), "sonnet-5")


# -------------------------------------------------- the translation layer
class TestUsageTranslation(unittest.TestCase):

    def test_cached_tokens_are_not_counted_twice(self):
        """`prompt_tokens` includes the cached prefix; `input_tokens` must not.

        1000 prompt tokens of which 400 were cached is 600 fresh, not 1000.
        Getting this wrong inflates every token sum over the ledger by the
        cached amount and the error grows with how well caching works.
        """
        u, _ = infer._usage_from_chat(_FakeUsage(
            prompt_tokens=1000, completion_tokens=50,
            prompt_tokens_details={"cached_tokens": 400}))
        self.assertEqual(u["input_tokens"], 600)
        self.assertEqual(u["cache_read_input_tokens"], 400)
        self.assertEqual(u["output_tokens"], 50)

    def test_fields_carry_anthropic_names(self):
        """One ledger schema, or every reader needs a provider branch."""
        u, _ = infer._usage_from_chat(_FakeUsage(prompt_tokens=7,
                                                 completion_tokens=3))
        self.assertEqual(sorted(u), ["cache_creation_input_tokens",
                                     "cache_read_input_tokens",
                                     "input_tokens", "output_tokens"])

    def test_a_missing_usage_block_is_zeros_not_a_crash(self):
        u, billed = infer._usage_from_chat(None)
        self.assertEqual(u["input_tokens"], 0)
        self.assertIsNone(billed)

    def test_truncation_survives_the_rename(self):
        """`length` must become `max_tokens` or truncation goes silent."""
        self.assertEqual(infer.FINISH_REASONS["length"], "max_tokens")
        self.assertEqual(infer.FINISH_REASONS["stop"], "end_turn")

    def test_an_unknown_finish_reason_is_passed_through_not_dropped(self):
        c = infer.Client.__new__(infer.Client)
        c._oai = _FakeOAI(_FakeResponse(finish_reason="weird",
                                        usage=_FakeUsage(prompt_tokens=1,
                                                         completion_tokens=1)))
        _t, _u, stop, _m, _b = c._send_chat({"model": "x/y"})
        self.assertEqual(stop, "weird")


# --------------------------------------------------------------- money
class TestWhatGetsBilled(ClientCase):

    def test_the_reported_cost_wins_over_the_table(self):
        """The provider's invoice is authoritative; the table is an estimate.

        The table price for this call is deliberately nowhere near 0.25, so a
        row billed from the table would be visibly different.
        """
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=1000, completion_tokens=1000, cost=0.25)))
        _t, _u, meta = self.client.message(
            "qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertAlmostEqual(meta["usd"], 0.25)
        row = self.rows()[-1]
        self.assertAlmostEqual(row["usd"], 0.25)
        self.assertTrue(row["usd_reported"])

    def test_without_a_reported_cost_the_table_is_used_and_said_so(self):
        """Falling back is fine. Falling back silently is not."""
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=1000, completion_tokens=1000)))
        _t, _u, meta = self.client.message(
            "qwen/qwen3-coder", "S", "U", 100, "synthesis")
        pin, pout = infer.OPENROUTER_PRICES["qwen/qwen3-coder"]
        self.assertAlmostEqual(meta["usd"], (1000 * pin + 1000 * pout) / 1e6)
        self.assertFalse(self.rows()[-1]["usd_reported"])

    def test_an_unpriced_model_is_refused_and_names_its_table(self):
        with self.assertRaises(infer.Refused) as cm:
            infer.price("nobody/nothing")
        self.assertIn("OPENROUTER_PRICES", str(cm.exception))
        with self.assertRaises(infer.Refused) as cm:
            infer.price("claude-imaginary")
        self.assertIn("PRICES", str(cm.exception))

    def test_the_budget_guard_uses_the_openrouter_table(self):
        """A ceiling that only knows Anthropic prices is not a ceiling."""
        b = infer.Budget(0.0001)
        with self.assertRaises(infer.Refused):
            b.check("deepseek/deepseek-v4-pro", 1_000_000, 100_000)


# ------------------------------------------------------- the request shape
class TestOpenRouterRequestShape(unittest.TestCase):

    def setUp(self):
        self.c = infer.Client.__new__(infer.Client)

    def test_no_cache_control_is_sent(self):
        """It is an Anthropic field. Sending it is asking for a 400."""
        body = self.c.build_chat("qwen/qwen3-coder", "S", "U", 100)
        self.assertNotIn("cache_control", repr(body))
        self.assertEqual(body["messages"][0],
                         {"role": "system", "content": "S"})

    def test_reasoning_is_sent_only_where_it_exists(self):
        """OpenRouter ignores it silently elsewhere, and a run written up as
        controlled when it was not is worse than a rejected request."""
        on = self.c.build_chat("deepseek/deepseek-v4-pro", "S", "U", 100,
                               thinking=True)
        self.assertEqual(on["reasoning_effort"], "medium")
        off = self.c.build_chat("qwen/qwen3-coder", "S", "U", 100,
                                thinking=True)
        self.assertNotIn("reasoning_effort", off)

    def test_every_reasoning_model_is_a_priced_model(self):
        self.assertTrue(
            set(infer.OPENROUTER_REASONING) <= set(infer.OPENROUTER_PRICES),
            "a model can be asked to reason that cannot be priced")

    def test_temperature_is_not_refused_alongside_thinking(self):
        """`build` refuses that because the Anthropic API 400s on it. That is
        a fact about one vendor, not a house rule."""
        body = self.c.build_chat("deepseek/deepseek-v4-pro", "S", "U", 100,
                                 thinking=True, temperature=0.0)
        self.assertEqual(body["temperature"], 0.0)

    def test_max_tokens_keeps_the_name_openrouter_accepts(self):
        body = self.c.build_chat("qwen/qwen3-coder", "S", "U", 4242)
        self.assertEqual(body["max_tokens"], 4242)
        self.assertNotIn("max_completion_tokens", body)


# ---------------------------------------------------------- credentials
class TestCredentials(unittest.TestCase):

    def assertNoCredential(self, value, what):
        """Assert emptiness by length, never by comparing against the value.

        `assertEqual(key, "")` prints both sides on failure, so the one test
        that catches a credential leaking in from the environment would be
        the thing that published it. Found the hard way: before
        `Client.__init__` distinguished `None` from `""`, this assertion
        failed on a machine with a key file and printed the key.
        """
        self.assertEqual(len(value), 0,
                         "%s: expected no credential, got %d characters"
                         % (what, len(value)))

    def test_one_key_does_not_read_as_the_other(self):
        """Otherwise a run dies mid-allocation with some cells paid for."""
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="anth",
                         openrouter_key="")
        self.assertEqual(c.key_for("claude-opus-5"), "anth")
        self.assertNoCredential(c.key_for("qwen/qwen3-coder"), "openrouter")

    def test_an_explicit_empty_key_is_not_a_request_to_read_the_disk(self):
        """`None` means resolve; `""` means there is none. `or` collapsed the
        two, so the suite's "no API key needed" claim in the README held only
        on machines that happened to have no key file."""
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="",
                         openrouter_key="")
        self.assertNoCredential(c.key_for("claude-opus-5"), "anthropic")
        self.assertNoCredential(c.key_for("qwen/qwen3-coder"), "openrouter")

    def test_a_missing_key_refuses_before_the_socket(self):
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="anth",
                         openrouter_key="")
        with self.assertRaises(infer.Refused) as cm:
            c.message("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertIn("OPENROUTER_API_KEY", str(cm.exception))

    def test_the_key_file_sits_outside_the_project_tree(self):
        """Same rule as KEY_FILE: a credential beside the data directory is
        one careless archive away from being shared."""
        self.assertNotIn(os.path.abspath(ROOT),
                         os.path.abspath(infer.OPENROUTER_KEY_FILE))

    def test_a_key_file_with_a_utf8_bom_still_reads(self):
        """Found on the first live call. Notepad and PowerShell's `Out-File`
        both write a BOM, `str.strip()` does not remove U+FEFF because it is
        not whitespace, and the vendor answers a BOM'd bearer token with a 401
        that reads as a bad key rather than a bad file."""
        d = tempfile.mkdtemp()
        p = os.path.join(d, "key")
        with io.open(p, "w", encoding="utf-8-sig") as fh:
            fh.write("sk-or-v1-abc\n")
        self.assertEqual(infer.read_openrouter_key(p), "sk-or-v1-abc")

    def test_a_key_file_without_a_bom_is_unchanged(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "key")
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write("sk-or-v1-abc\n")
        self.assertEqual(infer.read_openrouter_key(p), "sk-or-v1-abc")

    def test_a_dry_run_needs_no_credential(self):
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="", dry_run=True,
                         openrouter_key="")
        with self.assertRaises(infer.Refused) as cm:
            c.message("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertIn("dry run", str(cm.exception))


# --------------------------------------------------------------- ledger
class TestTheLedgerKnowsWhoWasCalled(ClientCase):

    def test_a_row_records_its_provider(self):
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        self.client.message("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertEqual(self.rows()[-1]["provider"], "openrouter")

    def test_a_failed_call_is_a_row_on_this_provider_too(self):
        """The hole ADR-0017 closed for one vendor, closed for the other."""
        self.install(_OAErr("rate limited", 429))
        with self.assertRaises(infer.ApiError):
            self.client.message("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        row = self.rows()[-1]
        self.assertFalse(row["ok"])
        self.assertEqual(row["provider"], "openrouter")
        self.assertEqual(row["status_code"], 429)
        self.assertEqual(row["usd"], 0.0)

    def test_a_response_with_no_choices_is_an_error_not_empty_text(self):
        """Empty text reads downstream as an extractor that produced nothing,
        which scores as a model failure rather than a transport one."""
        self.install(_FakeResponse(choices=[], usage=_FakeUsage(
            prompt_tokens=1, completion_tokens=0)))
        with self.assertRaises(infer.ApiError):
            self.client.message("qwen/qwen3-coder", "S", "U", 100, "synthesis")

    def test_a_truncated_draw_is_flagged_through_the_whole_path(self):
        self.install(_FakeResponse(finish_reason="length", usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=100, cost=0.01)))
        _t, _u, meta = self.client.message(
            "qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertTrue(meta["truncated"])
        self.assertEqual(self.rows()[-1]["stop_reason"], "max_tokens")

    def test_a_second_call_is_served_from_cache_and_bills_nothing(self):
        comp = self.install(_FakeResponse(text="hello", usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        args = ("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.client.message(*args)
        text, _u, meta = self.client.message(*args)
        self.assertEqual(len(comp.bodies), 1, "the cache did not hit")
        self.assertEqual(text, "hello")
        self.assertTrue(meta["cached"])
        self.assertEqual(meta["usd"], 0.0)


# ------------------------------------------------------- the price table
class TestThePriceTableIsUsable(unittest.TestCase):

    def test_every_entry_is_a_pair_of_rates(self):
        for m, pair in infer.OPENROUTER_PRICES.items():
            self.assertEqual(len(pair), 2, m)
            self.assertTrue(all(float(x) >= 0 for x in pair), m)

    def test_a_zero_price_is_declared_free_not_merely_zero(self):
        """A dropped digit prices a paid model at nothing, the budget guard
        then admits it unconditionally, and the ledger reports a run that
        cost nothing. Free is a real category; it has to be said out loud."""
        for m, (pin, pout) in infer.OPENROUTER_PRICES.items():
            if pin == 0 or pout == 0:
                self.assertIn(m, infer.OPENROUTER_FREE,
                              "%s is priced at zero but not declared free" % m)

    def test_a_free_endpoint_is_not_offered_as_a_measurement(self):
        """Free routing does not promise a fixed upstream or quantization, so
        draws from it are not samples of one condition."""
        self.assertTrue(
            set(infer.OPENROUTER_FREE) <= set(infer.OPENROUTER_PRICES))
        self.assertFalse(set(infer.OPENROUTER_FREE)
                         & set(infer.OPENROUTER_REASONING))

    def test_the_table_is_dated(self):
        """A price that moved makes every dollar figure wrong while every
        token figure stays right - so the date is not decoration."""
        self.assertRegex(infer.OPENROUTER_PRICES_AS_OF, r"^\d{4}-\d{2}-\d{2}")

    def test_the_axis_actually_widened(self):
        """The reason this provider exists. If the cheapest open-weight row
        is not an order of magnitude below Haiku, the second vendor bought
        nothing and this whole path should be reconsidered.
        """
        syn_in, syn_out = 13535, 4415

        def draw(m):
            pin, pout = infer.price(m)
            return (syn_in * pin + syn_out * pout) / 1e6

        dearest = max(draw(m) for m in infer.PRICES)
        cheapest = min(draw(m) for m in infer.OPENROUTER_PRICES
                       if m not in infer.OPENROUTER_FREE)
        self.assertGreater(dearest / cheapest, 50.0,
                           "the model axis is no wider than it was")


class TestTruncationIsDecidedOnFacts(unittest.TestCase):
    """A cut-off answer that reads as complete is the failure this project
    exists to measure, so the flag does not rest on the provider's label
    alone. An OpenRouter upstream returned `finish_reason: null` on
    2026-09-24, and null equals no spelling of truncation at all."""

    def test_the_label_is_believed_when_present(self):
        self.assertTrue(infer.truncated(
            "max_tokens", {"output_tokens": 10}, 16000))

    def test_a_null_label_does_not_hide_a_full_budget(self):
        self.assertTrue(infer.truncated(
            None, {"output_tokens": 16000}, 16000))

    def test_an_unmapped_label_does_not_hide_a_full_budget(self):
        self.assertTrue(infer.truncated(
            "provider_specific_thing", {"output_tokens": 16000}, 16000))

    def test_a_short_answer_is_not_truncated(self):
        self.assertFalse(infer.truncated(
            "end_turn", {"output_tokens": 1319}, 16000))

    def test_missing_usage_does_not_raise(self):
        self.assertFalse(infer.truncated("end_turn", None, 16000))
        self.assertFalse(infer.truncated("end_turn", {}, 0))


# --------------------------------------------- the ceiling is not the answer
class TestReasoningGetsRoomToThink(ClientCase):
    """OpenRouter bills reasoning and output from one allowance, so an equal
    `max_tokens` is an unequal experiment: the thinking model answers from
    what is left, the other answers from all of it.

    Measured 2026-09-24 at a flat 16,000, glm-5.2 spent the entire budget
    reasoning on both clarkco draws and emitted no extractor either time. The
    scored result was 0/2. That is not a capability measurement, it is the
    ceiling showing up in the table under a model's name, and it is the exact
    shape of harness artifact this suite exists to catch.
    """

    def test_a_reasoning_model_gets_headroom_on_top(self):
        self.assertEqual(infer.ceiling_for("z-ai/glm-5.2", 16000),
                         16000 + infer.REASONING_HEADROOM)

    def test_every_reasoning_model_gets_it(self):
        for m in infer.OPENROUTER_REASONING:
            self.assertGreater(infer.ceiling_for(m, 8000), 8000, m)

    def test_a_non_reasoning_model_is_untouched(self):
        """Including the ones that merely happen to be verbose. qwen3.5-flash
        averaged 9,817 output tokens on stjohns without a reasoning
        parameter, which is a property of the model and not a request for
        headroom; granting it here would hand one cheap model a larger budget
        than the others it is being compared against."""
        for m in ("qwen/qwen3.5-flash-02-23", "openai/gpt-oss-120b",
                  "qwen/qwen3-coder"):
            self.assertEqual(infer.ceiling_for(m, 16000), 16000, m)

    def test_the_anthropic_path_cannot_move(self):
        """The property the response cache is worth $4.34 of."""
        for m in ("claude-opus-5", "claude-sonnet-5",
                  "claude-haiku-4-5-20251001"):
            self.assertEqual(infer.ceiling_for(m, 16000), 16000, m)

    def test_the_budget_is_checked_against_what_can_actually_be_spent(self):
        """Raise the ceiling in the request body alone and the guard
        authorizes a third of what the call may draw. The ceiling is resolved
        once, before anything reads it."""
        seen = []
        self.client.budget.check = lambda m, i, o: seen.append((m, i, o))
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        self.client.message("z-ai/glm-5.2", "S", "U", 16000, "synthesis")
        self.assertEqual(seen[-1][2], 16000 + infer.REASONING_HEADROOM)

    def test_the_wire_carries_the_raised_ceiling(self):
        comps = self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        self.client.message("z-ai/glm-5.2", "S", "U", 16000, "synthesis")
        self.assertEqual(comps.bodies[-1]["max_tokens"],
                         16000 + infer.REASONING_HEADROOM)

    def test_the_projection_and_the_guard_quote_the_same_number(self):
        """`plan` prints a worst case, `Budget.check` enforces one, and they
        are computed at different sites from the same arguments. Raise the
        ceiling at one and not the other and the run is pre-authorized for a
        third of what it can spend - the printed figure is what a person reads
        before typing --run, so the two have to agree by construction."""
        projected = infer.estimate(
            "z-ai/glm-5.2", 9000,
            infer.ceiling_for("z-ai/glm-5.2", 16000))
        b = infer.Budget(projected + 1e-9)
        b.check("z-ai/glm-5.2", 9000,
                infer.ceiling_for("z-ai/glm-5.2", 16000))
        b.ceiling = projected - 1e-4
        with self.assertRaises(infer.Refused):
            b.check("z-ai/glm-5.2", 9000,
                    infer.ceiling_for("z-ai/glm-5.2", 16000))

    def test_thinking_to_the_old_ceiling_is_no_longer_truncation(self):
        """The 16,000-token reasoning burn that voided the first run reads as
        a complete answer once the answer budget is actually 16,000."""
        ceiling = infer.ceiling_for("z-ai/glm-5.2", 16000)
        self.assertFalse(infer.truncated(
            "stop", {"output_tokens": 16000}, ceiling))
        self.assertTrue(infer.truncated(
            "stop", {"output_tokens": ceiling}, ceiling))


# ------------------------------------------ the table is a ceiling, not a bill
class TestTheEstimatorStaysAboveTheInvoice(unittest.TestCase):
    """`OPENROUTER_PRICES` exists for one thing: the pre-call worst case. A
    rate below what the provider actually charges is not a ceiling.

    The quantity to reconcile against is the FULL prompt. `input_tokens`
    excludes the cached portion - `_usage_from_chat` subtracts it so the two
    providers' ledger rows mean the same thing - but a cached read is
    discounted, not free, so pricing a row off `input_tokens` alone
    understates it. Measured here that artifact was worth 4.5x on a single
    qwen3-coder row and looked exactly like a stale price, which is the whole
    reason this test names the quantity instead of assuming it.
    """

    def rows(self):
        path = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
        if not os.path.exists(path):
            self.skipTest("no ledger on this checkout")
        out = []
        with io.open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if (r.get("provider") == infer.OPENROUTER
                        and r.get("usd_reported") and r.get("usd", 0) > 0
                        and r.get("model") in infer.OPENROUTER_PRICES):
                    out.append(r)
        return out

    def test_no_paid_call_billed_more_than_the_table_projected(self):
        rows = self.rows()
        self.assertGreater(len(rows), 50, "too few paid rows to reconcile")
        for r in rows:
            with self.subTest(model=r["model"], at=r.get("at")):
                full_in = (r.get("input_tokens", 0)
                           + r.get("cache_read_input_tokens", 0))
                projected = infer.estimate(r["model"], full_in,
                                           r.get("output_tokens", 0))
                self.assertGreaterEqual(
                    round(projected, 6), round(r["usd"], 6),
                    "%s billed $%.5f against a projection of $%.5f; the "
                    "table is stale-low and no longer bounds the call"
                    % (r["model"], r["usd"], projected))

    def test_the_reconciled_entries_are_not_silently_list_price(self):
        """Refresh this table from the model list and every reconciled entry
        drops back to list, the ceiling quietly stops being one, and nothing
        fails. This is the tripwire for that."""
        above_list = {"z-ai/glm-5.2": 2.042,
                      "deepseek/deepseek-v4-pro": 1.879,
                      "openai/gpt-oss-120b": 0.600,
                      "qwen/qwen3-coder": 1.000}
        for model, listed in above_list.items():
            with self.subTest(model=model):
                self.assertGreater(infer.OPENROUTER_PRICES[model][1], listed)
        self.assertIn("reconciled", infer.OPENROUTER_PRICES_AS_OF)


if __name__ == "__main__":
    unittest.main()
