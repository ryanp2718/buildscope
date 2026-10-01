# -*- coding: utf-8 -*-
"""The agentic extractor: a tool-using agent and a scripted repair loop that
write an extractor for a portal, check it and repair it, with no reference to
compare against. Plan: docs/evidence/2026-09-29-agentic-extractor-plan.md.

Nothing here may import the adapters, the reference parsers, the scorer or
the hint text; `tests/test_structure.py` enforces it. The caller hands in the
prompt, the page files and the contract's field names.
"""
