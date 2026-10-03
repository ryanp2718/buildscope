# Results: the protocol v2 model comparison run

Date:      2026-10-01
Produced:  `python scripts/field_audit.py`, `python scripts/export_results.py`,
           `python spikes/v2_results.py --caption` (every table below), `python spikes/v2_label_check.py`
           (the label correction), `python spikes/v2_stage1_audit.py` (host failures, whole run),
           `python spikes/v2_name_clash.py` (the `html` parameter, added 2026-10-02). No model
           calls; cost $0.00.
Inputs:    `data/infer/variance.json` (86 v2 cells, 836 scored v2 draws, 3 of them excluded), `data/infer/ledger.jsonl` (927
           v2 synthesis calls, 2026-09-28 17:02Z to 2026-09-30 06:50Z),
           `data/infer/verifier/field_audit.json` (427 perfect draws re-run), the response cache
Outputs:   `site/results/data.json` and `tables.html`, `data/infer/model_stats.csv` and `.json`
Status:    Draft for review. Answers the five questions of the
           [v2 pre-registration](2026-09-27-v2-run-preregistration.md) under its analysis plan; the
           reporting additions of the [results plan](2026-09-28-v2-results-and-visualization-plan.md)
           are labelled as not pre-registered. The results page is not published.

## The run

19 roster models and the 7 v1 models re-run under v2, on Clark County (development), St. Johns County
(development) and Santa Barbara (held out): **833 scored draws in 86 cells, 424 perfect.** 927
synthesis calls, 898 successful, billed **$47.36**, inside the $53 cap (amendment 4). Failed calls
were billed $0.08. Two draws were lost to host failures after their retry (`infra_error`), 35 were
re-drawn at the catalogue limit after a cut-off at 64,000 tokens (amendment 2), and none was still
cut off after its re-draw.

