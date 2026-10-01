# The v2 run after stage 1: the host-failure search, and stages 2 and 3 re-projected

Date:      2026-09-29
Produced:  `python spikes/v2_stage1_audit.py`
Inputs:    `data/infer/ledger.jsonl` (600 protocol v2 calls, the last at 2026-09-29 14:07 UTC),
           `data/infer/variance.json` (64 v2 cells)
Outputs:   none; the script prints
Status:    Draft, written while stage 1's last cells ran. Stage 1 is now closed: glm-5.3-flash's
           cells are time-boxed at their completed draws (pre-registration, deviation 3), and
           glm-5.2's Clark hint cell is held until the re-projection after stage 2, since cut 2
           would remove it. Proposals 1 and 5 are decided. The figures are as of stage 1's
           close, from the same script.

Follows the [step 6 pre-registration](2026-09-27-v2-run-preregistration.md), which asks for two
checks between stages. Deviation 2 says the ledger is searched again for streams a host closed early,
on every model, before stage 1's results are used. "Funding, stages and the spend cap" says stages 2
and 3 are re-projected from measured tokens before they are funded, and cells are cut in a fixed order
if the run no longer fits the $45 cap.

## Questions

1. Did any model other than glm-5.3-flash have a stream closed early, scored as the model's answer?
2. Which hosts failed glm-5.3-flash, how, and at what cost?
3. With measured costs in place of assumed ones, does the rest of the run fit the $45 cap, and if not,
   which pre-registered cuts make it fit?

## Method

`spikes/v2_stage1_audit.py` reads the ledger and the variance cells. It sends nothing and costs
nothing.

- **The search.** Every successful v2 call with no stop reason and fewer output tokens than its
  `max_tokens`, which is the `infer.cut_by_host` rule applied after the fact.
- **Failed calls** are grouped by model, host and kind:
  - *host cut*: `_HostError` with tokens, a stream closed with usage but no finish reason;
  - *no usage*: `_HostError` with no tokens, a stream that ended with no usage block;
  - *1 h timeout*: `APIError` after at least 3,000 s. The client gives up at 3,600 s.
  - rate limits and connection errors.
- **The re-projection.** The pre-registration projected from assumed output tokens for 16 of 26
  models. Each mid and top model now has one measured draw, its smoke draw, which is draw 0 of its
  Clark cell. Stage 1 shows how well one draw predicts a model's whole bill. For each of the 15
  stage 1 models with at least 10 scored draws, the script divides the mean cost per scored draw by
  the first Clark draw's cost. Failed calls and both attempts of a re-drawn draw are included, so
  the ratio covers every target and the cell's variance.
  - Typical projection: a model's first-draw cost × the median ratio.
  - Heavy projection: the same cost × the 90th-percentile ratio.
  - Stage 1's remaining draws are costed at the model's own measured mean.
  - Worst is the pre-registration's definition: every call at the 64,000 cap, at the registry's
    price ceiling, and every two-stage cell at 20 draws.
- **Draws per cell.** A two-stage Clark cell is expected to take 10 + 10 × (share of stage 1 Clark
  cells that did not stop at 10).
- **The cap.** Spent so far, plus the projected cost of every draw still to buy, with the
  pre-registered cuts applied cumulatively in the pre-registered order.

## Result

### 1. The search: no other model was affected

572 successful v2 calls stopped on `end_turn` or `max_tokens`, and 8 stopped on neither. All 8 are
glm-5.3-flash calls cut at 301 s on AtlasCloud (2) or 602 s on Phala (6). They are the calls
deviation 2 describes, and their draws were superseded and re-bought under the new routing. No other
model has a call that meets the rule.

### 2. Failed calls: 20, seven of them billed, $0.078

| model | host | kind | calls | output tokens | billed | seconds |
|---|---|---|---:|---:|---:|---|
| glm-5.3-flash | Io Net | host cut | 3 | 83,933 | $0.0433 | 1,801, 1,801, 379 |
| glm-5.3-flash | GMICloud | host cut | 3 | 90,815 | $0.0292 | 603, 602, 619 |
| glm-5.3-flash | SiliconFlow | host cut | 1 | 8,911 | $0.0055 | 219 |
| glm-5.3-flash | none recorded | 1 h timeout | 5 | 0 | 0 | 3,600 to 3,615 |
| glm-5.3-flash | none recorded | connection | 1 | 0 | 0 | 1,416 |
| deepseek-v4-flash | none recorded | no usage | 2 | 0 | 0 | 766, 1,555 |
| deepseek-v4.1-flash | none recorded | no usage, api error | 2 | 0 | 0 | 769, 51 |
| gpt-oss-120b | none recorded | api error | 1 | 0 | 0 | 56 |
| qwen3.8-flash | none recorded | rate limit | 2 | 0 | 0 | 46, 50 |

