# Per-Agent Model Assignment for OpenClaw Teams

**Date:** 2026-03-21
**Status:** Draft
**Issue:** https://github.com/win4r/ClawTeam-OpenClaw/issues/1

## Problem

When all spawned agents use OpenClaw as the backend, there is no way to assign different models to different agent roles without creating multiple OpenClaw profiles or wrapper scripts. This adds friction and makes templates less portable.

## Solution

Add per-agent model selection at the ClawTeam layer, passed to OpenClaw via a new `--model` CLI flag. Models can be specified explicitly per agent, per template, via cost tiers, or via an automatic role-based strategy.

## Approach

**Approach B** (selected over two alternatives):
- **A (agent profile mapping)** was rejected — requires manual OpenClaw agent profile setup, not portable.
- **B (add --model flag to OpenClaw + plumb through ClawTeam)** — selected. Clean, portable, model is first-class.
- **C (dynamic config mutation)** was rejected — fragile, race conditions, hacky.

## Design

### 1. Data Model

#### Template Schema (`templates/__init__.py`)

`AgentDef` gains two optional fields:

```python
VALID_TIERS = {"strong", "balanced", "cheap"}

class AgentDef(BaseModel):
    name: str
    type: str = "general-purpose"
    task: str = ""
    command: list[str] | None = None
    model: str | None = None          # alias or full model ID
    model_tier: str | None = None     # "strong" / "balanced" / "cheap"

    @field_validator("model_tier")
    @classmethod
    def validate_tier(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_TIERS:
            raise ValueError(f"Invalid model_tier '{v}'. Must be one of: {VALID_TIERS}")
        return v
```

`TemplateDef` gains two optional fields:

```python
VALID_STRATEGIES = {"auto", "none"}

class TemplateDef(BaseModel):
    name: str
    description: str = ""
    command: list[str] = ["openclaw"]
    backend: str = "tmux"
    model: str | None = None          # default model for all agents
    model_strategy: str | None = None # "auto" | "none" (None = field not set)
    leader: AgentDef
    agents: list[AgentDef] = []
    tasks: list[TaskDef] = []

    @field_validator("model_strategy")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STRATEGIES:
            raise ValueError(f"Invalid model_strategy '{v}'. Must be one of: {VALID_STRATEGIES}")
        return v
```

**Validation:** Both `model_tier` and `model_strategy` are validated at parse time. Invalid values raise immediately rather than silently falling through to a lower priority level.

**Note on `_parse_toml()`:** The existing parser manually extracts fields from the TOML dict. It must be updated to also extract and forward `model`, `model_tier`, `model_strategy` to the Pydantic constructors. This is not automatic.

#### Runtime Models

`TeamMember` (`team/models.py`) gains:

```python
model_name: str = Field(default="", alias="modelName")
```

`AgentIdentity` (`identity.py`) gains a `model` field. Since `AgentIdentity` is a `@dataclass` (not Pydantic), both `from_env()` and `to_env()` must be updated:

```python
@dataclass
class AgentIdentity:
    ...existing fields...
    model: str | None = None

@classmethod
def from_env(cls) -> "AgentIdentity":
    return cls(
        ...existing fields...
        model=_env("CLAWTEAM_MODEL", "CLAUDE_CODE_MODEL") or None,
    )

def to_env(self) -> dict[str, str]:
    env = {...existing vars...}
    if self.model:
        env["CLAWTEAM_MODEL"] = self.model
    return env
```

### 2. Model Resolution Order

Highest priority wins:

1. CLI `--model` flag (escape hatch)
2. `agent.model` in template TOML (explicit per-agent)
3. `agent.model_tier` mapped via tier table
4. `template.model_strategy` auto-assignment by role
5. `template.model` (template-wide default)
6. `config.default_model` (global default)
7. OpenClaw's own configured default (no `--model` flag passed)

### 3. Model Tiers

Built-in tier mapping (overridable in config):

| Tier | Default Alias |
|------|---------------|
| `strong` | `opus` |
| `balanced` | `sonnet-4.6` |
| `cheap` | `haiku-4.5` |

These map to OpenClaw model aliases already configured by the user.

### 4. Auto Strategy

When `model_strategy = "auto"` on the template:

- Agent types containing `leader`, `reviewer`, `architect`, `manager` → `strong`
- All other agent types → `balanced`

When `model_strategy = "none"`, automatic role-based assignment is disabled; resolution falls through to the template default model or config default.

The auto strategy only applies when the agent has no explicit `model` or `model_tier` set.

**Precedence when both `model` and `model_tier` are set on the same agent:** `model` wins (priority 2 > priority 3). Setting both is allowed but redundant — `model` always takes precedence.

**Substring matching:** Role detection uses substring matching (e.g., `"data-manager"` matches `"manager"` → `strong`). This is intentional — agent types are descriptive strings and compound names like `"lead-reviewer"` should match `"leader"` and `"reviewer"`.

### 5. Template TOML Format

