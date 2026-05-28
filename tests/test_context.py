from __future__ import annotations

import json

from clawteam.workspace.context import _resolve_repo_path


def test_resolve_repo_path_uses_workspace_registry(isolated_data_dir):
    repo_root = isolated_data_dir / "demo-repo"
    repo_root.mkdir()
    registry_path = (
        isolated_data_dir
        / "workspaces"
        / "demo-team"
        / "workspace-registry.json"
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "team_name": "demo-team",
                "repo_root": str(repo_root),
                "workspaces": [],
            }
        ),
        encoding="utf-8",
    )

    assert _resolve_repo_path("demo-team") == str(repo_root)


def test_resolve_repo_path_prefers_explicit_repo(isolated_data_dir):
    registry_path = (
        isolated_data_dir
        / "workspaces"
        / "demo-team"
        / "workspace-registry.json"
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "team_name": "demo-team",
                "repo_root": "/tmp/registry-repo",
                "workspaces": [],
            }
        ),
        encoding="utf-8",
    )

    assert _resolve_repo_path("demo-team", "/tmp/explicit-repo") == "/tmp/explicit-repo"
