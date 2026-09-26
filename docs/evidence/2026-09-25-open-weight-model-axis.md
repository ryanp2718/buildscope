# Cost per success across a 90x price band: the rule holds, the inversion is partly vintage

Date:      2026-09-25 (revised 2026-09-26, before first commit; see "Revisions")
Produced:  `python scripts/conformance.py --run --cells ...`, then
           `python scripts/model_stats.py`, then
           `python spikes/open_weight_axis_tables.py`
Inputs:    `data/infer/variance.json` (variance cells, 2026-09-21 to 2026-09-26),
           `data/infer/ledger.jsonl` (priced calls, both providers; 266 rows)
Outputs:   `data/infer/model_stats.csv` (long format),
           `data/infer/model_stats.json` (per-cell aggregates with Wilson intervals)
Status:    Current.
           Cell figures pinned by `tests/test_model_stats.py::TestOpenWeightAxisFigures`.

## What changed

The 2026-09-22 report established that cost per success, not cost per token, is the quantity that
ranks models correctly. It established that over a 5x price band: Haiku 4.5, Sonnet 5, Opus 5.

A 5x band is narrow enough that the finding could be an artifact of three closely-related models from
one vendor. This run widens the band to roughly 90x by adding OpenRouter as a second provider and
eight open-weight models, and re-asks the same question.

The rule holds: ranking by cost per success and ranking by cost per token disagree, and the first is
the one that picks a working extractor. What does not fully hold is the 2026-09-22 corollary that the
expensive model is the cheap one on a hard page. On Clark, Opus 5 is cheaper per success than Haiku,
Sonnet and the three cheap models released in 2025 (which never succeed there). It is more expensive
per success than kimi-k2-thinking (1.6x) and the two current-generation cheap models (5x and 20x).

**Read this with the 2026-09-26 audit.** Output ceilings, reasoning settings, sampling and serving
host all vary by vendor in these runs, so each cell measures a model under its own configuration,
not a controlled comparison. The audit lists each difference and which way it cuts.

## Result

Success means perfect agreement with the hand-written adapter on every page of the target's corpus.
Anything less is a failure. `recall` is the mean fraction of reference records returned, over draws
whose extractor ran on every page; it is shown for Clark because it is what the pass rate hides
there. Spend is what the cell's draws cost to buy, joined from the ledger, including draws later
replayed from the cache. Intervals are Wilson 95%.

| target | model | provider | n | perfect | rate [95% CI] | recall | spend | **$ / success** |
|---|---|---|---:|---:|---|---:|---:|---:|
| St. Johns (WATS) | gpt-oss-120b | OpenRouter | 20 | 18 | 90% [70, 97] | - | $0.0183 | **$0.001016** |
| St. Johns (WATS) | qwen3.5-flash | OpenRouter | 20 | 10 | 50% [30, 70] | - | $0.0679 | **$0.006789** |
| St. Johns (WATS) | qwen3-coder | OpenRouter | 20 | 7 | 35% [18, 57] | - | $0.0526 | **$0.007514** |
| St. Johns (WATS) | Haiku 4.5 | Anthropic | 15 | 15 | 100% [80, 100] | - | $0.4987 | **$0.033244** |
| St. Johns (WATS) | Sonnet 5 | Anthropic | 5 | 5 | 100% [57, 100] | - | $0.3804 | **$0.076076** |
| Clark (Accela) | glm-5.3-flash | OpenRouter | 10 | 2 | 20% [6, 51] | 0.995 | $0.0283 | **$0.014129** |
| Clark (Accela) | deepseek-v4-flash | OpenRouter | 10 | 1 | 10% [2, 40] | 0.250 | $0.0566 | **$0.056620** |
| Clark (Accela) | kimi-k2-thinking | OpenRouter | 10 | 2 | 20% [6, 51] | 0.498 | $0.3476 | **$0.173813** |
| Clark (Accela) | Opus 5 | Anthropic | 3 | 3 | 100% [44, 100] | 1.000 | $0.8575 | **$0.285831** |
| Clark (Accela) | Sonnet 5 | Anthropic | 12 | 2 | 17% [5, 45] | 0.991 | $0.6432 | **$0.321613** |
| Clark (Accela) | Haiku 4.5 | Anthropic | 20 | 1 | 5% [1, 24] | 0.310 | $0.6863 | **$0.686275** |
| Clark (Accela) | gpt-oss-120b | OpenRouter | 20 | 0 | 0% [0, 16] | 0.000 | $0.0293 | **undefined** |
| Clark (Accela) | qwen3-coder | OpenRouter | 20 | 0 | 0% [0, 16] | 0.000 | $0.0383 | **undefined** |
| Clark (Accela) | qwen3.5-flash | OpenRouter | 20 | 0 | 0% [0, 16] | 0.270 | $0.0643 | **undefined** |
| Clark (Accela) | deepseek-v4-pro | OpenRouter | 10 | 0 | 0% [0, 28] | 0.000 | $0.2545 | **undefined** |
| Clark (Accela) | glm-5.2 | OpenRouter | 10 | 0 | 0% [0, 28] | 0.989 | $0.2740 | **undefined** |

