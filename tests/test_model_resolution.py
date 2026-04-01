"""Tests for per-agent model resolution (7-level priority chain)."""

from __future__ import annotations

import json

import pytest

from clawteam.model_resolution import DEFAULT_TIERS, resolve_model


class TestResolveModel:
    """Test the 7-level model resolution priority chain."""

    def test_cli_override_wins(self):
        """Level 1: CLI --model overrides everything."""
        result = resolve_model(
            cli_model="gpt-4o",
            agent_model="opus",
            agent_model_tier="strong",
            template_model_strategy="auto",
            template_model="sonnet",
            config_default_model="haiku",
            agent_type="leader",
        )
        assert result == "gpt-4o"

    def test_agent_model_explicit(self):
        """Level 2: Agent-level model when no CLI override."""
        result = resolve_model(
            cli_model=None,
            agent_model="opus",
            agent_model_tier=None,
            template_model_strategy=None,
            template_model=None,
            config_default_model="",
            agent_type="general-purpose",
        )
        assert result == "opus"

    def test_agent_model_tier_strong(self):
        """Level 3: Agent model_tier maps to tier table."""
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier="strong",
            template_model_strategy=None,
            template_model=None,
            config_default_model="",
            agent_type="general-purpose",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_agent_model_tier_cheap(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier="cheap",
            template_model_strategy=None,
            template_model=None,
            config_default_model="",
            agent_type="general-purpose",
        )
        assert result == DEFAULT_TIERS["cheap"]

    def test_agent_model_tier_invalid_skipped(self):
        """Invalid tier is silently skipped (falls through to next level)."""
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier="invalid",
            template_model_strategy=None,
            template_model=None,
            config_default_model="fallback",
            agent_type="general-purpose",
        )
        assert result == "fallback"

    def test_auto_strategy_leader(self):
        """Level 4: Auto strategy maps leader/reviewer/architect to 'strong'."""
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy="auto",
            template_model=None,
            config_default_model="",
            agent_type="leader",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_auto_strategy_reviewer(self):
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy="auto",
            template_model=None,
            config_default_model="",
            agent_type="code-reviewer",
        )
        assert result == DEFAULT_TIERS["strong"]

    def test_auto_strategy_generic_falls_to_balanced(self):
        """Auto strategy for unknown role type defaults to 'balanced'."""
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy="auto",
            template_model=None,
            config_default_model="",
            agent_type="coder",
        )
        assert result == DEFAULT_TIERS["balanced"]

    def test_template_model(self):
        """Level 5: Template default model."""
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier=None,
            template_model_strategy=None,
            template_model="sonnet-4.6",
            config_default_model="",
            agent_type="general-purpose",
        )
        assert result == "sonnet-4.6"

    def test_config_default_model(self):
        """Level 6: Config default_model."""
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

    def test_no_model_returns_none(self):
        """Level 7: No model specified at any level → None."""
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

    def test_tier_overrides(self):
        """Custom tier overrides replace defaults."""
        result = resolve_model(
            cli_model=None,
            agent_model=None,
            agent_model_tier="strong",
            template_model_strategy=None,
            template_model=None,
            config_default_model="",
            agent_type="general-purpose",
            tier_overrides={"strong": "my-custom-model"},
        )
        assert result == "my-custom-model"

    def test_priority_agent_model_over_tier(self):
        """Agent model (level 2) beats tier (level 3)."""
        result = resolve_model(
            cli_model=None,
            agent_model="explicit-model",
            agent_model_tier="strong",
            template_model_strategy=None,
            template_model=None,
            config_default_model="",
            agent_type="general-purpose",
        )
        assert result == "explicit-model"


