"""Team template loader — load TOML templates for one-command team launch."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, field_validator

# TOML support: built-in on 3.11+, conditional dependency on 3.10
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_AGENTS = 4  # Research-backed (Google/MIT arXiv:2512.08296)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

VALID_TIERS = {"strong", "balanced", "cheap"}
VALID_STRATEGIES = {"auto", "none"}


class RetryConfig(BaseModel):
    """Per-agent retry configuration with exponential backoff."""
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0


class AgentDef(BaseModel):
    name: str
    type: str = "general-purpose"
    task: str = ""
    command: list[str] | None = None
    task_type: str = "parallel"  # parallel | sequential | hybrid
    intent: str | None = None  # Auftragstaktik: what is the mission's purpose?
    end_state: str | None = None  # What does success look like?
    constraints: list[str] | None = None  # Boundaries the agent must respect
    retry: RetryConfig | None = None  # Retry with exponential backoff
    model: str | None = None  # Explicit model override for this agent
    model_tier: str | None = None  # "strong" | "balanced" | "cheap"

    @field_validator("model_tier")
    @classmethod
    def validate_tier(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_TIERS:
            raise ValueError(f"Invalid model_tier '{v}'. Must be one of: {VALID_TIERS}")
        return v


class TaskDef(BaseModel):
    subject: str
    description: str = ""
    owner: str = ""


class TemplateDef(BaseModel):
    name: str
    description: str = ""
    command: list[str] = ["openclaw"]
    backend: str = "tmux"
    model: str | None = None  # Template-level default model
    model_strategy: str | None = None  # "auto" | "none"
    leader: AgentDef
    agents: list[AgentDef] = []
    tasks: list[TaskDef] = []
    max_agents: int = DEFAULT_MAX_AGENTS  # Research-backed (arXiv:2512.08296)

    @field_validator("model_strategy")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STRATEGIES:
            raise ValueError(f"Invalid model_strategy '{v}'. Must be one of: {VALID_STRATEGIES}")
        return v


# ---------------------------------------------------------------------------
# Agent count warning
# ---------------------------------------------------------------------------

_MAX_AGENTS_WARNING = (
    "Warning: spawning agent #{count} exceeds recommended max of {max} agents per team. "
    "Research shows coordination overhead dominates beyond 3-4 agents "
    "(Google/MIT arXiv:2512.08296). Use --force to suppress."
)


def check_agent_count(current_count: int, max_agents: int) -> str | None:
    """Return a warning message if current_count exceeds max_agents, else None."""
    if current_count >= max_agents:
        return _MAX_AGENTS_WARNING.format(count=current_count + 1, max=max_agents)
    return None


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


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

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

    return TemplateDef(
        name=tmpl.get("name", path.stem),
        description=tmpl.get("description", ""),
        command=tmpl.get("command", ["openclaw"]),
        backend=tmpl.get("backend", "tmux"),
        model=tmpl.get("model"),
        model_strategy=tmpl.get("model_strategy"),
        leader=leader,
        agents=agents,
        tasks=tasks,
        max_agents=tmpl.get("max_agents", DEFAULT_MAX_AGENTS),
    )


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
