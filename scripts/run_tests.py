# -*- coding: utf-8 -*-
"""Run everything that can fail without a network request.

    python scripts/run_tests.py           # the whole suite
    python scripts/run_tests.py emit      # just tests/test_emit.py
    python scripts/run_tests.py -q        # quiet

One command rather than four, because a check that has to be remembered is a
check that gets skipped. `check_docs.py` and `check_identity.py` are also
invoked from `tests/test_artifacts.py`, so they run either way; they are listed
separately here only so their output is visible when a human is watching.

Everything here is offline and free. Nothing in this file makes a request or a
model call, which is what makes it reasonable to run on every change.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(argv):
    quiet = "-q" in argv
    argv = [a for a in argv if not a.startswith("-")]
    verbosity = 1 if quiet else 2

    loader = unittest.TestLoader()
    if argv:
        names = ["tests.test_%s" % a.replace("test_", "") for a in argv]
        suite = loader.loadTestsFromNames(names)
    else:
        suite = loader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)

    print("=" * 70)
    print("PERMITS TEST SUITE - offline, no requests, no model calls")
    print("=" * 70)
    # The runner writes to stderr; without this the banner lands after the
    # results whenever output is piped.
    sys.stdout.flush()
    result = unittest.TextTestRunner(verbosity=verbosity,
                                     stream=sys.stdout).run(suite)

    print()
    print("-" * 70)
    print("%d tests, %d failures, %d errors, %d skipped"
          % (result.testsRun, len(result.failures), len(result.errors),
             len(result.skipped)))
    if result.skipped and not quiet:
        print("\nskipped (a skip is what a disabled test looks like - check "
              "these are intentional):")
        for case, why in result.skipped:
            print("   %-58s %s" % (str(case)[:58], why))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
