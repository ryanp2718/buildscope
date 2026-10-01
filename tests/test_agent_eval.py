# -*- coding: utf-8 -*-
"""`scripts/agent_eval.py`, the runner for the agentic extractor's paid arms.
No model calls: a scripted fake model and synthetic pages.

What is pinned: best-of-k's success and spend are exact (checked against
enumerating every order of the draws); an episode's module and every draft
are scored with the v2 outcomes, and field agreement beside them; an episode
is read at any cap from one run, with the cases that are not observed left
out; the one-shot control is the v2 request, re-drawn when cut off; a run
records each episode once and does not run it again; and a pre-registered
run cannot share a run id, so a cache key, with an exploratory one. Written
with the runner, before its first paid call.
"""
import dataclasses
import io
import itertools
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import agent_eval as AE                                       # noqa: E402
from permits import harness as H                              # noqa: E402
from permits.cells import Outcome                             # noqa: E402
from tests.test_agent import BAD, GOOD, FakeClient, _page     # noqa: E402

ROW = re.compile(r"<tr>" + r"<td>([^<]*)</td>" * 4 + r"</tr>")
# Any model the registry knows; the fake model answers whatever it is.
MODEL = "deepseek/deepseek-v4-flash"


class _Adapter(object):
    """The reference parser for the synthetic pages."""

    @staticmethod
    def parse_index(html):
        return [{"number": a, "date": b, "address": c, "type": d}
                for a, b, c, d in ROW.findall(html)]


TARGET = H.Target("synthetic", "synthetic", "none", _Adapter,
                  {"native_id": "number", "issued_date": "date",
                   "address": "address", "permit_type": "type"},
                  "synthetic grid")


def _corpus():
    d = tempfile.mkdtemp()
    paths = []
    for n, ids in enumerate((["B-1", "B-2", "B-3"], ["B-4", "B-5"])):
        p = os.path.join(d, "page%d.html" % n)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_page(ids))
        paths.append(p)
    refs = {os.path.basename(p): TARGET.reference(H.read(p)) for p in paths}
    return d, paths, refs


def _stored(*spec):
    """Stored draws from (list_usd, accepted, perfect) triples."""
    return [AE.Stored(i, usd, usd / 2, acc, perf, perf)
            for i, (usd, acc, perf) in enumerate(spec)]


class TestBestOfK(unittest.TestCase):
    """Exact, against every order of the draws."""

    def _enumerate(self, draws, k):
        spend = success = count = 0
        for order in itertools.permutations(range(len(draws))):
            for j in order[:k]:
                spend += draws[j].list_usd
                if draws[j].accepted:
                    success += draws[j].perfect
                    break
            count += 1
        return spend / count, success / count

    def test_exact_against_every_order(self):
        cases = [
            _stored((0.01, False, False), (0.03, False, False),
                    (0.02, False, True), (0.05, False, False),
                    (0.04, False, False)),
            _stored(*[(0.01 * (i + 1), True, True) for i in range(5)]),
            # An accepted imperfect draw: the verifier's silent failure.
            _stored((0.01, True, False), (0.03, False, True),
                    (0.02, False, False), (0.05, True, True),
                    (0.04, False, False)),
            _stored((0.01, False, False), (0.03, False, False),
                    (0.02, False, False), (0.05, False, False),
                    (0.04, True, True)),
        ]
        for draws in cases:
            for k in range(1, 7):
                b = AE.best_of_k(draws, k)
                spend, success = self._enumerate(draws, k)
                self.assertAlmostEqual(b["list_usd"], spend, places=12)
                self.assertAlmostEqual(b["success"], success, places=12)
                self.assertAlmostEqual(
                    b["usd"], AE.expected_spend([d.usd for d in draws],
                                                [d.accepted for d in draws],
                                                k), places=12)

    def test_edges(self):
        prices = [0.01, 0.02, 0.03]
        self.assertAlmostEqual(AE.expected_spend(prices, [True] * 3, 5), 0.02)
        self.assertAlmostEqual(AE.expected_spend(prices, [False] * 3, 5), 0.06)
        with self.assertRaises(ValueError):
            AE.expected_spend(prices, [True], 5)
        self.assertEqual(AE.best_of_k(_stored((0.01, True, True)), 20)["k"], 1)

    def test_the_interval_is_reproducible_and_contains_the_estimate(self):
        draws = _stored(*[(0.01, i % 4 == 0, i % 4 == 0) for i in range(20)])
        a = AE.best_of_k_interval(draws, 5, 7)
        self.assertEqual(a, AE.best_of_k_interval(draws, 5, 7))
        self.assertLessEqual(a[0], AE.best_of_k(draws, 5)["success"])
        self.assertGreaterEqual(a[1], AE.best_of_k(draws, 5)["success"])


