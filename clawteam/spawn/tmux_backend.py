"""Tmux spawn backend - launches agents in tmux windows for visual monitoring."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from clawteam.platform_compat import is_windows
from clawteam.spawn.adapters import NativeCliAdapter
from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.cli_env import (
    build_spawn_path,
    propagate_openclaw_gateway_token,
    resolve_clawteam_executable,
)
from clawteam.spawn.command_validation import (
    command_has_workspace_arg,
    is_claude_command,
    is_codex_command,
    is_gemini_command,
    is_hermes_command,
    is_kimi_command,
    is_nanobot_command,
    is_openclaw_command,
    is_opencode_command,
    is_pi_command,
    is_qwen_command,
    normalize_spawn_command,
    validate_spawn_command,
)
from clawteam.spawn.runtime_notification import render_runtime_notification
from clawteam.spawn.session_capture import persist_spawned_session, prepare_session_capture
from clawteam.team.models import get_data_dir

_SHELL_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

_WORKER_AGENTS_MD = """\
# ClawTeam Worker

This is an isolated workspace for ClawTeam worker agents.
Follow the coordination protocol provided in your system prompt.
"""


def _openclaw_supports_agent_flag() -> bool:
    """Check whether the installed openclaw tui supports the --agent parameter."""
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        return False
    try:
        result = subprocess.run(
            [openclaw_bin, "tui", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        return "--agent" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _ensure_worker_workspace() -> str:
    """Create and return the path to an isolated minimal workspace for OpenClaw workers.

    This prevents workers from inheriting the user's SOUL.md/AGENTS.md/USER.md,
    which can cause NO_REPLY behavior or other workspace-rule pollution.
    """
    workspace_dir = Path.home() / ".clawteam" / "worker-workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    agents_md = workspace_dir / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(_WORKER_AGENTS_MD)
    return str(workspace_dir)


class TmuxBackend(SpawnBackend):
    """Spawn agents in tmux windows for visual monitoring.

    Each agent gets its own tmux window in a session named ``clawteam-{team}``.
    Agents run in interactive mode so their work is visible in the tmux pane.
    """

    def __init__(self):
        self._agents: dict[str, str] = {}  # agent_name -> tmux target
        self._adapter = NativeCliAdapter()

    def spawn(
        self,
        command: list[str],
        agent_name: str,
        agent_id: str,
        agent_type: str,
        team_name: str,
        prompt: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
        openclaw_agent: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        is_leader: bool = False,
        keepalive: bool = False,
    ) -> str:
        if not shutil.which("tmux"):
            return _tmux_unavailable_message("spawn")

        # Check --agent support once, gate all uses of openclaw_agent
        if openclaw_agent and not _openclaw_supports_agent_flag():
            print(
                f"Warning: openclaw tui does not support --agent (requested: {openclaw_agent!r}). "
                "Ignoring --openclaw-agent; worker isolation is handled via OPENCLAW_WORKSPACE instead.",
                file=sys.stderr,
            )
            openclaw_agent = None

        session_name = f"clawteam-{team_name}"
        clawteam_bin = resolve_clawteam_executable()
        env_vars = os.environ.copy()
        # Interactive CLIs like Codex refuse to start when TERM=dumb is inherited
        # from a non-interactive shell. tmux provides a real terminal, so we
        # normalize TERM to a sensible value before exporting it into the pane.
        if env_vars.get("TERM", "").lower() == "dumb":
            env_vars["TERM"] = "xterm-256color"
        env_vars.setdefault("CLAWTEAM_DATA_DIR", str(get_data_dir()))
        env_vars.update({
            "CLAWTEAM_AGENT_ID": agent_id,
            "CLAWTEAM_AGENT_NAME": agent_name,
            "CLAWTEAM_AGENT_TYPE": agent_type,
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_LEADER": "1" if is_leader else "0",
            "CLAWTEAM_MEMORY_SCOPE": f"custom:team-{team_name}",
        })
        # Propagate user if set
        user = os.environ.get("CLAWTEAM_USER", "")
        if user:
            env_vars["CLAWTEAM_USER"] = user
        # Propagate transport if set
        transport = os.environ.get("CLAWTEAM_TRANSPORT", "")
        if transport:
            env_vars["CLAWTEAM_TRANSPORT"] = transport
        if cwd:
            env_vars["CLAWTEAM_WORKSPACE_DIR"] = cwd
        if model:
            env_vars["CLAWTEAM_MODEL"] = model
        # Inject context awareness flags
        env_vars["CLAWTEAM_CONTEXT_ENABLED"] = "1"
        if env:
            env_vars.update(env)
        env_vars["PATH"] = build_spawn_path(env_vars.get("PATH", os.environ.get("PATH")))
        if os.path.isabs(clawteam_bin):
            env_vars.setdefault("CLAWTEAM_BIN", clawteam_bin)
            if is_openclaw_command(command):
                print(
                    f"Hint: OpenClaw 4.2+ requires absolute paths in exec allowlist. "
                    f"Run: openclaw approvals allowlist add --agent \"*\" \"{clawteam_bin}\"",
                    file=sys.stderr,
                )

        # Isolate OpenClaw workers from the user's workspace rules (SOUL.md, AGENTS.md, USER.md)
        # to prevent NO_REPLY behavior or workspace-rule pollution.
        if is_openclaw_command(command):
            worker_ws = _ensure_worker_workspace()
            env_vars["OPENCLAW_WORKSPACE"] = worker_ws
            propagate_openclaw_gateway_token(env_vars)

        # Session capture hook (upstream PR #154): record session id before spawn for
        # later resume.  OpenClaw locator's prepare() does not modify command, so
        # subsequent fork manual flag handling remains valid.
        session_capture = prepare_session_capture(
            command,
            team_name=team_name,
            agent_name=agent_name,
            cwd=cwd,
            prompt=prompt,
        )

        normalized_command = normalize_spawn_command(session_capture.command)

        command_error = validate_spawn_command(normalized_command, path=env_vars["PATH"], cwd=cwd)
        if command_error:
            return command_error

        # tmux launches the command through a shell, so only shell-safe
        # environment names can be exported. The current host environment on
        # WSL includes names like ``PROGRAMFILES(X86)``, which would abort the
        # shell before the pane becomes observable.
        export_vars = {k: v for k, v in env_vars.items() if _SHELL_ENV_KEY_RE.fullmatch(k)}

        # Write env vars to a temp file and source it to avoid exceeding
        # tmux's command-length limit (~16k chars).  The file is deliberately
        # NOT deleted here — the sourcing shell needs it at startup.  A
        # self-cleanup line inside the file removes it after it has been read.
        env_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".env.sh", delete=False, prefix="clawteam-env-"
        )
        for k, v in export_vars.items():
            env_file.write(f"export {k}={shlex.quote(v)}\n")
        # Self-cleanup: remove the env file after sourcing
        env_file.write(f"rm -f {shlex.quote(env_file.name)}\n")
        env_file.close()
        env_source_cmd = f". {shlex.quote(env_file.name)}"

        # Build the command (without prompt -- we'll send it via send-keys)
        final_command = list(normalized_command)
        if skip_permissions:
            if is_claude_command(normalized_command):
                final_command.append("--dangerously-skip-permissions")
            elif is_codex_command(normalized_command):
                final_command.append("--dangerously-bypass-approvals-and-sandbox")
            elif (
                is_gemini_command(normalized_command)
                or is_kimi_command(normalized_command)
                or is_opencode_command(normalized_command)
                or is_hermes_command(normalized_command)
                or is_qwen_command(normalized_command)
            ):
                final_command.append("--yolo")

        # Claude Code: pass --model if specified
        if model and is_claude_command(normalized_command):
            final_command.extend(["--model", model])

        # OpenClaw TUI: pass --message for initial prompt and --session for isolation
        if is_openclaw_command(normalized_command):
            session_key = f"clawteam-{team_name}-{agent_name}"
            if final_command[0].endswith("openclaw") and len(final_command) == 1:
                final_command = [final_command[0], "tui", "--session", session_key]
                if model:
                    final_command.extend(["--model", model])
                if openclaw_agent:
                    final_command.extend(["--agent", openclaw_agent])
                if prompt:
                    final_command.extend(["--message", prompt])
            elif "tui" in final_command:
                final_command.extend(["--session", session_key])
                if model:
                    final_command.extend(["--model", model])
                if openclaw_agent:
                    final_command.extend(["--agent", openclaw_agent])
                if prompt:
                    final_command.extend(["--message", prompt])
            elif "agent" in final_command:
                if model:
                    final_command.extend(["--model", model])
                if openclaw_agent:
                    final_command.extend(["--agent", openclaw_agent])
                if prompt:
                    final_command.extend(["--message", prompt])

        # Hermes Agent: tag as tool-sourced so clawteam spawns don't pollute the
        # user's session list, pass prompt via -q. Insert 'chat' subcommand
        # only when the user's original command is bare `hermes` (don't clobber
        # user-supplied global options or alternate subcommands).
        # Check normalized_command, not final_command, since skip_permissions
        # may have already appended --yolo.
        # Do NOT pass --continue -- Hermes --continue resumes EXISTING sessions
        # only; fresh spawns auto-generate a session ID.
        if is_hermes_command(normalized_command):
            if len(normalized_command) == 1:
                # Insert chat at position 1 (before any --yolo already appended).
                final_command.insert(1, "chat")
            if "--source" not in final_command:
                final_command.extend(["--source", "tool"])
            if model:
                final_command.extend(["-m", model])
            if prompt:
                final_command.extend(["-q", prompt])

        if is_kimi_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["--print", "-p", prompt])
        elif is_nanobot_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["-m", prompt])
        elif prompt and is_codex_command(normalized_command):
            final_command.append(prompt)
        elif prompt and is_gemini_command(normalized_command):
            # Gemini in interactive (tmux) context uses -i; subprocess uses -p.
            # Aligns with upstream adapter behaviour (per backlog §11 adapters.py).
            final_command.extend(["-i", prompt])
        elif prompt and (is_qwen_command(normalized_command) or is_opencode_command(normalized_command)):
            final_command.extend(["-p", prompt])

        # system_prompt injection (upstream PR #154): claude/pi only.
        if system_prompt and (is_claude_command(normalized_command) or is_pi_command(normalized_command)):
            insert_at = final_command.index("-p") if "-p" in final_command else len(final_command)
            final_command[insert_at:insert_at] = ["--append-system-prompt", system_prompt]

        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        # Append on-exit hook: runs immediately when agent process exits.  This
        # is the fork's lifecycle path — invokes `clawteam lifecycle on-exit`
        # which triggers respawn_agent (PR #60 auto-respawn).  upstream's
        # build_keepalive_shell_command/resume_command path is NOT used here;
        # the `keepalive` arg is accepted for signature compatibility but the
        # fork wrapper + on-exit hook covers the same recovery semantics.
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        heartbeat_hook = (
            f"{exit_cmd} lifecycle worker-heartbeat {shlex.quote(team_name)} "
            f"--status spawned >/dev/null 2>&1 || true"
        )
        # Unset nesting-detection env vars so spawned agents
        # don't refuse to start when the leader is itself a session.
        unset_clause = "unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION OPENCLAW_NESTED 2>/dev/null; "
        if cwd:
            full_cmd = f"{unset_clause}{env_source_cmd}; cd {shlex.quote(cwd)} && {heartbeat_hook}; trap \"{exit_hook}\" EXIT; {cmd_str}"
        else:
            full_cmd = f"{unset_clause}{env_source_cmd}; {heartbeat_hook}; trap \"{exit_hook}\" EXIT; {cmd_str}"

        # Check if tmux session exists
        check = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        target = f"{session_name}:{agent_name}"

        if check.returncode != 0:
            launch = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name, "-n", agent_name, full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            launch = subprocess.run(
                ["tmux", "new-window", "-t", session_name, "-n", agent_name, full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        if launch.returncode != 0:
            stderr = launch.stderr.decode() if isinstance(launch.stderr, bytes) else launch.stderr
            return f"Error: failed to launch tmux session: {(stderr or '').strip()}"

        # Keep leader pane alive even if the agent process exits, so it can be
        # re-activated or inspected later (upstream PR #154 new feature).
        if is_leader:
            subprocess.run(
                ["tmux", "set-option", "-t", target, "remain-on-exit", "on"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        from clawteam.config import load_config

        cfg = load_config()
        pane_ready_timeout = min(cfg.spawn_ready_timeout, max(4.0, cfg.spawn_prompt_delay + 2.0))
        if not _wait_for_tmux_pane(
            target,
            timeout_seconds=pane_ready_timeout,
            poll_interval_seconds=0.2,
        ):
            return (
                f"Error: tmux pane for '{normalized_command[0]}' did not become visible "
                f"within {pane_ready_timeout:.1f}s. Verify the CLI works standalone before "
                "using it with clawteam spawn."
            )

        _confirm_workspace_trust_if_prompted(
            target,
            normalized_command,
            timeout_seconds=cfg.spawn_ready_timeout,
        )

        # Send the prompt as input to the interactive session (fork path).
        # OpenClaw TUI, Codex, nanobot, and Gemini already received prompt via command args, skip here.
        # NOTE: fork uses trap EXIT inside cmd_str + `clawteam lifecycle on-exit`
        # for cleanup (PR #60 auto-respawn).  upstream's tmux set-hook
        # pane-exited/pane-died would double-trigger on-exit, so we deliberately
        # skip those hooks here.  is_leader remain-on-exit above is harmless
        # additive behaviour.
        if prompt and is_claude_command(normalized_command):
            # Wait for Claude Code to finish startup and show input prompt.
            # Bedrock-backed instances can take 10+ seconds to initialize.
            _wait_for_cli_ready(
                target,
                timeout_seconds=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            _inject_prompt_via_buffer(target, agent_name, prompt)
        elif prompt and not is_codex_command(normalized_command) and not is_openclaw_command(normalized_command) and not is_hermes_command(normalized_command) and not is_nanobot_command(normalized_command) and not is_gemini_command(normalized_command) and not is_kimi_command(normalized_command) and not is_qwen_command(normalized_command) and not is_opencode_command(normalized_command):
            # Generic command: append prompt via send-keys
            _wait_for_tui_ready(
                target,
                timeout=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", target, prompt, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self._agents[agent_name] = target

        # Capture pane PID for robust liveness checking (survives tile operations)
        pane_pid = 0
        pid_result = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_pid}"],
            capture_output=True, text=True,
        )
        if pid_result.returncode == 0 and pid_result.stdout.strip():
            try:
                pane_pid = int(pid_result.stdout.strip().splitlines()[0])
            except ValueError:
                pass

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="tmux",
            tmux_target=target,
            pid=pane_pid,
            command=list(final_command),
        )
        persist_spawned_session(
            session_capture,
            team_name=team_name,
            agent_name=agent_name,
            command=list(final_command),
        )

        # Emit AfterWorkerSpawn event
        try:
            from clawteam.events.global_bus import get_event_bus
            from clawteam.events.types import AfterWorkerSpawn
            get_event_bus().emit_async(AfterWorkerSpawn(
                team_name=team_name,
                agent_name=agent_name,
                agent_id=agent_id,
                backend="tmux",
                target=target,
            ))
        except Exception:
            pass

        return f"Agent '{agent_name}' spawned in tmux ({target})"

    def list_running(self) -> list[dict[str, str]]:
        return [
            {"name": name, "target": target, "backend": "tmux"}
            for name, target in self._agents.items()
        ]

    def inject_runtime_message(self, team: str, agent_name: str, envelope) -> tuple[bool, str]:
        """Best-effort runtime injection into an existing tmux agent pane."""
        if not shutil.which("tmux"):
            return False, "tmux not installed"

        target = f"{self.session_name(team)}:{agent_name}"
        probe = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            return False, f"tmux target '{target}' not found"

        try:
            _inject_prompt_via_buffer(
                target,
                agent_name,
                render_runtime_notification(envelope),
            )
        except Exception as exc:
            return False, f"runtime injection failed for '{target}': {exc}"

        return True, f"Injected runtime notification into {target}"

    @staticmethod
    def session_name(team_name: str) -> str:
        return f"clawteam-{team_name}"

    @staticmethod
    def tile_panes(team_name: str) -> str:
        """Merge all windows into one tiled view. Does NOT attach.

        Returns status message or error.
        """
        if not shutil.which("tmux"):
            return _tmux_unavailable_message("attach")

        session = TmuxBackend.session_name(team_name)

        check = subprocess.run(
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if check.returncode != 0:
            return f"Error: tmux session '{session}' not found. No agents spawned for team '{team_name}'?"

        # Count current panes in window 0
        pane_count = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session}:0"],
            capture_output=True, text=True,
        )
        num_panes = len(pane_count.stdout.strip().splitlines()) if pane_count.returncode == 0 else 0

        # Get windows
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_index}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return f"Error: failed to list windows: {result.stderr.strip()}"

        windows = result.stdout.strip().splitlines()

        # If already tiled (1 window, multiple panes), skip merge
        if len(windows) <= 1 and num_panes > 1:
            return f"Already tiled ({num_panes} panes) in {session}"

        if len(windows) > 1:
            first = windows[0]
            for w in windows[1:]:
                subprocess.run(
                    ["tmux", "join-pane", "-s", f"{session}:{w}", "-t", f"{session}:{first}", "-h"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            subprocess.run(
                ["tmux", "select-layout", "-t", f"{session}:{first}", "tiled"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        # Recount
        pane_count = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session}:0"],
            capture_output=True, text=True,
        )
        final_panes = len(pane_count.stdout.strip().splitlines()) if pane_count.returncode == 0 else 0
        return f"Tiled {final_panes} panes in {session}"

    @staticmethod
    def attach_all(team_name: str) -> str:
        """Tile all windows into panes and attach to the session."""
        result = TmuxBackend.tile_panes(team_name)
        if result.startswith("Error"):
            return result

        session = TmuxBackend.session_name(team_name)
        subprocess.run(["tmux", "attach-session", "-t", session])
        return result

def _confirm_workspace_trust_if_prompted(
    target: str,
    command: list[str],
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Acknowledge startup confirmation prompts for interactive CLIs.

    Claude Code and Codex can stop at a directory trust prompt when launched in
    a fresh git worktree. Claude can also pause on a confirmation dialog when
    `--dangerously-skip-permissions` is enabled. Detect these screens before
    any prompt injection so the interactive TUI remains intact.
    """
    if not (is_claude_command(command) or is_codex_command(command) or is_gemini_command(command)):
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
        )
        pane_text = pane.stdout.lower() if pane.returncode == 0 else ""
        action = _startup_prompt_action(command, pane_text)
        if action == "enter":
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True
        if action == "down-enter":
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "-l", "\x1b[B"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.2)
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True

        time.sleep(poll_interval_seconds)

    return False