Every host cut and every timeout was glm-5.3-flash's. Io Net and GMICloud cut every glm-5.3-flash
call they served (3 of 3 each), at what look like fixed limits: 1,800 s on Io Net, apart from one
call at 379 s, and 602 s on GMICloud. SiliconFlow cut 1 of its 11 calls at 219 s and completed the other
ten in 440 s to 1,276 s, so its cut is not a fixed limit. The timeouts and the connection error
carry no host, because the call never returned the chunk that names one.

A failed call is retried once under the same draw number. Two draws failed twice, both
glm-5.3-flash's (Clark draw 11, St. Johns draw 0). Their cells are closed at their completed draws
(pre-registration, deviation 3), so they are not retried; each is reported with best- and
worst-case bounds.

**A stop at 32,768 tokens on SiliconFlow (12:25 and 13:02 UTC).** Clark draws 14 and 16 were
served by SiliconFlow, which stopped both at exactly 32,768 output tokens and reported `max_tokens`,
although the request set 64,000. SiliconFlow's endpoint listing gives 262,144, and it completed four
other glm-5.3-flash calls past 32,768 (40,151 to 53,880 tokens) at the same 64,000 request, so this
is not a fixed limit either. The harness read the stop as truncation and re-drew each at 128,000
under amendment 2, so both were scored on a complete answer. The rule held, but a stop below the
requested cap is new: it gives those draws a second attempt that other draws did not get. Every other `max_tokens` stop in the v2 ledger is at 64,000.
`spikes/v2_stage1_audit.py` now checks for this in section 1.

### 3. The re-projection

**Stage 1** cost $10.45: $7.13 on the cheap tier and $3.32 on the v1 models. The
pre-registration projected $6.04 typical and $12.44 heavy for the whole stage. Its 10 remaining
draws, glm-5.2's Clark hint cell, are held until the re-projection after stage 2, since cut 2 would
remove them, and are projected at $0.79. **10 of 15 finished Clark cells stopped at 10 draws**, so a two-stage
cell is expected to take 13.3 draws. The pre-registration predicted 13.7 from the v1 rates.

**One draw against the whole bill.** Across the 15 stage 1 models, mean cost per draw divided by
the first Clark draw has a median of **0.85** and a 90th percentile of **1.25**:

| ratio | models |
|---|---|
| 0.57 to 0.71 | qwen3.8-flash, glm-5.3-flash, mimo-flash, luna, flash-lite, glm-5.2 |
| 0.82 to 1.06 | hy3, deepseek-v4.1-flash, kimi-k2-thinking, qwen3-coder, qwen3.5-flash, haiku |
| 1.25 and 1.38 | deepseek-v4-pro, gpt-oss-120b |
| 7.70 | deepseek-v4-flash, whose first draw cost $0.0009 against a mean of $0.0067 |

A first draw overstates the bill more often than it understates it, because smoke draws tended to be
long ones.

**Stages 2 and 3**, projected from each model's smoke draw, with cut 1 applied (no hint arm on
the mid tier):

| model | tier | smoke draw | output tokens | typical | heavy | worst |
|---|---|---:|---:|---:|---:|---:|
| sonnet-5 | mid | $0.0705 | 3,446 | $1.64 | $3.01 | $22.74 |
| gpt-6-sol | mid | $0.0342 | 1,328 | $0.79 | $1.46 | $37.78 |
| gemini-3.8-flash | mid | $0.0917 | 22,601 | $2.13 | $3.91 | $12.60 |
| deepseek-v4-pro-0813 | mid | $0.1280 | 29,261 | $2.97 | $5.46 | $13.54 |
| mimo-v2.6-pro | mid | $0.0198 | 18,227 | $0.46 | $0.84 | $3.04 |
| minimax-m3 | mid | $0.0128 | 8,466 | $0.30 | $0.55 | $4.05 |
| opus-5.5 | top | $0.1204 | 2,412 | $2.79 | $5.13 | $45.48 |
| grok-4.7 | top | $0.3338 | 66,437 | $7.75 | $14.23 | $16.50 |
| kimi-k3 | top | $0.0802 | 7,862 | $1.86 | $3.42 | $50.31 |
| glm-5.3 | top | $0.1698 | 40,785 | $3.94 | $7.24 | $34.13 |
| qwen3.8-max-0902 | top | $0.2478 | 40,647 | $5.75 | $10.57 | $20.52 |

| stage | typical | heavy | pre-registered typical / heavy |
|---|---:|---:|---|
| 2: mid, after cut 1 | $8.29 | $15.22 | $10.96 / $26.49, with the hint arm |
| 3: top | $22.09 | $40.59 | $18.05 / $46.84 |

Without cut 1, stage 2 would be $11.32 typical and $19.70 heavy, close to its pre-registered
typical projection. Stage 3 comes in higher, mostly
because of grok-4.7, whose smoke draw ran past the cap to 66,437 tokens (deviation 1). The
pre-registration assumed 10,000 tokens for it.

