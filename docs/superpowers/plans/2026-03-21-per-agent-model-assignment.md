# Per-Agent Model Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow ClawTeam templates and CLI to assign different models to different agents, passing `--model` to OpenClaw at spawn time.

**Architecture:** Add optional `model`/`model_tier` fields to templates, a `resolve_model()` function that implements a 7-level priority chain, and `--model` injection into spawn backends. All fields are optional — backward compatible.

**Tech Stack:** Python 3.10+, Pydantic v2, typer, pytest, tomllib

**Spec:** `docs/superpowers/specs/2026-03-21-per-agent-model-assignment-design.md`

---

## File Structure

| File | Role | Action |
|------|------|--------|
| `clawteam/model_resolution.py` | Model resolution logic, tier defaults, auto role map | Create |
| `clawteam/templates/__init__.py` | Template schema + TOML parser | Modify |
| `clawteam/team/models.py` | TeamMember runtime model | Modify |
| `clawteam/identity.py` | AgentIdentity env var support | Modify |
| `clawteam/config.py` | Global config with default_model | Modify |
| `clawteam/spawn/base.py` | SpawnBackend base class | Modify |
| `clawteam/spawn/tmux_backend.py` | Tmux spawn with --model injection | Modify |
| `clawteam/spawn/subprocess_backend.py` | Subprocess spawn with --model injection | Modify |
| `clawteam/cli/commands.py` | CLI spawn/launch with --model flag | Modify |
| `tests/test_model_resolution.py` | Tests for resolve_model() | Create |
| `tests/test_templates.py` | Additional template model field tests | Modify |
| `tests/test_models.py` | TeamMember model_name field test | Modify |
| `tests/test_config.py` | Config default_model tests | Modify |
| `tests/test_spawn_backends.py` | Backend --model injection tests | Modify |

---

### Task 1: Model Resolution Function

**Files:**
- Create: `clawteam/model_resolution.py`
- Create: `tests/test_model_resolution.py`

- [ ] **Step 1: Write failing tests for resolve_model()**

```python
# tests/test_model_resolution.py
"""Tests for clawteam.model_resolution — 7-level priority chain."""

import pytest

from clawteam.model_resolution import (
    AUTO_ROLE_MAP,
    DEFAULT_TIERS,
    resolve_model,
)


class TestResolvePriority:
    """Each test verifies one priority level wins over all lower levels."""

    def test_cli_model_wins_over_everything(self):
        result = resolve_model(
            cli_model="gpt-5.4",
            agent_model="opus",
            agent_model_tier="strong",
            template_model_strategy="auto",
            template_model="sonnet-4.6",
            config_default_model="haiku-4.5",
            agent_type="leader",
        )
        assert result == "gpt-5.4"

    def test_agent_model_wins_over_tier(self):
        result = resolve_model(
            cli_model=None,
            agent_model="codex",
            agent_model_tier="cheap",
            template_model_strategy="auto",
            template_model="sonnet-4.6",
            config_default_model="haiku-4.5",
            agent_type="general-purpose",
        )
        assert result == "codex"

    def test_agent_tier_wins_over_strategy(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier="cheap",
            template_model_strategy="auto",
            template_model="sonnet-4.6",
            config_default_model="",
            agent_type="leader",
        )
        assert result == DEFAULT_TIERS["cheap"]

    def test_auto_strategy_leader_gets_strong(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy="auto",
            template_model="sonnet-4.6",
            config_default_model="",
            agent_type="lead-reviewer",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_auto_strategy_worker_gets_balanced(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy="auto",
            template_model="sonnet-4.6",
            config_default_model="",
            agent_type="data-collector",
        )
        assert result == DEFAULT_TIERS["balanced"]

    def test_template_model_wins_over_config(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy=None,
            template_model="sonnet-4.6",
            config_default_model="haiku-4.5",
            agent_type="general-purpose",
        )
        assert result == "sonnet-4.6"

    def test_config_default_used_as_fallback(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy=None,
            template_model=None,
            config_default_model="haiku-4.5",
            agent_type="general-purpose",
        )
        assert result == "haiku-4.5"

    def test_returns_none_when_nothing_set(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy=None,
            template_model=None,
            config_default_model="",
            agent_type="general-purpose",
        )
        assert result is None


class TestAutoStrategy:
    """Test substring matching for auto role assignment."""

    def test_reviewer_matches_strong(self):
        result = resolve_model(
            cli_model=None, agent_model=None, agent_model_tier=None,
            template_model_strategy="auto", template_model=None,
            config_default_model="", agent_type="security-reviewer",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_architect_matches_strong(self):
        result = resolve_model(
            cli_model=None, agent_model=None, agent_model_tier=None,
            template_model_strategy="auto", template_model=None,
            config_default_model="", agent_type="system-architect",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_manager_matches_strong(self):
        result = resolve_model(
            cli_model=None, agent_model=None, agent_model_tier=None,
            template_model_strategy="auto", template_model=None,
            config_default_model="", agent_type="data-manager",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_none_strategy_falls_through(self):
        result = resolve_model(
            cli_model=None, agent_model=None, agent_model_tier=None,
            template_model_strategy="none", template_model="sonnet-4.6",
            config_default_model="", agent_type="leader",
        )
        assert result == "sonnet-4.6"


class TestTierOverrides:
    def test_custom_tier_mapping(self):
        result = resolve_model(
            cli_model=None, agent_model=None, agent_model_tier="strong",
            template_model_strategy=None, template_model=None,
            config_default_model="", agent_type="general-purpose",
            tier_overrides={"strong": "gpt-5.4"},
        )
        assert result == "gpt-5.4"

    def test_override_merges_with_defaults(self):
        """Overriding 'strong' should not affect 'balanced'."""
        result = resolve_model(
            cli_model=None, agent_model=None, agent_model_tier="balanced",
            template_model_strategy=None, template_model=None,
            config_default_model="", agent_type="general-purpose",
            tier_overrides={"strong": "gpt-5.4"},
        )
        assert result == DEFAULT_TIERS["balanced"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_model_resolution.py -v`
