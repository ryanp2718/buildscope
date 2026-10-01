# -*- coding: utf-8 -*-
"""Conversations with tools in `permits/infer.py`: `Client.converse`.

The agent in docs/evidence/2026-09-29-agentic-extractor-plan.md calls models
through the same client as every one-shot draw, so the budget, the ledger and
the response cache cover it. What is new, and pinned here: a turn's tool calls
and the assistant message come back in the provider's own shape and go out
again unchanged (thinking signatures, reasoning details), a streamed tool call
is assembled from its fragments, and a response bought in one run can never
be replayed into another.
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import anthropic                                             # noqa: E402

from permits import infer                                    # noqa: E402
from tests.test_infer import _FakeSDK, _FakeUsage            # noqa: E402
from tests.test_providers import _FakeOAI                    # noqa: E402
from tests.test_providers import _FakeUsage as _ChatUsage    # noqa: E402

OPUS = "claude-opus-5"
CODER = "qwen/qwen3-coder"
TOOLS = [{"name": "check", "description": "Run the checks.",
          "parameters": {"type": "object",
                         "properties": {"code": {"type": "string"}},
                         "required": ["code"]}}]
FIRST = [{"role": "user", "content": "Write an extractor."}]


class _ToolMessage(object):
    """An Anthropic final message that thinks, then calls a tool."""

    def __init__(self, stop_reason="tool_use"):
        self.id = "msg_1"
        self.model = OPUS
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(input_tokens=100, output_tokens=20)
        self.content = [
            anthropic.types.ThinkingBlock(type="thinking", thinking="hmm",
                                          signature="sig-1"),
            anthropic.types.ToolUseBlock(type="tool_use", id="tu_1",
                                         name="check",
                                         input={"code": "def extract(h): "
                                                        "return []"}),
        ]


class _Stream(object):
    """A streamed chat completion made of explicit chunks."""

    def __init__(self, deltas, finish="tool_calls", usage=None):
        self.deltas = deltas
        self.finish = finish
        self.usage = usage or _ChatUsage(prompt_tokens=50,
                                         completion_tokens=10, cost=0.001)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for i, d in enumerate(self.deltas):
            last = i == len(self.deltas) - 1
            choice = NS(delta=d, finish_reason=self.finish if last else None)
            yield NS(id="gen-1", model=CODER, choices=[choice], usage=None,
                     provider="Host")
        yield NS(id="gen-1", model=CODER, choices=[], usage=self.usage,
                 provider="Host")


def _delta(content=None, tool_calls=None, reasoning_details=None):
    return NS(content=content, tool_calls=tool_calls,
              reasoning_details=reasoning_details)


def _tc(index, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


class _Sequence(object):
    """`chat.completions` returning one stream per call, recording bodies."""

    def __init__(self, *streams):
        self.streams = list(streams)
        self.bodies = []

    def create(self, **kw):
        kw.pop("stream", None)
        kw.pop("stream_options", None)
        kw.update(kw.pop("extra_body", None) or {})
        self.bodies.append(kw)
        return self.streams[len(self.bodies) - 1]


def _client():
    c = infer.Client(tempfile.mkdtemp(), 10.0, api_key="a",
                     openrouter_key="b")
    return c


def _chat_client(*streams):
    c = _client()
    c._oai = _FakeOAI(None)
    seq = _Sequence(*streams)
    c._oai.chat.completions = seq
    return c, seq


class TestAnthropicTurns(unittest.TestCase):

    def test_a_tool_call_comes_back_parsed(self):
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        turn = c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "dev-1")
        self.assertEqual(turn.completion.stop_reason, "tool_use")
        self.assertFalse(turn.completion.truncated)
        self.assertEqual(turn.tool_calls, (infer.ToolCall(
            "tu_1", "check", {"code": "def extract(h): return []"}),))

    def test_the_thinking_signature_goes_back_unchanged(self):
        """Anthropic rejects a tool-use continuation whose thinking block
        was altered or dropped."""
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        turn = c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "dev-1")
        msgs = [*FIRST, turn.message, {"role": "tool", "results": [
            {"id": "tu_1", "content": "rows: ok", "is_error": False}]}]
        body = c.build_conversation(OPUS, "s", msgs, TOOLS, 1000)
        blocks = body["messages"][1]["content"]
        self.assertEqual(blocks[0], {"type": "thinking", "thinking": "hmm",
                                     "signature": "sig-1"})
        self.assertEqual(blocks[1]["type"], "tool_use")

    def test_tool_results_are_one_user_turn_with_a_cache_breakpoint(self):
        c = _client()
        msgs = [*FIRST, 
            {"role": "assistant", "native": {"role": "assistant",
                                             "content": []}},
            {"role": "tool", "results": [
                {"id": "a", "content": "one"},
                {"id": "b", "content": "two", "is_error": True}]}]
        body = c.build_conversation(OPUS, "s", msgs, TOOLS, 1000)
        last = body["messages"][-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual([b["tool_use_id"] for b in last["content"]],
                         ["a", "b"])
        self.assertTrue(last["content"][1]["is_error"])
        self.assertEqual(last["content"][-1]["cache_control"],
                         {"type": "ephemeral"})
        self.assertNotIn("cache_control", last["content"][0])
        self.assertEqual(body["tools"][0]["input_schema"],
                         TOOLS[0]["parameters"])

    def test_each_turn_is_a_ledger_row_with_its_episode(self):
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "dev-1",
                   episode=3, tag="clarkco/agent/e03/t00")
        (row,) = c.ledger.rows()
        self.assertEqual((row.call_class, row.draw, row.tag, row.ok),
                         ("agent", 3, "clarkco/agent/e03/t00", True))


class TestReplayStaysInsideARun(unittest.TestCase):

    def test_the_same_turn_in_the_same_run_replays_free(self):
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        first = c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "eval-1")
        again = c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "eval-1")
        self.assertTrue(again.completion.cached)
        self.assertEqual(again.completion.usd, 0.0)
        # What it cost to buy is still known, so an episode's spend limit
        # stops a replay where the original stopped.
        self.assertGreater(again.purchase_usd, 0.0)
        # And so is its list-priced cost, which the limit is on: every input
        # token at the list input rate, whatever a cache or host discounted.
        self.assertGreater(first.list_usd, 0.0)
        self.assertEqual(again.list_usd, first.list_usd)
        self.assertEqual(first.list_usd,
                         infer.list_cost(OPUS, first.completion.usage))
        self.assertEqual(again.tool_calls[0].name, "check")
        self.assertEqual(c._sdk.messages.calls, 1)

    def test_another_run_or_episode_is_bought_again(self):
        """An exploratory run's responses must never stand in for an
        evaluation run's, and independent episodes of one task start from
        the same first request."""
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "dev-1")
        other_run = c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent",
                               "eval-1")
        other_episode = c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent",
                                   "dev-1", episode=1)
        self.assertFalse(other_run.completion.cached)
        self.assertFalse(other_episode.completion.cached)
        self.assertEqual(c._sdk.messages.calls, 3)

    def test_another_arm_is_bought_again(self):
        """The scripted loop's first turn and a one-shot draw are the same
        request; each arm's episodes are its own samples."""
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        c.converse(OPUS, "s", FIRST, [], 1000, "scripted", "dev-1")
        oneshot = c.converse(OPUS, "s", FIRST, [], 1000, "oneshot", "dev-1")
        self.assertFalse(oneshot.completion.cached)
        self.assertEqual(c._sdk.messages.calls, 2)

    def test_a_run_id_is_required(self):
        c = _client()
        c._sdk = _FakeSDK(_ToolMessage())
        with self.assertRaises(infer.Refused):
            c.converse(OPUS, "s", FIRST, TOOLS, 1000, "agent", "")
        self.assertEqual(c._sdk.messages.calls, 0)

    def test_one_shot_keys_are_unchanged(self):
        """Every response bought before conversations existed must still
        replay: an empty salt hashes exactly as before."""
        c = _client()
        body = c.build(OPUS, "s", "u", 100)
        raw = json.dumps(body, sort_keys=True).encode("utf-8")
        import hashlib
        self.assertEqual(c._key_for(body),
                         hashlib.sha256(raw).hexdigest()[:24])
        self.assertEqual(c._key_for(body, 2, ""), c._key_for(body, 2))


