# Reasoning effort on OpenRouter: what each model accepts, and what an unlisted effort becomes

Date:      2026-09-27
Produced:  `python spikes/probe_reasoning_effort.py --stage 1 --run` (and `--prompt p2|p3
           --only openai/gpt-oss-120b`), then `--stage 2 --run` and `--generations`. Lab and
           OpenRouter documentation fetched 2026-09-27 with curl.
Inputs:    `data/audit/2026-09-27-openrouter-models.json`,
           `data/audit/2026-09-27-openrouter-endpoints.json`,
           `data/audit/2026-09-27-effort-sources/` (14 files, listed under Sources)
Outputs:   `data/audit/2026-09-27-effort-probe.jsonl` (173 calls, $0.081),
           `data/audit/2026-09-27-effort-probe-generations.json` (OpenRouter's record of each)
Status:    Current. Qualifies F3 of the
           [2026-09-26 fairness audit](2026-09-26-model-comparison-fairness-audit.md).

Follows finding F3 and the "new finding" under "Step 3 as built" in the audit. The plan was
written before the probe; the results follow it.

## Question

1. Which reasoning efforts does each model on the roster accept, in its lab's own terms?
2. What does OpenRouter send upstream when a request names an effort the model does not list?
   Protocol v1 sent `reasoning_effort: "medium"` to glm-5.2, deepseek-v4-pro, deepseek-v4-flash and
   glm-5.3-flash, none of which lists `medium`.
3. Does protocol v2's rule, "the catalogue's default effort", put every model at its lab's default?

## Sources

Saved in the private store, `data/audit/2026-09-27-effort-sources/`, fetched with curl on
2026-09-27:

- OpenRouter: the reasoning-tokens guide, the parameters reference, the generation-metadata API
  reference and the Logs guide (`openrouter.ai/docs/...md`); the live catalogue
  (`data/audit/2026-09-27-openrouter-models.json`, `reasoning` blocks identical to the 2026-09-25
  snapshot).
- Z.ai: the GLM-5 GitHub README; the GLM-5.2 and GLM-5.3-Flash Hugging Face cards and
  `chat_template.jinja`.
- DeepSeek: the API reference for chat completions and the thinking-mode guide
  (`api-docs.deepseek.com`); the DeepSeek-V4-Pro card and its `encoding/encoding_dsv4.py`, which
  replaces a chat template for V4.
- The `chat_template.jinja` of gpt-oss-120b, Kimi-K2-Thinking and Qwen3.5-35B-A3B.

## What the labs accept

| model | lab accepts | lab default | an unlisted value becomes | OpenRouter lists | OpenRouter default |
|---|---|---|---|---|---|
| glm-5.2 | high, max | max | max | xhigh, high | high |
| glm-5.3-flash | low, high, max | max | max | max, high, low | max |
| deepseek-v4-pro, -flash | API: none, low, high, max. Open weights: high, max | high | API: minimal→low, medium→high, xhigh→high. Open weights: rejected | xhigh, high | high |
| gpt-oss-120b | low, medium, high | medium | written into the prompt verbatim | high, medium, low | medium |
| kimi-k2-thinking | no effort control; always reasons | – | – | none (mandatory) | – |
| qwen3.5-flash | on/off (`enable_thinking`) | on in the open template | – | none | off unless enabled |
| opus-5, sonnet-5 | low, medium, high, xhigh, max | high | – | max, xhigh, high, medium, low | high |

- **GLM.** The GLM-5.2 template sets `'high' if reasoning_effort == 'high' else 'max'` and writes
  `<|system|>Reasoning Effort: High` or `Max` at the start of the prompt. GLM-5.3-Flash keeps `low`
  and `high` and turns everything else into `max`. The README says the default is `max` "if not
  passed (or if set to any other value)", and asks benchmark reproductions to keep `max`.
- **DeepSeek V4.** The API reference: "`none` disables thinking mode; `low` / `high` / `max` enable
  thinking mode. The default effort is `high`. For compatibility with existing software, `minimal`
  is accepted and mapped to `low`, and `medium` / `xhigh` are accepted and mapped to `high`." The
  open-weights encoder asserts `reasoning_effort in ['max', None, 'high']`; `high` and unset render
  the same prompt, and `max` prepends a fixed paragraph beginning "Reasoning Effort: Absolute
  maximum with no shortcuts permitted." No roster host for V4 is DeepSeek itself, so every host
  runs its own serving stack.
- **gpt-oss.** The template writes `Reasoning: <effort>` into the system message, default `medium`.
- **Claude.** From OpenRouter's parameters reference (`reasoning_effort` maps to
  `output_config.effort`) and its catalogue. Not checked against Anthropic's own documentation;
  Anthropic effort controls are not wired in this harness.