Expected: ModuleNotFoundError — `clawteam.model_resolution` does not exist yet.

- [ ] **Step 3: Implement resolve_model()**

```python
# clawteam/model_resolution.py
"""Model resolution for per-agent model assignment.

Implements a 7-level priority chain:
1. CLI --model flag
2. Agent-level model (from template TOML)
3. Agent-level model_tier mapped via tier table
4. Template model_strategy auto-assignment by role
5. Template-level default model
6. Config default_model
7. None (let backend use its own default)
"""

from __future__ import annotations

DEFAULT_TIERS: dict[str, str] = {
    "strong": "opus",
    "balanced": "sonnet-4.6",
    "cheap": "haiku-4.5",
}

AUTO_ROLE_MAP: dict[str, str] = {
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

    # 3. Agent model tier (validated at parse time, guard kept for safety)
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

    # 7. No model — let backend use its own default
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_model_resolution.py -v`
Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/model_resolution.py tests/test_model_resolution.py
git commit -m "feat: add resolve_model() with 7-level priority chain"
```

---

### Task 2: Template Schema — Add model fields to AgentDef and TemplateDef

**Files:**
- Modify: `clawteam/templates/__init__.py:24-44` (AgentDef, TemplateDef)
- Modify: `clawteam/templates/__init__.py:75-100` (_parse_toml)
- Modify: `tests/test_templates.py`

- [ ] **Step 1: Write failing tests for new template fields**

Add to `tests/test_templates.py`:

```python
from pydantic import ValidationError

# Add to existing TestModels class:

class TestModelFields:
    def test_agent_def_model_defaults_none(self):
        a = AgentDef(name="worker")
        assert a.model is None
        assert a.model_tier is None

    def test_agent_def_with_model(self):
        a = AgentDef(name="worker", model="opus")
        assert a.model == "opus"

    def test_agent_def_with_valid_tier(self):
        a = AgentDef(name="worker", model_tier="strong")
        assert a.model_tier == "strong"

    def test_agent_def_invalid_tier_raises(self):
        with pytest.raises(ValidationError, match="model_tier"):
            AgentDef(name="worker", model_tier="ultra")

    def test_template_def_model_defaults(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="test", leader=leader)
        assert t.model is None
        assert t.model_strategy is None

    def test_template_def_with_model(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="test", leader=leader, model="sonnet-4.6")
        assert t.model == "sonnet-4.6"

    def test_template_def_valid_strategy(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="test", leader=leader, model_strategy="auto")
        assert t.model_strategy == "auto"

    def test_template_def_none_strategy(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="test", leader=leader, model_strategy="none")
        assert t.model_strategy == "none"

    def test_template_def_invalid_strategy_raises(self):
        leader = AgentDef(name="lead")
        with pytest.raises(ValidationError, match="model_strategy"):
            TemplateDef(name="test", leader=leader, model_strategy="magic")