Explicit per-agent:

```toml
[template]
name = "code-review"
command = ["openclaw"]
model = "sonnet-4.6"           # default for all agents

[template.leader]
name = "lead-reviewer"
model = "opus"                  # override

[[template.agents]]
name = "security-reviewer"
model = "codex"                 # override

[[template.agents]]
name = "style-checker"
# inherits template default "sonnet-4.6"
```

Using auto strategy:

```toml
[template]
name = "hedge-fund"
command = ["openclaw"]
model_strategy = "auto"

[template.leader]
name = "portfolio-manager"
# auto → strong → opus

[[template.agents]]
name = "quant-analyst"
model_tier = "strong"          # explicit tier override

[[template.agents]]
name = "data-collector"
# auto → balanced → sonnet-4.6
```

### 6. CLI Changes

#### `spawn` command

Add `--model` option:

```python
def spawn_agent(
    ...existing args...
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Model alias or full ID (passed to OpenClaw via --model)"
    ),
):
```

#### `launch` command

Add `--model` and `--model-strategy` options:

```python
def launch_team(
    ...existing args...
    model_override: Optional[str] = typer.Option(
        None, "--model",
        help="Override model for ALL agents (ignores template models)"
    ),
    model_strategy: Optional[str] = typer.Option(
        None, "--model-strategy",
        help="Model strategy: auto | none"
    ),
):
```

CLI `--model` overrides all template-level model settings.

### 7. Spawn Backend Changes

#### Base class (`spawn/base.py`)

Add `model` parameter:

```python
@abstractmethod
def spawn(
    self,
    command: list[str],
    agent_name: str,
    agent_id: str,
    agent_type: str,
    team_name: str,
    prompt: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    skip_permissions: bool = False,
    model: str | None = None,         # NEW
) -> str:
```

#### Tmux backend (`spawn/tmux_backend.py`)

Insert `--model` into the OpenClaw command construction:

```python
if _is_openclaw_command(normalized_command):
    session_key = f"clawteam-{team_name}-{agent_name}"
    if final_command[0].endswith("openclaw") and len(final_command) == 1:
        final_command = [final_command[0], "tui", "--session", session_key]
        if model:
            final_command.extend(["--model", model])
        if prompt:
            final_command.extend(["--message", prompt])
    elif "tui" in final_command:
        final_command.extend(["--session", session_key])
        if model:
            final_command.extend(["--model", model])
        if prompt:
            final_command.extend(["--message", prompt])
    elif "agent" in final_command:
        if model:
            final_command.extend(["--model", model])
        if prompt:
            final_command.extend(["--message", prompt])
```

#### Subprocess backend (`spawn/subprocess_backend.py`)

The subprocess backend constructs OpenClaw commands differently (uses `--session-id`, auto-inserts `agent` subcommand). The `--model` injection follows its specific code path:

```python
elif _is_openclaw_command(normalized_command):
    # OpenClaw agent mode
    if "agent" not in final_command and "tui" not in final_command:
        final_command.insert(1, "agent")
    session_key = f"clawteam-{team_name}-{agent_name}"
    if model:
        final_command.extend(["--model", model])
    final_command.extend(["--session-id", session_key, "--message", prompt])
```

#### Environment variable propagation

Both backends add to env_vars:

```python
if model:
    env_vars["CLAWTEAM_MODEL"] = model
```

**Purpose of `CLAWTEAM_MODEL`:** Allows spawned agents to introspect their assigned model (e.g., for logging, cost tracking, or self-identification in team status). It is read by `AgentIdentity` but does not affect model selection — that is already determined before spawn.

### 8. Config Changes (`config.py`)

```python
class ClawTeamConfig(BaseModel):
    ...existing fields...
    default_model: str = ""
    model_tiers: dict[str, str] = {}  # override tier→alias mapping
```

Environment variable map addition:

```python
"default_model": "CLAWTEAM_DEFAULT_MODEL",
```

### 9. Model Resolution Function

New function in `clawteam/model_resolution.py` (new file — named to avoid collision with existing `clawteam/team/models.py`):

```python
DEFAULT_TIERS = {
    "strong": "opus",
    "balanced": "sonnet-4.6",
    "cheap": "haiku-4.5",
}

AUTO_ROLE_MAP = {
    "leader": "strong",
    "reviewer": "strong",
    "architect": "strong",
    "manager": "strong",
}

def resolve_model(
    cli_model: str | None,
    agent_model: str | None,
    agent_model_tier: str | None,
    template_model_strategy: str | None,
    template_model: str | None,
    config_default_model: str,
    agent_type: str,
    tier_overrides: dict[str, str] | None = None,
) -> str | None:
    """Resolve the effective model for an agent. Returns None if no model specified."""
    tiers = {**DEFAULT_TIERS, **(tier_overrides or {})}

    # 1. CLI override
    if cli_model:
        return cli_model

    # 2. Explicit agent model
    if agent_model:
        return agent_model

    # 3. Agent model tier
    if agent_model_tier and agent_model_tier in tiers:
        return tiers[agent_model_tier]

    # 4. Auto strategy
    if template_model_strategy == "auto":
        for keyword, tier in AUTO_ROLE_MAP.items():
            if keyword in agent_type.lower():
                return tiers[tier]
        return tiers["balanced"]

    # 5. Template default
    if template_model:
        return template_model

    # 6. Config default
    if config_default_model:
        return config_default_model

    # 7. No model — let OpenClaw use its own default
    return None
```

