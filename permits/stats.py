# -*- coding: utf-8 -*-
"""Estimators shared by the pass@1 scoring code and the statistics roll-up.

These lived in `scripts/conformance.py` until 2026-09-22 and moved here when a
second consumer appeared. `scripts/` is spikes and runners
([ADR-0016](../docs/adr/0016-tests-are-replay-over-the-raw-store.md)); a
function two scripts need is library code, and the alternative was a second
copy of an interval estimator, which is how two reports end up quoting
different confidence bounds for the same count.
"""
import math
from collections.abc import Iterable

from permits.cells import DrawRecord, Outcome

ORDER = ["perfect", "silent_partial", "silent_empty", "loud"]


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% score interval for x successes in n draws.

    A bare 3/3 reads as certainty. It is not: the interval is [0.31, 1.00].
    Every rate this project reports carries one, because quoting a point
    estimate off a handful of draws is the exact error the variance
    experiment exists to stop making.
    """
    if not n:
        return (0.0, 1.0)
    pr = float(x) / n
    d = 1.0 + z * z / n
    c = (pr + z * z / (2.0 * n)) / d
    h = (z / d) * math.sqrt(pr * (1 - pr) / n + z * z / (4.0 * n * n))
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe(k1: int, n1: int, k2: int, n2: int
             ) -> tuple[float, float, float]:
    """The difference p1 - p2 with its 95% interval, from the two Wilson
    intervals (Newcombe 1998, method 10). The v2 pre-registration's interval
    for a configuration or hint effect: it stays inside [-1, 1] and behaves
    at 0/n and n/n, where the normal interval collapses to a point."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return (d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
            d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def pctile(values: Iterable[float | None], q: float) -> float | None:
    """Nearest-rank percentile. No interpolation, no numpy.

    Nearest-rank because these samples are small - a p95 over 20 latencies is
    the 19th value, and interpolating between two observations would invent a
    latency that was never measured.
    """
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return None
    k = max(0, min(len(vs) - 1, int(math.ceil(q * len(vs))) - 1))
    return vs[k]


def failure_mode(d: DrawRecord) -> str:
    """Classify one synthesis draw.

    The distinction that matters operationally is silent versus loud, not
    which exception was raised. A module that raises stops a pipeline; one
    returning `[]` looks like a quiet week in the permit office and is
    discovered a month later, which is the failure family this whole project
    keeps meeting.
    """
    if d.outcome is Outcome.PERFECT:
        return "perfect"
    if d.outcome is Outcome.NOT_ATTEMPTED:
        return "not_attempted"
    if d.outcome is Outcome.INFRA_ERROR:
        return "infra_error"
    if d.outcome is not Outcome.IMPERFECT:
        return "loud"
    if d.recall_min == 0.0:
        return "silent_empty"
    return "silent_partial"
