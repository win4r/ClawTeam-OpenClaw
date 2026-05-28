"""Tests for clawteam.harness — phases, artifacts, contracts, orchestrator."""


from clawteam.harness.artifacts import ArtifactStore
from clawteam.harness.contracts import SprintContract, SuccessCriterion
from clawteam.harness.phases import (
    DISCUSS,
    EXECUTE,
    PLAN,
    VERIFY,
    ArtifactRequiredGate,
    HumanApprovalGate,
    PhaseRunner,
    PhaseState,
)
from clawteam.harness.roles import DEFAULT_ROLES, EVALUATOR, EXECUTOR, PLANNER


class TestPhaseState:
    def test_default_phases(self):
        state = PhaseState(team_name="t")
        assert state.current_phase == DISCUSS
        assert len(state.phases) == 5

    def test_persists_goal_and_cli(self):
        state = PhaseState(team_name="t", goal="build X", cli="codex", agent_count=5)
        assert state.goal == "build X"
        assert state.cli == "codex"
        assert state.agent_count == 5

    def test_phase_roles_default(self):
        state = PhaseState(team_name="t")
        assert state.phase_roles["discuss"] == "planner"
        assert state.phase_roles["execute"] == "executor"

    def test_serialization_roundtrip(self, tmp_path):
        state = PhaseState(team_name="test-team", goal="test goal")
        runner = PhaseRunner(state)
        path = runner.save(tmp_path)
        loaded = PhaseRunner.load(path)
        assert loaded.state.team_name == "test-team"
        assert loaded.state.goal == "test goal"
        assert loaded.state.harness_id == state.harness_id


class TestPhaseRunner:
    def test_advance_through_phases(self):
        state = PhaseState(team_name="t")
        runner = PhaseRunner(state)
        assert runner.advance() == PLAN
        assert runner.advance() == EXECUTE
        assert runner.advance() == VERIFY
        assert runner.advance() == "ship"
        assert runner.advance() is None

    def test_gate_blocks_advance(self):
        state = PhaseState(team_name="t")
        runner = PhaseRunner(state)
        runner.register_gate(DISCUSS, ArtifactRequiredGate(["spec.md"]))
        ok, reason = runner.can_advance()
        assert ok is False
        assert "spec.md" in reason
        assert runner.advance() is None

    def test_gate_passes_with_artifact(self):
        state = PhaseState(team_name="t")
        state.artifacts["spec.md"] = "/path/to/spec.md"
        runner = PhaseRunner(state)
        runner.register_gate(DISCUSS, ArtifactRequiredGate(["spec.md"]))
        assert runner.advance() == PLAN

    def test_human_approval_gate(self):
        state = PhaseState(team_name="t")
        runner = PhaseRunner(state)
        runner.register_gate(DISCUSS, HumanApprovalGate("discuss"))
        ok, reason = runner.can_advance()
        assert ok is False
        assert "approval" in reason.lower()

        # Approve
        state.artifacts["approval-discuss.json"] = "/path"
        ok, reason = runner.can_advance()
        assert ok is True

    def test_rollback(self):
        state = PhaseState(team_name="t")
        runner = PhaseRunner(state)
        runner.advance()  # plan
        runner.advance()  # execute
        assert runner.rollback(PLAN) == PLAN
        assert state.current_phase == PLAN

    def test_rollback_forward_fails(self):
        state = PhaseState(team_name="t")
        runner = PhaseRunner(state)
        assert runner.rollback(EXECUTE) is None

    def test_custom_phases(self):
        state = PhaseState(team_name="t", phases=["plan", "execute", "review", "deploy"])
        state.current_phase = "plan"
        runner = PhaseRunner(state)
        assert runner.advance() == "execute"
        assert runner.advance() == "review"
        assert runner.advance() == "deploy"

    def test_history_tracked(self):
        state = PhaseState(team_name="t")
        runner = PhaseRunner(state)
        runner.advance()
        assert len(state.phase_history) == 1
        assert state.phase_history[0]["phase"] == "discuss"


