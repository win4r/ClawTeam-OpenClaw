"""Tests for Gateway ↔ ClawTeam integration (P0-A/B/C)."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import pytest

from clawteam.team.costs import CostStore
from clawteam.team.gateway import (
    export_gateway_config,
    export_gateway_peers,
    notify_gateway_agent_status,
)
from clawteam.team.manager import TeamManager


@pytest.fixture
def team_with_members(team_name):
    """Create a team with a leader and two workers."""
    TeamManager.create_team(
        name=team_name, leader_name="leader", leader_id="lid001",
        description="Test team for gateway export",
    )
    TeamManager.add_member(team_name, "coder", "cid001", agent_type="coder")
    TeamManager.add_member(team_name, "reviewer", "rid001", agent_type="reviewer")
    return team_name


# =========================================================================
# P0-A: Config Export
# =========================================================================


class TestExportGatewayPeers:
    def test_basic_export(self, team_with_members):
        peers = export_gateway_peers(team_with_members)
        assert len(peers) == 3
        names = {p["name"] for p in peers}
        assert names == {"leader", "coder", "reviewer"}

    def test_agent_id_included(self, team_with_members):
        peers = export_gateway_peers(team_with_members)
        leader = next(p for p in peers if p["name"] == "leader")
        assert leader["agentId"] == "lid001"

    def test_agent_type_included(self, team_with_members):
        peers = export_gateway_peers(team_with_members)
        coder = next(p for p in peers if p["name"] == "coder")
        assert coder["agentType"] == "coder"

    def test_gateway_url_generates_card_url(self, team_with_members):
        peers = export_gateway_peers(team_with_members, gateway_base_url="http://localhost:18800")
        for p in peers:
            assert p["agentCardUrl"] == "http://localhost:18800/.well-known/agent.json"

    def test_no_gateway_url_no_card_url(self, team_with_members):
        peers = export_gateway_peers(team_with_members)
        for p in peers:
            assert "agentCardUrl" not in p

    def test_team_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            export_gateway_peers("nonexistent-team")


class TestExportGatewayConfig:
    def test_full_config(self, team_with_members):
        config = export_gateway_config(team_with_members)
        assert config["teamName"] == team_with_members
        assert len(config["peers"]) == 3
        assert "agentCard" in config
        assert "routing" in config

    def test_skills_from_members(self, team_with_members):
        config = export_gateway_config(team_with_members)
        skill_ids = {s["id"] for s in config["agentCard"]["skills"]}
        assert skill_ids == {"leader", "coder", "reviewer"}

    def test_routing_rules(self, team_with_members):
        config = export_gateway_config(team_with_members)
        rules = config["routing"]["rules"]
        assert len(rules) == 3
        assert config["routing"]["defaultAgentId"] == "lid001"

    def test_no_routing(self, team_with_members):
        config = export_gateway_config(team_with_members, include_routing=False)
        assert "routing" not in config

    def test_output_is_valid_json(self, team_with_members):
        config = export_gateway_config(team_with_members)
        serialized = json.dumps(config)
        assert json.loads(serialized) == config


# =========================================================================
# P0-B: Cost Event Sink
# =========================================================================


class TestCostIngest:
    def test_ingest_creates_ext_file(self, team_name, isolated_data_dir):
        store = CostStore(team_name)
        event = store.ingest_external_event(
            agent_name="remote-agent",
            input_tokens=1000,
            output_tokens=500,
            cost_cents=2.5,
            source="a2a-gateway",
        )
        assert event.agent_name == "remote-agent"
        assert event.cost_cents == 2.5
        costs_dir = isolated_data_dir / "costs" / team_name
        ext_files = list(costs_dir.glob("cost-ext-*.json"))
        assert len(ext_files) == 1
        assert "a2a-gateway" in ext_files[0].name

    def test_ingest_appears_in_summary(self, team_name):
        store = CostStore(team_name)
        store.report(agent_name="local-agent", cost_cents=1.0)
        store.ingest_external_event(agent_name="remote-agent", cost_cents=3.0)
        summary = store.summary()
        assert summary.total_cost_cents == pytest.approx(4.0)
        assert "local-agent" in summary.by_agent
        assert "remote-agent" in summary.by_agent

    def test_ingest_appears_in_list_events(self, team_name):
        store = CostStore(team_name)
        store.ingest_external_event(agent_name="ext-1", cost_cents=5.0, source="test")
        events = store.list_events()
        assert len(events) == 1
        assert events[0].agent_name == "ext-1"

    def test_ingest_custom_source(self, team_name, isolated_data_dir):
        store = CostStore(team_name)
        store.ingest_external_event(agent_name="a1", cost_cents=1.0, source="custom-src")
        costs_dir = isolated_data_dir / "costs" / team_name
        ext_files = list(costs_dir.glob("cost-ext-custom-src-*.json"))
        assert len(ext_files) == 1

    def test_ingest_with_model_and_task(self, team_name):
        store = CostStore(team_name)
        event = store.ingest_external_event(
            agent_name="a1", model="gpt-4", task_id="task-42", cost_cents=10.0,
        )
        assert event.model == "gpt-4"
        assert event.task_id == "task-42"
        summary = store.summary()
        assert "gpt-4" in summary.by_model
        assert "task-42" in summary.by_task


# =========================================================================
# P0-C: Liveness Notification
# =========================================================================


class _WebhookHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler that records POST payloads."""

    received: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        _WebhookHandler.received.append({"path": self.path, "body": body})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass  # suppress logs


