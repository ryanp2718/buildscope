# Extractor conformance test: synthesized extractors against the adapters

Date:      2026-09-21
Produced:  `scripts/conformance.py`, `permits/infer.py`, `permits/strip.py`
Inputs:    `data/step1/pages/` (71 index pages: 14 WATS, 57 Accela),
           `data/step1/manifest.csv` (the capture rows that name them),
           `permits/adapters/stjohns.py`, `permits/adapters/accela.py`
           (the reference implementations)
Outputs:   `data/infer/conformance.json` (5 scored cells),
           `data/infer/ledger.jsonl` (12 calls, $1.2751),
           `data/infer/synth/*_extract.py` (3 synthesized extractors),
           `data/infer/cache/` (every response, replayable at $0.00)
Status:    Current. Discharges
           [ADR-0009](../adr/0009-adapters-first-generic-extraction-second.md)'s
           written trigger — *"the fourth adapter is the last one built before
           a measured generic-versus-adapter comparison exists."* Every figure
           is an agreement rate against a reference implementation and **none
           may be quoted as accuracy**; the golden set of ADR-0014 is still
           unbuilt and is now the binding constraint on the extraction claim.

---

## What this is, and the one sentence that governs reading it

A synthesized extractor was scored against a hand-written adapter on pages
already in the raw store. **The adapter is the reference, so every number here
is an agreement rate, not an accuracy rate.** Where the two disagree either may
be right; where they agree, both may be wrong together. The thing that could
adjudicate is the [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md)
golden set, of which zero records exist.

This was called "the bake-off" until 2026-09-21. The name was retired because a
bake-off implies a neutral judge and there is none — the rename is a guardrail
against the reading it invited.

## Result

| Platform | Arm | Model | Pages | Records | Recall | Precision | Fields |
|---|---|---|---|---:|---:|---:|---|
| St. Johns (WATS/.NET) | S — synthesis | Haiku 4.5 | 14/14 | 3,627 | 1.0000 | 1.0000 | all 1.0000 |
| St. Johns (WATS/.NET) | D — direct | Haiku 4.5 | 2/2 | 488 | 1.0000 | 1.0000 | all 1.0000 |
| Clark County (Accela) | S — synthesis | Haiku 4.5 | **0/57** | — | — | — | **raised on every page** |
| Clark County (Accela) | S — synthesis | **Opus 5** | 57/57 | 561 | 1.0000 | 1.0000 | all 1.0000 |
| Clark County (Accela) | D — direct | Haiku 4.5 | 2/2 | 20 | 1.0000 | 1.0000 | all 1.0000 |

Fields scored: `native_id` (the join key), `issued_date`, `address`,
`permit_type`, `status`, `structure_code`, `contractor` — whichever the
platform prints. Comparison is whitespace-collapse only; no date parsing or
code lookup on either side, so a format difference counts as a disagreement.

**Four of five cells are perfect agreement**, with zero misses and zero
spurious rows in all four. That is 4,696 record-scorings over **4,188 distinct
records** — the two arms overlap on the same pages, so the totals must not be
added.

## Economics — the claim §1 actually rests on

Synthesis is a **fixed cost per template**; direct extraction is a **linear
cost per page**. That is the whole amortization argument, and it is now
measured rather than assumed.

| | synthesis (once) | direct (per page) | whole corpus direct | ratio | breakeven |
|---|---:|---:|---:|---:|---:|
| St. Johns, 14 pages | $0.0326 | $0.1494 | $2.09 | **64x** | **0.2 pages** |
| Clark County, 57 pages | $0.2965 | $0.0419 | $2.39 | **8.1x** | **7.1 pages** |

Cost per 1,000 records:

| | synthesis | direct |
|---|---:|---:|
| St. Johns (WATS) | **$0.009** | $0.61 |
| Clark County (Accela) | **$0.529** | $4.19 |

**On WATS, synthesis costs less than extracting a single page directly.** The
ratio is not a constant — it grows with the corpus, because the numerator is
fixed. Quoting "64x" as a property of the method would be wrong; it is a
property of 14 pages of one template.