**Against the cap.** The whole run is the $11.76 spent so far plus everything still to buy, with the
pre-registered cuts applied cumulatively:

| cuts applied | typical | heavy |
|---|---:|---:|
| none | $45.96 | $72.84 |
| 1. the hint arm on the mid tier | **$42.92** | $68.36 |
| 2. the v1 re-runs of kimi-k2-thinking and glm-5.2 | $42.14 | $67.57 |
| 3. St. Johns for the top tier, 10 draws to 5 | $38.10 | $61.60 |
| 4. Clark for the top tier stops at 10 | $35.40 | $49.66 |

Cut 2 now saves only $0.79, because kimi-k2-thinking's re-run is fully bought, and so is all of
glm-5.2's except the Clark hint cell.

## What this establishes

- **Deviation 2's search is done for stage 1 to date.** The only calls with no stop reason under the
  cap are the eight glm-5.3-flash calls it already covers. No other model's draws need re-buying.
- **The host failures are one model's, on a small set of hosts.** Io Net and GMICloud cut
  glm-5.3-flash at fixed durations, like AtlasCloud and Phala before them, and those four hosts
  account for every stream cut of that model but one, SiliconFlow's at 219 s.
- **On the typical projection, the run fits the cap after the first pre-registered cut**, dropping
  the mid tier's hint arm. The pre-registration tested the cap against the typical projection: its
  own heavy projection, $85.77, was already over $45 when it was registered, and no cut was made.
- **Stage 1 cost between its typical and heavy projections**, and the two-stage rule saved about what
  was predicted.

## Proposed for stages 2 and 3, for decision before any spend

1. **Apply cut 1.** Drop the Clark hint cells for the six mid-tier models, and report the cut.
   Stage 2 is then projected at $8.29 typical and $15.22 heavy. *Decided 2026-09-29: applied, and
   recorded in the pre-registration under "Cuts under the cap".*
2. **Re-project again after stage 2**, from stage 2's measured costs, and apply cuts 2 to 4 in order
   if stage 3 no longer fits. The pre-registration re-projects once. Re-projecting before each stage
   uses the same rule with better data, and is reported as a deviation.
3. **Keep the cap hard.** Each stage's `--max-spend` totals, across its parallel processes, no more
   than the $45 cap minus what has been spent. A cell stopped by the ceiling is reported as cut.
4. **Routing for glm-5.3 (stage 3).** Exclude the four hosts that cut glm-5.3-flash's streams,
   AtlasCloud, Phala, GMICloud and Io Net, since all four also serve glm-5.3. SiliconFlow is a fifth
   candidate: it cut one glm-5.3-flash call and stopped two at 32,768 tokens. The evidence
   is from the flash model, so this rests on the limits being per host and not per model. Routing
   is part of the request, so glm-5.3's smoke draw is re-bought under the new routing, about $0.17.
5. **glm-5.3-flash's remaining stage 1 draws.** *Decided 2026-09-29: not re-run.* Its three
   incomplete cells are closed at their completed draws (pre-registration, deviation 3): Clark
   baseline 15/19, Clark hint 9/9, St. Johns 3/3. Its draws take 11-44 minutes each, so finishing
   St. Johns alone would take over five hours, and no claim changes between the best- and worst-case
   bounds on the two draws lost to host failures. The same time box applies to any cell incomplete
   at the end of stage 3, with its cutoff set before stage 3 starts.
6. **Time.** grok-4.7's smoke draw took 772 s and qwen3.8-max-0902's 1,046 s, so a 20-draw Clark
   cell for either runs about four to six hours in sequence. Stage 3 needs a connection that stays
   up for that long, not the two hours the pre-registration estimated.

## What this does not establish

- **The mid and top projections rest on one draw per model.** The ratio that scales them is measured
  on cheap and v1 models, and a top model's draws may vary more or less around its first than a
  cheap model's do. The heavy column is the 90th percentile of 15 ratios, not a bound. The worst
  column, and `--max-spend`, are the bound.
- **Anthropic first draws include the 1.25× cache write**, and later draws read the cache at a tenth
  (a twentieth on Opus 5.5). Scaling from the first draw slightly overstates Sonnet 5 and Opus 5.5.
- **The host exclusion for glm-5.3 is inferred from glm-5.3-flash.** No glm-5.3 call has been cut
  yet. Its one call ran on Sail Research. A host could limit one deployment and not another:
  AtlasCloud completed a 412 s call for deepseek-v4-pro-0813, past the 301 s at which it cut
  glm-5.3-flash.
- **The timeouts are not attributed.** Five one-hour timeouts carry no host, so how they split across
  hosts is unknown, and they are not counted against any host above.
- **Stage 1 is not finished**, and these are the figures at 12:12 UTC. The remaining 25 draws are
  glm-5.3-flash's and glm-5.2's. They can move the stage 1 totals and the Clark stopping share, but
  not the ratio's median much, since both models already have 10 or more draws.
