"""Task orchestration services for release and wake flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from clawteam.team.tasks import TaskStore

from clawteam.runtime.orchestrator import RuntimeOrchestrator
from clawteam.team.models import TaskItem, TaskStatus


@dataclass(frozen=True)
class TaskReleaseRequest:
    message: str
    respawn: bool
    force: bool


@dataclass(frozen=True)
class TaskReleaseResult:
    task: TaskItem
    release: dict[str, Any]


@dataclass(frozen=True)
class TaskReleaseContext:
    team: str
    store: TaskStore
    runtime: RuntimeOrchestrator
    repo: str | None = None


def release_task_to_owner(
    team: str,
    task: TaskItem,
    caller: str,
    message: str = "",
    respawn: bool = True,
    repo: str | None = None,
    runtime: RuntimeOrchestrator | None = None,
) -> dict[str, Any]:
    orchestrator = runtime or RuntimeOrchestrator(team=team, repo=repo)
    return orchestrator.release_to_owner(
        task,
        caller=caller,
        message=message,
        respawn=respawn,
    )


def execute_task_release(
    *,
    task_id: str,
    caller: str,
    request: TaskReleaseRequest,
    ctx: TaskReleaseContext,
) -> TaskReleaseResult:
    """Run the full task-release use case behind the CLI adapter."""
    from clawteam.team.tasks import TaskLockError

    existing = ctx.store.get(task_id)
    if not existing:
        raise KeyError(task_id)
    if not existing.owner:
        raise ValueError(f"Task '{task_id}' has no owner")

    task = ctx.store.update(
        task_id,
        status=TaskStatus.pending,
        caller=caller,
        force=request.force,
    )
    if not task:
        raise KeyError(task_id)

    try:
        release = ctx.runtime.release_to_owner(
            task,
            caller=caller,
            message=request.message,
            respawn=request.respawn,
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
    store: TaskStore | None = None,
    runtime: RuntimeOrchestrator | None = None,
) -> list[dict[str, Any]]:
    from clawteam.team.tasks import TaskStore

    store = store or TaskStore(team)
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
            runtime=runtime,
        )
        releases.append({"taskId": target.id, "owner": target.owner, **release})
    return releases
