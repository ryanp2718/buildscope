# -*- coding: utf-8 -*-
"""The agent and the scripted loop in `permits/agent/`, against a scripted
fake model. Nothing here calls a model or spends money.

The tools are real: a `Workspace` over two small synthetic pages, so drafts
are audited, run in the subprocess sandbox and checked exactly as they would
be in an episode. What is pinned: the graphs route as the plan says, the
limits stop an episode where they should (a replayed episode included), an
interrupted episode resumes from its checkpoint without buying its turns
again, the review step pauses and resumes, and the behaviour the plan
measures (submitting without a check, or despite a failed one) is recorded.
"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from langgraph.checkpoint.memory import InMemorySaver         # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver           # noqa: E402
from langgraph.types import Command                           # noqa: E402

from permits import infer                                     # noqa: E402
from permits.agent import graph as G                          # noqa: E402
from permits.agent import tools as T                          # noqa: E402

FIELDS = ["native_id", "issued_date", "address", "permit_type", "status",
          "structure_code", "contractor"]


def _page(ids):
    rows = "".join(
        "<tr><td>%s</td><td>01/0%d/2026</td><td>%d Main St</td>"
        "<td>Residential</td></tr>" % (i, n + 1, 100 + n)
        for n, i in enumerate(ids))
    return ("<html><body><table><tr><td>Search</td><td>Go</td></tr></table>"
            "<table><tr><th>Permit</th><th>Issued</th><th>Address</th>"
            "<th>Type</th></tr>%s</table></body></html>" % rows)


GOOD = '''import re

def extract(html):
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html):
        cells = re.findall(r"<td>(.*?)</td>", tr)
        if len(cells) == 4:
            out.append({"native_id": cells[0], "issued_date": cells[1],
                        "address": cells[2], "permit_type": cells[3],
                        "status": None, "structure_code": None,
                        "contractor": None})
    return out
'''
# Drops every row after the first: the rows check fails on both pages.
BAD = GOOD.replace("    return out", "    return out[:1]")


def _workspace():
    d = tempfile.mkdtemp()
    paths = []
    for n, ids in enumerate((["B-1", "B-2", "B-3"], ["B-4", "B-5"])):
        p = os.path.join(d, "page%d.html" % n)
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(_page(ids))
        paths.append(p)
    return T.Workspace(paths, FIELDS, os.path.join(d, "work"))


class Crash(Exception):
    """Stands in for a process dying mid-episode."""


class FakeClient(object):
    """Plays back one step per model call. A step is text, a list of
    (name, arguments) tool calls, an `infer.ToolCall`-bearing list, or an
    exception to raise. Records what each call was given. Each turn costs
    `usd` to buy and `list_usd` (default: the same) at list price."""

    def __init__(self, *steps, usd=0.01, list_usd=None):
        self.steps = list(steps)
        self.usd = usd
        self.list_usd = usd if list_usd is None else list_usd
        self.calls = []

    def converse(self, model, system, messages, tools, **kw):
        self.calls.append({"system": system, "messages": list(messages),
                           "tools": [t["name"] for t in tools], **kw})
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        text, calls = (step, ()) if isinstance(step, str) else ("", step)
        tool_calls = tuple(
            c if isinstance(c, infer.ToolCall)
            else infer.ToolCall("c%d_%d" % (len(self.calls), i), c[0], c[1])
            for i, c in enumerate(calls))
        done = infer.Completion(
            text=text, usage=infer.Usage(10, 5), model=model,
            provider=infer.OPENROUTER, cached=False, usd=self.usd,
            stop_reason="tool_use" if tool_calls else "end_turn",
            truncated=False)
        native = {"role": "assistant", "content": text or None}
        return infer.Turn(done, tool_calls, {"role": "assistant",
                                             "native": native}, self.usd,
                          self.list_usd)


def _episode(client, ws=None, limits=None, review=False, episode=0):
    return G.Episode(client=client, model="x/fake", system="SYSTEM",
                     user="Write an extractor.", workspace=ws or _workspace(),
                     run_id="test", episode=episode, call_class="agent",
                     tag="t/agent/e%02d" % episode,
                     limits=limits or G.Limits(), review=review)


def _tool_results(client, n):
    """The tool results the model was shown at call `n`."""
    last = client.calls[n]["messages"][-1]
    return [r["content"] for r in last["results"]]


class TestTheAgent(unittest.TestCase):

    def test_it_checks_then_submits(self):
        c = FakeClient([("check", {"code": GOOD})], [("submit", {"code": GOOD})])
        s = G.run(_episode(c), "agent")
        self.assertEqual((s["stop"], s["submitted"], s["code"]),
                         ("submitted", True, GOOD))
        self.assertTrue(s["checked_before_submit"])
        self.assertTrue(s["accepted_at_submit"])
        self.assertEqual((s["turns"], s["usd"], s["checks"]), (2, 0.02, 1))
        self.assertTrue(_tool_results(c, 1)[0].startswith("ACCEPT"))
        self.assertEqual(c.calls[0]["tools"], list(T.TOOL_NAMES))
        self.assertIn(G.AGENT_INSTRUCTIONS, c.calls[0]["system"])

    def test_a_failed_check_names_the_pages_and_counts(self):
        c = FakeClient([("check", {"code": BAD})], [("submit", {"code": BAD})])
        s = G.run(_episode(c), "agent")
        shown = _tool_results(c, 1)[0]
        self.assertTrue(shown.startswith("REJECT"))
        self.assertIn("1 rows returned, grid shows 3", shown)
        self.assertTrue(s["checked_before_submit"])
        self.assertFalse(s["accepted_at_submit"])

    def test_submitting_without_a_check_is_recorded(self):
        c = FakeClient([("submit", {"code": GOOD})])
        s = G.run(_episode(c), "agent")
        self.assertEqual(s["stop"], "submitted")
        self.assertFalse(s["checked_before_submit"])
        self.assertIsNone(s["accepted_at_submit"])

    def test_calls_after_submit_are_not_run(self):
        c = FakeClient([("submit", {"code": GOOD}), ("check", {"code": BAD})])
        s = G.run(_episode(c), "agent")
        self.assertEqual(s["code"], GOOD)
        self.assertEqual(s["tool_errors"], 1)

    def test_arguments_that_did_not_parse_go_back_as_an_error(self):
        broken = infer.ToolCall("x", "check", {}, "arguments are not valid "
                                                  "JSON: Expecting value")
        c = FakeClient([broken], [("submit", {"code": GOOD})])
        s = G.run(_episode(c), "agent")
        self.assertIn("was not run", _tool_results(c, 1)[0])
        self.assertEqual(s["stop"], "submitted")

    def test_the_tools_read_and_search_the_pages(self):
        c = FakeClient([("list_pages", {}),
                        ("search_page", {"page": 1, "text": "b-5"}),
                        ("read_page", {"page": 0, "start": 0, "length": 50})],
                       [("submit", {"code": GOOD})])
        s = G.run(_episode(c), "agent")
        listed, found, read = _tool_results(c, 1)
        self.assertIn("page 1: page1.html", listed)
        self.assertIn("1 matches in page 1", found)
        self.assertIn("characters 0-50", read)
        self.assertEqual(s["pages_read"], 2)

    def test_it_is_told_its_budget_after_each_turn(self):
        # The last result of each turn ends with what is used of both
        # limits; the other results of the turn are left as they are.
        c = FakeClient([("list_pages", {}), ("list_pages", {})],
                       [("list_pages", {})], [("submit", {"code": GOOD})],
                       usd=0.001, list_usd=0.02)
        G.run(_episode(c, limits=G.Limits(turns=5, usd=0.10)), "agent")
        first, last = _tool_results(c, 1)
        self.assertNotIn("Budget", first)
        self.assertTrue(last.endswith("\n\nBudget: turn 1 of at most 5; "
                                      "$0.0200 of $0.10 spent (list price)."))
        self.assertIn("turn 2 of at most 5; $0.0400", _tool_results(c, 2)[0])

    def test_the_turn_limit_scores_the_last_draft(self):
        c = FakeClient([("list_pages", {})],
                       [("run_extractor", {"code": GOOD})],
                       [("list_pages", {})])
        s = G.run(_episode(c, limits=G.Limits(turns=2)), "agent")
        self.assertEqual((s["stop"], s["submitted"], s["code"]),
                         ("turn_limit", False, GOOD))
        self.assertEqual(len(c.calls), 2)

    def test_the_dollar_limit_is_checked_before_each_turn(self):
        c = FakeClient([("list_pages", {})], [("list_pages", {})],
                       [("list_pages", {})], usd=0.05)
        s = G.run(_episode(c, limits=G.Limits(usd=0.08)), "agent")
        self.assertEqual((s["stop"], s["turns"]), ("budget", 2))
        self.assertEqual(len(c.calls), 2)

    def test_a_text_reply_is_nudged_then_stops(self):
        c = FakeClient("```python\n" + GOOD + "```", "still text", "text")
        s = G.run(_episode(c), "agent")
        self.assertEqual((s["stop"], s["nudges"]), ("no_tool_call", 2))
        self.assertEqual(c.calls[1]["messages"][-1], {
            "role": "user", "content": G.NUDGE + "\n\nBudget: turn 1 of at "
            "most 30; $0.0100 of $0.15 spent (list price)."})

    def test_a_host_failure_ends_the_episode_as_infra_error(self):
        c = FakeClient(infer.TransientError("host closed the stream"))
        s = G.run(_episode(c), "agent")
        self.assertEqual(s["stop"], "infra_error")
        self.assertIn("host closed", s["error"])

    def test_the_limit_is_on_list_priced_spend(self):
        # Billed nothing (a host that charged nothing, or a replay) but
        # $0.06 at list price: the $0.10 limit stops it after two turns.
        c = FakeClient([("run_extractor", {"code": BAD})],
                       [("run_extractor", {"code": BAD})],
                       [("submit", {"code": GOOD})], usd=0.0, list_usd=0.06)
        s = G.run(_episode(c, limits=G.Limits(usd=0.10)), "agent")
        self.assertEqual((s["stop"], s["turns"], s["usd"], s["list_usd"]),
                         ("budget", 2, 0.0, 0.12))

    def test_the_trajectory_has_each_turns_spend_and_latest_draft(self):
        """What the runner scores an episode at every smaller limit from."""
        c = FakeClient([("read_page", {"page": 0})],
                       [("run_extractor", {"code": BAD})],
                       [("check", {"code": GOOD})],
                       [("submit", {"code": GOOD})])
        s = G.run(_episode(c), "agent")
        self.assertEqual([(t["turn"], t["list_usd"], t["draft"])
                          for t in s["trajectory"]],
                         [(1, 0.01, None), (2, 0.02, T.digest(BAD)),
                          (3, 0.03, T.digest(GOOD)), (4, 0.04, T.digest(GOOD))])
        self.assertEqual(s["drafts"], {T.digest(BAD): BAD, T.digest(GOOD): GOOD})


class TestCheckpoints(unittest.TestCase):

    def test_an_interrupted_episode_resumes_where_it_stopped(self):
        """The first turn is not bought again: the resumed episode's first
        model call already carries turn 1's tool result."""
        path = os.path.join(tempfile.mkdtemp(), "episodes.sqlite")
        conn = sqlite3.connect(path, check_same_thread=False)
        try:
            saver = SqliteSaver(conn)
            ws = _workspace()
            first = FakeClient([("check", {"code": GOOD})], Crash("died"))
            with self.assertRaises(Crash):
                G.run(_episode(first, ws), "agent", saver)
            second = FakeClient([("submit", {"code": GOOD})])
            s = G.run(_episode(second, ws), "agent", saver)
        finally:
            conn.close()
        self.assertEqual(len(second.calls), 1)
        self.assertEqual([m["role"] for m in second.calls[0]["messages"]],
                         ["user", "assistant", "tool"])
        self.assertEqual((s["stop"], s["turns"]), ("submitted", 2))
        self.assertTrue(s["checked_before_submit"])

    def test_review_pauses_before_accepting_and_resumes(self):
        for approved, stop in ((True, "submitted"),
                               (False, "rejected_in_review")):
            with self.subTest(approved=approved):
                ep = _episode(FakeClient([("submit", {"code": GOOD})]),
                              review=True)
                g = G.build_agent(ep, InMemorySaver())
                config = {"configurable": {"thread_id": "r%s" % approved}}
                g.invoke(G.initial_state(ep), config)
                snap = g.get_state(config)
                self.assertEqual(snap.next, ("review",))
                self.assertEqual(snap.tasks[0].interrupts[0].value,
                                 {"code": GOOD})
                final = g.invoke(Command(resume=approved), config)
                self.assertEqual(final["stop"], stop)


