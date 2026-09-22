# ADR-0014: The golden set precedes the pipeline, and is labelled blind from the rendered page

Status: Accepted

Date: 2026-09-21

*Back-fill. The decision is D9 in `DESIGN.md`, already dated there and carrying its own rationale. What
this ADR adds is what step 1 changed about the cost of building one.*

## Context

Extraction accuracy is the number this project lives or dies by, and there is no way to know it without
labelled data. Every shortcut to avoiding that has a specific way of producing a flattering number:

- **Labelling by correcting extractor output** anchors to the extractor's mistakes. A field the extractor
  systematically misreads looks correct because the labeller was shown the misreading first.
- **LLM-as-judge for headline numbers** has errors that correlate with the extractor's, so it flatters
  exactly where the pipeline is wrong.
- **Page-level labelling** leaves per-field metrics badly correlated, because one index page yields ~50
  records and a single wrong field on one record is invisible at page granularity.
- **Uniform sampling** oversamples reroofs and says nothing about the tail, which is where extraction
  actually fails.

## Decision

**Build the golden set before the pipeline it scores, under six rules.**

- **Record-level labelling**, not page-level.
- **Drawn from the raw store**, never live fetches, or the set is not replayable against future extractor
  versions.
- **Stratified** by platform, jurisdiction tier, page type and work class.
- **Labelled blind** from the rendered page, never by correcting extractor output.
- **Self-agreement check:** double-label ~50 records two weeks apart. Failure to agree with yourself on
  `work_class` means the field is underspecified and no extractor can be honestly scored on it.
- **Dev and test frozen separately.** Iterate on dev, touch test rarely. Failure cases go to a growing
  *regression* set, never into dev or test, or you overfit to your own bugs.

Size: 500–1,000 records for v1, realistically 15–25 hours of labelling.

LLM-as-judge may be used to **triage** which records deserve human attention. It must not produce headline
numbers.

## Consequences

- **The "drawn from the raw store" rule is now satisfiable and was not obviously so when written.** The
  store holds 160 saved pages with manifest rows across three platforms, and
  [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) guarantees the bytes are immutable. The
  sampling frame exists.
- **A cheap partial substitute already runs and must not be mistaken for this.** `tests/test_adapters.py`
  replays the adapters over stored pages and asserts that they still parse, still yield roughly the row
  counts they did, and still detect truncation. That is a **regression** set, not a golden set: it checks
  that behaviour has not changed, and says nothing about whether the behaviour is *correct*. The
  distinction matters because the regression set is free and the golden set costs 15–25 hours, and the
  temptation to let the cheap one stand in for the expensive one is exactly how a project stops measuring
  accuracy.
- **Stratification by work class is harder than it reads.** The strata have to come from somewhere, and
  the only available source is the extractor's own `work_class` — which is the thing being scored.
  Stratifying on the extractor's output biases the sample toward records it classified confidently.
  Stratifying on the source's native strings instead is the available fix and costs a per-source mapping
  before any labelling begins.
- **The self-agreement check is the cheapest and most skippable rule, and skipping it invalidates the
  rest.** If `work_class` cannot be labelled consistently by one person two weeks apart, every accuracy
  figure computed against it is noise with a decimal point.
- **This gates the D8 bake-off.** [ADR-0009](0009-adapters-first-generic-extraction-second.md) sets the
  fourth adapter as the last one before a measured generic-versus-adapter comparison exists, and a
  comparison needs something to compare against. The adapters are the oracle for *agreement*; the golden
  set is the oracle for *correctness*. A bake-off scored only on adapter agreement measures whether the
  synthesized extractor imitates the adapter, including its bugs.
- **Nothing is labelled.** Zero records. This is the largest unspent cost in the project and the one most
  likely to be deferred indefinitely, because it is the only task here that is neither automatable nor
  interesting.

## Alternatives considered

- **Score against BPS aggregates instead of a golden set.** Free, already built, and it is the project's
  headline metric. Rejected as a substitute: a monthly unit total can be right while every individual
  record is wrong, because errors cancel. It measures the pipeline, not the extractor, and cannot
  attribute an error to a field.
- **LLM-as-judge for headline accuracy.** Cheap, scalable, and would produce a number this week. Rejected
  because its errors correlate with the extractor's — both are language models reading the same ambiguous
  page — so it is most wrong exactly where the answer matters. Retained for triage, where correlated error
  costs nothing.
- **Label by correcting extractor output.** Perhaps 5x faster per record and it is what everyone does.
  Rejected on anchoring: measured accuracy inflates, and the inflation is invisible because there is
  nothing to compare it against.
- **Defer the golden set until after the generic extractor exists.** Tempting, since the extractor would
  make labelling faster. Rejected as the same anchoring problem wearing a schedule, and because it makes
  the bake-off unscoreable at the exact moment it is needed.
- **Buy labels.** Not seriously costed. Worth revisiting for the bulk of the set once the labelling
  guidelines are written, since the self-agreement check is precisely the artifact that would make
  outsourcing safe.

## Revisit when

The first 50 records are double-labelled and the self-agreement rate is known. If `work_class` agreement
is poor, the right response is to revise the ontology rather than the labelling process — and that is a
change to [ADR-0012](0012-ingest-everything-calibrate-one-slice.md), not to this decision. Also revisit
the size target once per-record labelling time is measured rather than estimated.

## References

- `DESIGN.md` §D9, §5 (metrics), §9 (sequencing)
- [ADR-0009](0009-adapters-first-generic-extraction-second.md) — the bake-off this gates
- [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) — why the set is drawn from the raw store
- [ADR-0016](0016-tests-are-replay-over-the-raw-store.md) — the regression set, and why it is not this
- `tests/test_adapters.py`
