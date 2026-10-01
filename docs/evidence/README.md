# Evidence reports

**Every number this project quotes lives here, with the machinery to reproduce it.**

A report is a dated record of one measurement: what was asked, what was run, what came back, and what it
does and does not establish. Reports are append-only. A later measurement that changes the answer gets a
new report and marks the old one superseded; it never edits the old one, because the point of the
directory is that a figure quoted in September can be traced to what was known in September.

## Why this is a separate category

Design docs are living and ADRs are immutable, and a measured number fits neither. Put `16.63% of
national authorized units` in a design doc and the doc becomes undateable - a reader cannot tell whether
the figure was refreshed with the last edit. Put it in an ADR and the ADR becomes mutable the first time
the data is re-pulled.

The failure this prevents is specific and has already happened once in this project: the catalog sweep's
first pass reported **112 offices / 5.0% of units**, that figure was quoted onward, and hand resolution
later tripled it to **180 offices / 16.63%**. The original number was not wrong when it was written; it
was wrong when it was *re-quoted*, and nothing carried the date forward to say so.

## Required front matter

Every report opens with this block. `check_docs.py` enforces its presence.

```
Date:      2026-09-20
Produced:  spikes/spike_a_sample.py, spikes/spike_a_probe.py
Inputs:    data/frame/bps_frame.csv (20,069 rows, built 2026-09-19)
Outputs:   data/spike_a/portal_classification.csv (28 rows)
Status:    Current | Superseded by <report>
```

**A claim with no named producer is not evidence, it is a recollection.** If a figure was arrived at by
hand, name the person and the method; that is a weaker provenance than a script but an honest one, and
the distinction is exactly what a reader needs.

## Required sections

- **Question** - what was being measured, in one sentence, written before the answer was known
- **Method** - enough that someone else could re-run it, including what was *not* controlled for
- **Result** - the numbers, with their denominators stated
- **What this establishes** - the claim that can now be made
- **What this does not establish** - the claim a reader might wrongly infer. This section is mandatory
  and must not be empty. Sampling error, selection bias, and coverage gaps go here.

## Index

| Report | Question | Status |
|---|---|---|
| [2026-09-20 Spike A](2026-09-20-spike-a-portal-enumerability.md) | Can the permit universe be enumerated by crawling, or must it be queried? | Current, except tier-2 |
| [2026-09-20 Tier-2 rerun](2026-09-20-tier2-issuing-level-rerun.md) | Does the tier-2 0% survive being measured at the body that actually issues the permit? | Current |
| [2026-09-20 Spike C](2026-09-20-spike-c-template-collision.md) | Do ~20,000 portals collapse onto a few hundred templates, or does every jurisdiction render its own thing? | Qualified by Measurement A/B |
| [2026-09-20 Measurement A/B pre-registration](2026-09-20-measurement-ab-preregistration.md) | Page types, controls and decision rules for the index/detail and Accela-cohort measurements, fixed before the data existed. | Pre-registered |
| [2026-09-20 Measurement A/B results](2026-09-20-measurement-ab-results.md) | Do permit index and detail pages collapse across jurisdictions, and how big is an Accela cohort? | Current |
| [2026-09-20 Spike B](2026-09-20-spike-b-bps-reconciliation.md) | Can portal permit data be aggregated into something comparable to Census unit counts? | Current |
| [2026-09-20 Step 1 / St. Johns](2026-09-20-step1-stjohns-reconciliation.md) | Can an HTML adapter produce a reconciliation figure, and what does it cost per record? | Current |
| [2026-09-21 Bucket 4 resolved](2026-09-21-bucket4-resolution.md) | Do the last two bucket-4 offices enumerate, and what does that do to the gate? | Current |
| [2026-09-21 Extractor conformance](2026-09-21-extractor-conformance.md) | Can a model write an extractor that agrees with a hand-written adapter, and which arm is cheaper? | Current |
| [2026-09-21 Drift robustness](2026-09-21-drift-robustness.md) | Do synthesised extractors survive realistic template drift? | Current |
| [2026-09-22 Cost per success](2026-09-22-cost-per-success.md) | Does cost per token or cost per working extractor rank models correctly? | Superseded in scope by 2026-09-25; Clark inversion not established (2026-09-27 intervals) |
| [2026-09-25 Open-weight model axis](2026-09-25-open-weight-model-axis.md) | Does the cost-per-success rule survive a 90x price band and a second provider? | Qualified by 2026-09-26 audit and 2026-09-27 intervals |
| [2026-09-26 Model-comparison fairness audit](2026-09-26-model-comparison-fairness-audit.md) | Is the cross-vendor comparison a fair test, and what must change before the next paid run? | Current |
| [2026-09-27 Reasoning effort on OpenRouter](2026-09-27-openrouter-reasoning-effort.md) | Which efforts does each model accept, and what does OpenRouter send for one a model does not list? | Current |
| [2026-09-27 Cost per success with its uncertainty](2026-09-27-cost-per-success-intervals.md) | How sure can we be which model is cheaper per working extractor, and do the quoted rankings survive? | Current |
| [2026-09-27 v2 run pre-registration](2026-09-27-v2-run-preregistration.md) | What will the protocol v2 comparison run, on which targets, at what n, judged how, for how much? | Pre-registered |
| [2026-09-28 v2 results and visualization plan](2026-09-28-v2-results-and-visualization-plan.md) | How will the v2 results be reported and drawn, and how is each graphic checked before it goes public? | Plan |
| [2026-09-29 v2 stage 1 check and re-projection](2026-09-29-v2-stage1-check-and-reprojection.md) | Did a host close any model's streams early besides glm-5.3-flash's, and does the rest of the run fit the $45 cap? | Draft |
| [2026-09-29 Agentic extractor plan](2026-09-29-agentic-extractor-plan.md) | Can a check with no reference pick working extractors, and does a tool-using agent beat sampling, a scripted loop and a human hint at the same spend? | Draft plan |
| [2026-09-29 v2 stage 3 plan](2026-09-29-v2-stage3-plan.md) | How is the top tier sized, ordered and routed so that it fits the cap and the clock, and loses the right draws if it does not? | Plan |

## Naming

`YYYY-MM-DD-slug.md`, so the directory sorts chronologically and a stale report is visibly stale in `ls`.
