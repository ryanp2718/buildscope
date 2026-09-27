"""Writing the harness's shared files safely: atomically, and under a lock.

Two failures this exists for, both from the 2026-09-26 fairness audit
(docs/evidence/2026-09-26-model-comparison-fairness-audit.md, step 4):

- A write interrupted halfway left truncated JSON behind. For a cache entry
  that key failed to load on every later hit; for `variance.json` the reader
  treated the unreadable file as empty, so the next save would have replaced
  every cell with one.
- Two processes ran the same variance cell at once on 2026-09-25. Both paid
  for draw 1, `variance.json` kept one response and the cache the other, and
  the cell stopped replaying to its own record. Its read-merge-write had no
  lock, so two runs of different cells could also drop each other's update.

`atomic_write` writes a temporary file beside the target and swaps it in with
`os.replace`, so a reader sees the old file or the new one and never part of
either. `update_json` holds a lock across the read, the merge and the write.
`run_lock` is taken for the whole run of one cell, without waiting: a second
process on the same cell is refused before it buys anything.

Locks are `filelock` lock files, `<path>.lock` beside the file they guard.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import filelock

# How long a writer waits for another writer's merge to finish. A merge is a
# read and a write of a file under a megabyte, so a wait this long means the
# holder is stuck, not busy.
MERGE_TIMEOUT_S = 60.0


class Busy(RuntimeError):
    """Another process holds the lock. Nothing was done."""


def read_json(path: str) -> Any:
    """The parsed file, with the handle closed. A missing file raises, and so
    does an unreadable one: treating it as empty is how a save wipes it."""
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write(path: str, text: str, newline: str | None = None) -> None:
    """Replace `path` with `text` in one step.

    `newline` is `io.open`'s: None translates each newline to the platform's
    line ending, as the plain writes this replaces did; a caller whose text
    already carries its line endings, like a CSV, passes "".

    The temporary file is in the target's directory so `os.replace` is a
    rename on one volume, which is atomic on NTFS and POSIX. On Windows a
    rename onto a file another process has open for reading fails with a
    sharing violation, so it is retried briefly; readers here hold a file
    only for the length of one `json.load`.
    """
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".",
                               suffix=".tmp")
    try:
        with io.open(fd, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def lock_for(path: str, timeout: float = MERGE_TIMEOUT_S) -> filelock.FileLock:
    return filelock.FileLock(path + ".lock", timeout=timeout)


def update_json(path: str, merge: Callable[[dict[str, Any]], dict[str, Any]],
                default: dict[str, Any] | None = None, indent: int = 1,
                ) -> dict[str, Any]:
    """Read `path`, apply `merge`, write the result, all under one lock.

    `merge` receives the file as it is now, not as it was when the caller
    last read it, so another process's update in between is kept. A missing
    file starts from `default`; an unreadable one raises.
    """
    try:
        with lock_for(path):
            current = read_json(path) if os.path.exists(path) else dict(default or {})
            out = merge(current)
            atomic_write(path, json.dumps(out, indent=indent, sort_keys=True,
                                          default=str))
            return out
    except filelock.Timeout:
        raise Busy("%s has been locked for over %.0f s by another process"
                   % (path, MERGE_TIMEOUT_S)) from None


@contextmanager
def run_lock(path: str, what: str) -> Iterator[None]:
    """Hold `path` for the whole of a run, or refuse at once."""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    lock = filelock.FileLock(path, timeout=0)
    try:
        lock.acquire()
    except filelock.Timeout:
        raise Busy("%s is being run by another process. Nothing was sent."
                   % what) from None
    try:
        yield
    finally:
        lock.release()
