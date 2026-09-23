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

ORDER = ["perfect", "silent_partial", "silent_empty", "loud"]


def wilson(x, n, z=1.96):
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


def pctile(values, q):
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


def failure_mode(d):
    """Classify one synthesis draw.

    The distinction that matters operationally is silent versus loud, not
    which exception was raised. A module that raises stops a pipeline; one
    returning `[]` looks like a quiet week in the permit office and is
    discovered a month later, which is the failure family this whole project
    keeps meeting.
    """
    o = d.get("outcome")
    if o == "perfect":
        return "perfect"
    if o in ("raised", "exec_error", "refused", "no_code", "not_attempted"):
        return "loud" if o != "not_attempted" else "not_attempted"
    r = d.get("recall_min")
    if r == 0.0:
        return "silent_empty"
    return "silent_partial"