What changed from the plan, all recorded in the pre-registration and applied as written:
deviations 1 (grok-4.7 bills past the cap), 2 (streams a host closed early are host failures), 3
(cells time-boxed; stage 3 cutoff), 4 (the pass rule as coded is primary, field-level pass@1 beside
it) and 5 (glm-5.3's St. Johns draws 2-4 finished after the cutoff and are excluded); amendments 3
and 4 (cap raised to $50, then $53); cut 1 (no Clark hint cells for the mid tier). The whole-run
search for streams closed early found only the 8 glm-5.3-flash calls of deviation 2.

**A label correction.** 13 draws recorded `refused` are `no_code`: the reply never contains
`def extract(` ([failure cases](../design/failure-cases.md), cases 1 and 10). Both are format
failures and count the same way, so no rate changes.

## Question 1: capability on Clark

Clark baseline, in order of output price. Field-level pass@1 also requires every field of every
matched record to agree (deviation 4). Silent: ran without error, wrong or missing rows. Near miss:
a silent failure with recall at least 0.98 at precision 1.0, counted among the silent. Format: no
code, or refused by the static audit.

| model | $/M out | pass@1 [95%] | field-level | near miss | silent | format | raised | $/success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GLM-5.3 Flash | 0.14 | 15/19 0.79 [0.57, 0.91] | 15/19 | 0 | 2 | 0 | 2 | 0.0419 |
| MiMo V2.6 Flash | 0.28 | 13/20 0.65 [0.43, 0.82] | 12/20 | 1 | 3 | 0 | 4 | 0.0069 |
| DeepSeek V4.1 Flash | 0.29 | 10/10 1.00 [0.72, 1.00] | 10/10 | 0 | 0 | 0 | 0 | 0.0055 |
| Qwen3.8 Flash | 0.47 | 16/20 0.80 [0.58, 0.92] | 15/20 | 0 | 2 | 0 | 2 | 0.0444 |
| GPT-6 Luna | 0.50 | 2/20 0.10 [0.03, 0.30] | 2/20 | 6 | 6 | 2 | 10 | 0.0152 |
| Hunyuan 3 | 0.53 | 0/10 0.00 [0.00, 0.28] | 0/10 | 4 | 4 | 0 | 6 | none |
| MiMo V2.6 Pro | 0.87 | 12/20 0.60 [0.39, 0.78] | 12/20 | 1 | 4 | 0 | 4 | 0.0308 |
| MiniMax M3 | 1.20 | 0/10 0.00 [0.00, 0.28] | 0/10 | 4 | 10 | 0 | 0 | none |
| Gemini 3.5 Flash-Lite | 2.50 | 0/10 0.00 [0.00, 0.28] | 0/10 | 1 | 10 | 0 | 0 | none |
| DeepSeek V4 Pro | 3.50 | 10/10 1.00 [0.72, 1.00] | 10/10 | 0 | 0 | 0 | 0 | 0.0922 |
| Gemini 3.8 Flash | 3.75 | 19/20 0.95 [0.76, 0.99] | 19/20 | 0 | 0 | 0 | 1 | 0.0828 |
| GLM-5.3 | 4.40 | 7/10 0.70 [0.40, 0.89] | 7/10 | 1 | 2 | 1 | 0 | 0.543 |
| Grok 4.7 | 4.80 | 12/13 0.92 [0.67, 0.99] | 12/13 | 0 | 0 | 1 | 0 | 0.359 |
| Claude Haiku 4.5 | 5.00 | 0/10 0.00 [0.00, 0.28] | 0/10 | 1 | 9 | 0 | 1 | none |
| Qwen3.8 Max | 6.00 | 10/10 1.00 [0.72, 1.00] | 10/10 | 0 | 0 | 0 | 0 | 0.250 |
| Claude Sonnet 5 | 10.00 | 6/20 0.30 [0.15, 0.52] | 6/20 | 13 | 13 | 0 | 1 | 0.132 |
| GPT-6 Sol | 10.00 | 0/10 0.00 [0.00, 0.28] | 0/10 | 0 | 0 | 0 | 10 | none |
| Kimi K3 | 15.00 | 10/10 1.00 [0.72, 1.00] | 10/10 | 0 | 0 | 0 | 0 | 0.150 |
| Claude Opus 5.5 | 20.00 | 18/20 0.90 [0.70, 0.97] | 18/20 | 1 | 1 | 0 | 1 | 0.0712 |

**Answer.** The roster splits in two. Twelve models pass Clark at point estimates of 0.60 to 1.00,
and no two of them are separable: every pair's intervals overlap. Seven pass at 0.30 or less, five
of them 0/10. Of the 171 pairs, 81 have intervals that do not overlap, and every one of the 81 is a
model of the first group over one of the second. Grok 4.7's cell is 13 draws and GLM-5.3's 10, not
20: their processes' spend limits cut the rest (below, "Missing draws"). The field-level rule changes
two cells by one draw and no pair.

Failures differ in kind more than rates show. 13 of Claude Sonnet 5's 14 failures are near misses, a
few records missed and none invented; GPT-6 Sol's 10 all raise, 7 of them on a name the prompt
gives two meanings (below, "The `html` parameter"); MiniMax M3's and Gemini 3.5 Flash-Lite's 10 are
all silent.

## Question 2: price per token against cost per success

Clark baseline, ranked by cost per success (USD per extractor that passed). Interval: cost per draw
over the Wilson bounds, as pre-registered. Models at 0/n are last, tied.

| rank | model | $/M out | $/success | interval |
|---:|---|---:|---:|---:|
| 1 | DeepSeek V4.1 Flash | 0.29 | 0.0055 | 0.0055-0.0076 |
| 2 | MiMo V2.6 Flash | 0.28 | 0.0069 | 0.0055-0.0104 |
| 3 | GPT-6 Luna | 0.50 | 0.0152 | 0.0051-0.0546 |
| 4 | MiMo V2.6 Pro | 0.87 | 0.0308 | 0.0237-0.0478 |
| 5 | GLM-5.3 Flash | 0.14 | 0.0419 | 0.0361-0.0583 |
| 6 | Qwen3.8 Flash | 0.47 | 0.0444 | 0.0386-0.0608 |
| 7 | Claude Opus 5.5 | 20.00 | 0.0712 | 0.0659-0.0917 |
| 8 | Gemini 3.8 Flash | 3.75 | 0.0828 | 0.0794-0.103 |
| 9 | DeepSeek V4 Pro | 3.50 | 0.0922 | 0.0922-0.128 |
| 10 | Claude Sonnet 5 | 10.00 | 0.132 | 0.0766-0.273 |
| 11 | Kimi K3 | 15.00 | 0.150 | 0.150-0.207 |
| 12 | Qwen3.8 Max | 6.00 | 0.250 | 0.250-0.346 |
| 13 | Grok 4.7 | 4.80 | 0.359 | 0.336-0.497 |
| 14 | GLM-5.3 | 4.40 | 0.543 | 0.426-0.957 |
| last | Hunyuan 3, MiniMax M3, Gemini 3.5 Flash-Lite, Claude Haiku 4.5, GPT-6 Sol | 0.53-10.00 | none | |

**Answer: supported.** 13 pairs are in the opposite order in the two rankings with cost-per-success
intervals that do not overlap; the claim needed one. The
[intervals method](2026-09-27-cost-per-success-intervals.md) (P ≥ 0.975 under both priors) also
settles 13, 12 of them the same: it does not settle Claude Opus 5.5 over DeepSeek V4 Pro, whose
Wilson-bound intervals miss each other by $0.0005, and it settles Qwen3.8 Max over Grok 4.7. The
largest:

| pricier per token, cheaper per success | than | times cheaper per success [95%] |
|---|---|---:|
| Claude Opus 5.5 ($20) | GLM-5.3 ($4.40) | 7.6 [4.9, 14.0] |
| DeepSeek V4.1 Flash ($0.29) | GLM-5.3 Flash ($0.14) | 7.6 [4.5, 12.8] |
| MiMo V2.6 Flash ($0.28) | GLM-5.3 Flash ($0.14) | 6.1 [3.6, 9.7] |
| Claude Opus 5.5 ($20) | Grok 4.7 ($4.80) | 5.1 [3.7, 7.1] |
| Claude Opus 5.5 ($20) | Qwen3.8 Max ($6) | 3.6 [2.7, 4.7] |
| Claude Opus 5.5 ($20) | Kimi K3 ($15) | 2.1 [1.4, 3.2] |

The dearest model per token is the seventh cheapest per success, ahead of every other top-tier
model, because its draws cost less ($0.064 a draw against $0.15-0.38): it writes far fewer tokens.
The cheapest per token, GLM-5.3 Flash, spends $0.033 a draw, so two cheap-tier models at twice its
price per token, at about $0.005 a draw, are 6-8 times cheaper per success. Under the field-level
rule there are also 13 such reversals.

## Question 3: the held-out portal

Santa Barbara, 5 draws per model, beside Clark.

| model | Clark | Santa Barbara | | model | Clark | Santa Barbara |
|---|---:|---:|---|---|---:|---:|
| GLM-5.3 Flash | 15/19 | 4/5 | | Gemini 3.8 Flash | 19/20 | 5/5 |
| MiMo V2.6 Flash | 13/20 | 2/5 | | GLM-5.3 | 7/10 | 4/5 |
| DeepSeek V4.1 Flash | 10/10 | **0/5** | | Grok 4.7 | 12/13 | 5/5 |
| Qwen3.8 Flash | 16/20 | 3/5 | | Claude Haiku 4.5 | **0/10** | 5/5 |
| GPT-6 Luna | 2/20 | 2/5 | | Qwen3.8 Max | 10/10 | 4/5 |
| Hunyuan 3 | 0/10 | 1/5 | | Claude Sonnet 5 | 6/20 | 4/5 |
| MiMo V2.6 Pro | 12/20 | 3/5 | | GPT-6 Sol | 0/10 | 3/5 |
| MiniMax M3 | 0/10 | 3/5 | | Kimi K3 | 10/10 | 4/5 |
| Gemini 3.5 Flash-Lite | 0/10 | 4/5 (field-level 3/5) | | Claude Opus 5.5 | 18/20 | 5/5 |
| DeepSeek V4 Pro | 10/10 | 3/5 | | | | |

**Answer.** Rates do not carry over in rank. Spearman's rho between the Clark and Santa Barbara rates
is **0.17, bootstrap 95% [-0.30, 0.65]** over the 19 models (0.25 under the field-level rule). One
model passes Clark reliably and fails Santa Barbara reliably (DeepSeek V4.1 Flash, 10/10 and 0/5),
and one does the reverse (Claude Haiku 4.5, 0/10 and 5/5). Five models at 0/10 on Clark pass Santa
Barbara at least once.

**What the two portals showed the model differs.** Most silently empty Clark extractors fail on one
structure, a small table nested in the grid's first row (below, "The caption table"). Santa Barbara's
grid carries the same nested table on all 5 pages, but its excerpt does not: the window fallback
added before the run (pre-registration, "A harness fix found on the test target") starts Santa
Barbara's excerpt at the grid's header row, just after the nested table, while Clark's excerpt shows
it. So the held-out comparison differs from Clark in what the model was shown, not only in the
template. Whether seeing that table is what trips the Clark extractors is not tested here.

## Question 4: configuration effects

v2 minus v1 for the seven re-run models, with Newcombe intervals. A configuration effect is claimed
only where the interval excludes 0.

| model | Clark v1 | Clark v2 | v2 - v1 | St. Johns v1 | St. Johns v2 | v2 - v1 |
|---|---:|---:|---:|---:|---:|---:|
| GLM-5.2 | 0/10 | 0/10 | 0.00 [-0.28, 0.28] | 1/2 | 10/10 | **+0.50 [+0.01, +0.91]** |
| DeepSeek V4 Pro (Apr) | 0/10 | 0/10 | 0.00 [-0.28, 0.28] | 0/1 | 2/10 | +0.20 [-0.61, +0.51] |
| DeepSeek V4 Flash | 1/10 | 2/20 | 0.00 [-0.31, 0.22] | no v1 cell | 5/10 | |
| Kimi K2 Thinking | 2/10 | 0/10 | -0.20 [-0.51, 0.11] | 0/2 | 3/10 | +0.30 [-0.39, +0.60] |
| gpt-oss-120b | 0/20 | 0/10 | 0.00 [-0.16, 0.28] | 18/20 | 10/10 | +0.10 [-0.19, +0.30] |
| Qwen3.5 Flash | 0/20 | 0/10 | 0.00 [-0.16, 0.28] | 10/20 | 3/10 | -0.20 [-0.48, +0.16] |
| Qwen3 Coder | 0/20 | 0/10 | 0.00 [-0.16, 0.28] | 7/20 | 8/10 | **+0.45 [+0.07, +0.67]** |

**Answer.** On Clark, no configuration effect for any of the seven: five were 0 under both, and the
other two moved by one or two draws. On St. Johns, two effects are claimed by the rule: Qwen3 Coder,
+0.45 [+0.07, +0.67], and GLM-5.2, +0.50 [+0.01, +0.91], the second against a v1 cell of 2 draws.
kimi-k2-thinking's v1 Clark cell without its host-error draw (deviation 2) is 2/9, and the
difference is then -0.22 [-0.55, +0.10]: no change. At these sizes an effect smaller than about 54
points (10 draws against 20) or 63 (10 against 10) would not be detected, so "no effect claimed" is
not "no effect". Kimi K2 Thinking's St. Johns difference is not claimed as scored, and would be with
the draws that crash on the `html` parameter patched (below).

## Question 5: the hint

Clark, hint minus baseline, Newcombe intervals, for the 15 models the hint arm ran on (the cheap tier
and the seven v1 models; cut 1 removed the mid tier).

| model | baseline | hint | hint - baseline |
|---|---:|---:|---:|
| Claude Haiku 4.5 | 0/10 | 2/10 | +0.20 [-0.11, +0.51] |
| GPT-6 Luna | 2/20 | 2/10 | +0.10 [-0.15, +0.42] |
| GLM-5.3 Flash | 15/19 | 9/9 | +0.21 [-0.11, +0.43] |
| Qwen3.8 Flash | 16/20 | 7/10 | -0.10 [-0.43, +0.19] |
| DeepSeek V4.1 Flash | 10/10 | 9/10 | -0.10 [-0.40, +0.19] |
| MiMo V2.6 Flash | 13/20 | 6/10 | -0.05 [-0.38, +0.27] |
| DeepSeek V4 Pro (Apr) | 0/10 | 1/10 | +0.10 [-0.19, +0.40] |
| DeepSeek V4 Flash | 2/20 | 1/10 | 0.00 [-0.22, +0.31] |
| Kimi K2 Thinking | 0/10 | 1/10 | +0.10 [-0.19, +0.40] |
| Gemini 3.5 Flash-Lite, Hunyuan 3, GLM-5.2, gpt-oss-120b, Qwen3.5 Flash, Qwen3 Coder | 0/10 | 0/10 | 0.00 [-0.28, +0.28] |

**Answer.** No hint effect is claimed for any of the 15. The minimum detectable difference is about
63 points at 10 draws against 10. The hint and baseline arms of a model were not always served by the
same hosts. The arms ran on largely different hosts for DeepSeek V4 Flash (hint on OpenInference,
baseline on Baidu; failure case 10), DeepSeek V4.1 Flash, DeepSeek V4 Pro (Apr), GLM-5.2 and Qwen3
Coder, and partly so for GLM-5.3 Flash and gpt-oss-120b (hosts per arm in `spikes/v2_results.py`,
"Question 5"). For those models the difference is a host comparison as well as a prompt one.

## Field-level pass@1 (deviation 4)

Of the perfect draws, those that also agree on every field of every matched record: **Clark 198 of
200, Santa Barbara 63 of 64, St. Johns 121 of 160.** On St. Johns the disagreements are whole columns
left empty: address in 32 draws, structure code 27, issue date 25, contractor 1. Cells that change:

| target | model: pass@1 → field-level |
|---|---|
| Clark | MiMo V2.6 Flash 13/20 → 12/20; Qwen3.8 Flash 16/20 → 15/20 |
| Santa Barbara | Gemini 3.5 Flash-Lite 4/5 → 3/5 |
| St. Johns | Gemini 3.8 Flash 10/10 → 3/10; DeepSeek V4 Pro 7/10 → 2/10; MiMo V2.6 Pro 5/10 → 1/10; Qwen3 Coder 8/10 → 4/10; Claude Sonnet 5 9/10 → 6/10; DeepSeek V4.1 Flash 9/10 → 6/10; Grok 4.7 6/7 → 4/7; MiMo V2.6 Flash 4/10 → 2/10; gpt-oss-120b 10/10 → 8/10; and one draw each for GPT-6 Luna, GPT-6 Sol, Hunyuan 3, Kimi K2 Thinking, Kimi K3, Qwen3.8 Flash, Qwen3.8 Max |

No answer to questions 1-3 changes under the field-level rule (81 separable pairs, 13 reversals, the
same one model each way on question 3). St. Johns' rates, which enter only question 4, are the ones
the rule moves.

## St. Johns (development target)

Baseline pass@1, beside field-level: GLM-5.3 Flash 3/3 (time-boxed), MiMo V2.6 Flash 4/10 (2), DeepSeek
V4.1 Flash 9/10 (6), Qwen3.8 Flash 8/10 (7), GPT-6 Luna 3/10 (2), Hunyuan 3 5/10 (4), MiMo V2.6 Pro 5/10
(1), MiniMax M3 9/10 (9), Gemini 3.5 Flash-Lite 9/10 (9), DeepSeek V4 Pro 7/10 (2), Gemini 3.8 Flash
10/10 (3), GLM-5.3 2/2 (excluded draws 2-4 were also perfect: 5/5 counting them), Grok 4.7 6/7 (4),
Claude Haiku 4.5 9/10 (9), Qwen3.8 Max 8/8 (7), Claude Sonnet 5 9/10 (6), GPT-6 Sol 1/10 (0), Kimi K3 4/7
(3), Claude Opus 5.5 8/10 (8). Intervals and costs are in `tables.html`.

## Reporting additions (not pre-registered)

None of these changes an answer above.

**Missing draws, by cause.** Never attempted, cut by a process's spend limit (missing by design and
independent of outcome, since a limit stops on spend, not results): Grok 4.7 Clark draws 13-19 and
St. Johns 7-9, Kimi K3 St. Johns 7-9, Qwen3.8 Max St. Johns 8-9, GLM-5.3 Clark 10-19 and St. Johns 5-9
(left cut by amendment 4), GLM-5.3 Flash Clark hint 9 and St. Johns 4-9 (then time-boxed, deviation
3). Cut by the clock: GLM-5.3 St. Johns 2-4, bought after the cutoff and excluded (deviation 5). Lost
to host failures after their retry, with bounds:
GLM-5.3 Flash Clark baseline 15/19, between 15/20 [0.53, 0.89] and 16/20 [0.58, 0.92]; St. Johns 3/3,
between 3/4 [0.30, 0.95] and 4/4 [0.51, 1.00]. No claim changes between the bounds. Excluded: GLM-5.3
St. Johns draws 2-4, as above.

