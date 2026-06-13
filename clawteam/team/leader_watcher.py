"""Leader watcher that periodically injects coordination reminders."""

from __future__ import annotations

import json
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


class _SimpleNudgeTracker:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def should_nudge(self, agent_name: str, text: str) -> bool:
        key = (agent_name, text.strip()[-240:])
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class _SimpleIdleNudgeTracker:
    def __init__(self, scan_interval_s: float = 30.0, repeat_interval_s: float = 60.0) -> None:
        self.scan_interval_s = scan_interval_s
        self.repeat_interval_s = repeat_interval_s
        self._last_scan_at = 0.0
        self._last_nudge_at: dict[str, float] = {}
        self._idle_agents: set[str] = set()

    def should_scan(self) -> bool:
        return time.time() - self._last_scan_at >= self.scan_interval_s

    def mark_scan(self) -> None:
        self._last_scan_at = time.time()

    def mark_idle(self, agent_name: str) -> None:
        self._idle_agents.add(agent_name)

    def reset_pane(self, agent_name: str) -> None:
        self._idle_agents.discard(agent_name)

    def should_nudge(self, agent_name: str) -> bool:
        if agent_name not in self._idle_agents:
            return False
        return time.time() - self._last_nudge_at.get(agent_name, 0.0) >= self.repeat_interval_s

    def record_nudge(self, agent_name: str) -> None:
        self._last_nudge_at[agent_name] = time.time()


def _make_nudge_tracker():
    try:
        from clawteam.harness.auto_nudge import NudgeTracker

        return NudgeTracker()
    except Exception:
        return _SimpleNudgeTracker()


def _make_idle_tracker():
    try:
        from clawteam.harness.idle_nudge import IdleNudgeTracker

        return IdleNudgeTracker()
    except Exception:
        return _SimpleIdleNudgeTracker()


def _is_permission_seeking(text: str) -> bool:
    try:
        from clawteam.harness.auto_nudge import is_permission_seeking

        return is_permission_seeking(text)
    except Exception:
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in (
                "do you want to proceed",
                "proceed?",
                "continue?",
                "yes/no",
                "permission",
            )
        )


def _pane_looks_idle(text: str) -> bool:
    try:
        from clawteam.harness.idle_nudge import pane_looks_idle

        return pane_looks_idle(text)
    except Exception:
        stripped = text.rstrip()
        return stripped.endswith(("$", "$ ", "%", "% ", ">", "> ")) or stripped.endswith("$")


