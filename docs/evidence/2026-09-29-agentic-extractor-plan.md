# An agentic extractor: does a tool-using agent beat sampling, at the same spend?

Date:      2026-09-29
Produced:  Written by hand, while stage 3 of the v2 run was running. No model calls; cost $0.00.
Inputs:    [v2 pre-registration](2026-09-27-v2-run-preregistration.md), the v2 draws in
           `data/infer/variance.json` and their generated extractors in
           `data/infer/synth/variance/` (689 v2 files at stage 2's close),
           [results and visualization plan](2026-09-28-v2-results-and-visualization-plan.md),
           [failure cases](../design/failure-cases.md)
Outputs:   `spikes/verifier_offline.py` (steps 1 and 2, done); tool calling in
           `permits/infer.py`, `permits/agent/` (the tools, the verifier and both graphs) and
           `scripts/agent_eval.py` (the runs and their scoring), built (step 3). Planned: a
           pre-registration and a results report.
Status:    Draft plan; steps 1 and 2 run offline 2026-09-30 (see "Progress"). Scope decided
           2026-09-30: a tool-using agent, with a scripted repair loop as its control, and LangSmith
           for tracing. The $0 build (step 3) starts while stage 3 of the v2 run finishes; nothing is
           spent on the agent until the v2 results page is published.

## Questions

The v2 run measures one-shot generation: a model reads the pages once, writes an extractor, and is
scored. Many of its failures are the kind feedback could fix (see the failure cases): a module that
does not parse, a class of rows dropped, a stray `>` on every value, a column left empty. The
question is whether a system around the model does better than the model alone, and at what cost.

1. **Can a check that needs no reference tell a working extractor from a broken one?** Answered
   offline (Progress): yes on these portals, with a 0.6% false-accept rate.
2. **Does sampling k drafts and keeping the first that passes that check beat one draft?** Answered
   offline: a median 40-point gain where pass@1 is between 0 and 1, at about the same cost per
   success, and no gain where pass@1 is 0.
3. **Does a tool-using agent beat best-of-k at the same spend per task?** Best-of-k is the cheap
   alternative a team would try first, so it is the baseline that matters.
4. **Rescue: does the agent produce working extractors where the model's one-shot rate is 0?**
   Sampling cannot find a draw a model never produces, so any success there comes from the agent.
5. **Does generic feedback do what a human expert's hint did?** On Clark, the v2 hint arm adds one
   paragraph a person wrote after studying Clark's failures. The agent gets no hint, only feedback
   any portal would give ("page 12's grid has 10 rows; you returned 8"). Per model on Clark:
   one-shot without the hint, one-shot with it, and the agent without it. If the agent matches the
   hint, a check that works on every portal can stand in for knowledge written for one.
6. **Does the agent's autonomy add anything over a scripted loop?** The same model, tools and
   budget, with the order of steps fixed instead of chosen by the model. Without this control, a
   good agent result could be the verifier's feedback rather than the agent.

## Arms

All are scored by the v2 scorer, after the run and outside it, on the same targets: record
agreement primary and field-level agreement beside it, as in the v2 run (its deviation 4).

| arm | what it does | new spend |
|---|---|---|
| one-shot | the v2 cells as measured: pass@1 | none |
| best-of-k | k independent v2 draws, keep the first the verifier accepts | none: simulated from stored draws |
| hint | the v2 hint cells (Clark only) | none |
| scripted loop | draft, run, check; if a check fails, repair with the failures shown; a fixed order | paid |
| agent | the model chooses its own tool calls until it submits or runs out of turns or money | paid |
| one-shot control | fresh one-shot draws, bought beside the paid arms: a check for drift since the v2 draws | paid, a few cents |

**Cost is compared as a frontier, with one primary point.** Revised 2026-09-30, after the smoke
run's dry run (Progress): a single limit matched to best-of-5 gives a cheap model two or three
agent turns, and a dollar figure depends on which host served each call.

- **Spend is list-priced.** Every figure on the cost axis is tokens at the model's list price, every
  input token at the input rate with no cache discount, so it does not depend on which host
  OpenRouter chose, what that host charged or what it served from a cache. The same model's calls
  are billed at a median 0.11 to 0.61 of list depending on the host (Progress). Billed dollars
  from the ledger are reported beside it.
- **Each arm is a set of operating points.** Best-of-k gives one point per k: its success rate and
  its mean list-priced spend per task, computed exactly from the stored draws (no simulation),
  with a bootstrap interval over those draws. The agent and the scripted loop give one point per
  cap B: the share of episodes whose module is perfect when the episode is stopped at B, and the
  mean spend at B, with Wilson intervals over episodes. Plotted together they are the
  cost-accuracy frontier.
- **One run gives every cap.** Each episode runs once under a generous cap (`--cap-usd`, $0.15 by
  default): the runner records each turn's cumulative spend and the latest draft after it, scores
  every distinct draft, and evaluates any B afterwards. The scripted loop is never told its limit,
  so its episode stopped at B is exactly its first B. The agent is told its budget (see "The
  agent") and paces itself for the run's cap, so below that cap an agent point is the episode cut
  off at B, not an agent given B, and likely understates it; the pre-registration can add episodes
  told the primary point's cap. The limit is checked
  before each turn, as in a live run, so the turn that crosses B still runs and its draft counts;
  spend is plotted as actually incurred, including that turn. A cap above what an episode spent
  before a host failure or before the run's own cap stopped it is not observed for that episode,
  and is left out of that point and counted beside it.
- **The primary comparison** is one pre-registered point per model and target: the agent against
  best-of-5 at best-of-5's mean list-priced spend, pooled across cells. The other points, at the
  spend of best-of-1, 10 and 20, are descriptive. Ten episodes per cell give a 95% interval about
  ±0.26 wide at a rate of 0.5, so per-cell points are for reading, and claims are pooled or large
  (a rescue: one success where 20 one-shot draws had none). The best-of-k side is uncertain too
  where the stored draws have few successes: deepseek-v4-flash on Clark has 2 in 20, and its
  best-of-5 success of 0.45 has a bootstrap interval of [0.00, 0.81].
- **Drift control.** The best-of-k points come from draws bought days earlier. Fresh one-shot draws
  in the same run, scored the same way, show whether the model or its hosts have moved since; if
  their rate differs from the stored one, that is reported beside the comparison.
- A turn limit (30 by default) stops a loop that spends nothing.

## The agent

A ReAct loop built as a LangGraph `StateGraph`: a model node, a conditional edge to a tool node,
and back, until the model calls `submit` or a limit is hit.

    start ─→ model ─┬─ tool calls ─→ tools ─→ model
                    ├─ submit ─→ (interrupt, demo only) ─→ end
                    └─ turn or dollar limit ─→ end (last draft, if any, is scored)

**Tools.** None of them sees the adapter, the reference records or the scorer.

| tool | returns |
|---|---|
| `list_pages()` | page ids and sizes |
| `read_page(page, start, length)` | a slice of a page's HTML, capped in length |
| `search_page(page, text)` | each match's offset with a little context, capped; plain text, not a regular expression |
| `run_extractor(code, pages)` | per page: rows returned, the traceback if it raised, the first few rows |
| `check(code)` | the verifier's results per page: row count against the grid, ids, stray markup, dates, empty columns |
| `submit(code)` | ends the episode with that module |

- **Nothing forces a check.** The agent may submit without calling `check`, or after a failed one.
  How often it does is measured, since that is what separates an agent from the scripted loop.
- **The first turn** carries the v2 frozen prompt, so the agent's first draft is comparable to a
  one-shot draw, plus the tool descriptions and an instruction to answer through `submit`.
- **It is told its budget.** Each turn's last tool result, and any nudge, ends with the turns and
  list-priced dollars used against its limits, and the instructions say an unsubmitted module does
  not count and that turns cost more as the conversation grows. Added after the smoke run, where
  the agent, told nothing, spent its cap exploring (Progress).
- **Model calls go through `permits.infer`**, not a LangChain chat model, so the agent inherits the
  per-process spend ceiling, the ledger, the response cache and the v2 request settings. LangGraph
  orchestrates; the transport stays the one source of truth for cost. This needs `permits.infer` to
  carry multi-turn conversations and tool calls, for Anthropic's Messages API and the OpenAI-style
  chat API OpenRouter serves (step 3a).
- **Sandbox:** the existing subprocess runner under a timeout (`run_synth`), after the static audit.
- **Checkpointing:** LangGraph's SQLite checkpointer, so an interrupted episode resumes at its last
  finished node without buying its calls again.
- **Human review:** an `interrupt` before accept, off in evaluation runs and on in the demo, where a
  person approves an extractor before it runs in production.

**The scripted loop** is a second `StateGraph` over the same tools and limits: draft, `run_extractor`,
`check`, and on any failure one repair turn that shows the traceback or failed checks and a few of the
draft's own rows; repeat until the checks pass or a limit is hit, then submit the last draft. It is
called a scripted loop (a workflow) throughout, never an agent.

**The rule that keeps it honest.** `permits/agent/` may not import the adapters, the reference
parsers, the scorer or the hint text, and `tests/test_structure.py` checks that, as it already checks
imports between tools. The verifier moves from `spikes/verifier_offline.py` into
`permits/agent/verify.py`, and the spike imports it from there.

**Tracing: LangSmith, for watching runs only.** Every reported figure comes from the ledger and the
scorer, never from LangSmith.

- Two LangSmith projects: `buildscope-agent-dev` for exploratory runs and `buildscope-agent-eval`
  for the pre-registered runs.
- Tracing never changes a request or a cache key; a test asserts it.
- Evaluation runs carry their run id in the cache key, so a response bought in an exploratory run
  cannot be replayed into an evaluation run; a test asserts that too.
- The key is `LANGSMITH_API_KEY` in the user's environment, set by the user. Without it tracing is
  off and everything else runs.
- LangSmith's datasets and experiments are fine for development comparisons and for reading
  trajectories, not for the headline figures (see "Why the headline figures stay local").

## Metrics

Pre-registered before any paid episode, from the families in the results plan:

- **Capability:** the success rate of the submitted extractor per model, target and arm, with Wilson
  intervals; pass@k and pass^k across episodes; field-level success beside it.
- **Economics:** the cost-accuracy frontier per arm, on list-priced spend (see "Arms"), with billed
  dollars and time beside it; cost per success and time per success at the primary point; per turn,
  the cost distribution (mean and median, since reasoning length is heavy-tailed), hosts and the
  share of input served from a cache.
- **Verifier quality:** false-accept rate (the check passes, the scorer fails: a silent failure that
  would ship) and false-reject rate, with intervals, on the episodes' own submissions.
- **Behaviour (agent and scripted loop):** turns and tool calls per episode; share of episodes that
  submit without checking, and that submit despite a failed check; repair efficacy (the share of
  failing drafts the next draft fixes); stuck rate (episodes that hit a limit); tool errors; pages
  read, and bytes of HTML read per episode.

## Models and targets

- **Targets:** Clark and St. Johns (development) and Santa Barbara (held out), as in v2, so every
  agent result has a one-shot and a best-of-k result beside it. The verifier's row rule was designed
  knowing that Clark's failures drop rows, so Santa Barbara is the clean test of question 5's claim.
- **Models,** chosen by a rule fixed in the pre-registration, not by name: v2 roster models with a
  purchase cost per draw of at most $0.03, a host that supports tool calling at the lab's
  precision, and a v2 hint cell on Clark; two with Clark pass@1 = 0 (question 4) and three with Clark
  pass@1 in (0, 0.7]. Candidates by the v2 data at 2026-09-30, before the tool-support check:
  gpt-oss-120b and qwen3-coder at 0; deepseek-v4-flash, gpt-6-luna and mimo-v2.6-flash in the band.
  A model that calls tools badly is a finding, reported, not a reason to swap it.
- **n:** 10 episodes per model, target and paid arm: 5 × 3 × 2 × 10 = 300 episodes.

## Why the headline figures stay local

- **Reproducibility.** Every number in `docs/evidence/` is reproducible from a named script and a
  local artifact. Hosted traces can be deleted, expire on a retention schedule, or be re-run, and a
  reader cannot re-derive them without the account.
- **One cost source.** The ledger records what the provider billed, the charges for failed calls,
  and $0 for cache replays. A second cost computed from token counts and a price table would
  disagree with it in exactly the cases that matter.
- **Like for like.** The one-shot, best-of-k and hint arms are scored by `conformance.score` from
  stored data. Scoring the agent with a different evaluator would make the comparison not like for
  like.
- **The statistics.** Wilson intervals, the unbiased pass@k estimators, Newcombe differences and
  missing-draw bounds are computed here; an experiment view gives means.
- **Leakage.** Keeping the references and the scorer local keeps the no-reference rule checkable by
  an import test. A hosted evaluator would need the references uploaded next to the traces.

## Order of work

1. **The verifier, offline, $0.** Done.
2. **Best-of-k, offline, $0.** Done.
3. **The build, $0, while the v2 run finishes:**
   - a. multi-turn conversations and tool calls in `permits.infer`, both APIs, with the cache key
     over the whole conversation plus episode and run ids, and tests against recorded responses;
   - b. `permits/agent/verify.py` and `permits/agent/tools.py`;
   - c. the agent and scripted-loop graphs, the SQLite checkpointer and the demo `interrupt`;
   - d. tests against a scripted fake model: routing, the dollar and turn limits, resuming from a
     checkpoint, the no-reference import rule, tracing not changing requests, dev responses not
     replaying into evaluation runs.
4. **Smoke run:** one model, one target, a few episodes per paid arm, to measure turns and cost per
   episode and check the limits are workable. Run 2026-09-30, before the v2 results page: the user
   moved it ahead, since it is independent of the v2 results.
5. **Pre-registration,** with the model rule applied, k, the limits and the cap; then the paid runs.
6. **Report and a page section,** the arms side by side, and new failure cases in the log.

## Budget

At a list-priced cap of $0.15 per episode, 300 episodes are at most about $45 at list price plus
one turn of overshoot each, and less where episodes submit early; the one-shot controls add a few
cents per cell at these models' prices. Billed spend is lower where hosts cache the repeated
conversation: 0.12 to 0.19 of list for the smoke run's multi-turn episodes, which would put 300
episodes near $5 to $9, but the ratio depends on each model's hosts. The pre-registration fixes
the cap and a spend limit from a projection per model.

## Progress

- 2026-09-30, step 1 and 2 run (`spikes/verifier_offline.py`, $0) on the 749 scored v2 draws then
  stored, stage 3 part-way. The row rule matched the reference row count on all 71 development pages
  before Santa Barbara was looked at. Against the scorer as coded, the verifier accepted 358
  extractors, of which 2 fail the scorer (0.6% [0.2, 2.0]); it rejected 3 of 359 perfect ones (0.8%)
  and caught 98.9% of the extractors that ran cleanly but disagreed. Santa Barbara, held out: 0 of
  48 accepted fail, 0 of 48 perfect rejected. The row count does almost all the work: without it,
  31% of accepted extractors fail. The 2 escapes return every value prefixed with a stray `>`,
  which the markup check does not match. The 3 rejections are extractors that emit one extra blank
  or duplicated row, which the contract forbids and the scorer forgives (it matches on the set of
  permit numbers and drops rows with none).
- Best-of-k with this verifier: over the 45 cells with 0 < pass@1 < 1, keeping the first accepted
  of up to 5 draws raises the chance of a working extractor by a median of 40 points, at a median
  0.93 times one-shot cost per success. It tracks the oracle's pass@k closely. It rescues no cell at
  pass@1 = 0: sampling cannot find a working draw a model never produces, which is the case a repair
  loop would have to answer.
- **The scorer checks the records, not their fields.** A draw is `perfect` when the set of permit
  numbers matches the adapter's on every page; field values are compared and stored but do not
  decide the outcome. The design doc and the pre-registration describe a pass as agreeing "on every
  record of every page". Re-scored with every field required (field audit, `data/infer/verifier/
  field_audit.json`), 311 of 349 perfect draws still pass: Clark 164 of 166, Santa Barbara 46 of 47,
  St. Johns 101 of 136. The St. Johns failures leave whole columns null (address, issue date,
  property-use code) on every record. The v2 report keeps the coded rule as primary and reports
  field-level pass@1 beside it (v2 pre-registration, deviation 4). The verifier has no check for it
  either; a column the grid prints but the output leaves null on every row is the candidate,
  designed on St. Johns and checked on Santa Barbara.
- 2026-09-30: scope decided. The paid arm is a tool-using agent (the model chooses its tool calls),
  with a scripted repair loop over the same tools as its control (question 6), question 5 (generic
  feedback against the human hint) added, and LangSmith wired in for tracing only. The $0 build may
  start before the v2 page is published; the paid steps may not.
- 2026-09-30, step 3 built, $0, no model called:
  - a. `Client.converse` in `permits/infer.py`: one turn of a conversation with tools, on both
    providers, through the same cache, budget, retries and ledger as a one-shot call (the shared
    part is now `Client._call`; `message` builds the same bodies and keys as before). The cache key
    adds the episode and a required run id. Each turn's cache entry keeps its purchase cost, so an
    episode's dollar limit stops a replay where the original stopped. `tests/test_converse.py`.
  - b. `permits/sandbox.py` (the audit, the subprocess runner, the code-block reader and the
    data-row rule, moved from `scripts/conformance.py` verbatim and re-exported there),
    `permits/agent/verify.py` (the verifier, moved from the spike; re-checked on 40 stored
    extractors, 25 of them failing a check, with identical results to the offline run) and
    `permits/agent/tools.py`. Two notes were added beside the four checks, not deciding acceptance:
    stray angle brackets (failure case 6) and fields empty on every row (case 5); they are post hoc.
    `search_page` is a plain substring search, not a regular expression, so a model's pattern
    cannot hang the harness.
  - c. `permits/agent/graph.py`: the agent (model node, tool node, review node with a LangGraph
    `interrupt`) and the scripted loop (draft, check, repair), with per-episode turn and dollar
    limits and a summary per episode (stop reason, turns, cost, submitted or last draft, checked
    before submit, accepted at submit, tool calls and errors, pages read). Model calls are traced
    to LangSmith as "llm" runs when tracing is on.
  - d. `tests/test_agent.py` (19 tests: routing, limits, resume from a SQLite checkpoint, review,
    both arms) and a structure test that `permits/agent/` imports no reference parser.
  - Not yet verified against a live API: sending Anthropic thinking blocks back after a tool call,
    and merging OpenRouter's streamed `reasoning_details`. The smoke run (step 4) checks both
    before any evaluation run.
  - Tracing switch: `enable_tracing()` in `permits/agent/graph.py` reads the key from
    `LANGSMITH_API_KEY` or `~/.langsmith_key` (the same rule as the model keys), so tracing can be
    turned on without restarting a session; 3 tests. `spikes/tracing_check.py` runs one agent
    episode against a scripted fake model and reads the trace back from `buildscope-agent-dev`,
    $0. First run, 2026-09-30: OK, 21 runs in the trace, all 4 model calls with token counts and
    cost.
  - The runner, `scripts/agent_eval.py`: cells as `target:model:episodes`, both paid arms, and
    without `--run` a dry run that prints each episode's dollar limit and the run's worst case and
    refuses a worst case over `--max-spend`. The limit is best-of-k's expected purchase cost per
    task, computed exactly from the stored v2 draws, their purchase costs and the verifier's
    verdicts (checked against enumerating every order), or set by hand with `--episode-usd`. Each
    episode's module is scored after the episode, outside it, with the v2 outcomes and field
    agreement beside them, and saved to `data/agent/episodes.json`; a finished episode is not run
    again, and an interrupted one resumes from its SQLite checkpoint. `--eval` sends traces to
    `buildscope-agent-eval` and needs a run id starting `eval-`, which no exploratory run may use,
    so no cached response crosses between the two. 11 tests in `tests/test_agent_eval.py`.
  - Smoke-run dry run, 2026-09-30 (run by the user): deepseek-v4-flash on Clark, 3 episodes per
    arm. The limit matched to best-of-5 came to $0.0026: one draw costs about $0.0006 billed, and
    the verifier accepts 2 of the 20 stored draws (both perfect), so best-of-5 usually pays for all
    five. That buys the agent two or three turns. The same model's v2 calls were billed at a
    median 0.11 of list price on Baidu (18 calls), 0.61 on OpenInference (19) and 0.18 on
    StreamLake (3), list price counting every input token at the input rate (the ratio includes
    cache discounts as well as host prices): the same request costs about five times as much on
    one host as another. At list price a draw costs about $0.005, and best-of-1, 5, 10 and 20 cost
    $0.005, $0.021, $0.031 and $0.036, all below the $0.05 cap. Hence
    the revision in "Arms": list-priced spend, a frontier from one run per episode under a generous
    cap, one primary point, and a one-shot drift control. The runner's dry run prints the host
    table for each cell's model.
  - The runner revised to match, 2026-09-30: `infer.list_cost` prices a response at list with no
    cache discount, and `Client.converse` returns it with each turn; the graphs' dollar limit is
    on that figure, and each episode records every turn's cumulative spend, host, tokens and the
    latest draft after it. `scripts/agent_eval.py` runs the agent, the scripted loop and the
    one-shot control under `--cap-usd`, scores every distinct draft, and reports per cell the
    frontier at the spend of best-of-1, 5 (primary), 10 and 20: best-of-k's exact success, field
    success, spend and a bootstrap interval over the stored draws beside each arm's successes,
    Wilson interval, field successes, mean spend and unobserved episodes, and the control's rate
    against the stored pass@1. A dry run prints the same for any episodes the run id already has.
    Tests: best-of-k's success and spend against every order of the draws, reading an episode at
    a cap (including the unobserved cases), the one-shot control and its re-draw, and a run and its
    re-run. 17 tests in `tests/test_agent_eval.py`, 3 more in `tests/test_agent.py`, 1 in
    `tests/test_converse.py`.
  - So that the runner scores with the harness's own code without importing a sibling script, the
    targets, the corpus, stripping and the excerpt window, the synthesis prompt and the scorer
    moved verbatim from `scripts/conformance.py` to `permits/harness.py`, re-exported there. Checked
    on every page of Clark (57), St. Johns (14) and Santa Barbara (5): identical corpus,
    references, stripped pages, excerpts, scores and scorer self-checks before and after. The
    structure test now also forbids `permits/agent/` from importing `permits.harness`.
- 2026-09-30, step 4, smoke run `smoke-1` (exploratory, traced to `buildscope-agent-dev`):
  deepseek-v4-flash on Clark, 3 episodes per arm, $0.05 list-priced cap, 52 calls, $0.04 billed.
  Every turn was served by StreamLake, which cached 77-91% of each multi-turn episode's input.

  | arm | e00 | e01 | e02 |
  |---|---|---|---|
  | agent | perfect, not submitted | no draft | imperfect, not submitted |
  | scripted | perfect, 11 turns | perfect, 7 turns | perfect, 1 turn |
  | one-shot | imperfect | raised | perfect |

  - **The agent spent its cap exploring.** All three episodes stopped on the dollar limit after 11
    turns ($0.051-0.057 list, $0.007 billed each), none submitted. They spent 8-10 turns listing,
    searching and reading 8,000-character slices of 96,000-character pages, much of it the same
    grid region on pages that share one template. e00 ran its first draft on turn 11 (perfect,
    never checked); e02 ran drafts on turns 9 and 10 and checked on turn 11 (REJECT); e01 never
    drafted. A turn cost $0.002 at list with the 10,000-token prompt and $0.007 by turn 11 at
    36,000, since each turn re-sends the conversation and list price counts cached tokens in full.
    The agent was not told its limit, so nothing told it to hurry.
  - **The scripted loop submitted every time,** each after its check accepted, at $0.006-0.055
    list.
  - **The one-shot control was not fresh.** Its requests were identical to the scripted loop's
    first turns, and the conversation cache key held the run and episode but not the arm, so all
    three replayed those turns. Fixed: `Client.converse` keys on the arm too (test in
    `tests/test_converse.py`). The smoke run's one-shot row is the scripted loop's first drafts.
  - **The API paths.** 11-turn conversations with tools ran on OpenRouter with no request errors;
    whether reasoning details came back and were returned was not checked. The Anthropic path
    (thinking blocks sent back after a tool call) is still unverified.
  - **Changes, decided with the user.** The agent is told its budget (see "The agent"; tests in
    `tests/test_agent.py` that the line ends each turn's last result and that the scripted loop
    is not told), and the default cap is $0.15 list with a 30-turn limit, so the dollars bind
    first: about 20 turns at these prices. Lower caps are still read from the same episodes, as
    cut-offs for the agent ("Arms").
- 2026-09-30, smoke run `smoke-2`, run by the user: the same cell with the budget shown, a $0.15
  cap and the arm in the cache key; $0.07 billed per the ledger. The runner printed $0.17
  spent: two calls that died mid-stream (a scripted turn after 40 s, a one-shot call after
  1,217 s) are charged their worst case against the session's limit, and the ledger records
  them at $0 billed.

  | arm | e00 | e01 | e02 |
  |---|---|---|---|
  | agent | perfect, submitted, 10 turns, $0.063 | perfect draft, not submitted, 22 turns, $0.158 | perfect, submitted, 16 turns, $0.118 |
  | scripted | perfect, 13 turns, $0.075 | perfect, 2 turns, $0.008 | perfect, 14 turns, $0.083 |
  | one-shot | perfect, $0.007 | raised, $0.006 | raised, $0.006 |

  - **Told its budget, the agent drafted by turns 7-10** (smoke-1: 11 or never) and submitted
    twice. The one-shot control, now fresh, is 1/3, in line with the stored 0.10.
  - **It submitted modules it had not checked.** In e00 and e02 the check accepted a draft that
    returned no structure code or contractor, with the note that a column empty on every row is
    right only if the pages do not print it. The agent then changed the module and submitted the
    change without checking it again; both submitted modules were perfect. In e01 the note sent
    it on after an ACCEPT at turn 17, and the budget ran out at turn 22 with a perfect draft
    unsubmitted. Whether Clark's pages print those fields decides whether the note helps or
    only costs turns there.
  - **Read at the best-of-k points** the agent is 0/3 up to best-of-10's $0.031 and 1/3 at
    best-of-20's $0.036, as cut-offs; the scripted loop is 1/3 throughout. Only the agent's point
    at its own cap is not a cut-off: 3/3 perfect drafts at a mean $0.113 list, 2 submitted.

## What this does not establish

- **Anything about the agent yet.** Steps 1 and 2 are measured; everything after is a plan.
- **That a better agent result generalizes.** Three portals, two of them development targets, as in
  v2. The tool descriptions and the scripted loop's repair prompt are written while looking at Clark
  and St. Johns; Santa Barbara stays the held-out check, and more portals remain the main next step.
- **That matched cost is the only fair comparison.** An agent also costs wall-clock time and
  engineering effort, and a verifier good enough for best-of-k may make the agent unnecessary. Both
  outcomes are reported.