**Reliability.** pass@k (at least one of k works) and pass^k (all k work), Clark baseline, from the
draws bought:

| model | pass@1 | pass@3 | pass^3 | pass^5 | silent rate | time per success |
|---|---:|---:|---:|---:|---:|---:|
| DeepSeek V4.1 Flash, DeepSeek V4 Pro, Qwen3.8 Max, Kimi K3 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 122 s, 366 s, 1,016 s, 129 s |
| Gemini 3.8 Flash | 0.95 | 1.00 | 0.85 | 0.75 | 0.00 | 135 s |
| Grok 4.7 | 0.92 | 1.00 | 0.77 | 0.62 | 0.00 | 646 s |
| Claude Opus 5.5 | 0.90 | 1.00 | 0.72 | 0.55 | 0.05 | 27 s |
| Qwen3.8 Flash | 0.80 | 1.00 | 0.49 | 0.28 | 0.10 | 1,263 s |
| GLM-5.3 Flash | 0.79 | 1.00 | 0.47 | 0.26 | 0.11 | 1,784 s |
| GLM-5.3 | 0.70 | 0.99 | 0.29 | 0.08 | 0.20 | 618 s |
| MiMo V2.6 Flash | 0.65 | 0.97 | 0.25 | 0.08 | 0.15 | 471 s |
| MiMo V2.6 Pro | 0.60 | 0.95 | 0.19 | 0.05 | 0.20 | 755 s |
| Claude Sonnet 5 | 0.30 | 0.68 | 0.02 | 0.00 | 0.65 | 105 s |
| GPT-6 Luna | 0.10 | 0.28 | 0.00 | 0.00 | 0.30 | 257 s |

