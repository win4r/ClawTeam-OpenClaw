"""Leader watcher that periodically injects coordination reminders."""

from __future__ import annotations

import json
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawteam.fileutil import atomic_write_text
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import MessageType, TaskStatus, get_data_dir
from clawteam.team.redis_wakeup import (
    RedisWakeup,
    agent_channel,
    resolve_wakeup,
    subscribe_client,
    team_channel,
)
from clawteam.team.routing_policy import RuntimeEnvelope
from clawteam.team.tasks import TaskStore


@dataclass
class LeaderWatchResult:
    injected: bool
    reason: str
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    redis_event: bool = False


class LeaderWatcher:
    """Poll team state and wake the leader agent when action is needed."""

    def __init__(
        self,
        team_name: str,
        leader_name: str,
        *,
        interval: float = 60.0,
        heartbeat_interval: float = 300.0,
        redis_mode: str = "auto",
        json_output: bool = False,
        verbose: bool = False,
    ):
        validate_identifier(team_name, "team name")
        validate_identifier(leader_name, "leader name")
        self.team_name = team_name
        self.leader_name = leader_name
        self.interval = max(interval, 1.0)
        self.heartbeat_interval = max(heartbeat_interval, 1.0)
        self.redis_mode = redis_mode
        self.json_output = json_output
        self.verbose = verbose
        self.task_store = TaskStore(team_name)
        self.mailbox = MailboxManager(team_name)
        self.redis: RedisWakeup = RedisWakeup(False)
        self._running = False

    def run(self) -> None:
        """Run the blocking watcher loop."""
        self.redis = resolve_wakeup(self.team_name, self.redis_mode)
        self._running = True

        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)

        def _handle_signal(signum, frame):
            self._running = False

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        try:
            self.check_once(reason="startup")
            if self.redis.enabled:
                self._run_redis_loop()
            else:
                self._run_poll_loop()
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)

    def check_once(self, *, reason: str = "poll", redis_event: bool = False) -> LeaderWatchResult:
        """Check team state once and inject if state changed or heartbeat is due."""
        snapshot = self._collect_snapshot()
        state = self._read_state()
        signature = self._signature(snapshot)
        now = time.time()
        last_signature = str(state.get("lastSignature") or "")
        last_heartbeat = float(state.get("lastHeartbeatAt") or 0.0)

        changed = signature != last_signature
        heartbeat_due = now - last_heartbeat >= self.heartbeat_interval
        if not changed and not heartbeat_due:
            return LeaderWatchResult(False, "no_change", redis_event=redis_event)

        summary, evidence = self._render(snapshot, changed=changed, heartbeat_due=heartbeat_due)
        injected, status = self._inject(summary, evidence)
        state.update(
            {
                "lastSignature": signature,
                "lastCheckAt": now,
                "lastInjectAt": now if injected else state.get("lastInjectAt", 0.0),
                "lastInjectStatus": status,
            }
        )
        if heartbeat_due:
            state["lastHeartbeatAt"] = now
        self._write_state(state)
        result = LeaderWatchResult(
            injected=injected,
            reason=reason if changed else "heartbeat",
            summary=summary,
            evidence=evidence,
            redis_event=redis_event,
        )
        self._emit_result(result)
        return result

    def _run_poll_loop(self) -> None:
        while self._running:
            time.sleep(self.interval)
            self.check_once(reason="poll")

    def _run_redis_loop(self) -> None:
        client = subscribe_client(self.redis.url)
        if client is None:
            self.redis = RedisWakeup(False, reason="redis client unavailable")
            self._run_poll_loop()
            return
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            try:
                from clawteam.team.manager import TeamManager
                leader_inbox = TeamManager.resolve_inbox(self.team_name, self.leader_name)
            except Exception:
                leader_inbox = self.leader_name
            channels = {
                agent_channel(self.team_name, self.leader_name),
                agent_channel(self.team_name, leader_inbox),
                team_channel(self.team_name, "tasks"),
                team_channel(self.team_name, "events"),
            }
            pubsub.subscribe(
                *sorted(channels),
            )
            while self._running:
                try:
                    message = pubsub.get_message(timeout=self.interval)
                except Exception:
                    self.redis = RedisWakeup(False, reason="redis subscription failed")
                    self._run_poll_loop()
                    return
                self.check_once(reason="redis" if message else "poll", redis_event=bool(message))
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    def _collect_snapshot(self) -> dict[str, Any]:
        tasks = self.task_store.list_tasks()
        try:
            from clawteam.spawn.registry import list_dead_agents
            dead_agents = list_dead_agents(self.team_name)
        except Exception:
            dead_agents = []
        leader_messages = self.mailbox.peek(self.leader_name)
        actionable_messages = [
            m for m in leader_messages
            if m.from_agent != "scheduler" and not (m.content or "").startswith("Scheduler check:")
        ]
        completed = [t for t in tasks if t.status == TaskStatus.completed]
        blocked = [t for t in tasks if t.status == TaskStatus.blocked]
        in_progress = [t for t in tasks if t.status == TaskStatus.in_progress]
        pending = [t for t in tasks if t.status == TaskStatus.pending]
        return {
            "total": len(tasks),
            "completed": [_task_ref(t) for t in completed],
            "blocked": [_task_ref(t) for t in blocked],
            "inProgress": [_task_ref(t) for t in in_progress],
            "pending": [_task_ref(t) for t in pending],
            "leaderInboxCount": len(actionable_messages),
            "deadAgents": sorted(dead_agents),
        }

    def _signature(self, snapshot: dict[str, Any]) -> str:
        data = {
            "completed": snapshot["completed"],
            "blocked": snapshot["blocked"],
            "leaderInboxCount": snapshot["leaderInboxCount"],
            "deadAgents": snapshot["deadAgents"],
        }
        return json.dumps(data, sort_keys=True, ensure_ascii=False)

    def _render(
        self,
        snapshot: dict[str, Any],
        *,
        changed: bool,
        heartbeat_due: bool,
    ) -> tuple[str, list[str]]:
        completed_by_owner: dict[str, int] = {}
        for task in snapshot["completed"]:
            owner = task.get("owner") or "unassigned"
            completed_by_owner[owner] = completed_by_owner.get(owner, 0) + 1
        completed_text = ", ".join(
            f"{owner} finished {count} task(s)" for owner, count in sorted(completed_by_owner.items())
        ) or "none"
        dead_text = ", ".join(snapshot["deadAgents"]) or "none"
        summary = (
            "Scheduler check:\n"
            f"- Completed: {completed_text}\n"
            f"- Inbox: {self.leader_name} has {snapshot['leaderInboxCount']} unread message(s)\n"
            f"- Blocked: {len(snapshot['blocked'])}\n"
            f"- Dead agents: {dead_text}\n\n"
            "Recommended next action:\n"
            f"Run `clawteam task list {self.team_name}` and "
            f"`clawteam inbox receive {self.team_name} --agent {self.leader_name}`, "
            "then decide next steps."
        )
        evidence = [
            f"trigger: {'state_changed' if changed else 'heartbeat'}",
            f"heartbeatDue: {heartbeat_due}",
            f"tasks: {len(snapshot['completed'])}/{snapshot['total']} completed",
            f"inProgress: {len(snapshot['inProgress'])}",
            f"pending: {len(snapshot['pending'])}",
            f"blocked: {len(snapshot['blocked'])}",
            f"leaderInboxCount: {snapshot['leaderInboxCount']}",
            f"deadAgents: {dead_text}",
        ]
        return summary, evidence

    def _inject(self, summary: str, evidence: list[str]) -> tuple[bool, str]:
        envelope = RuntimeEnvelope(
            source="scheduler",
            target=self.leader_name,
            channel="coordinator",
            priority="medium",
            message_type="scheduler_check",
            summary=summary,
            evidence=evidence,
            recommended_next_action=(
                f"Run `clawteam task list {self.team_name}` and "
                f"`clawteam inbox receive {self.team_name} --agent {self.leader_name}`."
            ),
        )
        try:
            from clawteam.spawn import get_backend
            from clawteam.spawn.registry import get_registry
            registry = get_registry(self.team_name)
            backend_name = (registry.get(self.leader_name) or {}).get("backend", "tmux") or "tmux"
            backend = get_backend(backend_name)
            if hasattr(backend, "inject_runtime_message"):
                ok, status = backend.inject_runtime_message(self.team_name, self.leader_name, envelope)
                if ok:
                    return True, status
        except Exception as exc:
            status = str(exc)
        else:
            status = "runtime injection unsupported or failed"

        try:
            self.mailbox.send(
                from_agent="scheduler",
                to=self.leader_name,
                content=summary,
                msg_type=MessageType.message,
                summary="Scheduler check",
            )
            return True, f"queued in leader inbox after injection failure: {status}"
        except Exception as exc:
            return False, f"runtime injection and inbox fallback failed: {exc}"

    def _state_path(self) -> Path:
        team_dir = ensure_within_root(
            get_data_dir() / "teams",
            validate_identifier(self.team_name, "team name"),
        )
        return team_dir / "leader_watch_state.json"

    def _read_state(self) -> dict[str, Any]:
        path = self._state_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        atomic_write_text(self._state_path(), json.dumps(state, indent=2, ensure_ascii=False))

    def _emit_result(self, result: LeaderWatchResult) -> None:
        if not (self.json_output or self.verbose):
            return
        if self.json_output:
            print(
                json.dumps(
                    {
                        "event": "leader_watch",
                        "team": self.team_name,
                        "leader": self.leader_name,
                        "injected": result.injected,
                        "reason": result.reason,
                        "redisEvent": result.redis_event,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return
        if result.injected:
            print(f"[leader-watch] injected reminder ({result.reason})", flush=True)


def _task_ref(task) -> dict[str, str]:
    return {
        "id": task.id,
        "owner": task.owner,
        "updatedAt": task.updated_at,
        "status": task.status.value,
    }
