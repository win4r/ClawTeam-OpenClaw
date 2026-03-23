"""Agent identity for team context with multi-prefix environment variable support."""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass, field


def _env(clawteam_key: str, claude_code_key: str, default: str = "") -> str:
    """Read from CLAWTEAM_* first, fall back to OPENCLAW_* or CLAUDE_CODE_*."""
    openclaw_key = clawteam_key.replace("CLAWTEAM_", "OPENCLAW_", 1)
    return (
        os.environ.get(clawteam_key)
        or os.environ.get(openclaw_key)
        or os.environ.get(claude_code_key)
        or default
    )


def _env_bool(clawteam_key: str, claude_code_key: str) -> bool:
    val = _env(clawteam_key, claude_code_key)
    return val.lower() in ("1", "true", "yes")


def _read_ppid(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _read_cmd(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def _extract_session_key_from_command(command: str) -> str | None:
    if not command or "openclaw" not in command:
        return None
    parts = command.split()
    for i, part in enumerate(parts):
        if part in ("--session", "--session-id") and i + 1 < len(parts):
            return parts[i + 1].strip("\"'")
        if part.startswith("--session=") or part.startswith("--session-id="):
            return part.split("=", 1)[1].strip("\"'")
    return None


def _session_key_from_process_tree() -> str | None:
    pid = os.getpid()
    seen: set[int] = set()
    for _ in range(12):
        if pid in seen or pid <= 1:
            break
        seen.add(pid)
        cmd = _read_cmd(pid)
        session_key = _extract_session_key_from_command(cmd)
        if session_key:
            return session_key
        ppid = _read_ppid(pid)
        if not ppid:
            break
        pid = ppid
    return None


def runtime_session_record() -> dict[str, str] | None:
    """Resolve the current worker's ClawTeam registry record from session ancestry."""
    session_key = _session_key_from_process_tree()
    if not session_key:
        return None
    try:
        from clawteam.spawn.registry import find_agent_by_session_key

        record = find_agent_by_session_key(session_key)
        if isinstance(record, dict):
            return record
    except Exception:
        return None
    return None


def resolve_runtime_data_dir() -> str | None:
    """Resolve CLAWTEAM data_dir from the current OpenClaw worker session."""
    env_data_dir = os.environ.get("CLAWTEAM_DATA_DIR", "").strip()
    if env_data_dir:
        return env_data_dir
    record = runtime_session_record() or {}
    data_dir = str(record.get("data_dir") or "").strip()
    return data_dir or None


@dataclass
class AgentIdentity:
    """Identity of an agent within a team (or standalone)."""

    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_name: str = "agent"
    user: str = ""
    agent_type: str = "general-purpose"
    team_name: str | None = None
    data_dir: str = ""
    is_leader: bool = False
    plan_mode_required: bool = False

    @property
    def in_team(self) -> bool:
        return self.team_name is not None

    @classmethod
    def from_env(cls) -> AgentIdentity:
        """Build identity from env first, then fall back to OpenClaw session registry."""
        user = os.environ.get("CLAWTEAM_USER", "")
        if not user:
            from clawteam.config import load_config

            user = load_config().user

        env_agent_name = _env("CLAWTEAM_AGENT_NAME", "CLAUDE_CODE_AGENT_NAME", "")
        env_team_name = _env("CLAWTEAM_TEAM_NAME", "CLAUDE_CODE_TEAM_NAME", "")
        env_agent_id = _env("CLAWTEAM_AGENT_ID", "CLAUDE_CODE_AGENT_ID", "")
        env_agent_type = _env("CLAWTEAM_AGENT_TYPE", "CLAUDE_CODE_AGENT_TYPE", "")
        env_data_dir = os.environ.get("CLAWTEAM_DATA_DIR", "")

        if env_agent_name and env_team_name:
            return cls(
                agent_id=env_agent_id or uuid.uuid4().hex[:12],
                agent_name=env_agent_name,
                user=user,
                agent_type=env_agent_type or "general-purpose",
                team_name=env_team_name or None,
                data_dir=env_data_dir,
                is_leader=_env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER"),
                plan_mode_required=_env_bool(
                    "CLAWTEAM_PLAN_MODE_REQUIRED", "CLAUDE_CODE_PLAN_MODE_REQUIRED"
                ),
            )

        session_identity = runtime_session_record() or {}
        if session_identity.get("agent_name") and session_identity.get("team_name"):
            return cls(
                agent_id=session_identity.get("agent_id") or env_agent_id or uuid.uuid4().hex[:12],
                agent_name=session_identity["agent_name"],
                user=user,
                agent_type=session_identity.get("agent_type") or env_agent_type or "general-purpose",
                team_name=session_identity["team_name"],
                data_dir=str(session_identity.get("data_dir") or env_data_dir or ""),
                is_leader=_env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER"),
                plan_mode_required=_env_bool(
                    "CLAWTEAM_PLAN_MODE_REQUIRED", "CLAUDE_CODE_PLAN_MODE_REQUIRED"
                ),
            )

        return cls(
            agent_id=env_agent_id or uuid.uuid4().hex[:12],
            agent_name=env_agent_name or "agent",
            user=user,
            agent_type=env_agent_type or "general-purpose",
            team_name=env_team_name or None,
            data_dir=env_data_dir,
            is_leader=_env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER"),
            plan_mode_required=_env_bool(
                "CLAWTEAM_PLAN_MODE_REQUIRED", "CLAUDE_CODE_PLAN_MODE_REQUIRED"
            ),
        )

    def to_env(self) -> dict[str, str]:
        """Export identity as environment variables (for spawning sub-agents)."""
        env = {
            "CLAWTEAM_AGENT_ID": self.agent_id,
            "CLAWTEAM_AGENT_NAME": self.agent_name,
            "CLAWTEAM_AGENT_TYPE": self.agent_type,
            "CLAWTEAM_AGENT_LEADER": "1" if self.is_leader else "0",
            "CLAWTEAM_PLAN_MODE_REQUIRED": "1" if self.plan_mode_required else "0",
        }
        if self.user:
            env["CLAWTEAM_USER"] = self.user
        if self.team_name:
            env["CLAWTEAM_TEAM_NAME"] = self.team_name
        if self.data_dir:
            env["CLAWTEAM_DATA_DIR"] = self.data_dir
        return env