pass@k assumes something picks the working draw. The offline verifier of the
[agentic extractor plan](2026-09-29-agentic-extractor-plan.md), re-run on all 836 scored draws, does
that with 0.7% [0.2, 2.0] of its accepted extractors failing the scorer and 3 of 427 perfect ones
rejected. pass^k is what an unattended pipeline that redraws each time gets: four models at 1.00, and
the rest fall fast.

**Minimum detectable effects** at 80% power, two-sided 5%, near a 50% rate: 63 points at 10 against
10, 54 at 10 against 20, 44 at 20 against 20.

**Unit of generalization.** Every interval is over draws of one task on one portal. A claim about
portals in general needs more portals and a two-level bootstrap; the three targets are not pooled.

**False discovery among settled rankings** (exploratory): over the 402 settled pairs on the page
(every target and arm), the expected number of wrong calls is 1.1; over the 73 settled roster pairs
on Clark it is 0.15.

## The `html` parameter (not pre-registered)

Found 2026-10-02, after the run, while reading why GPT-6 Sol failed every Clark draw
([failure cases](../design/failure-cases.md), case 11). The answers above stand as scored: the
prompt is part of the protocol, and v1's and v2's both name the parameter `html`. What follows is
what the prompt cost, from `python spikes/v2_name_clash.py`, with no model calls.

