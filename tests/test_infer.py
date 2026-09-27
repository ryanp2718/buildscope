# -*- coding: utf-8 -*-
"""The inference path: pricing, the budget guard, the cache, and the stripper.

Two of these exist because something here already produced a wrong answer
silently, which is `docs/design/testing.md`'s bar for writing a test at all:

- **The stripper deleted the only marker that identifies an Accela data row.**
  `class` was not on the keep-list, so `class="ACA_TabRow_Odd"` vanished from
  all 42 rows while the rows themselves stayed. The page still looked whole.
  DESIGN.md section 6 lever 4 claims an order-of-magnitude token reduction
  "against identical extraction quality"; the reduction was measured and the
  quality was not.
- **The synthesis window twice landed on a part of the page with no permit
  rows on it.** First by starting at the first `<table` (Clark's grid begins
  at character 65,386, the window ended at 24,973), then by maximizing bare
  `<tr` count, which prefers layout tables because they have more rows. Either
  would have scored synthesis at zero and the number would have described the
  harness.

The rest exist because they compute dollars. `cost()` is the only thing
standing between a `usage` block and a figure that goes in an evidence report.
"""
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import tempfile

import anthropic

from permits import infer, strip                             # noqa: E402

PAGES = os.path.join(ROOT, "data", "step1", "pages")
CLARK = os.path.join(PAGES, "acc2_clarkco_03022026.html")
SJ = os.path.join(PAGES, "sj_stjohns_01012026_01072026.html")


