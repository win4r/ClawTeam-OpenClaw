"""Team template loader — load TOML templates for one-command team launch."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel

# TOML support: built-in on 3.11+, conditional dependency on 3.10
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentDef(BaseModel):
    name: str
    type: str = "general-purpose"
    task: str = ""
    command: list[str] | None = None


class TaskDef(BaseModel):
    subject: str
    description: str = ""
    owner: str = ""
    stage: str = ""
    blocked_by: list[str] = []
    on_fail: list[str] = []
    message_type: str = ""
    required_sections: list[str] = []
    feature_scope_required: bool = False


class TemplateDef(BaseModel):
    name: str
    description: str = ""
    command: list[str] = ["openclaw"]
    backend: str = "tmux"
    topology_mode: str = "explicit"
    materialization_mode: str = "immediate"
    leader: AgentDef
    agents: list[AgentDef] = []
    tasks: list[TaskDef] = []


from .launch import (
    FeatureScope,
    LaunchBriefSections,
    LaunchExecutionResult,
    LaunchReferenceError,
    LaunchTaskBuildError,
    LaunchTaskInput,
    LaunchTemplateError,
    NormalizedLaunchBrief,
    PreparedTaskLaunchBrief,
    ScopeAuditWarning,
    ScopeTaskValidationError,
    TaskLaunchBriefView,
    find_scope_audit_warnings,
    find_scope_inventions,
    find_scope_tightening,
    inject_resolved_scope_context,
    normalize_launch_brief,
    parse_feature_scope_block,
    parse_launch_brief,
    read_feature_scope_metadata,
    read_launch_brief_metadata,
    read_task_launch_brief,
    render_resolved_scope_context,
    validate_scope_task_completion,
)
from .launch import build_launch_task_input as _build_launch_task_input
from .launch import execute_template_launch as _execute_template_launch
from .launch import prepare_task_launch_brief as _prepare_task_launch_brief
from .launch import render_task_brief as _render_task_brief


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BUILTIN_DIR = Path(__file__).parent
_USER_DIR = Path.home() / ".clawteam" / "templates"


# ---------------------------------------------------------------------------
# Variable substitution helper
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    """dict subclass that keeps unknown {placeholders} intact."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_task(task: str, **variables: str) -> str:
    """Replace {goal}, {team_name}, {agent_name} etc. in task text."""
    return task.format_map(_SafeDict(**variables))


def prepare_task_launch_brief(task: str, **variables: str) -> PreparedTaskLaunchBrief:
    return _prepare_task_launch_brief(task, render_task=render_task, **variables)


def render_task_brief(task: str, **variables: str) -> str:
    return _render_task_brief(task, render_task=render_task, **variables)


def build_launch_task_input(
    task_def: TaskDef,
    *,
    goal: str,
    team_name: str,
    created_task_ids: dict[str, str],
    materialization_mode: str = "immediate",
) -> LaunchTaskInput:
    return _build_launch_task_input(
        task_def,
        goal=goal,
        team_name=team_name,
        created_task_ids=created_task_ids,
        render_task=render_task,
        materialization_mode=materialization_mode,
    )


