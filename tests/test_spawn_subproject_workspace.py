from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager


class FakeBackend:
    def __init__(self):
        self.calls: list[dict] = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return "Agent 'worker' spawned"

    def list_running(self):
        return []


class FakeWorkspaceInfo:
    def __init__(self, worktree_path: str, repo_root: str, branch_name: str = "clawteam/demo/worker"):
        self.worktree_path = worktree_path
        self.repo_root = repo_root
        self.branch_name = branch_name


class FakeWorkspaceManager:
    def __init__(self, info: FakeWorkspaceInfo):
        self.info = info

    def create_workspace(self, team_name: str, agent_name: str, agent_id: str):
        return self.info


def test_spawn_uses_subproject_cwd_inside_worktree(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")

    repo_root = tmp_path / "workspace"
    subproject = repo_root / "projects" / "openclaw-bet"
    subproject.mkdir(parents=True)

    worktree_root = tmp_path / "worktrees" / "demo" / "worker"
    (worktree_root / "projects" / "openclaw-bet").mkdir(parents=True)

    backend = FakeBackend()
    ws_info = FakeWorkspaceInfo(str(worktree_root), str(repo_root))
    ws_mgr = FakeWorkspaceManager(ws_info)

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr("clawteam.workspace.get_workspace_manager", lambda repo=None: ws_mgr)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "spawn",
            "tmux",
            "openclaw",
            "--team",
            "demo",
            "--agent-name",
            "worker",
            "--workspace",
            "--repo",
            str(subproject),
            "--task",
            "fix it",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path / "data")},
    )

    assert result.exit_code == 0
    assert backend.calls
    assert backend.calls[0]["cwd"] == str(worktree_root / "projects" / "openclaw-bet")