### 10. OpenClaw-Side Change (Separate PR)

Add `--model` flag to `openclaw tui` and `openclaw agent` CLI commands:

- Accepts an alias (e.g., `opus`) or full model ID (e.g., `anthropic/claude-opus-4-6`)
- Overrides the agent's configured model for that session only
- Does not persist to config
- Falls back to the agent's configured model if not provided
- Resolves aliases via the existing alias table in `openclaw.json`

This is a small, self-contained change in the OpenClaw CLI layer.

**Dependency ordering:** The OpenClaw `--model` PR must be merged and available before the ClawTeam feature is usable. If ClawTeam passes `--model` to an older OpenClaw that doesn't support it, the command will fail. To handle this gracefully, ClawTeam should log a warning if the resolved model is non-None but the backend command is not known to support `--model`.

### 11. Scope: Non-OpenClaw Backends

This feature is **primarily scoped to OpenClaw**. When `command = ["claude"]` or `command = ["codex"]`:

- Claude Code already supports `--model` — ClawTeam can inject it for `_is_claude_command()` as well.
- Codex CLI model selection mechanism should be checked; if it supports `--model`, inject similarly.
- If a backend does not support `--model`, the resolved model string is still set in `CLAWTEAM_MODEL` env var for introspection, but no CLI flag is injected. A debug log message is emitted.

### 12. `launch_team` Wiring Detail

The core integration point is inside `launch_team`'s agent spawning loop. For each agent:

```python
for agent in all_agents:
    resolved = resolve_model(
        cli_model=model_override,           # from --model CLI flag
        agent_model=agent.model,            # from template TOML
        agent_model_tier=agent.model_tier,  # from template TOML
        template_model_strategy=tmpl.model_strategy or model_strategy,
        template_model=tmpl.model,          # template-level default
        config_default_model=cfg.default_model,
        agent_type=agent.type,
        tier_overrides=cfg.model_tiers or None,
    )

    result = be.spawn(
        command=a_cmd,
        agent_name=agent.name,
        agent_id=a_id,
        agent_type=agent.type,
        team_name=t_name,
        prompt=prompt,
        cwd=cwd,
        skip_permissions=_skip,
        model=resolved,                     # NEW parameter
    )
```

`resolve_model()` is called once per agent, producing a potentially different model for each based on their individual `model`/`model_tier` settings and their type.

## Files Changed

| File | Change | Size |
|------|--------|------|
| `clawteam/templates/__init__.py` | Add `model`, `model_tier` to `AgentDef` with validators; `model`, `model_strategy` to `TemplateDef` with validators; update `_parse_toml()` to forward new fields | S |
| `clawteam/model_resolution.py` | New file: `resolve_model()` function, tier defaults, auto role map | S |
| `clawteam/team/models.py` | Add `model_name` field to `TeamMember` | XS |
| `clawteam/identity.py` | Add `model` field to `AgentIdentity`, read from `CLAWTEAM_MODEL` | XS |
| `clawteam/config.py` | Add `default_model`, `model_tiers` to `ClawTeamConfig` | XS |
| `clawteam/cli/commands.py` | Add `--model` to `spawn_agent` and `launch_team`; call `resolve_model()` | M |
| `clawteam/spawn/base.py` | Add `model` param to `spawn()` signature | XS |
| `clawteam/spawn/tmux_backend.py` | Pass `--model` to OpenClaw; propagate `CLAWTEAM_MODEL` env var | S |
| `clawteam/spawn/subprocess_backend.py` | Same as tmux backend | S |
| `clawteam/spawn/prompt.py` | Include model info in agent prompt (optional) | XS |
| `clawteam/templates/*.toml` | Add example model assignments to all 4 templates | S |
| **OpenClaw repo (separate PR)** | Add `--model` flag to `tui` and `agent` commands | S |

## Backward Compatibility

All new fields are optional with `None` or empty defaults. Existing templates and CLI invocations continue to work unchanged. When no model is specified anywhere in the chain, no `--model` flag is passed to OpenClaw, preserving current behavior.

## Testing

- Unit tests for `resolve_model()` covering all 7 priority levels
- Unit tests for TOML parsing with new fields
- Integration test: `clawteam spawn --model opus` passes `--model opus` to OpenClaw
- Integration test: `clawteam launch code-review` with model-annotated template spawns agents with correct models
- Verify backward compatibility: existing templates without model fields work unchanged