def _startup_prompt_action(command: list[str], pane_text: str) -> str | None:
    """Return the key action needed to dismiss a startup confirmation prompt."""
    if _looks_like_claude_skip_permissions_prompt(command, pane_text):
        return "down-enter"
    if _looks_like_workspace_trust_prompt(command, pane_text):
        return "enter"
    return None


def _wait_for_tmux_pane(
    target: str,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Poll tmux until the target pane exists and is observable."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
        )
        if pane.returncode == 0 and pane.stdout.strip():
            return True
        time.sleep(poll_interval_seconds)

    return False


def _looks_like_workspace_trust_prompt(command: list[str], pane_text: str) -> bool:
    """Return True when the tmux pane is showing a trust confirmation dialog."""
    if not pane_text:
        return False

    if is_claude_command(command):
        return ("trust this folder" in pane_text or "trust the contents" in pane_text) and (
            "enter to confirm" in pane_text or "press enter" in pane_text or "enter to continue" in pane_text
        )

    if is_codex_command(command):
        return (
            "trust the contents of this directory" in pane_text
            and "press enter to continue" in pane_text
        )

    if is_gemini_command(command):
        return "trust folder" in pane_text or "trust parent folder" in pane_text

    return False


def _looks_like_claude_skip_permissions_prompt(command: list[str], pane_text: str) -> bool:
    """Return True when Claude is waiting for the dangerous-permissions confirmation."""
    if not pane_text or not is_claude_command(command):
        return False

    has_accept_choice = "yes, i accept" in pane_text
    has_permissions_warning = (
        "dangerously-skip-permissions" in pane_text
        or "skip permissions" in pane_text
        or "permission" in pane_text
        or "approval" in pane_text
    )
    return has_accept_choice and has_permissions_warning


