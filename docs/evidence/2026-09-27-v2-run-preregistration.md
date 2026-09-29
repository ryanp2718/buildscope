# Pre-registration: the protocol v2 model comparison run

Date:      2026-09-27
Produced:  `python spikes/preregister_v2_run.py` (roster check, prompt and window hashes, cost
           projection); `python spikes/heldout_fetch.py` and `python spikes/heldout_review.py
           --check` (held-out target); `python spikes/fetch_roster_sources.py` (registry sources).
           Written before any protocol v2 draw was bought.
Inputs:    `data/audit/2026-09-27-openrouter-models.json`, `data/audit/2026-09-27-openrouter-rankings.html`,
           `data/audit/2026-09-27-roster-endpoints.json`, `data/audit/2026-09-27-roster-hf.json`,
           `data/audit/2026-09-27-roster-cards/`,
           `data/infer/ledger.jsonl`, `data/infer/model_stats.json`, `data/step1/manifest.csv`,
           `data/step1/heldout_review/*.csv` (the human review of the held-out references)
Outputs:   none yet. The run will write `data/infer/variance.json` cells keyed `|v2`, and a results
           report that cites this one.
Status:    Pre-registered; amended once before any draw and once after the smoke draws (see
           "Amendments"); smoke draws bought 2026-09-28, stage 1 started the same day. The plan
           below was fixed before the data existed; any change is reported in the results as a
           deviation, with its reason (see "Deviations during the run").

Step 6 of the order of work in the
[2026-09-26 fairness audit](2026-09-26-model-comparison-fairness-audit.md). The audit's decisions are
the policies this run is held to. Where this plan departs from one, the departure is listed under
"Departures from the audit's decisions". How the harness runs a cell is in
[the model comparison design doc](../design/model-comparison.md).

## Questions

1. **Capability under a fair configuration.** On Clark County, with every model at a 64,000-token
   output cap, its lab's default reasoning level, its model card's sampling settings and a host at its
   lab's precision, what is each model's pass@1 rate?
2. **Cost per success.** Does ranking models by cost per success differ from ranking them by price
   per token, across a roster that spans about 140 times in output price ($0.14 to $20 per million
   output tokens)?
3. **Generalization.** Do those rates carry over to a portal no prompt was written against?
4. **Configuration effects.** For the seven v1 models re-run under v2 with nothing else changed, how
   much of the v1 result was the configuration?
5. **The hint.** How much does the one-paragraph row-state hint change Clark pass rates, per model?

## Roster

**Rule.** Each lab's current generally available model at each tier of the lab's own lineup. Tier is
the lab's positioning, not a price band; price is the x-axis of the result. Preview, stealth,
`:free`, `:batch`, moving aliases (`~...-latest`) and task variants are excluded, and ids are pinned
where the lab publishes a dated one. `-pro` siblings at the same price as their base are excluded as
unexplained duplicates, and so are speed variants of the same weights (`-prime`, `-flashx`). Applied
to the OpenRouter catalogue snapshot of 2026-09-27.

| lab | top | mid | cheap |
|---|---|---|---|
| Anthropic | claude-opus-5.5 | claude-sonnet-5 | claude-haiku-4.5 |
| OpenAI | - | gpt-6-sol | gpt-6-luna |
| Google | - | gemini-3.8-flash | gemini-3.5-flash-lite |
| xAI | grok-4.7 | - | - |
| Moonshot | kimi-k3 | - | - |
| Z.ai | glm-5.3 | - | glm-5.3-flash |
| Qwen | qwen3.8-max-0902 | - | qwen3.8-flash |
| DeepSeek | - | deepseek-v4-pro-0813 | deepseek-v4.1-flash |
| Xiaomi | - | mimo-v2.6-pro | mimo-v2.6-flash |
| MiniMax | - | minimax-m3 | - |
| Tencent | - | - | hy3 |

19 models. The Anthropic models are called on Anthropic's API and every other model through
OpenRouter; the provider does not change the request policy. GLM-5.3 is Z.ai's top tier because Z.ai
positions it as its flagship; Z.ai has no mid-tier entry.

