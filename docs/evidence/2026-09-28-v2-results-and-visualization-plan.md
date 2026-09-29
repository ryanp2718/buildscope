# How the protocol v2 run will be reported: the results report and the visual story page

Date:      2026-09-28
Produced:  Written by hand during stage 1, before any results report, export script or page exists.
           No model calls; cost $0.00.
Inputs:    [2026-09-27 v2 run pre-registration](2026-09-27-v2-run-preregistration.md) (the questions,
           the analysis, deviations 1 and 2), [2026-09-27 cost per success with its
           uncertainty](2026-09-27-cost-per-success-intervals.md) (the method for ranking claims),
           stage 1 cells in `data/infer/variance.json` as they stood on 2026-09-28
Outputs:   none yet. Planned: `scripts/export_results.py`, `site/results/` (the page and its
           `data.json`), a test of the export, and the results report in `docs/evidence/`.
Status:    Plan. The page's lead story and its location (`/results/`) were chosen by the user on
           2026-09-28.

## Purpose

The run answers five pre-registered questions. This fixes how the answers reach two readers: someone
checking the work, who needs every number, interval and deviation, and someone with no context at
all, who needs to know in a few minutes what was tested and what came out of it. The first reader
gets a report. The second gets a page of graphics that tells the story in order. Both are built from
one exported data file, so they cannot disagree.

Nothing here changes the analysis. The pre-registration decides what is claimed; this decides how it
is shown.

## Rules for both outputs

- **Assume no context about the project, not about the field.** Standard ML and evaluation terms
  are used as they are: pass@1, draw, cost per success, Wilson interval, held-out target, ablation.
  What is particular to this project, a permit portal, an extractor, the reference it is scored
  against, is explained in a sentence before it is used.
- **Public framing.** The page is public-facing, so limits are framed as scope and next steps
  rather than as blunt disclaimers. The substance is the same and nothing is left out; the tone is
  that of a paper's "future work", not an internal risk list.
- **One point per graphic.** Each chart has a headline sentence that states its point, and the chart
  exists to show that sentence.
- **Uncertainty is always drawn.** Every rate carries its Wilson 95% interval. A ranking is drawn as
  settled only where it holds by the 2026-09-27 intervals method (the simulated probability that one
  model is cheaper per success is at least 0.975 under both priors); the rest are drawn faded and
  labelled as not settled.
- **A model that never worked is shown, not dropped.** Cost per success has no value at 0 successes.
  Those models sit on a separate "no working attempt in n" shelf beside the chart rather than
  disappearing from it.
- **Pre-registered first, exploratory second.** The report answers questions 1-5 in order before
  any post-hoc analysis, and every post-hoc section is labelled as such. The page marks exploratory
  graphics the same way.
- **Every number traces to data.** No number is typed into a chart. The page reads `data.json`, which
  `scripts/export_results.py` writes from `variance.json` and the ledger; a test re-runs the export
  and checks the page's data and the report's headline figures against `model_stats`, as the design
  documents are checked now.
- **Readable by everyone.** Direct labels rather than legends, a colour-blind-safe palette with a
  second cue (fill or shape) for every colour, a text summary and a data table behind every chart,
  and a layout that works on a phone.

## The page: the story in order

Led by the price story, because it needs the least context: "does paying more get you more?" is a
question any reader already has.

1. **What was tested.** One illustration: a permit search page on the left, the table of records a
   program should pull from it on the right, and a model writing that program in between. 26 models,
   3 county and city permit sites, each model given the same page and the same instructions, every
   draw checked against a hand-written reference. Nothing on this panel needs a number.
2. **Paying more per token does not buy a working program.** A scatter on Clark County: each model's
   price per million output tokens across (log scale), pass@1 up the side, with interval bars. A second step of the same chart switches the vertical axis to cost per
   working program (log scale), with the no-success shelf beside it and faint diagonal lines of equal
   cost per working program behind the points. A slope chart then ranks the models by price on the
   left and by cost per working program on the right, with a line solid only where the ranking holds.
   This answers question 2.
3. **Every draw is a square.** A unit chart: one row per model, sorted by price, one square per
   draw, coloured by what happened: perfect, near miss (missed a few rows), silently empty, raised
   an error, host failure. It shows that two models with the same
   rate can fail in different ways, and that silently empty output dominates the cheap end on Clark. This carries question 1.
4. **One table inside a table.** An explainer. A simplified drawing of Clark's page markup, the small
   table inside the grid's caption highlighted, and the cut a common program makes at the first
   closing table tag, landing before any permit row. Beside it, the share of silently empty draws
   that recover once that one table is removed (56 of 71 in stage 1, recomputed at the end). Marked
   exploratory.
5. **Pass here, fail there.** One line per model with three dots: Clark, St. Johns, Santa Barbara,
   each with its interval. Models that fail Clark and pass St. Johns show that one test site can
   mislead. Santa Barbara is annotated with what its window did and did not show the model
   (pre-registration question 3 and the window note in the method section).
