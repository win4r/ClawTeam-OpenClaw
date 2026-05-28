"""Tests for clawteam.templates — loading, parsing, and variable substitution."""

import pytest

from clawteam.platform_compat import default_spawn_backend
from clawteam.templates import (
    AgentDef,
    TaskDef,
    TemplateDef,
    _SafeDict,
    check_agent_count,
    list_templates,
    load_template,
    render_task,
)


class TestRenderTask:
    def test_basic_substitution(self):
        result = render_task("Analyze {goal} for {team_name}", goal="AAPL", team_name="alpha")
        assert result == "Analyze AAPL for alpha"

    def test_unknown_placeholders_kept(self):
        """Variables we don't provide should stay as {placeholder}."""
        result = render_task("Hello {name}, team is {team_name}", name="bob")
        assert result == "Hello bob, team is {team_name}"

    def test_no_variables(self):
        result = render_task("plain text with no placeholders")
        assert result == "plain text with no placeholders"

    def test_empty_string(self):
        assert render_task("") == ""

    def test_multiple_same_variable(self):
        result = render_task("{x} and {x}", x="foo")
        assert result == "foo and foo"


class TestSafeDict:
    def test_missing_key_returns_placeholder(self):
        d = _SafeDict(a="1")
        assert d["a"] == "1"
        # missing key wrapped back into braces
        assert "{missing}".format_map(d) == "{missing}"


class TestModels:
    def test_agent_def_defaults(self):
        a = AgentDef(name="worker")
        assert a.type == "general-purpose"
        assert a.task == ""
        assert a.command is None
        assert a.task_type == "parallel"
        assert a.intent is None
        assert a.end_state is None
        assert a.constraints is None

    def test_agent_def_task_type(self):
        a = AgentDef(name="worker", task_type="sequential")
        assert a.task_type == "sequential"

    def test_agent_def_intent_fields(self):
        a = AgentDef(
            name="analyst",
            intent="Analyze stock fundamentals",
            end_state="Buy/sell/hold recommendation",
            constraints=["No leverage", "Max 10% position"],
        )
        assert a.intent == "Analyze stock fundamentals"
        assert len(a.constraints) == 2

    def test_task_def(self):
        t = TaskDef(subject="Build feature", description="details", owner="alice")
        assert t.subject == "Build feature"

    def test_template_def_defaults(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="my-tmpl", leader=leader)
        assert t.description == ""
        assert t.command == ["openclaw"]
        assert t.backend == default_spawn_backend()
        assert t.agents == []
        assert t.tasks == []
        assert t.max_agents == 4

    def test_template_def_custom_max_agents(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="my-tmpl", leader=leader, max_agents=8)
        assert t.max_agents == 8