def _looks_like_codex_update_prompt(pane_text: str) -> bool:
    """Return True when Codex is showing the update gate before the main TUI."""
    if not pane_text:
        return False

    return (
        "update available" in pane_text
        and "press enter to continue" in pane_text
        and ("update now" in pane_text or "skip until next version" in pane_text)
    )


def _dismiss_codex_update_prompt_if_present(
    target: str,
    command: list[str],
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Dismiss the Codex update gate if it is blocking the interactive UI."""
    if not is_codex_command(command):
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
        )
        pane_text = pane.stdout.lower() if pane.returncode == 0 else ""
        if _looks_like_codex_update_prompt(pane_text):
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True

        if pane_text and "openai codex" in pane_text:
            return False

        time.sleep(poll_interval_seconds)

    return False


def _wait_for_cli_ready(
    target: str,
    timeout_seconds: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll tmux pane until an interactive CLI shows an input prompt.

    Uses two complementary heuristics:

    1. **Prompt indicators** — common prompt characters (``❯``, ``>``,
       ``›``) or well-known hint lines in the last few visible lines.
    2. **Content stabilization** — if the pane output has stopped changing
       for two consecutive polls and contains visible text, the CLI has
       likely finished initialisation and is waiting for input.

    Returns True when ready, False on timeout (caller should still
    attempt injection as a best-effort).
    """
    deadline = time.monotonic() + timeout_seconds
    last_content = ""
    stable_count = 0

    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
        )
        if pane.returncode != 0:
            time.sleep(poll_interval)
            continue

        text = pane.stdout
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        tail = lines[-10:] if len(lines) >= 10 else lines

        for line in tail:
            # Claude Code shows these prompt characters when ready
            if line.startswith(("❯", ">", "›")):
                return True
            # Also detect the "Try ..." hint line
            if "Try " in line and "write a test" in line:
                return True

        if text == last_content and lines:
            stable_count += 1
            if stable_count >= 2:
                return True
        else:
            stable_count = 0
            last_content = text

        time.sleep(poll_interval)
    time.sleep(fallback_delay)
    return False