The St. Johns reasoning-tier cells (glm-5.2 1/2, kimi-k2-thinking 0/2, deepseek-v4-pro 0/1) were
drawn at the old 16,000-token ceiling, before the fix described under "The ceiling was the
measurement". They are too small and too stale to compare, and are left out of the table.

With one or two successes in a cell, one more success or failure moves the cost per success by 30-100%.
The Clark figures for glm-5.3-flash, deepseek-v4-flash and kimi-k2-thinking set an order of
magnitude, not a ranking among the three.

## The cheap tier was also the stale tier

The roster was assembled as a price axis. It is also, unintentionally, a recency axis. Release dates
below are from `openrouter.ai/api/v1/models`, read 2026-09-25.

| model | released | age | in $/M | n | perfect | clarkco |
|---|---|---:|---:|---:|---:|---|
| qwen/qwen3-coder | 2025-07-23 | 14.1 mo | 0.300 | 20 | 0 | 20 draws return zero rows |
| openai/gpt-oss-120b | 2025-08-05 | 13.7 mo | 0.150 | 20 | 0 | 11 return no usable record, 9 raise |
| moonshotai/kimi-k2-thinking | 2025-11-06 | 10.6 mo | 0.600 | 10 | **2** | 1 near miss, 3 zero rows, 3 raise, 1 no code |
| qwen/qwen3.5-flash-02-23 | 2026-02-25 | 7.0 mo | 0.065 | 20 | 0 | 3 near miss, 8 no usable record, 9 raise |
| deepseek/deepseek-v4-pro | 2026-04-24 | 5.0 mo | 0.682 | 10 | 0 | 5 zero rows, 5 raise, no near miss |
| deepseek/deepseek-v4-flash | 2026-04-24 | 5.0 mo | 0.047 | 10 | **1** | 3 zero rows, 3 raise, 3 break the output contract |
| z-ai/glm-5.2 | 2026-06-16 | 3.3 mo | 0.650 | 10 | 0 | 8 near miss, 2 raise |
| z-ai/glm-5.3-flash | 2026-08-26 | 1.0 mo | 0.045 | 10 | **2** | 3 near miss, 1 over-extracts, 4 raise |

The first version of this report stopped at the three cheap models released before 2026, which
together went 0 for 60 on Clark. The two current-generation cheap models, glm-5.3-flash and
deepseek-v4-flash, were added because they sit at the same price as the stale three (glm-5.3-flash
is 3.3x cheaper per input token than gpt-oss-120b) and at the opposite end of the recency axis.
Together they solve Clark on 3 of 20 draws against 0 of 60 for the stale three (Fisher exact,
one-sided p = 0.014). So the old cheap tier's zero on Clark was at least partly its age, not its
price.

Vintage does not explain everything either. kimi-k2-thinking is the third-oldest model here at
10.6 months and solves Clark as often as the newest, 2 in 10. deepseek-v4-pro is five months newer
than kimi and 14% more expensive per input token, and returns zero rows or raises on all ten draws.
Six models have produced a perfect Clark extractor at least once: Opus 5 (3/3), kimi-k2-thinking and
glm-5.3-flash (2/10 each), Sonnet 5 (2/12), deepseek-v4-flash (1/10) and Haiku 4.5 (1/20).