class TestScoring(unittest.TestCase):
    """The v2 outcomes, and field agreement beside them."""

    def setUp(self):
        self.dir, self.paths, self.refs = _corpus()

    def _score(self, code):
        return AE.score_code(TARGET, code, self.paths, self.refs,
                             os.path.join(self.dir, "out", "m.py"))

    def test_outcomes(self):
        raises = GOOD.replace("    out = []", "    raise ValueError('no grid')")
        cases = [(GOOD, Outcome.PERFECT), (BAD, Outcome.IMPERFECT),
                 (raises, Outcome.RAISED), ("import os\n" + GOOD,
                                            Outcome.REFUSED),
                 (None, Outcome.NO_CODE), ("print('hi')", Outcome.NO_CODE)]
        for code, want in cases:
            self.assertEqual(self._score(code)["outcome"], want, code)

    def test_field_agreement_is_reported_beside_the_outcome(self):
        good = self._score(GOOD)
        self.assertTrue(good["field_perfect"])
        # Right permit numbers, a stray '>' on every address: case 6 of the
        # failure log. Perfect under the primary rule, not field by field.
        stray = GOOD.replace('"address": cells[2]', '"address": ">" + cells[2]')
        s = self._score(stray)
        self.assertEqual(s["outcome"], Outcome.PERFECT)
        self.assertFalse(s["field_perfect"])
        self.assertEqual(s["field_disagreements"]["address"], 5)


class TestAtACap(unittest.TestCase):
    """One run read at any smaller limit, as a live limit would have
    stopped it: the turns that run are those that start below the cap."""

    SCORES = {"bad": {"outcome": "imperfect", "field_perfect": False},
              "good": {"outcome": "perfect", "field_perfect": True}}

    def _rec(self, stop, *steps):
        return {"stop": stop, "draft_scores": self.SCORES, "trajectory": [
            {"turn": i + 1, "list_usd": usd, "draft": d}
            for i, (usd, d) in enumerate(steps)]}

    def test_the_draft_at_each_cap(self):
        rec = self._rec("submitted", (0.01, None), (0.02, "bad"),
                        (0.04, "good"), (0.05, "good"))
        got = [(c, AE.at_cap(rec, c)) for c in (0.005, 0.015, 0.02, 0.03, 1.0)]
        self.assertEqual(
            [(c, x["perfect"], x["list_usd"]) for c, x in got],
            [(0.005, False, 0.01),   # the first turn always runs
             (0.015, False, 0.02),   # started at 0.01 < cap: its draft counts
             (0.02, False, 0.02),    # 0.02 is not below 0.02: stop
             (0.03, True, 0.04),     # started at 0.02 < 0.03, so it ran
             (1.0, True, 0.05)])     # submitted: final at any larger cap

    def test_what_is_not_observed(self):
        # A host failure after $0.02: a live run capped at 0.015 had
        # stopped by then, so it is observed there; at 0.05 it would have
        # gone on, and what it would have done is not known.
        cut = self._rec("infra_error", (0.01, "bad"), (0.02, "bad"))
        self.assertIsNotNone(AE.at_cap(cut, 0.015))
        self.assertIsNone(AE.at_cap(cut, 0.05))
        # The run's own cap stopped it at 0.05: known below, not above.
        capped = self._rec("budget", (0.03, "bad"), (0.06, "good"))
        self.assertTrue(AE.at_cap(capped, 0.06)["perfect"])
        self.assertIsNone(AE.at_cap(capped, 0.07))
        self.assertIsNone(AE.at_cap(self._rec("refused"), 0.01))

    def test_a_frontier_point_counts_what_it_leaves_out(self):
        recs = [self._rec("submitted", (0.01, "good")),
                self._rec("submitted", (0.01, "bad"), (0.02, "good")),
                self._rec("infra_error", (0.01, "bad"))]
        p = AE.frontier_point(recs, 0.05)
        self.assertEqual((p["n"], p["ok"], p["unobserved"]), (2, 2, 1))
        self.assertAlmostEqual(p["list_usd"], 0.015)

    def test_a_perfect_draft_left_unsubmitted_is_not_a_submission(self):
        recs = [{"submitted": True, "outcome": "perfect"},
                {"submitted": False, "outcome": "perfect"},
                {"submitted": True, "outcome": "imperfect"}]
        self.assertEqual(AE.submitted_perfect(recs), 1)