def page(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


class TestPricing(unittest.TestCase):

    def test_prices_match_the_design_document(self):
        """The rates are quoted from DESIGN.md section 6. If they are edited
        here without editing there, a cost figure and its stated source
        disagree - which is the re-quoting failure in its cheapest form."""
        self.assertEqual(infer.price("claude-opus-5"), (5.0, 25.0))
        self.assertEqual(infer.price("claude-sonnet-5"), (2.0, 10.0))
        self.assertEqual(infer.price("claude-haiku-4-5-20251001"), (1.0, 5.0))
        self.assertIn("2026-06-24", infer.PRICES_AS_OF)

    def test_cost_arithmetic(self):
        usd = infer.cost("claude-opus-5", infer.Usage(input_tokens=1000000))
        self.assertAlmostEqual(usd, 5.0, places=6)
        usd = infer.cost("claude-opus-5", infer.Usage(output_tokens=1000000))
        self.assertAlmostEqual(usd, 25.0, places=6)

    def test_cache_read_bills_at_a_tenth(self):
        full = infer.cost("claude-opus-5", infer.Usage(input_tokens=100000))
        cached = infer.cost("claude-opus-5",
                            infer.Usage(cache_read_input_tokens=100000))
        self.assertAlmostEqual(cached, full * 0.1, places=8)

    def test_cache_write_bills_at_a_premium(self):
        full = infer.cost("claude-opus-5", infer.Usage(input_tokens=100000))
        write = infer.cost("claude-opus-5",
                           infer.Usage(cache_creation_input_tokens=100000))
        self.assertAlmostEqual(write, full * 1.25, places=8)

    def test_missing_cache_fields_are_not_billed_as_input(self):
        """A deployment may omit the cache fields. Treating a missing field as
        a full-price input token would inflate every figure quietly."""
        self.assertEqual(
            infer.Usage.from_dict({"input_tokens": 1000}),
            infer.Usage.from_dict({"input_tokens": 1000,
                                   "cache_read_input_tokens": None,
                                   "cache_creation_input_tokens": None}))

    def test_an_unpriced_model_is_refused_not_guessed(self):
        with self.assertRaises(infer.Refused):
            infer.cost("some-future-model", infer.Usage(input_tokens=10))


class TestBudget(unittest.TestCase):

    def test_ceiling_is_tested_against_the_worst_case(self):
        """`max_tokens` is what the request authorizes the model to bill, so
        that is what the guard must test. A guard that admits calls on the
        basis of what usually happens is not a guard."""
        b = infer.Budget(0.10)
        b.check("claude-opus-5", 1000, 1000)          # $0.03, fine
        with self.assertRaises(infer.Refused):
            b.check("claude-opus-5", 1000, 100000)    # $2.51, not fine

    def test_spend_accumulates_across_calls(self):
        b = infer.Budget(0.10)
        b.record(0.09)
        with self.assertRaises(infer.Refused):
            b.check("claude-opus-5", 1000, 1000)

    def test_refusal_names_both_numbers(self):
        b = infer.Budget(0.01)
        try:
            b.check("claude-opus-5", 100000, 100000)
        except infer.Refused as e:
            self.assertIn("0.01", str(e))
        else:
            self.fail("no refusal")


class TestRequestCache(unittest.TestCase):
    """A model call is not reproducible, so the response is the artifact. The
    cache key has to change when the request changes and not otherwise."""

    def client(self):
        return infer.Client(ROOT, 0.0, api_key="unused", dry_run=True)

    def test_key_is_stable_across_dict_ordering(self):
        c = self.client()
        a = c.build("claude-opus-5", "sys", "user", 100)
        b = dict(reversed(list(a.items())))
        self.assertEqual(c._key_for(a), c._key_for(b))

    def test_model_change_is_a_cache_miss(self):
        c = self.client()
        a = c.build("claude-opus-5", "sys", "user", 100)
        b = c.build("claude-sonnet-5", "sys", "user", 100)
        self.assertNotEqual(c._key_for(a), c._key_for(b))

    def test_prompt_change_is_a_cache_miss(self):
        c = self.client()
        a = c.build("claude-opus-5", "sys", "user", 100)
        b = c.build("claude-opus-5", "sys", "user!", 100)
        self.assertNotEqual(c._key_for(a), c._key_for(b))

    def test_thinking_change_is_a_cache_miss(self):
        c = self.client()
        a = c.build("claude-opus-5", "sys", "u", 100, thinking=False)
        b = c.build("claude-opus-5", "sys", "u", 100, thinking=True)
        self.assertNotEqual(c._key_for(a), c._key_for(b))

    def test_transport_flags_are_not_part_of_the_key(self):
        """The regression. `stream` is set after the lookup and before the
        store, so every streamed response was written under a hash nothing
        would ever ask for: the cache filled up and never hit, silently, and
        three paid-for responses had to be re-keyed by hand. The same prompt
        streamed and unstreamed is the same question."""
        c = self.client()
        plain = c.build("claude-opus-5", "s", "u", 16000)
        streamed = dict(plain)
        streamed["stream"] = True
        self.assertNotEqual(c._key_for(plain), c._key_for(streamed),
                            "sanity: the two bodies really do differ")
        import inspect
        src = inspect.getsource(c.message)
        # The original bug was an ordering problem: `body["stream"] = True`
        # ran between the lookup and the store. Streaming is now a choice of
        # SDK method, so the body is never mutated after it is hashed and the
        # ordering cannot regress. Assert the shape is gone, not the order.
        self.assertNotIn('body["stream"]', src,
                         "a transport flag must not be written into the "
                         "request body; pick the SDK method instead")
        self.assertIn("self._store(key,", src,
                      "store must reuse the lookup key, not re-hash the "
                      "mutated body")

    def test_a_small_call_streams_too(self):
        """Streaming used to start above 8,192 tokens, because a longer
        unstreamed call can outlive the server's request timeout. Every call
        streams now, so the read timeout is a gap between chunks and an SDK
        retry never re-sends a generation. The fake has no `create`."""
        c = infer.Client(tempfile.mkdtemp(), 10.0, api_key="k")
        c._sdk = _FakeSDK(_FakeMessage("ok", output_tokens=1))
        self.assertFalse(hasattr(c._sdk.messages, "create"))
        self.assertEqual(
            c.message("claude-opus-5", "s", "u", 100, "synthesis").text, "ok")

    def test_system_carries_a_cache_breakpoint(self):
        """Section 6 lever 3. Without the breakpoint the stable prefix bills
        at full price on every resend and the lever is silently off."""
        c = self.client()
        body = c.build("claude-opus-5", "prefix", "page", 100)
        self.assertEqual(body["system"][0]["cache_control"],
                         {"type": "ephemeral"})

    def test_thinking_shape_follows_the_model(self):
        """The regression that killed the first run: Haiku 4.5 answered
        `adaptive thinking is not supported on this model` with a 400, and
        Opus 5 rejects `budget_tokens` the same way. There is no form that
        works on both, so it is a property of the model."""
        c = self.client()
        adaptive = c.build("claude-opus-5", "s", "u", 8000, thinking=True)
        self.assertEqual(adaptive["thinking"], {"type": "adaptive"})

        budgeted = c.build("claude-haiku-4-5-20251001", "s", "u", 8000,
                           thinking=True)
        self.assertEqual(budgeted["thinking"]["type"], "enabled")
        self.assertGreaterEqual(budgeted["thinking"]["budget_tokens"], 1024)
        self.assertLess(budgeted["thinking"]["budget_tokens"], 8000,
                        "the thinking budget must leave room for the answer")

    def test_thinking_off_sends_no_thinking_block(self):
        c = self.client()
        body = c.build("claude-haiku-4-5-20251001", "s", "u", 100)
        self.assertNotIn("thinking", body)


class _FakeUsage(object):
    def __init__(self, **kw):
        self.kw = {"input_tokens": 0, "output_tokens": 0,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0}
        self.kw.update(kw)

    def model_dump(self, mode=None):
        return dict(self.kw)


class _FakeMessage(object):
    def __init__(self, text, stop_reason="end_turn", **usage):
        self.model = "claude-opus-5"
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(**usage)
        self.content = [anthropic.types.TextBlock(type="text", text=text)]


class _Event(object):
    def __init__(self, type_):
        self.type = type_


class _FakeStream(object):
    """What `messages.stream()` returns: a context manager that yields
    events and then hands over the final message. `fail` is raised after the
    events, which is a connection dying mid-generation."""

    def __init__(self, message, events=("content_block_delta",), fail=None):
        self.message = message
        self.events = [_Event(t) for t in events]
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for e in self.events:
            yield e
        if self.fail is not None:
            raise self.fail

    def get_final_message(self):
        return self.message


class _FakeMessages(object):
    """Stands in for `client.messages`, one result per attempt; the last
    result repeats. An exception is raised as the SDK raises a rejected
    request, before any event. There is no `create`: every call streams."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def stream(self, **body):
        r = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, _FakeStream) else _FakeStream(r)


class _FakeSDK(object):
    def __init__(self, *results):
        self.messages = _FakeMessages(*results)


class _Err(anthropic.APIError):
    """A vendor error with a status code, built without a live response."""

    def __init__(self, message, status):
        self.status_code = status
        Exception.__init__(self, message)


class TestFailedCallsReachTheLedger(unittest.TestCase):
    """The hole found on 2026-09-22.

    The hand-rolled client raised on `HTTPError` three lines before it reached
    `ledger.write`, so a failed call left no trace anywhere. Every rate ever
    computed from this ledger had "calls that succeeded" as its denominator
    while being described as "calls". The ledger is the cost record of
    account; a denominator it cannot express is a measurement defect, not a
    logging preference.
    """

    def client(self, *results):
        c = infer.Client(tempfile.mkdtemp(), 10.0, api_key="k")
        c._sdk = _FakeSDK(*results)
        return c

    def test_a_failed_call_is_a_row(self):
        c = self.client(_Err("invalid x-api-key", 401))
        with self.assertRaises(infer.ApiError):
            c.message("claude-opus-5", "s", "u", 100, "synthesis")
        rows = c.ledger.rows()
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0].ok, False)
        self.assertEqual(rows[0].status_code, 401)
        self.assertEqual(rows[0].error_type, "_Err")

    def test_a_failed_call_bills_nothing(self):
        """A rejected request is not billed, and a row that claimed
        otherwise would corrupt the one number this file exists to protect."""
        c = self.client(_Err("rate limited", 429))
        with self.assertRaises(infer.ApiError):
            c.message("claude-opus-5", "s", "u", 100, "synthesis")
        self.assertEqual(c.ledger.rows()[0].usd, 0.0)
        self.assertEqual(c.budget.spent, 0.0)

    def test_a_refusal_is_not_a_row(self):
        """`Refused` means nothing was sent. It must not appear in a ledger
        whose rows are calls that reached the API - a dry run would otherwise
        manufacture a failure rate out of calls that never happened."""
        c = infer.Client(tempfile.mkdtemp(), 10.0, api_key="k", dry_run=True)
        with self.assertRaises(infer.Refused):
            c.message("claude-opus-5", "s", "u", 100, "synthesis")
        self.assertEqual(c.ledger.rows(), [])

    def test_old_rows_without_the_field_read_as_successes(self):
        """Backward compatibility with the 67 rows bought before the field
        existed. They are successes - the old client could not write a row
        for anything else."""
        c = self.client(_FakeMessage("ok", input_tokens=10, output_tokens=5))
        # The shape of the first rows on disk: no `ok`, `provider`, `draw` or
        # `usd_reported`.
        with io.open(c.ledger.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": "2026-09-21T15:42:43Z", "call_class": "synthesis",
                "tag": "clarkco", "model": "claude-opus-5", "usd": 1.0,
                "seconds": 60.0, "stop_reason": "end_turn",
                "input_tokens": 10, "output_tokens": 5,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}) + "\n")
        c.message("claude-opus-5", "s", "u", 100, "synthesis")
        rows = c.ledger.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.ok for r in rows))
        self.assertEqual(rows[0].provider, "anthropic")
        self.assertEqual(rows[0].draw, 0)

    def test_a_success_is_marked_and_priced(self):
        c = self.client(_FakeMessage("hello", input_tokens=1000,
                                     output_tokens=200))
        reply = c.message("claude-opus-5", "s", "u", 100, "synthesis")
        self.assertEqual(reply.text, "hello")
        row = c.ledger.rows()[0]
        self.assertIs(row.ok, True)
        self.assertGreater(row.usd, 0)
        self.assertEqual(row.input_tokens, 1000)

    def test_truncation_still_surfaces(self):
        """Kept from the deleted stream tests: a `max_tokens` stop is a
        silently short answer, and the caller has to be told."""
        c = self.client(_FakeMessage("cut", stop_reason="max_tokens",
                                     output_tokens=100))
        reply = c.message("claude-opus-5", "s", "u", 100, "synthesis")
        self.assertTrue(reply.truncated)


class TestTheLedgerFormatIsUnchanged(unittest.TestCase):
    """`LedgerRow` is a typed view of a file that predates it. Every row on
    disk has to read, and every row in the current shape has to write back
    byte for byte, or the typed layer has quietly changed the record of
    account."""

    def test_every_row_on_disk_reads_and_round_trips(self):
        path = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
        if not os.path.exists(path):
            self.skipTest("no ledger on this checkout")
        with io.open(path, encoding="utf-8") as fh:
            lines = [line.strip() for line in fh if line.strip()]
        current = 0
        for line in lines:
            raw = json.loads(line)
            row = infer.LedgerRow.from_dict(raw)
            if {"ok", "provider", "draw"} <= set(raw):
                current += 1
                self.assertEqual(json.dumps(row.to_dict(), sort_keys=True),
                                 json.dumps(raw, sort_keys=True))
        self.assertGreater(current, 150)

    def test_a_misspelled_field_raises(self):
        """What `.get("field", 0) or 0` turned into a silent zero."""
        with self.assertRaises(ValueError):
            infer.LedgerRow.from_dict({
                "at": "t", "call_class": "synthesis", "tag": "", "draw": 0,
                "model": "claude-opus-5", "ok": True, "usd": 0.0,
                "seconds": 0.0, "stop_reason": None, "output_tokns": 5})


class TestTransportIsTheVendors(unittest.TestCase):
    """What the SDK swap bought, asserted so it cannot be lost silently."""

    def test_retries_are_configured_and_not_left_at_the_default(self):
        """The old client had none. A 429 anywhere in a 55-draw run would
        have ended it."""
        self.assertGreaterEqual(infer.MAX_RETRIES, 3)
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="k")
        self.assertEqual(c.sdk().max_retries, infer.MAX_RETRIES)

    def test_the_client_is_lazy_so_a_dry_run_needs_no_key(self):
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="", dry_run=True)
        self.assertIsNone(c._sdk)
        with self.assertRaises(infer.Refused):
            c.message("claude-opus-5", "s", "u", 100, "synthesis")


class TestNothingIsSentWithoutIntent(unittest.TestCase):

    def test_dry_run_refuses_before_the_socket(self):
        c = infer.Client(ROOT, 100.0, api_key="unused", dry_run=True)
        with self.assertRaises(infer.Refused):
            c.message("claude-opus-5", "s", "u", 100, "synthesis")

    def test_no_key_refuses_rather_than_erroring_late(self):
        c = infer.Client(ROOT, 100.0, api_key="", dry_run=False)
        c.key = ""
        with self.assertRaises(infer.Refused):
            c.message("claude-opus-5", "s", "u", 100, "synthesis")

    def test_refused_is_not_an_api_error(self):
        """`Refused` means no money was spent. Collapsing it into the
        transport error type would lose exactly that distinction."""
        self.assertFalse(issubclass(infer.Refused, infer.ApiError))


class TestStripper(unittest.TestCase):

    def test_class_is_kept_by_default(self):
        self.assertIn("class", strip.KEEP_ATTR)

    def test_legacy_keep_list_is_frozen(self):
        """The published token figures were measured with this list. Changing
        it silently re-derives a published number under new inputs."""
        self.assertEqual(strip.LEGACY_KEEP,
                         ("id", "name", "href", "value", "type"))

    @unittest.skipUnless(os.path.exists(CLARK), "Clark page not in the store")
    def test_accela_row_markers_survive_stripping(self):
        """The regression. 42 `ACA_TabRow` markers went to zero and the rows
        stayed, so the page looked complete with its only row signal gone."""
        raw = page(CLARK)
        self.assertGreater(raw.count("ACA_TabRow"), 0)
        kept = strip.levels(raw)["attrs-stripped"]
        self.assertGreater(kept.count("ACA_TabRow"), 0)
        old = strip.levels(raw, strip.LEGACY_KEEP)["attrs-stripped"]
        self.assertEqual(old.count("ACA_TabRow"), 0)

    @unittest.skipUnless(os.path.exists(CLARK), "Clark page not in the store")
    def test_keeping_class_stays_an_order_of_magnitude_cheaper(self):
        """Lever 4's reduction has to survive the fix, or the fix costs more
        than the defect did."""
        raw = page(CLARK)
        kept = strip.levels(raw)["attrs-stripped"]
        self.assertLess(len(kept), len(raw) / 5.0)

    @unittest.skipUnless(os.path.exists(CLARK), "Clark page not in the store")
    def test_stripping_removes_viewstate_payload(self):
        raw = page(CLARK)
        self.assertGreater(strip.viewstate_bytes(raw), 10000)
        kept = strip.levels(raw)["attrs-stripped"]
        self.assertLess(strip.viewstate_bytes(kept),
                        strip.viewstate_bytes(raw))
        self.assertIn("chars elided", kept)


class TestSynthesisWindow(unittest.TestCase):
    """The window must land on permit rows. Twice it did not, and a synthesis
    score of zero would have been blamed on the model."""

    def setUp(self):
        import conformance
        self.C = conformance

    @unittest.skipUnless(os.path.exists(CLARK) and os.path.exists(SJ),
                         "target pages not in the store")
    def test_window_contains_data_rows_on_both_platforms(self):
        for key, marker in (("clarkco", "lblPermitNumber"),
                            ("stjohns", "PopPermit")):
            t = self.C.TARGETS[key]
            pages = self.C.corpus(t)
            self.assertTrue(pages, "no corpus for %s" % key)
            win, frac, at = self.C.window(self.C.read(pages[0][1]), 24000)
            with self.subTest(target=key):
                self.assertGreater(
                    win.count(marker), 0,
                    "%s: the synthesis window (char %d, %.0f%% of the page) "
                    "contains no permit rows - synthesis would be scored on a "
                    "page with no data on it" % (key, at, 100 * frac))

    def test_data_rows_ignores_layout_tables(self):
        """A layout row has one or two cells; a grid row has many."""
        layout = "<table><tr><td>a</td><td>b</td></tr></table>" * 20
        grid = ("<table><tr>" + "<td>x</td>" * 8 + "</tr></table>") * 3
        self.assertEqual(len(self.C.data_rows(layout)), 0)
        self.assertEqual(len(self.C.data_rows(grid)), 3)

    def test_a_second_model_tier_does_not_overwrite_the_first(self):
        """The cheap tier is run first and the expensive one only if needed.
        If both wrote to the same path the second run would destroy the
        artifact the comparison is between."""
        import inspect
        src = inspect.getsource(self.C.run_target)
        self.assertIn("%s_%s_extract.py", src)
        self.assertIn("tier", src)

    def test_extractor_runs_on_the_representation_it_was_shown(self):
        """Synthesis sees a stripped page, so it is run on stripped pages. On
        raw HTML it would meet attribute order and whitespace it was told had
        been normalized, and the failure would be the harness's."""
        import inspect
        src = inspect.getsource(self.C.run_target)
        self.assertIn("stripped_corpus", src)


class TestGeneratedCodeIsAudited(unittest.TestCase):
    """Model-written code gets executed here. The audit is a guard, not a
    sandbox - it refuses and reports rather than silently allowing something
    the measurement would then attribute to extraction quality."""

    def setUp(self):
        import conformance
        self.C = conformance

    def test_clean_module_passes(self):
        problems, imports = self.C.audit(
            "import re\ndef extract(html):\n    return []\n")
        self.assertEqual(problems, [])
        self.assertEqual(imports, ["re"])

    def test_file_and_network_access_is_refused(self):
        for bad in ("import os\ndef extract(h):\n    return []\n",
                    "import socket\ndef extract(h):\n    return []\n",
                    "import urllib.request\ndef extract(h):\n    return []\n",
                    "def extract(h):\n    return open('x').read()\n"):
            with self.subTest(src=bad.splitlines()[0]):
                problems, _ = self.C.audit(bad)
                self.assertTrue(problems, "not refused: %r" % bad)

    def test_missing_entry_point_is_refused(self):
        problems, _ = self.C.audit("import re\ndef parse(h):\n    return []\n")
        self.assertIn("defines no top-level extract()", problems)

    def test_unparseable_source_is_refused_not_executed(self):
        problems, _ = self.C.audit("def extract(:\n")
        self.assertTrue(problems[0].startswith("does not parse"))


if __name__ == "__main__":
    unittest.main()
