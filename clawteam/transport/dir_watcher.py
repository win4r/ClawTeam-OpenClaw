"""Directory mtime + filename-set watcher (stdlib-only).

Why both signals: macOS APFS mtime is rounded to 1 second. Two file writes within
the same second produce equal mtimes; the filename-set hash catches the second write.

The ``on_change`` callback receives the full ``Path`` of each newly detected file.
For pure modification events (mtime advanced, no new files), it receives the
directory path instead.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Callable


class DirectoryMtimeWatcher:
    """Poll a directory for changes using mtime AND a sorted-filename-set SHA1.

    Daemon thread; active poll interval is ``poll_ms`` (default 250 ms),
    dropping to ``idle_poll_ms`` (default 1 s) after ``quiet_ticks_until_idle``
    consecutive ticks with no change.

    No third-party dependencies — stdlib only.
    """

    def __init__(
        self,
        directory: Path,
        on_change: Callable[[Path], None],
        poll_ms: int = 250,
        idle_poll_ms: int = 1000,
        quiet_ticks_until_idle: int = 20,
    ) -> None:
        self._dir = directory
        self._cb = on_change
        self._active_interval = poll_ms / 1000.0
        self._idle_interval = idle_poll_ms / 1000.0
        self._quiet_thresh = quiet_ticks_until_idle
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # State seeded in _run() before loop to avoid startup false-positive
        self._last_mtime: float = 0.0
        self._last_set_hash: str = ""
        self._known_names: frozenset[str] = frozenset()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread (daemon).

        State is seeded *synchronously* here (on the caller's thread) before the
        background thread launches, so files written after ``start()`` returns are
        reliably detected as new.
        """
        self._last_mtime, self._known_names = self._read_dir()
        self._last_set_hash = self._set_hash(self._known_names)
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="DirMtimeWatcher"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to stop and wait up to 2 s for it to join."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_dir(self) -> tuple[float, frozenset[str]]:
        """Return (dir_mtime, frozenset of filenames) or (0.0, empty) on error."""
        if not self._dir.exists():
            return 0.0, frozenset()
        try:
            mtime = self._dir.stat().st_mtime
            names: frozenset[str] = frozenset(p.name for p in self._dir.iterdir())
            return mtime, names
        except OSError:
            return 0.0, frozenset()

    @staticmethod
    def _set_hash(names: frozenset[str]) -> str:
        return hashlib.sha1("\n".join(sorted(names)).encode()).hexdigest()

    def _run(self) -> None:
        quiet_ticks = 0
        while not self._stop.is_set():
            mtime, names = self._read_dir()
            set_hash = self._set_hash(names)

            mtime_changed = mtime > self._last_mtime
            set_changed = set_hash != self._last_set_hash

            if mtime_changed or set_changed:
                new_names = names - self._known_names
                self._last_mtime = mtime
                self._last_set_hash = set_hash
                self._known_names = names

                if new_names:
                    # Notify once per new file so callers can react per-message
                    for name in sorted(new_names):
                        try:
                            self._cb(self._dir / name)
                        except Exception:
                            pass
                else:
                    # mtime advanced but no new files (file modification / deletion)
                    try:
                        self._cb(self._dir)
                    except Exception:
                        pass

                quiet_ticks = 0
            else:
                quiet_ticks += 1

            interval = (
                self._active_interval
                if quiet_ticks < self._quiet_thresh
                else self._idle_interval
            )
            self._stop.wait(interval)
