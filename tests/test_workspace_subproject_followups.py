from __future__ import annotations

from pathlib import Path

from clawteam.cli import commands
from clawteam.workspace.manager import WorkspaceManager


class FakeWorkspaceInfo:
    def __init__(self, worktree_path: str, repo_root: str, repo_subpath: str, branch_name: str = "clawteam/demo/worker"):
        self.worktree_path = worktree_path
        self.repo_root = repo_root
        self.repo_subpath = repo_subpath
        self.branch_name = branch_name


def test_workspace_cwd_uses_recorded_repo_subpath_without_repo_flag(tmp_path):
    worktree_root = tmp_path / "worktrees" / "demo" / "worker"
    info = FakeWorkspaceInfo(str(worktree_root), str(tmp_path / "repo"), "projects/openclaw-bet")
    cwd = commands._workspace_cwd_from_info(None, info)
    assert cwd == str(worktree_root / "projects" / "openclaw-bet")


def test_workspace_overlay_skips_large_ignored_dirs(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    subproject = repo_root / "projects" / "openclaw-bet"
    (subproject / "node_modules" / "leftpad").mkdir(parents=True)
    (subproject / "node_modules" / "leftpad" / "index.js").write_text("module.exports = 1\n", encoding="utf-8")
    (subproject / "scripts").mkdir(parents=True)
    (subproject / "scripts" / "collect_team_context.ts").write_text("ok\n", encoding="utf-8")
    (subproject / ".env").write_text("SECRET=1\n", encoding="utf-8")

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("clawteam.workspace.git.repo_root", lambda path: repo_root)
    monkeypatch.setattr("clawteam.workspace.git.current_branch", lambda repo: "main")
    monkeypatch.setattr("clawteam.workspace.git.create_worktree", lambda repo, worktree_path, branch, base_ref='HEAD': Path(worktree_path).mkdir(parents=True, exist_ok=True))

    ws = WorkspaceManager(subproject)
    info = ws.create_workspace("demo", "worker", "id123")

    worktree_root = Path(info.worktree_path) / "projects" / "openclaw-bet"
    assert (worktree_root / "scripts" / "collect_team_context.ts").exists()
    assert not (worktree_root / "node_modules" / "leftpad" / "index.js").exists()
    assert not (worktree_root / ".env").exists()


def test_workspace_overlay_skips_symlink_files(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    subproject = repo_root / "projects" / "openclaw-bet"
    scripts = subproject / "scripts"
    scripts.mkdir(parents=True)
    secret = tmp_path / "host-secret.txt"
    secret.write_text("top-secret\n", encoding="utf-8")
    (scripts / "cert").symlink_to(secret)
    (scripts / "collect_team_context.ts").write_text("ok\n", encoding="utf-8")

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("clawteam.workspace.git.repo_root", lambda path: repo_root)
    monkeypatch.setattr("clawteam.workspace.git.current_branch", lambda repo: "main")
    monkeypatch.setattr("clawteam.workspace.git.create_worktree", lambda repo, worktree_path, branch, base_ref='HEAD': Path(worktree_path).mkdir(parents=True, exist_ok=True))

    ws = WorkspaceManager(subproject)
    info = ws.create_workspace("demo", "worker", "id123")

    worktree_root = Path(info.worktree_path) / "projects" / "openclaw-bet" / "scripts"
    assert (worktree_root / "collect_team_context.ts").exists()
    assert not (worktree_root / "cert").exists()
