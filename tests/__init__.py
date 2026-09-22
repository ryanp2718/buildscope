# -*- coding: utf-8 -*-
"""Tests for the BuildScope pipeline.

    uv run pytest                      # the whole suite
    uv run python scripts/run_tests.py # same thing, plus the standing checks

**Written as stdlib `unittest.TestCase` classes, run under pytest.** The cases
themselves use `assertEqual` and `subTest` and would run under `python -m
unittest discover -s tests -t .` with nothing installed; pytest supplies the
runner, the reporting and the `pythonpath` wiring. That split is deliberate:
the assertions do not depend on a framework, and swapping the runner would not
touch a single test.

This file used to claim that stdlib-only was a rule, on the grounds that the
project had no third-party dependencies at all. It has some now, and
[ADR-0017](../docs/adr/0017-the-inference-layer-uses-the-vendor-sdk.md) records
why that rule was wrong: it had never been weighed for the code it ended up
governing.

**What these tests are for.** Not coverage. Every test here corresponds to a
defect that actually produced a wrong number in this project, or to an
invariant a published figure depends on. The suite is closer to a regression
set than to a unit-test suite, and `docs/design/testing.md` says which failure
each file is descended from.

**The raw store.** Roughly a quarter of the suite replays over captured pages
in `data/`, which is not in the repository
([ADR-0015](../docs/adr/0015-the-raw-store-is-permanently-private.md)). Those
tests skip when it is absent and run when it is present; `requires_raw_store`
below is the single place that rule is written down.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


# The only artifact under `data/` that the repository publishes: 28 rows of
# derived public data, no page content, un-ignored by name in `.gitignore`.
# It is listed here because its presence must not be mistaken for the raw
# store being present - which is exactly the bug this constant exists to
# prevent, and which it caused once before it did.
PUBLISHED = frozenset([os.path.join("spike_a", "classification.csv")])


def raw_store_present():
    """True on a machine that has done the captures, False on a fresh clone.

    Asks whether `data/` holds anything beyond the published slice, rather
    than whether `data/` exists. Those were the same question until one file
    was committed into it.
    """
    if not os.path.isdir(DATA):
        return False
    for dirpath, _, files in os.walk(DATA):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), DATA)
            if rel not in PUBLISHED:
                return True
    return False


def requires_raw_store(case, what):
    """Skip `case` if the private raw store is absent.

    Deliberately checks for `data/` itself rather than for the specific file a
    test wants. If the store is here and one artifact is missing, that is a
    real failure and should be loud - it is how a deleted or half-written
    capture gets noticed. If the store is not here at all, there is nothing to
    say and a skip is the honest result.
    """
    if not raw_store_present():
        case.skipTest(
            "%s needs the raw store, which is not in this repository "
            "(ADR-0015). Derived numbers are published in docs/evidence/."
            % what)