**What happens.** The prompt asks for `def extract(html: str)`, asks for HTML entities to be decoded
(rule 1), and allows the `html` module, whose `unescape` decodes them. Inside `extract` the name
`html` is the page. A module that does `import html` and then calls `html.unescape` inside
`extract`, or in a helper defined inside it, calls it on a string and raises `AttributeError: 'str'
object has no attribute 'unescape'`. GPT-6 Sol's Clark draw 0 defines, inside `extract`, a helper
named `html_module_unescape` whose body is `return html.unescape(value)`.

**How often.** 62 of the 833 scored v2 draws, from 8 of the 26 models: Hunyuan 3 22, GPT-6 Sol 13,
Kimi K2 Thinking 12, GPT-6 Luna 7, Qwen3.5 Flash 5, and one each for DeepSeek V4.1 Flash, MiniMax M3
and Grok 4.7. 44 are baseline draws and 18 hint draws; v1 adds 9. Of the 62, 37 call the module from
a helper defined inside `extract`, 16 in `extract` itself, and 9 try to reach it under another name
from inside `extract`, which gets the page again or a name never defined (GPT-6 Sol 5, GPT-6 Luna 4).

**The other 18 models.** Read from the syntax tree of each stored v2 baseline module, they reach the
module some other way: Claude Opus 5.5 imports it under an alias in 35 of 35 (`import html as
_html`), Gemini 3.8 Flash names the parameter something else in 29 of 35 and Gemini 3.5 Flash-Lite
in 21 of 24, and others use `from html import unescape` or call it only from helpers at module
level, where `html` is still the module. GPT-6 Sol imports it under an alias in 1 of its 24 stored
modules. These are counts under one prompt; whether a model does the same under another is not
tested.