So OpenRouter's vocabulary is not the labs'. For glm-5.2 the catalogue default, `high`, is not
Z.ai's default, `max`. Protocol v2 as built sends glm-5.2 `high`, so the answer to question 3 is
no for glm-5.2. For DeepSeek, the catalogue's `xhigh` is a value DeepSeek's API maps to `high`,
so whether `xhigh` through OpenRouter ever reaches Think Max depends on a translation OpenRouter
does not document.

## What OpenRouter documents

- The `reasoning` object takes `effort` of `max`, `xhigh`, `high`, `medium`, `low`, `minimal` or
  `none`. Top-level `reasoning_effort`, which protocol v1 sent, is in the parameters reference
  with the enum `xhigh` to `none`, without `max`.
- The catalogue's `supported_efforts` is described as a filter for client UIs: "Filter effort
  selectors to these values."
- One sentence, placed in the Gemini 3 section: "If a model doesn't support a specific effort
  level (for example, if a model only supports `low` and `high`), OpenRouter will map your
  requested effort to the nearest supported level." The Anthropic Messages section says `xhigh`
  and `max` "are translated to the model's supported reasoning efforts". Neither says how a tie
  is broken, or whether the mapping is done by OpenRouter or left to the host.
- An unsupported effort in a mid-conversation update is rejected with a 400 on OpenAI models.
  Nothing says a request-level unsupported effort is rejected, and v1's requests were not.
- `reasoning: {"enabled": true}` "enables reasoning at the 'medium' effort level". Protocol v2
  sends this to qwen3.5-flash and kimi-k2-thinking, which have no levels.
- The generation record (`GET /api/v1/generation?id=`) carries `provider_name` and
  `native_tokens_reasoning`, and no field for the effort applied. There is no endpoint that lists
  past generations, and the Activity export is aggregated. Reconciling a draw with OpenRouter's
  record therefore needs the generation id, which neither the cache nor the ledger keeps.

What v1's `medium` became is therefore not documented. The candidates:

| model | nearest listed | passed through to the lab's template or API |
|---|---|---|
| glm-5.2 | high | max |
| glm-5.3-flash | high or low (a tie) | max |
| deepseek-v4-pro, -flash | high | high (API); rejected (open encoder), so the host must translate |

The v1 OpenRouter cache entries kept only text and token totals: no host, no reasoning tokens and
no generation id. The v1 cells cannot answer this.

## Probe

Every template above writes the effective effort into the prompt as text the model can read:
`Reasoning Effort: High|Max|Low` (GLM), the "Absolute maximum" paragraph (DeepSeek at max,
nothing at high), `Reasoning: low|medium|high` (gpt-oss). Asking the model to quote that line
reads back what the serving host rendered, and the reasoning-token count corroborates it (max
should reason longer than high).

`spikes/probe_reasoning_effort.py`:

