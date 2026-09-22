# Injected-drift robustness: synthesized extractors against the hand-written adapters

Date:      2026-09-21
Produced:  `scripts/conformance.py --drift` (no model calls; cost $0.00)
Inputs:    `data/step1/pages/` (stored captures; 3 St. Johns, 5 Clark index pages),
           `permits/adapters/stjohns.py`, `permits/adapters/accela.py`
           (both the reference *and* a scored candidate here),
           `data/infer/synth/*_extract.py` (the 3 published synthesized extractors),
           `data/infer/variance.json` (conformance-passing draws, via `--drift-variance`)
Outputs:   `data/infer/drift.json` (survival matrix),
           `data/infer/drift/<target>/<mutation>/` (every mutated page, raw and stripped)
Status:    Current. First robustness measurement in the project. Answers the
           "Does a synthesized extractor survive drift?" row of
           `INTERNAL/red-team.md`, which was previously "Never tested".

## Why this eval is free, and why that matters

The golden set is the binding constraint on every accuracy claim in this project, and it costs 15–25
hours that have not been spent. That has been used, wrongly, as a reason nothing could be measured.

This eval needs **zero labelled data**. Every mutation preserves the records a human reads off the page
and changes only the markup around them, so the adapter's parse of the **clean** page stays the correct
answer after mutation. Nothing needs labelling because nothing about the answer changed.

That also makes the adapter scoreable on the same footing as the synthesized extractors — it is the
reference on the clean page and a *candidate* on the mutated one. This is the first head-to-head
measurement in the project of whether a synthesized extractor is more or less brittle than the parser a
human wrote for the same grid.

## The mutations

Eight classes, each a thing portals actually do, applied independently:

| mutation | what it does | why it is realistic |
|---|---|---|
| `id_suffix` | `ctl00_X` → `ctl00_ctl99_X` | ASP.NET renumbers control ids when the control hierarchy changes |
| `class_rename` | `class="Row"` → `class="Row_x"` | a restyle |
| `attr_reorder` | reverses attribute order in every start tag | any template or minifier change |
| `wrapper_div` | wraps every table in a `<div>` | a layout or vendor upgrade |
| `nested_table` | inserts an empty table in the first cell of each row | Accela already nests tables; this deepens it |
| `whitespace` | reflows whitespace between tags | a template or pretty-printer change |
| `column_append` | adds a trailing cell to every row | a new field in the grid |
| `header_case` | uppercases header labels | a restyle |

**The control.** A mutation that deleted records would make every extractor look catastrophically
brittle, and the number would be an artifact of the mutator rather than a fact about extraction. So every
mutated page is checked for the adapter's own native ids before anything is scored, and a mutation that
loses one is reported as broken rather than run. All eight passed on every page in this run.

This is the control the stripper never had — the omission that let it silently delete all 42 `ACA_TabRow`
markers from every Accela page while the rows stayed and the page looked complete.

## Result

**OK = perfect agreement with the clean-page reference on every page. Anything less is BREAK.**

### St. Johns (WATS/.NET), 3 pages, 771 reference records

| mutation | adapter (hand-written) | synth haiku-4-5 |
|---|---|---|
| clean | OK | OK |
| id_suffix | OK | OK |
| class_rename | **BREAK** | **BREAK** |
| attr_reorder | **BREAK** | OK |
| wrapper_div | OK | OK |
| nested_table | **BREAK** | **BREAK** |
| whitespace | OK | OK |
| column_append | OK | OK |
| header_case | OK | OK |
| **survived** | **5/8**, CI [0.31, 0.86] | **6/8**, CI [0.41, 0.93] |

### Clark County (Accela ACA), 4–5 pages, 40–50 reference records

| mutation | adapter | synth haiku-4-5 | synth opus-5 | haiku draw d06 |
|---|---|---|---|---|
| clean | OK | BREAK | OK | OK |
| id_suffix | OK | BREAK | OK | OK |
| class_rename | OK | BREAK | OK | OK |
| attr_reorder | OK | BREAK | OK | OK |
| wrapper_div | OK | BREAK | OK | OK |
| nested_table | **BREAK** | BREAK | **OK** | **BREAK** |
| whitespace | OK | BREAK | OK | OK |
| column_append | OK | BREAK | OK | OK |
| header_case | OK | BREAK | OK | OK |
| **survived** | **7/8**, CI [0.53, 0.98] | 0/8 | **8/8**, CI [0.68, 1.00] | 7/8, CI [0.53, 0.98] |

The published Haiku Accela extractor scores 0/8 because it was **already broken on the clean page** — it
is the cell that raised on all 57 pages in the conformance test. Its 0/8 is not a drift finding and must
not be quoted as one. It is included because omitting a column because it embarrasses the run is how
benchmarks start lying.

`haiku draw d06` is the single draw out of 20 that passed conformance, pulled in by `--drift-variance`.

## The pool run: what a saturated eval was hiding

`--drift-variance` re-runs the same eval over **every synthesis draw that passed the conformance test** —
24 extractors after the variance experiment, rather than the 3 published ones. The population is worth
naming precisely: *among extractors that the conformance test scored as perfect, how many survive drift?*