**Excluded, with reasons, all decided 2026-09-27:**

- **claude-fable-5.1 and gpt-6-astra**, the two $10 / $50 flagships: together about half the
  projected spend. So OpenAI has no top-tier entry, and Opus 5.5 is Anthropic's. The user's reason for
  accepting this is that Opus 5.5 scores broadly above Fable 5.1 on Artificial Analysis's benchmarks;
  that comparison was not checked here.
- **gemini-3.1-pro-preview**, Google's only Pro model: the rule excludes previews, because a preview
  id can change under a run. Google has no top-tier entry.
- **glm-5.3-prime and qwen3.8-max-prime**, the first top-tier picks for Z.ai and Qwen: the catalogue
  describes them as higher-throughput variants of glm-5.3 and Qwen3.8 Max (amendment 1).
- `spikes/preregister_v2_run.py` lists every other generally available model from a roster lab
  released since that lab's oldest pick, so a reader can check the rule was applied rather than
  picked around.

**The v1 models re-run under v2** (question 4): glm-5.2, deepseek-v4-pro, deepseek-v4-flash,
kimi-k2-thinking, gpt-oss-120b, qwen3.5-flash-02-23, qwen3-coder. **Opus 5 is not re-run**, for cost
(about $15 of the $20 this set would have cost).

## Targets: development and test

| target | split | corpus | records | synthesis window (page 1) |
|---|---|---|---:|---|
| `clarkco` | development | 57 pages | 561 | at char 59,000; 5 of 10 records |
| `stjohns` | development | 14 pages | 3,627 | at char 6,000; 83 of 173 records |
| `santabarbara` | **test** | 5 pages | 50 | at char 37,177; 6 of 10 records |
| `polkco` | test, **held back** | 4 pages | 40 | not run |
| `oregon` | test, **held back** | 4 pages | 40 | not run |

**Development targets** are Clark and St. Johns. The system prompt and the hint were written while
reading their pages and model output on them, so a pass rate on them measures fit to those portals as
well as capability.

**The test target** is Santa Barbara city. Same vendor as Clark (Accela), a different template: a
different column set and order, and rows in a state that has no detail page and a blank status (3
of 50; one of them partly inside the synthesis window). No prompt was written against it. Its search
form has no date filter, so its corpus is the most recent Residential Alteration records as of
2026-09-27, which are dated 2020 to 2024.

**Held back.** Polk County (a different column order) and Oregon statewide (a different template
family) are fetched and their references checked, but are not run. They are kept unspent as a clean
test for any prompt change the results of this run prompt.

**The held-out reference was checked** before this was written: a second parse sharing no code with
the adapter agrees on all 650 scored fields and every row count across the three test targets, and
a person checked the column chosen for each field on each portal, that every record row is counted,
and 29 rows against the rendered page (two per page drawn with a fixed seed, plus Santa Barbara's
three rows with no detail link). No disagreement.

**A harness fix found on the test target, before any model saw it.** The synthesis window on Santa
Barbara page 1 contained none of its records: its search form's layout rows outnumbered the grid
rows the window could hold. `window()` now falls back to starting at the grid's header when the
chosen window holds fewer than three rows of the grid's width. The fallback does not fire on any of
the 71 stored development pages, whose windows are byte-identical to before (checked against the
committed version), and it does not fire on Polk County or Oregon. It was designed after looking at
a test page's markup, which is disclosed here as a use of the test set; no model output on it
existed.

## The frozen prompt

Hashes are sha256 of the constants in `scripts/conformance.py`, and of page 1's window at 24,000
characters (first 16 hex digits):

| item | sha256 | size |
|---|---|---|
| `SYNTH_SYSTEM` (includes `CONTRACT`) | `60516d231c6036837bb6c1f6c79e2db9e6026888dd14ec23d6d739193c4484ad` | 2,832 chars |
| `CONTRACT` | `b82be963dbc039396558485de78bc1267a0dbbeb05fd8dd418fef8ed85a71a53` | 1,570 chars |
| `SYNTH_HINT` | `3ee6b1cab29d71a40060e1c966c90a8a350b00ca639aa7c7fbd760c6dd0eea17` | 419 chars |
| window, `clarkco` | `156e849de0f0aaed` | |
| window, `stjohns` | `f1f61740c7aefb6f` | |
| window, `santabarbara` | `cac4f1d07aadbceb` | |