**Re-scored with that one reference patched.** Each of the 62 draws was re-run with
`import html as _htmlmod` added and the hidden references pointed at it, nothing else changed, and
scored as a v2 draw is scored. 28 pass (25 of the 44 baseline draws), 21 still raise and 13 run but
miss records. This is what these draws would have scored without the clash, not what a prompt with
another parameter name would draw. Cells that change, pass@1 with field-level in parentheses:

| target | model | as scored | patched |
|---|---|---:|---:|
| Clark | GPT-6 Sol | 0/10 (0) | 2/10 (2) |
| Clark | Hunyuan 3, hint | 0/10 (0) | 3/10 (3) |
| Santa Barbara | DeepSeek V4.1 Flash | 0/5 (0) | 1/5 (1) |
| Santa Barbara | GPT-6 Luna | 2/5 (2) | 3/5 (3) |
| Santa Barbara | GPT-6 Sol | 3/5 (3) | 4/5 (4) |
| Santa Barbara | Hunyuan 3 | 1/5 (1) | 3/5 (3) |
| St. Johns | Hunyuan 3 | 5/10 (4) | 10/10 (9) |
| St. Johns | Kimi K2 Thinking | 3/10 (2) | 10/10 (7) |
| St. Johns | Kimi K2 Thinking, v1 | 0/2 | 1/2 |
| St. Johns | Qwen3.5 Flash | 3/10 (3) | 6/10 (6) |
| St. Johns | Qwen3.5 Flash, v1 | 10/20 | 13/20 |
| St. Johns | GPT-6 Sol | 1/10 (0) | 2/10 (0) |
| St. Johns | MiniMax M3 | 9/10 (9) | 10/10 (10) |
| St. Johns | Grok 4.7 | 6/7 (4) | 7/7 (4) |