The 95x per-record byte spread between platforms
([step 1](2026-09-20-step1-stjohns-reconciliation.md)) reappears here as a
**58x spread in direct extraction cost per record** and a **59x spread in
synthesis cost per record**. Platform, not method, is the dominant term in
both.

## The model-tier finding, and a correction to DESIGN.md §6

§6 lever 6 proposes "a strong model for *synthesis* (few calls, hard
reasoning, high leverage — an error here propagates to every page that template
touches) and a cheap model for *fallback extraction* (many calls, mechanical)",
and then defers the whole lever: *"lever 6 cannot be evaluated until the golden
set exists, because before step 2 there is no way to tell a cost saving from a
quality regression."*

**That deferral is wrong, and the lever is now measured.** The reasoning holds
for *accuracy* and does not apply to a *comparison between two models*. The
reference here is a hand-written parser, so its errors are uncorrelated with
any model's — which is exactly the property an LLM-as-judge lacks and exactly
why D9 forbids LLM-as-judge for headline numbers. Two models scored against an
uncorrelated reference can be compared to each other even though neither can be
called correct.

What the comparison says:

- **Direct extraction: the cheap tier is sufficient.** Haiku 4.5 scored 1.0000
  on both platforms, including a 259-record page returned as one JSON array.
  There is no measured reason to spend Opus prices on this call class.
- **Synthesis: the tier is decisive.** Haiku failed Accela completely; Opus was
  perfect on the same window of the same page.
- **The failure propagated exactly as §6 predicts.** One bad synthesis call
  broke **all 57 pages**. That is the asymmetry the lever is built on, observed
  rather than argued: a cheap extraction error costs one page, a cheap
  synthesis error costs the template.

So lever 6's split is confirmed, with the platform as a third term: the easy
template synthesized correctly at the cheap tier, the hard one did not.

## Why Haiku failed on Accela

It keyed the grid with `<table[^>]*id="...gdvPermitList"[^>]*>(.*?)</table>`.
An Accela page nests tables inside the grid, so the non-greedy `.*?` closed at
the **first inner** `</table>` and captured **617 characters** containing zero
rows.

The generated module then did the right thing: it **raised**
`ValueError: No permit records found in table` on all 57 pages rather than
returning `[]`. The prompt asks for loud failure over guessing, and that
instruction is what turned a silent zero into a visible one. A synthesized
extractor that returns an empty list on a changed page is the single most
dangerous failure mode available to this design, and it did not happen.

Opus, given the identical window, wrote a 298-line module that scans every
`<table>` region while **tracking nesting depth**, scores candidates by the
presence of ACA control ids, strips inner tables before row parsing, and falls
back to header-label column position for anything the control id does not
identify — including the hidden address column whose header is empty. It
contains no hard-coded permit number, date, address or row count.

## Findings about the instrument, not the model

Every one of these would have produced a number that looked like a fact about
the model and was a fact about the instrument. Four were caught before any call
was made; four cost money or a failed run.

**Caught before spending (free):**

1. **The stripper deleted the Accela row markers.** `class` was not on the
   keep-list, so `class="ACA_TabRow_Odd"` vanished from all 42 rows while the
   rows stayed. See §6 lever 4, amended.
2. **Window v1 missed the grid entirely** — Clark's grid begins at character
   65,386; the window ended at 24,973.
3. **Window v2 landed on nav** — maximizing bare `<tr>` count prefers layout
   tables, which have more rows and smaller ones. Fixed by counting rows with
   ≥4 cells (Clark: 31 layout rows of 2 cells, 11 grid rows of 8).
4. **The generated parser would have run on raw HTML although it was shown
   stripped HTML.**

**Cost money or a run:**

5. **`adaptive` thinking is rejected by Haiku 4.5 with a 400**, and
   `budget_tokens` is rejected by Opus 5 the same way. No form works on both;
   the shape is a property of the model. Cost: one failed run, $0.00 — the
   request was refused before billing.
6. **Arm D's output budget was guessed at 45 tokens/record and truncated both
   St. Johns pages.** Truncation here is not a degraded answer but an
   unparseable one: the JSON array never closes, the page scores zero, and the
   call bills in full. Measured replacement: **110 tokens/record**, from
   Clark's two successful calls (1,003 and 958 output tokens for 10 records).
   Cost: $0.1112.