None of these may change during the run. A cell whose recorded settings or prompt differ from these is
not part of this run.

## Cells and draws

| target | condition | draws per cell | models |
|---|---|---|---|
| Clark | baseline | two-stage: 10, then to 20 unless 0/10 or 10/10 | all 19 roster + 7 v1 |
| St. Johns | baseline | 10 | all 19 roster + 7 v1 |
| Clark | hint | 10 | roster below the top tier (14) + 7 v1 |
| Santa Barbara | baseline | 5 | all 19 roster |

**The two-stage rule** (a curtailed design): a Clark baseline cell buys 10 draws and stops if they
are 0/10 (Wilson 95% [0.00, 0.28]) or 10/10 ([0.72, 1.00]); otherwise it continues to 20. The stopping
rule depends only on the pass count, is fixed here, and the interval is computed as for a fixed n.
The v1 Clark rates predict about 13.7 draws per cell on average.

**Precision this buys**, stated so no claim outruns it:

- n = 10: a rate of 50% has a Wilson interval of [0.24, 0.76]; two models are distinguishable at
  about 50 points apart (Fisher exact: 10/10 against 5/10 gives p = 0.03; 9/10 against 5/10 gives
  p = 0.14).
- n = 20: 50% gives [0.30, 0.70]; 18/20 against 10/20 gives p = 0.014.
- n = 5 (Santa Barbara): 5/5 gives [0.57, 1.00] and 0/5 gives [0.00, 0.43]. Santa Barbara separates
  "passes reliably" from "fails reliably" and nothing finer.

**Draws that do not count.** An `infra_error` draw (the host failed twice) is left out of the rate
and retried by re-running the cell. A cell with more than 20% infra errors after one retry pass is
reported as unmeasured. A truncated draw is a harness failure: it is re-drawn at the model's
catalogue output limit (at most 128,000), and the count is reported.

## Success criteria

A draw **passes** if the generated module clears the static audit, raises on no page, and agrees with
the adapter on every record of every page of the target's corpus. Anything less fails.

**Primary, per cell:** pass@1, the pass rate over scored draws, with a Wilson 95% interval.

**Secondary, per cell:**

- **Near misses:** the share of failing draws with recall at least 0.98 at precision 1.0.
- **Cost per success:** mean cost per scored draw divided by the pass rate, with the interval from
  the Wilson bounds. Undefined (reported as such) at a pass rate of 0.
- Format failures (`no_code`, audit refusals) reported apart from extraction failures.
- Infra-error rate, truncation count, median time to first token, reasoning tokens, and the serving
  host, per model.

**How each question is answered:**

1. Clark baseline pass@1 per model, with intervals. No model is called better than another unless
   their intervals do not overlap.
2. Two rankings of the roster over the Clark baseline cells: by output price per token, and by cost
   per success. The claim "cost per success ranks differently from price" is supported if at least
   one pair of models is in the opposite order in the two rankings and its cost-per-success
   intervals do not overlap. Models at 0/n are placed last in the cost-per-success ranking, tied.
3. Santa Barbara pass@1 per roster model beside its Clark rate. Reported: the count of models that
   pass Clark reliably (lower bound at least 0.5) but fail Santa Barbara reliably (0/5), and the
   reverse; and the Spearman rank correlation between the two rates across the 19 models, with a
   bootstrap 95% interval. No threshold on the correlation is claimed in advance.
4. v2 minus v1 rate per v1 model on Clark and St. Johns, with Newcombe intervals. A configuration
   effect is claimed only where the interval excludes 0.
5. Hint minus baseline rate per model on Clark, Newcombe intervals, claimed only where the interval
   excludes 0. The hint is an ablation and never the headline condition. It was written from Clark
   failures and is evaluated on Clark, so a positive effect is an upper bound on what it would do
   elsewhere.