## On the easy page the price list is right

gpt-oss-120b produces a working extractor 18 times in 20 and costs **$0.001016** per working
extractor, against Haiku's $0.033244 and Sonnet's $0.076076. That is **32.7x cheaper than Haiku** and
**74.9x cheaper than Sonnet**.

There is no inversion here. gpt-oss is the cheapest model per token in the comparison and also the
cheapest per success, so cost per token and cost per success agree on the ranking and either would
have picked the right model.

This matters because it is the case the 2026-09-22 report could not see. Within one vendor's lineup
the cheap model was cheap and unreliable, so the two metrics always disagreed. Widen the band and
the disagreement turns out not to be a property of cheapness - it is a property of the page.

## On the hard page, one failure dominates - and it is a near miss

Reported as a pass rate, Clark looks like a cliff. Re-scoring the stored extractors per record shows
most of the failures are one failure.

| model | behaviour on Clark | recall (mean) | precision (mean) | perfect |
|---|---|---:|---:|---:|
| Opus 5 | resolves every row class | 1.000 | 1.000 | 3/3 |
| glm-5.3-flash | near miss, raises, or over-extracts | 0.995 | 0.889 | 2/10 |
| Sonnet 5 | misses one row class | 0.991 | 1.000 | 2/12 |
| glm-5.2 | misses the same row class | 0.989 | 1.000 | 0/10 |
| kimi-k2-thinking | perfect, near miss, zero rows, or raises | 0.498 | 0.500 | 2/10 |
| Haiku 4.5 | perfect, near miss, zero rows, or raises | 0.310 | 0.312 | 1/20 |
| qwen3.5-flash | near miss, no usable record, or raises | 0.270 | 0.273 | 0/20 |
| deepseek-v4-flash | perfect, zero rows, raises, or breaks the contract | 0.250 | 0.250 | 1/10 |
| gpt-oss-120b | no usable record, or raises | 0.000 | 0.000 | 0/20 |
| qwen3-coder | zero rows | 0.000 | 0.000 | 0/20 |
| deepseek-v4-pro | zero rows, or raises | 0.000 | 0.000 | 0/10 |

Recall and precision are means over draws whose extractor ran on every page, so a model that raises
often can show high recall on the draws that did not.

**The near miss.** 33 draws across six models - Sonnet 5 (10), glm-5.2 (8), Haiku 4.5 (4),
qwen3.5-flash (3), glm-5.3-flash (3) and kimi-k2-thinking (1) - return 555 of 561 records at precision
1.000, and every one of the 33 misses the *same* six record-instances on five pages. Those are four
distinct permit numbers, one of which appears on three pages. All four begin `26TMP-`, and every one
is a record with **no detail hyperlink**: a temporary, in-progress application whose permit number
renders as plain text where an issued permit renders as an anchor. The extractors select rows by
that anchor, so rows without one are invisible to them.

The distance between Sonnet 5 at 2/12 and glm-5.2 at 0/10 is which side of a knife-edge criterion each
landed on, not a difference in what they can parse.

**The other failures.** "Zero rows" is an extractor that runs on every page and returns an empty
list. "No usable record" also covers rows with no permit number: gpt-oss-120b does this on 6 draws
and qwen3.5-flash on 4, and it is worse than an empty list because it looks like output. One
glm-5.3-flash draw finds every record and adds 114 that are not records. deepseek-v4-flash breaks the
output contract on 3 draws: two define the parser under another name (`parse_permit_table`,
`extract_permit_records`) and one answers with JSON instead of code. The harness records those as
`refused`, the outcome it also uses for a failed safety audit. They are format failures, not
extraction failures, and not refusals.

So the sentence this report would otherwise carry - that the hard-page failure is total and not a
near miss - is false for six of the eleven models. For those six, Clark's difficulty is mostly one
row class, worth 1.07% of records, that 33 of their draws key past. An all-or-nothing criterion over
561 records turns that 1.07% into a zero.