class TestArtifactStore:
    def test_write_and_read(self, tmp_path):
        store = ArtifactStore(tmp_path, "team1", "harness1")
        store.write("test.md", "hello world")
        assert store.read("test.md") == "hello world"
        assert store.exists("test.md")

    def test_read_missing(self, tmp_path):
        store = ArtifactStore(tmp_path, "team1", "harness1")
        assert store.read("missing.md") is None

    def test_list_artifacts(self, tmp_path):
        store = ArtifactStore(tmp_path, "team1", "harness1")
        store.write("spec.md", "spec content", {"type": "specification"})
        store.write("report.json", "{}")
        arts = store.list_artifacts()
        names = [a["name"] for a in arts]
        assert "spec.md" in names
        assert "report.json" in names

    def test_convenience_methods(self, tmp_path):
        store = ArtifactStore(tmp_path, "team1", "harness1")
        store.write_spec("my spec")
        store.write_sprint_contract("001", '{"title": "test"}')
        store.write_evaluation('{"passed": true}')
        store.write_ship_manifest('{"files": []}')
        assert store.exists("spec.md")
        assert store.exists("sprint-contract-001.json")
        assert store.exists("eval-report.json")
        assert store.exists("ship-manifest.json")


class TestSprintContract:
    def test_default_values(self):
        c = SprintContract(title="Test")
        assert c.status == "pending"
        assert c.wave == 1

    def test_with_criteria(self):
        c = SprintContract(
            title="Build login",
            success_criteria=[
                SuccessCriterion(description="Login form renders"),
                SuccessCriterion(description="Invalid password shows error"),
            ],
        )
        assert len(c.success_criteria) == 2
        assert c.success_criteria[0].verified is False


class TestAgentRoles:
    def test_all_roles_defined(self):
        assert PLANNER in DEFAULT_ROLES
        assert EXECUTOR in DEFAULT_ROLES
        assert EVALUATOR in DEFAULT_ROLES

    def test_planner_affinity(self):
        cfg = DEFAULT_ROLES[PLANNER]
        assert "discuss" in cfg.phase_affinity
        assert "plan" in cfg.phase_affinity


class TestPluginManager:
    def test_discover_empty(self):
        from clawteam.plugins.manager import PluginManager
        mgr = PluginManager()
        found = mgr.discover()
        assert isinstance(found, dict)

    def test_load_nonexistent_module(self):
        from clawteam.plugins.manager import PluginManager
        mgr = PluginManager()
        assert mgr.load_from_module("no.such.module") is None