class TestTheScriptedLoop(unittest.TestCase):

    def test_the_trajectory_has_each_draft(self):
        c = FakeClient("```python\n%s```" % BAD, "```python\n%s```" % GOOD)
        s = G.run(_episode(c), "scripted")
        self.assertEqual([t["draft"] for t in s["trajectory"]],
                         [T.digest(BAD), T.digest(GOOD)])
        self.assertEqual(s["stop"], "submitted")

    def test_it_is_not_told_its_budget(self):
        c = FakeClient("```python\n%s```" % BAD, "```python\n%s```" % GOOD)
        G.run(_episode(c), "scripted")
        self.assertNotIn("Budget", json.dumps(c.calls[1]["messages"]))

    def test_a_failed_check_is_shown_and_repaired(self):
        c = FakeClient("```python\n" + BAD + "```",
                       "```python\n" + GOOD + "```")
        s = G.run(_episode(c), "scripted")
        self.assertEqual((s["stop"], s["code"], s["turns"]),
                         ("submitted", GOOD, 2))
        self.assertEqual([call["tools"] for call in c.calls], [[], []])
        repair = c.calls[1]["messages"][-1]["content"]
        self.assertIn("REJECT", repair)
        self.assertIn("1 rows returned, grid shows 3", repair)
        self.assertEqual(c.calls[0]["system"], "SYSTEM")

    def test_a_reply_without_a_module_is_asked_again(self):
        c = FakeClient("I will write it next.", "```python\n" + GOOD + "```")
        s = G.run(_episode(c), "scripted")
        self.assertEqual(s["stop"], "submitted")
        self.assertEqual(c.calls[1]["messages"][-1]["content"], G.NO_CODE)

    def test_it_stops_at_the_turn_limit_with_its_last_draft(self):
        c = FakeClient(*["```python\n" + BAD + "```"] * 3)
        s = G.run(_episode(c, limits=G.Limits(turns=3)), "scripted")
        self.assertEqual((s["stop"], s["code"], s["checks"]),
                         ("turn_limit", BAD, 3))


