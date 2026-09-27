# Model comparison

A living document: how the cross-vendor extractor-synthesis comparison is run today, what each model
is sent and why, and a dated log of what changed. Measured numbers live in the linked evidence
reports; this document says where they came from and does not restate them.

## What is compared

A **variance cell** is *k* independent draws of one identical synthesis request, for one target
portal, one model and one condition. Each draw asks the model for an extractor, runs it on every page
of the target's stored corpus, and scores it against the hand-written adapter. A draw passes only if
it clears the static audit, raises on no page, and agrees with the adapter on every record of every
page. The cell reports the pass rate (pass@1) with a Wilson 95% interval. Draws the host failed on
twice are `infra_error` and are reported beside the rate, not inside it. That rate is agreement
with an adapter, not accuracy.

- Code: `run_variance` in `scripts/conformance.py`; `scripts/model_stats.py` rolls every cell into
  `data/infer/model_stats.csv` and `.json`.
- A cell's key is `target|model[@effort][|hint][|v2]`, in `data/infer/variance.json`; its extractor
  files carry the same condition suffix. Two conditions never share a key, a file or a pool.
- Run: `python scripts/conformance.py --run --cells clarkco:z-ai/glm-5.2:10` (dry run without
  `--run`, which prints the worst case the budget will authorize).

## Request policy

The cache key is the SHA-256 of the request body, so any change to what is sent is a new request.
The policy is therefore versioned (`models.Protocol`) rather than edited in place.

- **Protocol v1** is the shape every cell before 2026-09-26 ran under, frozen so those cells still
  replay: `--protocol v1`. Answer budgets of 12,000–16,000 tokens, 32,000 tokens of headroom for
  the five OpenRouter models sent `reasoning_effort: "medium"`, no sampling or routing parameters.
- **Protocol v2** is the default:
  - **One cap**: 64,000 output tokens for every model, reasoning included, nothing on top.
  - **Reasoning at the lab's default level**, sent explicitly. Where OpenRouter's name for a level
    differs from the lab's, the registry records both (`ModelSpec.levels`).
  - **Sampling** from the model card, else the catalogue's `default_parameters`, else 1.0 / 1.0.
    Claude with thinking runs at the 1.0 the API fixes.
  - **Routing** on OpenRouter: `require_parameters`, host precision at or above the lowest
    precision the lab released (`quantizations`), and endpoints measured ignoring the effort setting
    excluded (`ignore`).
  - **Transport**: every call streamed; 120 s read timeout between chunks; a wall-clock limit of
    300 s plus the cap at 10 tokens per second. A host failure is retried once under the same draw.

### Per-model settings under protocol v2

| model | reasoning sent | lab level | temperature / top_p | host precision | endpoints excluded |
|---|---|---|---|---|---|
| claude-opus-5, claude-sonnet-5 | adaptive thinking | API default | 1.0 (fixed) | Anthropic | – |
| claude-haiku-4-5 | thinking, budget 48,000 | – | 1.0 (fixed) | Anthropic | – |
| qwen3.5-flash | `enabled` (no levels) | – | 0.6 / 0.95 | fp8+, and `unknown` (Alibaba is the only host) | – |
| gpt-oss-120b (and `:batch`) | `effort: medium` | medium | 1.0 / 1.0 | fp4+ | – |
| qwen3-coder | none; does not reason | – | 0.7 / 0.8 | fp8+ | – |
| kimi-k2-thinking | `enabled` (no levels; always reasons) | – | 1.0 / 1.0 | int4+ | – |
| glm-5.2 | `effort: xhigh` | max | 1.0 / 0.95 | fp8+ | – |
| glm-5.3-flash | `effort: max` | max | 1.0 / 0.95 | fp8+ | – |
| deepseek-v4-pro | `effort: high` | high | 1.0 / 1.0 | fp8+ | novita, parasail |
| deepseek-v4-flash | `effort: high` | high | 1.0 / 1.0 | fp8+ | gmicloud, siliconflow, parasail |

Every value carries its source in a comment in `permits/models.py`, and `tests/test_models.py`
checks the efforts, caps and host filters against the saved catalogue and endpoint snapshots.

**Effort sweeps.** A cell may name `model@effort` with an effort the catalogue lists, on OpenRouter
models only: gpt-oss-120b `low`/`medium`/`high`; glm-5.3-flash `low`/`high`/`max`; glm-5.2 and
DeepSeek V4 `high` and `xhigh`, where `xhigh` is the lab's max. Anthropic effort controls are not
wired.

### What protocol v1 cells ran at

