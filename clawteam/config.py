"""Persistent configuration for ClawTeam."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from clawteam.fileutil import atomic_write_text


class AgentProfile(BaseModel):
    """Reusable agent runtime profile for spawn/launch."""

    description: str = ""
    agent: str = ""
    command: list[str] = Field(default_factory=list)
    model: str = ""
    base_url: str = ""
    base_url_env: str = ""
    api_key_env: str = ""
    api_key_target_env: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    env_map: dict[str, str] = Field(default_factory=dict)
    args: list[str] = Field(default_factory=list)


class AgentPreset(BaseModel):
    """Shared preset input for generating client-scoped profiles."""

    description: str = ""
    auth_env: str = ""
    base_url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    client_overrides: dict[str, AgentProfile] = Field(default_factory=dict)


class ClawTeamConfig(BaseModel):
    data_dir: str = ""
    user: str = ""
    default_team: str = ""
    transport: str = ""
    task_store: str = ""  # "file" (default) — extensible for redis/sql later
    workspace: str = "auto"  # "auto" | "always" | "never" | ""
    default_backend: str = "tmux"  # "tmux" | "subprocess"
    skip_permissions: bool = True  # pass --dangerously-skip-permissions to claude


def config_path() -> Path:
    """Fixed config location: ~/.clawteam/config.json (never affected by data_dir)."""
    return Path.home() / ".clawteam" / "config.json"


def load_config() -> ClawTeamConfig:
    """Load config from disk. Returns defaults if file doesn't exist."""
    p = config_path()
    if not p.exists():
        return ClawTeamConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return ClawTeamConfig.model_validate(data)
    except Exception:
        return ClawTeamConfig()


def save_config(cfg: ClawTeamConfig) -> None:
    """Atomically write config to disk (mkstemp + replace)."""
    atomic_write_text(config_path(), cfg.model_dump_json(indent=2))


def get_effective(key: str) -> tuple[str, str]:
    """Get effective value for a config key. Returns (value, source).

    Priority: env var > config file > default.
    """
    env_map = {
        "data_dir": "CLAWTEAM_DATA_DIR",
        "user": "CLAWTEAM_USER",
        "default_team": "CLAWTEAM_TEAM_NAME",
        "transport": "CLAWTEAM_TRANSPORT",
        "task_store": "CLAWTEAM_TASK_STORE",
        "workspace": "CLAWTEAM_WORKSPACE",
        "default_backend": "CLAWTEAM_DEFAULT_BACKEND",
        "skip_permissions": "CLAWTEAM_SKIP_PERMISSIONS",
    }
    defaults = ClawTeamConfig()
    cfg = load_config()

    env_key = env_map.get(key)
    if env_key:
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val, "env"

    file_val = getattr(cfg, key, "")
    default_val = getattr(defaults, key, "")
    if file_val != default_val:
        return str(file_val), "file"

    return str(default_val), "default"