**The questions, recomputed with the patched rates.**

- Question 1: 78 separable pairs, not 81. GPT-6 Sol at 2/10 [0.06, 0.51] now overlaps GLM-5.3,
  MiMo V2.6 Flash and MiMo V2.6 Pro. The two groups stand.
- Question 2: 14 reversals, not 13. The new one is GPT-6 Sol ($10 per M output tokens), at $0.110
  per success [0.043, 0.389], over GLM-5.3 ($4.40) at $0.543 [0.426, 0.957]. Sol's draws cost $0.022
  each.
- Question 3: Spearman's rho 0.06 [-0.41, 0.55], not 0.17 [-0.30, 0.65]. DeepSeek V4.1 Flash's Santa
  Barbara cell goes to 1/5, so no model passes Clark reliably and fails Santa Barbara reliably;
  Claude Haiku 4.5 still does the reverse.
- Question 4: Kimi K2 Thinking on St. Johns goes from +0.30 [-0.39, +0.60] to **+0.50 [+0.01,
  +0.91]**, which the rule would claim, against a v1 cell of 2 draws like GLM-5.2's. Qwen3.5 Flash's
  -0.20 becomes -0.05 [-0.38, +0.27]. Clark does not change.
- Question 5: Hunyuan 3's hint difference goes from 0.00 to +0.30 [-0.04, +0.60], not claimed.

