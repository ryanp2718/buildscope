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

from permits import infer, models                                 # noqa: E402
from permits.models import Protocol                                 # noqa: E402
from tests import requires_raw_store                         # noqa: E402


# --------------------------------------------------------------- fakes
class _FakeUsage(object):
    """An OpenAI usage block. `model_dump` is what the real object offers."""

    def __init__(self, **kw):
        self.kw = kw

    def model_dump(self, mode=None):
        return dict(self.kw)


class _FakeChoice(object):
    """One streamed choice: the whole answer in a single delta."""

    def __init__(self, text, finish_reason="stop"):
        self.finish_reason = finish_reason
        self.delta = type("D", (), {"content": text})()


class _FakeChunk(object):
    def __init__(self, model, choices, usage, provider=None, id="gen-1"):
        self.id = id
        self.model = model
        self.choices = choices
        self.usage = usage
        self.provider = provider


class _FakeResponse(object):
    """A streamed chat completion, as `create(..., stream=True)` returns it:
    a context manager yielding one chunk per choice, then the usage chunk
    that `include_usage` asks for. `usage=None` sends an empty usage block,
    which reads as zeros, the same as a missing block did unstreamed."""

    def __init__(self, text="ok", finish_reason="stop", model="x/y",
                 usage=None, choices=None, host=None):
        self.model = model
        self.host = host
        self.usage = usage if usage is not None else _FakeUsage()
        self.choices = (choices if choices is not None
                        else [_FakeChoice(text, finish_reason)])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for c in self.choices:
            yield _FakeChunk(self.model, [c], None, self.host)
        yield _FakeChunk(self.model, [], self.usage, self.host)


class _FakeCompletions(object):
    """`bodies` holds the request body as it goes on the wire, `extra_body`
    merged back in; the streaming arguments, which the client passes beside
    the body and never in it, go to `transport`, and the names that went
    through `extra_body` to `extras`."""

    def __init__(self, result):
        self.result = result
        self.bodies = []
        self.transport = []
        self.extras = []

    def create(self, **kw):
        self.transport.append({k: kw.pop(k) for k in ("stream",
                                                      "stream_options")
                               if k in kw})
        extra = kw.pop("extra_body", None) or {}
        self.extras.append(sorted(extra))
        kw.update(extra)
        self.bodies.append(kw)
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

    def test_the_user_breakpoint_is_opt_in(self):
        """A variance cell resends one prompt, so it caches the whole of it.
        Every other caller, and every response bought before the flag, gets
        the body above unchanged."""
        body = self.c.build("claude-opus-5-5", "SYS", "USER", 8000, True, None,
                            cache_user=True)
        self.assertEqual(body["messages"],
                         [{"role": "user",
                           "content": [{"type": "text", "text": "USER",
                                        "cache_control":
                                            {"type": "ephemeral"}}]}])
        self.assertEqual(body["system"][0]["cache_control"],
                         {"type": "ephemeral"})
        self.assertEqual(
            self.c.request("claude-opus-5-5", "SYS", "USER", 8000, True),
            dict(body, messages=[{"role": "user", "content": "USER"}]))

    def test_openrouter_has_no_user_breakpoint(self):
        body = self.c.request("qwen/qwen3-coder", "S", "U", 100,
                              cache_user=True)
        self.assertNotIn("cache_control", repr(body))

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

    def test_every_slashed_id_is_registered_to_openrouter(self):
        """OpenRouter addresses models as `vendor/model` and no Anthropic
        first-party id contains a slash. The provider is a registry field
        now, so this checks the registry agrees with the addressing scheme."""
        for m, s in models.REGISTRY.items():
            self.assertEqual(s.provider,
                             infer.OPENROUTER if "/" in m else infer.ANTHROPIC,
                             m)
            self.assertEqual(infer.provider_for(m), s.provider)

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
        """It names files under `data/infer/synth`. A slash is a directory,
        and on NTFS a colon writes an alternate data stream of the file named
        by whatever precedes it, so `gpt-oss-120b:batch` is not a file."""
        for m in models.REGISTRY:
            short = infer.short_model(m)
            self.assertTrue(short, m)
            self.assertFalse(set(short) & set('<>:"/\\|?*'), m)

    def test_short_names_are_unique(self):
        """Two models with one short name write to the same files."""
        shorts = [s.short for s in models.REGISTRY.values()]
        self.assertEqual(len(shorts), len(set(shorts)))

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
        self.assertEqual(c._send_chat({"model": "x/y"}).stop_reason, "weird")


