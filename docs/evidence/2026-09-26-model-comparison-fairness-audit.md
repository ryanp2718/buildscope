# Model-comparison fairness audit: the harness measures configuration as well as capability

Date:      2026-09-26
Produced:  `python spikes/audit_model_fairness.py`, plus a code read of `permits/infer.py`,
           `scripts/conformance.py` and `tests/` at `519d260` with the uncommitted working tree
           of that date. OpenRouter snapshots fetched 2026-09-25 with
           `curl -s https://openrouter.ai/api/v1/models` and
           `curl -s -A "Mozilla/5.0" https://openrouter.ai/rankings`.
Inputs:    `data/infer/ledger.jsonl` (260 rows, last written 2026-09-26T14:57:31Z),
           `data/infer/variance.json` (22 cells),
           `data/audit/2026-09-25-openrouter-models.json` (458 models),
           `data/audit/2026-09-25-openrouter-rankings.html` (weekly top 20, dated 2026-09-24)
Outputs:   stdout only; no artifact written
Status:    Current. Qualifies [2026-09-25 open-weight model axis](2026-09-25-open-weight-model-axis.md).

## Question

Is the cross-vendor model comparison in the 2026-09-25 report a fair test, in the roster chosen, in
how each model is configured, and in how the results are reported? And if it is not, what has to
change before the next paid run?

## Method

A read of the request path end to end: how each provider's request is built, what caps and
reasoning settings each model receives, how failures are classified, and how cells are aggregated.
Each suspected asymmetry was then checked against the ledger and the variance cells, and each
model's capabilities against OpenRouter's catalogue. The roster was compared against OpenRouter's
catalogue and its weekly usage rankings. Every figure below is printed by the producer script.

Not done: no model was called. Nothing here re-measures a pass rate; it measures the conditions the
existing pass rates were measured under.

## Result

The bias does not run one way. Some findings favour Anthropic, some favour the open-weight models, and
some are too uncontrolled to sign. The table records the direction of each.

| id | finding | favours |
|---|---|---|
| F1 | Unequal output ceilings: 12k for Claude including thinking, 48k for OpenRouter reasoning models | open-weight reasoning models |
| F2 | gpt-oss-120b and qwen3.5-flash reason but get no reasoning configuration | Claude |
| F3 | Reasoning effort differs by vendor and is not recorded | unknown |
| F4 | OpenRouter hosts chosen by price, quantization unconstrained, host not logged | Claude |
| F5 | The 900 s timeout is not a wall-clock bound; a timeout stops the whole cell | unknown, likely against slow reasoning models |
| F6 | Sampling parameters on OpenRouter are whatever each host defaults to | unknown |
| F7 | The prompt was developed against Claude's output; the hint was derived on the test target | Claude |
| F8 | Cell sizes differ by up to 20x | overstates Opus 5 |
| F9 | The roster compares Claude's frontier tier with other vendors' budget tier | Claude |
| R1 | The 2026-09-25 report says only Opus 5 solves Clark; five other models have | Claude |

### F1. The ceiling fix was applied to one provider

`ceiling_for` (`permits/infer.py:227`) adds `REASONING_HEADROOM = 32000` on top of the answer budget
for models in `OPENROUTER_REASONING`. Claude's thinking still comes out of the answer budget:
adaptive thinking on Opus and Sonnet shares `max_tokens`, and Haiku's `budget_tokens` is half of it
(`infer.py:653-664`). At the settings the published cells ran at, that is 12,000 tokens in total for
Claude and 16,000 + 32,000 = 48,000 for an OpenRouter reasoning model.

| cell | answer budget | ceiling on the wire | output tokens, max |
|---|---:|---:|---:|
| clarkco, Opus 5 | 12,000 | 12,000 | 10,177 |
| clarkco, kimi-k2-thinking | 16,000 | 48,000 | 26,340 |
| clarkco, deepseek-v4-pro | 16,000 | 48,000 | 42,386 |
| clarkco, deepseek-v4-flash | 16,000 | 48,000 | 41,680 |

