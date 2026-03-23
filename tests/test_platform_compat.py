from __future__ import annotations

from pathlib import Path

from clawteam.platform_compat import exclusive_file_lock, shell_join


def test_exclusive_file_lock_creates_lock_file(tmp_path: Path):
    lock_path = tmp_path / ".lock"

    with exclusive_file_lock(lock_path):
        assert lock_path.exists()

    assert lock_path.read_bytes().startswith(b"0")


def test_shell_join_uses_unix_separator(monkeypatch):
    monkeypatch.setattr("clawteam.platform_compat.is_windows", lambda: False)
    assert shell_join(["echo one", "echo two"]) == "echo one; echo two"


def test_shell_join_uses_windows_separator(monkeypatch):
    monkeypatch.setattr("clawteam.platform_compat.is_windows", lambda: True)
    assert shell_join(["echo one", "echo two"]) == "echo one & echo two"