# --------------------------------------------------------------- money
class TestWhatGetsBilled(ClientCase):

    def test_the_reported_cost_wins_over_the_table(self):
        """The provider's invoice is authoritative; the table is an estimate.

        The table price for this call is deliberately nowhere near 0.25, so a
        row billed from the table would be visibly different.
        """
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=1000, completion_tokens=1000, cost=0.25)))
        reply = self.client.message(
            "qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertAlmostEqual(reply.usd, 0.25)
        row = self.rows()[-1]
        self.assertAlmostEqual(row.usd, 0.25)
        self.assertTrue(row.usd_reported)

    def test_without_a_reported_cost_the_table_is_used_and_said_so(self):
        """Falling back is fine. Falling back silently is not."""
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=1000, completion_tokens=1000)))
        reply = self.client.message(
            "qwen/qwen3-coder", "S", "U", 100, "synthesis")
        pin, pout = infer.price("qwen/qwen3-coder")
        self.assertAlmostEqual(reply.usd, (1000 * pin + 1000 * pout) / 1e6)
        self.assertFalse(self.rows()[-1].usd_reported)

    def test_an_unregistered_model_is_refused_and_says_where_to_add_it(self):
        for m in ("nobody/nothing", "claude-imaginary"):
            with self.assertRaises(infer.Refused) as cm:
                infer.price(m)
            self.assertIn("permits/models.py", str(cm.exception))

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
        off = self.c.build_chat("qwen/qwen3-coder", "S", "U", 100,
                                thinking=True)
        self.assertNotIn("reasoning", off)
        self.assertNotIn("reasoning_effort", off)

    def test_v1_sent_medium_to_its_five_and_nothing_else(self):
        """The frozen shape the v1 cells were bought with."""
        on = self.c.build_chat("deepseek/deepseek-v4-pro", "S", "U", 100,
                               thinking=True, protocol=Protocol.V1)
        self.assertEqual(on, {
            "model": "deepseek/deepseek-v4-pro", "max_tokens": 100,
            "messages": [{"role": "system", "content": "S"},
                         {"role": "user", "content": "U"}],
            "reasoning_effort": "medium"})
        for m in ("openai/gpt-oss-120b", "qwen/qwen3.5-flash-02-23"):
            self.assertEqual(
                set(self.c.build_chat(m, "S", "U", 100, thinking=True,
                                      protocol=Protocol.V1)),
                {"model", "max_tokens", "messages"}, m)

    def test_v2_asks_for_the_labs_default_level(self):
        """Four of v1's five were sent "medium", which their catalogue
        entries do not list. glm-5.2's catalogue default is `high`; Z.ai's
        is `max`, which `xhigh` reaches."""
        want = {"deepseek/deepseek-v4-pro": {"effort": "high"},
                "z-ai/glm-5.2": {"effort": "xhigh"},
                "z-ai/glm-5.3-flash": {"effort": "max"},
                "openai/gpt-oss-120b": {"effort": "medium"},
                "moonshotai/kimi-k2-thinking": {"enabled": True},
                "qwen/qwen3.5-flash-02-23": {"enabled": True}}
        for m, r in want.items():
            with self.subTest(model=m):
                body = self.c.build_chat(m, "S", "U", 100, thinking=True)
                self.assertEqual(body["reasoning"], r)
                self.assertNotIn("reasoning_effort", body)

    def test_an_effort_the_catalogue_does_not_list_is_refused(self):
        self.assertEqual(self.c.build_chat(
            "z-ai/glm-5.3-flash", "S", "U", 100, thinking=True,
            effort="low")["reasoning"], {"effort": "low"})
        for m, e in (("z-ai/glm-5.2", "medium"),
                     ("moonshotai/kimi-k2-thinking", "high"),
                     ("qwen/qwen3-coder", "low")):
            with self.subTest(model=m), self.assertRaises(infer.Refused):
                self.c.build_chat(m, "S", "U", 100, thinking=True, effort=e)

    def test_sampling_and_routing_are_sent_from_the_registry(self):
        body = self.c.build_chat("qwen/qwen3-coder", "S", "U", 100)
        self.assertEqual((body["temperature"], body["top_p"]), (0.7, 0.8))
        self.assertEqual(body["provider"], {
            "require_parameters": True,
            "quantizations": ["fp8", "fp16", "bf16"]})
        # Endpoints measured ignoring the effort setting, then one whose
        # output limit is below the cap, named by its tag alone.
        ds = self.c.build_chat("deepseek/deepseek-v4-pro", "S", "U", 100,
                               thinking=True)
        self.assertEqual(ds["provider"]["ignore"],
                         ["novita", "parasail", "deepinfra/fp8"])
        # Closed weights with no published sampling, on endpoints that take
        # none: nothing is sent and no precision filter applies.
        sol = self.c.build_chat("openai/gpt-6-sol", "S", "U", 100,
                                thinking=True)
        self.assertNotIn("temperature", sol)
        self.assertNotIn("top_p", sol)
        self.assertEqual(sol["provider"], {"require_parameters": True})
        self.assertEqual(sol["reasoning"], {"effort": "medium"})
        # One lab-run host that reports no precision, so `unknown` is admitted
        # beside the fp8 the lab released; without it the model has no host.
        only = self.c.build_chat("qwen/qwen3.5-flash-02-23", "S", "U", 100)
        self.assertEqual(only["provider"]["quantizations"],
                         ["fp8", "fp16", "bf16", "unknown"])
        self.assertEqual((only["temperature"], only["top_p"]), (0.6, 0.95))

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
        self.assertEqual(self.rows()[-1].provider, "openrouter")

    def test_a_failed_call_is_a_row_on_this_provider_too(self):
        """The hole ADR-0017 closed for one vendor, closed for the other."""
        self.install(_OAErr("rate limited", 429))
        with self.assertRaises(infer.ApiError):
            self.client.message("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        row = self.rows()[-1]
        self.assertFalse(row.ok)
        self.assertEqual(row.provider, "openrouter")
        self.assertEqual(row.status_code, 429)
        self.assertEqual(row.usd, 0.0)

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
        reply = self.client.message(
            "qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.assertTrue(reply.truncated)
        self.assertEqual(self.rows()[-1].stop_reason, "max_tokens")

    def test_a_second_call_is_served_from_cache_and_bills_nothing(self):
        comp = self.install(_FakeResponse(text="hello", usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        args = ("qwen/qwen3-coder", "S", "U", 100, "synthesis")
        self.client.message(*args)
        reply = self.client.message(*args)
        self.assertEqual(len(comp.bodies), 1, "the cache did not hit")
        self.assertEqual(reply.text, "hello")
        self.assertTrue(reply.cached)
        self.assertEqual(reply.usd, 0.0)


# ------------------------------------------------------- the price table
class TestThePriceTableIsUsable(unittest.TestCase):

    def test_every_entry_is_a_pair_of_rates(self):
        for m, s in models.REGISTRY.items():
            for pair in (s.price, s.list_price):
                self.assertEqual(len(pair), 2, m)
                self.assertTrue(all(float(x) >= 0 for x in pair), m)

    def test_a_zero_price_is_declared_free_not_merely_zero(self):
        """A dropped digit prices a paid model at nothing, the budget guard
        then admits it unconditionally, and the ledger reports a run that
        cost nothing. Free is a real category; it has to be said out loud."""
        for m, s in models.REGISTRY.items():
            if 0 in s.price:
                self.assertIs(s.tier, models.Tier.FREE,
                              "%s is priced at zero but not declared free" % m)

    def test_a_free_endpoint_is_not_offered_as_a_measurement(self):
        """Free routing does not promise a fixed upstream or quantization, so
        draws from it are not samples of one condition."""
        free = [s for s in models.REGISTRY.values()
                if s.tier is models.Tier.FREE]
        self.assertTrue(free)
        for s in free:
            self.assertNotIn(s, models.measured())
            self.assertIs(s.reasoning, models.ReasoningControl.NONE)

    def test_every_ceiling_is_at_or_above_list(self):
        """Stale-high is safe; a ceiling below the published rate is not a
        ceiling. For Anthropic the two are the same number."""
        for m, s in models.REGISTRY.items():
            with self.subTest(model=m):
                self.assertGreaterEqual(s.price[0], s.list_price[0])
                self.assertGreaterEqual(s.price[1], s.list_price[1])
                if s.provider is models.Provider.ANTHROPIC:
                    self.assertEqual(s.price, s.list_price)

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

        dearest = max(draw(s.id) for s in models.measured()
                      if s.provider is models.Provider.ANTHROPIC)
        cheapest = min(draw(s.id) for s in models.measured()
                       if s.provider is models.Provider.OPENROUTER)
        self.assertGreater(dearest / cheapest, 50.0,
                           "the model axis is no wider than it was")


class TestTruncationIsDecidedOnFacts(unittest.TestCase):
    """A cut-off answer that reads as complete is the failure this project
    exists to measure, so the flag does not rest on the provider's label
    alone. An OpenRouter upstream returned `finish_reason: null` on
    2026-09-24, and null equals no spelling of truncation at all."""

    def test_the_label_is_believed_when_present(self):
        self.assertTrue(infer.truncated(
            "max_tokens", infer.Usage(output_tokens=10), 16000))

    def test_a_null_label_does_not_hide_a_full_budget(self):
        self.assertTrue(infer.truncated(
            None, infer.Usage(output_tokens=16000), 16000))

    def test_an_unmapped_label_does_not_hide_a_full_budget(self):
        self.assertTrue(infer.truncated(
            "provider_specific_thing", infer.Usage(output_tokens=16000), 16000))

    def test_a_natural_stop_past_the_cap_is_not_truncated(self):
        """xAI let grok-4.7 run to 66,437 tokens against 64,000 and it
        stopped on `end_turn` with a complete answer (2026-09-28)."""
        self.assertFalse(infer.truncated(
            "end_turn", infer.Usage(output_tokens=66437), 64000))
        self.assertTrue(infer.truncated(
            "max_tokens", infer.Usage(output_tokens=64000), 64000))

    def test_a_short_answer_is_not_truncated(self):
        self.assertFalse(infer.truncated(
            "end_turn", infer.Usage(output_tokens=1319), 16000))

    def test_missing_usage_does_not_raise(self):
        self.assertFalse(infer.truncated("end_turn", None, 16000))
        self.assertFalse(infer.truncated("end_turn", infer.Usage(), 0))


# --------------------------------------------- the ceiling is not the answer
V1 = Protocol.V1


class TestReasoningGetsRoomToThink(ClientCase):
    """Protocol v1's rule, kept so its requests hash as they did.

    OpenRouter bills reasoning and output from one allowance, so an equal
    `max_tokens` is an unequal experiment: the thinking model answers from
    what is left, the other answers from all of it.

    Measured 2026-09-24 at a flat 16,000, glm-5.2 spent the entire budget
    reasoning on both clarkco draws and emitted no extractor either time. The
    scored result was 0/2. That is not a capability measurement, it is the
    ceiling showing up in the table under a model's name, and it is the exact
    shape of harness artifact this suite exists to catch.
    """

    def test_a_reasoning_model_gets_headroom_on_top(self):
        self.assertEqual(infer.ceiling_for("z-ai/glm-5.2", 16000, V1),
                         16000 + infer.REASONING_HEADROOM)

    def test_every_reasoning_model_gets_it(self):
        self.assertEqual(len(infer.V1_EFFORT), 5)
        for m in infer.V1_EFFORT:
            self.assertGreater(infer.ceiling_for(m, 8000, V1), 8000, m)

    def test_a_non_reasoning_model_is_untouched(self):
        """Including the ones that merely happen to be verbose. qwen3.5-flash
        averaged 9,817 output tokens on stjohns without a reasoning
        parameter, which is a property of the model and not a request for
        headroom; granting it here would hand one cheap model a larger budget
        than the others it is being compared against."""
        for m in ("qwen/qwen3.5-flash-02-23", "openai/gpt-oss-120b",
                  "qwen/qwen3-coder"):
            self.assertEqual(infer.ceiling_for(m, 16000, V1), 16000, m)

    def test_the_anthropic_path_cannot_move(self):
        """The property the response cache is worth $4.34 of."""
        for m in ("claude-opus-5", "claude-sonnet-5",
                  "claude-haiku-4-5-20251001"):
            for p in Protocol:
                self.assertEqual(infer.ceiling_for(m, 16000, p), 16000, m)

    def test_the_budget_is_checked_against_what_can_actually_be_spent(self):
        """Raise the ceiling in the request body alone and the guard
        authorizes a third of what the call may draw. The ceiling is resolved
        once, before anything reads it."""
        seen = []
        self.client.budget.check = lambda m, i, o: seen.append((m, i, o))
        self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        self.client.message("z-ai/glm-5.2", "S", "U", 16000, "synthesis",
                            protocol=V1)
        self.assertEqual(seen[-1][2], 16000 + infer.REASONING_HEADROOM)

    def test_the_wire_carries_the_raised_ceiling(self):
        comps = self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        self.client.message("z-ai/glm-5.2", "S", "U", 16000, "synthesis",
                            protocol=V1)
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
            infer.ceiling_for("z-ai/glm-5.2", 16000, V1))
        b = infer.Budget(projected + 1e-9)
        b.check("z-ai/glm-5.2", 9000,
                infer.ceiling_for("z-ai/glm-5.2", 16000, V1))
        b.ceiling = projected - 1e-4
        with self.assertRaises(infer.Refused):
            b.check("z-ai/glm-5.2", 9000,
                    infer.ceiling_for("z-ai/glm-5.2", 16000, V1))

    def test_thinking_to_the_old_ceiling_is_no_longer_truncation(self):
        """The 16,000-token reasoning burn that voided the first run reads as
        a complete answer once the answer budget is actually 16,000."""
        ceiling = infer.ceiling_for("z-ai/glm-5.2", 16000, V1)
        self.assertFalse(infer.truncated(
            "stop", infer.Usage(output_tokens=16000), ceiling))
        self.assertTrue(infer.truncated(
            "stop", infer.Usage(output_tokens=ceiling), ceiling))


# ------------------------------------------------------------ protocol v2
class TestProtocolV2(ClientCase):
    """The step 3 policy: one cap, the vendor's own reasoning default,
    sampling from the model card, host precision filtered, and every
    setting recorded on the row that paid for it."""

    def test_every_model_gets_the_same_cap(self):
        caps = {infer.output_cap(s.id) for s in models.measured()}
        self.assertEqual(caps, {models.OUTPUT_CAP})
        for s in models.measured():
            self.assertGreaterEqual(s.max_output, models.OUTPUT_CAP, s.id)

    def test_the_cap_is_the_whole_allowance_with_nothing_on_top(self):
        for s in models.measured():
            self.assertEqual(infer.ceiling_for(s.id, 64000), 64000, s.id)

    def test_haikus_thinking_budget_does_not_bind_before_the_cap(self):
        body = self.client.build("claude-haiku-4-5-20251001", "S", "U",
                                 64000, thinking=True)
        self.assertEqual(body["thinking"]["budget_tokens"],
                         64000 - infer.ANSWER_RESERVE)
        v1 = self.client.build("claude-haiku-4-5-20251001", "S", "U",
                               12000, thinking=True, protocol=V1)
        self.assertEqual(v1["thinking"]["budget_tokens"], 6000)

    def test_openrouter_only_fields_travel_in_extra_body(self):
        """The OpenAI SDK raises on a keyword it does not know."""
        comps = self.install(_FakeResponse(usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        self.client.message("z-ai/glm-5.2", "S", "U", 64000, "synthesis",
                            thinking=True)
        self.assertEqual(comps.extras[-1], ["provider", "reasoning"])
        self.assertEqual(comps.bodies[-1]["reasoning"], {"effort": "xhigh"})

    def test_the_row_records_what_was_asked_and_who_answered(self):
        self.install(_FakeResponse(host="Novita", usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=900, cost=0.01,
            completion_tokens_details={"reasoning_tokens": 700})))
        reply = self.client.message("z-ai/glm-5.2", "S", "U", 64000,
                                    "synthesis", thinking=True)
        row = self.rows()[-1]
        self.assertEqual(
            (row.protocol, row.max_tokens, row.reasoning, row.reasoning_level,
             row.temperature, row.top_p, row.host, row.reasoning_tokens,
             row.response_id),
            ("v2", 64000, "effort=xhigh", "max", 1.0, 0.95, "Novita", 700,
             "gen-1"))
        self.assertEqual((reply.host, reply.usage.reasoning_tokens,
                          reply.response_id), ("Novita", 700, "gen-1"))

    def test_v1_records_no_level_for_its_medium(self):
        """What v1's `medium` reached depended on the serving endpoint."""
        body = self.client.request("z-ai/glm-5.2", "S", "U", 16000,
                                   thinking=True, protocol=V1)
        sent = infer.settings_sent(body, V1)
        self.assertEqual((sent["reasoning"], sent["reasoning_level"]),
                         ("effort=medium", None))

    def test_a_replay_keeps_the_host(self):
        self.install(_FakeResponse(host="Novita", usage=_FakeUsage(
            prompt_tokens=10, completion_tokens=10, cost=0.01)))
        args = ("z-ai/glm-5.2", "S", "U", 64000, "synthesis")
        self.client.message(*args)
        again = self.client.message(*args)
        self.assertEqual((again.host, again.response_id), ("Novita", "gen-1"))

    def test_the_two_protocols_are_different_requests(self):
        """So a v2 draw can never be answered from a v1 cache entry."""
        c = self.client
        for m in ("z-ai/glm-5.2", "openai/gpt-oss-120b",
                  "claude-haiku-4-5-20251001"):
            a = c.request(m, "S", "U", 16000, thinking=True, protocol=V1)
            b = c.request(m, "S", "U", infer.output_cap(m), thinking=True)
            self.assertNotEqual(c._key_for(a), c._key_for(b), m)

    def test_claude_thinking_records_the_temperature_the_api_fixes(self):
        body = self.client.build("claude-opus-5", "S", "U", 64000,
                                 thinking=True)
        self.assertNotIn("temperature", body)
        self.assertEqual(infer.settings_sent(body, Protocol.V2)["temperature"],
                         1.0)

    def test_effort_is_refused_for_anthropic_and_under_v1(self):
        with self.assertRaises(infer.Refused):
            self.client.request("claude-opus-5", "S", "U", 64000,
                                thinking=True, effort="low")
        with self.assertRaises(infer.Refused):
            self.client.request("z-ai/glm-5.3-flash", "S", "U", 16000,
                                thinking=True, protocol=V1, effort="low")


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
                        and r.get("model") in models.REGISTRY):
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
                self.assertGreater(infer.price(model)[1], listed)
        self.assertIn("reconciled", infer.OPENROUTER_PRICES_AS_OF)


if __name__ == "__main__":
    unittest.main()
