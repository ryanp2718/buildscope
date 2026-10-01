# Failure cases

A living log of the odd things models, hosts and the measurement itself did during the model
comparison runs, one entry per kind of case. It exists for error analysis: read failures one at a
time, name them, and count them, because a pass rate averages away the cases that explain it. Most
entries so far are not model failures but measurement ones, which would have been read as facts
about a model if nobody had looked.

Each entry keeps what was **observed** (with the cell, draw and figures to find it again) apart from
the **hypothesis** (why it happened, untested until a test is named and run). **Frequency** turns an
anecdote into a rate. **Consequence** says what changed because of it. Categories: *model* (the
model's behaviour), *harness* (how the reply was parsed or run), *scorer*, *verifier* (the
reference-free check in the [agentic extractor plan](../evidence/2026-09-29-agentic-extractor-plan.md)),
*host* and *provider*. A cell key is `target|model|arm|protocol` in `data/infer/variance.json`; a
response id finds the call in `data/infer/ledger.jsonl` and in OpenRouter's generation record.

Figures are as of 2026-09-30, stage 3 of the v2 run in progress, over 833 successful v2 synthesis
calls in the ledger and 780 scored v2 draws.

| # | case | category | frequency |
|---|---|---|---|
| 1 | Announces a plan, then ends the turn | model; harness label | 1 of 10 grok-4.7 calls |
| 2 | Output past the token cap | provider | 4 of 10 grok-4.7 calls |
| 3 | Drafts in the answer, scored on the first | harness (fixed) | one draw, found 2026-09-24 |
| 4 | Hosts cut long streams at fixed durations | host | 8 of 21 glm-5.3-flash calls at the time |
| 5 | Every permit number right, whole columns empty | model; scorer | 35 of 136 perfect St. Johns draws |
| 6 | A stray `>` on every value | model; verifier blind spot | 2 of 358 verifier-accepted draws |
| 7 | An extra blank or duplicate row | scorer and verifier disagree | 3 of 359 perfect draws |
| 8 | Reasoning length at the output cap | model; design | 3 of 4 glm-5.3 Clark draws |
| 9 | A regex's quotes close its own string | model | 1 checked; 5 v2 draws refused for not parsing |

## 1. Announces a plan, then ends the turn

*Model; harness label.*

- **Observed.** `clarkco|x-ai/grok-4.7|v2` draw 5, 2026-09-30, response
  `gen-1790728596-NT15GpJ0xxWobMFM3Xcw`, served by xAI. 32,110 output tokens, 32,081 of them
  reasoning, 361.5 s, stop reason `end_turn`, $0.198. The visible reply, in full: "The grid is an
  Accela result table; I'll key off that template's row and field markup, then verify the parser
  against the sample structure." No code followed. Well under the 64,000-token cap, so not cut off.
- **Related.** `stjohns|deepseek/deepseek-v4-flash|v2` draws 5 and 7 ended on `end_turn` with 26,301
  and 24,085 output tokens, all but 0 and 2 of them reasoning: no reply at all. Recorded `no_code`.
- **Frequency.** 1 of 10 grok-4.7 v2 synthesis calls so far. 3 of 833 v2 synthesis calls ended their
  own turn with under 60 visible tokens; 22 more had under 60 because they hit the cap (case 8).
- **Recorded as** `refused`, which is a harness mislabel. With no fenced block and no `def extract(`,
  `extract_block` falls back to the whole reply, and the static audit fails to parse the sentence.
  It should be `no_code`. Both are format failures, reported together, so pass@1 does not change.
  It is the only one of 23 refused v2 draws that is prose; the rest are code the audit rejected.
- **Hypothesis (untested).** A model tuned for multi-turn tool use learns that announcing a plan is
  followed by another turn; in a one-shot task there is none. Tests: whether it recurs across
  grok-4.7's remaining draws; the visible-to-reasoning ratio per model; a prompt line asking for the
  module only, in a later protocol.
- **Consequence.** After stage 3, `extract_block` returns nothing when the reply has no
  `def extract(`, and the export relabels this draw `no_code`, reported as a label correction.

## 2. Output past the token cap

*Provider.*

- **Observed.** grok-4.7 is sent `max_tokens` 64,000 and bills past it: 66,437 output tokens (62,866
  reasoning) on its smoke draw, 2026-09-28, then 69,344, 80,290 and 76,097 in stage 3, all stopping
  on `end_turn` with a complete answer. xAI does not hold the model to the cap.
