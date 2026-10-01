# -*- coding: utf-8 -*-
"""The package boundary, as a ratchet.

Three directories, one direction of dependency. `permits/` is the library and
imports nothing above it. `scripts/` holds the six maintained tools a reader
runs. `spikes/` is the lab notebook: probes, samples and one-shot runners kept
because the published numbers came out of them.

A module in `spikes/` that another spike imports is in the wrong place - it is
library code that happens to live in the notebook, reachable only through a
`sys.path` hack, under a name that describes the spike it was born in rather
than the job it does.

`measure_fetch.py` was the case that mattered. It is the capture layer - robots
handling, politeness, verdicts, the manifest, and D1's rule that a page may not
exist on disk without a manifest row written in the same operation - and 23
scripts imported it through a `sys.path` hack, under the name of the
measurement it was first written for. On 2026-09-22 it became
`permits/capture.py` and the entry below was deleted. That deletion is what a
finished refactor looks like here: `test_allowlist_has_no_dead_entries` fails
until the entry goes, so the ratchet cannot quietly become stale documentation.

`ALLOWED` is the remaining violation set. Entries may be deleted; adding one
requires editing this file, which is the point. A boundary nobody can cross
accidentally is worth more than a boundary that is correct and unenforced.
"""
import ast
import io
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SPIKES = os.path.join(ROOT, "spikes")
PERMITS = os.path.join(ROOT, "permits")

# Modules in spikes/ that siblings import. Measured 2026-09-21, one entry
# retired 2026-09-22. This may shrink and may not grow. Each entry names where
# it is going.
ALLOWED = {
    # -> mostly done. The fingerprint itself is now permits/fingerprint.py;
    #    what remains here is Spike C's corpus handling and page labelling,
    #    which is spike-specific and should stay.
    "spike_c_fingerprint": 3,
    # -> dies with the Spike A probes. Not worth moving; worth deleting once
    #    the tier-2 reruns are no longer re-runnable.
    "spike_a_query_probe": 2,
    # -> permits/bps.py when the frame loader is extracted.
    "spike_b_sample": 1,
}

# Distribution name -> the module it imports as, where they differ. Only
# needed for packages whose import name is not their PyPI name.
IMPORT_NAMES = {
    "opentelemetry-api": "opentelemetry",
    "opentelemetry-sdk": "opentelemetry",
    "opentelemetry-exporter-otlp-proto-http": "opentelemetry",
    "langgraph-checkpoint-sqlite": "langgraph",
}


def declared_dependencies():
    """Top-level import names permitted by pyproject.toml.

    Parsed with a regex rather than tomllib so the rule is readable at the
    call site and does not depend on the section ordering of the file.
    """
    path = os.path.join(ROOT, "pyproject.toml")
    if not os.path.exists(path):
        return set()
    text = io.open(path, encoding="utf-8").read()
    out = set()
    for raw in re.findall(r'"([A-Za-z0-9._-]+)(?:[<>=!~\[].*?)?"', text):
        name = raw.strip().lower()
        out.add(IMPORT_NAMES.get(name, name.replace("-", "_")))
    return out


IMPORT = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)


def module_names(d):
    return {f[:-3] for f in os.listdir(d) if f.endswith(".py")}


def cross_imports(d, names=None):
    """{module: set(importers)} for files in `d` importing `names`.

    `names` defaults to `d`'s own modules, which makes this a sibling-import
    census. Passing another directory's names asks the other question: does
    `d` reach into it?
    """
    names = module_names(d) if names is None else names
    out = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py"):
            continue
        with io.open(os.path.join(d, f), encoding="utf-8") as fh:
            src = fh.read()
        for mod in IMPORT.findall(src):
            if mod in names and mod != f[:-3]:
                out.setdefault(mod, set()).add(f)
    return out


