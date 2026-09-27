# -*- coding: utf-8 -*-
"""Streaming, timeouts and the three-way error split in `permits/infer.py`.

Finding F5 of docs/evidence/2026-09-26-model-comparison-fairness-audit.md:
a single 900 s float bounded each socket read rather than the call, one
OpenRouter request stayed open for 65,161 s, and a budget refusal, a revoked
key, a host error and a timeout were all one outcome that stopped the cell
and dropped the draw from the denominator. Each test here pins one part of
the policy that replaced it.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import anthropic                                             # noqa: E402
import httpx2                                                # noqa: E402
import openai                                                # noqa: E402

import model_stats                                           # noqa: E402
from permits import infer                                    # noqa: E402
from permits.cells import DrawRecord, Outcome                # noqa: E402
from permits.stats import failure_mode                       # noqa: E402
from tests.test_infer import (_Err, _Event, _FakeMessage,    # noqa: E402
                              _FakeSDK, _FakeStream)
from tests.test_providers import (_FakeChoice, _FakeOAI,     # noqa: E402
                                  _FakeResponse, _FakeUsage)

OPUS = "claude-opus-5"
CODER = "qwen/qwen3-coder"
REQUEST = httpx2.Request("POST", "https://example.invalid/v1")


def _client(*results):
    c = infer.Client(tempfile.mkdtemp(), 10.0, api_key="a",
                     openrouter_key="b")
    c._sdk = _FakeSDK(*results)
    return c


def _ok():
    return _FakeMessage("ok", input_tokens=10, output_tokens=1)


class TestWhatARetryCanFix(unittest.TestCase):

    def test_rejections_that_will_repeat_are_fatal(self):
        for status in (400, 401, 402, 403, 404, 413, 422):
            with self.subTest(status=status):
                self.assertFalse(infer.is_transient(_Err("no", status)))

    def test_host_and_rate_failures_are_transient(self):
        for status in (408, 409, 429, 500, 502, 503, 529):
            with self.subTest(status=status):
                self.assertTrue(infer.is_transient(_Err("busy", status)))

    def test_an_error_inside_a_200_stream_is_transient(self):
        """Anthropic reports an in-stream `overloaded_error` with the
        stream's own status, 200; the OpenAI SDK raises one with none."""
        self.assertTrue(infer.is_transient(_Err("overloaded", 200)))
        self.assertTrue(infer.is_transient(
            openai.APIError("upstream died", request=REQUEST, body=None)))

    def test_transport_failures_are_transient(self):
        self.assertTrue(infer.is_transient(httpx2.ReadTimeout("slow")))
        self.assertTrue(infer.is_transient(
            anthropic.APIConnectionError(request=REQUEST)))
        self.assertTrue(infer.is_transient(
            openai.APITimeoutError(request=REQUEST)))

    def test_callers_that_catch_api_error_still_catch_both(self):
        self.assertTrue(issubclass(infer.FatalError, infer.ApiError))
        self.assertTrue(issubclass(infer.TransientError, infer.ApiError))
        self.assertFalse(issubclass(infer.Refused, infer.ApiError))