Opus 5 used 85% of its ceiling on its largest draw, and an earlier Opus call stopped at exactly
8,000 (2026-09-21T15:42:43Z). kimi-k2-thinking's two perfect Clark draws used 19,793 and 20,691
tokens, more than Claude's entire allowance. The 2026-09-25 report describes the mismatch as a 33%
larger answer budget; measured as total ceiling it is 4x.

48,000 is also close to binding: two deepseek draws reached 41,680 and 42,386.

### F2. Two reasoning models are configured as non-reasoning

OpenRouter's catalogue lists `reasoning` in `supported_parameters` for both `openai/gpt-oss-120b` and
`qwen/qwen3.5-flash-02-23`. Neither is in `OPENROUTER_REASONING` (`infer.py:197`), so neither is sent a
reasoning setting and neither gets headroom. `tests/test_providers.py`
(`test_a_non_reasoning_model_is_untouched`) asserts that this is correct.

qwen3.5-flash averages about 11,000 output tokens per Clark draw and one call stopped at its 8,000
ceiling. gpt-oss-120b ran at whatever effort the serving host defaults to, 1,139-2,197 tokens per
Clark draw. Both are in the "0 of 60 on Clark" figure.

### F3. Reasoning effort is not controlled and not observable

- OpenRouter reasoning models get a top-level `reasoning_effort: "medium"` (`infer.py:719`).
  OpenRouter's reasoning documentation describes only the `reasoning: {effort}` object, so whether the
  top-level form is honoured is unverified.
- Opus and Sonnet get adaptive thinking at the API's default effort, and Haiku 4.5 gets a fixed
  budget.
- `_usage_from_chat` discards `completion_tokens_details.reasoning_tokens` (`infer.py:519-528`), so the
  ledger cannot show whether any setting took effect.

### F4. OpenRouter picks the host, and the ledger does not say which

With no `provider` object, OpenRouter load-balances weighted by inverse square of price, so the
cheapest hosts serve most requests. Without a `quantizations` filter those may be serving
lower-precision copies of the model. Without `require_parameters: true`, a host that ignores the
reasoning or sampling settings stays eligible. The response names the serving host, and
`_error_detail` already reads that field, but the ledger does not store it. Draws in one OpenRouter
cell are therefore not guaranteed to be one condition, which the 2026-09-25 report notes and which is
fixable.

### F5. Timeouts

`TIMEOUT_S = 900` is passed to both SDKs as a single float. That is an httpx timeout applied to each
network operation, not to the request as a whole, and the ledger shows it does not bound wall time:

| call | seconds | output tokens |
|---|---:|---:|
| deepseek-v4-flash, clarkco draw 1 | 1,341 | 31,986 |
| deepseek-v4-flash, clarkco draw 2 | 1,420 | 30,648 |
| deepseek-v4-flash, clarkco draw 3 | 2,802 | 41,680 |
| deepseek-v4-flash, clarkco draw 4 | 65,161 | 5,434 |

The last row spans the night of 2026-09-25 and most likely includes the machine sleeping; nothing in
the ledger can tell. The OpenRouter path does not stream, so a slow host holds one open request for
the whole generation.

When a call does fail, `run_variance` records the draw as `not_attempted` and breaks out of the cell
(`scripts/conformance.py:1003-1010`). A budget refusal, a revoked key, a host error and a timeout are
therefore one outcome. The cell stops early and the draw leaves the denominator. The SDKs also retry
timeouts automatically (`MAX_RETRIES = 5`), and a retried long generation may be billed again.

### F6. Sampling

Claude with thinking runs at temperature 1.0, the only value the API accepts. OpenRouter requests send
no sampling parameters, so each draw runs at the serving host's default. Hosts differ, so draws in one
cell may not share a temperature, and the value is not recorded.