## Gates before and during the run

**Before any spend**, the code the plan depends on must exist and be tested:

- Done 2026-09-27: the two-stage rule in `run_variance` (`--cells target:model:10+10`,
  `permits.cells.curtail`), with tests.
- Done 2026-09-27: an Anthropic cache breakpoint on the user message, under v2 only, so a cell's
  identical window is billed at full price once and at a tenth after (a twentieth on Opus 5.5).
  The first draw's write bills at 1.25x, as the projection below assumes. Whether each draw after
  the first reads it is checked on the smoke draws, from `cache_read_input_tokens` in the ledger.
- Done 2026-09-27: the development/test split in `TARGETS`, the held-out targets, and the window
  fallback, with tests.
- Done 2026-09-27: registry entries for the 16 roster models not in it, set from sources snapshotted
  by `spikes/fetch_roster_sources.py` (endpoint listings, Hugging Face configs, cards and chat
  templates) and the labs' API docs. See "Registry settings" below.

**Registry settings.** Every entry follows protocol v2's rules: the lab's API default reasoning level,
the card's sampling (for a closed model with none published, nothing is sent, so the lab's default
applies), and hosts at or above the lowest precision the lab released. Four points a reader could
not infer from those rules:

- **Two departures from "the lab's default level"**, decided 2026-09-27. Hy3's default is no
  reasoning, and its card says to use `high` for coding; `high` is sent. MiniMax-M3's default is
  `adaptive` thinking, which OpenRouter's on/off switch cannot request; reasoning is switched on.
- **Opus 5.5's default effort is `medium`** on Anthropic's API (the OpenRouter catalogue says
  `high`), and adaptive thinking with no effort sent is that default.
- **Hosts excluded from routing:** OpenRouter endpoints whose output limit is below the 64,000 cap,
  since OpenRouter does not document routing around them. There are six: two for the v1 models
  (gpt-oss-120b has four and deepseek-v4-pro one) and one each for kimi-k3, deepseek-v4-pro-0813 and
  deepseek-v4.1-flash. The DeepSeek endpoints measured ignoring the effort setting on V4 are also
  excluded on the two newer DeepSeek ids, where they were not re-measured.
- **Lab hosts lost to `require_parameters`:** Moonshot's own Kimi K3 endpoint and Tencent's own Hy3
  endpoint list no sampling parameters, so requests carrying the card's sampling route to other hosts
  at the lab's precision or higher.

**Smoke draws.** Each roster model's first Clark draw is bought alone, before any cell is filled. It
is draw 0 of that model's Clark cell, so it is not paid for twice. A model enters the run only if its
smoke draw shows:

- OpenRouter accepted the `quantizations` filter and routed the 64,000-token request (no 4xx, a
  serving host recorded);
- usage and cost arrived in the stream's last chunk;
- the output was not truncated;
- for GLM models, non-zero reasoning tokens, since nothing else shows whether a third-party endpoint
  honours the effort sent. An endpoint that shows none is added to `provider.ignore` and the smoke
  draw is repeated.

A model that fails its gate after one fix is dropped and reported as not measured, with the reason.

## Funding, stages and the spend cap

Projected from the ledger's per-model output tokens where observed and 10,000 (typical) or 30,000
(heavy) where not; 16 of the 26 models have no ledger history, which is most of the uncertainty.
"Worst" charges every draw at the 64,000 cap and every two-stage cell 20 draws. Prices are the
catalogue's list prices; a request routed to a dearer host costs more, and the registry's price
ceilings, which bound every host a request can reach, are what `--max-spend` is enforced against.

| stage | billed by | typical | heavy | worst | running typical / heavy |
|---|---|---:|---:|---:|---|
| 1: cheap tier + v1 models | Anthropic | $0.94 | $1.42 | $14.53 | $0.94 / $1.42 |
| | OpenRouter | $5.10 | $11.02 | $33.82 | $6.04 / $12.44 |
| 2: mid tier | Anthropic | $1.38 | $1.97 | $29.07 | $7.42 / $14.42 |
| | OpenRouter | $9.58 | $24.52 | $58.09 | $17.00 / $38.94 |
| 3: top tier | Anthropic | $6.03 | $17.50 | $45.11 | $23.03 / $56.44 |
| | OpenRouter | $12.02 | $29.34 | $71.74 | **$35.05 / $85.77** |