class TestTheSplitInTheClient(unittest.TestCase):

    def test_a_transient_failure_is_retried_once_under_the_same_draw(self):
        c = _client(_Err("overloaded", 529), _ok())
        reply = c.message(OPUS, "s", "u", 100, "synthesis", draw=3)
        self.assertEqual(reply.text, "ok")
        rows = c.ledger.rows()
        self.assertEqual([r.ok for r in rows], [False, True])
        self.assertEqual({r.draw for r in rows}, {3})
        self.assertEqual(c._sdk.messages.calls, 2)

    def test_two_transient_failures_are_an_infra_error(self):
        c = _client(_Err("overloaded", 529))
        with self.assertRaises(infer.TransientError) as ctx:
            c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertIn("after 2 attempts", str(ctx.exception))
        self.assertEqual(len(c.ledger.rows()), 2)
        self.assertEqual(c._sdk.messages.calls, 2)

    def test_a_rejection_is_not_retried(self):
        """Out of credit is out of credit on the second try too, and every
        later draw would spend a request finding that out."""
        c = _client(_Err("insufficient credits", 402), _ok())
        with self.assertRaises(infer.FatalError):
            c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertEqual(c._sdk.messages.calls, 1)
        self.assertEqual(len(c.ledger.rows()), 1)

    def test_a_failure_before_any_token_is_not_charged(self):
        c = _client(_Err("overloaded", 529))
        with self.assertRaises(infer.TransientError):
            c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertEqual(c.budget.spent, 0.0)
        self.assertTrue(all(r.ttft_s is None for r in c.ledger.rows()))

    def test_a_failure_after_tokens_is_charged_the_worst_case(self):
        """The host may bill for what it generated before the connection
        died, and nothing reports how much. The ledger row keeps `usd` at 0
        and marks the row with `ttft_s`; the budget, which is a guarantee,
        counts the worst case."""
        cut = _FakeStream(_ok(), fail=httpx2.ReadTimeout("gap"))
        c = _client(cut)
        with self.assertRaises(infer.TransientError):
            c.message(OPUS, "s", "u", 100, "synthesis")
        rows = c.ledger.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.ttft_s is not None and r.usd == 0.0
                            for r in rows))
        worst = infer.estimate(OPUS, infer.tokens("s") + infer.tokens("u"),
                               100)
        self.assertAlmostEqual(c.budget.spent, 2 * worst)


class TestTimeouts(unittest.TestCase):

    def test_the_read_timeout_is_a_gap_not_a_total(self):
        c = infer.Client(tempfile.mkdtemp(), 1.0, api_key="a",
                         openrouter_key="b")
        for sdk in (c.sdk(), c.oai()):
            with self.subTest(sdk=type(sdk).__name__):
                self.assertIsInstance(sdk.timeout, httpx2.Timeout)
                self.assertEqual(sdk.timeout.read, 120.0)
                self.assertEqual(sdk.timeout.connect, 10.0)

    def test_the_wall_limit_binds_on_a_stall_not_on_the_slowest_good_call(
            self):
        """The slowest successful call in the ledger generated 41,680 tokens
        in 2,802 s; the stalled one took 65,161 s for 5,434."""
        limit = infer.wall_limit(infer.output_cap("deepseek/deepseek-v4-flash"))
        self.assertGreater(limit, 2802)
        self.assertLess(limit, 65161)

    def test_hitting_the_wall_limit_is_an_infra_error(self):
        c = _client(_ok())
        with mock.patch.object(infer, "wall_limit", lambda n: -1.0):
            with self.assertRaises(infer.TransientError) as ctx:
                c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertIn("wall-clock", str(ctx.exception))

    def test_a_success_records_time_to_first_token(self):
        c = _client(_ok())
        c.message(OPUS, "s", "u", 100, "synthesis")
        row = c.ledger.rows()[0]
        self.assertIsNotNone(row.ttft_s)
        self.assertLessEqual(row.ttft_s, row.seconds)

    def test_a_stream_with_no_token_has_no_time_to_first_token(self):
        c = _client(_FakeStream(_ok(), events=("message_start",)))
        c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertIsNone(c.ledger.rows()[0].ttft_s)


class TestResponseIds(unittest.TestCase):
    """Every row carries the provider's id for the response, so it can be
    reconciled with the provider's own record of the call later - a failed
    call most of all, since the ledger cannot say what that one cost."""

    def test_a_success_records_the_message_id(self):
        c = _client(_ok())
        reply = c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertEqual((c.ledger.rows()[0].response_id, reply.response_id),
                         ("msg_1", "msg_1"))

    def test_a_failure_after_the_message_started_records_its_id(self):
        start = _Event("message_start", message=_FakeMessage("x"))
        cut = _FakeStream(_ok(), events=(start, "content_block_delta"),
                          fail=httpx2.ReadTimeout("gap"))
        c = _client(cut)
        with self.assertRaises(infer.TransientError):
            c.message(OPUS, "s", "u", 100, "synthesis")
        self.assertEqual([r.response_id for r in c.ledger.rows()],
                         ["msg_1", "msg_1"])

    def test_an_openrouter_failure_records_the_generation_id(self):
        c = _client(_ok())
        c._oai = _FakeOAI(_FakeResponse(finish_reason="error"))
        with self.assertRaises(infer.TransientError):
            c.message("z-ai/glm-5.2", "s", "u", 100, "synthesis")
        self.assertEqual([r.response_id for r in c.ledger.rows()],
                         ["gen-1", "gen-1"])


