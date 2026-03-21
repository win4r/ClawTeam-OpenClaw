"""ZeroMQ PUSH/PULL transport with file-based fallback for offline agents."""

from __future__ import annotations

import collections
import json
import os
import socket
from pathlib import Path

from clawteam.team.models import get_data_dir
from clawteam.transport.base import Transport
from clawteam.transport.file import FileTransport


def _peers_dir(team_name: str) -> Path:
    d = get_data_dir() / "teams" / team_name / "peers"
    d.mkdir(parents=True, exist_ok=True)
    return d


class P2PTransport(Transport):
    """ZeroMQ PUSH/PULL + FileTransport offline fallback.

    - PULL socket: listens for incoming messages (bound if bind_agent is set)
    - PUSH socket: sends messages to other agents (connects to their PULL port)
    - Peer discovery: via shared filesystem peers/{agent}.json
    - Offline fallback: if peer is unreachable, messages go through FileTransport
    """

    def __init__(self, team_name: str, bind_agent: str | None = None):
        self.team_name = team_name
        self._bind_agent = bind_agent
        self._file_fallback = FileTransport(team_name)
        self._ctx = None
        self._pull = None
        self._push_cache: dict[str, object] = {}
        self._peek_buffer: collections.deque = collections.deque()
        self._port: int | None = None
        if bind_agent:
            self._start_listener()

    def _start_listener(self) -> None:
        """Bind a PULL socket and register this peer."""
        import zmq

        self._ctx = zmq.Context()
        self._pull = self._ctx.socket(zmq.PULL)
        self._port = self._pull.bind_to_random_port("tcp://*")
        self._register_peer()

    def _register_peer(self) -> None:
        """Write peers/{agent}.json with host/port/pid."""
        if not self._bind_agent or self._port is None:
            return
        peer_file = _peers_dir(self.team_name) / f"{self._bind_agent}.json"
        info = {
            "host": socket.gethostname(),
            "port": self._port,
            "pid": os.getpid(),
        }
        tmp = peer_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        tmp.replace(peer_file)

    def _deregister_peer(self) -> None:
        """Remove peers/{agent}.json."""
        if not self._bind_agent:
            return
        peer_file = _peers_dir(self.team_name) / f"{self._bind_agent}.json"
        try:
            peer_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _get_peer_addr(self, recipient: str) -> str | None:
        """Read peers/{recipient}.json and return tcp://host:port if alive."""
        peer_file = _peers_dir(self.team_name) / f"{recipient}.json"
        if not peer_file.exists():
            return None
        try:
            info = json.loads(peer_file.read_text(encoding="utf-8"))
            pid = info.get("pid")
            if pid and not self._pid_alive(pid):
                # Stale peer file — clean it up
                try:
                    peer_file.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            host = info["host"]
            port = info["port"]
            return f"tcp://{host}:{port}"
        except Exception:
            return None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _get_or_create_push(self, addr: str):
        """Get or create a cached PUSH socket for the given address."""
        import zmq

        if addr in self._push_cache:
            return self._push_cache[addr]
        if self._ctx is None:
            self._ctx = zmq.Context()
        sock = self._ctx.socket(zmq.PUSH)
        sock.setsockopt(zmq.SNDTIMEO, 1000)  # 1s send timeout
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(addr)
        self._push_cache[addr] = sock
        return sock

    def deliver(self, recipient: str, data: bytes) -> None:
        addr = self._get_peer_addr(recipient)
        if addr:
            try:
                import zmq

                sock = self._get_or_create_push(addr)
                sock.send(data, zmq.NOBLOCK)
                return
            except Exception:
                pass
        # Peer unreachable — fall back to file
        self._file_fallback.deliver(recipient, data)

    def fetch(self, agent_name: str, limit: int = 10, consume: bool = True) -> list[bytes]:
        messages: list[bytes] = []
        # 1. Drain peek buffer first (only on consume)
        if consume:
            while self._peek_buffer and len(messages) < limit:
                messages.append(self._peek_buffer.popleft())
        # 2. Drain ZMQ PULL socket (non-blocking)
        if self._pull:
            import zmq

            while len(messages) < limit:
                try:
                    data = self._pull.recv(zmq.NOBLOCK)
                    if consume:
                        messages.append(data)
                    else:
                        self._peek_buffer.append(data)
                        messages.append(data)
                except zmq.Again:
                    break
        # 3. File fallback for remaining
        remaining = limit - len(messages)
        if remaining > 0:
            messages.extend(self._file_fallback.fetch(agent_name, remaining, consume))
        return messages[:limit]

    def count(self, agent_name: str) -> int:
        # ZMQ has no queue-depth query; return file count + peek buffer size
        return self._file_fallback.count(agent_name) + len(self._peek_buffer)

    def list_recipients(self) -> list[str]:
        # Union of peers/ directory and inboxes/ directory
        peers: set[str] = set()
        peers_dir = _peers_dir(self.team_name)
        for f in peers_dir.glob("*.json"):
            peers.add(f.stem)
        peers.update(self._file_fallback.list_recipients())
        return list(peers)

    def close(self) -> None:
        self._deregister_peer()
        for sock in self._push_cache.values():
            try:
                sock.close()
            except Exception:
                pass
        self._push_cache.clear()
        if self._pull:
            try:
                self._pull.close()
            except Exception:
                pass
            self._pull = None
        if self._ctx:
            try:
                self._ctx.term()
            except Exception:
                pass
            self._ctx = None