Largest single models, typical: Opus 5.5 $6.03, kimi-k3 $5.56, gpt-6-sol $5.00, qwen3.8-max-0902
$2.56. The alternatives this plan was chosen from, typical / heavy (recomputed for the amended
roster): no hint arm $31.11 / $77.16; hint below the top tier with St. Johns two-stage $35.50 /
$87.09; that with St. Johns fixed at 10 $30.05 / $73.25; this plan $35.05 / $85.77.

**Staged funding.** Accounts are funded one stage at a time, and each stage runs with `--max-spend`
set to what remains of its allocation, so a heavy stage stops rather than overruns:

1. Smoke draws for all 19 roster models (projected $1.09 typical, $2.60 heavy; they are draw 0 of
   each Clark cell, so already inside the totals above), then stage 1. Fund about $3 Anthropic and
   $15 OpenRouter.
2. Re-project stages 2 and 3 from the measured smoke-draw tokens, which replace the assumed ones.
3. Stage 2, then stage 3, each funded to its re-projected heavy cost.

**The cap is $45 in total.** If a re-projection puts the run over it, cells are cut in this order
until it fits, and every cut is reported:

1. the hint arm on the mid tier;
2. the v1 re-runs of kimi-k2-thinking and glm-5.2, the two most expensive;
3. St. Johns for the top tier, from 10 draws to 5;
4. Clark for the top tier stops at 10 draws whatever the count.

Never cut: any roster model's first 10 Clark draws, and any Santa Barbara cell.

**Timing.** Draws within a cell run in sequence and cells run in parallel. With about eight processes,
stage 1 takes about 2 hours, stage 2 about 2 hours and stage 3 about 2 hours, each needing a
connection that stays up for its length.

## Departures from the audit's decisions

- **n per cell.** The audit's default is 20 draws on both targets. This run uses the two-stage rule
  on Clark, 10 on St. Johns and 5 on Santa Barbara, for cost; St. Johns is reported as a rate with its
  interval and not used to rank models closer than about 50 points.
- **The hint arm is not run on the top tier**, for cost. Question 5 is answered for 21 models, not 26.
- **No effort sweep.** The audit's low/high sweep for the cheap tier and one mid-tier model is not in
  this run, so each model is one point, not a frontier.
- **Held-out target.** The audit asked for a development/test split; the test target is one portal at
  n = 5, with two more held back.

## What this does not establish

**Anything yet.** This fixes a plan; it measures nothing.

**Generalization beyond one portal.** Santa Barbara is one Accela tenancy at 5 draws per model. A
model that passes it has passed one template it was not tuned on, not "unseen portals". Polk County
and Oregon are held back, so the run makes no claim about them, and no non-Accela portal is in the
test set at all. St. Johns is a different vendor but a development target.

**A clean test set.** The window fallback was designed after reading a test page's markup (disclosed
above), and the Santa Barbara corpus is a type-filtered, 2020-2024 sample chosen because the form
allowed nothing else. Neither involved model output, but both are choices made with the test page in
view.

**Accuracy.** Every pass rate is agreement with a hand-written adapter. On the test target that
adapter's output was checked by a second implementation and a person, on the development targets by
the earlier reconciliations; agreement is still not correctness against the jurisdiction's records.

**Fine distinctions between models.** At these n, two models are distinguishable only when their
rates are far apart (see "Precision this buys"). A ranking of models with overlapping intervals is not
a finding.

**The cost figures.** They are projections, 16 of 26 models' tokens are assumed, and the staged
funding exists because the heavy case is 2.4 times the typical one. Prices are the 2026-09-27
catalogue's.

**Vendor-neutrality of the prompt.** `SYNTH_SYSTEM` was developed against Claude's output (audit F7).
The test target controls for over-fitting to Clark; it does not control for a prompt written in one
lab's idiom.