### F7. The prompt

`SYNTH_SYSTEM` was developed against Claude's output, and the 2026-09-25 report says so. `SYNTH_HINT`
was written after observing Clark failures and is evaluated on Clark: test-set contamination if it is
ever read as a headline condition. Output-format tolerance was a real bias until 2026-09-24
(`extract_block` took the first fenced block) and is fixed.

### F8. Cell sizes

Baseline Clark cells range from n = 3 (Opus 5, and glm-5.3-flash until it was completed to 10 on
2026-09-26) to n = 20. Opus 5 has no St. Johns cell. The St. Johns reasoning cells have n = 1-2 and were drawn at the old 16,000 ceiling. 3 of 3 has
a 95% Wilson interval of [0.44, 1.00], so "Opus 5 solves Clark" is supported and "only Opus 5 solves
Clark reliably" is not.

### F9. The roster

The Anthropic side is three current frontier-tier models, $1-5 per million input tokens. The other
side is mostly budget models, several over a year old, and no closed model from OpenAI, Google or
xAI appears at all.

| tier | Anthropic | everyone else |
|---|---|---|
| top | Opus 5 ($5 / $25) | none |
| mid | Sonnet 5 ($2 / $10) | glm-5.2, deepseek-v4-pro (about $0.65 input) |
| cheap | Haiku 4.5 ($1 / $5) | qwen3-coder (2025-07), gpt-oss-120b (2025-08), kimi-k2-thinking (2025-11), qwen3.5-flash, glm-5.3-flash, deepseek-v4-flash |

"Only the most expensive model solves Clark" and "only Claude solves Clark" cannot be told apart,
because no other vendor was tested at the top tier. The Anthropic side is not current either: Opus 5.5
(2026-09-22, $4 / $20) is newer and cheaper than Opus 5, and Fable 5.1 ($10 / $50) sits above both.

What OpenRouter's users actually run, by share of tokens in the week dated 2026-09-24 (all
categories; the programming view is rendered client-side and is not in the snapshot):

| model | share |
|---|---:|
| z-ai/glm-5.3-flash | 17.9% |
| deepseek/deepseek-v4.1-flash | 17.8% |
| tencent/hy4-preview | 11.6% |
| openai/gpt-5.6-luna | 8.2% |
| deepseek/deepseek-v4-flash-0731 | 7.8% |
| xiaomi/mimo-v2.5 | 4.6% |
| z-ai/glm-5.3 | 3.0% |
| google/gemini-3.8-flash | 2.0% |
| openai/gpt-5.6-sol | 1.6% |
| z-ai/glm-5.2 | 1.6% |
| anthropic/claude-sonnet-5 | 1.4% |
| minimax/minimax-m3 | 1.4% |

Usage volume reflects price as much as quality, so this list shows what is in production, not what
is best.

### R1. A reporting error in the 2026-09-25 report

That report states that every model except Opus 5 misses Clark's pending-permit row class, and lists
kimi-k2-thinking at 0 of 2. The same claim appears in the `SYNTH_HINT` comment
(`scripts/conformance.py:191`) and the `tests/test_hint.py` docstring. The baseline cells in
`variance.json` as of this report:

| model | Clark perfect / n |
|---|---:|
| Opus 5 | 3 / 3 |
| glm-5.3-flash | 2 / 3 |
| kimi-k2-thinking | 2 / 10 |
| Sonnet 5 | 2 / 12 |
| deepseek-v4-flash | 1 / 10 |
| Haiku 4.5 | 1 / 20 |

kimi's two perfect draws are the two that used about 20,000 tokens, which only the raised ceiling
allowed. glm-5.3-flash, the cheapest model on the roster at $0.045 per million input tokens, solved
Clark on 2 of its 3 draws (2 of 10 once completed on 2026-09-26). The report's headline table also
omits every reasoning-tier open-weight cell. None of its tables are pinned by `tests/test_artifacts.py`, although its front matter says it
is pinned by tests, which is how the stale figures survived.

