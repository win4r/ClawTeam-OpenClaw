from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from io import TextIOBase
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from clawteam.delivery.failure_notifier import notify_task_failure
from clawteam.spawn.cli_env import resolve_clawteam_executable
from clawteam.spawn.registry import unregister_agent
from clawteam.task.terminal_commands import build_terminal_task_update_command
from clawteam.task.transition import (
    DUPLICATE_TERMINAL_CONFLICTING_STATUS,
    DUPLICATE_TERMINAL_SAME_STATUS,
)
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskLockError, TaskStore


DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_AGENT_TIMEOUT = 900
DEFAULT_IDLE_EXIT_TIMEOUT = 600.0
DEFAULT_PROGRESS_STALL_TIMEOUT = 90.0
DEFAULT_PROGRESS_POLL_INTERVAL = 1.0
DEFAULT_POST_EXIT_SETTLE_TIMEOUT = 15.0
DEFAULT_POST_EXIT_POLL_INTERVAL = 1.0
DEFAULT_POST_EXIT_PROGRESS_GRACE = 3.0

COMPLETION_ENVELOPE_VERSION = 1
COMPLETION_SIGNAL_PRIMARY_SOURCE = "runtime_completion_envelope"
COMPLETION_SIGNAL_TEMPORARY_FALLBACK_SOURCE = "transcript_result_block_temporary_compatibility"
_COMPLETION_ENVELOPE_ALLOWED_TERMINAL_STATUS = frozenset({"completed", "failed"})


@dataclass(frozen=True)
class RuntimeCompletionEnvelope:
    version: int
    task_id: str
    execution_id: str
    terminal_status: str
    result_type: str = ""
    result_payload: Any | None = None
    emitted_at: str = ""


@dataclass(frozen=True)
class TerminalIntent:
    task_id: str
    execution_id: str | None
    terminal_status: TaskStatus
    reason: str
    evidence: str
    source: Literal[
        "completion_envelope",
        "transcript_result_block_temporary_compatibility",
        "watchdog_runtime_progress_stall",
        "watchdog_total_timeout",
        "dispatch_failure",
        "agent_exit_nonzero",
        "post_exit_missing_terminal",
        "post_exit_upstream_failure",
    ]
    metadata: dict[str, Any] | None = None
    session_key: str | None = None
    result_type: str = ""
    authoritative: bool = False
    fallback_case_name: str = "worker_runtime_terminal_intent"


@dataclass
class _PipeProgressState:
    stdout_chunks: list[str]
    stderr_chunks: list[str]
    stdout_bytes: int = 0
    stderr_bytes: int = 0