## Amendments

**1. 2026-09-27, before any draw: the roster rule applied consistently.** While snapshotting the
registry sources, the two top-tier picks `z-ai/glm-5.3-prime` and `qwen/qwen3.8-max-prime` turned out
to be speed variants: the catalogue calls the first "the high-speed variant of Z.ai's GLM-5.3" and
the second "a higher-throughput variant of Qwen3.8 Max". The rule already excluded
`z-ai/glm-5.3-flashx` on the same grounds, so the first roster applied it inconsistently. Changed:

- Z.ai's top tier is `z-ai/glm-5.3`, moved from mid; Z.ai has no mid-tier entry. GLM-5.3 therefore
  loses the hint arm, which is not run on the top tier.
- Qwen's top tier is `qwen/qwen3.8-max-0902`, the dated snapshot of Qwen3.8 Max ($2 / $6 per million
  tokens, against $4 / $12 for the variant).
- The roster is 19 models, not 20; the hint arm covers 21 models, not 22; registry entries needed
  were 16, not 17.
- The projection falls from $42.02 / $102.12 to $35.05 / $85.77 (typical / heavy). Stage 1 is
  unchanged, so its funding is unchanged. The cap and cut order are unchanged.
- The Opus 5.5 cost uses its 0.05x cache-read rate, found on the pricing page the same day
  ($6.10 to $6.03).

Nothing else in the plan changed. No draw had been bought, and no model output was involved.

**2. 2026-09-28, after the smoke draws and before any other draw: how a cut-off draw is handled.**
"Draws that do not count" says a truncated draw is re-drawn at the model's catalogue output limit,
at most 128,000. The code for that did not exist and was not on the list of gates before spend, so
the smoke draws ran without it. Two smoke draws then showed the rule was underspecified: qwen3.8-flash
stopped on `max_tokens` at exactly 64,000 tokens with its code cut off, and grok-4.7 ran to 66,437
tokens and stopped on `end_turn` with a complete answer (deviation 1). This amendment was written
after seeing those outputs. It changes how cut-off draws are handled, not what is scored or how. Added:

- **What counts as truncated.** The provider's stop reason is `max_tokens`, or it gave no stop reason
  or an unrecognised one and the output used the whole cap. A natural stop (`end_turn`, a stop
  sequence, a refusal) is not truncation, whatever the token count. Before this, any draw at or over
  the cap was flagged, which is how grok-4.7's draw came to be.
- **The re-draw.** Once, under the same draw number, at the model's catalogue limit up to 128,000
  (`models.REDRAW_CAP`), in the same run. For Haiku 4.5 the catalogue limit is the cap, so there is
  nothing larger and a cut-off draw is scored as it stands; for the two Gemini models it is 65,536.
- **A re-draw cut off again** is scored as it stands, which in practice is a failure: the model did
  not finish within its own catalogue limit.
- **Cost.** Both attempts count toward the draw's cost, and so toward cost per success. The cut-off
  attempt's ledger row is joined to its draw (`truncated_output_tokens`), not left unclaimed.
- **Reported per model:** draws re-drawn, and draws still cut off after the re-draw. A re-drawn draw
  had up to twice the reasoning budget of the others, so a model with many re-draws had more budget
  than the one cap the protocol sets, and that is stated beside its rate.
- **Spend.** The per-cell worst case is still priced at the 64,000 cap. A re-draw is outside it and is
  checked against `--max-spend` before it is sent, like every call.

The one smoke draw this re-draws is qwen3.8-flash's, at 128,000. grok-4.7's draw is kept as scored.

## Deviations during the run

Departures from the plan made after draws began, each with the reason, decided before the affected
cell's result was used.

**1. 2026-09-28, smoke draws: a truncation flag not acted on.** `x-ai/grok-4.7`'s smoke draw billed
66,437 output tokens (62,866 of them reasoning) against a `max_tokens` of 64,000, so xAI does not
hold the model to the cap. The harness marks any draw at or over the cap as truncated whatever the
provider's stop reason, and the plan re-draws a truncated draw at the catalogue limit. This draw
stopped on `end_turn` and its extractor agreed with the adapter on every page, so the flag is a
false positive from the overrun, not a cut-off answer. The draw is kept and scored. Reported: the
count of grok-4.7 draws over the cap and by how much, since a model allowed past the cap has had
more reasoning budget than the rest. Amendment 2 changes the harness so a natural stop past the cap
is not flagged, which makes this the rule rather than an exception.