### Code quality

- **Type coverage.** 1 of about 231 functions in `permits/` and `scripts/` has a return annotation,
  and CI runs no type checker. The SDKs return typed response objects that are converted to plain dicts
  immediately (`infer.py:519`, `infer.py:902`). Every later read is `.get("field", 0) or 0`, so a
  misspelled field reads as zero instead of raising: the silent-wrong-number failure this project
  exists to catch.
- **Model facts are spread across seven places.** `PRICES`, `OPENROUTER_PRICES`,
  `OPENROUTER_REASONING`, `ADAPTIVE_THINKING`, `OPENROUTER_FREE`, the slash test in `provider_for`,
  and `short_model`. F2 is a direct consequence: capability is a hand-kept set rather than a field on
  the model.
- **Mutable run configuration.** `run_cells` overwrites `args.synth_model` and `args.draws` and does
  not restore them (`scripts/conformance.py:1167-1191`), and the argparse namespace is threaded into
  helpers such as `synth_system(args)` and `cell_key(..., args)`.
- **Filename bug on Windows.** `short_model("openai/gpt-oss-120b:batch")` keeps the colon. On NTFS,
  `stjohns_gpt-oss-120b:batch_d00.py` writes an alternate data stream of a file named
  `stjohns_gpt-oss-120b`, not a file. `test_short_model_is_filename_safe` checks only for `/`.
- **Non-atomic cache writes.** `_store` (`infer.py:638`) writes the response file in place. A crash
  mid-write leaves truncated JSON that fails to load every time that key is hit afterwards.
  `cached()` and `Ledger.rows()` also leave file handles open.
- **The price ceiling is already too low for the two newest models.** The reconciliation test in
  the working tree (`test_no_paid_call_billed_more_than_the_table_projected`) fails on 4 paid rows
  from 2026-09-25: glm-5.3-flash billed 1.67x its ceiling-table projection, and deepseek-v4-flash
  1.20-1.21x on three long reasoning draws. Their margins were guessed from sibling models before any
  paid call, as the comment beside them says. The budget guard therefore under-authorized those
  calls. Re-derived from the ledger on 2026-09-26. The deepseek-v4-flash excess is routing, not
  reasoning: its three slow draws billed 4.7-4.8x list and the other twelve 1.00x, which fits a
  different upstream. The host is not logged, so that cannot be confirmed.
- **The roll-up pooled conditions and over-counted spend.** `scripts/model_stats.py` grouped cells
  on (target, model), so the hinted draws merged into their baselines (glm-5.2 read 1/15 instead
  of 0/10 and 1/5). Its cost figure summed every variance call a model had made, including draws
  bought under the old 16,000 ceiling and one draw bought twice. Fixed 2026-09-26: cells are
  (target, model, condition), and a cell's cost is joined from the ledger row that bought each of
  its draws.
- **Concurrent runs are unguarded.** Two processes ran the glm-5.2 Clark cell at once on
  2026-09-25. Both paid for draw 1, `variance.json` recorded one response and the cache kept the
  other, so the cell no longer replayed to its own record. `variance.json` is read-merge-written
  with no lock. The cell was re-scored from the cache on 2026-09-26: draw 1 moved from `raised` to
  the common near miss, and the rate stayed 0/10. Step 4 adds the lock.
- **Generated code is not sandboxed.** The AST check is a denylist and can be bypassed, for example
  with `getattr` on builtins or by walking `object.__subclasses__()`. Generated modules run as the
  local user with network access. That was tolerable with one vendor; it is less so with a dozen,
  some served by hosts nobody here has vetted.

## What this establishes

- The published cross-vendor comparison mixes capability with configuration: ceiling, reasoning
  setting, serving host and sampling all vary by vendor, and several of them are not recorded.
