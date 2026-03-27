"""Leader self-healing loop.

Monitors dead agents and performs controlled auto-respawn with backoff/budget.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from clawteam.config import get_effective
from clawteam.spawn import get_backend
from clawteam.spawn.registry import get_registry, list_dead_agents
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus, get_data_dir
from clawteam.team.tasks import TaskStore


@dataclass
class LeaderLoopConfig:
    auto_respawn: bool = True
    respawn_backoff_seconds: int = 30
    max_respawns_per_agent: int = 2
    max_parallel_agents: int = 4


class LeaderLoop:
    def __init__(self, team_name: str, mailbox: MailboxManager, config: LeaderLoopConfig | None = None):
        self.team_name = team_name
        self.mailbox = mailbox
        self.task_store = TaskStore(team_name)
        self.config = config or _load_config_from_effective()
        self._state_path = get_data_dir() / "teams" / team_name / "leader_loop_state.json"

    def run_once(self) -> dict:
        released = self.task_store.release_stale_locks()
        dead_agents = list_dead_agents(self.team_name)

        in_progress = self.task_store.list_tasks(status=TaskStatus.in_progress)
        active_agents = {
            t.owner
            for t in in_progress
            if t.owner
        }

        # Bootstrap: treat members with no registry entry as "dead" so the
        # loop spawns them without manual intervention.
        for member in TeamManager.list_members(self.team_name):
            if member.name == TeamManager.get_leader_name(self.team_name):
                continue
            if member.name not in dead_agents:
                registry = get_registry(self.team_name)
                if member.name not in registry:
                    dead_agents.append(member.name)

        result = {
            "team": self.team_name,
            "released_locks": released,
            "dead_agents": dead_agents,
            "active_agents": sorted(active_agents),
            "respawned": [],
            "skipped": [],
            "failed": [],
        }

        if not self.config.auto_respawn:
            return result

        state = self._load_state()
        now = time.time()
        desired_backend_raw, _ = get_effective("default_backend")
        desired_backend = (desired_backend_raw or "subprocess").strip() or "subprocess"

        for agent_name in dead_agents:
            agent_state = state.setdefault("agents", {}).setdefault(agent_name, {
                "attempts": 0,
                "last_attempt": 0.0,
                "permanent_failure": False,
                "last_error": "",
                "backend_policy": desired_backend,
            })

            # If backend strategy changed (e.g. tmux -> subprocess), clear old
            # permanent-failure lockout and retry budget for recovery.
            if agent_state.get("backend_policy") != desired_backend:
                agent_state["attempts"] = 0
                agent_state["last_attempt"] = 0.0
                agent_state["permanent_failure"] = False
                agent_state["last_error"] = ""
                agent_state["backend_policy"] = desired_backend

            if agent_state.get("permanent_failure"):
                result["skipped"].append({"agent": agent_name, "reason": "permanent_failure"})
                continue

            if agent_state.get("attempts", 0) >= self.config.max_respawns_per_agent:
                agent_state["permanent_failure"] = True
                result["skipped"].append({"agent": agent_name, "reason": "retry_exhausted"})
                self._notify_leader(
                    f"Auto-respawn exhausted for '{agent_name}' (attempts={agent_state['attempts']}). "
                    "Manual intervention required."
                )
                continue

            last_attempt = float(agent_state.get("last_attempt") or 0.0)
            if now - last_attempt < self.config.respawn_backoff_seconds:
                result["skipped"].append({"agent": agent_name, "reason": "backoff"})
                continue

            # Resource guard: cap active workers to reduce OOM / overload cascades.
            if self.config.max_parallel_agents > 0 and len(active_agents) >= self.config.max_parallel_agents:
                result["skipped"].append({"agent": agent_name, "reason": "parallel_limit"})
                continue

            ok, info = self._respawn_agent(agent_name)
            agent_state["last_attempt"] = now
            agent_state["attempts"] = int(agent_state.get("attempts", 0)) + 1

            if ok:
                agent_state["last_error"] = ""
                result["respawned"].append({"agent": agent_name, **info})
                active_agents.add(agent_name)
                self._notify_leader(
                    f"Auto-respawned '{agent_name}' via {info.get('backend')} backend. "
                    f"Task: {info.get('task_id', '-')}."
                )
            else:
                err = info.get("error", "unknown")
                agent_state["last_error"] = err
                if _is_permanent_spawn_error(err):
                    agent_state["permanent_failure"] = True
                result["failed"].append({"agent": agent_name, "error": err})
                self._notify_leader(
                    f"Auto-respawn failed for '{agent_name}': {err}"
                )

        self._save_state(state)
        return result

    def run_forever(self, interval_seconds: float = 10.0, stop_when_done: bool = False) -> None:
        while True:
            self.run_once()
            if stop_when_done and self._all_tasks_completed():
                return
            time.sleep(interval_seconds)

    def _respawn_agent(self, agent_name: str) -> tuple[bool, dict]:
        registry = get_registry(self.team_name)
        reg_info = registry.get(agent_name, {})

        # Aggressive mode: ignore per-agent backend in registry.
        # Use global default_backend for all respawns (tmux is treated as non-essential).
        default_backend_raw, _ = get_effective("default_backend")
        backend_name = (default_backend_raw or "subprocess").strip() or "subprocess"
        command = reg_info.get("command") or ["openclaw"]

        # Pick a pending task for this agent as resume entrypoint.
        tasks = self.task_store.list_tasks(owner=agent_name)
        pending = [
            t for t in tasks
            if t.status == TaskStatus.pending and not t.blocked_by
        ]
        task = pending[0] if pending else None

        leader_name = TeamManager.get_leader_name(self.team_name) or "leader"
        prompt = None
        if task:
            prompt = (
                f"You are {agent_name} in team {self.team_name}. "
                f"Your task is #{task.id}: {task.subject}. "
                "Continue work, send progress/results to leader inbox with sources, "
                "then mark task completed when done."
            )

        member = TeamManager.get_member(self.team_name, agent_name)
        agent_id = member.agent_id if member else uuid.uuid4().hex[:12]
        agent_type = member.agent_type if member else "general-purpose"

        skip_raw, _ = get_effective("skip_permissions")
        skip_permissions = str(skip_raw).lower() not in ("false", "0", "no", "")

        be = get_backend(backend_name)
        msg = be.spawn(
            command=list(command),
            agent_name=agent_name,
            agent_id=agent_id,
            agent_type=agent_type,
            team_name=self.team_name,
            prompt=prompt,
            skip_permissions=skip_permissions,
        )
        if msg.startswith("Error"):
            return False, {"error": msg}

        return True, {
            "backend": backend_name,
            "task_id": task.id if task else "",
            "message": msg,
        }

    def _notify_leader(self, content: str) -> None:
        leader_name = TeamManager.get_leader_name(self.team_name)
        if not leader_name:
            return
        self.mailbox.send(
            from_agent="leader-loop",
            to=leader_name,
            content=content,
        )

    def _all_tasks_completed(self) -> bool:
        tasks = self.task_store.list_tasks()
        if not tasks:
            return False
        return all(t.status == TaskStatus.completed for t in tasks)

    def _load_state(self) -> dict:
        if not self._state_path.exists():
            return {"agents": {}}
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"agents": {}}

    def _save_state(self, state: dict) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._state_path)


def _load_config_from_effective() -> LeaderLoopConfig:
    auto_raw, _ = get_effective("auto_respawn")
    backoff_raw, _ = get_effective("respawn_backoff_seconds")
    max_raw, _ = get_effective("max_respawns_per_agent")
    parallel_raw, _ = get_effective("max_parallel_agents")

    auto_respawn = str(auto_raw).lower() not in ("false", "0", "no", "")
    try:
        backoff = int(float(backoff_raw))
    except (TypeError, ValueError):
        backoff = 30
    try:
        max_respawns = int(float(max_raw))
    except (TypeError, ValueError):
        max_respawns = 2
    try:
        max_parallel = int(float(parallel_raw))
    except (TypeError, ValueError):
        max_parallel = 4

    return LeaderLoopConfig(
        auto_respawn=auto_respawn,
        respawn_backoff_seconds=max(backoff, 0),
        max_respawns_per_agent=max(max_respawns, 0),
        max_parallel_agents=max(max_parallel, 0),
    )


def _is_permanent_spawn_error(error: str) -> bool:
    e = (error or "").lower()
    markers = (
        "not installed",
        "not found in path",
        "unknown spawn backend",
        "failed to launch tmux session",
    )
    return any(m in e for m in markers)