class TestExitJournal:
    def test_write_and_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
        from clawteam.harness.exit_journal import FileExitJournal

        journal = FileExitJournal("test-team", "harness-1")
        journal.record_exit("agent-1", exit_code=0, abandoned_tasks=[])
        journal.record_exit("agent-2", exit_code=1, abandoned_tasks=["task-1"])

        entries = journal.read_new()
        assert len(entries) == 2
        assert entries[0]["agent_name"] == "agent-1"
        assert entries[1]["abandoned_tasks"] == ["task-1"]

    def test_read_new_incremental(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
        from clawteam.harness.exit_journal import FileExitJournal

        journal = FileExitJournal("test-team", "harness-1")
        journal.record_exit("a1")
        assert len(journal.read_new()) == 1
        assert len(journal.read_new()) == 0  # no new entries

        journal.record_exit("a2")
        assert len(journal.read_new()) == 1  # only the new one


class TestContractExecutor:
    def test_round_robin_assignment(self):
        from clawteam.harness.contract_executor import RoundRobinAssigner

        contracts = [
            SprintContract(title="A"),
            SprintContract(title="B"),
            SprintContract(title="C"),
        ]
        assigner = RoundRobinAssigner()
        mapping = assigner.assign(contracts, ["exec-1", "exec-2"])
        assert len(mapping["exec-1"]) == 2
        assert len(mapping["exec-2"]) == 1

    def test_create_tasks_from_contracts_assigns_owner_round_robin(self, tmp_path, monkeypatch):
        from clawteam.harness.contract_executor import ContractExecutor
        from clawteam.team.tasks import TaskStore

        monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

        class Orch:
            team_name = "demo"
            artifacts = ArtifactStore(tmp_path, "demo", "h1")

        orch = Orch()
        orch.artifacts.write_sprint_contract(
            "001",
            SprintContract(title="A", description="a", wave=1).model_dump_json(),
        )
        orch.artifacts.write_sprint_contract(
            "002",
            SprintContract(title="B", description="b", wave=1).model_dump_json(),
        )
        orch.artifacts.write_sprint_contract(
            "003",
            SprintContract(title="C", description="c", wave=2).model_dump_json(),
        )

        executor = ContractExecutor(orch)
        tasks = executor.create_tasks_from_contracts(agent_names=["exec-1", "exec-2"])

        assert [task.owner for task in tasks] == ["exec-1", "exec-2", "exec-1"]

        stored = TaskStore("demo").list_tasks()
        owners_by_subject = {task.subject: task.owner for task in stored}
        assert owners_by_subject == {"A": "exec-1", "B": "exec-2", "C": "exec-1"}
        metadata_by_subject = {task.subject: task.metadata for task in stored}
        assert metadata_by_subject["A"]["assigned_to"] == ["exec-1"]

    def test_create_tasks_from_contracts_prefers_contract_assignee(self, tmp_path, monkeypatch):
        from clawteam.harness.contract_executor import ContractExecutor

        monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

        class Orch:
            team_name = "demo"
            artifacts = ArtifactStore(tmp_path, "demo", "h1")

        orch = Orch()
        orch.artifacts.write_sprint_contract(
            "001",
            SprintContract(
                title="A", description="a", wave=1, assigned_to=["specialist"],
            ).model_dump_json(),
        )

        executor = ContractExecutor(orch)
        tasks = executor.create_tasks_from_contracts(agent_names=["exec-1", "exec-2"])

        assert len(tasks) == 1
        assert tasks[0].owner == "specialist"
        assert tasks[0].metadata["assigned_to"] == ["specialist"]


class TestContextRecovery:
    def test_build_recovery_prompt(self):
        from clawteam.harness.context_recovery import ContextRecovery

        recovery = ContextRecovery()
        prompt = recovery.build_recovery_prompt(
            agent_name="exec-1",
            team_name="test",
            role="executor",
            iteration=3,
            max_iterations=5,
        )
        assert "Iteration 3/5" in prompt

    def test_role_scoped(self):
        from clawteam.harness.context_recovery import ContextRecovery

        recovery = ContextRecovery()
        exec_prompt = recovery.build_recovery_prompt("a", "t", "executor", 1)
        eval_prompt = recovery.build_recovery_prompt("a", "t", "evaluator", 1)
        # Both should have iteration context
        assert "Iteration 1/5" in exec_prompt
        assert "Iteration 1/5" in eval_prompt


class TestHarnessPrompts:
    def test_system_prompt_includes_assignment_fallback(self):
        from clawteam.harness.prompts import build_harness_system_prompt

        prompt = build_harness_system_prompt("demo", "exec-1")
        assert "task list demo --owner exec-1" in prompt
        assert "task list demo`" in prompt
        assert "before declaring yourself idle" in prompt

    def test_wrapped_prompt_includes_assignment_fallback(self):
        from clawteam.harness.prompts import build_wrapped_prompt

        prompt = build_wrapped_prompt("exec-1", "Implement feature X", "demo")
        assert "task list demo --owner exec-1" in prompt
        assert "fall back to `clawteam task list demo`" in prompt


class TestRalphLoopPlugin:
    def test_plugin_instantiation(self):
        from clawteam.plugins.ralph_loop_plugin import RalphLoopPlugin

        plugin = RalphLoopPlugin(max_iterations=3)
        assert plugin.name == "ralph-loop"
        assert plugin.max_iterations == 3


class TestStrategies:
    def test_no_respawn_default(self):
        from clawteam.harness.conductor import NoRespawn

        strategy = NoRespawn()
        assert strategy.should_respawn("agent-1", "team-1") is False

    def test_event_type_registry(self):
        from dataclasses import dataclass

        from clawteam.events.bus import register_event_type, resolve_event_type
        from clawteam.events.types import HarnessEvent

        @dataclass
        class CustomEvent(HarnessEvent):
            custom_field: str = ""

        register_event_type(CustomEvent)
        assert resolve_event_type("CustomEvent") is CustomEvent
        assert resolve_event_type("WorkerExit") is not None
        assert resolve_event_type("NoSuchEvent") is None