class TestParseTomlWithModel:
    def test_toml_with_agent_model(self, tmp_path, monkeypatch):
        toml_content = """\
[template]
name = "model-test"
model = "sonnet-4.6"

[template.leader]
name = "boss"
model = "opus"

[[template.agents]]
name = "worker"
model_tier = "cheap"
"""
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "model-test.toml").write_text(toml_content)

        import clawteam.templates as tmod
        monkeypatch.setattr(tmod, "_USER_DIR", tpl_dir)

        tmpl = load_template("model-test")
        assert tmpl.model == "sonnet-4.6"
        assert tmpl.leader.model == "opus"
        assert tmpl.agents[0].model_tier == "cheap"

    def test_toml_with_strategy(self, tmp_path, monkeypatch):
        toml_content = """\
[template]
name = "strategy-test"
model_strategy = "auto"

[template.leader]
name = "boss"
type = "leader"
"""
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "strategy-test.toml").write_text(toml_content)

        import clawteam.templates as tmod
        monkeypatch.setattr(tmod, "_USER_DIR", tpl_dir)

        tmpl = load_template("strategy-test")
        assert tmpl.model_strategy == "auto"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_templates.py::TestModelFields tests/test_templates.py::TestParseTomlWithModel -v`
Expected: FAIL — `AgentDef` has no `model` attribute, `TemplateDef` has no `model_strategy`.

- [ ] **Step 3: Add model fields to AgentDef and TemplateDef**

Edit `clawteam/templates/__init__.py`. Replace the Pydantic models section (lines 24-44):

```python
from pydantic import BaseModel, field_validator

VALID_TIERS = {"strong", "balanced", "cheap"}
VALID_STRATEGIES = {"auto", "none"}


class AgentDef(BaseModel):
    name: str
    type: str = "general-purpose"
    task: str = ""
    command: list[str] | None = None
    model: str | None = None
    model_tier: str | None = None

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
    model: str | None = None
    model_strategy: str | None = None
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

- [ ] **Step 4: Update _parse_toml() to forward new fields**

Edit `clawteam/templates/__init__.py` `_parse_toml()` (lines 92-100). The `AgentDef(**leader_data)` and `AgentDef(**a)` calls already pass through all TOML keys via `**`, so `model` and `model_tier` on agents are automatically forwarded. Only the `TemplateDef` constructor needs updating:

```python
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
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_templates.py -v`
Expected: All tests PASS (existing + new).

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/templates/__init__.py tests/test_templates.py
git commit -m "feat: add model and model_tier fields to template schema"
```

---

### Task 3: Runtime Models — TeamMember and AgentIdentity

**Files:**
- Modify: `clawteam/team/models.py:58-68` (TeamMember)
- Modify: `clawteam/identity.py:26-74` (AgentIdentity)
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_models.py`:

```python
# Add to TestTeamMember class:

    def test_model_name_default(self):
        m = TeamMember(name="worker")
        assert m.model_name == ""

    def test_model_name_set(self):
        m = TeamMember(name="worker", model_name="opus")
        assert m.model_name == "opus"

    def test_model_name_alias(self):
        data = {"name": "worker", "modelName": "opus"}
        m = TeamMember.model_validate(data)
        assert m.model_name == "opus"
        dumped = json.loads(m.model_dump_json(by_alias=True))
        assert dumped["modelName"] == "opus"
```

Add a new test file `tests/test_identity_model.py`:

```python
"""Tests for AgentIdentity model field."""

from clawteam.identity import AgentIdentity


class TestAgentIdentityModel:
    def test_model_defaults_none(self):
        ident = AgentIdentity()
        assert ident.model is None

    def test_model_from_env(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_MODEL", "opus")
        ident = AgentIdentity.from_env()
        assert ident.model == "opus"

    def test_model_from_openclaw_env(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_MODEL", raising=False)
        monkeypatch.setenv("OPENCLAW_MODEL", "sonnet-4.6")
        ident = AgentIdentity.from_env()
        assert ident.model == "sonnet-4.6"

    def test_model_not_set(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_MODEL", raising=False)
        monkeypatch.delenv("OPENCLAW_MODEL", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_MODEL", raising=False)
        ident = AgentIdentity.from_env()
        assert ident.model is None

    def test_to_env_includes_model(self):
        ident = AgentIdentity(model="opus")
        env = ident.to_env()
        assert env["CLAWTEAM_MODEL"] == "opus"

    def test_to_env_omits_model_when_none(self):
        ident = AgentIdentity()
        env = ident.to_env()
        assert "CLAWTEAM_MODEL" not in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_models.py::TestTeamMember::test_model_name_default tests/test_identity_model.py -v`