def _wait_for_tui_ready(
    target: str,
    timeout: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 0.5,
) -> None:
    """Poll the tmux pane until the TUI appears ready, then return.

    This is used for interactive CLIs that still rely on tmux send-keys prompt
    injection. When readiness is not detected before ``timeout``, we keep the
    previous fallback behaviour and sleep for ``fallback_delay`` seconds.
    """
    ready_hints = ("╭", "╔", "┌", "│", "║", "✓", ">", "❯", "›")
    time.sleep(0.5)

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and any(hint in result.stdout for hint in ready_hints):
            return
        time.sleep(poll_interval)

    time.sleep(fallback_delay)


def _inject_prompt_via_buffer(
    target: str,
    agent_name: str,
    prompt: str,
) -> None:
    """Inject a prompt into a tmux pane via ``load-buffer`` / ``paste-buffer``.

    Using a temp file avoids the shell-escaping pitfalls of ``send-keys`` for
    multi-line or special-character prompts. Two Enter keystrokes are sent
    after the paste to confirm and submit.
    """
    buf_name = f"prompt-{agent_name}"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="clawteam-prompt-"
    ) as f:
        f.write(prompt)
        tmp_path = f.name

    try:
        subprocess.run(
            ["tmux", "load-buffer", "-b", buf_name, tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-b", buf_name, "-t", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Claude interactive mode needs Enter twice after paste:
        # first to confirm the pasted text, second to submit.
        time.sleep(0.5)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.3)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tmux", "delete-buffer", "-b", buf_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        os.unlink(tmp_path)


def _tmux_unavailable_message(context: str) -> str:
    """Return a helpful error when tmux is unavailable."""
    if is_windows():
        if context == "attach":
            return (
                "Error: tmux is not available on this system. "
                "On Windows, use 'clawteam board serve' for live monitoring or run ClawTeam inside WSL for tmux support."
            )
        return (
            "Error: tmux is not available on this system. "
            "On Windows, use the subprocess backend ('clawteam spawn subprocess ...') or run ClawTeam inside WSL for tmux support."
        )
    return "Error: tmux not installed"