class TestTheWorkspace(unittest.TestCase):

    def test_the_grid_rows_are_counted_without_a_reference(self):
        self.assertEqual(_workspace().expected, [3, 2])

    def test_a_refused_module_is_not_run(self):
        ws = _workspace()
        out = ws.check("import os\n\ndef extract(html):\n    return []\n")
        self.assertTrue(out.startswith("REJECT: refused before running"))
        self.assertIn("imports os", out)

    def test_notes_do_not_decide_acceptance(self):
        """Fields the pages do not print are null by contract, so an empty
        column is a note, not a failure."""
        out = _workspace().check(GOOD)
        self.assertTrue(out.startswith("ACCEPT"))
        self.assertIn("empty on every row: status, structure_code, "
                      "contractor", out)

    def test_stray_brackets_are_noted(self):
        edgy = GOOD.replace('"native_id": cells[0]',
                            '"native_id": ">" + cells[0]')
        out = _workspace().check(edgy)
        self.assertIn("stray angle bracket", out)
        self.assertIn('">B-1"', out)


class TestTracingSwitch(unittest.TestCase):
    """`enable_tracing` reads the key from the environment or a file outside
    the tree, and leaves tracing off when there is neither. Written with the
    agentic extractor, so a missing key cannot fail a run or turn tracing on
    half-way."""

    NAMES = ("LANGSMITH_API_KEY", "LANGSMITH_TRACING")

    def setUp(self):
        self.saved = {n: os.environ.pop(n, None) for n in self.NAMES}
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for n, v in self.saved.items():
            os.environ.pop(n, None)
            if v is not None:
                os.environ[n] = v

    def _file(self, text):
        p = os.path.join(self.dir, "key")
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return p

    def test_no_key_leaves_tracing_off(self):
        self.assertFalse(G.enable_tracing(os.path.join(self.dir, "none")))
        self.assertFalse(G.enable_tracing(self._file("  \n")))
        for n in self.NAMES:
            self.assertNotIn(n, os.environ)

    def test_key_file_turns_tracing_on(self):
        self.assertTrue(G.enable_tracing(self._file("lsv2_fake\n")))
        self.assertEqual(os.environ["LANGSMITH_API_KEY"], "lsv2_fake")
        self.assertEqual(os.environ["LANGSMITH_TRACING"], "true")

    def test_environment_key_wins(self):
        os.environ["LANGSMITH_API_KEY"] = "from_env"
        self.assertTrue(G.enable_tracing(self._file("from_file")))
        self.assertEqual(os.environ["LANGSMITH_API_KEY"], "from_env")


if __name__ == "__main__":
    unittest.main()