def load_startup_prompt(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _render_setup_runtime_handoff_prompt_block(task: Any) -> list[str]:
    metadata = getattr(task, "metadata", None)
    if not isinstance(metadata, dict):
        return []
    payload = metadata.get("setup_runtime_handoff")
    if not isinstance(payload, dict) or not payload:
        return []

    lines = ["", "## Machine Runtime Handoff"]
    detached_worktree = str(payload.get("detached_worktree") or "").strip()
    detached_head = str(payload.get("detached_head") or "").strip()
    remote_status = str(payload.get("remote_status") or "").strip()
    remote_head = str(payload.get("remote_head") or "").strip()
    venv_path = str(payload.get("venv_path") or "").strip()
    activation_commands = [str(item).strip() for item in (payload.get("activation_commands") or []) if str(item).strip()]
    baseline_commands = [str(item).strip() for item in (payload.get("baseline_commands") or []) if str(item).strip()]
    install_commands = [str(item).strip() for item in (payload.get("install_commands") or []) if str(item).strip()]

    if detached_worktree:
        lines.append(f"- Use detached worktree from setup: `{detached_worktree}`")
    if detached_head:
        lines.append(f"- Detached HEAD proven by setup: `{detached_head}`")
    if remote_status:
        remote_line = f"- Remote status from setup: `{remote_status}`"
        if remote_head:
            remote_line += f" (`{remote_head}`)"
        lines.append(remote_line)
    if venv_path:
        lines.append(f"- Required virtualenv path: `{venv_path}`")
    if activation_commands:
        lines.append("- Activation command(s) proven in setup:")
        lines.extend(f"  - `{item}`" for item in activation_commands)
    if baseline_commands:
        lines.append("- Baseline command(s) proven in setup:")
        lines.extend(f"  - `{item}`" for item in baseline_commands)
    if install_commands:
        lines.append("- Install command(s) observed in setup:")
        lines.extend(f"  - `{item}`" for item in install_commands)
    lines.extend([
        "- This handoff is machine-derived from SETUP_RESULT.",
        "- Reuse this environment before inventing your own validation path.",
        "- If this contract is unusable, report that exact mismatch as the blocker.",
    ])
    return lines


def build_worker_task_prompt(
    *,
    team_name: str,
    agent_name: str,
    leader_name: str,
    task: Any,
    startup_prompt: str = "",
    workspace_dir: str = "",
    workspace_branch: str = "",
    runtime_completion_signal_path: str = "",
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
    lines.extend(_render_setup_runtime_handoff_prompt_block(task))
    clawteam_bin = resolve_clawteam_executable()
    shell_exports = [
        ("CLAWTEAM_AGENT_NAME", agent_name),
        ("CLAWTEAM_AGENT_ID", os.environ.get("CLAWTEAM_AGENT_ID", agent_name)),
        ("CLAWTEAM_AGENT_TYPE", os.environ.get("CLAWTEAM_AGENT_TYPE", "general-purpose")),
        ("CLAWTEAM_TEAM_NAME", team_name),
        ("CLAWTEAM_BIN", clawteam_bin),
        ("CLAWTEAM_DATA_DIR", os.environ.get("CLAWTEAM_DATA_DIR", "")),
    ]
    if getattr(task, "active_execution_id", ""):
        shell_exports.append(("CLAWTEAM_TASK_EXECUTION_ID", task.active_execution_id))
    if runtime_completion_signal_path:
        shell_exports.append(("CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH", runtime_completion_signal_path))
    shell_prefix = " ".join(
        f"{key}={shlex.quote(str(value))}" for key, value in shell_exports if str(value)
    )
    clawteam_cmd = shlex.quote(clawteam_bin)
    bootstrap = (
        f"eval $({shell_prefix} {clawteam_cmd} identity set "
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

    terminal_complete_cmd = build_terminal_task_update_command(
        team_name=team_name,
        task_id=task.id,
        status="completed",
        execution_id=getattr(task, "active_execution_id", ""),
    )
    terminal_fail_cmd = build_terminal_task_update_command(
        team_name=team_name,
        task_id=task.id,
        status="failed",
        execution_id=getattr(task, "active_execution_id", ""),
        failure_kind="complex",
        failure_root_cause="<cause>",
        failure_evidence="<evidence>",
        failure_recommended_next_owner="leader",
        failure_recommended_action="<action>",
    )

    lines.extend([
        "",
        "## Required Runtime Protocol",
        f"- You are running inside the formal ClawTeam worker runtime for {team_name}.",
        f"- First bootstrap the shell identity for every command block: `{bootstrap}`.",
        f"- Your task lock is already claimed as {agent_name}. Do not claim it again unless you explicitly released it.",
        f"- Use `{clawteam_cmd} inbox receive {team_name} --ack` to consume wake/context messages when needed.",
        f"- If blocked, send a concrete blocker to {leader_name} via `{clawteam_cmd} inbox send {team_name} {leader_name} \"<blocker>\"` and update the task to failed with the correct failure metadata.",
        "- The task brief in Description is the current scope authority. Treat Source Request / Scoped Brief / Out of Scope as binding for this run.",
        "- Leader messages may clarify or prioritize within that task brief, but they do not by themselves approve new endpoints, APIs, schemas, pages, tabs, workflows, or deliverables.",
        "- If a leader message appears to expand scope beyond the task brief, stop and ask for a new task or explicit human-approved scope change instead of implementing it silently.",
        "- Workflow routing is owned by the leader/template/state machine. Do not create repair/retry/review tasks or mutate blocked_by/on_fail edges unless the leader explicitly told you to do that.",
        f"- Before terminal completion, write the machine completion envelope to `$CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH` with task_id/execution_id/terminal_status. result_type and result_payload are optional business fields, not runtime authority.",
        f"- Example completion envelope command: `python3 - <<'PY'\nimport json, os\nfrom pathlib import Path\nPath(os.environ['CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH']).write_text(json.dumps({{'version': 1, 'task_id': '{task.id}', 'execution_id': '{getattr(task, 'active_execution_id', '')}', 'terminal_status': 'completed', 'result_type': 'DEV_RESULT', 'result_payload': {{'status': 'completed'}}}}) + '\\n', encoding='utf-8')\nPY`",
        f"- When the task is truly complete, run `{terminal_complete_cmd}`.",
        f"- When you must fail the claimed task, use an execution-scoped terminal writeback like `{terminal_fail_cmd}`.",
        f"- Do not pretend success. Use real validation and report exact files, commands, and results.",
        f"- If more context is needed, read your inbox and inspect the workspace before changing code.",
        "- Use structured result blocks instead of free-form prose.",
        "- Keep summary, evidence, validation, and next action in separate sections.",
        "- Do not mix optional suggestions into required fixes.",
        "- If a section has no content, write `none` instead of omitting the section.",
        "",
        "## Result Block Formats",
        "- SETUP_RESULT must include exactly these headings: status, remote_status, remote_head, detached_worktree, detached_head, install, baseline_validation, known_limitations, next_action.",
        "- SETUP_RESULT remote_status must be confirmed_latest, cached_only, or unreachable.",
        "- For setup tasks, fail closed: do not claim latest main unless `git ls-remote --heads <remote> <branch>` succeeded; if remote probing fails or times out, report cached_only or unreachable explicitly.",
        "- For setup tasks, use the built-in helper when possible: `python3 - <<'PY'` / `from clawteam.workspace.git import probe_remote_head` / `print(probe_remote_head(Path('.'), remote='flyzorro', branch='main'))` so timeout and command-failure classification stays deterministic.",
        "- For setup tasks, if you need a bounded remote probe, do not rely on Linux-only `timeout`; use `python3` / subprocess timeout or the host tool's timeout so the same step works on macOS too.",
        "- For setup tasks, detached worktree evidence must include the path plus actual `git rev-parse HEAD` / `git status --short --branch` output from that detached workspace.",
        "- For setup tasks, baseline validation must be discovered before execution (for example pyproject / README / Makefile / package.json / tests); do not guess a test path and present that as proof.",
        "- DEV_RESULT must include exactly these headings: status, summary, changed_files, validation, known_issues, next_action.",
        "- QA_RESULT must include exactly these headings: status, summary, evidence, validation, risk, next_action.",
        "- QA_RESULT status may be pass, pass_with_risk, fail, or blocked. Use pass_with_risk when the main goal is validated but residual risk or unobserved branch coverage remains.",
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
    cwd: str | None = None,
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
    ])
    if cwd:
        final.extend(["--cwd", cwd])
    final.extend([
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
    worker_instance_id: str | None = None,
) -> bool:
    from clawteam.spawn.registry import current_runtime_generation, get_agent_record

    record = get_agent_record(team_name, agent_name, data_dir)
    if not record:
        return False

    current_instance_id = str(worker_instance_id or os.environ.get("CLAWTEAM_WORKER_INSTANCE_ID") or "").strip()
    recorded_instance_id = str(record.get("worker_instance_id") or "").strip()
    if current_instance_id and recorded_instance_id:
        return current_instance_id != recorded_instance_id

    recorded_pid = int(record.get("pid", 0) or 0)
    observed_parent = parent_pid if parent_pid is not None else os.getppid()
    if recorded_pid <= 0 or observed_parent <= 0 or recorded_pid == observed_parent:
        return False

    recorded_generation = str(record.get("runtime_generation") or "").strip()
    if not recorded_generation:
        return True

    return recorded_generation != current_runtime_generation()


def clear_replaced_worker_unfinished_tasks(
    *,
    team_name: str,
    agent_name: str,
    data_dir: str | None = None,
    parent_pid: int | None = None,
    worker_instance_id: str | None = None,
) -> list[str]:
    if not detect_worker_replacement(
        team_name=team_name,
        agent_name=agent_name,
        data_dir=data_dir,
        parent_pid=parent_pid,
        worker_instance_id=worker_instance_id,
    ):
        return []

    store = TaskStore(team_name)
    cleared = store.clear_unfinished_tasks_for_owner(agent_name)
    return [task.id for task in cleared]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_transcript_path(session_key: str) -> Path:
    return Path.home() / ".openclaw" / "agents" / "main" / "sessions" / f"{session_key}.jsonl"


def _completion_signal_path(session_key: str) -> Path:
    return Path.home() / ".openclaw" / "agents" / "main" / "sessions" / f"{session_key}.completion.json"


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


def _parse_runtime_completion_envelope(payload: dict[str, Any] | None) -> RuntimeCompletionEnvelope | None:
    if not isinstance(payload, dict):
        return None
    try:
        version = int(payload.get("version", COMPLETION_ENVELOPE_VERSION))
    except (TypeError, ValueError):
        return None
    task_id = str(payload.get("task_id") or "").strip()
    execution_id = str(payload.get("execution_id") or "").strip()
    terminal_status = str(payload.get("terminal_status") or "").strip().lower()
    result_type = str(payload.get("result_type") or "").strip()
    result_payload = payload.get("result_payload")
    emitted_at = str(payload.get("emitted_at") or "").strip()
    if version != COMPLETION_ENVELOPE_VERSION:
        return None
    if not task_id or not execution_id or terminal_status not in _COMPLETION_ENVELOPE_ALLOWED_TERMINAL_STATUS:
        return None
    return RuntimeCompletionEnvelope(
        version=version,
        task_id=task_id,
        execution_id=execution_id,
        terminal_status=terminal_status,
        result_type=result_type,
        result_payload=result_payload,
        emitted_at=emitted_at,
    )


def _read_completion_signal(session_key: str) -> RuntimeCompletionEnvelope | None:
    path = _completion_signal_path(session_key)
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _parse_runtime_completion_envelope(payload)


def _extract_text_from_transcript_line(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line

    parts: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            if value:
                parts.append(value)
            return
        if isinstance(value, list):
            for item in value:
                _walk(item)
            return
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str):
                if content:
                    parts.append(content)
            elif isinstance(content, list):
                _walk(content)
            text = value.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
            message = value.get("message")
            if message is not None:
                _walk(message)

    _walk(payload)
    return "\n".join(part for part in parts if part).strip() or line


_RESULT_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str], dict[str, TaskStatus]]] = [
    (
        "DEV_RESULT",
        re.compile(
            r"DEV_RESULT\s+status:\s*(?P<status>completed|blocked)\b(?P<body>.*?)next_action:",
            re.IGNORECASE | re.DOTALL,
        ),
        {"completed": TaskStatus.completed, "blocked": TaskStatus.failed},
    ),
    (
        "QA_RESULT",
        re.compile(
            r"QA_RESULT\s+status:\s*(?P<status>pass_with_risk|pass|fail|blocked)\b(?P<body>.*?)next_action:",
            re.IGNORECASE | re.DOTALL,
        ),
        {"pass": TaskStatus.completed, "pass_with_risk": TaskStatus.completed, "fail": TaskStatus.failed, "blocked": TaskStatus.blocked},
    ),
    (
        "REVIEW_RESULT",
        re.compile(
            r"REVIEW_RESULT\s+decision:\s*(?P<status>approve|return_to_implement)\b(?P<body>.*?)next_action:",
            re.IGNORECASE | re.DOTALL,
        ),
        {"approve": TaskStatus.completed, "return_to_implement": TaskStatus.failed},
    ),
]


def _normalize_result_text(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", value.strip())


def _extract_structured_result_sections(transcript_tail: str, block_name: str) -> dict[str, str] | None:
    normalized = "\n".join(
        part for part in (_extract_text_from_transcript_line(line) for line in transcript_tail.splitlines()) if part
    )
    heading_pattern = re.compile(rf"{re.escape(block_name)}\s+", re.IGNORECASE)
    heading_match = heading_pattern.search(normalized)
    if not heading_match:
        return None
    body = normalized[heading_match.end():]
    section_pattern = re.compile(
        r"(?im)^(status|summary|changed_files|evidence|validation|known_issues|risk|next_action|decision|architecture_review|required_fixes):\s*"
    )
    matches = list(section_pattern.finditer(body))
    if not matches:
        return None
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = str(match.group(1) or "").strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = _normalize_result_text(body[start:end])
        sections[key] = value
    return sections or None


def _infer_terminal_status_from_transcript_tail(transcript_tail: str) -> tuple[TaskStatus, str, str] | None:
    normalized = "\n".join(
        part for part in (_extract_text_from_transcript_line(line) for line in transcript_tail.splitlines()) if part
    )
    for block_name, pattern, status_map in _RESULT_BLOCK_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        raw_status = str(match.group("status") or "").strip().lower()
        inferred = status_map.get(raw_status)
        if inferred is None:
            continue
        return inferred, block_name, raw_status
    return None


def _infer_terminal_status_from_completion_signal(
    signal: RuntimeCompletionEnvelope | None,
    *,
    task_id: str,
    execution_id: str,
) -> tuple[TaskStatus, str, str] | None:
    if not signal:
        return None
    if signal.task_id != task_id:
        return None
    if signal.execution_id != execution_id:
        return None
    terminal_map = {
        "completed": TaskStatus.completed,
        "failed": TaskStatus.failed,
    }
    inferred = terminal_map.get(signal.terminal_status)
    if inferred is None:
        return None
    result_type = signal.result_type or "RUNTIME_COMPLETION_ENVELOPE"
    return inferred, result_type, signal.terminal_status


_UPSTREAM_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"An error occurred while processing your request", re.IGNORECASE),
    re.compile(r"request ID\s+[0-9a-f-]{8,}", re.IGNORECASE),
    re.compile(r"LLM request failed", re.IGNORECASE),
    re.compile(r"network connection error", re.IGNORECASE),
    re.compile(r"upstream request failed", re.IGNORECASE),
    re.compile(r"502\b"),
    re.compile(r"503\b"),
    re.compile(r"504\b"),
)


