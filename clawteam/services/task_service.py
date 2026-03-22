"""Task orchestration services for release and wake flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from clawteam.team.models import TaskItem, TaskStatus


@dataclass(frozen=True)
class TaskReleaseRequest:
    message: str
    respawn: bool
    repo: str | None
    force: bool


@dataclass(frozen=True)
class TaskReleaseResult:
    task: TaskItem
    release: dict[str, Any]


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
    from clawteam.spawn.sessions import SessionStore
    from clawteam.team.manager import TeamManager

    if backend is None:
        backend, _ = get_effective("default_backend")
        backend = backend or "tmux"
    if skip_permissions is None:
        skip_permissions_value, _ = get_effective("skip_permissions")
        skip_permissions = str(skip_permissions_value).lower() not in ("false", "0", "no", "")

    workspace = _load_workspace_info(team_name, agent_name)
    cwd = workspace.worktree_path if workspace else (str(Path(repo).resolve()) if repo else None)
    workspace_branch = workspace.branch_name if workspace else ""

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


def release_task_to_owner(
    team: str,
    task: TaskItem,
    caller: str,
    message: str = "",
    respawn: bool = True,
    repo: str | None = None,
) -> dict[str, Any]:
    from clawteam.spawn.registry import get_agent_runtime_state, terminate_agent
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore

    release_message = message.strip() or f"Task {task.id} is released. Start now and report only real blockers."

    state_before = get_agent_runtime_state(team, task.owner)
    alive_before = True if state_before == "alive" else (None if state_before == "missing" else False)
    respawned = False
    terminated_stale = False
    spawn_info = None
    replacement_required = False
    cleared_tasks: list[TaskItem] = []

    if respawn and state_before in {"dead", "stale"}:
        replacement_required = True
        store = TaskStore(team)
        cleared_tasks = store.clear_unfinished_tasks_for_owner(task.owner)
        member = TeamManager.get_member(team, task.owner)
        if member is None:
            raise RuntimeError(f"Owner '{task.owner}' is not a registered team member")
        if state_before == "stale":
            terminated_stale = terminate_agent(team, task.owner)
        spawn_info = _spawn_existing_agent(
            team_name=team,
            agent_name=task.owner,
            agent_id=member.agent_id,
            agent_type=member.agent_type,
            task_prompt=(
                "Your previous worker runtime was replaced. "
                "All unfinished tasks previously assigned to you were cleared. "
                "Do not resume old work. Wait for the leader to dispatch fresh tasks."
            ),
            repo=repo,
            resume=False,
        )
        respawned = True

    if not replacement_required:
        if respawn and state_before == "missing":
            member = TeamManager.get_member(team, task.owner)
            if member is None:
                raise RuntimeError(f"Owner '{task.owner}' is not a registered team member")
            spawn_info = _spawn_existing_agent(
                team_name=team,
                agent_name=task.owner,
                agent_id=member.agent_id,
                agent_type=member.agent_type,
                task_prompt=_build_release_task_prompt(task, release_message),
                repo=repo,
                resume=True,
            )
            respawned = True

        mailbox = MailboxManager(team)
        mailbox.send(
            caller,
            task.owner,
            release_message,
            key=f"task-wake:{task.id}",
            last_task=task.id,
            status=task.status.value,
        )

    return {
        "messageSent": not replacement_required,
        "message": release_message,
        "ownerAliveBefore": alive_before,
        "ownerRuntimeStateBefore": state_before,
        "terminatedStale": terminated_stale,
        "respawned": respawned,
        "spawn": spawn_info or {},
        "replacementRequired": replacement_required,
        "clearedTaskIds": [item.id for item in cleared_tasks],
        "clearedTaskSubjects": [item.subject for item in cleared_tasks],
    }


def execute_task_release(
    *,
    team: str,
    task_id: str,
    caller: str,
    request: TaskReleaseRequest,
    store: Any,
) -> TaskReleaseResult:
    """Run the full task-release use case behind the CLI adapter."""
    from clawteam.team.tasks import TaskLockError

    existing = store.get(task_id)
    if not existing:
        raise KeyError(task_id)
    if not existing.owner:
        raise ValueError(f"Task '{task_id}' has no owner")

    task = store.update(
        task_id,
        status=TaskStatus.pending,
        caller=caller,
        force=request.force,
    )
    if not task:
        raise KeyError(task_id)

    try:
        release = release_task_to_owner(
            team,
            task,
            caller=caller,
            message=request.message,
            respawn=request.respawn,
            repo=request.repo,
        )
    except TaskLockError:
        raise

    return TaskReleaseResult(task=task, release=release)


def describe_release_action(release: dict[str, Any]) -> str:
    if release.get("replacementRequired"):
        return (
            f"  Replacement cleanup for {release['owner']} task {release['taskId']}: "
            f"cleared {len(release.get('clearedTaskIds', []))} unfinished task(s); leader must re-dispatch."
        )
    return (
        f"  Auto-notified {release['owner']} for task {release['taskId']}"
        + (f" and respawned via {release['spawn'].get('backend', '')}" if release.get("respawned") else "")
    )


def wake_tasks_to_pending(
    team: str,
    task_ids: list[str],
    caller: str,
    message_builder: Callable[[TaskItem], str],
    repo: str | None = None,
) -> list[dict[str, Any]]:
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    releases: list[dict[str, Any]] = []
    for target_id in task_ids:
        target = store.get(target_id)
        if target is None or not target.owner or target.status != TaskStatus.pending:
            continue
        release = release_task_to_owner(
            team,
            target,
            caller=caller,
            message=message_builder(target),
            respawn=True,
            repo=repo,
        )
        releases.append({"taskId": target.id, "owner": target.owner, **release})
    return releases
