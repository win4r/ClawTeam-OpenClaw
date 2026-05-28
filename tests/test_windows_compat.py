"""Regression tests for Windows import compatibility."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module_as_windows(monkeypatch: pytest.MonkeyPatch, relative_path: str):
    fake_msvcrt = types.SimpleNamespace(
        LK_LOCK=1,
        LK_UNLCK=2,
        LK_NBLCK=3,
    )
    module_path = _REPO_ROOT / relative_path
    module_name = f"_wincheck_{relative_path.replace('/', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module, fake_msvcrt


@pytest.mark.parametrize(
    ("relative_path", "expects_lock_constants"),
    [
        ("clawteam/fileutil.py", False),
        ("clawteam/store/file.py", False),
        ("clawteam/team/snapshot.py", False),
        ("clawteam/transport/file.py", True),
    ],
)
def test_windows_specific_modules_import_without_fcntl(monkeypatch, relative_path, expects_lock_constants):
    module, fake_msvcrt = _load_module_as_windows(monkeypatch, relative_path)

    assert "fcntl" not in module.__dict__
    assert module.msvcrt is fake_msvcrt
    if expects_lock_constants:
        assert module.LOCK_EX == fake_msvcrt.LK_NBLCK
        assert module.LOCK_NB == 0
