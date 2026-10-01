# Pre-registration: the agentic extractor's evaluation run

Date:      2026-10-01
Produced:  Written by hand. Figures from `python spikes/heldout_selfcheck.py` (the held-back portals)
           and `scripts/agent_eval.py`'s `best_of_k` on the stored v2 draws. No model calls; cost $0.00.
Inputs:    [agentic extractor plan](2026-09-29-agentic-extractor-plan.md) (arms, tools, metrics),
           [v2 run results](2026-10-01-v2-run-results.md) (the cells the rule reads), `data/infer/variance.json`
Outputs:   none yet. The run will write `data/agent/` episode records under `eval-` run ids and the
           `buildscope-agent-eval` LangSmith project, and a results report that cites this one.
Status:    **Draft for the owner's review.** Becomes binding when approved, before any paid call it
           governs. Four choices are marked "to confirm"; nothing paid runs until they are settled.

## Questions

From the [plan](2026-09-29-agentic-extractor-plan.md), unchanged:

1. **Does a tool-using agent beat best-of-5 at best-of-5's spend?** (the plan's question 3; primary)
2. **Rescue:** does the agent produce a working extractor where the model's one-shot rate is 0?
3. **Does generic feedback do what the human hint did** on Clark?
4. **Does the agent's autonomy add anything over the scripted loop** at the same spend?

**A possible outcome, named in advance:** the scripted loop, a fixed draft-check-repair workflow,
matches or beats the agent at the same spend. In smoke-2 it got the same 3/3 as the agent at half the
spend. If that holds, the result is that the check does the work and the autonomy does not, and it is
reported as such.

## Models: the rule applied

The rule, decided 2026-10-01: v2 roster or re-run models with a v2 Clark hint cell, a purchase cost
of at most $0.03 per draw, hosts that list tool support at the lab's precision, and stored cells on
every target; two at Clark pass@1 = 0 and three with Clark pass@1 in (0, 0.7]; ties broken by the
lowest cost per draw. Applied to the finished v2 run:

| model | Clark pass@1 | $/draw | group | passed over in its group |
|---|---:|---:|---|---|
| gpt-oss-120b | 0/10 | 0.0005 | 0 | Gemini 3.5 Flash-Lite is next; then Qwen3 Coder 0.0045, Qwen3.5 Flash 0.0051, Hunyuan 3 0.0054, DeepSeek V4 Pro (Apr) 0.0121, Kimi K2 Thinking 0.0247 |
| Gemini 3.5 Flash-Lite | 0/10 | 0.0032 | 0 | |
| DeepSeek V4 Flash | 2/20 | 0.0006 | (0, 0.7] | none: exactly three qualify |
| GPT-6 Luna | 2/20 | 0.0015 | (0, 0.7] | |
| MiMo V2.6 Flash | 13/20 | 0.0045 | (0, 0.7] | |

