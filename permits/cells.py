"""Records for the variance experiment: what a cell is, how a run is
configured, and what one draw produced.

A cell is (target, model, condition) and holds k independent draws of one
synthesis request. These were argparse attributes and dicts until
2026-09-26. `run_cells` overwrote `args.synth_model` and `args.draws` per cell
and did not restore them, and every reader of a draw used `.get("field")`, so
a misspelled field read as missing rather than raising. The on-disk format of
`data/infer/variance.json` is unchanged; these are the typed view of it.
"""
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from enum import StrEnum
from typing import Any

from permits.models import Protocol


class Outcome(StrEnum):
    """How one draw ended. Exactly one per draw, decided in this order: the
    call, the code block, the AST audit, execution, then the score."""
    NOT_ATTEMPTED = "not_attempted"   # refused, or rejected; the run stopped
    INFRA_ERROR = "infra_error"       # the host failed on every attempt
    NO_CODE = "no_code"               # no `def extract(` block in the reply
    REFUSED = "refused"               # the AST audit rejected the module
    EXEC_ERROR = "exec_error"         # the runner itself failed
    RAISED = "raised"                 # extract() raised on at least one page
    IMPERFECT = "imperfect"           # ran everywhere, disagreed somewhere
    PERFECT = "perfect"               # agreed with the adapter on every page


@dataclass(frozen=True)
class CellSpec:
    """One `--cells` entry: `target:model[@effort]:draws`, where `draws` is a
    count or, for a two-stage cell, `first+more` (see `curtail`).

    `draws` is the most the cell can buy, so a worst case priced from it is
    the worst case of either design. `stage1` is set on a two-stage cell."""
    target: str
    model: str
    draws: int
    hint: bool = False
    protocol: Protocol = Protocol.V2
    effort: str | None = None
    stage1: int | None = None

    @property
    def label(self) -> str:
        """The model as the cell names it: `model`, or `model@effort`."""
        return "%s@%s" % (self.model, self.effort) if self.effort else self.model

    @property
    def draws_label(self) -> str:
        """The draw count as it was written: `20`, or `10+10`."""
        if self.stage1 is None:
            return str(self.draws)
        return "%d+%d" % (self.stage1, self.draws - self.stage1)

    @property
    def key(self) -> str:
        """`target|label`, then `|hint` when the hint is on and `|v2` under
        protocol v2.

        Each is a different condition, so each gets its own cell. Merging
        them under one key would pool draws made under two prompts, or two
        request policies, into one rate and report it as one experiment. v1
        cells keep the keys they were written under.
        """
        key = "%s|%s" % (self.target, self.label)
        if self.hint:
            key += "|hint"
        if self.protocol is not Protocol.V1:
            key += "|%s" % self.protocol
        return key

    @classmethod
    def parse(cls, entry: str, hint: bool = False,
              protocol: Protocol = Protocol.V2) -> "CellSpec":
        """Split off the target at the first colon and the draw count at the
        last, rather than splitting on every colon: an OpenRouter model id may
        contain one itself, as in `openai/gpt-oss-120b:batch`. An effort is
        written after the model id with `@`, which no id contains. A
        two-stage cell writes its draws as `10+10`."""
        entry = entry.strip()
        if entry.count(":") < 2:
            raise ValueError("bad --cells entry %r, want target:model:draws"
                             % entry)
        target, rest = entry.split(":", 1)
        model, draws = rest.rsplit(":", 1)
        try:
            parts = [int(p) for p in draws.split("+")]
        except ValueError:
            raise ValueError("bad draw count %r in --cells entry %r"
                             % (draws, entry)) from None
        if len(parts) > 2 or min(parts) < 1:
            raise ValueError("bad draw count %r in --cells entry %r, want n "
                             "or first+more" % (draws, entry))
        stage1 = parts[0] if len(parts) == 2 else None
        effort = None
        if "@" in model:
            model, effort = model.split("@", 1)
            if protocol is Protocol.V1:
                raise ValueError("%r names an effort, which protocol v1 does "
                                 "not have" % entry)
        return cls(target, model, sum(parts), hint, protocol, effort, stage1)


