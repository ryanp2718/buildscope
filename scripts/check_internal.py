# -*- coding: utf-8 -*-
"""Check INTERNAL/ talking points against the live sources they are copied from.

`check_docs.py` validates docs/ internally. Nothing validated INTERNAL/, and on
2026-09-21 `numbers.md` carried "$0 total inference spend" as headline figure 4
-- the one you are told to say without thinking -- after the conformance test
had spent $1.2751, checkable on disk the whole time. Quoting a withdrawn or
stale figure and then being asked how it was measured converts the project's
greatest strength into its worst moment, so this exists to make that class of
error loud.

What it checks, all against live sources rather than prose:

  1. the inference spend quoted in INTERNAL/ matches data/infer/ledger.jsonl
  2. the test count quoted anywhere matches what run_tests.py collects
  3. the step-1 record count quoted in INTERNAL/ matches data/step1/records/
  4. no figure on the do-not-say list appears outside numbers.md

Usage: python scripts/check_internal.py
Exits non-zero on any mismatch.
"""
import io
import json
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INTERNAL = os.path.join(ROOT, "INTERNAL")

problems = []


def fail(where, msg):
    problems.append("%s: %s" % (where, msg))


def read(path):
    return io.open(path, encoding="utf-8").read()


def internal_files():
    return sorted(glob.glob(os.path.join(INTERNAL, "*.md")))


# ----------------------------------------------------------- live quantities
def ledger_total():
    """Total USD and call count from the inference ledger."""
    p = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
    if not os.path.exists(p):
        return None, 0
    total, n = 0.0, 0
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            fail("ledger.jsonl", "unparseable row")
            continue
        total += float(d.get("usd") or 0)
        n += 1
    return round(total, 4), n


def test_count():
    """Number of tests collected, without running them."""
    try:
        sys.path.insert(0, ROOT)
        import unittest
        loader = unittest.TestLoader()
        suite = loader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)

        def count(s):
            return sum(count(x) if isinstance(x, unittest.TestSuite) else 1
                       for x in s)
        return count(suite)
    except Exception as e:                      # discovery is best-effort
        fail("tests", "could not collect: %s" % e)
        return None


def record_count():
    d = os.path.join(ROOT, "data", "step1", "records")
    if not os.path.isdir(d):
        return None
    total = 0
    for p in glob.glob(os.path.join(d, "*.jsonl")):
        total += sum(1 for line in io.open(p, encoding="utf-8") if line.strip())
    return total


# ---------------------------------------------------------------- the checks
# A figure is a problem only when it is *asserted*. Every one of these documents
# legitimately discusses withdrawn numbers -- that discussion is the point of the
# do-not-say list and of the failure stories -- so a bare string match flags the
# files doing the right thing. Look at the surrounding window instead.
MARKERS = re.compile(
    r"withdraw|do not say|don't say|never measured|invented|killed|dead|"
    r"retired|supersede|no longer|true until|stale|false|wrong|correct|"
    r"unsupportable|not supportable|may not|rather than|instead of|"
    r"lower bound|provisional|less tidy|say instead|floor|it does not exist",
    re.I)


def _paragraph(text, start, end):
    """The contiguous block of non-blank lines containing the match.

    A character window is the wrong scope: these documents discuss withdrawn
    figures constantly, so a window wide enough to avoid false positives
    reaches into neighbouring prose and masks a real assertion. Markdown is
    line-oriented -- a table row is one line and a claim sits with its
    correction in the same row or paragraph -- so the paragraph is the unit
    that actually separates "asserted here" from "corrected nearby".
    """
    sep = "\n\n"
    lo = text.rfind(sep, 0, start)
    lo = 0 if lo < 0 else lo + len(sep)
    hi = text.find(sep, end)
    hi = len(text) if hi < 0 else hi
    return text[lo:hi]


def asserted(text, start, end):
    """True if the match is stated as fact rather than flagged as withdrawn."""
    return not MARKERS.search(_paragraph(text, start, end))