Expected: FAIL — `model_name` not a field on TeamMember, `model` not a field on AgentIdentity.

- [ ] **Step 3: Add model_name to TeamMember**

Edit `clawteam/team/models.py` line 67, add after `joined_at`:

```python
    model_name: str = Field(default="", alias="modelName")
```

- [ ] **Step 4: Add model to AgentIdentity**

Edit `clawteam/identity.py`:

Add `model` field to `AgentIdentity` dataclass (after line 36):
```python
    model: str | None = None
```

Update `from_env()` (lines 43-59) — add to the `cls(...)` call:
```python
        model=_env("CLAWTEAM_MODEL", "CLAUDE_CODE_MODEL") or None,
```

Update `to_env()` (after line 73) — add:
```python
        if self.model:
            env["CLAWTEAM_MODEL"] = self.model
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_models.py tests/test_identity_model.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/team/models.py clawteam/identity.py tests/test_models.py tests/test_identity_model.py
git commit -m "feat: add model field to TeamMember and AgentIdentity"
```

---

### Task 4: Config — Add default_model and model_tiers

**Files:**
- Modify: `clawteam/config.py:12-19` (ClawTeamConfig)
- Modify: `clawteam/config.py:53-61` (env_map in get_effective)
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
# Add to TestClawTeamConfig class:

    def test_default_model_empty(self):
        cfg = ClawTeamConfig()
        assert cfg.default_model == ""

    def test_model_tiers_empty(self):
        cfg = ClawTeamConfig()
        assert cfg.model_tiers == {}

    def test_custom_model_config(self):
        cfg = ClawTeamConfig(default_model="opus", model_tiers={"strong": "gpt-5.4"})
        assert cfg.default_model == "opus"
        assert cfg.model_tiers["strong"] == "gpt-5.4"

# Add to TestLoadSaveConfig class:

    def test_model_config_roundtrip(self):
        cfg = ClawTeamConfig(default_model="opus", model_tiers={"strong": "gpt-5.4"})
        save_config(cfg)
        loaded = load_config()
        assert loaded.default_model == "opus"
        assert loaded.model_tiers == {"strong": "gpt-5.4"}

# Add to TestGetEffective class:

    def test_default_model_from_env(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_DEFAULT_MODEL", "opus")
        val, source = get_effective("default_model")
        assert val == "opus"
        assert source == "env"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_config.py::TestClawTeamConfig::test_default_model_empty tests/test_config.py::TestGetEffective::test_default_model_from_env -v`
Expected: FAIL — `default_model` not a field.

- [ ] **Step 3: Add fields to ClawTeamConfig**

Edit `clawteam/config.py` line 19, add after `skip_permissions`:

```python
    default_model: str = ""
    model_tiers: dict[str, str] = {}
```

- [ ] **Step 4: Add to env_map in get_effective()**

Edit `clawteam/config.py` line 60, add after `"skip_permissions"` entry:

```python
        "default_model": "CLAWTEAM_DEFAULT_MODEL",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_config.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/config.py tests/test_config.py
git commit -m "feat: add default_model and model_tiers to config"
```

---

### Task 5: Spawn Backend — Add model parameter and --model injection

**Files:**
- Modify: `clawteam/spawn/base.py:11-23`
- Modify: `clawteam/spawn/tmux_backend.py:27-38,84-96`
- Modify: `clawteam/spawn/subprocess_backend.py:20-31,63-86`
- Modify: `tests/test_spawn_backends.py`

- [ ] **Step 1: Write failing tests for --model injection**

Add to `tests/test_spawn_backends.py`:

```python
def test_tmux_backend_passes_model_to_openclaw(monkeypatch, tmp_path):
    """When model is provided and command is openclaw, --model should appear in the tmux command."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    original_which = __import__("shutil").which
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend.shutil.which",
        lambda name, path=None: "/opt/homebrew/bin/tmux" if name == "tmux" else original_which(name),
    )
    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/openclaw" if name == "openclaw" else original_which(name),
    )
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=False,
        model="opus",
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "--model opus" in full_cmd or "--model 'opus'" in full_cmd


def test_tmux_backend_no_model_flag_when_none(monkeypatch, tmp_path):
    """When model is None, --model should NOT appear."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    original_which = __import__("shutil").which
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend.shutil.which",
        lambda name, path=None: "/opt/homebrew/bin/tmux" if name == "tmux" else original_which(name),
    )
    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/openclaw" if name == "openclaw" else original_which(name),
    )
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=False,
        model=None,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "--model" not in full_cmd


