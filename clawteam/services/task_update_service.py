"""Task update application services: use-case orchestration and follow-up execution."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any, Callable


FAILURE_REPAIR_PACKET_KEYS = (
    "failure_target_files",
    "failure_repro_steps",
    "failure_expected_result",
    "failure_candidate_patch",
)

from clawteam.services.task_service import wake_tasks_to_pending


def _build_dependency_completion_message(task, target) -> str:
    message = (
        f"Task {target.id} is unblocked because dependency {task.id} completed. "
        "Start now and report only real blockers."
    )
    qa_result = task.metadata.get("qa_result") if isinstance(task.metadata, dict) else None
    if isinstance(qa_result, dict) and qa_result:
        status = str(qa_result.get("status") or "").strip()
        summary = str(qa_result.get("summary") or "").strip()
        risk = str(qa_result.get("risk") or "").strip()
        structured_lines = ["", "Dependency QA context:"]
        if status:
            structured_lines.append(f"- status: {status}")
        if summary:
            structured_lines.append(f"- summary: {summary}")
        if risk:
            structured_lines.append(f"- risk: {risk}")
        message += "\n" + "\n".join(structured_lines)
    return message


from clawteam.templates import (
    ALLOWED_EXECUTION_SHAPES,
    ScopeTaskValidationError,
    find_scope_audit_warnings,
    inject_resolved_scope_context,
    validate_scope_task_completion,
    read_feature_scope_metadata,
)
from clawteam.templates.launch import _BACKEND_TARGET_KINDS, _FRONTEND_TARGET_KINDS, _infer_layers_from_paths
from clawteam.task.transition import (
    ReopenTaskEvent,
    TaskTransitionPlan,
    TaskTransitionRequest,
    TaskTransitionValidationError,
    TerminalWritebackEvent,
    build_failure_metadata,
    merge_transition_metadata,
    plan_reopen_task,
    plan_task_transition,
    plan_task_transition_followups,
    plan_terminal_writeback,
    plan_watchdog_failed_completion_recovery,
)
from clawteam.team.models import TaskItem, TaskStatus
from clawteam.team.tasks import TaskPatch, TaskStore, TransitionApplyResult


TaskUpdateValidationError = TaskTransitionValidationError
TaskUpdatePlan = TaskTransitionPlan
merge_update_metadata = merge_transition_metadata
plan_task_update_followups = plan_task_transition_followups


POST_SCOPE_MATERIALIZATION_MODE = "post-scope"
DEFERRED_MATERIALIZATION_CASE = "deferred_post_scope_materialization"
DEFERRED_MATERIALIZATION_HOOK = "post_scope_materialization"
DEFERRED_MATERIALIZATION_AWAITING_HOOK = "awaiting_explicit_post_scope_hook"
DEFERRED_MATERIALIZATION_MATERIALIZED = "materialized_post_scope"
DEFERRED_MATERIALIZATION_REASON = (
    "Deferred topology materialization is not implemented; refusing legacy downstream auto-release."
)

_FIVE_STEP_SCOPE_SUBJECT = "Scope the task into a minimal deliverable"
_FIVE_STEP_SETUP_SUBJECT = "Prepare repo, branch, env, and runnable baseline"
_FIVE_STEP_IMPL_A_SUBJECT = "Implement assigned change slice A with real validation"
_FIVE_STEP_IMPL_B_SUBJECT = "Implement assigned change slice B with real validation"
_FIVE_STEP_QA_A_SUBJECT = "Run scoped QA pass A on the real change"
_FIVE_STEP_QA_B_SUBJECT = "Run scoped QA pass B on the real change"
_FIVE_STEP_REVIEW_SUBJECT = "Review code quality, maintainability, and release readiness"
_FIVE_STEP_DELIVER_SUBJECT = "Prepare final delivery package and human decision summary"


def _build_failure_repair_packet(task: TaskItem) -> str | None:
    if not isinstance(task.metadata, dict):
        return None

    lines: list[str] = []
    target_files = task.metadata.get("failure_target_files")
    if isinstance(target_files, list):
        filtered = [str(item).strip() for item in target_files if str(item).strip()]
        if filtered:
            lines.append("Target files:")
            lines.extend(f"- {item}" for item in filtered)

    repro_steps = (task.metadata.get("failure_repro_steps") or "").strip()
    if repro_steps:
        lines.append(f"Repro steps: {repro_steps}")

    expected_result = (task.metadata.get("failure_expected_result") or "").strip()
    if expected_result:
        lines.append(f"Expected result: {expected_result}")

    candidate_patch = (task.metadata.get("failure_candidate_patch") or "").strip()
    if candidate_patch:
        lines.append(f"Candidate patch: {candidate_patch}")

    if not lines:
        return None
    return "\n".join(["Repair packet:", *lines])


def _extract_structured_sections(description: str) -> dict[str, str]:
    text = (description or "").strip()
    if not text:
        return {}
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_ ]*):\s*(.*)$", line.strip())
        if match:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = match.group(1).strip().lower().replace(" ", "_")
            initial = match.group(2).strip()
            buf = [initial] if initial else []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _looks_like_sha(value: str) -> bool:
    candidate = (value or "").strip()
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", candidate))


def _looks_like_command_evidence_block(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return any(line.startswith("-") and ("->" in line or ":" in line) for line in lines)


def _normalize_bullet_block(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    normalized: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("-"):
            continue
        entry = line[1:].strip()
        if entry:
            normalized.append(entry)
    return normalized


def _has_meaningful_bullets(value: str) -> bool:
    entries = _normalize_bullet_block(value)
    if not entries:
        return False
    blacklist = {
        "none",
        "n/a",
        "na",
        "no",
        "no change",
        "no changes",
        "unchanged",
        "no-op",
        "noop",
    }
    for entry in entries:
        normalized = entry.strip().lower()
        if normalized in blacklist:
            continue
        if normalized.startswith("none"):
            continue
        return True
    return False


def _normalize_command_evidence_block(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    normalized: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("-"):
            continue
        normalized.append(line[1:].strip())
    return normalized


def _infer_runtime_handoff_from_setup_sections(sections: dict[str, str]) -> dict[str, Any]:
    detached_worktree = sections.get("detached_worktree", "").strip()
    detached_head = sections.get("detached_head", "").strip()
    remote_status = sections.get("remote_status", "").strip().lower()
    remote_head = sections.get("remote_head", "").strip()
    install_commands = _normalize_command_evidence_block(sections.get("install", ""))
    baseline_commands = _normalize_command_evidence_block(sections.get("baseline_validation", ""))

    venv_path = ""
    for entry in [*install_commands, *baseline_commands]:
        match = re.search(r"(?:^|[\s'\"])\.venv(?:/|['\"]|\s|$)", entry)
        if match:
            venv_path = ".venv"
            break

    activation_commands: list[str] = []
    if venv_path:
        activation_commands.append(f"source {venv_path}/bin/activate")
        if detached_worktree and detached_worktree.lower() != "none":
            activation_commands.append(
                f"cd {detached_worktree} && source {venv_path}/bin/activate"
            )

    detached_worktree_name = ""
    if detached_worktree and detached_worktree.lower() != "none":
        try:
            detached_worktree_name = PurePath(detached_worktree).name
        except Exception:
            detached_worktree_name = ""

    return {
        "version": 1,
        "source_task_stage": "setup",
        "remote_status": remote_status,
        "remote_head": remote_head,
        "detached_worktree": detached_worktree,
        "detached_worktree_name": detached_worktree_name,
        "detached_head": detached_head,
        "install_commands": install_commands,
        "baseline_commands": baseline_commands,
        "venv_path": venv_path,
        "activation_commands": activation_commands,
    }


def _parse_required_structured_result(
    *,
    existing: TaskItem,
    request: TaskUpdateRequest,
    message_type: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    metadata = existing.metadata or {}
    description = (request.description if request.description is not None else existing.description or "").strip()
    if not description:
        raise TaskTransitionValidationError(
            f"{message_type.lower()} completion requires {message_type} via --description"
        )
    lines = description.splitlines()
    header = (lines[0].strip() if lines else "")
    if header != message_type:
        raise TaskTransitionValidationError(
            f"{message_type.lower()} completion requires {message_type} header via --description"
        )

    sections = _extract_structured_sections(description)
    required_sections = [str(s).strip().lower() for s in (metadata.get("required_sections") or []) if str(s).strip()]
    missing = [section for section in required_sections if section not in sections or not sections[section].strip()]
    if missing:
        raise TaskTransitionValidationError(
            f"{message_type.lower()} completion missing required {message_type} sections: " + ", ".join(missing)
        )
    return description, sections, metadata


def _git_changed_paths_since_head(*, repo_path: Path, base_head: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_head}..HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _validate_setup_completion(existing: TaskItem, request: TaskUpdateRequest) -> None:
    if request.status != TaskStatus.completed:
        return
    metadata = existing.metadata or {}
    if metadata.get("message_type") != "SETUP_RESULT":
        return

    description, sections, _ = _parse_required_structured_result(
        existing=existing,
        request=request,
        message_type="SETUP_RESULT",
    )

    remote_status = sections.get("remote_status", "").strip().lower()
    if remote_status not in {"confirmed_latest", "cached_only", "unreachable"}:
        raise TaskTransitionValidationError(
            "setup completion requires remote_status to be one of: confirmed_latest, cached_only, unreachable"
        )

    remote_head = sections.get("remote_head", "").strip()
    if remote_head.lower() == "none":
        if remote_status == "confirmed_latest":
            raise TaskTransitionValidationError("setup completion cannot use remote_head none when remote_status=confirmed_latest")
    elif not _looks_like_sha(remote_head):
        raise TaskTransitionValidationError("setup completion requires remote_head to look like a git sha or `none`")

    detached_worktree = sections.get("detached_worktree", "").strip()
    if detached_worktree.lower() == "none":
        raise TaskTransitionValidationError("setup completion requires detached_worktree evidence; `none` is not allowed")

    detached_head = sections.get("detached_head", "").strip()
    if detached_head.lower() == "none" or not _looks_like_sha(detached_head):
        raise TaskTransitionValidationError("setup completion requires detached_head to look like a git sha")

    install_block = sections.get("install", "")
    if not _looks_like_command_evidence_block(install_block):
        raise TaskTransitionValidationError("setup completion requires install evidence in `- <command> -> <result>` form")

    baseline_block = sections.get("baseline_validation", "")
    if not _looks_like_command_evidence_block(baseline_block):
        raise TaskTransitionValidationError(
            "setup completion requires baseline_validation evidence in `- <command> -> <result>` form"
        )

    if remote_status == "confirmed_latest" and "ls-remote" not in description:
        raise TaskTransitionValidationError(
            "setup completion with remote_status=confirmed_latest requires explicit `git ls-remote` evidence"
        )

    if remote_status == "confirmed_latest" and remote_head.lower() != "none" and detached_head != remote_head:
        raise TaskTransitionValidationError(
            "setup completion with remote_status=confirmed_latest requires detached_head to equal confirmed remote_head"
        )


def _validate_dev_completion(existing: TaskItem, request: TaskUpdateRequest) -> None:
    if request.status != TaskStatus.completed:
        return
    metadata = existing.metadata or {}
    if metadata.get("message_type") != "DEV_RESULT":
        return

    _, sections, _ = _parse_required_structured_result(
        existing=existing,
        request=request,
        message_type="DEV_RESULT",
    )

    changed_files = [line[1:].strip() for line in sections.get("changed_files", "").splitlines() if line.strip().startswith("-")]
    if not changed_files:
        raise TaskTransitionValidationError("DEV_RESULT completion requires changed_files evidence as a non-empty bullet list")
    placeholder_values = {"none", "n/a", "na", "unchanged", "no changes"}
    if any(item.lower() in placeholder_values for item in changed_files):
        raise TaskTransitionValidationError("DEV_RESULT completion requires real changed_files evidence; placeholders are not allowed")

    validation_block = sections.get("validation", "")
    if not _looks_like_command_evidence_block(validation_block):
        raise TaskTransitionValidationError("DEV_RESULT completion requires validation evidence in `- <command> -> <result>` form")

    runtime_handoff = metadata.get("setup_runtime_handoff") if isinstance(metadata, dict) else None
    detached_worktree = str((runtime_handoff or {}).get("detached_worktree") or "").strip()
    detached_head = str((runtime_handoff or {}).get("detached_head") or "").strip()
    if not detached_worktree or not detached_head:
        raise TaskTransitionValidationError("DEV_RESULT completion requires setup_runtime_handoff with detached_worktree and detached_head")
    if not _looks_like_sha(detached_head):
        raise TaskTransitionValidationError("DEV_RESULT completion requires setup_runtime_handoff.detached_head to look like a git sha")

    repo_path = Path(detached_worktree)
    if not repo_path.exists():
        raise TaskTransitionValidationError(
            f"DEV_RESULT completion requires detached_worktree to exist for validation: {detached_worktree}"
        )
    try:
        changed_since_base = _git_changed_paths_since_head(repo_path=repo_path, base_head=detached_head)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise TaskTransitionValidationError(
            f"DEV_RESULT completion requires git diff evidence from detached_worktree: {exc}"
        ) from exc

    declared_changed_files = {Path(item).as_posix() for item in changed_files}
    substantive_matches = sorted(path for path in changed_since_base if path in declared_changed_files)
    if not substantive_matches:
        raise TaskTransitionValidationError(
            "DEV_RESULT completion requires at least one declared changed_file to differ from setup detached_head in detached_worktree"
        )


def _validate_qa_completion(existing: TaskItem, request: TaskUpdateRequest) -> None:
    if request.status != TaskStatus.completed:
        return
    metadata = existing.metadata or {}
    if metadata.get("message_type") != "QA_RESULT":
        return

    _, sections, _ = _parse_required_structured_result(
        existing=existing,
        request=request,
        message_type="QA_RESULT",
    )
    status = str(sections.get("status") or "").strip().lower()
    if status not in {"pass", "pass_with_risk"}:
        raise TaskTransitionValidationError("QA_RESULT completion requires status pass or pass_with_risk")
    if not _has_meaningful_bullets(sections.get("evidence", "")):
        raise TaskTransitionValidationError("QA_RESULT completion requires non-placeholder evidence bullets")
    if not _has_meaningful_bullets(sections.get("validation", "")):
        raise TaskTransitionValidationError("QA_RESULT completion requires non-placeholder validation bullets")


def _validate_review_completion(existing: TaskItem, request: TaskUpdateRequest, *, all_tasks: list[TaskItem]) -> None:
    if request.status != TaskStatus.completed:
        return
    metadata = existing.metadata or {}
    if metadata.get("message_type") != "REVIEW_RESULT":
        return

    _, sections, _ = _parse_required_structured_result(
        existing=existing,
        request=request,
        message_type="REVIEW_RESULT",
    )
    decision = str(sections.get("decision") or "").strip().lower()
    if decision != "approve":
        raise TaskTransitionValidationError("REVIEW_RESULT completion requires decision approve")
    if not _has_meaningful_bullets(sections.get("evidence", "")):
        raise TaskTransitionValidationError("REVIEW_RESULT completion requires non-placeholder evidence bullets")
    if not _has_meaningful_bullets(sections.get("validation", "")):
        raise TaskTransitionValidationError("REVIEW_RESULT completion requires non-placeholder validation bullets")

    task_by_id = {task.id: task for task in all_tasks}
    qa_dependencies = [task_by_id[task_id] for task_id in existing.blocked_by if task_id in task_by_id]
    if not qa_dependencies:
        qa_dependencies = [
            task for task in all_tasks
            if existing.id in getattr(task, "blocks", []) and str((task.metadata or {}).get("template_stage") or "").strip().lower() == "qa"
        ]
    if not qa_dependencies:
        raise TaskTransitionValidationError("REVIEW_RESULT completion requires completed QA dependencies with persisted QA_RESULT metadata")
    for dependency in qa_dependencies:
        dep_metadata = dependency.metadata if isinstance(dependency.metadata, dict) else {}
        qa_result = dep_metadata.get("qa_result") if isinstance(dep_metadata.get("qa_result"), dict) else {}
        qa_status = str(qa_result.get("status") or dep_metadata.get("qa_result_status") or "").strip().lower()
        if dependency.status != TaskStatus.completed or qa_status not in {"pass", "pass_with_risk"}:
            raise TaskTransitionValidationError("REVIEW_RESULT completion requires completed QA dependencies with persisted QA_RESULT metadata")


def validate_completion(existing: TaskItem, request: TaskUpdateRequest, *, all_tasks: list[TaskItem]) -> None:
    metadata = existing.metadata or {}
    message_type = str(metadata.get("message_type") or "").strip().upper()
    if message_type == "SETUP_RESULT":
        _validate_setup_completion(existing, request)
        return
    if message_type == "DEV_RESULT":
        _validate_dev_completion(existing, request)
        return
    if message_type == "QA_RESULT":
        _validate_qa_completion(existing, request)
        return
    if message_type == "REVIEW_RESULT":
        _validate_review_completion(existing, request, all_tasks=all_tasks)
        return


def plan_task_update(
    *,
    existing: TaskItem,
    status: TaskStatus | None,
    all_tasks: list[TaskItem],
    failure_metadata: dict[str, str] | None,
    add_on_fail_list: list[str] | None,
) -> TaskUpdatePlan:
    """Backward-compatible wrapper around the task transition planner."""
    transition_request = TaskTransitionRequest(
        status=status,
        add_on_fail=add_on_fail_list,
        failure_kind=(failure_metadata or {}).get("failure_kind"),
        failure_note=(failure_metadata or {}).get("failure_note"),
        failure_root_cause=(failure_metadata or {}).get("failure_root_cause"),
        failure_evidence=(failure_metadata or {}).get("failure_evidence"),
        failure_recommended_next_owner=(failure_metadata or {}).get("failure_recommended_next_owner"),
        failure_recommended_action=(failure_metadata or {}).get("failure_recommended_action"),
    )
    return plan_task_transition(existing=existing, request=transition_request, all_tasks=all_tasks)


@dataclass(frozen=True)
class TaskUpdateEffects:
    wake: dict[str, Any] | None
    auto_releases: list[dict[str, Any]]
    failure_notice: dict[str, Any] | None
    triage_release: dict[str, Any] | None = None
    deferred_materialization: dict[str, Any] | None = None


@dataclass(frozen=True)
class FailureRepairPacket:
    target_files: list[str] | None = None
    repro_steps: str | None = None
    expected_result: str | None = None
    candidate_patch: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if self.target_files:
            metadata["failure_target_files"] = list(self.target_files)
        if self.repro_steps is not None:
            metadata["failure_repro_steps"] = self.repro_steps
        if self.expected_result is not None:
            metadata["failure_expected_result"] = self.expected_result
        if self.candidate_patch is not None:
            metadata["failure_candidate_patch"] = self.candidate_patch
        return metadata


@dataclass(frozen=True)
class TaskUpdateRequest:
    status: TaskStatus | None
    owner: str | None
    subject: str | None
    description: str | None
    add_blocks: list[str] | None
    add_blocked_by: list[str] | None
    add_on_fail: list[str] | None
    failure_kind: str | None
    failure_note: str | None
    failure_root_cause: str | None
    failure_evidence: str | None
    failure_recommended_next_owner: str | None
    failure_recommended_action: str | None
    qa_result_status: str | None = None
    qa_risk_note: str | None = None
    triage_resolution_owner: str | None = None
    triage_resolution_action: str | None = None
    triage_resolution_note: str | None = None
    failure_repair_packet: FailureRepairPacket | None = None
    execution_id: str | None = None
    wake_owner: bool = False
    message: str = ""
    force: bool = False


@dataclass(frozen=True)
class TaskUpdateResult:
    task: TaskItem
    plan: TaskUpdatePlan
    effects: TaskUpdateEffects
    transition_case: str | None = None
    apply_result: TransitionApplyResult | None = None

    def __post_init__(self) -> None:
        if self.transition_case is None and self.apply_result is not None:
            object.__setattr__(self, "transition_case", self.apply_result.case_name)


@dataclass(frozen=True)
class TaskUpdateContext:
    store: TaskStore
    team: str
    runtime: Any
    release_notifier: Callable[[str, TaskItem, str, str], dict[str, Any] | None]
    failure_notifier: Callable[[str, TaskItem, str], dict[str, Any] | None]
    repo: str | None = None

    @property
    def release_team(self) -> str:
        """Backward-compatible alias for older call sites."""
        return self.team

    @property
    def release_repo(self) -> str | None:
        """Backward-compatible alias for older call sites."""
        return self.repo


def _scope_payload(task: TaskItem) -> dict[str, Any] | None:
    payload = task.metadata.get("resolved_scope")
    return payload if isinstance(payload, dict) else None


def _setup_runtime_handoff_payload(task: TaskItem) -> dict[str, Any] | None:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    existing = metadata.get("runtime_handoff")
    if isinstance(existing, dict):
        return existing
    if metadata.get("message_type") != "SETUP_RESULT":
        return None
    description = (task.description or "").strip()
    if not description.startswith("SETUP_RESULT"):
        return None
    sections = _extract_structured_sections(description)
    if not sections:
        return None
    return _infer_runtime_handoff_from_setup_sections(sections)


def _render_runtime_handoff_context(payload: dict[str, Any]) -> str:
    detached_worktree = str(payload.get("detached_worktree") or "").strip()
    detached_head = str(payload.get("detached_head") or "").strip()
    remote_status = str(payload.get("remote_status") or "").strip()
    remote_head = str(payload.get("remote_head") or "").strip()
    venv_path = str(payload.get("venv_path") or "").strip()
    activation_commands = [str(item).strip() for item in (payload.get("activation_commands") or []) if str(item).strip()]
    baseline_commands = [str(item).strip() for item in (payload.get("baseline_commands") or []) if str(item).strip()]
    install_commands = [str(item).strip() for item in (payload.get("install_commands") or []) if str(item).strip()]

    lines = ["## Setup Runtime Handoff"]
    if detached_worktree:
        lines.append(f"- Detached worktree: `{detached_worktree}`")
    if detached_head:
        lines.append(f"- Detached HEAD: `{detached_head}`")
    if remote_status:
        remote_line = f"- Remote status: `{remote_status}`"
        if remote_head:
            remote_line += f" (`{remote_head}`)"
        lines.append(remote_line)
    if venv_path:
        lines.append(f"- Expected virtualenv: `{venv_path}`")
    if activation_commands:
        lines.append("- Activation commands:")
        lines.extend(f"  - `{item}`" for item in activation_commands)
    if baseline_commands:
        lines.append("- Baseline commands proven in setup:")
        lines.extend(f"  - `{item}`" for item in baseline_commands)
    if install_commands:
        lines.append("- Install commands observed in setup:")
        lines.extend(f"  - `{item}`" for item in install_commands)
    lines.append("- Treat this handoff as runtime contract, not optional advice.")
    return "\n".join(lines)


def _propagate_resolved_scope_to_targets(
    *,
    store: TaskStore,
    target_ids: list[str],
    scope_payload: dict[str, Any],
    scope_warnings: list[dict[str, Any]] | None = None,
    runtime_handoff: dict[str, Any] | None = None,
    feature_scope: dict[str, Any] | None = None,
) -> None:
    for target_id in target_ids:
        target = store.get(target_id)
        if target is None:
            continue
        patched_metadata = dict(getattr(target, "metadata", {}) or {})
        patched_description = getattr(target, "description", "") or ""
        if scope_payload:
            patched_metadata["resolved_scope"] = scope_payload
            if scope_warnings is not None:
                patched_metadata["scope_audit_warnings"] = scope_warnings
            if feature_scope is not None:
                patched_metadata["feature_scope"] = feature_scope
            patched_description = inject_resolved_scope_context(
                description=patched_description,
                normalized=scope_payload,
                scope_audit_warnings=scope_warnings,
            )
        if runtime_handoff is not None:
            patched_metadata["setup_runtime_handoff"] = runtime_handoff
        if runtime_handoff is not None and "## Setup Runtime Handoff" not in patched_description:
            patched_description = (patched_description.rstrip() + "\n\n" + _render_runtime_handoff_context(runtime_handoff)).strip()
        store.update(
            target_id,
            description=patched_description,
            metadata=patched_metadata,
        )


def _build_failure_reopen_message(failed_task: TaskItem, target: TaskItem) -> str:
    repair_packet = _build_failure_repair_packet(failed_task)
    parts = [
        f"Task {target.id} is reopened because task {failed_task.id} failed and routed work back to you. Start now and report only real blockers.",
    ]
    if repair_packet:
        parts.append(repair_packet)
    return "\n".join(parts)


def _build_triage_followup(task: TaskItem, ctx: TaskUpdateContext) -> tuple[TaskItem, str, bool] | tuple[None, None, bool]:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    if metadata.get("triage_followup") == "true":
        return None, None, False

    is_complex_failure = task.status == TaskStatus.failed and metadata.get("failure_kind") == "complex"
    is_blocked = task.status == TaskStatus.blocked
    if not is_complex_failure and not is_blocked:
        return None, None, False

    owner_key = "failure_recommended_next_owner" if is_complex_failure else "blocked_recommended_next_owner"
    action_key = "failure_recommended_action" if is_complex_failure else "blocked_recommended_action"
    root_key = "failure_root_cause" if is_complex_failure else "blocked_root_cause"
    evidence_key = "failure_evidence" if is_complex_failure else "blocked_evidence"
    note_key = "failure_note" if is_complex_failure else "blocked_note"

    from clawteam.team.manager import TeamManager

    next_owner = str(metadata.get(owner_key) or "").strip()
    next_action = str(metadata.get(action_key) or "").strip()
    if not next_owner or not next_action:
        return None, None, False
    if TeamManager.get_member(ctx.team, next_owner) is None:
        fallback_leader = TeamManager.get_leader_name(ctx.team) or "leader"
        next_owner = fallback_leader

    existing_followup_id = str(metadata.get("triage_followup_task_id") or "").strip()
    if existing_followup_id:
        existing_followup = ctx.store.get(existing_followup_id)
        if existing_followup is not None:
            return existing_followup, next_owner, False

    root_cause = str(metadata.get(root_key) or "").strip() or "Unspecified"
    evidence = str(metadata.get(evidence_key) or "").strip() or "No evidence provided."
    note = str(metadata.get(note_key) or "").strip()
    repair_packet = _build_failure_repair_packet(task)
    kind_label = "complex failure" if is_complex_failure else "blocked task"
    triage = ctx.store.create(
        subject=f"Triage {kind_label}: {task.subject}",
        owner=next_owner,
        description="\n".join(
            line
            for line in [
                f"Source task: {task.subject} ({task.id})",
                f"Current status: {task.status.value}",
                f"Recommended action: {next_action}",
                f"Root cause: {root_cause}",
                f"Evidence: {evidence}",
                f"Note: {note}" if note else "",
                repair_packet or "",
                "Goal: decide the correct reroute/recovery path and then reopen or release the right owner.",
            ]
            if line
        ),
        metadata={
            "triage_followup": "true",
            "triage_source_task_id": task.id,
            "triage_source_status": task.status.value,
            "triage_recommended_action": next_action,
            "triage_recommended_next_owner": next_owner,
        },
    )
    patched_metadata = dict(metadata)
    patched_metadata["triage_followup_task_id"] = triage.id
    ctx.store.update(task.id, metadata=patched_metadata)
    return triage, next_owner, True


def _build_triage_resolution_message(source: TaskItem, triage: TaskItem, action: str) -> str:
    return (
        f"Task {source.id} is reopened after triage follow-up {triage.id} completed. "
        f"Next action: {action}. Start now and report only real blockers."
    )


def _apply_triage_followup_resolution(
    *,
    ctx: TaskUpdateContext,
    triage: TaskItem,
    caller: str,
) -> list[dict[str, Any]] | None:
    if triage.status != TaskStatus.completed:
        return None
    metadata = triage.metadata if isinstance(triage.metadata, dict) else {}
    if metadata.get("triage_followup") != "true":
        return None

    source_id = str(metadata.get("triage_source_task_id") or "").strip()
    if not source_id:
        return None

    source = ctx.store.get(source_id)
    if source is None:
        return None

    if str(source.metadata.get("triage_followup_task_id") or "").strip() != triage.id:
        return None

    if str(source.metadata.get("triage_followup_resolution_id") or "").strip() == triage.id:
        return None

    source_status = str(metadata.get("triage_source_status") or source.status.value)
    if source_status == TaskStatus.blocked.value:
        if source.status != TaskStatus.blocked:
            return None
    elif source_status == TaskStatus.failed.value:
        if source.status != TaskStatus.failed:
            return None
        if str(source.metadata.get("failure_kind") or "").strip() != "complex":
            return None
    else:
        return None

    next_owner = str(metadata.get("triage_resolution_owner") or "").strip()
    next_action = str(metadata.get("triage_resolution_action") or "").strip()
    if not next_owner or not next_action:
        return None

    from clawteam.team.manager import TeamManager

    if TeamManager.get_member(ctx.team, next_owner) is None:
        fallback_leader = TeamManager.get_leader_name(ctx.team) or "leader"
        next_owner = fallback_leader

    reopen_decision = plan_reopen_task(existing=source, event=ReopenTaskEvent(caller=caller))
    if not reopen_decision.accepted:
        return None

    apply_result = _apply_reopen_transition(
        ctx=ctx,
        task_id=source.id,
        caller=caller,
        force=False,
        decision=reopen_decision,
    )
    updated = apply_result.task if apply_result is not None else None
    if updated is None:
        return None

    resolution_metadata = {
        "triage_followup_resolution_id": triage.id,
        "triage_followup_resolved_at": datetime.now().astimezone().isoformat(),
        "triage_followup_resolved_by": triage.owner or caller,
        "triage_followup_resolution_owner": next_owner,
        "triage_followup_resolution_action": next_action,
        "triage_followup_resolution_source_status": source_status,
    }

    updated = _apply_generic_patch(
        ctx=ctx,
        task_id=source.id,
        patch=TaskPatch(
            owner=next_owner,
            metadata=resolution_metadata,
        ),
        caller=caller,
        force=False,
    )
    if updated is None:
        return None

    return wake_tasks_to_pending(
        ctx.team,
        [updated.id],
        caller=caller,
        message_builder=lambda target: _build_triage_resolution_message(target, triage, next_action),
        repo=ctx.repo,
        store=ctx.store,
        runtime=ctx.runtime,
        release_notifier=ctx.release_notifier,
    )


def _infer_execution_shape(feature_scope: dict[str, Any]) -> str:
    explicit_shape = str(feature_scope.get("execution_shape") or "").strip().lower()
    if explicit_shape in ALLOWED_EXECUTION_SHAPES:
        return explicit_shape
    raise TaskUpdateValidationError(
        "post-scope materialization requires FEATURE_SCOPE.execution_shape to be explicitly set to ui-only | backend-only | full-stack"
    )


def _validate_materialization_budget(feature_scope: dict[str, Any]) -> None:
    parsed = read_feature_scope_metadata({"feature_scope": feature_scope})
    if parsed is None:
        raise TaskUpdateValidationError("post-scope materialization requires machine-readable feature_scope metadata")
    budget = parsed.change_budget
    if not budget.allowed_layers or not budget.allowed_operations or not budget.allowed_roots:
        raise TaskUpdateValidationError(
            "post-scope materialization requires FEATURE_SCOPE.change_budget with allowed_layers, allowed_operations, and allowed_roots"
        )


def _mobile_lane_boundary(roots: list[str]) -> list[str]:
    normalized = [str(root).strip().lstrip("./") for root in roots]
    if normalized and all(path.startswith("mobile/") for path in normalized):
        return ["mobile/"]
    return roots



def _build_lane_authority(feature_scope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parsed = read_feature_scope_metadata({"feature_scope": feature_scope})
    if parsed is None:
        raise TaskUpdateValidationError("post-scope materialization requires machine-readable feature_scope metadata")

    budget = parsed.change_budget
    validated_targets = [target for target in parsed.initial_targets if target.exists]
    frontend_roots = [root for root in budget.allowed_roots if _infer_layers_from_paths([root]) & {"web-ui", "mobile-ui"}]
    lane_roots = {
        "frontend": _mobile_lane_boundary(frontend_roots),
        "backend": [root for root in budget.allowed_roots if _infer_layers_from_paths([root]) & {"backend", "api", "schema", "db"}],
        "combined": list(budget.allowed_roots),
    }
    lane_layers = {
        "frontend": [layer for layer in budget.allowed_layers if layer in {"web-ui", "mobile-ui"}],
        "backend": [layer for layer in budget.allowed_layers if layer in {"backend", "api", "schema", "db", "crawler", "auth"}],
        "combined": list(budget.allowed_layers),
    }
    lane_targets = {
        "frontend": [
            target.model_dump(mode="python")
            for target in validated_targets
            if target.kind in _FRONTEND_TARGET_KINDS or _infer_layers_from_paths([target.path]) & {"web-ui", "mobile-ui"}
        ],
        "backend": [
            target.model_dump(mode="python")
            for target in validated_targets
            if target.kind in _BACKEND_TARGET_KINDS or _infer_layers_from_paths([target.path]) & {"backend", "api", "schema", "db"}
        ],
        "combined": [target.model_dump(mode="python") for target in validated_targets],
    }

    authority: dict[str, dict[str, Any]] = {}
    for lane_name in ("frontend", "backend", "combined"):
        authority[lane_name] = {
            "lane": lane_name,
            "allowed_roots": lane_roots[lane_name],
            "allowed_layers": lane_layers[lane_name],
            "initial_targets": lane_targets[lane_name],
            "meaningful": bool(lane_roots[lane_name] and lane_layers[lane_name] and lane_targets[lane_name]),
            "primary_evidence": {
                "roots": list(lane_roots[lane_name]),
                "layers": list(lane_layers[lane_name]),
                "targets": [target["path"] for target in lane_targets[lane_name]],
            },
        }
    return authority


def _render_lane_authority_context(authority: dict[str, Any]) -> str:
    evidence = authority.get("primary_evidence") if isinstance(authority, dict) else None
    if not isinstance(evidence, dict):
        return ""
    roots = ", ".join(str(item) for item in evidence.get("roots") or []) or "none"
    layers = ", ".join(str(item) for item in evidence.get("layers") or []) or "none"
    targets = ", ".join(str(item) for item in evidence.get("targets") or []) or "none"
    return (
        "\n\n## Lane Authority\n"
        f"- lane: {authority.get('lane') or 'unspecified'}\n"
        f"- allowed_roots: {roots}\n"
        f"- allowed_layers: {layers}\n"
        f"- initial_targets: {targets}\n"
        "- This machine-readable slice authority is binding for this task; stay inside it and fail closed if the required change spills outside."
    )


def _materialize_post_scope_tasks(*, store: TaskStore, scope_task: TaskItem) -> tuple[TaskItem, TaskTransitionPlan, dict[str, Any]]:
    metadata = scope_task.metadata if isinstance(scope_task.metadata, dict) else {}
    workflow_definition = metadata.get("workflow_definition")
    feature_scope = metadata.get("feature_scope")
    launch_brief = metadata.get("launch_brief")
    resolved_scope = metadata.get("resolved_scope")
    scope_warnings = metadata.get("scope_audit_warnings")
    if not isinstance(workflow_definition, dict):
        raise TaskUpdateValidationError("post-scope materialization requires preserved workflow_definition metadata")
    if not isinstance(feature_scope, dict):
        raise TaskUpdateValidationError("post-scope materialization requires machine-readable feature_scope metadata")
    tasks = workflow_definition.get("tasks")
    if workflow_definition.get("template_name") != "five-step-delivery" or not isinstance(tasks, list):
        raise TaskUpdateValidationError("post-scope materialization skeleton currently supports only five-step-delivery")

    authored = {str(item.get("subject") or ""): item for item in tasks if isinstance(item, dict)}
    required_subjects = {
        _FIVE_STEP_SCOPE_SUBJECT,
        _FIVE_STEP_SETUP_SUBJECT,
        _FIVE_STEP_IMPL_A_SUBJECT,
        _FIVE_STEP_IMPL_B_SUBJECT,
        _FIVE_STEP_QA_A_SUBJECT,
        _FIVE_STEP_QA_B_SUBJECT,
        _FIVE_STEP_REVIEW_SUBJECT,
        _FIVE_STEP_DELIVER_SUBJECT,
    }
    if set(authored) != required_subjects:
        raise TaskUpdateValidationError("post-scope materialization requires the authored five-step-delivery workflow definition")

    execution_shape = _infer_execution_shape(feature_scope)
    _validate_materialization_budget(feature_scope)
    lane_authority = _build_lane_authority(feature_scope)
    dual_lane_full_stack = (
        execution_shape == "full-stack"
        and lane_authority["backend"]["meaningful"]
        and lane_authority["frontend"]["meaningful"]
        and set(lane_authority["backend"]["allowed_roots"]).isdisjoint(set(lane_authority["frontend"]["allowed_roots"]))
        and set(lane_authority["backend"]["primary_evidence"]["targets"]).isdisjoint(set(lane_authority["frontend"]["primary_evidence"]["targets"]))
    )
    selected_subjects = {
        "ui-only": [
            _FIVE_STEP_SETUP_SUBJECT,
            _FIVE_STEP_IMPL_B_SUBJECT,
            _FIVE_STEP_QA_B_SUBJECT,
            _FIVE_STEP_REVIEW_SUBJECT,
            _FIVE_STEP_DELIVER_SUBJECT,
        ],
        "backend-only": [
            _FIVE_STEP_SETUP_SUBJECT,
            _FIVE_STEP_IMPL_A_SUBJECT,
            _FIVE_STEP_QA_A_SUBJECT,
            _FIVE_STEP_REVIEW_SUBJECT,
            _FIVE_STEP_DELIVER_SUBJECT,
        ],
        "full-stack": [
            _FIVE_STEP_SETUP_SUBJECT,
            _FIVE_STEP_IMPL_A_SUBJECT,
            _FIVE_STEP_QA_A_SUBJECT,
            _FIVE_STEP_REVIEW_SUBJECT,
            _FIVE_STEP_DELIVER_SUBJECT,
        ],
    }[execution_shape]
    if dual_lane_full_stack:
        selected_subjects = [
            _FIVE_STEP_SETUP_SUBJECT,
            _FIVE_STEP_IMPL_A_SUBJECT,
            _FIVE_STEP_IMPL_B_SUBJECT,
            _FIVE_STEP_QA_A_SUBJECT,
            _FIVE_STEP_QA_B_SUBJECT,
            _FIVE_STEP_REVIEW_SUBJECT,
            _FIVE_STEP_DELIVER_SUBJECT,
        ]

    single_lane_authority = lane_authority["combined"] if execution_shape == "full-stack" and not dual_lane_full_stack else lane_authority["backend"]
    subject_lane_authority = {
        _FIVE_STEP_IMPL_A_SUBJECT: single_lane_authority,
        _FIVE_STEP_QA_A_SUBJECT: single_lane_authority,
        _FIVE_STEP_IMPL_B_SUBJECT: lane_authority["frontend"],
        _FIVE_STEP_QA_B_SUBJECT: lane_authority["frontend"],
    }

    created_ids_by_subject: dict[str, str] = {_FIVE_STEP_SCOPE_SUBJECT: scope_task.id}
    root_ids_to_wake: list[str] = []
    for subject in [s for s in workflow_definition.get("authored_task_order") or [] if s in selected_subjects]:
        authored_task = authored[subject]
        raw_blocked_by = [str(dep) for dep in authored_task.get("blocked_by") or []]
        filtered_blocked_by = [dep for dep in raw_blocked_by if dep in selected_subjects or dep == _FIVE_STEP_SCOPE_SUBJECT]
        if raw_blocked_by and not filtered_blocked_by and subject != _FIVE_STEP_SETUP_SUBJECT:
            raise TaskUpdateValidationError(f"post-scope materialization could not map dependencies for '{subject}' cleanly")
        blocked_by_ids = [created_ids_by_subject[dep] for dep in filtered_blocked_by if dep != _FIVE_STEP_SCOPE_SUBJECT]
        on_fail_subjects = [str(dep) for dep in authored_task.get("on_fail") or [] if dep in selected_subjects]
        task_metadata = {
            "template_stage": str(authored_task.get("stage") or ""),
            "materialization_origin": "post_scope_materialization",
            "launch_brief": launch_brief,
            "resolved_scope": resolved_scope,
            "feature_scope": feature_scope,
            "execution_shape": execution_shape,
            "scope_task_id": scope_task.id,
        }
        if isinstance(scope_warnings, list):
            task_metadata["scope_audit_warnings"] = scope_warnings
        if authored_task.get("message_type"):
            task_metadata["message_type"] = authored_task.get("message_type")
        if authored_task.get("required_sections"):
            task_metadata["required_sections"] = list(authored_task.get("required_sections") or [])
        lane_slice_authority = subject_lane_authority.get(subject)
        if lane_slice_authority is not None:
            task_metadata["lane_slice_authority"] = lane_slice_authority
        if on_fail_subjects:
            task_metadata["on_fail"] = [created_ids_by_subject[dep] for dep in on_fail_subjects]

        description = inject_resolved_scope_context(
            description=str(authored_task.get("description") or ""),
            normalized=resolved_scope or {},
            scope_audit_warnings=scope_warnings if isinstance(scope_warnings, list) else None,
        )
        if lane_slice_authority is not None:
            description += _render_lane_authority_context(lane_slice_authority)
        created = store.create(
            subject=subject,
            description=description,
            owner=str(authored_task.get("owner") or ""),
            blocked_by=blocked_by_ids,
            metadata=task_metadata,
        )
        created_ids_by_subject[subject] = created.id
        if not blocked_by_ids:
            root_ids_to_wake.append(created.id)

    updated_metadata = dict(metadata)
    updated_metadata["deferred_materialization_state"] = DEFERRED_MATERIALIZATION_MATERIALIZED
    updated_metadata["deferred_materialization_case"] = DEFERRED_MATERIALIZATION_CASE
    updated_metadata["execution_shape"] = execution_shape
    updated_metadata["lane_authority"] = lane_authority
    updated_metadata["lane_materialization"] = "dual_lane" if dual_lane_full_stack else "single_lane_fail_closed"
    updated_metadata["materialized_task_ids"] = {
        subject: created_ids_by_subject[subject] for subject in selected_subjects if subject in created_ids_by_subject
    }
    updated_metadata["workflow_definition"] = {
        **workflow_definition,
        "materialized_subjects": [_FIVE_STEP_SCOPE_SUBJECT, *selected_subjects],
        "deferred_subjects": [subject for subject in workflow_definition.get("authored_task_order") or [] if subject not in {_FIVE_STEP_SCOPE_SUBJECT, *selected_subjects}],
    }
    updated_scope = store.update(scope_task.id, metadata=updated_metadata)
    if updated_scope is None:
        raise TaskUpdateValidationError("post-scope materialization could not persist scope metadata")

    return (
        updated_scope,
        TaskTransitionPlan(metadata_to_apply=None, dependent_ids_to_wake=root_ids_to_wake, failed_targets_to_wake=[]),
        {
            "case_name": DEFERRED_MATERIALIZATION_CASE,
            "status": "materialized",
            "mode": POST_SCOPE_MATERIALIZATION_MODE,
            "hook": DEFERRED_MATERIALIZATION_HOOK,
            "state": DEFERRED_MATERIALIZATION_MATERIALIZED,
            "reason": "Downstream topology materialized explicitly from FEATURE_SCOPE after scope completion.",
            "execution_shape": execution_shape,
            "lane_materialization": "dual_lane" if dual_lane_full_stack else "single_lane_fail_closed",
            "lane_authority": lane_authority,
            "created_task_ids": {subject: created_ids_by_subject[subject] for subject in selected_subjects if subject in created_ids_by_subject},
            "released_root_task_ids": list(root_ids_to_wake),
            "deferred_subjects": list(updated_metadata["workflow_definition"]["deferred_subjects"]),
        },
    )


def _resolve_deferred_materialization(
    *,
    task: TaskItem,
    deferred_materialization: dict[str, Any] | None,
    dependent_ids_to_wake: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    metadata = task.metadata if isinstance(task.metadata, dict) else None
    is_post_scope_completion = (
        metadata is not None
        and task.status == TaskStatus.completed
        and str(metadata.get("template_stage") or "").strip().lower() == "scope"
        and str(metadata.get("materialization_mode") or "immediate").strip().lower() == POST_SCOPE_MATERIALIZATION_MODE
    )
    if not is_post_scope_completion and deferred_materialization is None:
        return None, dependent_ids_to_wake

    effect = dict(deferred_materialization or {})
    effect["case_name"] = str(effect.get("case_name") or DEFERRED_MATERIALIZATION_CASE)
    effect["mode"] = str(effect.get("mode") or POST_SCOPE_MATERIALIZATION_MODE)
    effect["hook"] = str(effect.get("hook") or DEFERRED_MATERIALIZATION_HOOK)
    effect["state"] = str(
        effect.get("state")
        or (metadata or {}).get("deferred_materialization_state")
        or DEFERRED_MATERIALIZATION_AWAITING_HOOK
    )
    effect["status"] = str(effect.get("status") or "fail_closed")
    effect["reason"] = str(effect.get("reason") or DEFERRED_MATERIALIZATION_REASON)
    if effect["status"] == "fail_closed":
        effect["suppressed_dependent_ids"] = list(
            effect.get("suppressed_dependent_ids") or dependent_ids_to_wake
        )
        return effect, []
    return effect, dependent_ids_to_wake

def execute_task_update_effects(
    *,
    ctx: TaskUpdateContext,
    task: TaskItem,
    caller: str,
    wake_owner: bool,
    message: str,
    dependent_ids_to_wake: list[str],
    failed_targets_to_wake: list[str],
    deferred_materialization: dict[str, Any] | None = None,
) -> TaskUpdateEffects:
    """Execute post-update side effects after the task store mutation succeeds."""
    deferred_materialization, dependent_ids_to_wake = _resolve_deferred_materialization(
        task=task,
        deferred_materialization=deferred_materialization,
        dependent_ids_to_wake=dependent_ids_to_wake,
    )

    scope_payload = _scope_payload(task)
    scope_warnings = task.metadata.get("scope_audit_warnings") if isinstance(task.metadata, dict) else None
    feature_scope = task.metadata.get("feature_scope") if isinstance(task.metadata, dict) else None
    runtime_handoff = _setup_runtime_handoff_payload(task)
    if isinstance(task.metadata, dict) and task.metadata.get("message_type") == "SETUP_RESULT" and runtime_handoff:
        current_metadata = dict(task.metadata)
        if current_metadata.get("runtime_handoff") != runtime_handoff:
            current_metadata["runtime_handoff"] = runtime_handoff
            updated_task = ctx.store.update(task.id, metadata=current_metadata)
            if updated_task is not None:
                task = updated_task
    if dependent_ids_to_wake and (scope_payload or runtime_handoff):
        _propagate_resolved_scope_to_targets(
            store=ctx.store,
            target_ids=dependent_ids_to_wake,
            scope_payload=scope_payload or {},
            scope_warnings=scope_warnings if isinstance(scope_warnings, list) else None,
            runtime_handoff=runtime_handoff,
            feature_scope=feature_scope if isinstance(feature_scope, dict) else None,
        )

    wake = None
    if wake_owner and task.status == TaskStatus.pending and task.owner:
        wake = ctx.runtime.release_to_owner(
            task,
            caller=caller,
            message=message,
            respawn=True,
            release_notifier=ctx.release_notifier,
        )

    auto_releases: list[dict[str, Any]] = []
    if dependent_ids_to_wake:
        auto_releases.extend(
            wake_tasks_to_pending(
                ctx.release_team,
                dependent_ids_to_wake,
                caller=caller,
                message_builder=lambda target: _build_dependency_completion_message(task, target),
                repo=ctx.release_repo,
                store=ctx.store,
                runtime=ctx.runtime,
                release_notifier=ctx.release_notifier,
            )
        )
    if failed_targets_to_wake:
        auto_releases.extend(
            wake_tasks_to_pending(
                ctx.team,
                failed_targets_to_wake,
                caller=caller,
                message_builder=lambda target: _build_failure_reopen_message(task, target),
                repo=ctx.repo,
                store=ctx.store,
                runtime=ctx.runtime,
                release_notifier=ctx.release_notifier,
            )
        )

    triage_release = None
    triage_task, _triage_owner, triage_created = _build_triage_followup(task, ctx)
    if triage_task is not None and triage_task.owner and triage_created:
        try:
            triage_release = ctx.runtime.release_to_owner(
                triage_task,
                caller=caller,
                message=(
                    f"Task {triage_task.id} is auto-created from {task.id}. "
                    "Triage the blocker/failure, choose the next owner, and only then reopen or reroute work."
                ),
                respawn=True,
                release_notifier=ctx.release_notifier,
            )
        except Exception as exc:
            triage_release = {"taskId": triage_task.id, "owner": triage_task.owner, "releaseError": str(exc)}

    _apply_triage_followup_resolution(ctx=ctx, triage=task, caller=caller)

    failure_notice = None
    if task.status == TaskStatus.failed:
        failure_notice = ctx.failure_notifier(ctx.team, task, caller)

    return TaskUpdateEffects(
        wake=wake,
        auto_releases=auto_releases,
        failure_notice=failure_notice,
        triage_release=triage_release,
        deferred_materialization=deferred_materialization,
    )


def _build_generic_task_patch(
    *,
    request: TaskUpdateRequest,
    metadata_to_apply: dict[str, Any] | None,
    metadata_keys_to_remove: list[str] | None,
) -> TaskPatch:
    return TaskPatch(
        owner=request.owner,
        subject=request.subject,
        description=request.description,
        add_blocks=request.add_blocks,
        add_blocked_by=request.add_blocked_by,
        metadata=metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
    )


def _decision_to_payload(decision: Any, default_case_name: str) -> dict[str, Any]:
    if hasattr(decision, "case_name"):
        return {
            "case_name": decision.case_name,
            "accepted": decision.accepted,
            "rejection_reason": decision.rejection_reason,
        }
    if isinstance(decision, dict):
        return {
            "case_name": decision.get("case_name", default_case_name),
            "accepted": decision.get("accepted", True),
            "rejection_reason": decision.get("rejection_reason"),
        }
    return {
        "case_name": default_case_name,
        "accepted": True,
        "rejection_reason": None,
    }


def _terminal_decision_for_apply(
    *,
    execution_decision: Any,
    recovery_decision: Any,
) -> dict[str, Any]:
    if recovery_decision is not None and getattr(recovery_decision, "accepted", False):
        return _decision_to_payload(
            recovery_decision,
            default_case_name="recover_watchdog_failed_completion",
        )
    if execution_decision is not None:
        return _decision_to_payload(
            execution_decision,
            default_case_name="terminal_writeback_without_execution_scope",
        )
    return {
        "case_name": "terminal_writeback_without_execution_scope",
        "accepted": True,
        "rejection_reason": None,
    }


def _apply_terminal_transition(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    status: TaskStatus,
    execution_id: str | None,
    decision: Any,
    metadata_to_apply: dict[str, Any] | None,
    metadata_keys_to_remove: list[str] | None,
    force: bool,
) -> TransitionApplyResult | None:
    if execution_id:
        _decision_payload = _decision_to_payload(
            decision,
            default_case_name="terminal_writeback_without_execution_scope",
        )
        runtime_decision, _task, apply_result = ctx.store.apply_runtime_terminal_writeback(
            task_id,
            status=status,
            caller=caller,
            execution_id=execution_id,
            metadata=metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
            force=force,
            fallback_case_name=str(_decision_payload.get("case_name") or "worker_runtime_failed_closed"),
        )
        if runtime_decision is not None and not runtime_decision.accepted:
            raise RuntimeError(
                f"terminal writeback rejected: {runtime_decision.rejection_reason}"
            )
        return apply_result

    return ctx.store.apply_transition_decision(
        task_id,
        decision=_decision_to_payload(
            decision,
            default_case_name="terminal_writeback_without_execution_scope",
        ),
        status=status,
        caller=caller,
        execution_id=execution_id,
        metadata=metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
        force=force,
    )


def _apply_reopen_transition(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    force: bool,
    decision: Any,
) -> TransitionApplyResult | None:
    return ctx.store.apply_transition_decision(
        task_id,
        decision=_decision_to_payload(decision, default_case_name="reopen_task"),
        status=TaskStatus.pending,
        caller=caller,
        force=force,
    )


def _apply_generic_patch(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    force: bool,
    patch: TaskPatch,
) -> TaskItem | None:
    return ctx.store.apply_patch(
        task_id,
        patch=patch,
        caller=caller,
        force=force,
    )


def _apply_generic_status_update(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    request: TaskUpdateRequest,
    metadata_to_apply: dict[str, Any] | None,
    metadata_keys_to_remove: list[str] | None,
) -> TaskItem | None:
    return ctx.store.update(
        task_id,
        status=request.status,
        owner=request.owner,
        subject=request.subject,
        description=request.description,
        add_blocks=request.add_blocks,
        add_blocked_by=request.add_blocked_by,
        metadata=metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
        execution_id=request.execution_id,
        caller=caller,
        force=request.force,
    )


def execute_task_update(
    *,
    task_id: str,
    caller: str,
    request: TaskUpdateRequest,
    ctx: TaskUpdateContext,
) -> TaskUpdateResult:
    """Run the full task-update use case behind the CLI adapter."""
    existing = ctx.store.get(task_id)
    if not existing:
        raise KeyError(task_id)

    transition_request = TaskTransitionRequest(
        status=request.status,
        add_on_fail=request.add_on_fail,
        failure_kind=request.failure_kind,
        failure_note=request.failure_note,
        failure_root_cause=request.failure_root_cause,
        failure_evidence=request.failure_evidence,
        failure_recommended_next_owner=request.failure_recommended_next_owner,
        failure_recommended_action=request.failure_recommended_action,
    )
    plan = plan_task_transition(
        existing=existing,
        request=transition_request,
        all_tasks=ctx.store.list_tasks(),
    )

    metadata_to_apply = dict(plan.metadata_to_apply or {})
    if request.qa_result_status is not None:
        metadata_to_apply["qa_result_status"] = request.qa_result_status
    if request.qa_risk_note is not None:
        metadata_to_apply["qa_risk_note"] = request.qa_risk_note
    if request.triage_resolution_owner is not None:
        metadata_to_apply["triage_resolution_owner"] = request.triage_resolution_owner
    if request.triage_resolution_action is not None:
        metadata_to_apply["triage_resolution_action"] = request.triage_resolution_action
    if request.triage_resolution_note is not None:
        metadata_to_apply["triage_resolution_note"] = request.triage_resolution_note
    if request.failure_repair_packet is not None:
        if request.status != TaskStatus.failed:
            raise TaskUpdateValidationError("failure repair-packet options require --status failed")
        metadata_to_apply.update(request.failure_repair_packet.to_metadata())
    plan = TaskUpdatePlan(
        metadata_to_apply=metadata_to_apply or None,
        dependent_ids_to_wake=plan.dependent_ids_to_wake,
        failed_targets_to_wake=plan.failed_targets_to_wake,
    )

    metadata_keys_to_remove: list[str] | None = None
    apply_result: TransitionApplyResult | None = None
    deferred_materialization_effect: dict[str, Any] | None = None

    existing_launch_brief = existing.metadata.get("launch_brief") if isinstance(existing.metadata, dict) else None
    is_scope_task = (existing.metadata.get("template_stage") == "scope") if isinstance(existing.metadata, dict) else False
    require_feature_scope = bool(existing.metadata.get("feature_scope_required")) if isinstance(existing.metadata, dict) else False
    materialization_mode = str((existing.metadata or {}).get("materialization_mode") or "immediate").strip().lower() if isinstance(existing.metadata, dict) else "immediate"
    if request.status == TaskStatus.completed and is_scope_task:
        final_scope_description = (request.description or existing.description or "").strip()
        if not final_scope_description:
            raise TaskTransitionValidationError(
                "scope task completion must include the final structured brief before downstream release"
            )
        source_request = ""
        if isinstance(existing_launch_brief, dict):
            sections = existing_launch_brief.get("sections")
            if isinstance(sections, dict):
                source_request = str(sections.get("source_request") or "")
        try:
            validated_scope = validate_scope_task_completion(
                source_request=source_request,
                leader_brief=final_scope_description,
                require_feature_scope=require_feature_scope,
            )
        except ScopeTaskValidationError as e:
            raise TaskTransitionValidationError(str(e)) from e
        scope_warnings = find_scope_audit_warnings(
            source_request=source_request,
            normalized=validated_scope,
        )
        metadata = dict(plan.metadata_to_apply or {})
        metadata["launch_brief"] = validated_scope.model_dump(mode="json", exclude_none=True)
        metadata["resolved_scope"] = validated_scope.model_dump(mode="json", exclude_none=True)
        metadata["scope_audit_warnings"] = [warning.model_dump(mode="json") for warning in scope_warnings]
        if validated_scope.feature_scope is not None:
            metadata["feature_scope"] = validated_scope.feature_scope.model_dump(mode="json")
        if materialization_mode == POST_SCOPE_MATERIALIZATION_MODE:
            metadata["deferred_materialization_state"] = DEFERRED_MATERIALIZATION_AWAITING_HOOK
            metadata["deferred_materialization_case"] = DEFERRED_MATERIALIZATION_CASE
            plan = TaskUpdatePlan(
                metadata_to_apply=metadata,
                dependent_ids_to_wake=[],
                failed_targets_to_wake=plan.failed_targets_to_wake,
            )
        else:
            plan = TaskUpdatePlan(
                metadata_to_apply=metadata,
                dependent_ids_to_wake=plan.dependent_ids_to_wake,
                failed_targets_to_wake=plan.failed_targets_to_wake,
            )

    execution_decision = plan_terminal_writeback(
        existing=existing,
        event=TerminalWritebackEvent(
            caller=caller,
            status=request.status,
            execution_id=request.execution_id,
        ) if request.status in (TaskStatus.completed, TaskStatus.failed) else None,
    ) if request.status in (TaskStatus.completed, TaskStatus.failed) else None
    if execution_decision and not execution_decision.accepted:
        ctx.store.record_transition_rejection(
            task_id,
            case_name=execution_decision.case_name,
            caller=caller,
            execution_id=request.execution_id,
            rejection_reason=execution_decision.rejection_reason,
        )
        raise RuntimeError(
            f"terminal writeback rejected: {execution_decision.rejection_reason}"
        )
    recovery_decision = plan_watchdog_failed_completion_recovery(
        existing=existing,
        caller=caller,
        requested_status=request.status,
    )
    if recovery_decision and recovery_decision.accepted:
        metadata_keys_to_remove = recovery_decision.metadata_keys_to_remove
        metadata = dict(plan.metadata_to_apply or {})
        metadata.update(recovery_decision.metadata_to_apply or {})
        plan = TaskUpdatePlan(
            metadata_to_apply=metadata,
            dependent_ids_to_wake=plan.dependent_ids_to_wake,
            failed_targets_to_wake=plan.failed_targets_to_wake,
        )

    validate_completion(existing, request, all_tasks=ctx.store.list_tasks())

    generic_patch = _build_generic_task_patch(
        request=request,
        metadata_to_apply=plan.metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
    )

    if request.status in (TaskStatus.completed, TaskStatus.failed):
        apply_result = _apply_terminal_transition(
            ctx=ctx,
            task_id=task_id,
            caller=caller,
            status=request.status,
            execution_id=request.execution_id,
            decision=_terminal_decision_for_apply(
                execution_decision=execution_decision,
                recovery_decision=recovery_decision,
            ),
            metadata_to_apply=plan.metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
            force=request.force,
        )
        task = apply_result.task if apply_result is not None else None
        if task is not None and any(
            value is not None for value in (
                request.owner,
                request.subject,
                request.description,
                request.add_blocks,
                request.add_blocked_by,
            )
        ):
            task = _apply_generic_patch(
                ctx=ctx,
                task_id=task_id,
                patch=TaskPatch(
                    owner=request.owner,
                    subject=request.subject,
                    description=request.description,
                    add_blocks=request.add_blocks,
                    add_blocked_by=request.add_blocked_by,
                    metadata=None,
                    metadata_keys_to_remove=None,
                ),
                caller=caller,
                force=request.force,
            )
    elif request.status == TaskStatus.pending and existing.status != TaskStatus.pending:
        reopen_decision = plan_reopen_task(existing=existing, event=ReopenTaskEvent(caller=caller))
        if not reopen_decision.accepted:
            ctx.store.record_transition_rejection(
                task_id,
                case_name=reopen_decision.case_name,
                caller=caller,
                rejection_reason=reopen_decision.rejection_reason,
            )
            raise RuntimeError(f"reopen rejected: {reopen_decision.rejection_reason}")
        apply_result = _apply_reopen_transition(
            ctx=ctx,
            task_id=task_id,
            caller=caller,
            force=request.force,
            decision=reopen_decision,
        )
        task = apply_result.task if apply_result is not None else None
        if not generic_patch.is_empty():
            task = _apply_generic_patch(
                ctx=ctx,
                task_id=task_id,
                patch=generic_patch,
                caller=caller,
                force=request.force,
            )
    elif request.status is None:
        task = _apply_generic_patch(
            ctx=ctx,
            task_id=task_id,
            patch=generic_patch,
            caller=caller,
            force=request.force,
        )
    else:
        task = _apply_generic_status_update(
            ctx=ctx,
            task_id=task_id,
            caller=caller,
            request=request,
            metadata_to_apply=plan.metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
        )

    is_post_scope_completion = (
        request.status == TaskStatus.completed
        and isinstance(task.metadata, dict)
        and str(task.metadata.get("template_stage") or "").strip().lower() == "scope"
        and str(task.metadata.get("materialization_mode") or "immediate").strip().lower() == POST_SCOPE_MATERIALIZATION_MODE
    )
    if is_post_scope_completion:
        task, materialization_plan, deferred_materialization_effect = _materialize_post_scope_tasks(
            store=ctx.store,
            scope_task=task,
        )
        plan = TaskUpdatePlan(
            metadata_to_apply=plan.metadata_to_apply,
            dependent_ids_to_wake=materialization_plan.dependent_ids_to_wake,
            failed_targets_to_wake=plan.failed_targets_to_wake,
        )

    effects = execute_task_update_effects(
        ctx=ctx,
        task=task,
        caller=caller,
        wake_owner=request.wake_owner,
        message=request.message,
        dependent_ids_to_wake=plan.dependent_ids_to_wake,
        failed_targets_to_wake=plan.failed_targets_to_wake,
        deferred_materialization=deferred_materialization_effect,
    )

    return TaskUpdateResult(task=task, plan=plan, effects=effects, apply_result=apply_result)