- **Related.** Usage reported inconsistently: minimax-m3 (Santa Barbara draw 1) and glm-5.2 (St.
  Johns draw 6) each report more reasoning tokens than output tokens at the cap (67,143 and 64,171
  against 64,000).
- **Frequency.** 4 of 10 grok-4.7 v2 synthesis calls; no other model.
- **Why it matters.** The cap is part of the fair configuration. A model allowed past it has more
  reasoning budget than the rest, by up to 25% on these calls.
- **Consequence.** Deviation 1 and amendment 2 of the
  [v2 pre-registration](../evidence/2026-09-27-v2-run-preregistration.md): a natural stop past the
  cap is not treated as truncation, and the report gives the count of grok-4.7 draws over the cap
  and by how much.

## 3. Drafts in the answer, scored on the first

*Harness, fixed 2026-09-25.*

- **Observed.** 2026-09-24, an open-weight reasoning model that reasons in its visible reply, not a
  separate channel, returned nine fenced blocks: sketches, corrections, then the finished module.
  One fence opened where a close was due. The harness took the first block and scored 10,236
  output tokens containing a working extractor on a 154-character sketch, as a refusal.
- **Frequency.** One draw found; the cause applied to every model that drafts in its reply.
- **Why it matters.** It pointed one way, against the open-weight tier, which is the comparison the
  experiment exists to make. It was one of five harness assumptions that held only while Claude was
  the sole model, each turning a working extractor into a recorded failure.
- **Consequence.** `extract_block` takes the last block that defines the contract, and the fence
  scanner tolerates fences that do not pair (commit `519d260`; tests in `tests/test_variance.py`,
  including `test_unbalanced_fences_do_not_walk_out_of_phase`).

## 4. Hosts cut long streams at fixed durations

*Host.*

- **Observed.** glm-5.3-flash, v2 stage 1: calls ended with a usage block and no finish reason,
  mid-reasoning, at 301 s on AtlasCloud (2 of its 2 calls) and at 602 s on Phala (6 calls; Phala also
  completed calls of 1,118 s and 1,702 s). OpenRouter's generation record agrees: native finish
  reason null, not cancelled. After re-routing, 7 more on Io Net (3), GMICloud (3) and SiliconFlow
  (1), and two SiliconFlow calls stopped at 32,768 tokens, below the cap.
- **Frequency.** 8 of glm-5.3-flash's first 21 v2 calls.
- **Why it matters.** The cuts land on the longest-reasoning draws. Scored as failures (as they were,
  `no_code`, until found) they understate the model; dropped, they overstate it.
- **Consequence.** Deviation 2: a stream with no stop reason under the cap is a host failure
  (`infer.cut_by_host`), retried once and then recorded `infra_error`, outside n. The five hosts are
  excluded for glm-5.3-flash and, carried over unmeasured, for glm-5.3.

## 5. Every permit number right, whole columns empty

*Model; scorer.*

- **Observed.** Draws scored perfect, because on every page the set of permit numbers matches the
  adapter's, that leave a whole column null on every record. Re-scored with every field required,
  311 of 349 perfect v2 draws pass: Clark 164 of 166, Santa Barbara 46 of 47, St. Johns 101 of 136.
  Fields that disagree, counted in draws: address 34, issue date 26, structure code 23, and one each
  of permit type, status and contractor (`data/infer/verifier/field_audit.json`).
- **Frequency.** 35 of 136 perfect St. Johns draws, across 13 models; Gemini 3.8 Flash 7 of 10,
  DeepSeek V4 Pro 0813 5, qwen3-coder 4, MiMo V2.6 Pro 4, Sonnet 5 3. Gemini 3.8 Flash's St.
  Johns cell goes from 10/10 to 3/10.
- **Hypothesis (untested).** Models anchor on the id column and on columns whose headers resemble the
  contract's field names, and leave a field null rather than guess when a header does not match.
  Test: compare St. Johns' column headers with the contract's names, per missing field.
- **Consequence.** Deviation 4: the coded rule stays primary and field-level pass@1 is reported
  beside it everywhere. A verifier check for it (a column the grid prints but the output leaves
  null on every row) is designed on St. Johns and checked on Santa Barbara, labelled post hoc.

