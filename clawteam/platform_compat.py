"""Centralized cross-platform compatibility helpers."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


def is_windows() -> bool:
    """Return True when running on Windows."""
    return os.name == "nt"


def default_spawn_backend() -> str:
    """Return the default spawn backend for the current platform."""
    return "subprocess" if is_windows() else "tmux"


@contextmanager
def exclusive_file_lock(path: Path):
    """Acquire a blocking exclusive file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock_file:
        lock_file.seek(0)
        if path.stat().st_size == 0:
            lock_file.write(b"0")
            lock_file.flush()

        if is_windows():
            import msvcrt

            lock_file.seek(0)
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            lock_file.seek(0)
            if is_windows():
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def install_signal_handlers(
    handler: Callable[[int, object], None],
    signal_names: tuple[str, ...] = ("SIGINT", "SIGTERM"),
) -> list[tuple[signal.Signals, object]]:
    """Install a handler for supported signals and return previous handlers."""
    previous: list[tuple[signal.Signals, object]] = []
    for name in signal_names:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous.append((sig, signal.getsignal(sig)))
            signal.signal(sig, handler)
        except (OSError, RuntimeError, ValueError):
            continue
    return previous


def restore_signal_handlers(previous: list[tuple[signal.Signals, object]]) -> None:
    """Restore signal handlers captured by install_signal_handlers()."""
    for sig, handler in previous:
        try:
            signal.signal(sig, handler)
        except (OSError, RuntimeError, ValueError):
            continue


def shell_join(commands: list[str]) -> str:
    """Join shell commands using the current platform's shell syntax."""
    separator = " & " if is_windows() else "; "
    return separator.join(command for command in commands if command)


def shell_quote(arg: str) -> str:
    """Quote a shell argument for the current platform."""
    if is_windows():
        return subprocess.list2cmdline([arg])
    return shlex.quote(arg)


def pid_alive(pid: int) -> bool:
    """Return True when a process is still running."""
    if pid <= 0:
        return False

    if is_windows():
        import ctypes

        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(process)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