class TestPackageBoundary(unittest.TestCase):

    def test_no_new_library_modules_in_spikes(self):
        found = cross_imports(SPIKES)
        new = sorted(set(found) - set(ALLOWED))
        self.assertEqual(
            new, [],
            "new library module(s) in spikes/: %s. Library code belongs in "
            "permits/. If this is genuinely a spike helper, add it to ALLOWED "
            "with a note saying where it is going - deliberately, not by "
            "accident." % ", ".join(new))

    def test_the_ratchet_only_tightens(self):
        found = cross_imports(SPIKES)
        grew = []
        for mod, cap in sorted(ALLOWED.items()):
            n = len(found.get(mod, ()))
            if n > cap:
                grew.append("%s: %d importers, was %d" % (mod, n, cap))
        self.assertEqual(grew, [],
                         "a known boundary violation got worse: %s. Import "
                         "the library from permits/ instead of widening this."
                         % "; ".join(grew))

    def test_allowlist_has_no_dead_entries(self):
        """An entry that no longer describes reality is stale documentation
        pretending to be a constraint."""
        found = cross_imports(SPIKES)
        dead = sorted(m for m in ALLOWED if m not in found)
        self.assertEqual(dead, [],
                         "ALLOWED names modules nothing imports any more: %s. "
                         "Delete the entry - that is a refactor finishing."
                         % ", ".join(dead))


class TestToolsAreNotTheNotebook(unittest.TestCase):
    """`scripts/` is the maintained surface. It has no allowlist.

    The files in `scripts/` are what the README tells a reader to run, so
    each has to stand on its own: everything shared comes from `permits/`, and
    nothing reaches sideways into a sibling tool or downwards into `spikes/`.
    There is no ratchet here because there is nothing to ratchet - the rule
    has held since the split and a violation would mean a tool is one deleted
    probe away from breaking.
    """

    def test_tools_do_not_import_each_other(self):
        found = cross_imports(SCRIPTS)
        self.assertEqual(
            found, {},
            "scripts/ imports a sibling: %s. Shared code between two tools "
            "is library code - put it in permits/." % found)

    def test_tools_do_not_import_spikes(self):
        found = cross_imports(SCRIPTS, module_names(SPIKES))
        self.assertEqual(
            found, {},
            "a maintained tool imports the lab notebook: %s. spikes/ is kept "
            "for provenance and may be deleted; nothing in scripts/ may "
            "depend on it." % found)


class TestLibraryIsSelfContained(unittest.TestCase):
    """`permits/` may not import from `scripts/`, ever.

    This one is not a ratchet. It has never been violated and there is no
    reason it should be: a dependency pointing that way would make the library
    unusable without the spike directory, which is the boundary inverted.
    """

    def modules(self):
        for dirpath, _, files in os.walk(PERMITS):
            for f in sorted(files):
                if f.endswith(".py"):
                    yield os.path.join(dirpath, f)

    def test_no_imports_from_scripts(self):
        names = module_names(SCRIPTS) | module_names(SPIKES)
        for path in self.modules():
            with io.open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                mod = None
                if isinstance(node, ast.Import):
                    mod = node.names[0].name.split(".")[0]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mod = (node.module or "").split(".")[0]
                if mod and mod in names:
                    self.fail("%s imports scripts/%s.py"
                              % (os.path.relpath(path, ROOT), mod))

    def test_no_sys_path_hacks_in_the_library(self):
        """A `sys.path.insert` inside `permits/` means the package cannot be
        imported normally, which is the symptom the boundary exists to prevent.
        Half the scripts carry one; the library carries none."""
        for path in self.modules():
            with io.open(path, encoding="utf-8") as fh:
                src = fh.read()
            with self.subTest(module=os.path.relpath(path, ROOT)):
                self.assertNotIn("sys.path.insert", src)

    def test_imports_are_declared_dependencies(self):
        """Every import in `permits/` is stdlib or a declared dependency.

        This replaces the stdlib-only assertion retired by ADR-0017. The rule
        it enforced was never weighed for the inference layer and cost real
        things there - no retries, a hand-maintained per-model capability
        table, a streaming parser whose transport flag leaked into the cache
        key. What is worth keeping is the narrower property the old test was
        a blunt instrument for: nothing gets imported that `pyproject.toml`
        does not declare, so a fresh `uv sync` is sufficient to run this.
        """
        stdlib = set(getattr(__import__("sys"), "stdlib_module_names", ()))
        if not stdlib:
            self.skipTest("sys.stdlib_module_names unavailable")
        declared = declared_dependencies()
        self.assertTrue(declared, "no dependencies parsed from pyproject.toml")
        for path in self.modules():
            with io.open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                mod = None
                if isinstance(node, ast.Import):
                    mod = node.names[0].name.split(".")[0]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mod = (node.module or "").split(".")[0]
                if not mod or mod in stdlib or mod == "permits":
                    continue
                if mod not in declared:
                    self.fail(
                        "%s imports %r, which pyproject.toml does not "
                        "declare. Add it to [project] dependencies or stop "
                        "importing it."
                        % (os.path.relpath(path, ROOT), mod))