class TestOpenRouterTurns(unittest.TestCase):

    def test_a_streamed_tool_call_is_assembled_from_its_fragments(self):
        c, _ = _chat_client(_Stream([
            _delta(tool_calls=[_tc(0, "call_a", "check", '{"co')]),
            _delta(tool_calls=[_tc(0, None, None, 'de": "x = 1"}')]),
        ]))
        turn = c.converse(CODER, "s", FIRST, TOOLS, 1000, "agent", "dev-1")
        self.assertEqual(turn.completion.stop_reason, "tool_use")
        self.assertFalse(turn.completion.truncated)
        self.assertEqual(turn.tool_calls, (infer.ToolCall(
            "call_a", "check", {"code": "x = 1"}),))
        native = turn.message["native"]
        self.assertIsNone(native["content"])
        self.assertEqual(native["tool_calls"][0]["function"],
                         {"name": "check", "arguments": '{"code": "x = 1"}'})

    def test_two_calls_in_one_turn_keep_their_order(self):
        c, _ = _chat_client(_Stream([
            _delta(tool_calls=[_tc(0, "a", "check", "{}"),
                               _tc(1, "b", "check", "{}")]),
        ]))
        turn = c.converse(CODER, "s", FIRST, TOOLS, 1000, "agent", "dev-1")
        self.assertEqual([t.id for t in turn.tool_calls], ["a", "b"])

    def test_arguments_that_do_not_parse_are_reported_not_raised(self):
        c, _ = _chat_client(_Stream([
            _delta(tool_calls=[_tc(0, "a", "check", '{"code": ')])]))
        (call,) = c.converse(CODER, "s", FIRST, TOOLS, 1000, "agent",
                             "dev-1").tool_calls
        self.assertEqual(call.arguments, {})
        self.assertIn("not valid JSON", call.error)

    def test_reasoning_details_are_merged_and_sent_back(self):
        c, seq = _chat_client(
            _Stream([
                _delta(reasoning_details=[
                    {"type": "reasoning.text", "index": 0, "text": "Look "}]),
                _delta(reasoning_details=[
                    {"type": "reasoning.text", "index": 0, "text": "first."}],
                    tool_calls=[_tc(0, "a", "check", "{}")]),
            ]),
            _Stream([_delta(content="done")], finish="stop"))
        turn = c.converse(CODER, "s", FIRST, TOOLS, 1000, "agent", "dev-1")
        self.assertEqual(turn.message["native"]["reasoning_details"],
                         [{"type": "reasoning.text", "index": 0,
                           "text": "Look first."}])
        msgs = [*FIRST, turn.message, {"role": "tool", "results": [
            {"id": "a", "content": "ok"}]}]
        c.converse(CODER, "s", msgs, TOOLS, 1000, "agent", "dev-1")
        sent = seq.bodies[1]["messages"]
        self.assertEqual([m["role"] for m in sent],
                         ["system", "user", "assistant", "tool"])
        self.assertEqual(sent[2]["reasoning_details"][0]["text"],
                         "Look first.")
        self.assertEqual(sent[3], {"role": "tool", "tool_call_id": "a",
                                   "content": "ok"})

    def test_a_turn_without_tools_sends_no_tools_field(self):
        """The scripted loop talks to the model without tools; an empty
        `tools` list is not the same request as no tools at all."""
        c = _client()
        self.assertNotIn("tools", c.build_conversation(CODER, "s", FIRST, [],
                                                       1000))
        self.assertNotIn("tools", c.build_conversation(OPUS, "s", FIRST, [],
                                                       1000))

    def test_tracing_settings_do_not_change_the_request(self):
        """LangSmith is configured from the environment; nothing it reads may
        reach a request body or its cache key."""
        c = _client()
        before = c.build_conversation(CODER, "s", FIRST, TOOLS, 1000)
        env = {"LANGSMITH_TRACING": "true", "LANGSMITH_PROJECT": "p",
               "LANGCHAIN_TRACING_V2": "true"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            after = c.build_conversation(CODER, "s", FIRST, TOOLS, 1000)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(before, after)
        self.assertEqual(c._key_for(before, 0, "run=x"),
                         c._key_for(after, 0, "run=x"))

    def test_tools_are_function_tools_and_hosts_must_list_them(self):
        c = _client()
        body = c.build_conversation(CODER, "s", FIRST, TOOLS, 1000)
        self.assertEqual(body["tools"][0]["type"], "function")
        self.assertEqual(body["tools"][0]["function"]["parameters"],
                         TOOLS[0]["parameters"])
        self.assertTrue(body["provider"]["require_parameters"])
        self.assertEqual(body["messages"][0], {"role": "system",
                                               "content": "s"})


if __name__ == "__main__":
    unittest.main()