**2. 2026-09-28, stage 1: streams the host closed early were scored as model failures.** Eight
`z-ai/glm-5.3-flash` calls ended with a usage block and no finish reason, mid-reasoning, at 301 s
on AtlasCloud (2 of its 2 calls) and at 602 s on Phala (6 calls; Phala also completed calls of
1,118 s and 1,702 s, so its cut is not a fixed per-request limit). OpenRouter's own generation
record agrees for the first seven, checked: `native_finish_reason` null, `cancelled` false, generation time 301.0
s or 601.3-601.6 s, and no reasoning-token count. The model had not reached its answer, so the text
was empty and the harness scored `no_code`, a model failure: draws 0, 1, 8 and 9 of the Clark hint
cell, and draws 4, 5, 6 and 7 of the Clark baseline cell. The harness only treated a stream as failed
when it ended without choices, without usage, or on an `error` finish, and `truncated()` reads a
missing stop reason as truncation only when the whole budget was used.

This is not a model result, and dropping the draws would not fix it either: 8 of glm-5.3-flash's
21 v2 calls to that point were cut, all of them long-reasoning calls, so either reading biases the
model's rate. Found by looking into the no-code draws after the hint cell's result (5/10) was seen;
the rule below is decided on the stop reason and token count alone, not on any draw's outcome.

- **The rule.** A stream with no stop reason and fewer output tokens than the cap is a host
  failure (`infer.cut_by_host`): retried once under the same draw number, then recorded as
  `infra_error` and left out of n, like any other host failure. Its ledger row is a failure row
  that carries the charge the host reported, since the tokens were billed, and `model_stats`
  reports that spend per model as `usd_failed_calls`, outside `usd_total`. With the whole budget
  used, a missing stop reason is still truncation (amendment 2).
- **Cached copies.** A response cached before the rule existed that meets it is not replayed under
  v2; the draw is bought again. v1 replays are unchanged, so no published v1 figure moves.
- **Routing.** glm-5.3-flash no longer routes to AtlasCloud or Phala. Without that, a draw's retry
  lands on the same hosts and about one draw in seven would fail twice, and those would be the
  longest-reasoning draws. The routing is part of the request, so every glm-5.3-flash v2 draw
  misses the cache: **all of them are re-bought under the new routing**, the smoke draw included,
  and the earlier draws are superseded rather than pooled, so the model's cells are one routing
  policy. Their records are kept, and the superseded Clark cells are reported beside the
  replacements. Cost of the re-buy: about $1.
- **Other models.** The stage 1 processes already running keep the old code. Before stage 1's
  results are used, the ledger is searched again for calls with no stop reason under the cap; any
  such draw on another model is re-bought by the same cache rule, and the count per model and host
  is reported. At the time of writing there were none: of 521 successful calls in the ledger, 8
  had no stop reason, 7 of them these, and the other (2026-09-24) is not a scored draw; the eighth
  glm-5.3-flash cut came after.
- **The v1 comparison (question 4).** One published v1 draw has the older form of the same
  problem: draw 7 of the v1 `clarkco|moonshotai/kimi-k2-thinking` cell stopped on a host `error`
  finish after 13.7 s and was scored `no_code`, from a client that did not yet treat that as a
  host failure. The v1 cell is left as published; question 4 reports kimi-k2-thinking's v1 rate
  both as published and with that draw left out.

**Operational, not a deviation.** The first smoke run was stopped by the host for low memory during
`qwen/qwen3.8-max-0902`'s draw, after 11 of 19 models. The re-run replayed those 11 from the cache
at no cost. OpenRouter's usage rose $0.04 more than the ledger records, which is the interrupted
generation: it has no ledger row or response id, so it is not reconcilable.
