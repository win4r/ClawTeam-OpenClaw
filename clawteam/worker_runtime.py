from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskLockError, TaskStore


DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_AGENT_TIMEOUT = 900


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
    lines.extend([
        "",
        "## Required Runtime Protocol",
        f"- You are running inside the formal ClawTeam worker runtime for {team_name}.",
        f"- First bootstrap the shell identity for every command block: `{bootstrap}`.",
        f"- Your task lock is already claimed as {agent_name}. Do not claim it again unless you explicitly released it.",
        f"- Use `clawteam inbox receive {team_name} --ack` to consume wake/context messages when needed.",
        f"- If blocked, send a concrete blocker to {leader_name} via `clawteam inbox send {team_name} {leader_name} \"<blocker>\"` and update the task to failed with the correct failure metadata.",
        f"- When the task is truly complete, run `clawteam task update {team_name} {task.id} --status completed`.",
        f"- Do not pretend success. Use real validation and report exact files, commands, and results.",
        f"- If more context is needed, read your inbox and inspect the workspace before changing code.",
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

    task = pending[0]
    message_count = len(visible_messages)
    if message_count == 0:
        return {
            "status": "waiting_for_wake",
            "messages": 0,
            "acked": 0,
            "taskId": task.id,
        }

    matched_wakes = mailbox.receive_matching(
        agent_name,
        lambda msg: msg.key == f"task-wake:{task.id}" or msg.last_task == task.id,
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

    try:
        claimed = store.update(task.id, status=TaskStatus.in_progress, caller=agent_name)
    except TaskLockError:
        return {
            "status": "contended",
            "messages": message_count,
            "acked": acked_count,
            "taskId": task.id,
        }

    if claimed is None:
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
        task=claimed,
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
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    return {
        "status": "dispatched",
        "messages": message_count,
        "acked": acked_count,
        "taskId": claimed.id,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
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
