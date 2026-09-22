# -*- coding: utf-8 -*-
"""Tests for the permits pipeline.

Run them all with `python scripts/run_tests.py`, or the stdlib equivalent
`python -m unittest discover -s tests -t .` from the repository root.

**Stdlib `unittest`, not pytest, and that is a decision rather than an
accident.** This project has no third-party dependencies at all - the import
graph is `csv`, `json`, `re`, `urllib`, `hashlib`, `html.parser` and friends -
which is why a two-year-old script in `scripts/` still runs. Adding pytest to
get nicer assertions would make the test suite the only part of the system that
needs an install, and the first thing that breaks on a new machine. `subTest`
covers the parametrization that pytest is usually reached for.

**What these tests are for.** Not coverage. Every test here corresponds to a
defect that actually produced a wrong number in this project, or to an
invariant a published figure depends on. The suite is closer to a regression
set than to a unit-test suite, and `docs/design/testing.md` says which failure
each file is descended from.
"""