class TestTemplateModelFields:
    """Test model fields on AgentDef and TemplateDef."""

    def test_agent_def_model_field(self):
        from clawteam.templates import AgentDef
        agent = AgentDef(name="test", model="opus")
        assert agent.model == "opus"

    def test_agent_def_model_tier_field(self):
        from clawteam.templates import AgentDef
        agent = AgentDef(name="test", model_tier="strong")
        assert agent.model_tier == "strong"

    def test_agent_def_model_tier_invalid(self):
        from clawteam.templates import AgentDef
        with pytest.raises(ValueError, match="Invalid model_tier"):
            AgentDef(name="test", model_tier="invalid")

    def test_agent_def_no_model(self):
        from clawteam.templates import AgentDef
        agent = AgentDef(name="test")
        assert agent.model is None
        assert agent.model_tier is None

    def test_template_def_model_fields(self):
        from clawteam.templates import AgentDef, TemplateDef
        tmpl = TemplateDef(
            name="test",
            model="sonnet-4.6",
            model_strategy="auto",
            leader=AgentDef(name="lead"),
        )
        assert tmpl.model == "sonnet-4.6"
        assert tmpl.model_strategy == "auto"

    def test_template_def_model_strategy_invalid(self):
        from clawteam.templates import AgentDef, TemplateDef
        with pytest.raises(ValueError, match="Invalid model_strategy"):
            TemplateDef(
                name="test",
                model_strategy="invalid",
                leader=AgentDef(name="lead"),
            )

    def test_template_toml_with_model(self, tmp_path):
        """TOML template with model fields parses correctly."""
        from clawteam.templates import _parse_toml
        toml_content = """
[template]
name = "test-model"
model = "sonnet-4.6"
model_strategy = "auto"

[template.leader]
name = "lead"
model = "opus"
model_tier = "strong"

[[template.agents]]
name = "worker"
model_tier = "cheap"
"""
        toml_file = tmp_path / "test-model.toml"
        toml_file.write_text(toml_content)
        tmpl = _parse_toml(toml_file)
        assert tmpl.model == "sonnet-4.6"
        assert tmpl.model_strategy == "auto"
        assert tmpl.leader.model == "opus"
        assert tmpl.leader.model_tier == "strong"
        assert tmpl.agents[0].model_tier == "cheap"
        assert tmpl.agents[0].model is None


class TestConfigModelFields:
    """Test model fields on ClawTeamConfig."""

    def test_config_default_model(self):
        from clawteam.config import ClawTeamConfig
        cfg = ClawTeamConfig(default_model="opus")
        assert cfg.default_model == "opus"

    def test_config_model_tiers(self):
        from clawteam.config import ClawTeamConfig
        cfg = ClawTeamConfig(model_tiers={"strong": "my-opus"})
        assert cfg.model_tiers["strong"] == "my-opus"

    def test_config_defaults_empty(self):
        from clawteam.config import ClawTeamConfig
        cfg = ClawTeamConfig()
        assert cfg.default_model == ""
        assert cfg.model_tiers == {}


class TestIdentityModelField:
    """Test model field on AgentIdentity."""

    def test_identity_model_field(self):
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity(model="opus")
        assert identity.model == "opus"

    def test_identity_model_from_env(self, monkeypatch):
        from clawteam.identity import AgentIdentity
        monkeypatch.setenv("CLAWTEAM_MODEL", "sonnet-4.6")
        identity = AgentIdentity.from_env()
        assert identity.model == "sonnet-4.6"

    def test_identity_model_to_env(self):
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity(model="opus")
        env = identity.to_env()
        assert env["CLAWTEAM_MODEL"] == "opus"

    def test_identity_no_model(self):
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity()
        assert identity.model is None
        env = identity.to_env()
        assert "CLAWTEAM_MODEL" not in env


class TestTeamMemberModelField:
    """Test model_name field on TeamMember."""

    def test_member_model_name(self):
        from clawteam.team.models import TeamMember
        member = TeamMember(name="test", model_name="opus")
        assert member.model_name == "opus"

    def test_member_model_name_default(self):
        from clawteam.team.models import TeamMember
        member = TeamMember(name="test")
        assert member.model_name == ""

    def test_member_model_name_serialization(self):
        from clawteam.team.models import TeamMember
        member = TeamMember(name="test", model_name="opus")
        data = json.loads(member.model_dump_json(by_alias=True))
        assert data["modelName"] == "opus"
