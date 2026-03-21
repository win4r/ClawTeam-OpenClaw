"""Tests for clawteam.templates — loading, parsing, and variable substitution."""

import pytest

from clawteam.templates import (
    AgentDef,
    TaskDef,
    TemplateDef,
    _SafeDict,
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

    def test_task_def(self):
        t = TaskDef(subject="Build feature", description="details", owner="alice")
        assert t.subject == "Build feature"

    def test_task_def_blocked_by(self):
        t = TaskDef(subject="Build feature", blocked_by=["Setup"])
        assert t.blocked_by == ["Setup"]

    def test_task_def_on_fail(self):
        t = TaskDef(subject="Run QA", on_fail=["Implement"])
        assert t.on_fail == ["Implement"]

    def test_template_def_defaults(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="my-tmpl", leader=leader)
        assert t.description == ""
        assert t.command == ["openclaw"]
        assert t.backend == "tmux"
        assert t.agents == []
        assert t.tasks == []


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

    def test_five_step_delivery_parallel_structure(self):
        tmpl = load_template("five-step-delivery")
        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        assert {"config1", "dev1", "dev2", "qa1", "qa2", "review1"}.issubset(agent_names)

        by_subject = {task.subject: task for task in tmpl.tasks}
        assert by_subject["Implement backend/data changes with real validation"].blocked_by == [
            "Prepare repo, branch, env, and runnable baseline"
        ]
        assert by_subject["Implement frontend/UI changes with real validation"].blocked_by == [
            "Prepare repo, branch, env, and runnable baseline"
        ]
        assert by_subject["Run main-flow QA on the real change"].blocked_by == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Run edge-case and regression QA on the real change"].blocked_by == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Review code quality, maintainability, and delivery readiness"].blocked_by == [
            "Run main-flow QA on the real change",
            "Run edge-case and regression QA on the real change",
        ]
        assert by_subject["Run main-flow QA on the real change"].on_fail == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Run edge-case and regression QA on the real change"].on_fail == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Review code quality, maintainability, and delivery readiness"].on_fail == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]


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

    def test_list_entry_format(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "source" in t
            assert t["source"] in ("builtin", "user")