def test_subprocess_backend_passes_model_to_openclaw(monkeypatch, tmp_path):
    """Subprocess backend should include --model in the openclaw command."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=False,
        model="opus",
    )

    assert "--model" in captured["cmd"]
    assert "opus" in captured["cmd"]
    assert captured["env"]["CLAWTEAM_MODEL"] == "opus"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_spawn_backends.py::test_tmux_backend_passes_model_to_openclaw tests/test_spawn_backends.py::test_subprocess_backend_passes_model_to_openclaw -v`
Expected: TypeError — `spawn()` got unexpected keyword argument `model`.

- [ ] **Step 3: Add model param to SpawnBackend base class**

Edit `clawteam/spawn/base.py` line 22, add before `) -> str:`:

```python
        model: str | None = None,
```

- [ ] **Step 4: Add model to TmuxBackend.spawn()**

Edit `clawteam/spawn/tmux_backend.py`:

1. Add `model: str | None = None,` to the `spawn()` signature (after `skip_permissions` param).

2. In the OpenClaw command construction block (around line 84-96), after each `final_command.extend(["--session", session_key])` or `final_command = [...]` line and before the `if prompt:` check, add:
```python
        if model:
            final_command.extend(["--model", model])
```

3. Also inject `--model` for Claude Code commands (spec section 11). In the `_is_claude_command()` branch where `skip_permissions` is handled, add after the `--dangerously-skip-permissions` logic:
```python
        if model and _is_claude_command(normalized_command):
            final_command.extend(["--model", model])
```

4. In the env_vars dict (around line 44-62), add after existing env vars:
```python
        if model:
            env_vars["CLAWTEAM_MODEL"] = model
```

- [ ] **Step 5: Add model to SubprocessBackend.spawn()**

Edit `clawteam/spawn/subprocess_backend.py`:

1. Add `model: str | None = None,` to the `spawn()` signature.

2. In the OpenClaw command block (around line 78-84), refactor the single `.extend()` call into two calls so `--model` is injected before `--session-id`:
```python
    elif _is_openclaw_command(normalized_command):
        if "agent" not in final_command and "tui" not in final_command:
            final_command.insert(1, "agent")
        session_key = f"clawteam-{team_name}-{agent_name}"
        if model:
            final_command.extend(["--model", model])
        final_command.extend(["--session-id", session_key, "--message", prompt])
```

3. In spawn_env setup, add:
```python
        if model:
            spawn_env["CLAWTEAM_MODEL"] = model
```

- [ ] **Step 6: Run all spawn backend tests**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_spawn_backends.py -v`
Expected: All PASS (existing + new).

- [ ] **Step 7: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/spawn/base.py clawteam/spawn/tmux_backend.py clawteam/spawn/subprocess_backend.py tests/test_spawn_backends.py
git commit -m "feat: add --model injection to spawn backends"
```

---

### Task 6: CLI — Add --model flag to spawn and launch commands

**Files:**
- Modify: `clawteam/cli/commands.py:1606-1617` (spawn_agent)
- Modify: `clawteam/cli/commands.py:2145-2153` (launch_team)
- Modify: `clawteam/cli/commands.py:2231-2281` (launch_team spawn loop)

This task modifies the CLI wiring. The `commands.py` file is 2311 lines, so read the exact sections before editing.

- [ ] **Step 1: Read the current spawn_agent and launch_team functions**

Run: Read `clawteam/cli/commands.py` lines 1600-1750 and 2140-2310 to get exact current code.

- [ ] **Step 2: Add --model to spawn_agent**

Add to `spawn_agent()` function signature (after `resume` param):

```python
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model alias or ID (passed to backend via --model)"),
```

In the `be.spawn()` call within `spawn_agent()`, add `model=model` parameter.

- [ ] **Step 3: Add --model and --model-strategy to launch_team**

Add to `launch_team()` function signature:

```python
    model_override: Optional[str] = typer.Option(None, "--model", help="Override model for ALL agents"),
    model_strategy_override: Optional[str] = typer.Option(None, "--model-strategy", help="Model strategy: auto | none"),
```

- [ ] **Step 4: Wire resolve_model() into launch_team spawn loop**

Import at top of file:
```python
from clawteam.config import load_config
from clawteam.model_resolution import resolve_model
```

Near the top of `launch_team()`, load config:
```python
    cfg = load_config()
```

In the agent spawning loop (around line 2231), before `be.spawn()`, add model resolution. Note: CLI `--model-strategy` override takes precedence over template value:

```python
    resolved_model = resolve_model(
        cli_model=model_override,
        agent_model=agent.model,
        agent_model_tier=agent.model_tier,
        template_model_strategy=model_strategy_override or tmpl.model_strategy,
        template_model=tmpl.model,
        config_default_model=cfg.default_model,
        agent_type=agent.type,
        tier_overrides=cfg.model_tiers or None,
    )
```

Add `model=resolved_model` to the `be.spawn()` call.

Also add a log warning when model is resolved but command may not support it:
```python
    if resolved_model and not (_is_openclaw_command(a_cmd) or _is_claude_command(a_cmd)):
        console.print(f"[yellow]Warning: model '{resolved_model}' resolved for {agent.name} but command {a_cmd[0]} may not support --model[/yellow]")
```

- [ ] **Step 5: Run existing CLI tests to verify no regression**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_spawn_cli.py -v`
Expected: All existing tests PASS.

- [ ] **Step 6: Run full test suite**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/cli/commands.py
git commit -m "feat: add --model flag to spawn and launch CLI commands"
```

---

### Task 7: Update Built-in Templates with Example Model Assignments

**Files:**
- Modify: `clawteam/templates/code-review.toml`
- Modify: `clawteam/templates/hedge-fund.toml`
- Modify: `clawteam/templates/research-paper.toml`
- Modify: `clawteam/templates/strategy-room.toml`

- [ ] **Step 1: Read current templates**

Read all 4 template files to understand their current structure.

- [ ] **Step 2: Add model_strategy = "auto" to all templates**

Add `model_strategy = "auto"` to the `[template]` section of each template. This enables automatic model assignment by role (leaders get `strong`, workers get `balanced`) without requiring explicit per-agent model fields.

Example for `code-review.toml`:
```toml
[template]
name = "code-review"
description = "..."
command = ["openclaw"]
backend = "tmux"
model_strategy = "auto"
```

Do the same for all 4 templates.

- [ ] **Step 3: Run template tests to verify no breakage**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest tests/test_templates.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add clawteam/templates/*.toml
git commit -m "feat: add model_strategy=auto to all built-in templates"
```

---

### Task 8: Full Integration Test and Backward Compatibility Verification

**Files:**
- All modified files from Tasks 1-7

- [ ] **Step 1: Run the full test suite**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m pytest -v`
Expected: All tests PASS.

- [ ] **Step 2: Verify backward compatibility — existing templates parse without model fields**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -c "from clawteam.templates import load_template; t = load_template('hedge-fund'); print(f'OK: {t.name}, model={t.model}, strategy={t.model_strategy}')"`
Expected: Prints template name with model_strategy=auto (from Task 7).

- [ ] **Step 3: Verify resolve_model returns None when nothing set**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -c "from clawteam.model_resolution import resolve_model; r = resolve_model(None,None,None,None,None,'','general-purpose'); print(f'Result: {r}'); assert r is None"`
Expected: `Result: None`

- [ ] **Step 4: Verify CLI help shows --model flag**

Run: `cd ~/Projects/ClawTeam-OpenClaw && python -m clawteam spawn --help | grep -A1 model`
Expected: Shows `--model` / `-m` option with help text.

- [ ] **Step 5: Commit any remaining fixes**

If any test failures were found and fixed, commit them:

```bash
cd ~/Projects/ClawTeam-OpenClaw
git add -A
git commit -m "fix: address integration test findings"
```

- [ ] **Step 6: Final commit — tag the feature**

```bash
cd ~/Projects/ClawTeam-OpenClaw
git log --oneline -8  # verify all commits look correct
```