> **Match the tier to the page, not to the budget - and read the failure before paying to fix it.**
> On easy pages the price list ranks correctly and the cheapest model wins by more than an order of
> magnitude. On hard pages a pass rate stops being informative: it cannot separate a model that
> returns nothing from one that returns 98.93% of the records correctly, and on Clark those two
> outcomes both read as 0%.

## Does telling the model about row state help?

`--synth-hint` appends one general paragraph to the synthesis prompt: grid rows differ in state,
markup follows state, so select by row container rather than by anchor. It names no prefix, column or
jurisdiction. Hinted draws are scored into separate `|hint` cells.

| model | baseline | hint | hinted draws that still drop the 26TMP- rows |
|---|---:|---:|---:|
| glm-5.2 | 0/10 | 1/5 | 3 of 4 failures |
| glm-5.3-flash | 2/10 | 2/5 | 1 of 3 failures |
| deepseek-v4-flash | 1/10 | 0/5 | none; all 5 return zero rows |

Five draws per arm cannot separate a hint effect from noise: for all three models the hinted and
baseline intervals overlap, and the largest move, glm-5.2 from 0/10 to 1/5, has a Fisher exact p of
0.33. The hint did not stop most glm-5.2 failures from keying on the anchor. This is recorded
as a null result at small n, not as evidence either way.

## The silent-failure split, which is not the same as the pass rate

The project's central measurement concern is the failure that produces zero rows and raises nothing,
because it survives a smoke test and reaches production looking like a quiet week at the permit
office. Splitting Clark's baseline draws by `permits.stats.failure_mode`, with contract breaks
separated from loud failures:

| model | perfect | loud | format | **silent, empty** | silent, partial | n |
|---|---:|---:|---:|---:|---:|---:|
| Opus 5 | 3 | 0 | 0 | **0** | 0 | 3 |
| Sonnet 5 | 2 | 0 | 0 | **0** | 10 | 12 |
| glm-5.2 | 0 | 2 | 0 | **0** | 8 | 10 |
| glm-5.3-flash | 2 | 4 | 0 | **0** | 4 | 10 |
| kimi-k2-thinking | 2 | 3 | 1 | **3** | 1 | 10 |
| deepseek-v4-flash | 1 | 3 | 3 | **3** | 0 | 10 |
| deepseek-v4-pro | 0 | 5 | 0 | **5** | 0 | 10 |
| Haiku 4.5 | 1 | 4 | 0 | **11** | 4 | 20 |
| gpt-oss-120b | 0 | 9 | 0 | **11** | 0 | 20 |
| qwen3.5-flash | 0 | 9 | 0 | **8** | 3 | 20 |
| qwen3-coder | 0 | 0 | 0 | **20** | 0 | 20 |

glm-5.3-flash's one over-extracting draw is in "silent, partial": it returned wrong data without
raising.

Across the three stale cheap models, 42 of 60 failures were silent (70%), and **39 of 60 returned no
usable record**: 29 returned no rows at all and 10 returned rows with no permit number. qwen3-coder
returned zero rows on every one of its twenty draws: twenty extractors that import cleanly, run to
completion on all 57 pages, raise nothing, and produce no data. A deployment gated on "did it throw?"
would have shipped all twenty.

The column that matters operationally is **silent, empty**, and it does not order the way price does:

- **glm-5.2 and glm-5.3-flash never once returned an empty result.** Their silent failures are
  partial - all eight of glm-5.2's at 98.93% recall and precision 1.000.
- **Haiku 4.5 returned nothing on 11 of 20 draws** - more often than not.

So on the failure mode this project cares most about, glm-5.2 is *safer* than Haiku 4.5 on Clark,
at a slightly lower cost per draw ($0.027 against $0.034). The pass rate says Haiku 1/20 beats glm 0/10. The
failure taxonomy says the opposite, and the failure taxonomy is the one tied to what goes wrong in
production.

A model that fails loudly costs a retry. A model that fails partially costs a reconciliation. A model
that fails silently and empty costs the data, and you find out a month later.