def _infer_upstream_failure_evidence(*parts: str) -> str:
    snippets: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if not text:
            continue
        normalized = text if len(text) <= 4000 else text[-4000:]
        if any(pattern.search(normalized) for pattern in _UPSTREAM_ERROR_PATTERNS):
            snippets.append(normalized)
    if not snippets:
        return ""
    deduped: list[str] = []
    seen: set[str] = set()
    for snippet in snippets:
        if snippet in seen:
            continue
        seen.add(snippet)
        deduped.append(snippet)
    return "\n---\n".join(deduped)


def _configure_nonblocking_text_pipe(pipe: TextIOBase | None) -> None:
    if pipe is None:
        return
    try:
        os.set_blocking(pipe.fileno(), False)
    except (AttributeError, OSError, ValueError):
        return


def _drain_text_pipe_nonblocking(pipe: TextIOBase | None, chunks: list[str]) -> int:
    if pipe is None:
        return 0
    total = 0
    while True:
        try:
            chunk = pipe.read()
        except BlockingIOError:
            break
        except OSError:
            break
        if chunk in (None, ""):
            break
        chunks.append(chunk)
        total += len(chunk)
    return total


def _collect_runtime_progress(
    proc: subprocess.Popen[str],
    session_key: str,
    pipe_state: _PipeProgressState,
) -> tuple[tuple[int, int], tuple[int, int]]:
    transcript_marker = _transcript_progress_marker(session_key)
    stdout_pipe = getattr(proc, "stdout", None)
    stderr_pipe = getattr(proc, "stderr", None)
    pipe_state.stdout_bytes += _drain_text_pipe_nonblocking(stdout_pipe, pipe_state.stdout_chunks)
    pipe_state.stderr_bytes += _drain_text_pipe_nonblocking(stderr_pipe, pipe_state.stderr_chunks)
    io_marker = (pipe_state.stdout_bytes, pipe_state.stderr_bytes)
    return transcript_marker, io_marker


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
    _configure_nonblocking_text_pipe(getattr(proc, "stdout", None))
    _configure_nonblocking_text_pipe(getattr(proc, "stderr", None))
    pipe_state = _PipeProgressState(stdout_chunks=[], stderr_chunks=[])
    started_at = time.monotonic()
    last_progress_at = started_at
    last_transcript_marker, last_io_marker = _collect_runtime_progress(proc, session_key, pipe_state)

    while True:
        if proc.poll() is not None:
            _collect_runtime_progress(proc, session_key, pipe_state)
            stdout, stderr = proc.communicate()
            if stdout:
                pipe_state.stdout_chunks.append(stdout)
            if stderr:
                pipe_state.stderr_chunks.append(stderr)
            return subprocess.CompletedProcess(
                command,
                proc.returncode or 0,
                "".join(pipe_state.stdout_chunks),
                "".join(pipe_state.stderr_chunks),
            )

        now = time.monotonic()
        transcript_marker, io_marker = _collect_runtime_progress(proc, session_key, pipe_state)
        if transcript_marker != last_transcript_marker or io_marker != last_io_marker:
            last_transcript_marker = transcript_marker
            last_io_marker = io_marker
            last_progress_at = now

        if total_timeout_seconds > 0 and now - started_at > total_timeout_seconds:
            proc.kill()
            _collect_runtime_progress(proc, session_key, pipe_state)
            stdout, stderr = proc.communicate()
            if stdout:
                pipe_state.stdout_chunks.append(stdout)
            if stderr:
                pipe_state.stderr_chunks.append(stderr)
            raise TimeoutError(f"worker agent turn exceeded total timeout of {total_timeout_seconds}s")

        if progress_stall_timeout_seconds > 0 and now - last_progress_at > progress_stall_timeout_seconds:
            proc.kill()
            _collect_runtime_progress(proc, session_key, pipe_state)
            stdout, stderr = proc.communicate()
            if stdout:
                pipe_state.stdout_chunks.append(stdout)
            if stderr:
                pipe_state.stderr_chunks.append(stderr)
            tail = _read_transcript_tail(session_key)
            raise TimeoutError(
                "worker agent turn stalled without runtime progress for "
                f"{progress_stall_timeout_seconds:.0f}s\n"
                f"transcript_marker: {transcript_marker}\n"
                f"io_marker: {io_marker}\n"
                f"stdout: {''.join(pipe_state.stdout_chunks).strip()}\n"
                f"stderr: {''.join(pipe_state.stderr_chunks).strip()}\n"
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


def _team_is_terminal(team_name: str) -> bool:
    store = TaskStore(team_name)
    tasks = store.list_tasks()
    if not tasks:
        return False
    terminal_statuses = {TaskStatus.completed, TaskStatus.failed}
    return all(task.status in terminal_statuses for task in tasks)


def _cleanup_worker_runtime(team_name: str, agent_name: str) -> dict[str, Any]:
    data_dir = os.environ.get("CLAWTEAM_DATA_DIR", "")
    session_key = os.environ.get("OPENCLAW_SESSION_KEY", "") or f"clawteam-{team_name}-{agent_name}"
    return unregister_agent(team_name, agent_name, data_dir, session_key=session_key)


def _build_failure_terminal_intent(
    *,
    task_id: str,
    execution_id: str | None,
    reason: str,
    evidence: str,
    source: Literal[
        "watchdog_runtime_progress_stall",
        "watchdog_total_timeout",
        "dispatch_failure",
        "agent_exit_nonzero",
        "post_exit_missing_terminal",
        "post_exit_upstream_failure",
    ],
    session_key: str | None = None,
    stall_phase: str | None = None,
) -> TerminalIntent:
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
    return TerminalIntent(
        task_id=task_id,
        execution_id=execution_id,
        terminal_status=TaskStatus.failed,
        reason=reason,
        evidence=evidence,
        source=source,
        metadata=failure_metadata,
        session_key=session_key,
        fallback_case_name="worker_runtime_failed_closed",
    )


def apply_terminal_intent(
    *,
    team_name: str,
    agent_name: str,
    intent: TerminalIntent,
) -> dict[str, Any]:
    store = TaskStore(team_name)
    decision, task, apply_result = store.apply_runtime_terminal_writeback(
        intent.task_id,
        status=intent.terminal_status,
        caller=agent_name,
        execution_id=intent.execution_id,
        metadata=dict(intent.metadata or {}),
        fallback_case_name=intent.fallback_case_name,
    )
    current_task = apply_result.task if apply_result is not None else task
    if decision and not decision.accepted:
        if decision.rejection_reason == DUPLICATE_TERMINAL_SAME_STATUS:
            return {
                "status": "already_terminal",
                "taskId": intent.task_id,
                "reason": intent.reason,
                "evidence": intent.evidence,
                "rejectionReason": decision.rejection_reason,
                "terminalStatus": task.status.value if task is not None else "",
                "intentSource": intent.source,
            }
        if decision.rejection_reason == DUPLICATE_TERMINAL_CONFLICTING_STATUS:
            return {
                "status": "duplicate_terminal",
                "taskId": intent.task_id,
                "reason": intent.reason,
                "evidence": intent.evidence,
                "rejectionReason": decision.rejection_reason,
                "terminalStatus": task.status.value if task is not None else "",
                "intentSource": intent.source,
            }

    if intent.terminal_status == TaskStatus.failed:
        failure_notice = None
        if current_task is not None:
            failure_notice = notify_task_failure(team_name, current_task, agent_name)
        return {
            "status": "failed_closed",
            "taskId": intent.task_id,
            "failureNotice": failure_notice,
            "reason": intent.reason,
            "evidence": intent.evidence,
            "intentSource": intent.source,
        }

    return {
        "status": "terminal_applied",
        "taskId": intent.task_id,
        "terminalStatus": intent.terminal_status.value,
        "reason": intent.reason,
        "evidence": intent.evidence,
        "intentSource": intent.source,
        "taskStatus": current_task.status.value if current_task is not None else intent.terminal_status.value,
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

    try:
        claim_result = store.claim_execution(task.id, caller=agent_name)
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

    if not claim_result.accepted:
        return {
            "status": "contended",
            "messages": message_count,
            "acked": acked_count,
            "taskId": task.id,
            "rejectionReason": claim_result.rejection_reason,
        }

    leader_name = TeamManager.get_leader_name(team_name) or "leader"
    workspace_dir = os.environ.get("CLAWTEAM_WORKSPACE_DIR", cwd or "")
    workspace_branch = os.environ.get("CLAWTEAM_WORKSPACE_BRANCH", "")
    session_key = f"clawteam-{team_name}-{agent_name}"
    runtime_completion_signal_path = str(_completion_signal_path(session_key))
    prompt = build_worker_task_prompt(
        team_name=team_name,
        agent_name=agent_name,
        leader_name=leader_name,
        task=claim_result.task,
        startup_prompt=startup_prompt,
        workspace_dir=workspace_dir,
        workspace_branch=workspace_branch,
        runtime_completion_signal_path=runtime_completion_signal_path,
    )
    command = build_openclaw_agent_command(
        base_command=base_command or ["openclaw"],
        session_key=session_key,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        cwd=workspace_dir or cwd,
    )
    env = os.environ.copy()
    claimed = claim_result.task
    env["CLAWTEAM_TASK_ID"] = claimed.id
    env["CLAWTEAM_TASK_EXECUTION_ID"] = claimed.active_execution_id
    env["CLAWTEAM_TASK_EXECUTION_SEQ"] = str(claimed.execution_seq)
    env["CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH"] = runtime_completion_signal_path
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
        reason = "worker runtime dispatch failed"
        stall_phase = "dispatch"
        if isinstance(exc, TimeoutError) and "stalled without runtime progress" in str(exc):
            reason = "worker agent turn stalled without runtime progress"
            stall_phase = "dispatch_runtime_progress_stall"
        elif isinstance(exc, TimeoutError) and "exceeded total timeout" in str(exc):
            reason = "worker agent turn exceeded total timeout"
            stall_phase = "dispatch_total_timeout"
        failure_source = "dispatch_failure"
        if stall_phase == "dispatch_runtime_progress_stall":
            failure_source = "watchdog_runtime_progress_stall"
        elif stall_phase == "dispatch_total_timeout":
            failure_source = "watchdog_total_timeout"
        failed = apply_terminal_intent(
            team_name=team_name,
            agent_name=agent_name,
            intent=_build_failure_terminal_intent(
                task_id=claimed.id,
                execution_id=claimed.active_execution_id,
                reason=reason,
                evidence=repr(exc),
                source=failure_source,
                session_key=session_key,
                stall_phase=stall_phase,
            ),
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
        failed = apply_terminal_intent(
            team_name=team_name,
            agent_name=agent_name,
            intent=_build_failure_terminal_intent(
                task_id=claimed.id,
                execution_id=claimed.active_execution_id,
                reason="worker agent turn failed",
                evidence=evidence,
                source="agent_exit_nonzero",
                session_key=session_key,
                stall_phase="agent_exit_nonzero",
            ),
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
            signal_payload = _read_completion_signal(session_key)
            inferred_terminal = _infer_terminal_status_from_completion_signal(
                signal_payload,
                task_id=claimed.id,
                execution_id=claimed.active_execution_id,
            )
            recovery_source = COMPLETION_SIGNAL_PRIMARY_SOURCE
            fallback_mode = False
            if inferred_terminal is None:
                # Temporary compatibility fallback only: transcript parsing is evidence/debugging-oriented and
                # must not become the formal completion authority.
                transcript_tail = _read_transcript_tail(session_key)
                inferred_terminal = _infer_terminal_status_from_transcript_tail(transcript_tail)
                recovery_source = COMPLETION_SIGNAL_TEMPORARY_FALLBACK_SOURCE
                fallback_mode = inferred_terminal is not None
            else:
                transcript_tail = _read_transcript_tail(session_key)

            if inferred_terminal is not None:
                inferred_status, result_type, terminal_status_value = inferred_terminal
                recovery_metadata = {
                    "runtime_terminal_recovery": recovery_source,
                    "runtime_terminal_recovery_result_type": result_type,
                    "runtime_terminal_recovery_terminal_status": terminal_status_value,
                    "runtime_terminal_recovery_session_key": session_key,
                    "runtime_terminal_recovery_at": _now_iso(),
                }
                if signal_payload is not None and recovery_source == COMPLETION_SIGNAL_PRIMARY_SOURCE:
                    recovery_metadata["runtime_terminal_recovery_signal_version"] = str(signal_payload.version)
                if fallback_mode:
                    recovery_metadata["runtime_terminal_recovery_compatibility_fallback"] = "true"
                structured_sections = _extract_structured_result_sections(transcript_tail, result_type)
                if structured_sections:
                    normalized_result_type = result_type.lower()
                    recovery_metadata[f"{normalized_result_type}_sections"] = structured_sections
                    if result_type == "QA_RESULT":
                        recovery_metadata["qa_result"] = structured_sections
                        recovery_metadata["qa_result_status"] = structured_sections.get("status", terminal_status_value)
                        recovery_metadata["qa_result_risk"] = structured_sections.get("risk", "")
                        recovery_metadata["qa_result_summary"] = structured_sections.get("summary", "")
                recovered = apply_terminal_intent(
                    team_name=team_name,
                    agent_name=agent_name,
                    intent=TerminalIntent(
                        task_id=claimed.id,
                        execution_id=claimed.active_execution_id,
                        terminal_status=inferred_status,
                        reason=f"runtime terminal recovered from {recovery_source}",
                        evidence=transcript_tail,
                        source=(
                            "completion_envelope"
                            if recovery_source == COMPLETION_SIGNAL_PRIMARY_SOURCE
                            else "transcript_result_block_temporary_compatibility"
                        ),
                        metadata=recovery_metadata,
                        session_key=session_key,
                        result_type=result_type,
                        authoritative=recovery_source == COMPLETION_SIGNAL_PRIMARY_SOURCE,
                        fallback_case_name="worker_runtime_transcript_terminal_recovery",
                    ),
                )
                if recovered["status"] in {"terminal_applied", "already_terminal"}:
                    return {
                        "status": "recovered_terminal",
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
                        "recoveredStatus": inferred_status.value,
                        "recoveredFrom": result_type,
                        "recoverySource": recovery_source,
                        "taskStatus": recovered.get("terminalStatus") or recovered.get("taskStatus") or inferred_status.value,
                    }

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
            upstream_failure_evidence = _infer_upstream_failure_evidence(
                result.stderr,
                result.stdout,
                transcript_tail,
            )
            failure_reason = "worker agent turn stalled without terminal task update"
            stall_phase = "post_exit_without_terminal_update"
            if upstream_failure_evidence:
                failure_reason = "worker agent turn failed before terminal task update"
                stall_phase = "post_exit_upstream_failure_without_terminal_update"
                evidence_parts.append(f"upstream_failure_evidence:\n{upstream_failure_evidence}")
            failed = apply_terminal_intent(
                team_name=team_name,
                agent_name=agent_name,
                intent=_build_failure_terminal_intent(
                    task_id=claimed.id,
                    execution_id=claimed.active_execution_id,
                    reason=failure_reason,
                    evidence="\n".join(evidence_parts),
                    source=(
                        "post_exit_upstream_failure"
                        if upstream_failure_evidence
                        else "post_exit_missing_terminal"
                    ),
                    session_key=session_key,
                    stall_phase=stall_phase,
                ),
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
    idle_exit_timeout = float(os.environ.get("CLAWTEAM_WORKER_IDLE_EXIT_TIMEOUT", DEFAULT_IDLE_EXIT_TIMEOUT))
    idle_started_at: float | None = None
    idle_statuses = {"idle", "waiting_for_wake"}
    while True:
        if _team_is_terminal(team_name):
            cleanup = _cleanup_worker_runtime(team_name, agent_name)
            history.append({
                "status": "team_terminal",
                "team": team_name,
                "agent": agent_name,
                "cleanup": cleanup,
            })
            return history
        result = run_worker_iteration(
            team_name=team_name,
            agent_name=agent_name,
            startup_prompt=startup_prompt,
            base_command=base_command,
            timeout_seconds=timeout_seconds,
            cwd=cwd,
        )
        history.append(result)
        if result.get("status") in idle_statuses:
            if idle_started_at is None:
                idle_started_at = time.monotonic()
            elif idle_exit_timeout > 0 and (time.monotonic() - idle_started_at) >= idle_exit_timeout:
                cleanup = _cleanup_worker_runtime(team_name, agent_name)
                history.append({
                    "status": "idle_exit",
                    "team": team_name,
                    "agent": agent_name,
                    "idleSeconds": round(time.monotonic() - idle_started_at, 3),
                    "cleanup": cleanup,
                })
                return history
        else:
            idle_started_at = None
        if once:
            return history
        time.sleep(max(poll_interval, 0.2))