6. **Instructions and settings barely move the needle.** Arrows from baseline to hint per model
   (question 5), and from the v1 settings to v2 for the seven re-run models (question 4), over the
   interval of the other arm. An arrow that stays inside it is drawn as no detectable change.
7. **How the test was kept fair.** The settings each model was run at, the hosts that served each
   arm, the re-draws after a cut-off at the output cap, and "the wall": every glm-5.3-flash call by
   duration, with the 301 s and 602 s points where hosts closed the stream (deviation 2). This is the
   section that earns the rest of the page its trust.
8. **Scope and next steps.** What the run covers, and the follow-ups it points to: more portals
   per vendor, an agentic arm where the model can run its program and retry, an effort sweep, and
   the top-tier models left out for cost. Drawn from the report's limitations, framed as further
   work.

## The report

`docs/evidence/YYYY-MM-DD-v2-run-results.md`, written when stage 3 is done:

- the answers to questions 1-5 in the pre-registered order, each with its table and intervals, and
  the counts the pre-registration says are reported;
- deviations 1 and 2 and anything after them, and the cells cut under the $45 cap, if any;
- a method appendix: settings per model, **hosts per arm** (the hint and baseline arms of a model can
  be served by different hosts, which is a confound in question 5), re-draws per model, host
  failures per model and host, and spend on failed calls (`usd_failed_calls`) beside `usd_total`;
- exploratory sections, labelled: a failure breakdown per draw (cut at the caption table, rows keyed
  on the detail link, raised, host failure, other), the caption-table removal test, reasoning length
  by outcome, and the effect of the hint on reasoning length;
- kimi-k2-thinking's v1 rate as published and without its host-error draw (deviation 2);
- "What this does not establish" (every evidence report carries it; `check_docs` requires it),
  with the follow-ups it implies;
- a link to the page.

## Build

- **Export.** `scripts/export_results.py` reads `variance.json`, the ledger and `model_stats`, and
  writes `site/results/data.json`: one record per draw (model, target, arm, outcome, failure type,
  tokens, cost, host, seconds) and one per cell (rate, interval, cost per success and its simulated
  range). Deterministic for a fixed seed, so a re-run with no new draws writes identical bytes.
- **Page.** Static HTML, CSS and JavaScript in `site/results/`, with no build step: D3 and
  Observable Plot for the charts and Scrollama for the scroll-driven steps, loaded from jsDelivr. It
  deploys with the existing Pages workflow beside the crawler page.
- **Tests.** The export is reproducible; every cell in `data.json` matches `model_stats`; every
  number quoted in the page's prose is present in `data.json`.
- **Render checks.** A page can break in far more ways than a document, and a chart that fails
  to draw fails silently. So nothing is published until it has been seen rendering:
  - a headless-browser check (Playwright) that loads the page from a local server, fails on any
    console error or failed request, and asserts every chart drew what the data says: the number
    of points, squares and arrows per chart, and no empty SVG;
  - screenshots at phone and desktop widths, in light and dark mode, looked at by a person, and
    for each scroll step, not just the first screen;
  - the no-JavaScript fallback (the text summaries and data tables) checked the same way;
  - after deploy, the same check against the live GitHub Pages URL, since paths, the CDN and
    caching differ from a local server.

## Order of work

1. The export script and its test, on stage 1 data.
2. A prototype of sections 2 and 3, the price story and the unit chart, shared as a private preview
   for review of the look before the rest is built.
3. Sections 1 and 4-8.
4. After stage 3: the export re-run on the full data and the report written.
5. The render checks passed and the screenshots reviewed; only then is the page published, and
   the check re-run against the live URL.

**Where the page lives.** A public page on the project's GitHub Pages site at `/results/`
(confirmed by the user on 2026-09-28), published only once the report is final; prototypes are
shared as private previews until then. The Pages workflow deploys everything under `site/` on a push
to `main`, so `site/results/` reaches `main` only when the page is ready to publish.

## Progress

- 2026-09-29: `scripts/export_results.py` and `tests/test_export_results.py` written, on stage 1
  data. The roll-up they share with `scripts/model_stats.py` is now `permits/rollup.py`.
- 2026-09-29: a prototype of sections 2 and 3 in `site/results/index.html`, shared as a private
  preview. It uses D3 alone; the scroll steps use the browser's IntersectionObserver, which does
  what Scrollama would with one dependency fewer. The slope chart waits until the export carries
  the pairwise comparisons, so that it can mark only settled rankings.

## What this does not establish

**Anything about the models.** This is a plan for presentation and measures nothing.

**That the graphics are neutral.** Choices of axis, order and colour change what a reader takes away.
The rules above (intervals always drawn, settled rankings marked apart from unsettled ones,
never-worked models kept on the chart, exploratory graphics labelled) are the guard against that,
and the report, not the page, is the record: where they differ, the report is right and the page is
fixed.

**The final shape of the story.** The section order assumes the stage 1 pattern (models in the
cheap tier range from 0 to 10 of 10 on Clark, and Clark is hard for one structural reason) holds
across stages 2 and 3, which bring in the mid and top tiers and so the price comparison itself. If the full data says something else, the page tells that instead; the report's structure does
not change, because the pre-registration fixes it.