class TestNotifyGateway:
    def test_successful_notification(self):
        _WebhookHandler.received.clear()
        server = HTTPServer(("127.0.0.1", 0), _WebhookHandler)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()

        ok = notify_gateway_agent_status(
            gateway_url=f"http://127.0.0.1:{port}",
            agent_name="worker-1",
            agent_id="w001",
            status="shutdown",
            team_name="my-team",
        )
        thread.join(timeout=5)
        server.server_close()

        assert ok is True
        assert len(_WebhookHandler.received) == 1
        payload = _WebhookHandler.received[0]
        assert payload["path"] == "/a2a/webhooks/agent-status"
        assert payload["body"]["agentName"] == "worker-1"
        assert payload["body"]["status"] == "shutdown"

    def test_unreachable_gateway_returns_false(self):
        ok = notify_gateway_agent_status(
            gateway_url="http://127.0.0.1:1",  # unreachable
            agent_name="w1",
            agent_id="id1",
            status="shutdown",
            timeout_seconds=0.5,
        )
        assert ok is False


class TestLifecycleGatewayIntegration:
    def test_shutdown_triggers_notification(self, team_name, monkeypatch):
        """request_shutdown sends gateway webhook when CLAWTEAM_GATEWAY_URL is set."""
        TeamManager.create_team(name=team_name, leader_name="leader", leader_id="lid")
        TeamManager.add_member(team_name, "worker", "wid")

        from clawteam.team.lifecycle import LifecycleManager
        from clawteam.team.mailbox import MailboxManager

        mailbox = MailboxManager(team_name)
        lifecycle = LifecycleManager(team_name, mailbox)

        monkeypatch.setenv("CLAWTEAM_GATEWAY_URL", "http://fake:18800")
        with patch("clawteam.team.gateway.notify_gateway_agent_status") as mock_notify:
            lifecycle.request_shutdown("leader", "worker", reason="test")

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args
            assert call_kwargs[1]["agent_name"] == "worker"
            assert call_kwargs[1]["status"] == "shutdown"

    def test_no_gateway_url_no_notification(self, team_name, monkeypatch):
        """Without CLAWTEAM_GATEWAY_URL, no notification is sent."""
        TeamManager.create_team(name=team_name, leader_name="leader", leader_id="lid")
        TeamManager.add_member(team_name, "worker", "wid")

        from clawteam.team.lifecycle import LifecycleManager
        from clawteam.team.mailbox import MailboxManager

        mailbox = MailboxManager(team_name)
        lifecycle = LifecycleManager(team_name, mailbox)

        monkeypatch.delenv("CLAWTEAM_GATEWAY_URL", raising=False)
        with patch("clawteam.team.gateway.notify_gateway_agent_status") as mock_notify:
            lifecycle.request_shutdown("leader", "worker")
            mock_notify.assert_not_called()