def _read_heartbeat(team_dir: Path, agent_name: str):
    try:
        from clawteam.team.heartbeat import read_heartbeat

        return read_heartbeat(team_dir, agent_name)
    except Exception:
        return None


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
        self._nudge_tracker = _make_nudge_tracker()
        self._idle_tracker = _make_idle_tracker()
        self._last_stale_leader_nudge_at = 0.0
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
        reflex_injected = self._run_reflexes(snapshot)
        state = self._read_state()
        signature = self._signature(snapshot)
        now = time.time()
        last_signature = str(state.get("lastSignature") or "")
        last_heartbeat = float(state.get("lastHeartbeatAt") or 0.0)

        changed = signature != last_signature
        heartbeat_due = now - last_heartbeat >= self.heartbeat_interval
        if not changed and not heartbeat_due:
            result = LeaderWatchResult(
                reflex_injected,
                "reflex" if reflex_injected else "no_change",
                redis_event=redis_event,
            )
            self._emit_result(result)
            return result

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


    def _run_reflexes(self, snapshot: dict[str, Any]) -> bool:
        """Run v2 reflex integrations without breaking scheduler checks."""
        injected = False
        for reflex in (
            self._auto_nudge_workers,
            self._idle_nudge_workers,
            lambda: self._stale_leader_check(snapshot),
        ):
            try:
                injected = reflex() or injected
            except Exception:
                continue
        return injected

    def _auto_nudge_workers(self) -> bool:
        injected = False
        for worker_name, meta in self._worker_registry_items():
            target = str(meta.get("tmux_target") or "")
            if not target:
                continue
            text = self._capture_pane_text(target)
            if not _is_permission_seeking(text):
                continue
            if not self._nudge_tracker.should_nudge(worker_name, text):
                continue
            envelope = RuntimeEnvelope(
                source="leader_watcher",
                target=worker_name,
                channel="reflex",
                priority="high",
                message_type="auto_nudge",
                summary="yes, proceed",
                evidence=["trigger: permission_seeking_worker", f"pane: {target}"],
                recommended_next_action="yes, proceed",
                dedupe_key=f"auto-nudge:{self.team_name}:{worker_name}",
            )
            ok, _status = self._inject_runtime(worker_name, meta, envelope)
            injected = ok or injected
        return injected

    def _idle_nudge_workers(self) -> bool:
        if not self._idle_tracker.should_scan():
            return False
        self._idle_tracker.mark_scan()
        injected = False
        action = (
            "read your inbox/mailbox, continue your assigned task now, and if blocked send "
            "the leader a concrete status update"
        )
        for worker_name, meta in self._worker_registry_items():
            target = str(meta.get("tmux_target") or "")
            if not target:
                continue
            text = self._capture_pane_text(target)
            if _pane_looks_idle(text):
                self._idle_tracker.mark_idle(worker_name)
            else:
                self._idle_tracker.reset_pane(worker_name)
                continue
            if not self._idle_tracker.should_nudge(worker_name):
                continue
            envelope = RuntimeEnvelope(
                source="leader_watcher",
                target=worker_name,
                channel="reflex",
                priority="high",
                message_type="idle_nudge",
                summary=f"Worker {worker_name} appears idle at a shell prompt; {action}.",
                evidence=["trigger: idle_worker_shell_prompt", f"pane: {target}"],
                recommended_next_action=action,
                dedupe_key=f"idle-nudge:{self.team_name}:{worker_name}",
            )
            ok, _status = self._inject_runtime(worker_name, meta, envelope)
            if ok:
                self._idle_tracker.record_nudge(worker_name)
            injected = ok or injected
        return injected

    def _stale_leader_check(self, snapshot: dict[str, Any] | None = None) -> bool:
        if snapshot is None:
            snapshot = self._collect_snapshot()
        if not (snapshot.get("pending") or snapshot.get("inProgress") or snapshot.get("blocked")):
            return False
        heartbeat = _read_heartbeat(self._team_dir(), self.leader_name)
        if heartbeat is None:
            return False
        try:
            age = (
                datetime.now(timezone.utc)
                - heartbeat.last_turn_at.astimezone(timezone.utc)
            ).total_seconds()
        except Exception:
            return False
        if age <= 180:
            return False
        now = time.time()
        if now - self._last_stale_leader_nudge_at < 60:
            return False

        meta = self._agent_meta(self.leader_name)
        target = str(meta.get("tmux_target") or "")
        if target:
            text = self._capture_pane_text(target)
            if text and not _pane_looks_idle(text):
                return False
        action = "check messages and redistribute pending tasks"
        envelope = RuntimeEnvelope(
            source="leader_watcher",
            target=self.leader_name,
            channel="reflex",
            priority="high",
            message_type="stale_leader_nudge",
            summary=f"Leader heartbeat is stale ({age:.0f}s); {action}.",
            evidence=[
                "trigger: stale_leader",
                f"last_turn_age_seconds: {age:.0f}",
                f"pending: {len(snapshot.get('pending') or [])}",
                f"inProgress: {len(snapshot.get('inProgress') or [])}",
                f"blocked: {len(snapshot.get('blocked') or [])}",
            ],
            recommended_next_action=action,
            dedupe_key=f"stale-leader:{self.team_name}:{self.leader_name}",
        )
        ok, _status = self._inject_runtime(self.leader_name, meta, envelope)
        if ok:
            self._last_stale_leader_nudge_at = now
        return ok

    def _worker_registry_items(self) -> list[tuple[str, dict[str, Any]]]:
        try:
            from clawteam.spawn.registry import get_registry

            registry = get_registry(self.team_name)
        except Exception:
            return []
        return [
            (name, meta)
            for name, meta in registry.items()
            if name != self.leader_name and isinstance(meta, dict)
        ]

    def _agent_meta(self, agent_name: str) -> dict[str, Any]:
        try:
            from clawteam.spawn.registry import get_registry

            meta = get_registry(self.team_name).get(agent_name) or {}
            return meta if isinstance(meta, dict) else {}
        except Exception:
            return {}

    def _capture_pane_text(self, target: str) -> str:
        try:
            from clawteam.spawn.tmux_backend import capture_pane_text

            return capture_pane_text(target)
        except Exception:
            return ""

    def _inject_runtime(
        self,
        agent_name: str,
        meta: dict[str, Any],
        envelope: RuntimeEnvelope,
    ) -> tuple[bool, str]:
        try:
            from clawteam.spawn import get_backend

            backend_name = str(meta.get("backend") or "tmux")
            backend = get_backend(backend_name)
            if hasattr(backend, "inject_runtime_message"):
                return backend.inject_runtime_message(self.team_name, agent_name, envelope)
        except Exception as exc:
            return False, str(exc)
        return False, "runtime injection unsupported or failed"

    def _team_dir(self) -> Path:
        return ensure_within_root(
            get_data_dir() / "teams",
            validate_identifier(self.team_name, "team name"),
        )

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