class TestTheAgentSeesNoReference(unittest.TestCase):
    """`permits/agent/` writes and checks extractors with no answer key.

    The adapters are the reference parsers; the scorer lives in
    `permits.harness`, and the hint text in `scripts/conformance.py`, which
    the library cannot import at all (`TestLibraryIsSelfContained`). An
    agent that could reach any of them would be graded by the answer key it
    was shown (docs/evidence/2026-09-29-agentic-extractor-plan.md), so the
    rule is checked, not trusted.
    """
    FORBIDDEN = ("permits.adapters", "permits.harness")

    def test_no_reference_imports(self):
        agent = os.path.join(PERMITS, "agent")
        for f in sorted(os.listdir(agent)):
            if not f.endswith(".py"):
                continue
            path = os.path.join(agent, f)
            with io.open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module] + ["%s.%s" % (node.module, a.name)
                                             for a in node.names]
                for name in names:
                    with self.subTest(module=f, imports=name):
                        self.assertFalse(
                            any(name == b or name.startswith(b + ".")
                                for b in self.FORBIDDEN),
                            "permits/agent/%s imports %s, a reference "
                            "parser" % (f, name))
                        self.assertNotIn("conformance", name)


class TestAdaptersStayThin(unittest.TestCase):
    """D8's shared emit interface: an adapter returns native strings and this
    module owns all normalization.

    The rule keeps the vendor-specific part of every adapter small and means a
    synthesized extractor is drop-in the moment it emits the same dict. An
    adapter that normalizes dates itself has forked the normalization path, and
    two normalization paths drift.
    """

    def adapters(self):
        d = os.path.join(PERMITS, "adapters")
        for f in sorted(os.listdir(d)):
            if f.endswith(".py") and f != "__init__.py":
                yield f, os.path.join(d, f)

    def test_build_does_not_normalize(self):
        """`build()` is where extracted values become a record, and it must
        hand them to the shared layer rather than interpreting them.

        The rule is about *extracted* values, not every date in the file. A
        first version of this test banned `strptime` anywhere in an adapter and
        failed on `stjohns.pull_window`, which uses it to bisect a query window
        when the portal truncates - that is query construction in the vendor's
        own date format, which is exactly the vendor-specific part that belongs
        in an adapter. Scoping the assertion to `build` is the difference
        between the rule and a proxy for it.
        """
        banned = ("strptime", "strftime", "datetime.")
        for name, path in self.adapters():
            with io.open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            fn = next((n for n in tree.body
                       if isinstance(n, ast.FunctionDef) and n.name == "build"),
                      None)
            if fn is None:
                continue
            body = ast.dump(ast.Module(body=fn.body, type_ignores=[]))
            for token in banned:
                with self.subTest(adapter=name, token=token):
                    self.assertNotIn(
                        token.rstrip("."), body,
                        "%s.build() interprets a date itself; extracted values "
                        "go through permits/emit.py or the normalization path "
                        "forks and the two copies drift" % name)

    def test_build_routes_units_through_the_emitter(self):
        """`unit_count_source` is not optional and not inferable. An adapter
        that assigns `rec.unit_count` directly bypasses the check that "0
        units" and "no unit field exists" stay different facts."""
        for name, path in self.adapters():
            with io.open(path, encoding="utf-8") as fh:
                src = fh.read()
            with self.subTest(adapter=name):
                self.assertNotIn(
                    "rec.unit_count =", src,
                    "%s assigns unit_count directly instead of calling "
                    "rec.units(value, source)" % name)

    def test_every_adapter_declares_a_version(self):
        for name, path in self.adapters():
            with io.open(path, encoding="utf-8") as fh:
                src = fh.read()
            with self.subTest(adapter=name):
                self.assertIn("ADAPTER_VERSION", src)


if __name__ == "__main__":
    unittest.main()
