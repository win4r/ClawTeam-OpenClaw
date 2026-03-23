from __future__ import annotations

import os
import shlex
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawteam.delivery.failure_notifier import notify_task_failure
from clawteam.task.transition import (
    ClaimExecutionEvent,
    TerminalWritebackEvent,
    plan_claim_execution,
    plan_terminal_writeback,
)
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskLockError, TaskStore


DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_AGENT_TIMEOUT = 900
DEFAULT_PROGRESS_STALL_TIMEOUT = 90.0
DEFAULT_PROGRESS_POLL_INTERVAL = 1.0
DEFAULT_POST_EXIT_SETTLE_TIMEOUT = 15.0
DEFAULT_POST_EXIT_POLL_INTERVAL = 1.0
DEFAULT_POST_EXIT_PROGRESS_GRACE = 3.0


def load_startup_prompt(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_worker_task_prompt(
    *,
    team_name: str,
    agent_name: str,
    leader_name: str,
    task: Any,
    startup_prompt: str = "",
    workspace_dir: str = "",
    workspace_branch: str = "",
) -> str:
    lines: list[str] = []
    if startup_prompt.strip():
        lines.extend([startup_prompt.strip(), ""])

    lines.extend([
        "## Current ClawTeam Task",
        f"- Team: {team_name}",
        f"- Worker: {agent_name}",
        f"- Leader: {leader_name}",
        f"- Task ID: {task.id}",
        f"- Subject: {task.subject}",
    ])
    if workspace_dir:
        lines.extend([
            f"- Workspace: {workspace_dir}",
            f"- Branch: {workspace_branch}",
        ])
    if task.description:
        lines.extend(["", "## Description", task.description])
    bootstrap = (
        "eval $(clawteam identity set "
        f"--agent-name {shlex.quote(agent_name)} "
        f"--agent-id {shlex.quote(os.environ.get('CLAWTEAM_AGENT_ID', agent_name))} "
        f"--agent-type {shlex.quote(os.environ.get('CLAWTEAM_AGENT_TYPE', 'general-purpose'))} "
        f"--team {shlex.quote(team_name)} "
        f"--data-dir {shlex.quote(os.environ.get('CLAWTEAM_DATA_DIR', ''))} --shell)"
    )
    if getattr(task, "active_execution_id", ""):
        lines.extend([
            f"- Active Execution ID: {task.active_execution_id}",
        ])

    lines.extend([
        "",
        "## Required Runtime Protocol",
        f"- You are running inside the formal ClawTeam worker runtime for {team_name}.",
        f"- First bootstrap the shell identity for every command block: `{bootstrap}`.",
        f"- Your task lock is already claimed as {agent_name}. Do not claim it again unless you explicitly released it.",
        f"- Use `clawteam inbox receive {team_name} --ack` to consume wake/context messages when needed.",
        f"- If blocked, send a concrete blocker to {leader_name} via `clawteam inbox send {team_name} {leader_name} \"<blocker>\"` and update the task to failed with the correct failure metadata.",
        "- Workflow routing is owned by the leader/template/state machine. Do not create repair/retry/review tasks or mutate blocked_by/on_fail edges unless the leader explicitly told you to do that.",
        f"- When the task is truly complete, run `clawteam task update {team_name} {task.id} --status completed`.",
        f"- Do not pretend success. Use real validation and report exact files, commands, and results.",
        f"- If more context is needed, read your inbox and inspect the workspace before changing code.",
        "- Use structured result blocks instead of free-form prose.",
        "- Keep summary, evidence, validation, and next action in separate sections.",
        "- Do not mix optional suggestions into required fixes.",
        "- If a section has no content, write `none` instead of omitting the section.",
        "",
        "## Result Block Formats",
        "- DEV_RESULT must include exactly these headings: status, summary, changed_files, validation, known_issues, next_action.",
        "- QA_RESULT must include exactly these headings: status, summary, evidence, validation, risk, next_action.",
        "- REVIEW_RESULT must include exactly these headings: decision, summary, architecture_review, required_fixes, evidence, validation, next_action.",
        "- Keep required_fixes limited to must-fix items; put nice-to-have ideas outside that section or write `none`.",
    ])
    return "\n".join(lines)


def build_openclaw_agent_command(
    *,
    base_command: list[str],
    session_key: str,
    prompt: str,
    timeout_seconds: int,
) -> list[str]:
    if not base_command:
        raise ValueError("agent command is required")
    if Path(base_command[0]).name != "openclaw":
        raise ValueError("formal worker runtime currently supports openclaw only")

    final = list(base_command)
    if "agent" not in final and "tui" not in final:
        final.insert(1, "agent")
    if "tui" in final:
        raise ValueError("formal worker runtime requires headless `openclaw agent`, not `tui`")
    final.extend([
        "--session-id",
        session_key,
        "--message",
        prompt,
        "--timeout",
        str(timeout_seconds),
    ])
    return final


def detect_worker_replacement(
    *,
    team_name: str,
    agent_name: str,
    data_dir: str | None = None,
    parent_pid: int | None = None,
) -> bool:
    from clawteam.spawn.registry import current_runtime_generation, get_agent_record

    record = get_agent_record(team_name, agent_name, data_dir)
    if not record:
        return False

    recorded_generation = str(record.get("runtime_generation") or "").strip()
    if recorded_generation and recorded_generation != current_runtime_generation():
        return True

    recorded_pid = int(record.get("pid", 0) or 0)
    observed_parent = parent_pid if parent_pid is not None else os.getppid()
    return recorded_pid > 0 and observed_parent > 0 and recorded_pid != observed_parent


def clear_replaced_worker_unfinished_tasks(
    *,
    team_name: str,
    agent_name: str,
    data_dir: str | None = None,
    parent_pid: int | None = None,
) -> list[str]:
    if not detect_worker_replacement(
        team_name=team_name,
        agent_name=agent_name,
        data_dir=data_dir,
        parent_pid=parent_pid,
    ):
        return []

    store = TaskStore(team_name)
    cleared = store.clear_unfinished_tasks_for_owner(agent_name)
    return [task.id for task in cleared]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_transcript_path(session_key: str) -> Path:
    return Path.home() / ".openclaw" / "agents" / "main" / "sessions" / f"{session_key}.jsonl"


def _read_transcript_tail(session_key: str, max_lines: int = 20) -> str:
    path = _session_transcript_path(session_key)
    if not path.exists():
        return f"transcript missing: {path}"
    try:
        tail: deque[str] = deque(maxlen=max_lines)
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line:
                    tail.append(line)
        if not tail:
            return f"transcript empty: {path}"
        return "\n".join(tail)
    except OSError as exc:
        return f"transcript unreadable: {path} ({exc!r})"


def _transcript_progress_marker(session_key: str) -> tuple[int, int]:
    path = _session_transcript_path(session_key)
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (0, 0)


def _run_agent_with_progress_watchdog(
    *,
    command: list[str],
    cwd: str | None,
    env: dict[str, str],
    session_key: str,
    total_timeout_seconds: int,
    progress_stall_timeout_seconds: float,
    progress_poll_interval_seconds: float,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started_at = time.monotonic()
    last_progress_at = started_at
    last_marker = _transcript_progress_marker(session_key)

    while True:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            return subprocess.CompletedProcess(command, proc.returncode or 0, stdout or "", stderr or "")

        now = time.monotonic()
        marker = _transcript_progress_marker(session_key)
        if marker != last_marker:
            last_marker = marker
            last_progress_at = now

        if total_timeout_seconds > 0 and now - started_at > total_timeout_seconds:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise TimeoutError(f"worker agent turn exceeded total timeout of {total_timeout_seconds}s")

        if progress_stall_timeout_seconds > 0 and now - last_progress_at > progress_stall_timeout_seconds:
            proc.kill()
            stdout, stderr = proc.communicate()
            tail = _read_transcript_tail(session_key)
            raise TimeoutError(
                "worker agent turn stalled without transcript progress for "
                f"{progress_stall_timeout_seconds:.0f}s\n"
                f"stdout: {(stdout or '').strip()}\n"
                f"stderr: {(stderr or '').strip()}\n"
                f"transcript_tail:\n{tail}"
            )

        time.sleep(max(progress_poll_interval_seconds, 0.05))


def _wait_for_post_exit_settle(
    *,
    team_name: str,
    task_id: str,
    agent_name: str,
    session_key: str,
    settle_timeout_seconds: float,
    poll_interval_seconds: float,
    progress_grace_seconds: float,
) -> tuple[Any | None, bool]:
    store = TaskStore(team_name)
    started_at = time.monotonic()
    last_progress_at = started_at
    last_marker = _transcript_progress_marker(session_key)

    while True:
        task = store.get(task_id)
        if task is None:
            return None, False
        if task.status != TaskStatus.in_progress or task.locked_by != agent_name:
            return task, True

        now = time.monotonic()
        marker = _transcript_progress_marker(session_key)
        if marker != last_marker:
            last_marker = marker
            last_progress_at = now

        if settle_timeout_seconds > 0 and now - started_at >= settle_timeout_seconds:
            return task, False

        if progress_grace_seconds > 0 and now - last_progress_at >= progress_grace_seconds:
            return task, False

        time.sleep(max(poll_interval_seconds, 0.05))


def _fail_claimed_task(
    *,
    team_name: str,
    agent_name: str,
    task_id: str,
    reason: str,
    evidence: str,
    execution_id: str | None = None,
    session_key: str | None = None,
    stall_phase: str | None = None,
) -> dict[str, Any]:
    store = TaskStore(team_name)
    failure_metadata = {
        "failure_kind": "complex",
        "failure_root_cause": reason,
        "failure_evidence": evidence,
        "failure_recommended_next_owner": "leader",
        "failure_recommended_action": "Inspect runtime failure and decide whether to retry or reroute.",
        "watchdog_decision_at": _now_iso(),
    }
    if session_key:
        failure_metadata["session_key"] = session_key
    if stall_phase:
        failure_metadata["stall_phase"] = stall_phase
    existing = store.get(task_id)
    task = None
    apply_result = None
    if existing is not None:
        decision = plan_terminal_writeback(
            existing=existing,
            event=TerminalWritebackEvent(
                caller=agent_name,
                status=TaskStatus.failed,
                execution_id=execution_id,
            ),
        )
        if decision and not decision.accepted:
            store.record_transition_rejection(
                task_id,
                case_name=decision.case_name,
                caller=agent_name,
                execution_id=execution_id,
                rejection_reason=decision.rejection_reason,
            )
        else:
            applied_case = "worker_runtime_failed_closed"
            if decision and decision.accepted:
                applied_case = decision.case_name
            apply_result = store.accept_terminal_writeback(
                task_id,
                status=TaskStatus.failed,
                caller=agent_name,
                execution_id=execution_id,
                metadata=failure_metadata,
                case_name=applied_case,
            )
    failure_notice = None
    task = apply_result.task if apply_result is not None else None
    if task is not None:
        failure_notice = notify_task_failure(team_name, task, agent_name)
    return {
        "status": "failed_closed",
        "taskId": task_id,
        "failureNotice": failure_notice,
        "reason": reason,
        "evidence": evidence,
    }



def run_worker_iteration(
    *,
    team_name: str,
    agent_name: str,
    startup_prompt: str = "",
    base_command: list[str] | None = None,
    timeout_seconds: int = DEFAULT_AGENT_TIMEOUT,
    cwd: str | None = None,
) -> dict[str, Any]:
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team_name)
    visible_messages = mailbox.peek(agent_name)

    store = TaskStore(team_name)
    pending = store.list_tasks(status=TaskStatus.pending, owner=agent_name)
    if not pending:
        drained = mailbox.receive(agent_name, limit=50, acknowledge=True)
        return {"status": "idle", "messages": len(drained)}

    pending_by_id = {task.id: task for task in pending}
    first_wake = None
    ordered_messages = sorted(visible_messages, key=lambda msg: (msg.timestamp or "", msg.request_id or ""))
    for msg in ordered_messages:
        candidate_id = None
        if msg.key and msg.key.startswith("task-wake:"):
            candidate_id = msg.key.split(":", 1)[1]
        elif msg.last_task:
            candidate_id = msg.last_task
        if candidate_id in pending_by_id:
            first_wake = (candidate_id, pending_by_id[candidate_id])
            break

    message_count = len(visible_messages)
    if first_wake is None:
        return {
            "status": "waiting_for_wake",
            "messages": message_count,
            "acked": 0,
            "taskId": pending[0].id,
        }

    selected_task_id, task = first_wake
    matched_wakes = mailbox.receive_matching(
        agent_name,
        lambda msg: (
            msg.key == f"task-wake:{selected_task_id}" or msg.last_task == selected_task_id
        ),
        limit=50,
        acknowledge=True,
    )
    acked_count = len(matched_wakes)

    if acked_count == 0:
        return {
            "status": "waiting_for_wake",
            "messages": message_count,
            "acked": 0,
            "taskId": task.id,
        }

    claim_decision = plan_claim_execution(
        existing=task,
        event=ClaimExecutionEvent(caller=agent_name),
    )
    if not claim_decision.accepted:
        store.record_transition_rejection(
            task.id,
            case_name=claim_decision.case_name,
            caller=agent_name,
            rejection_reason=claim_decision.rejection_reason,
        )
        return {
            "status": "contended",
            "messages": message_count,
            "acked": acked_count,
            "taskId": task.id,
            "rejectionReason": claim_decision.rejection_reason,
        }

    try:
        claim_result = store.apply_transition_decision(
            task.id,
            decision={"case_name": claim_decision.case_name, "accepted": True},
            status=TaskStatus.in_progress,
            caller=agent_name,
        )
    except TaskLockError:
        return {
            "status": "contended",
            "messages": message_count,
            "acked": acked_count,
            "taskId": task.id,
        }

    if claim_result is None:
        return {
            "status": "missing",
            "messages": message_count,
            "acked": acked_count,
            "taskId": task.id,
        }

    leader_name = TeamManager.get_leader_name(team_name) or "leader"
    workspace_dir = os.environ.get("CLAWTEAM_WORKSPACE_DIR", cwd or "")
    workspace_branch = os.environ.get("CLAWTEAM_WORKSPACE_BRANCH", "")
    prompt = build_worker_task_prompt(
        team_name=team_name,
        agent_name=agent_name,
        leader_name=leader_name,
        task=claim_result.task,
        startup_prompt=startup_prompt,
        workspace_dir=workspace_dir,
        workspace_branch=workspace_branch,
    )
    session_key = f"clawteam-{team_name}-{agent_name}"
    command = build_openclaw_agent_command(
        base_command=base_command or ["openclaw"],
        session_key=session_key,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    env = os.environ.copy()
    claimed = claim_result.task
    env["CLAWTEAM_TASK_ID"] = claimed.id
    env["CLAWTEAM_TASK_EXECUTION_ID"] = claimed.active_execution_id
    env["CLAWTEAM_TASK_EXECUTION_SEQ"] = str(claimed.execution_seq)
    progress_stall_timeout_seconds = float(
        env.get("CLAWTEAM_WORKER_PROGRESS_STALL_TIMEOUT", DEFAULT_PROGRESS_STALL_TIMEOUT)
    )
    progress_poll_interval_seconds = float(
        env.get("CLAWTEAM_WORKER_PROGRESS_POLL_INTERVAL", DEFAULT_PROGRESS_POLL_INTERVAL)
    )
    try:
        result = _run_agent_with_progress_watchdog(
            command=command,
            cwd=cwd,
            env=env,
            session_key=session_key,
            total_timeout_seconds=timeout_seconds,
            progress_stall_timeout_seconds=progress_stall_timeout_seconds,
            progress_poll_interval_seconds=progress_poll_interval_seconds,
        )
    except Exception as exc:
        failed = _fail_claimed_task(
            team_name=team_name,
            agent_name=agent_name,
            task_id=claimed.id,
            reason="worker runtime dispatch failed",
            evidence=repr(exc),
            execution_id=claimed.active_execution_id,
            session_key=session_key,
            stall_phase="dispatch",
        )
        failed.update({
            "messages": message_count,
            "acked": acked_count,
            "command": command,
            "error": repr(exc),
        })
        return failed

    if result.returncode != 0:
        evidence_parts = []
        if result.stderr:
            evidence_parts.append(f"stderr: {result.stderr.strip()}")
        if result.stdout:
            evidence_parts.append(f"stdout: {result.stdout.strip()}")
        evidence = "\n".join(part for part in evidence_parts if part) or f"returncode={result.returncode}"
        failed = _fail_claimed_task(
            team_name=team_name,
            agent_name=agent_name,
            task_id=claimed.id,
            reason="worker agent turn failed",
            evidence=evidence,
            execution_id=claimed.active_execution_id,
            session_key=session_key,
            stall_phase="agent_exit_nonzero",
        )
        failed.update({
            "messages": message_count,
            "acked": acked_count,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command,
        })
        return failed

    refreshed = store.get(claimed.id)
    if (
        refreshed is not None
        and refreshed.status == TaskStatus.in_progress
        and refreshed.locked_by == agent_name
    ):
        settle_timeout_seconds = float(
            env.get("CLAWTEAM_WORKER_POST_EXIT_SETTLE_TIMEOUT", DEFAULT_POST_EXIT_SETTLE_TIMEOUT)
        )
        settle_poll_interval_seconds = float(
            env.get("CLAWTEAM_WORKER_POST_EXIT_POLL_INTERVAL", DEFAULT_POST_EXIT_POLL_INTERVAL)
        )
        settle_progress_grace_seconds = float(
            env.get("CLAWTEAM_WORKER_POST_EXIT_PROGRESS_GRACE", DEFAULT_POST_EXIT_PROGRESS_GRACE)
        )
        refreshed, settled = _wait_for_post_exit_settle(
            team_name=team_name,
            task_id=claimed.id,
            agent_name=agent_name,
            session_key=session_key,
            settle_timeout_seconds=settle_timeout_seconds,
            poll_interval_seconds=settle_poll_interval_seconds,
            progress_grace_seconds=settle_progress_grace_seconds,
        )

        if (
            refreshed is not None
            and refreshed.status == TaskStatus.in_progress
            and refreshed.locked_by == agent_name
        ):
            transcript_tail = _read_transcript_tail(session_key)
            evidence_parts = [
                "openclaw agent returned success but task remained in_progress and locked to the same worker",
                f"session_key={session_key}",
                f"post_exit_settled={settled}",
                f"post_exit_settle_timeout_seconds={settle_timeout_seconds}",
                f"post_exit_progress_grace_seconds={settle_progress_grace_seconds}",
            ]
            if result.stderr:
                evidence_parts.append(f"stderr: {result.stderr.strip()}")
            if result.stdout:
                evidence_parts.append(f"stdout: {result.stdout.strip()}")
            evidence_parts.append(f"transcript_tail:\n{transcript_tail}")
            failed = _fail_claimed_task(
                team_name=team_name,
                agent_name=agent_name,
                task_id=claimed.id,
                reason="worker agent turn stalled without terminal task update",
                evidence="\n".join(evidence_parts),
                execution_id=claimed.active_execution_id,
                session_key=session_key,
                stall_phase="post_exit_without_terminal_update",
            )
            failed.update({
                "messages": message_count,
                "acked": acked_count,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
                "sessionKey": session_key,
            })
            return failed

    return {
        "status": "dispatched",
        "messages": message_count,
        "acked": acked_count,
        "taskId": claimed.id,
        "executionId": claimed.active_execution_id,
        "executionSeq": claimed.execution_seq,
        "claimCase": claim_result.case_name,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
        "sessionKey": session_key,
    }


def worker_loop(
    *,
    team_name: str,
    agent_name: str,
    startup_prompt: str = "",
    base_command: list[str] | None = None,
    timeout_seconds: int = DEFAULT_AGENT_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    cwd: str | None = None,
    once: bool = False,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    while True:
        result = run_worker_iteration(
            team_name=team_name,
            agent_name=agent_name,
            startup_prompt=startup_prompt,
            base_command=base_command,
            timeout_seconds=timeout_seconds,
            cwd=cwd,
        )
        history.append(result)
        if once:
            return history
        time.sleep(max(poll_interval, 0.2))