| | adapter | Haiku 4.5 | Sonnet 5 | Opus 5 |
|---|---|---|---|---|
| **St. Johns**, 8 mutations | 5/8 = **0.62** | 86/120 = **0.72** (n=15) | 35/40 = **0.88** (n=5) | — |
| | CI [0.31, 0.86] | CI [0.63, 0.79] | CI [0.74, 0.95] | |
| **Clark**, 8 mutations | 7/8 = **0.88** | 7/8 = 0.88 (n=1) | 15/16 = **0.94** (n=2) | 24/24 = **1.00** (n=3) |
| | CI [0.53, 0.98] | CI [0.53, 0.98] | CI [0.72, 0.99] | CI [0.86, 1.00] |

**Drift survival is monotone in model tier on both platforms, and every tier matches or beats the
hand-written adapter.**

The sharpest single result is `class_rename` on St. Johns:

- **5 of 20 extractors survived it, and they are exactly the 5 Sonnet draws. All 15 Haiku draws broke.**

Every one of those 20 extractors scored **identically perfect** on the conformance test — 15/15 and 5/5,
recall and precision 1.0000 on every page. **The conformance test had no power to separate them at all.**
The drift eval separates them cleanly, and along the model-tier line.

This is the ceiling-effect argument in `INTERNAL/evals-and-inference.md` §B1 turned from a caution into a
measurement. A saturated eval did not merely fail to rank the things it scored — it concealed a real and
systematic quality difference between them.

Two smaller findings in the same direction:

- **Within one tier, extractors vary.** The 15 Haiku draws on St. Johns split 11 at 6/8 and 4 at 5/8,
  differing on `column_append`. Conformance saw all 15 as identical.
- **`nested_table` is ordered by tier on Clark**: Opus 3/3, Sonnet 1/2, Haiku 0/1. On St. Johns it is
  **0/18** — no synthesized extractor survives it there, and neither does the adapter.

## What this establishes

- **The synthesized extractor was at least as robust as the hand-written adapter on both platforms**, and
  strictly better on both: 6/8 vs 5/8 on WATS, 8/8 vs 7/8 on Accela. This is the reverse of the
  expected direction and it is the most interesting thing here.
- **One bug class explains almost every failure, and humans have it too.** `nested_table` is the only
  mutation that breaks the Accela adapter, and it breaks the St. Johns adapter, the published Haiku
  extractor and the Haiku draw that passed conformance. The cause is identical in all four: a non-greedy
  `(.*?)</tr>` or `(.*?)</table>` closes on the inner table.
  - `permits/adapters/stjohns.py:77` — `<tr class="Row"[^>]*>(.*?)</tr>`
  - `permits/adapters/accela.py:60` — `<tr class="ACA_TabRow_(?:Odd|Even)[^"]*">(.*?)</tr>`
  - The published Haiku extractor — `<table[^>]*id="...gdvPermitList"[^>]*>(.*?)</table>`
- **The only implementation that survives it is the Opus-synthesized one**, which tracks nesting depth and
  strips inner tables before parsing rows. On this mutation the top-tier model wrote a more careful parser
  than either human did.
- **The St. Johns adapter is brittle in two further ways the model was not.** `<tr class="Row"` requires
  `class` to be the literal first attribute (`attr_reorder` breaks it) and to be exactly `Row`
  (`class_rename` breaks it). Accela's `[^"]*` absorbs the rename, which is why it survives where St.
  Johns does not — a one-character difference in a regex is the whole gap between the two adapters.
- **Structural drift is mostly survivable.** `id_suffix`, `wrapper_div`, `whitespace`, `column_append` and
  `header_case` broke nothing at all. The scary-sounding drift classes are not the dangerous ones;
  nesting is.

## What this does not establish

- **It is not accuracy, and it is not even agreement with truth.** The reference is the adapter's parse of
  the clean page. Everything here inherits that parse's assumptions, including reading "Issue Dt" as an
  issue date. [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md) is untouched.
- **Eight mutations is not the space of drift.** They were chosen by me, they are independent
  single-factor changes, and real drift arrives combined and correlated with a vendor release. A survival
  rate against this set is not a survival rate against the world.
- **n is small in the direction that matters.** Two platforms, four extractors, 3–5 pages per target. The
  intervals are wide and stated for that reason: 7/8 is [0.53, 0.98], which admits a true survival rate
  barely above half.
- **`nested_table` may be harsher than real drift.** It inserts a table into every row rather than
  changing an existing structure. It is the mutation doing most of the discriminating, so the headline is
  sensitive to that one choice.
- **The pool is unbalanced and small in the tiers that matter.** Opus n=3, Sonnet n=3 and n=2, against
  Haiku n=15 — because the pool is whatever passed conformance, and what passed conformance depends on
  the cell's success rate. The tier ordering is consistent across both platforms, but Clark's Opus and
  Sonnet columns rest on three and two extractors.
- **Tier ordering here is confounded with what survived selection.** A Haiku draw only enters the pool by
  passing conformance; the Haiku draws that entered may differ systematically from Sonnet's. This is not
  a randomised comparison of tiers, it is a comparison of the survivors of each tier.
- **Nothing here measures repair.** A broken extractor stays broken; whether a model can fix one given the
  failure is the obvious next experiment and has not been run.

## Reproduction

```
python scripts/conformance.py --drift --targets stjohns --drift-pages 3
python scripts/conformance.py --drift --drift-variance --targets clarkco --drift-pages 4
python -m unittest tests.test_variance -v
```

No API key required and no calls are made. `tests/test_variance.py` checks the mutators against a
synthetic grid: that each preserves every record id, that each actually changes the page, that
`nested_table` reproduces the non-greedy-match shape, and that the faithfulness control itself catches a
mutation built to delete a record.