def execute_template_launch(
    task_store,
    tasks: list[TaskDef],
    *,
    goal: str,
    team_name: str,
    materialization_mode: str = "immediate",
    template_name: str | None = None,
) -> LaunchExecutionResult:
    return _execute_template_launch(
        task_store,
        tasks,
        goal=goal,
        team_name=team_name,
        render_task=render_task,
        materialization_mode=materialization_mode,
        template_name=template_name,
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def resolve_template_topology(tmpl: TemplateDef) -> TemplateDef:
    """Resolve any template-level topology defaults before launch.

    Currently supported:
    - explicit: use blocked_by/on_fail exactly as authored
    - delivery-default: require staged tasks and auto-fill standard delivery edges
    - post-scope-only: launch creates only scope/root tasks; no auto-downstream materialization
    """
    if tmpl.topology_mode in ("explicit", "post-scope-only"):
        return tmpl

    if tmpl.topology_mode != "delivery-default":
        raise ValueError(f"Unsupported template topology_mode: {tmpl.topology_mode}")

    by_stage: dict[str, list[TaskDef]] = {}
    for task in tmpl.tasks:
        stage = task.stage.strip().lower()
        if not stage:
            raise ValueError(
                f"Template '{tmpl.name}' uses topology_mode=delivery-default but task '{task.subject}' is missing stage"
            )
        by_stage.setdefault(stage, []).append(task)

    required = ["scope", "setup", "implement", "qa", "review", "deliver"]
    missing = [stage for stage in required if not by_stage.get(stage)]
    if missing:
        raise ValueError(
            f"Template '{tmpl.name}' uses topology_mode=delivery-default but is missing required stages: {', '.join(missing)}"
        )

    scope_subjects = [task.subject for task in by_stage["scope"]]
    setup_subjects = [task.subject for task in by_stage["setup"]]
    implement_subjects = [task.subject for task in by_stage["implement"]]
    qa_subjects = [task.subject for task in by_stage["qa"]]
    review_subjects = [task.subject for task in by_stage["review"]]

    resolved_tasks: list[TaskDef] = []
    for task in tmpl.tasks:
        stage = task.stage.strip().lower()
        updates: dict[str, object] = {}
        if stage == "setup" and not task.blocked_by:
            updates["blocked_by"] = list(scope_subjects)
        elif stage == "implement" and not task.blocked_by:
            updates["blocked_by"] = list(setup_subjects)
        elif stage == "qa":
            if not task.blocked_by:
                updates["blocked_by"] = list(implement_subjects)
            if not task.on_fail:
                updates["on_fail"] = list(implement_subjects)
        elif stage == "review":
            if not task.blocked_by:
                updates["blocked_by"] = list(qa_subjects)
            if not task.on_fail:
                updates["on_fail"] = list(implement_subjects)
        elif stage == "deliver" and not task.blocked_by:
            updates["blocked_by"] = list(review_subjects)

        resolved_tasks.append(task.model_copy(update=updates) if updates else task)

    return tmpl.model_copy(update={"tasks": resolved_tasks})


def _parse_toml(path: Path) -> TemplateDef:
    """Parse a TOML template file into a TemplateDef."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    tmpl = raw.get("template", {})

    # Parse leader
    leader_data = tmpl.get("leader", {})
    leader = AgentDef(**leader_data)

    # Parse agents
    agents = [AgentDef(**a) for a in tmpl.get("agents", [])]

    # Parse tasks
    tasks = [TaskDef(**t) for t in tmpl.get("tasks", [])]

    parsed = TemplateDef(
        name=tmpl.get("name", path.stem),
        description=tmpl.get("description", ""),
        command=tmpl.get("command", ["openclaw"]),
        backend=tmpl.get("backend", "tmux"),
        topology_mode=tmpl.get("topology_mode", "explicit"),
        materialization_mode=tmpl.get("materialization_mode", "immediate"),
        leader=leader,
        agents=agents,
        tasks=tasks,
    )
    return resolve_template_topology(parsed)


def load_template(name: str) -> TemplateDef:
    """Load a template by name.

    Search order: user templates (~/.clawteam/templates/) first,
    then built-in templates (clawteam/templates/).
    """
    filename = f"{name}.toml"

    # User templates take priority
    user_path = _USER_DIR / filename
    if user_path.is_file():
        return _parse_toml(user_path)

    # Built-in templates
    builtin_path = _BUILTIN_DIR / filename
    if builtin_path.is_file():
        return _parse_toml(builtin_path)

    raise FileNotFoundError(
        f"Template '{name}' not found. "
        f"Searched: {_USER_DIR}, {_BUILTIN_DIR}"
    )


def list_templates() -> list[dict[str, str]]:
    """List all available templates (user + builtin, user overrides builtin)."""
    seen: dict[str, dict[str, str]] = {}

    # Built-in templates first (can be overridden)
    if _BUILTIN_DIR.is_dir():
        for p in sorted(_BUILTIN_DIR.glob("*.toml")):
            try:
                tmpl = _parse_toml(p)
                seen[tmpl.name] = {
                    "name": tmpl.name,
                    "description": tmpl.description,
                    "source": "builtin",
                }
            except Exception:
                continue

    # User templates override
    if _USER_DIR.is_dir():
        for p in sorted(_USER_DIR.glob("*.toml")):
            try:
                tmpl = _parse_toml(p)
                seen[tmpl.name] = {
                    "name": tmpl.name,
                    "description": tmpl.description,
                    "source": "user",
                }
            except Exception:
                continue

    return list(seen.values())