def check_spend():
    total, n = ledger_total()
    if total is None:
        return
    for path in internal_files():
        text = read(path)
        name = os.path.relpath(path, ROOT)
        # Any claim that total spend is $0 is false once the ledger is non-empty.
        for m in re.finditer(r"[Tt]otal inference spend[^\n|]{0,40}?\$([0-9]+(?:\.[0-9]+)?)", text):
            got = float(m.group(1))
            if not asserted(text, m.start(), m.end()):
                continue
            if abs(got - total) > 0.01:      # tolerate 2-dp rounding
                fail(name, "quotes total inference spend $%s; ledger says $%.4f "
                           "over %d calls" % (m.group(1), total, n))
        if total > 0 and re.search(r"inference spend:?\s*\*?\*?\$0\b", text):
            fail(name, "asserts $0 inference spend; ledger says $%.4f over %d "
                       "calls" % (total, n))


def check_tests():
    n = test_count()
    if n is None:
        return
    targets = [*internal_files(),
               os.path.join(ROOT, "docs", "design", "testing.md")]
    for path in targets:
        if not os.path.exists(path):
            continue
        text = read(path)
        name = os.path.relpath(path, ROOT)
        for m in re.finditer(r"\b([0-9]{2,4})\s+tests\b", text):
            got = int(m.group(1))
            if got != n:
                fail(name, "quotes %d tests; suite collects %d" % (got, n))


def check_records():
    n = record_count()
    if n is None:
        return
    for path in internal_files():
        text = read(path)
        name = os.path.relpath(path, ROOT)
        # Only the step-1 store total, which is always written with a tilde:
        # "~29,700 records" / "~29.7k record rows". Bare counts elsewhere are
        # other quantities and must not be compared against this one.
        for m in re.finditer(r"~([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+\.[0-9]k)\s+record", text):
            raw = m.group(1)
            got = (float(raw[:-1]) * 1000 if raw.endswith("k")
                   else float(raw.replace(",", "")))
            if abs(got - n) / float(n) > 0.02:      # 2% tolerance for rounding
                fail(name, "quotes %s records; store holds %d" % (raw, n))


# Figures formally withdrawn. Discussing one is fine and expected; asserting
# one is the error. `asserted()` draws that line.
#
# The multiplication signs and en dashes below are deliberate and must
# not be normalized to ASCII: these patterns match how the figures were
# actually typed in the documents, and the documents use the
# typographic characters.
WITHDRAWN = [
    (r"\b340\s*[x×]",  # noqa: RUF001
     "340x cost reduction (invented, never measured)"),
    (r"\b20\s*[-–]\s*60\s*[x×]",  # noqa: RUF001
     "20-60x amortization (withdrawn by Spike C)"),
    (r"\b28\.5%\s+enumerable", "28.5% enumerable (superseded by St. Johns)"),
    (r"floor is 39\.2%", "39.2% fallback floor (superseded)"),
]


def check_withdrawn():
    for path in internal_files():
        text = read(path)
        name = os.path.relpath(path, ROOT)
        for pat, what in WITHDRAWN:
            for m in re.finditer(pat, text):
                if asserted(text, m.start(), m.end()):
                    fail(name, "asserts withdrawn figure: %s" % what)


def main():
    if not internal_files():
        sys.stdout.write(
            "INTERNAL check skipped: no INTERNAL/*.md in this checkout. "
            "Those are working notes about the author rather than about the "
            "project and are not published, so there is nothing here to "
            "cross-check against the ledger.\n")
        return 0
    check_spend()
    check_tests()
    check_records()
    check_withdrawn()

    if problems:
        sys.stdout.write("INTERNAL check FAILED\n\n")
        for p in problems:
            sys.stdout.write("  %s\n" % p)
        sys.stdout.write("\n%d problem(s). docs/evidence/ wins every "
                         "disagreement.\n" % len(problems))
        return 1

    total, n = ledger_total()
    sys.stdout.write("INTERNAL check ok: spend $%.4f over %d calls, %s tests, "
                     "%s records\n" % (total or 0.0, n, test_count(),
                                       record_count()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
