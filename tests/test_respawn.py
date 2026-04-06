"""Tests for clawteam.spawn.respawn module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clawteam.spawn.registry import AgentHealth, HealthState
from clawteam.spawn.respawn import MAX_RESPAWN_ATTEMPTS, respawn_agent

# Patch targets: since respawn_agent uses lazy imports (from X import Y inside
# the function body), we must patch the *source* modules so the fresh local
# bindings pick up the mocks.
_PATCH_RECORD = "clawteam.spawn.registry.record_outcome"
_PATCH_GET_INFO = "clawteam.spawn.registry.get_agent_info"
_PATCH_TM = "clawteam.team.manager.TeamManager"
_PATCH_BACKEND = "clawteam.spawn.get_backend"
_PATCH_SWR = "clawteam.spawn.spawn_with_retry"


@pytest.fixture
def mock_team():
    return {"team": "test-team", "agent": "worker-1"}


class TestRespawnAgent:

    def test_respawn_succeeds_on_first_crash(self, mock_team):
        health = AgentHealth(
            agent_name=mock_team["agent"],
            consecutive_failures=1,
            state=HealthState.degraded,
        )
        member = MagicMock()
        member.agent_id = "abc123"
        member.agent_type = "researcher"
        member.model_name = ""
        spawn_info = {
            "backend": "tmux",
            "command": ["claude", "--dangerously-skip-permissions"],
            "tmux_target": "clawteam-test:0",
            "pid": 0,
        }

        with (
            patch(_PATCH_RECORD, return_value=health),
            patch(_PATCH_GET_INFO, return_value=spawn_info),
            patch(_PATCH_TM) as mock_tm,
            patch(_PATCH_BACKEND),
            patch(_PATCH_SWR, return_value="ok") as mock_swr,
        ):
            mock_tm.get_member.return_value = member
            result = respawn_agent(mock_team["team"], mock_team["agent"], spawn_info=spawn_info)

        assert result.startswith("ok:")
        mock_swr.assert_called_once()

    def test_respawn_blocked_after_max_attempts(self, mock_team):
        health = AgentHealth(
            agent_name=mock_team["agent"],
            consecutive_failures=MAX_RESPAWN_ATTEMPTS + 1,
            state=HealthState.open,
        )

        with patch(_PATCH_RECORD, return_value=health):
            result = respawn_agent(mock_team["team"], mock_team["agent"])

        assert result.startswith("Error:")
        assert "not respawning" in result

    def test_respawn_fails_no_spawn_info(self, mock_team):
        health = AgentHealth(
            agent_name=mock_team["agent"],
            consecutive_failures=1,
        )

        with (
            patch(_PATCH_RECORD, return_value=health),
            patch(_PATCH_GET_INFO, return_value=None),
        ):
            result = respawn_agent(mock_team["team"], mock_team["agent"])

        assert result.startswith("Error:")
        assert "no spawn info" in result

    def test_respawn_fails_no_team_member(self, mock_team):
        health = AgentHealth(
            agent_name=mock_team["agent"],
            consecutive_failures=1,
        )
        spawn_info = {"backend": "tmux", "command": ["claude"]}

        with (
            patch(_PATCH_RECORD, return_value=health),
            patch(_PATCH_GET_INFO, return_value=spawn_info),
            patch(_PATCH_TM) as mock_tm,
        ):
            mock_tm.get_member.return_value = None
            result = respawn_agent(mock_team["team"], mock_team["agent"], spawn_info=spawn_info)

        assert result.startswith("Error:")
        assert "not found in team config" in result

    def test_respawn_fails_spawn_error(self, mock_team):
        health = AgentHealth(
            agent_name=mock_team["agent"],
            consecutive_failures=1,
        )
        member = MagicMock()
        member.agent_id = "abc"
        member.agent_type = "worker"
        member.model_name = ""
        spawn_info = {"backend": "tmux", "command": ["claude"]}

        with (
            patch(_PATCH_RECORD, return_value=health),
            patch(_PATCH_GET_INFO, return_value=spawn_info),
            patch(_PATCH_TM) as mock_tm,
            patch(_PATCH_BACKEND),
            patch(_PATCH_SWR, return_value="Error: tmux not found"),
        ):
            mock_tm.get_member.return_value = member
            result = respawn_agent(mock_team["team"], mock_team["agent"], spawn_info=spawn_info)

        assert result.startswith("Error:")

    def test_respawn_second_attempt_still_allowed(self, mock_team):
        """Second crash (consecutive_failures=2) should still allow respawn."""
        health = AgentHealth(
            agent_name=mock_team["agent"],
            consecutive_failures=2,
            state=HealthState.degraded,
        )
        member = MagicMock()
        member.agent_id = "abc"
        member.agent_type = "worker"
        member.model_name = ""
        spawn_info = {"backend": "tmux", "command": ["claude"]}

        with (
            patch(_PATCH_RECORD, return_value=health),
            patch(_PATCH_GET_INFO, return_value=spawn_info),
            patch(_PATCH_TM) as mock_tm,
            patch(_PATCH_BACKEND),
            patch(_PATCH_SWR, return_value="ok"),
        ):
            mock_tm.get_member.return_value = member
            result = respawn_agent(mock_team["team"], mock_team["agent"], spawn_info=spawn_info)

        assert result.startswith("ok:")