For reading the existing cells. v1 recorded no host, so where the level depended on the endpoint,
each cell is a mixture in unknown proportion.

| model | v1 sent | level it ran at |
|---|---|---|
| claude-opus-5, claude-sonnet-5 | adaptive thinking | API default |
| claude-haiku-4-5 | budget = half the ceiling | – |
| gpt-oss-120b, qwen3.5-flash | nothing | each host's default (audit finding F2) |
| qwen3-coder | nothing | does not reason |
| kimi-k2-thinking | `reasoning_effort: medium` | always reasons; no levels |
| glm-5.2, glm-5.3-flash | `reasoning_effort: medium` | high on Z.ai's API, max on endpoints running the open template |
| deepseek-v4-pro, -flash | `reasoning_effort: medium` | mostly high; Think Max on GMICloud (Pro), and on Novita (Pro) whatever was sent |

## What every call records

- **Ledger** (`data/infer/ledger.jsonl`, one row per call that reached the API, failures included):
  tokens, cost (the provider's reported charge on OpenRouter), seconds, time to first token, the
  settings sent (protocol, cap, reasoning, lab level, temperature, top_p), the serving host,
  reasoning tokens, and the provider's response id: OpenRouter's generation id or Anthropic's
  message id. The id is what OpenRouter's `GET /api/v1/generation?id=` takes, whose record carries
  the host's native token counts and cost; there is no endpoint that lists past generations.
- **Draw records** (`variance.json`): outcome, scores, host, reasoning tokens. A v2 cell also records
  the settings every draw was sent with.
- **Cache** (`data/infer/cache/`): the response text, usage, stop reason, host and response id.

## File guarantees

`permits/fileio.py`: cache entries and roll-ups are written atomically; `variance.json` and
`conformance.json` are merged under a lock into the file as it is at that moment; a cell runs in one
process at a time, and a second run of it is refused before it sends anything; ledger appends are
locked. An unreadable `variance.json` raises instead of being treated as empty.

## Checking a change

- **Nothing already bought is invalidated.** Every v1 draw must still hash to its cached response
  under `--protocol v1`. Re-running a cell with `--run --max-spend 0` replays it from the cache,
  re-scores every draw and writes no ledger row; compare its draw records with a backup of
  `variance.json` before restoring it.
- **Roll-ups are unchanged.** `python scripts/model_stats.py`, then compare the two outputs byte for
  byte, or key for key where a field was added.
- **Effort handling.** `python spikes/probe_reasoning_effort.py --stage 2 --run --max-spend 2`
  re-reads what each DeepSeek endpoint renders for each effort (about $0.07; then `--generations`
  and `--report`). Re-run it when OpenRouter's endpoint list for a model changes.

## Open

- **GLM on third-party endpoints.** Nothing in the prompt-token count separates GLM's levels, so
  whether each endpoint honours the effort is not measured. Planned as behavioural smoke draws in
  step 6 of the audit's order of work.
- **Unverified on a live stream**, also for step 6: that OpenRouter accepts every `quantizations`
  value sent, routes a 64,000-token request only to endpoints that allow it, and reports usage and
  cost in the last chunk for every upstream.
- **Reconciling failed calls** with OpenRouter's records: possible from 2026-09-27, when ids began to
  be recorded; not built. Earlier rows carry no id and cannot be reconciled.
- **Generated code is not sandboxed** (audit step 7, deferred).

## Log

- **2026-09-25**: OpenRouter added as a second provider, widening the model axis to a 90x price
  band: [Open-weight model axis](../evidence/2026-09-25-open-weight-model-axis.md). Two processes
  ran one cell at once and both bought draw 1.
- **2026-09-26**: Reasoning models given headroom above the answer budget; two current cheap models
  and a hint arm added. [Fairness audit](../evidence/2026-09-26-model-comparison-fairness-audit.md):
  the comparison measured configuration as well as capability (unequal caps, uncontrolled reasoning,
  sampling and routing, a tier-mismatched roster). Remediation steps 1–3 and 5 done: one model
  registry and typed records; every call streamed and bounded in wall time, with errors split into
  fatal, transient and infra; protocol v2; the report's reporting error corrected.
- **2026-09-27**: [Reasoning effort on OpenRouter](../evidence/2026-09-27-openrouter-reasoning-effort.md).
  OpenRouter's effort names are not the labs', its catalogue default for glm-5.2 is not Z.ai's, and
  some DeepSeek endpoints ignore the effort sent. Protocol v2 now sends each lab's default level,
  excludes those endpoints, and records the lab level and the provider's response id on every row.
  Step 4 done: atomic writes, locked merges, one run per cell.
