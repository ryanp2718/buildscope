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
    """One `--cells` entry: `target:model:draws`."""
    target: str
    model: str
    draws: int
    hint: bool = False

    @property
    def key(self) -> str:
        """`target|model`, or `target|model|hint` when the hint is on.

        A hinted draw is a different condition, so it gets its own cell.
        Merging the two under one key would pool draws from two prompts into
        one rate and report it as one experiment.
        """
        base = "%s|%s" % (self.target, self.model)
        return base + "|hint" if self.hint else base

    @classmethod
    def parse(cls, entry: str, hint: bool = False) -> "CellSpec":
        """Split off the target at the first colon and the draw count at the
        last, rather than splitting on every colon: an OpenRouter model id may
        contain one itself, as in `openai/gpt-oss-120b:batch`."""
        entry = entry.strip()
        if entry.count(":") < 2:
            raise ValueError("bad --cells entry %r, want target:model:draws"
                             % entry)
        target, rest = entry.split(":", 1)
        model, draws = rest.rsplit(":", 1)
        try:
            n = int(draws)
        except ValueError:
            raise ValueError("bad draw count %r in --cells entry %r"
                             % (draws, entry)) from None
        return cls(target, model, n, hint)


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

    @classmethod
    def from_args(cls, args: Any) -> "RunConfig":
        return cls(**{f.name: getattr(args, f.name) for f in fields(cls)})

    def for_cell(self, cell: CellSpec) -> "RunConfig":
        return replace(self, synth_model=cell.model, draws=cell.draws,
                       synth_hint=cell.hint)


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