@dataclass(frozen=True)
class RunConfig:
    """The settings one synthesis run is made under. Frozen, so a cell gets
    its own copy from `for_cell` instead of editing a shared namespace."""
    synth_model: str
    direct_model: str
    synth_tokens: int
    synth_window: int
    synth_hint: bool
    direct_pages: int
    draws: int
    protocol: Protocol = Protocol.V2
    effort: str | None = None
    stage1: int | None = None

    @classmethod
    def from_args(cls, args: Any) -> "RunConfig":
        return cls(**{f.name: getattr(args, f.name) for f in fields(cls)
                      if hasattr(args, f.name)})

    def for_cell(self, cell: CellSpec) -> "RunConfig":
        return replace(self, synth_model=cell.model, draws=cell.draws,
                       synth_hint=cell.hint, protocol=cell.protocol,
                       effort=cell.effort, stage1=cell.stage1)


@dataclass(frozen=True)
class DrawRecord:
    """One draw in a variance cell, as stored in `variance.json`.

    Which optional fields are present depends on how far the draw got: a
    draw stopped before the call has only `why`, one whose code was refused
    has no scores, and so on. `to_dict` omits the absent ones, which is the
    shape the file has always had.
    """
    draw: int
    model: str
    target: str
    outcome: Outcome
    why: str | None = None
    usd: float | None = None
    cached: bool | None = None
    truncated: bool | None = None
    output_tokens: int | None = None
    bytes: int | None = None
    imports: list[str] | None = None
    audit_problems: list[str] | None = None
    source: str | None = None
    error: str | None = None
    raised_on: int | None = None
    recall_min: float | None = None
    recall_mean: float | None = None
    precision_min: float | None = None
    pages_scored: int | None = None
    # Who served the response and how much of `output_tokens` was reasoning,
    # where known. Absent on draws recorded before 2026-09-26.
    host: str | None = None
    reasoning_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "DrawRecord":
        known = {f.name for f in fields(cls)}
        extra = sorted(set(d) - known)
        if extra:
            raise ValueError("unknown draw field(s) %s" % ", ".join(extra))
        return cls(**{**d, "outcome": Outcome(d["outcome"])})

    def scored(self) -> bool:
        """Whether this draw counts toward the pass rate.

        An infrastructure error is a property of the host and the network,
        not of the model, so it is reported beside the rate rather than
        folded into it as a failure (fairness audit, "Timeouts"). A draw
        that was never sent is not a measurement of anything.
        """
        return self.outcome not in (Outcome.NOT_ATTEMPTED, Outcome.INFRA_ERROR)

    def spend(self) -> float:
        """What the run that wrote this record paid for it. Zero for a draw
        replayed from the cache. Raises on a scored draw with no figure,
        which is a malformed record and not a free one. An infrastructure
        error has no figure because the host does not report one."""
        if self.usd is None:
            if self.scored():
                raise ValueError("draw %d of %s|%s has no usd"
                                 % (self.draw, self.target, self.model))
            return 0.0
        return self.usd


def draws_of(cell: Mapping[str, Any]) -> list[DrawRecord]:
    """The typed draws of one `variance.json` cell."""
    return [DrawRecord.from_dict(d) for d in cell.get("detail", [])]


def curtail(draws: list[DrawRecord], stage1: int) -> bool:
    """Whether a two-stage cell stops after its first `stage1` draws: it does
    when they are unanimous, all passing or all failing. This is a curtailed
    design, fixed in the step 6 pre-registration: 0/10 already has a Wilson
    interval of [0.00, 0.28] and 10/10 one of [0.72, 1.00], and ten more
    draws would narrow neither to a different conclusion. The rule depends
    only on the pass count, so the interval is computed as for a fixed n.

    Only scored draws count, as in the rate. An infrastructure error in stage
    1 leaves it deciding on fewer draws, and the re-run that retries that
    draw decides again. That can only turn a stop into a continue, never
    the reverse: a stage 1 that is already split stays split whatever the
    retried draw does. So stage 2 is never bought on data the complete stage
    1 would have stopped on. A stage 1 with no scored draw stops: there is
    nothing to decide on.
    """
    scored = [r for r in draws if r.draw < stage1 and r.scored()]
    passed = sum(1 for r in scored if r.outcome is Outcome.PERFECT)
    return passed in (0, len(scored))