class TestEpisodes(unittest.TestCase):

    def setUp(self):
        self.dir, self.paths, self.refs = _corpus()
        self.loaded = (TARGET, self.paths, self.refs, "Write an extractor.")
        self.args = AE.parse_args(["--run-id", "t1", "--cells",
                                   "clarkco:%s:1" % MODEL])
        self.cell = AE.Cell("synthetic", MODEL, 1)
        self.patch = mock.patch.multiple(
            AE, OUT=self.dir, EPISODES=os.path.join(self.dir, "episodes.json"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def _run(self, client, arm="agent", limits=None):
        return AE.run_episode(client, self.args, arm, self.cell, self.loaded,
                              limits or AE.G.Limits(), 0, None)

    def test_an_episode_and_every_draft_are_scored_and_saved(self):
        client = FakeClient([("run_extractor", {"code": BAD})],
                            [("check", {"code": GOOD})],
                            [("submit", {"code": GOOD})])
        rec = self._run(client)
        self.assertEqual((rec["outcome"], rec["stop"], rec["turns"]),
                         (Outcome.PERFECT, "submitted", 3))
        self.assertTrue(rec["checked_before_submit"])
        self.assertNotIn("code", rec)
        self.assertNotIn("drafts", rec)
        self.assertEqual(
            {h: s["outcome"] for h, s in rec["draft_scores"].items()},
            {AE.T.digest(BAD): "imperfect", AE.T.digest(GOOD): "perfect"})
        # Read at a cap of $0.005 only the first turn runs, and it hands
        # back the bad draft.
        self.assertFalse(AE.at_cap(rec, 0.005)["perfect"])
        self.assertTrue(AE.at_cap(rec, 1.0)["perfect"])
        self.assertEqual((client.calls[0]["run_id"],
                          client.calls[0]["call_class"]), ("t1", "agent"))
        key = AE.episode_key("t1", "agent", "synthetic", MODEL, 0)
        AE.save_episode(key, rec)
        self.assertEqual(AE.done_episodes()[key]["outcome"], "perfect")

    def test_the_cap_scores_the_last_draft(self):
        client = FakeClient([("check", {"code": BAD})], usd=0.05)
        rec = self._run(client, limits=AE.G.Limits(usd=0.05))
        self.assertEqual((rec["stop"], rec["submitted"], rec["outcome"]),
                         ("budget", False, Outcome.IMPERFECT))

    def test_a_refused_call_is_not_attempted(self):
        client = FakeClient(AE.infer.Refused("budget ceiling"))
        rec = self._run(client, arm="scripted")
        self.assertEqual(rec["outcome"], Outcome.NOT_ATTEMPTED)

    def test_the_one_shot_control_is_the_v2_request(self):
        client = FakeClient("```python\n%s```" % GOOD)
        rec = AE.run_oneshot(client, self.args, self.cell, self.loaded, 0)
        self.assertEqual((rec["outcome"], rec["turns"], rec["arm"]),
                         (Outcome.PERFECT, 1, "oneshot"))
        call = client.calls[0]
        self.assertEqual((call["system"], call["tools"]), (H.SYNTH_SYSTEM, []))
        self.assertEqual(call["messages"],
                         [{"role": "user", "content": "Write an extractor."}])

    def test_the_one_shot_control_is_redrawn_when_cut_off(self):
        client = FakeClient("```python\n%s```" % BAD,
                            "```python\n%s```" % GOOD)
        real = client.converse

        def converse(model, system, messages, tools, **kw):
            turn = real(model, system, messages, tools, **kw)
            if kw["max_tokens"] == AE.infer.output_cap(MODEL):
                return AE.infer.Turn(
                    dataclasses.replace(turn.completion, truncated=True),
                    (), turn.message, turn.purchase_usd, turn.list_usd)
            return turn
        client.converse = converse
        if AE.infer.redraw_cap(MODEL) <= AE.infer.output_cap(MODEL):
            self.skipTest("%s has no larger cap to re-draw at" % MODEL)
        rec = AE.run_oneshot(client, self.args, self.cell, self.loaded, 0)
        self.assertEqual((rec["outcome"], rec["turns"]), (Outcome.PERFECT, 2))
        self.assertEqual([c["max_tokens"] for c in client.calls],
                         [AE.infer.output_cap(MODEL), AE.infer.redraw_cap(MODEL)])
        self.assertAlmostEqual(rec["list_usd"], 0.02)


class _Client(FakeClient):
    """The fake model, with what `main` asks of `infer.Client`."""

    def __init__(self, *steps):
        super().__init__(*steps)
        self.budget = AE.infer.Budget(1.0)

    def key_for(self, model):
        return "fake"


class TestMain(unittest.TestCase):
    """The whole loop: plan, run, score, save, report; then the same run
    again, which must buy nothing."""

    def setUp(self):
        self.dir, self.paths, self.refs = _corpus()
        loaded = (TARGET, self.paths, self.refs, "Write an extractor.")
        stored = _stored(*[(0.001, i < 2, i < 2) for i in range(20)])
        self.patches = [
            mock.patch.multiple(
                AE, OUT=self.dir,
                EPISODES=os.path.join(self.dir, "episodes.json"),
                CHECKPOINTS=os.path.join(self.dir, "checkpoints.sqlite")),
            mock.patch.object(AE, "load_target", lambda key: loaded),
            mock.patch.object(AE, "stored_draws", lambda cells: {
                (c.target, c.model): stored for c in cells}),
            mock.patch.object(AE, "host_prices", lambda model: {})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def _main(self, client, *extra):
        argv = ["--run-id", "m1", "--cells", "clarkco:%s:2" % MODEL,
                "--no-trace", "--max-spend", "2.00", *extra]
        with mock.patch.object(AE.infer, "Client", lambda *a, **k: client), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = AE.main(argv)
        return code, out.getvalue()

    def test_a_run_and_its_rerun(self):
        # Two episodes per arm. Agent: submit at once. Scripted: a draft
        # the check accepts. One-shot: a good and a bad module.
        good, bad = "```python\n%s```" % GOOD, "```python\n%s```" % BAD
        client = _Client([("submit", {"code": GOOD})],
                         [("submit", {"code": BAD})], good, good, good, bad)
        code, out = self._main(client, "--run")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(client.calls), 6)
        eps = AE.done_episodes()
        got = {(r["arm"], r["episode"]): r["outcome"] for r in eps.values()}
        self.assertEqual(got, {("agent", 0): "perfect",
                               ("agent", 1): "imperfect",
                               ("scripted", 0): "perfect",
                               ("scripted", 1): "perfect",
                               ("oneshot", 0): "perfect",
                               ("oneshot", 1): "imperfect"})
        self.assertIn("one-shot control: 1/2 perfect", out)
        self.assertIn("k=5 *", out)
        # The run's cap, the agent's one exact point, with the most that
        # best-of-k spends beside it.
        self.assertRegex(out, r"cap +\$0\.1500 +k=20 spends \$[0-9.]+ +"
                              r"1/2 \[[^\]]*\] f1 \$[0-9.]+ sub 1 ")
        # The same run again: every episode is on record, nothing is sent,
        # and a dry run reports the same frontier.
        again = _Client()
        code, out2 = self._main(again, "--run")
        self.assertEqual((code, again.calls), (0, []), out2)
        code, dry = self._main(_Client())
        self.assertIn("one-shot control: 1/2 perfect", dry)
        self.assertIn("dry run: nothing sent", dry)

    def test_worst_case_over_the_cap_sends_nothing(self):
        client = _Client()
        with self.assertRaises(SystemExit):
            self._main(client, "--run", "--max-spend", "0.01")
        self.assertEqual(client.calls, [])


class TestArguments(unittest.TestCase):
    CELL = "clarkco:deepseek/deepseek-v4-flash:3"

    def _args(self, *extra):
        return AE.parse_args(["--cells", self.CELL, *extra])

    def _refused(self, *extra):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            self._args(*extra)

    def test_eval_runs_have_their_own_run_ids_and_project(self):
        a = self._args("--run-id", "eval-1", "--eval")
        self.assertEqual(a.project, AE.EVAL_PROJECT)
        self.assertEqual(self._args("--run-id", "smoke-1").project,
                         AE.DEV_PROJECT)
        self._refused("--run-id", "eval-1")
        self._refused("--run-id", "smoke-1", "--eval")

    def test_bad_cells_and_arms_are_refused(self):
        a = self._args("--run-id", "x")
        self.assertEqual(a.cells, [AE.Cell("clarkco", MODEL, 3)])
        self.assertEqual(a.arms, list(AE.ARMS))
        self._refused("--run-id", "x", "--arms", "agent,bestofk")
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            AE.parse_args(["--run-id", "x", "--cells", "nowhere:x/y:1"])
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            AE.parse_args(["--run-id", "x", "--cells", "clarkco:no/such-model:1"])


if __name__ == "__main__":
    unittest.main()
