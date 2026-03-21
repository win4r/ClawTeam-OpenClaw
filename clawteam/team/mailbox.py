"""Mailbox system for inter-agent communication, backed by pluggable Transport."""

from __future__ import annotations

import json
import time
import uuid

from clawteam.team.models import MessageType, TeamMessage, get_data_dir
from clawteam.transport.base import Transport


def _default_transport(team_name: str) -> Transport:
    """Resolve the transport from env / config, with optional P2P listener binding."""
    import os

    name = os.environ.get("CLAWTEAM_TRANSPORT", "")
    if not name:
        from clawteam.config import load_config
        name = load_config().transport or "file"
    if name == "p2p":
        from clawteam.identity import AgentIdentity
        agent = AgentIdentity.from_env().agent_name
        from clawteam.transport import get_transport
        return get_transport("p2p", team_name=team_name, bind_agent=agent)
    from clawteam.transport import get_transport
    return get_transport("file", team_name=team_name)


class MailboxManager:
    """Mailbox for inter-agent messaging, delegating I/O to a Transport.

    Each message is a JSON file in the recipient's inbox directory:
    ``{data_dir}/teams/{team}/inboxes/{agent}/msg-{timestamp}-{uuid}.json``

    Atomic writes (write tmp then rename) prevent partial reads.
    """

    def __init__(self, team_name: str, transport: Transport | None = None):
        self.team_name = team_name
        self._transport = transport or _default_transport(team_name)
        self._events_dir = get_data_dir() / "teams" / team_name / "events"
        self._events_dir.mkdir(parents=True, exist_ok=True)

    def _log_event(self, msg: TeamMessage) -> None:
        """Persist message to event log (never consumed, for history)."""
        ts = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        path = self._events_dir / f"evt-{ts}-{uid}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            msg.model_dump_json(indent=2, by_alias=True, exclude_none=True),
            encoding="utf-8",
        )
        tmp.rename(path)

    def get_event_log(self, limit: int = 100) -> list[TeamMessage]:
        """Read event log (newest first). Non-destructive."""
        files = sorted(self._events_dir.glob("evt-*.json"), reverse=True)[:limit]
        msgs = []
        for f in files:
            try:
                msgs.append(TeamMessage.model_validate(json.loads(f.read_text("utf-8"))))
            except Exception:
                pass
        return msgs

    def send(
        self,
        from_agent: str,
        to: str,
        content: str | None = None,
        msg_type: MessageType = MessageType.message,
        request_id: str | None = None,
        key: str | None = None,
        proposed_name: str | None = None,
        capabilities: str | None = None,
        feedback: str | None = None,
        reason: str | None = None,
        assigned_name: str | None = None,
        agent_id: str | None = None,
        team_name: str | None = None,
        plan_file: str | None = None,
        summary: str | None = None,
        plan: str | None = None,
        last_task: str | None = None,
        status: str | None = None,
    ) -> TeamMessage:
        from clawteam.team.manager import TeamManager

        delivery_target = TeamManager.resolve_inbox(self.team_name, to)
        msg = TeamMessage(
            type=msg_type,
            from_agent=from_agent,
            to=to,
            content=content,
            request_id=request_id or uuid.uuid4().hex[:12],
            key=key,
            proposed_name=proposed_name,
            capabilities=capabilities,
            feedback=feedback,
            reason=reason,
            assigned_name=assigned_name,
            agent_id=agent_id,
            team_name=team_name,
            plan_file=plan_file,
            summary=summary,
            plan=plan,
            last_task=last_task,
            status=status,
        )
        data = msg.model_dump_json(indent=2, by_alias=True, exclude_none=True).encode("utf-8")
        self._transport.deliver(delivery_target, data)
        self._log_event(msg)
        return msg

    def broadcast(
        self,
        from_agent: str,
        content: str,
        msg_type: MessageType = MessageType.broadcast,
        key: str | None = None,
        exclude: list[str] | None = None,
    ) -> list[TeamMessage]:
        from clawteam.team.manager import TeamManager

        exclude_set = set(exclude or [])
        exclude_set.add(from_agent)
        # Build a mapping from inbox directory name to logical agent name
        # so we can correctly exclude the sender even when inbox names
        # use user-prefixed format (e.g. "alice_worker").
        exclude_inboxes = set()
        for name in exclude_set:
            inbox = TeamManager.resolve_inbox(self.team_name, name)
            exclude_inboxes.add(inbox)
            exclude_inboxes.add(name)  # also exclude by raw name
        messages = []
        for recipient in self._transport.list_recipients():
            if recipient not in exclude_inboxes:
                msg = TeamMessage(
                    type=msg_type,
                    from_agent=from_agent,
                    to=recipient,
                    content=content,
                    key=key,
                )
                data = msg.model_dump_json(
                    indent=2, by_alias=True, exclude_none=True
                ).encode("utf-8")
                self._transport.deliver(recipient, data)
                self._log_event(msg)
                messages.append(msg)
        return messages

    def receive(
        self,
        agent_name: str,
        limit: int = 10,
        acknowledge: bool = False,
        acknowledge_status: str | None = None,
    ) -> list[TeamMessage]:
        """Receive and delete messages from an agent's inbox (FIFO).

        When acknowledge=True, send an explicit ack back to the original sender for
        each received message that has both a sender and request_id.
        """
        raw = self._transport.fetch(agent_name, limit=limit, consume=True)
        messages = [TeamMessage.model_validate(json.loads(r)) for r in raw]
        if acknowledge:
            ack_status = acknowledge_status or "acknowledged"
            for msg in messages:
                if msg.type == MessageType.ack or not msg.from_agent or not msg.request_id:
                    continue
                self.send(
                    from_agent=agent_name,
                    to=msg.from_agent,
                    msg_type=MessageType.ack,
                    request_id=msg.request_id,
                    content=f"Ack: received message {msg.request_id}",
                    key=msg.key,
                    last_task=msg.last_task,
                    status=ack_status,
                )
        return messages

    def peek(self, agent_name: str) -> list[TeamMessage]:
        """Return pending messages without consuming them."""
        raw = self._transport.fetch(agent_name, consume=False)
        return [TeamMessage.model_validate(json.loads(r)) for r in raw]

    def peek_count(self, agent_name: str) -> int:
        return self._transport.count(agent_name)