7. **Synthesis at `max_tokens` 8,000 truncated Opus mid-function**, because
   adaptive thinking shares the output budget and a nesting-aware parser is
   roughly 2.4x the code of a naive one. Cost: $0.2732.
8. **The response cache never hit for streamed calls.** `stream` was added to
   the request body after the lookup key was computed and before the store, so
   every streamed response was written under a hash nothing would ask for. It
   is silent — the cache fills and simply never hits. Three paid-for responses
   ($0.60) were re-keyed by reconstructing the request bodies rather than
   re-bought.

**$0.38 of the $1.28 was spent on items 6 and 7**, both mis-sizing by the
author. Recorded because a cost figure that quietly excludes the failed
attempts is not the cost of doing the thing.

## What this establishes

- A synthesized extractor reached **perfect agreement with a hand-written
  adapter on 4,188 records across 71 pages and two platforms**, from two model
  calls costing **$0.33 combined**.
- **Two independent implementations agree.** The adapter was written by hand
  from the page; the extractor was synthesized from a stripped excerpt with no
  sight of the adapter. Agreement on 4,188 records is materially stronger
  evidence than one implementation alone — though it is still evidence about
  *parsing*, not about semantics.
- **Amortization is real and measured**: 64x and 8.1x on these corpora,
  breakeven at 0.2 and 7.1 pages.
- **Model tiering is measurable now**, and §6's deferral of lever 6 is retired.
- **Loud failure works.** The one broken extractor announced itself on all 57
  pages.

## What this does not establish

- **Accuracy.** Agreement with a reference implementation, nothing more. The
  adapter has been wrong before — it read a truncated page as complete, and it
  mis-keyed a vocabulary.
- **Semantic correctness.** Both implementations read the column headed
  "Issue Dt" as the issue date. Neither establishes that it *is* one.
- **Drift.** Every page here is one capture of one template. Whether a
  synthesized extractor survives the portal changing is the step-2 question
  against the golden set, and it is the question that sets the cohort threshold
  Spike C could not pick. **No amortization multiple may still be quoted
  across templates.**
- **Detail pages.** Measurement B put index and detail at J = 0.19 inside one
  portal, so a tenancy needs at least two extractors. This scored one of them.
- **The other 5 platforms.** Two templates, both ASP.NET grids, both already
  having adapters. A template with no adapter has no reference and cannot be
  scored this way at all — which is the limit of the whole method and the
  reason [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md)
  survives this result intact.
- **That synthesis generalizes to bucket-2 portals**, JSON APIs, or anything
  that is not a server-rendered results grid.
- **Arm D at the Opus tier was never run**, so "Haiku is sufficient for direct
  extraction" rests on Haiku scoring 1.0000 — a ceiling, which cannot show that
  Opus would not have scored the same. The claim is "no measured reason to
  spend more", not "Opus is no better".

## Reproducing

```
python scripts/conformance.py --matrix          # projected cost, no calls
python scripts/conformance.py                   # dry run: plan + scorer checks
python scripts/conformance.py --run --max-spend 0.40 \
    --synth-model claude-haiku-4-5-20251001 \
    --direct-model claude-haiku-4-5-20251001
python scripts/conformance.py --run --max-spend 0.55 --targets clarkco \
    --synth-model claude-opus-5 --synth-tokens 16000 --direct-pages 0
```

All four replay from `data/infer/cache/` at $0.00. The scorer validates itself
before any call — identity scores 1.000 and four mutations each move the number
they should and leave the others alone, 18 checks across the two targets.

## References

- [ADR-0009](../adr/0009-adapters-first-generic-extraction-second.md) — the
  trigger this discharges
- [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md) — the golden
  set this does not replace
- [ADR-0016](../adr/0016-tests-are-replay-over-the-raw-store.md) — replay is
  why the corpus was free to score against
- `DESIGN.md` §1 (amortization), §5, §6 (levers 4 and 6), §9 obligations
- [Spike C](2026-09-20-spike-c-template-collision.md) — why the cohort size
  this does not measure is the remaining unknown