- **Models and request forms.**
  - glm-5.2, glm-5.3-flash, deepseek-v4-pro, deepseek-v4-flash: `v1` (top-level
    `reasoning_effort: "medium"`, exactly v1's shape), `none` (no reasoning field), `enabled`
    (`reasoning: {"enabled": true}`), and `reasoning: {"effort": e}` for every effort the
    catalogue lists plus `max` where it is not listed.
  - gpt-oss-120b as the control, whose mapping is known: `low`, `medium`, `high`, on four hosts.
    If the readout does not return the effort sent there, the method fails and nothing else is
    read from it.
- **Hosts.** Every endpoint the live endpoint listing shows for the model, one request per
  endpoint slug, pinned with `provider: {"only": [slug], "allow_fallbacks": false}`. v1 had no
  host filter, so any of them may have served a v1 cell. The `provider` field of the response is
  checked against the pin.
- **One draw per (model, form, host).** The readout is close to deterministic. Any cell whose
  readout and token count disagree is repeated twice.
- **Prompt.** No system message. User: "Before this message, your input may contain a line that
  begins with the word "Reasoning". If it does, reply with that line exactly as written. If it
  does not, reply NONE. Reply with nothing else." `max_tokens` 4,000: a truncated reply still
  carries the reasoning-token count.
- **Recorded per call**, to `data/audit/2026-09-27-effort-probe.jsonl`: model, slug, form, the
  body sent, the host that served it, the reply, the parsed readout, reasoning and completion
  tokens, `usage.cost`, finish reason, generation id, and any error with its status. Re-running
  skips calls already recorded without error.
- **Cost.** A dry run prints the call count and the worst case at 4,000 output tokens at the
  registry's price ceilings. `--max-spend` stops the run on reported cost.

### Reading the result

- Per model and form: if every host gives the same readout, that is what OpenRouter sends, and
  the v1 cells ran at that effort. If hosts differ, v1 cells were a mixture weighted by routing,
  which cannot be recovered per draw, and the report says so.
- `max` and `xhigh` per model: which one reaches the lab's top level, if either.
- A 400 for a form: OpenRouter rejects that effort for that model, so it is not a usable setting.

## Results, 2026-09-27

Spend: $0.081 over 173 calls (`data/audit/2026-09-27-effort-probe.jsonl`), plus OpenRouter's
free generation record for each (`data/audit/2026-09-27-effort-probe-generations.json`).

**The readout failed.** All 27 stage-1 calls answered NONE, the gpt-oss control included. The
control's reasoning shows it reads its system message and does not report the `Reasoning:` line
in it. Two rewordings on the control returned the effort sent once in six. Per the rule above,
nothing is read from the readout.

**The prompt-token count works for DeepSeek.** The generation record's `native_tokens_prompt` is
the host's own count of the prompt it rendered. On Novita, deepseek-v4-flash rendered 49 tokens
for `v1`, none, enabled and `high`, and 128 for `xhigh` and `max`: the 79-token Think Max
paragraph. This signal is deterministic and needs one call per form, so stage 2 was run on it,
for DeepSeek only: every endpoint × `v1`, none, `high`, `xhigh`, `max` (140 calls, $0.071, no
errors). It reads GLM and gpt-oss not at all, since their level names are one token each (every
GLM form rendered 56).

Endpoints render the levels differently: most render 49 for high and 128 for max, while
Cloudflare, DeepInfra, Venice, Relace and OpenInference render 128 for high and 141 for max. So
each endpoint is read against itself, by which forms render the same prompt:

| | deepseek-v4-pro (14 endpoints) | deepseek-v4-flash (16 endpoints) |
|---|---|---|
| `xhigh` renders as `max` | 14 of 14 | 16 of 16 |
| v1's `medium` renders as `high` | 9 | 12 |
| v1's `medium` renders as `max` | 1 (GMICloud) | 0 |
| every thinking form renders one prompt | 4 (Novita, Parasail, DigitalOcean, Azure) | 4 (GMICloud, SiliconFlow, Parasail, Azure) |

- **`xhigh` and `max` are the same request** on every endpoint, so OpenRouter translates `xhigh`
  to Think Max before DeepSeek's own `xhigh`→high mapping could apply. A `@xhigh` sweep is Think
  Max, and `@max` would duplicate it.
- **v1's `medium` ran at high** on 21 of 30 endpoints and at max on GMICloud's Pro endpoint. On 8
  it made no difference, because those endpoints ignore the effort. Novita's Pro endpoint renders
  the 128-token prompt for every form while Novita's Flash endpoint renders 49 for high, so
  Novita serves Pro at Think Max whatever is asked. Parasail and Azure render 49 for every form,
  so they never reach max. Which endpoint served a v1 draw was not recorded, so each v1 DeepSeek
  cell is a mixture, mostly high.
- **What "no effort" means is up to the endpoint.** With no reasoning field, DeepInfra,
  DigitalOcean (Flash), SiliconFlow (Flash) and Azure did not think at all (0 reasoning tokens);
  the rest thought.
- Among endpoints protocol v2 admits (fp8 or higher), the ones that ignore effort are Novita and
  Parasail for Pro, and GMICloud, SiliconFlow and Parasail for Flash.

**GLM, from Z.ai's API reference** (`zai-api-chat-completion.md` in the sources): for GLM-5.2,
"`none` or `minimal` will cause the model to skip thinking; `low` and `medium` will be mapped to
`high`; `xhigh` will be mapped to `max`", default `max`; GLM-5.3 and GLM-5.3-Flash take only
`low`, `high`, `max`. So Z.ai's API maps v1's `medium` to high, while an endpoint running the open
template maps it to max. What third-party GLM endpoints do, and whether some ignore effort, is
not measured: nothing in the prompt-token count separates the levels. `xhigh` reaches max for
glm-5.2 on both routes.

## Consequences for protocol v2

Implemented on 2026-09-27; see "Step 3 as built" in the audit. The v1 labels are carried in
[`docs/design/model-comparison.md`](../design/model-comparison.md).

- **Reasoning at the lab's default** (decided 2026-09-27), not the catalogue's: glm-5.2 sends
  `xhigh` (Z.ai max on both routes), glm-5.3-flash `max`, DeepSeek V4 `high`, gpt-oss-120b
  `medium`, Claude the API default. The registry carries the lab's level name beside the
  OpenRouter value sent, and the settings recorded per draw carry both.
- **Exclude endpoints that ignore effort**, with `provider.ignore`: Novita and Parasail for
  deepseek-v4-pro; GMICloud, SiliconFlow and Parasail for deepseek-v4-flash. Otherwise a v2
  DeepSeek cell mixes Think Max (Novita Pro) and high by routing. The list is a snapshot and
  needs re-probing when the endpoint listing changes; the probe costs about $0.07.
- **Effort sweeps** name distinct levels only. For DeepSeek that is `high` and `xhigh` (Think
  Max); `max` is accepted and equals `xhigh`.
- **v1 cells**: DeepSeek v1 cells are labelled "mostly high, mixed by endpoint". GLM v1 cells are
  "high on Z.ai, max on open-template endpoints, mixture unknown".
- Every ledger row carries the provider's generation or message id, so any draw can be
  reconciled with the provider's own record later, failed calls included. This probe's
  generation lookups show the record is available within seconds and carries the host's native
  prompt and reasoning token counts.

These change the v2 request body. No v2 cell has been bought, so no v2 cell is invalidated.

Not measured: GLM on third-party endpoints. The one signal left is behavioural, reasoning-token
distributions on an effort-sensitive task at several draws per form; the trivial probe prompt
gives single-draw counts too noisy to use (glm-5.2 on Z.ai: `high` 46, `max` 34, `xhigh` 118).

## What this does not establish

- **GLM on third-party endpoints is not measured.** The prompt-token signal cannot separate GLM's
  levels, so the GLM findings rest on Z.ai's API reference and the open template. The behavioural
  probe is deferred to step 6's smoke draws.
- **One call per endpoint and form.** The prompt-token count is deterministic for a given
  endpoint, template and effort, but an endpoint can change its template or its routing at any
  time. The exclusion list is a 2026-09-27 snapshot.
- **The prompt-token signal reads the prompt, not the model.** An endpoint that rendered Think Max
  could still serve a different checkpoint or cap reasoning some other way.
- **Reasoning-token counts on the probe prompt are not evidence of a level.** The prompt is
  trivial, and single draws vary more between repeats than between levels.
- **Which endpoint served any v1 draw is unknown**, so the v1 labels here describe what each cell
  could have been, not what each draw was.
