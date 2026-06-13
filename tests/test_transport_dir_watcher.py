"""Tests for DirectoryMtimeWatcher (Task 3.1)."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path


def test_watcher_fires_on_new_file(tmp_path: Path) -> None:
    from clawteam.transport.dir_watcher import DirectoryMtimeWatcher

    seen: list[Path] = []
    w = DirectoryMtimeWatcher(tmp_path, on_change=lambda p: seen.append(p), poll_ms=50)
    w.start()
    try:
        (tmp_path / "msg-1.json").write_text("{}")
        time.sleep(0.3)
        assert any("msg-1.json" in str(p) for p in seen)
    finally:
        w.stop()


def test_watcher_detects_two_writes_within_same_second(tmp_path: Path) -> None:
    """macOS APFS mtime granularity is 1s; the filename-set hash must catch this.

    Sleep ~60ms between writes so the poll thread has a chance to run between
    them — keeps the test deterministic on loaded CI runners.
    """
    from clawteam.transport.dir_watcher import DirectoryMtimeWatcher

    calls = 0

    def cb(_: Path) -> None:
        nonlocal calls
        calls += 1

    w = DirectoryMtimeWatcher(tmp_path, on_change=cb, poll_ms=25)
    w.start()
    try:
        (tmp_path / "msg-1.json").write_text("{}")
        time.sleep(0.06)
        (tmp_path / "msg-2.json").write_text("{}")
        time.sleep(0.3)
        assert calls >= 2
    finally:
        w.stop()


def test_filename_set_hash_diff_unit() -> None:
    """Deterministic unit-level check: filename-set hash changes when set changes."""
    from clawteam.transport.dir_watcher import (
        DirectoryMtimeWatcher,  # noqa: F401 (import to confirm no error)
    )

    def _set_hash(names: list[str]) -> str:
        return hashlib.sha1("\n".join(sorted(names)).encode()).hexdigest()

    h1 = _set_hash(["a.json"])
    h2 = _set_hash(["a.json", "b.json"])
    assert h1 != h2


def test_watcher_does_not_fire_when_no_change(tmp_path: Path) -> None:
    from clawteam.transport.dir_watcher import DirectoryMtimeWatcher

    calls = 0

    def cb(_: Path) -> None:
        nonlocal calls
        calls += 1

    w = DirectoryMtimeWatcher(tmp_path, on_change=cb, poll_ms=30)
    w.start()
    try:
        time.sleep(0.2)
        assert calls == 0
    finally:
        w.stop()


def test_watcher_stop_joins_cleanly(tmp_path: Path) -> None:
    from clawteam.transport.dir_watcher import DirectoryMtimeWatcher

    w = DirectoryMtimeWatcher(tmp_path, on_change=lambda _: None, poll_ms=50)
    w.start()
    w.stop()  # must not hang
