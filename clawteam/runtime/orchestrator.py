"""Runtime orchestration helpers for task release and wake flows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from clawteam.execution.state import AWAITING_CLAIM, AWAITING_RELEASE, CLAIM_FAILED, ExecutionLifecycleState, merge_execution_metadata
from clawteam.team.models import TaskItem, TaskStatus


@dataclass(frozen=True)
class ReplacementDecision:
    owner: str
    replacement_required: bool
    replaced_execution_id: str | None
    reason: str


@dataclass(frozen=True)
class RuntimeOrchestrator:
    """Application-facing facade for runtime wake/respawn behavior."""

    team: str
    repo: str | None = None

    def release_to_owner(
        self,
        task: TaskItem,
        *,
        caller: str,
        message: str = "",
        respawn: bool = True,
        release_notifier: Callable[[str, TaskItem, str, str], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        from clawteam.delivery.release_notifier import notify_task_release
        from clawteam.spawn.registry import get_agent_runtime_state, terminate_agent
        from clawteam.team.manager import TeamManager
        from clawteam.team.tasks import TaskStore

        release_message = message.strip() or f"Task {task.id} is released. Start now and report only real blockers."

        store = TaskStore(self.team)
        self._write_release_execution_metadata(
            store,
            task,
            caller=caller,
            state=AWAITING_RELEASE,
            released_at=task.updated_at,
        )

        state_before = get_agent_runtime_state(self.team, task.owner)
        alive_before = True if state_before == "alive" else (None if state_before == "missing" else False)
        replacement = plan_replacement(
            store=TaskStore(self.team),
            task=task,
            state_before=state_before,
            respawn=respawn,
        )
        respawned = False
        terminated_stale = False
        spawn_info = None
        cleared_tasks: list[TaskItem] = []

        if replacement.reason in {"dead", "stale"}:
            member = TeamManager.get_member(self.team, task.owner)
            if member is None:
                raise RuntimeError(f"Owner '{task.owner}' is not a registered team member")
            if replacement.replacement_required:
                cleared_tasks = TaskStore(self.team).clear_unfinished_tasks_for_owner(task.owner)
            if state_before == "stale":
                terminated_stale = terminate_agent(self.team, task.owner)
            spawn_info = _spawn_existing_agent(
                team_name=self.team,
                agent_name=task.owner,
                agent_id=member.agent_id,
                agent_type=member.agent_type,
                task_prompt=(
                    "Your previous worker runtime was replaced. "
                    + (
                        "All unfinished tasks previously assigned to you were cleared. "
                        "Do not resume old work. Wait for the leader to dispatch fresh tasks."
                        if replacement.replacement_required
                        else "No claimed unfinished task was preserved from the old runtime. Wait for or consume the fresh wake for your current task."
                    )
                ),
                repo=self.repo,
                resume=False,
            )
            respawned = True

        notifier_result = None
        try:
            if not replacement.replacement_required:
                if respawn and state_before == "missing":
                    member = TeamManager.get_member(self.team, task.owner)
                    if member is None:
                        raise RuntimeError(f"Owner '{task.owner}' is not a registered team member")
                    spawn_info = _spawn_existing_agent(
                        team_name=self.team,
                        agent_name=task.owner,
                        agent_id=member.agent_id,
                        agent_type=member.agent_type,
                        task_prompt=_build_release_task_prompt(task, release_message),
                        repo=self.repo,
                        resume=True,
                    )
                    respawned = True

                notifier = release_notifier or notify_task_release
                notifier_result = notifier(self.team, task, caller, release_message)
        except Exception as exc:
            self._write_release_execution_metadata(
                store,
                task,
                caller=caller,
                state=CLAIM_FAILED,
                runtime_state_before=state_before or "unknown",
                respawn_attempted=bool(respawn),
                respawn_succeeded=respawned,
                message_sent=bool((notifier_result or {}).get("messageSent")),
                message_id=str((notifier_result or {}).get("messageId") or ""),
                replacement_required=replacement.replacement_required,
                replacement_reason=replacement.reason,
                last_error=str(exc),
            )
            raise

        result = {
            "messageSent": not replacement.replacement_required,
            "message": release_message,
            "ownerAliveBefore": alive_before,
            "ownerRuntimeStateBefore": state_before,
            "terminatedStale": terminated_stale,
            "respawned": respawned,
            "spawn": spawn_info or {},
            "replacementRequired": replacement.replacement_required,
            "replacementReason": replacement.reason,
            "replacedExecutionId": replacement.replaced_execution_id,
            "replacement": asdict(replacement),
            "clearedTaskIds": [item.id for item in cleared_tasks],
            "clearedTaskSubjects": [item.subject for item in cleared_tasks],
            **(notifier_result or {}),
        }
        self._write_release_execution_metadata(
            store,
            task,
            caller=caller,
            state=AWAITING_CLAIM,
            runtime_state_before=state_before or "unknown",
            respawn_attempted=bool(respawn),
            respawn_succeeded=respawned,
            message_sent=bool(result.get("messageSent")),
            message_id=str(result.get("messageId") or ""),
            replacement_required=replacement.replacement_required,
            replacement_reason=replacement.reason,
        )
        return result

    def _write_release_execution_metadata(
        self,
        store,
        task: TaskItem,
        *,
        caller: str,
        state: ExecutionLifecycleState,
        **fields: Any,
    ) -> None:
        current = store.get(task.id) or task
        store.update(
            task.id,
            metadata=merge_execution_metadata(
                current,
                state=state,
                **fields,
            ),
            caller=caller,
        )


def plan_replacement(*, store, task: TaskItem, state_before: str | None, respawn: bool) -> ReplacementDecision:
    if not respawn:
        return ReplacementDecision(
            owner=task.owner or "",
            replacement_required=False,
            replaced_execution_id=None,
            reason="respawn_disabled",
        )
    if state_before in {"dead", "stale"}:
        started_unfinished_tasks = _started_unfinished_tasks_for_owner(store, task.owner)
        return ReplacementDecision(
            owner=task.owner or "",
            replacement_required=bool(started_unfinished_tasks),
            replaced_execution_id=task.active_execution_id if started_unfinished_tasks else None,
            reason=state_before,
        )
    if state_before == "missing":
        return ReplacementDecision(
            owner=task.owner or "",
            replacement_required=False,
            replaced_execution_id=None,
            reason="missing",
        )
    if state_before == "alive":
        return ReplacementDecision(
            owner=task.owner or "",
            replacement_required=False,
            replaced_execution_id=None,
            reason="alive",
        )
    return ReplacementDecision(
        owner=task.owner or "",
        replacement_required=False,
        replaced_execution_id=None,
        reason="unknown",
    )


def _task_has_started_execution(task: TaskItem) -> bool:
    """Return True only when there is evidence of current unfinished execution.

    Historical evidence from a prior completed attempt (for example a reopened task
    that still has started_at/duration history) must not force replacement cleanup
    for the new pending task.
    """
    return bool(
        task.active_execution_id
        or task.active_execution_owner
        or task.locked_by
        or task.status == TaskStatus.in_progress
    )


def _started_unfinished_tasks_for_owner(store, owner: str) -> list[TaskItem]:
    return [
        candidate
        for candidate in store.list_tasks(owner=owner)
        if candidate.status in {TaskStatus.pending, TaskStatus.blocked, TaskStatus.in_progress}
        and _task_has_started_execution(candidate)
    ]


def _workspace_registry_path(team_name: str) -> Path:
    from clawteam.team.models import get_data_dir

    return get_data_dir() / "workspaces" / team_name / "workspace-registry.json"


def _load_workspace_info(team_name: str, agent_name: str):
    from clawteam.workspace.models import WorkspaceRegistry

    path = _workspace_registry_path(team_name)
    if not path.exists():
        return None
    try:
        registry = WorkspaceRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for workspace in registry.workspaces:
        if workspace.agent_name == agent_name:
            return workspace
    return None


def _build_release_task_prompt(task: TaskItem, message: str) -> str:
    lines = []
    if message.strip():
        lines.append(message.strip())
        lines.append("")
    lines.extend(
        [
            f"Resume task {task.id} now.",
            f"Subject: {task.subject}",
        ]
    )
    if task.description:
        lines.extend(
            [
                "Description:",
                task.description,
            ]
        )
    lines.extend(
        [
            "",
            "This task has been released back to you.",
            "Start immediately, update the task to in_progress when you begin, and only mark it completed when truly done.",
        ]
    )
    return "\n".join(lines)


def _spawn_existing_agent(
    team_name: str,
    agent_name: str,
    agent_id: str,
    agent_type: str,
    task_prompt: str,
    repo: str | None = None,
    backend: str | None = None,
    skip_permissions: bool | None = None,
    resume: bool = True,
) -> dict[str, str]:
    import os

    from clawteam.config import get_effective
    from clawteam.spawn import get_backend
    from clawteam.spawn.prompt import build_agent_prompt
    from clawteam.spawn.registry import get_agent_record
    from clawteam.spawn.sessions import SessionStore
    from clawteam.team.manager import TeamManager

    if backend is None:
        backend, _ = get_effective("default_backend")
        backend = backend or "tmux"
    if skip_permissions is None:
        skip_permissions_value, _ = get_effective("skip_permissions")
        skip_permissions = str(skip_permissions_value).lower() not in ("false", "0", "no", "")

    workspace = _load_workspace_info(team_name, agent_name)
    existing_record = get_agent_record(team_name, agent_name)
    registry_cwd = str(Path(existing_record.get("cwd")).expanduser().resolve()) if existing_record and existing_record.get("cwd") else None
    cwd = workspace.worktree_path if workspace else (str(Path(repo).resolve()) if repo else registry_cwd)
    workspace_branch = workspace.branch_name if workspace else ""

    pinned_env: dict[str, str] = {}
    pinned_bin = str((existing_record or {}).get("clawteam_bin") or os.environ.get("CLAWTEAM_BIN") or "").strip()
    if pinned_bin:
        pinned_env["CLAWTEAM_BIN"] = pinned_bin

    prompt = build_agent_prompt(
        agent_name=agent_name,
        agent_id=agent_id,
        agent_type=agent_type,
        team_name=team_name,
        leader_name=TeamManager.get_leader_name(team_name) or "leader",
        task=task_prompt,
        user=os.environ.get("CLAWTEAM_USER", ""),
        workspace_dir=cwd or "",
        workspace_branch=workspace_branch,
    )

    command = ["openclaw"]
    if resume:
        session = SessionStore(team_name).load(agent_name)
        if session and session.session_id and command[0] in ("claude",):
            command = list(command) + ["--resume", session.session_id]
        prompt += "\nYou are resuming a previous session."

    backend_impl = get_backend(backend)
    result = backend_impl.spawn(
        command=command,
        agent_name=agent_name,
        agent_id=agent_id,
        agent_type=agent_type,
        team_name=team_name,
        prompt=prompt,
        env=pinned_env or None,
        cwd=cwd,
        skip_permissions=skip_permissions,
    )
    if result.startswith("Error"):
        raise RuntimeError(result)
    return {
        "backend": backend,
        "cwd": cwd or "",
        "workspaceBranch": workspace_branch,
        "message": result,
    }