"""Shared fixtures for clawteam tests.

We redirect all file-based state to tmp_path so tests never touch the real ~/.clawteam.
"""


import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point CLAWTEAM_DATA_DIR at a temp dir so every test gets a clean slate."""
    data_dir = tmp_path / ".clawteam"
    data_dir.mkdir()
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_dir))
    # Also override HOME so config_path() doesn't hit real ~/.clawteam/config.json
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return data_dir


@pytest.fixture
def team_name():
    return "test-team"
