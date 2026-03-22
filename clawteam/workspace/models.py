"""Data models for workspace management."""

from __future__ import annotations

from pydantic import BaseModel


class WorkspaceInfo(BaseModel):
    """Information about a single agent workspace (git worktree)."""

    agent_name: str
    agent_id: str
    team_name: str
    branch_name: str        # "clawteam/{team}/{agent}"
    worktree_path: str      # "{data_dir}/workspaces/{team}/{agent}"
    repo_root: str
    repo_subpath: str = ""
    base_branch: str        # branch from which the worktree was created
    created_at: str


class WorkspaceRegistry(BaseModel):
    """Tracks all active workspaces for a team."""

    team_name: str
    repo_root: str
    workspaces: list[WorkspaceInfo] = []
