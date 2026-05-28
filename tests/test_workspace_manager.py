from __future__ import annotations

from pathlib import Path

from clawteam.workspace.manager import WorkspaceManager


def test_create_workspace_deletes_stale_branch_even_when_worktree_missing(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree_root = tmp_path / "data"
    worktree_root.mkdir()

    deleted: list[str] = []
    created: list[tuple[Path, str, str]] = []

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(worktree_root))
    monkeypatch.setattr("clawteam.workspace.git.repo_root", lambda path: repo_root)
    monkeypatch.setattr("clawteam.workspace.git.current_branch", lambda repo: "main")
    monkeypatch.setattr("clawteam.workspace.git.remove_worktree", lambda repo, path: None)
    monkeypatch.setattr(
        "clawteam.workspace.git.delete_branch",
        lambda repo, branch: deleted.append(branch),
    )
    monkeypatch.setattr(
        "clawteam.workspace.git.create_worktree",
        lambda repo, wt_path, branch, base_ref="HEAD": created.append((wt_path, branch, base_ref)),
    )

    manager = WorkspaceManager(repo_root)
    info = manager.create_workspace(team_name="demo", agent_name="alice", agent_id="agent-1")

    assert deleted == ["clawteam/demo/alice"]
    assert created == [(Path(info.worktree_path), "clawteam/demo/alice", "main")]