## The ceiling was the measurement

The first attempt at the reasoning tier produced a clean, wrong result: glm-5.2, kimi-k2-thinking and
deepseek-v4-pro scored 0 on Clark, and 5 of 11 calls stopped at exactly 16,000 output tokens.

OpenRouter bills reasoning tokens and output tokens against the same `max_tokens`. A single ceiling
across the model axis is therefore not a single experiment: a model that thinks answers from what is
left after thinking, and a model that does not answers from all of it. At 16,000, glm-5.2 spent the
entire allowance reasoning on both draws and emitted no extractor either time.

Scored as written, that reads as "reasoning models cannot parse Accela". It is the ceiling appearing
in the results table under a model's name.

`infer.ceiling_for` now holds the *answer* budget constant and adds a 32,000-token thinking allowance
on top for the OpenRouter reasoning models. Re-run at the corrected ceiling, the first draws of the
same three models emitted extractors of 2,953 to 6,105 bytes using 4,415 to 9,466 output tokens. The
models were not spending 16,000 tokens by choice. They were hitting a wall. kimi-k2-thinking's two
perfect Clark draws each used about 20,000 tokens, which only the raised ceiling allowed.

The fix is itself an asymmetry: Claude's thinking budget sits inside its 12,000-token ceiling, while
the OpenRouter reasoning models get up to 48,000. The 2026-09-26 audit records it as F1.

## The price table is a ceiling table

Reconciling every paid OpenRouter call against `OPENROUTER_PRICES` surfaced two independent reasons
the table under-projected, and one reason it only appeared to.

**It only appeared to, for qwen3-coder.** Back-pricing a ledger row off `input_tokens` understated it
by up to 4.5x. `_usage_from_chat` subtracts the cached portion so that both providers' rows mean the
same thing, but a cached read is discounted, not free. The quantity to reconcile against is
`input_tokens + cache_read_input_tokens`. Priced correctly, qwen3-coder reconciles at a mean of 0.57.
This looked exactly like a stale price and was not one.

**Under-reported reasoning.** glm-5.2 billed 2.09x its list projection on 4 of 4 calls and
deepseek-v4-pro 1.26x on 3 of 3, because `completion_tokens` does not include every reasoning token
they are charged for. glm-5.3-flash does the same: 9 of its first 9 calls billed above list, mean
2.40x. kimi-k2-thinking reconciles at exactly 1.00, which is how we know this is a per-model
reporting difference rather than a rule about reasoning models.

**Routing variance.** One OpenRouter model id is not one upstream, and the upstreams do not agree on
price. gpt-oss-120b reconciles at a mean of 0.51 and a max of 1.88. deepseek-v4-flash reconciles at
1.00 on 12 of 15 calls and 4.7-4.8x on the other 3. Those 3 are also the slow ones (15-24 tokens per
second, 22-47 minutes each) and the three contract breaks above. That pattern fits a different
upstream host. The ledger does not record the host, so it cannot be confirmed.

The six glm-5.3-flash draws bought on 2026-09-26 differ from its first four in the same way.
They report either no cached input or 8,512 cached tokens where the first four reported 4,666. They
answered in 500-1,500 output tokens where the first four used 1,900-5,000 (one outlier used
25,350). They went 0 for 6 where the first four went 2 for 4. At these counts that is not
significant (Fisher exact p = 0.13), but it is the pattern an unpinned route produces.

The table's only job is the pre-call worst case in `Budget.check`, where stale-high is safe and
stale-low is not a ceiling at all. It now carries reconciled rates with the list price beside each in
a comment. None of this touches the accounting: the ledger records OpenRouter's reported `usage.cost`
and flags it `usd_reported`, so what is billed comes from the invoice and only what is *authorized*
comes from the table.

## Harness defects found, and which way they cut

Adding a second provider required one validation draw before the grid. That draw surfaced five
defects, and **every one of them turned a working extractor into a recorded failure** - which is to
say, every one of them biased the comparison against the tier being added.