class TestOpenRouterStreams(unittest.TestCase):

    def client(self, result):
        c = _client(_ok())
        c._oai = _FakeOAI(result)
        return c, c._oai.chat.completions

    def test_stream_is_an_argument_and_never_part_of_the_body(self):
        """The cache key is the body's hash. `stream` inside it is the bug
        that orphaned paid responses before."""
        c, comp = self.client(_FakeResponse("ok"))
        c.message(CODER, "s", "u", 100, "synthesis")
        self.assertEqual(comp.bodies[0], c.build_chat(
            CODER, "s", "u", infer.ceiling_for(CODER, 100)))
        self.assertEqual(comp.transport[0],
                         {"stream": True,
                          "stream_options": {"include_usage": True}})

    def test_the_text_is_the_deltas_in_order(self):
        c, _ = self.client(_FakeResponse(choices=[
            _FakeChoice("def ", None), _FakeChoice("extract(", "stop")]))
        reply = c.message(CODER, "s", "u", 100, "synthesis")
        self.assertEqual(reply.text, "def extract(")
        self.assertEqual(reply.stop_reason, "end_turn")

    def test_the_reported_cost_arrives_in_the_last_chunk(self):
        c, _ = self.client(_FakeResponse("ok", usage=_FakeUsage(
            prompt_tokens=100, completion_tokens=10, cost=0.0123)))
        self.assertEqual(c.message(CODER, "s", "u", 100, "synthesis").usd,
                         0.0123)

    def test_an_error_finish_is_an_infra_error(self):
        c, _ = self.client(_FakeResponse(choices=[_FakeChoice("", "error")]))
        with self.assertRaises(infer.TransientError):
            c.message(CODER, "s", "u", 100, "synthesis")

    def test_a_stream_without_its_usage_block_is_an_infra_error(self):
        """A zero-token row would price a paid call at nothing."""
        resp = _FakeResponse("ok")
        resp.usage = None
        c, _ = self.client(resp)
        with self.assertRaises(infer.TransientError):
            c.message(CODER, "s", "u", 100, "synthesis")


class TestInfraErrorsAreReportedBesideTheRate(unittest.TestCase):

    def draw(self, i, outcome, **kw):
        return DrawRecord(i, CODER, "clarkco", outcome, **kw)

    def test_an_infra_error_is_not_scored_and_costs_no_figure(self):
        d = self.draw(0, Outcome.INFRA_ERROR, why="ReadTimeout")
        self.assertFalse(d.scored())
        self.assertEqual(d.spend(), 0.0)
        self.assertEqual(failure_mode(d), "infra_error")

    def test_the_cell_rate_excludes_it_and_the_infra_rate_counts_it(self):
        v = {"cells": {"clarkco|" + CODER: {
            "target": "clarkco", "model": CODER,
            "detail": [
                self.draw(0, Outcome.PERFECT, usd=0.01, output_tokens=5,
                          bytes=10, truncated=False).to_dict(),
                self.draw(1, Outcome.RAISED, usd=0.01, output_tokens=5,
                          bytes=10, truncated=False).to_dict(),
                self.draw(2, Outcome.INFRA_ERROR, why="x").to_dict(),
            ]}}}
        agg = model_stats.aggregate(model_stats.rows_from_variance(v))
        e = agg["clarkco|" + CODER]
        self.assertEqual((e["draws_scored"], e["perfect"]), (2, 1))
        self.assertEqual(e["success_rate"], 0.5)
        self.assertEqual(e["draws_infra_error"], 1)
        self.assertAlmostEqual(e["infra_error_rate"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