- The claim that only Opus 5 solves Clark is contradicted by the project's own variance cells.
- The roster cannot separate vendor from price tier, because no non-Anthropic model was tested at
  the top tier.

## Decisions for the remediation

These are the policies the next paid run is held to. Once a policy is implemented it moves into
`docs/design/` as a description of how the harness works, and this report stays the dated record of
why.

**Reasoning: cap the output generously for every model; leave the effort control alone.** Vendors
expose incomparable controls: effort levels (Opus and Sonnet 5, gpt-oss and GPT), a token budget
(Haiku 4.5), an on/off switch (Qwen 3.x, GLM), or reasoning that is always on (kimi-k2-thinking,
DeepSeek v4). "High" on one is not "high" on another, and an equal token budget is not equal either,
because tokenizers and efficiency differ. The experiment measures cost per success, so a model's
reasoning spend is already charged to it. The unfair part is only an arbitrary cap cutting it off.
So:

- Every model runs with reasoning on, at the vendor's default effort. The setting lives in the
  model registry and every call records it.
- Where the only control is a token budget, the budget is set high enough never to bind.
- Every model's cap is the lower of its catalogue `max_completion_tokens` and 64,000, Claude
  included.
- Truncation rate must be zero. A truncated draw is a harness failure, not a model failure: the cell
  is rerun at a higher cap, and the count is reported.
- Reasoning tokens and visible tokens are logged separately.
- Effort becomes its own axis only where a sweep is cheap: low and high for the cheap tier and for
  one mid-tier model, in cells labelled `model@effort`. Results are reported as each model's best
  point on a pass-rate versus cost-per-success frontier.
- The existing 12,000-token Claude cells are kept and labelled with the cap they ran under.

**Timeouts.**

- Stream on the OpenRouter path, with `stream_options={"include_usage": True}` so usage and cost
  still arrive. `stream` is passed to the SDK call, never put in the request body, so it stays out of
  the cache key.
- Use `httpx.Timeout` with a short connect timeout and a gap-between-chunks timeout of about 120 s.
  A wall-clock limit is enforced by the harness itself, not by the SDK.
- Retry only before the first token arrives.
- Errors are split three ways. Budget, authentication and credit errors stop the run. Timeouts and
  host errors are retried once under the same draw number, then recorded as `infra_error`. Neither
  kind stops the cell.
- Infrastructure error rate is reported per model beside the pass rate, not folded into it. Time to
  first token and tokens per second are recorded.

**Prompt.**

- `SYNTH_SYSTEM` is frozen, and its hash is stored on every cell.
- Targets are split into development and test sets. Prompt changes are made against development
  targets only.
- `SYNTH_HINT` is an ablation run on every model and is never the headline condition.
- Format failures (`no_code`, contract violations) are reported separately from extraction failures.
- One smoke draw per model is a required gate before any spend.
- A per-model tuned prompt is a separate study and is out of scope.

**Sampling.**

- Each model's registry entry carries the model card's recommended temperature and top_p, or the API
  default where the card gives none.
- They are sent explicitly on every request, because on OpenRouter "default" varies by host, with
  `require_parameters: true`, and recorded on every row.
- Claude with thinking stays at 1.0. Temperature 0 is not used.

**Routing.**

- Every OpenRouter request carries `provider: {require_parameters: true, quantizations: ["bf16",
  "fp8"]}`.
- The serving host is logged on every row, and results are split by host after the run.
- Pinning one host per model with `only` is more comparable but fails whenever that host is down, so
  it is not the default.

**Roster.**

- The rule is the latest dated snapshot per lab per price tier. Preview, stealth and `:free` models
  are excluded, and ids are pinned (`deepseek-v4-flash-0731`, not the moving alias).
- Every model gets the same n on both targets, 20 draws per cell unless the pre-registration says
  otherwise.