class TestLoadBuiltinTemplate:
    def test_load_hedge_fund(self):
        tmpl = load_template("hedge-fund")
        assert tmpl.name == "hedge-fund"
        assert tmpl.leader.name == "portfolio-manager"
        assert len(tmpl.agents) > 0
        assert len(tmpl.tasks) > 0

    def test_leader_type(self):
        tmpl = load_template("hedge-fund")
        assert tmpl.leader.type == "portfolio-manager"

    def test_agents_have_tasks(self):
        tmpl = load_template("hedge-fund")
        for agent in tmpl.agents:
            assert agent.task != "", f"Agent '{agent.name}' has no task text"

    def test_task_owners_match_agents(self):
        tmpl = load_template("hedge-fund")
        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        for task in tmpl.tasks:
            if task.owner:
                assert task.owner in agent_names, f"Task owner '{task.owner}' not in agents"

    def test_load_strategy_room(self):
        tmpl = load_template("strategy-room")
        assert tmpl.name == "strategy-room"
        assert tmpl.leader.name == "strategy-lead"
        assert len(tmpl.agents) == 4
        assert len(tmpl.tasks) == 5

    def test_load_software_dev(self):
        tmpl = load_template("software-dev")
        assert tmpl.name == "software-dev"
        assert tmpl.leader.name == "tech-lead"
        assert len(tmpl.agents) == 4
        assert len(tmpl.tasks) == 5

    def test_software_dev_task_owners_match_agents(self):
        tmpl = load_template("software-dev")
        agent_names = {tmpl.leader.name} | {agent.name for agent in tmpl.agents}
        for task in tmpl.tasks:
            if task.owner:
                assert task.owner in agent_names

    def test_strategy_room_agent_names(self):
        tmpl = load_template("strategy-room")
        names = {agent.name for agent in tmpl.agents}
        assert names == {
            "systems-analyst",
            "delivery-planner",
            "risk-mapper",
            "decision-editor",
        }

    def test_strategy_room_task_owners_match_agents(self):
        tmpl = load_template("strategy-room")
        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        for task in tmpl.tasks:
            if task.owner:
                assert task.owner in agent_names, f"Task owner '{task.owner}' not in agents"

    def test_strategy_room_specialists_route_to_decision_editor(self):
        tmpl = load_template("strategy-room")
        for agent in tmpl.agents:
            if agent.name == "decision-editor":
                continue
            assert "decision-editor" in agent.task
            assert "strategy-lead" not in agent.task

    def test_strategy_room_decision_editor_routes_to_strategy_lead(self):
        tmpl = load_template("strategy-room")
        decision_editor = next(agent for agent in tmpl.agents if agent.name == "decision-editor")
        assert "strategy-lead" in decision_editor.task
        assert "Do not recommend the final path yourself" in decision_editor.task

    def test_strategy_room_leader_waits_for_decision_editor_memo(self):
        tmpl = load_template("strategy-room")
        assert "Wait for the decision-editor's strategy memo" in tmpl.leader.task
        assert "supporting specialist outputs" not in tmpl.leader.task


class TestLoadTemplateNotFound:
    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_template("this-does-not-exist-anywhere")


class TestUserTemplateOverride:
    def test_user_template_takes_priority(self, tmp_path, monkeypatch):
        """User templates in ~/.clawteam/templates/ override builtins."""
        user_tpl_dir = tmp_path / ".clawteam" / "templates"
        user_tpl_dir.mkdir(parents=True)

        toml_content = """\
[template]
name = "custom"
description = "User override"

[template.leader]
name = "my-leader"
type = "custom-leader"
"""
        (user_tpl_dir / "custom.toml").write_text(toml_content)

        # patch the module-level _USER_DIR
        import clawteam.templates as tmod

        monkeypatch.setattr(tmod, "_USER_DIR", user_tpl_dir)

        tmpl = load_template("custom")
        assert tmpl.name == "custom"
        assert tmpl.leader.name == "my-leader"
        assert tmpl.description == "User override"


class TestListTemplates:
    def test_list_includes_builtin(self):
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "hedge-fund" in names
        assert "strategy-room" in names
        assert "software-dev" in names

    def test_list_entry_format(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "source" in t
            assert t["source"] in ("builtin", "user")


class TestCheckAgentCount:
    """Tests for max-agent warning (research-backed: arXiv:2512.08296)."""

    def test_under_limit_no_warning(self):
        assert check_agent_count(2, max_agents=4) is None

    def test_at_limit_warns(self):
        warning = check_agent_count(4, max_agents=4)
        assert warning is not None
        assert "exceeds recommended max" in warning

    def test_over_limit_warns(self):
        warning = check_agent_count(6, max_agents=4)
        assert warning is not None
        assert "#7" in warning

    def test_custom_max(self):
        assert check_agent_count(7, max_agents=8) is None
        assert check_agent_count(8, max_agents=8) is not None

    def test_warning_contains_research_ref(self):
        warning = check_agent_count(4, max_agents=4)
        assert "arXiv:2512.08296" in warning
