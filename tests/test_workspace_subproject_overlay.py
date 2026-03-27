from __future__ import annotations

from pathlib import Path

from clawteam.workspace.manager import WorkspaceManager


def test_workspace_overlays_subproject_files_into_worktree(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    subproject = repo_root / "projects" / "openclaw-bet"
    scripts = subproject / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "collect_team_context.ts").write_text("export const ok = true\n", encoding="utf-8")
    (scripts / "workflow_runner.ts").write_text("export const runner = true\n", encoding="utf-8")

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("clawteam.workspace.git.repo_root", lambda path: repo_root)
    monkeypatch.setattr("clawteam.workspace.git.current_branch", lambda repo: "main")
    monkeypatch.setattr("clawteam.workspace.git.create_worktree", lambda repo, worktree_path, branch, base_ref='HEAD': Path(worktree_path).mkdir(parents=True, exist_ok=True))

    ws = WorkspaceManager(subproject)
    info = ws.create_workspace("demo", "worker", "id123")

    overlaid = Path(info.worktree_path) / "projects" / "openclaw-bet" / "scripts" / "collect_team_context.ts"
    assert info.repo_subpath == "projects/openclaw-bet"
    assert overlaid.exists()
    assert overlaid.read_text(encoding="utf-8") == "export const ok = true\n"