**GPT-6 Sol on Clark, the rest of the way.** Patched, 2 of its 10 Clark draws pass. The other 8, 3
of which never had the clash, agree with the reference on the 52 pages without a temporary permit
and raise on the 5 with one. A temporary permit's row (`26TMP-`) puts its number in a span whose id
ends `lblPermitNumber`; an issued permit's ends `lblPermitNumber1`. The Clark excerpt in the prompt
has only issued permits. Sol's extractors key on the issued permit's span and raise when a row lacks it,
as the prompt asks ("if the structure you keyed on is absent, raise"). Across all models, 25 of the
28 patched Clark v2 draws that still fail do so only on those 5 pages.

**What it changes.** Passes lost to it, v1 included: Hunyuan 3 10, Kimi K2 Thinking 8, Qwen3.5
Flash 6, GPT-6 Sol 4, and one each for the other four models. Their cells above understate what
their extractors did apart from this one name. A parameter name no allowed module shares (`page`,
say) is a candidate change for the next protocol. In an agent loop the clash costs a turn, not the
draw: the traceback names it.

## Exploratory

**The caption table.** Clark's grid carries a small layout table inside its first row (the "Showing
1-10 of 100+" bar). An extractor that takes the grid and stops at the first `</table>` stops before
any permit. Of the 112 v2 Clark draws that returned nothing on some page, **84 return matching rows on
every page once that one table is removed**, and 18 then pass outright; the other 66 fail in a second
way as well.

**Reasoning length by outcome**, median reasoning tokens over every scored v2 draw: perfect 18,424;
silent but partial 8,501; raised or format failure 6,758; silently empty 842. The hint changes a
model's median reasoning length by a median factor of 1.11 (12 models with reasoning counts), from
0.61 (MiMo V2.6 Flash) to 9.47 (DeepSeek V4 Flash, whose hint draws ran on another host; case 10).

**deepseek-v4-flash by host.** Clark baseline 2/18 on Baidu and 0/2 on StreamLake; Clark hint 1/9 on
OpenInference and 0/1 on StreamLake; St. Johns 5/10, all OpenInference. 13 of the 19 OpenInference
draws broke the output contract, against none of 817 draws on any other host
([failure cases](../design/failure-cases.md), case 10). Reported, not corrected.

## Method appendix

Settings per model are in `permits/models.py` and recorded per draw; hosts per model and per arm,
re-draws, host failures and spend on failed calls are printed by `spikes/v2_results.py` ("Method
appendix"). Re-draws after a cut-off: GLM-5.3 10, GLM-5.3 Flash 10, Qwen3.8 Flash 12, and one each for
MiniMax M3, GLM-5.2 and Qwen3.5 Flash. Host failures after a retry: 2, both GLM-5.3 Flash. Failed
calls: 29 over the run, 7 of them billed ($0.08), all 7 GLM-5.3 Flash streams cut by GMICloud, Io Net
and SiliconFlow; the rest were API errors (11, 7 of them Gemini 3.8 Flash), 1-hour timeouts (5, GLM-5.3
Flash), rate limits (2), responses with no usage (3) and a dropped connection (1).

## What this does not establish

**Accuracy.** A pass is agreement with a hand-written adapter on every saved page, not correctness
against the portal. The held-out references were checked by hand (pre-registration), the development
ones were not re-checked for this run.

**Rankings within the top group.** On Clark, twelve models are inseparable at these n. The ranking
claims that are settled are about cost per success, not pass rate.

**Generalization beyond three portals.** Santa Barbara is one held-out Accela tenancy at 5 draws per
model; its rank correlation with Clark has an interval from -0.30 to 0.65. Polk County and Oregon,
held back, are the next test.

**The absence of configuration or hint effects.** Effects smaller than 54-63 points would not be
detected. The hint arm ran on 15 models, not the mid or top tier.

**Host-independence.** Some models' arms were served by different hosts, and one host's draws of one
model (case 10) behave unlike the same model elsewhere. The routing rules were fixed before the run;
whether a host serves the model it lists is not checked by anything here.

**Cost at other prices or settings.** Costs are what each draw cost to buy at the run's prices and
each lab's default reasoning level; a different effort level changes both the rate and the cost.

**Rates under another prompt.** Every draw had one prompt, and its parameter name collides with a
module it allows ("The `html` parameter"). A model's rate here includes what that cost it.