- The candidate roster, from the catalogue snapshot, input / output $ per million tokens:

| tier | Anthropic | OpenAI | Google | xAI | open-weight |
|---|---|---|---|---|---|
| top | claude-opus-5.5 (4 / 20) | gpt-6-sol (2 / 10) | gemini-3.1-pro-preview (2 / 12) | grok-4.7 (1.6 / 4.8) | kimi-k3 (3 / 15), glm-5.3-prime (2.8 / 8.8), qwen3.8-max-prime (4 / 12) |
| mid | claude-sonnet-5 (2 / 10) | - | gemini-3.8-flash (0.75 / 3.75) | - | glm-5.3 (1.4 / 4.4), deepseek-v4-pro-0813 (0.35 / 1.04), minimax-m3 (0.3 / 1.2) |
| cheap | claude-haiku-4.5 (1 / 5) | gpt-6-luna (0.1 / 0.5) | gemini-3.5-flash-lite (0.3 / 2.5) | - | glm-5.3-flash, deepseek-v4.1-flash, qwen3.8-flash, mimo-v2.6-flash |

Haiku 4.5 is from 2025-10 and has no successor, so at the cheap tier the age gap now works against
Anthropic.

**Reporting.**

- Evidence tables for model cells are generated from `variance.json` or pinned by
  `tests/test_artifacts.py`.
- A model result is reported as pass rate, recall and precision, and cost per success together.

### Order of work

| step | work | spends money |
|---|---|---|
| 1 | Model registry (`ModelSpec`: provider, pinned id, tier, prices, reasoning control and default, sampling, release date) replacing the seven scattered tables; frozen dataclasses for `Usage`, `Completion`, `LedgerRow`, `DrawRecord`, `CellSpec`, `RunConfig`; outcomes as a `StrEnum`; a type checker in CI, ratcheted file by file from `permits/infer.py` | no |
| 2 | Streaming on OpenRouter, `httpx.Timeout` plus a wall-clock limit, the three-way error split, `infra_error` outcome, latency fields | no |
| 3 | Reasoning, sampling and routing policies above, driven by the registry; `reasoning_tokens` and serving host in the ledger. (Ceiling rates for glm-5.3-flash and deepseek-v4-flash: done 2026-09-26.) | no |
| 4 | `short_model` strips `:`; atomic cache writes; a lock on `variance.json`; closed file handles | no |
| 5 | (Done 2026-09-26: R1 corrected in the report, the code comment and the test docstring; the report's cells pinned in `tests/test_model_stats.py`.) | no |
| 6 | Pre-register roster, prompt hash, development/test split, n per cell and success criteria; dry-run the cost projection; then run | yes |
| 7 | Run generated extractors in a container with no network | no, deferred |

## What this does not establish

- **No model was re-measured.** Every finding is about the conditions the existing numbers were
  measured under. Whether fixing them moves any pass rate, and in which direction, is unknown until
  step 6 runs.
- **The directions in the findings table are about how each condition pushes, not how far.** No
  finding here has been shown to change a result. F1, for instance, may matter to Opus 5 on Clark or
  may not.
- **The rankings are one week of all-category usage.** Coding share may differ, and token volume
  measures price and adoption, not quality.
- **The catalogue is a 2026-09-25 snapshot.** Prices, availability and "latest" all move. The
  candidate roster must be re-read from a fresh snapshot at pre-registration.
- **F4 is a risk, not an observation.** No draw has been shown to come from a quantized host, because
  the ledger does not record the host. That missing record is the finding.
- **The long wall times in F5 are unexplained.** The 65,161 s row most likely includes the machine
  sleeping, and the ledger cannot tell a slow host from a sleeping client.
- **The candidate roster is not a recommendation of any model.** It is a coverage rule applied to a
  catalogue.
- **Agreement is still not accuracy.** Every pass rate cited here is agreement with a hand-written
  adapter, exactly as in the report it qualifies.