## 6. A stray `>` on every value

*Model; verifier blind spot.*

- **Observed.** `clarkco|qwen/qwen3.8-flash|v2` draw 3 and `clarkco|xiaomi/mimo-v2.6-flash|v2` draw 4
  return every value prefixed with `>`. In the qwen extractor the cause is visible: its cell
  pattern `<td\b[^>]*` matches an opening tag without its closing bracket, so each cell's text
  starts with it. The scorer fails both (the permit numbers do not match); the verifier accepts
  both, since its markup check looks for tags, not stray brackets, and the row counts are right.
- **Frequency.** 2 of 358 extractors the verifier accepted: its whole false-accept rate.
- **Consequence.** Candidate verifier check: no value starts or ends with `<` or `>`. Added after
  the fact, so reported as post hoc if adopted.

## 7. An extra blank or duplicate row

*Scorer and verifier disagree.*

- **Observed.** `clarkco|moonshotai/kimi-k2-thinking|hint|v2` draw 2,
  `clarkco|xiaomi/mimo-v2.6-flash|v2` draw 3 and `clarkco|z-ai/glm-5.3-flash|v2` draw 1 emit one extra
  row per page, blank or duplicating another. The verifier rejects them on all 57 pages (row count
  and unique ids). The scorer passes them: it matches on the set of permit numbers, drops rows with
  none and keeps the first of duplicates.
- **Frequency.** 3 of 359 perfect draws: the verifier's whole false-reject rate.
- **Open question.** Which one is right. A pipeline loading these would insert a blank or duplicate
  record, so the verifier's reading is arguably the stricter and more useful one. Not changed; both
  are reported.

## 8. Reasoning length at the output cap

*Model; design.*

- **Observed.** glm-5.3, stage 3 Clark: draws 1, 2 and 3 hit the 64,000-token cap. Re-drawn once at
  128,000 (amendment 2), they finished at 69,934, 58,419 and 60,442 tokens, all perfect. Two of the
  three finished under the cap the second time, so the task does not need more than 64,000 tokens;
  the model's reasoning length varies that much from draw to draw.
- **Frequency.** v2 calls stopped at 64,000: glm-5.3-flash 16, qwen3.8-flash 12, glm-5.3 3, and one
  each for qwen3.5-flash-02-23, glm-5.2 and minimax-m3.
- **Why it matters.** A fixed cap cuts the long tail of a model's reasoning, and the tail is not
  where the failures are: all three glm-5.3 re-draws passed. The re-draw rule turns truncation into
  a cost instead of a failure; a re-drawn glm-5.3 draw cost $0.42-0.48 against $0.21.
- **Consequence.** Cost per success carries the re-draw spend. glm-5.3's stage 3 spend limit is at
  risk from it, and any draws lost that way are reported as cut by the ceiling.

## 9. A regex's quotes close its own string

*Model.*

- **Observed.** `clarkco|z-ai/glm-5.3|v2` draw 6, 2026-09-30, response
  `gen-1790731187-N8TJ6Wvd6MEzMFfqGxz6`, re-drawn at 128,000 tokens after a cut-off, 49,206 output
  tokens, $0.39. A 304-line module refused by the static audit: "unterminated string literal", line
  118. The model wrote an attribute pattern that has to match both quote characters as a raw
  triple-quoted string, and the pattern's own closing `"` ran into the string's closing `"""`,
  which ended the string one character early and opened a new one that never closes.
- **Frequency.** 5 v2 draws refused because the module does not parse, not counting case 1 (this one; Gemini 3.5 Flash
  Lite, qwen3.8-flash and two mimo-v2.6-flash on St. Johns). Only this one's mechanism is checked
  so far. Refused modules are not saved to disk, so the other four need their replies read from the
  response cache.
- **Hypothesis (untested).** Regexes over HTML attributes need both quote characters inside a Python
  string literal, which is where quoting mistakes concentrate; a model that parses HTML with
  `html.parser` instead of regexes avoids the whole class. Test: read the other four, and compare the
  parse-failure rate of regex-based and parser-based extractors.
- **Consequence.** None to the scoring: a module that does not parse fails, as pre-registered. It is
  the kind of failure a repair turn should fix in one step, since the error message names the line,
  so it is a case for the agentic follow-up.