| defect | effect if unfixed |
|---|---|
| `extract_block` took the first fenced block | a 10,236-token reply containing a complete extractor scored as a 144-byte refusal |
| runner did not isolate `stdout` | a module that prints read as an execution failure |
| `extract()` returning a non-list | `TypeError` in the scorer, or a clean zero |
| `api_key=""` collapsed with `None` | tests silently read the real key off disk, and printed part of it into an assertion message |
| UTF-8 BOM in the key file | `Authorization` header carried U+FEFF; the 401 read as a bad key rather than a bad file |

Two more were found on 2026-09-26, in the reporting rather than the measurement:

| defect | effect if unfixed |
|---|---|
| `model_stats.py` grouped cells on (target, model) | hinted draws pooled into baselines: glm-5.2 read 1/15, not 0/10; cost per success summed every call a model had made, including superseded and duplicate purchases |
| two concurrent runs of the glm-5.2 Clark cell | draw 1 bought twice; the cell recorded one response and the cache kept the other. Re-scored from the cache: draw 1 moved from `raised` to the common near miss, and the rate stayed 0/10 |

A defect that turns working extractors into recorded failures is indistinguishable, in the published
table, from a fact about the models. That is the argument for validating one draw before buying 280.

## What this does not establish

- **Agreement is not accuracy.** Success means agreeing with a hand-written adapter, which is itself
  unvalidated against ground truth. A model that is wrong in exactly the way the adapter is wrong
  scores as perfect. The 50-record golden set (ADR-0014, unratified) is the missing control.
- **Configuration is not matched.** Claude runs with a 12,000-token ceiling that includes thinking;
  OpenRouter non-reasoning models get 16,000 and reasoning models 48,000. Reasoning effort is set to
  `medium` on some OpenRouter models, left at the vendor default on others, and adaptive or fixed on
  Claude. Serving host is chosen by OpenRouter's price-weighted routing and not recorded. The
  2026-09-26 audit lists each difference; none of it is controlled here.
- **One prompt, one window.** No prompt engineering was attempted for the open-weight models. They
  were given the prompt tuned for Claude. A tier-specific prompt could move these numbers and nothing
  here bounds by how much.
- **Two portals is not a survey.** WATS and Accela are two vendors. "Easy page" and "hard page" are
  labels attached after the fact to two specific corpora, not a difficulty scale.
- **Cost per success is defined by the success criterion, and on Clark that choice dominates the
  result.** The criterion is perfect agreement across all 561 records. Under it, glm-5.2 scores 0/10.
  Under "recall >= 0.98 at precision 1.0" it scores 8/10 and has a defined, low cost per success.
  Neither criterion is wrong; the first is the right one for an unattended pipeline and the second
  for a pipeline with reconciliation. This report should not be cited for a claim about capability
  without the recall column beside the pass rate.
- **The 26TMP- finding is one corpus.** That four records in 57 pages happen to be the discriminating
  case is a property of this capture, not a general law about Accela. A different capture window
  would contain a different number of them, and the pass rates would move accordingly - which is
  itself a reason to distrust pass rates on small, strict corpora.
- **Small cells stay small.** Clark Opus 5 is n = 3 and is the anchor of the hard-page comparison.
  Every Clark success count outside the Anthropic cells is 0, 1 or 2. Read the intervals, not the
  point estimates.
- **Prices move.** Every dollar figure is as of the date on this report.

## Revisions

This report was revised on 2026-09-26, before it was first committed. The first draft:

- said every model except Opus 5 misses Clark's pending-permit row class, and listed
  kimi-k2-thinking at 0 of 2 in two sections after the cell had reached 2 of 10;
- described qwen3.5-flash's Clark draws as returning rows with every field `None`, which is 4 of its
  20 draws;
- left the reasoning-tier cells, glm-5.3-flash, deepseek-v4-flash and the hint arm out of the
  headline table;
- quoted glm-5.3-flash at 2/3 before its baseline was completed to 10 draws (it is 2/10), and
  kimi-k2-thinking at $0.1644 per success, which divided what the last run paid rather than what
  the cell's draws cost ($0.1738);
- said it was pinned by tests before any test pinned it.

Every figure in this version is printed by the three commands under "Produced".