Out by the cost limit: Claude Haiku 4.5 ($0.075) and GLM-5.2 ($0.047). Out for no hint cell: every
mid- and top-tier model (the top tier by design, the mid tier by the v2 run's cut 1). Every host admitted for these five lists tool support
(2026-09-27 endpoint snapshot). A model that calls tools badly is a finding, reported, not a reason
to swap it.

**To confirm: deepseek-v4-flash's hosts.** 13 of its 19 v2 draws served by OpenInference broke the
output contract, against none of 817 elsewhere ([failure cases](../design/failure-cases.md), case 10).
Proposed: `ignore` OpenInference for this model in every purchase this run makes, decided now,
before any draw, and reported as a routing change from v2.

## Targets

| target | role | stored v2 baseline draws | to buy |
|---|---|---|---|
| Clark County | development; the hint's portal; where all five have room | 10-20 per model | none |
| Santa Barbara | held out in v2 | 5 for three of the five | 10 for gpt-oss-120b and DeepSeek V4 Flash; 5 more for the other three |
| Polk County | held back in v2, never used | none | 10 per model |
| Oregon statewide | held back in v2, never used | none | 10 per model |

**To confirm: the target set.** St. Johns is left out: it is a development portal, the verifier's
row rule was fixed on it and Clark, and its empty-column note was written from its failures. Polk County and Oregon replace it as two more
held-out portals, so three of the four targets are held out.

**To confirm: 10 baseline draws, not 5.** Best-of-5 over a cell of 5 draws uses every draw, so its
success is close to 0 or 1 by construction: all three stored 5-draw Santa Barbara cells give 1.00.
Ten draws make the best-of-5 point a real reading. At these models' prices the 135 baseline draws
cost well under a dollar (about $0.30 at their v2 cost per draw).

**The instrument on the new portals** (`spikes/heldout_selfcheck.py`, 2026-10-01): 4 pages and 40
reference records each; the scorer's self-check passes on every page; the excerpt a model sees holds 4
of 10 (Polk) and 5 of 10 (Oregon) page-1 records; the verifier's grid-row count matches the reference
on all 8 pages, and its four checks pass on the reference's own output; no contract field is empty on
every reference row. Nobody has seen a model's output on either portal. Like Clark's, and unlike
Santa Barbara's, both excerpts show the small table nested in the grid's first row, the structure most
silently empty Clark extractors fail on ([v2 results](2026-10-01-v2-run-results.md), question 3).

## Arms and episodes

20 cells (5 models × 4 targets). Per cell:

| arm | episodes | limit | what it gives |
|---|---:|---|---|
| agent, told B5 | 10 | the cell's B5, list-priced | **the primary point** |
| scripted loop | 10 | $0.15 list | every cap exactly, B5 among them (it is never told its limit) |
| agent, told $0.15 | 10 | $0.15 list | the frontier; points below $0.15 are cut-offs, descriptive |
| one-shot control | 3 | one call | drift since the stored draws |

**B5** is best-of-5's expected list-priced spend per task on the cell's stored draws, computed exactly
(`agent_eval.best_of_k`), after the baseline draws above are bought and before any episode. On Clark:
gpt-oss-120b $0.0215, Gemini 3.5 Flash-Lite $0.0388, DeepSeek V4 Flash $0.0205, GPT-6 Luna $0.0151,
MiMo V2.6 Flash $0.0123.

Common to all: the v2 frozen prompt in the first turn; the turn limit 30; spend list-priced (every
input token at the input rate, no cache discount), with billed dollars beside it; `eval-` run ids, so
no response from a development run replays; the `check` tool without the empty-column note (removed
2026-10-01: it fired on every correct Clark and Santa Barbara module). **The outcome is the submitted
module only**; an episode that never submits fails, and its last draft is reported beside.

## Analysis

- **Primary (question 1).** Pooled over the 20 cells: the agent-told-B5 success rate minus best-of-5's
  success, the mean of the per-cell differences, with a 95% interval from a bootstrap that resamples
  episodes and stored draws within each cell. The agent beats best-of-5 only if the interval is
  above 0; it loses only if below. Per-cell points are reported, not tested.
- **Question 4,** the same pooled difference for the agent told B5 against the scripted loop read at
  B5, and for the scripted loop against best-of-5. The named outcome above holds if the scripted loop
  minus the agent is not below 0.
- **Question 2,** per cell at Clark pass@1 = 0 (gpt-oss-120b and Gemini 3.5 Flash-Lite on Clark): a
  rescue is one submitted perfect module in any paid arm, against 0 in 10 stored draws and 0 in 10
  hint draws. Reported as counts, not rates.
- **Question 3,** on Clark per model: the agent's submitted success at $0.15 against the v2 hint
  cell's pass@1, Newcombe interval, claimed only where it excludes 0; the spend of each beside.
- **Beside every rate:** field-level success (v2 deviation 4), Wilson intervals, billed spend, and
  the behaviour metrics of the plan (turns, checks before submit, submits after a failed check,
  stuck rate).
- **Drift:** if a cell's control draws pass at a rate whose interval excludes the stored rate, the
  cell is reported with that flag; the primary analysis is also given without it.

## Spend

List-priced worst case: 400 paid episodes at a $0.15 cap plus one turn of overshoot, about $70, and
200 at B5, about $10. Billed spend in smoke-2 was 0.12-0.19 of list on multi-turn episodes, which puts
the run near $10-15 billed, but the ratio depends on each model's hosts.

**To confirm with the cap: a run-wide spend limit of $25 billed,** enforced by `--max-spend` per
process with processes sized at typical cost plus one worst-case call. Cells run in this order, so a
stop loses what matters least: baseline purchases; the agent told B5 and the scripted loop on every
cell; the one-shot controls; then the agent told $0.15. If the projection after the first model
exceeds the limit, the $0.15 agent arm drops to 5 episodes per cell, then to Clark only.

Before the paid run, one development episode per model not yet run with tools (the four other than
DeepSeek V4 Flash, a few cents each), to check the tool-call round trip on each provider path; those
episodes are not evaluation data.

## What this does not establish

**Anything yet.** It fixes a plan and measures nothing.

**A general agent result.** Five cheap models and four portals of two vendors; a claim about agents
in general, or about frontier models, is outside it.

**A fair fight on every cell.** Where best-of-5 already succeeds every time, as on Santa Barbara for
three of the five, the agent can only tie; the pooled difference is weighted toward the cells with
room. Per-cell points show which.

**The value of autonomy beyond this budget.** The primary point is at best-of-5's spend, a few cents.
An agent may do better with more; the $0.15 frontier arm shows the trend, as cut-offs, not as an agent
given that budget from the start.
