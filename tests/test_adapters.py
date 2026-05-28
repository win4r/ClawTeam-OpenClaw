"""Tests for clawteam.spawn.adapters — CLI detection and command preparation."""

from __future__ import annotations

from unittest.mock import patch

from clawteam.spawn.adapters import (
    NativeCliAdapter,
    command_basename,
    is_hermes_command,
    is_interactive_cli,
    is_nanobot_command,
    is_opencode_command,
    is_pi_command,
    is_qwen_command,
)
from clawteam.spawn.cli_env import DockerClawteamRuntime


class TestCLIDetection:
    """Each detector must accept full paths, bare names, and reject others."""

    def test_is_qwen_command(self):
        assert is_qwen_command(["qwen"])
        assert is_qwen_command(["qwen-code"])
        assert is_qwen_command(["/usr/local/bin/qwen"])
        assert not is_qwen_command(["claude"])
        assert not is_qwen_command([])

    def test_is_opencode_command(self):
        assert is_opencode_command(["opencode"])
        assert is_opencode_command(["/opt/bin/opencode"])
        assert not is_opencode_command(["openai"])
        assert not is_opencode_command([])

    def test_is_pi_command(self):
        assert is_pi_command(["pi"])
        assert is_pi_command(["/usr/local/bin/pi"])
        assert not is_pi_command(["python"])
        assert not is_pi_command([])

    def test_is_interactive_cli_covers_all_known(self):
        for cmd in ["claude", "codex", "nanobot", "gemini", "kimi", "qwen", "opencode", "pi"]:
            assert is_interactive_cli([cmd]), f"{cmd} should be interactive"

    def test_is_nanobot_command_accepts_docker_wrapper(self):
        assert is_nanobot_command(["docker", "run", "--rm", "hkuds/nanobot"])

    def test_is_interactive_cli_rejects_unknown(self):
        assert not is_interactive_cli(["my-custom-agent"])
        assert not is_interactive_cli([])

    def test_command_basename_normalisation(self):
        assert command_basename(["/usr/local/bin/Claude"]) == "claude"
        assert command_basename([]) == ""


class TestPrepareCommandSkipPermissions:
    """Verify the skip_permissions flag maps to the correct CLI flag."""

    adapter = NativeCliAdapter()

    def test_qwen_gets_yolo(self):
        result = self.adapter.prepare_command(
            ["qwen"], skip_permissions=True,
        )
        assert "--yolo" in result.final_command

    def test_opencode_gets_yolo(self):
        result = self.adapter.prepare_command(
            ["opencode"], skip_permissions=True,
        )
        assert "--yolo" in result.final_command

    def test_claude_unchanged(self):
        result = self.adapter.prepare_command(
            ["claude"], skip_permissions=True,
        )
        assert "--dangerously-skip-permissions" in result.final_command


class TestPrepareCommandPrompt:
    """Prompt delivery: via command args or post_launch_prompt."""

    adapter = NativeCliAdapter()

    def test_qwen_prompt_via_flag(self):
        result = self.adapter.prepare_command(
            ["qwen"], prompt="do work",
        )
        assert "-p" in result.final_command
        assert "do work" in result.final_command
        assert result.post_launch_prompt is None

    def test_opencode_prompt_via_flag(self):
        result = self.adapter.prepare_command(
            ["opencode"], prompt="analyse this",
        )
        assert "-p" in result.final_command
        assert "analyse this" in result.final_command
        assert result.post_launch_prompt is None

    def test_claude_interactive_gets_post_launch_prompt(self):
        result = self.adapter.prepare_command(
            ["claude"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt == "hello"
        assert "-p" not in result.final_command

    def test_claude_noninteractive_gets_flag(self):
        result = self.adapter.prepare_command(
            ["claude"], prompt="hello", interactive=False,
        )
        assert result.post_launch_prompt is None
        assert "-p" in result.final_command

    def test_codex_interactive_gets_post_launch_prompt(self):
        result = self.adapter.prepare_command(
            ["codex"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt == "hello"
        assert "hello" not in result.final_command

    def test_codex_exec_remains_noninteractive(self):
        result = self.adapter.prepare_command(
            ["codex", "exec"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt is None
        assert "hello" in result.final_command

    def test_gemini_interactive_uses_prompt_interactive_flag(self):
        result = self.adapter.prepare_command(
            ["gemini"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt is None
        assert result.final_command == ["gemini", "-i", "hello"]

    def test_docker_wrapped_nanobot_gets_agent_workspace_and_prompt(self):
        with patch(
            "clawteam.spawn.adapters.build_docker_clawteam_runtime",
            return_value=DockerClawteamRuntime(
                mounts=(
                    ("/tmp/docker-bootstrap", "/usr/local/bin/clawteam"),
                    ("/tmp/docker-clawteam", "/usr/local/bin/clawteam-host"),
                    ("/tmp/docker-venv", "/tmp/docker-venv"),
                    ("/tmp/docker-src", "/tmp/docker-src"),
                ),
                env={
                    "CLAWTEAM_BIN": "/usr/local/bin/clawteam",
                    "CLAWTEAM_DOCKER_HOST_WRAPPER": "/usr/local/bin/clawteam-host",
                    "CLAWTEAM_DOCKER_SOURCE_ROOT": "/tmp/docker-src",
                },
            ),
        ):
            result = self.adapter.prepare_command(
                ["docker", "run", "--rm", "hkuds/nanobot"],
                prompt="hello",
                cwd="/tmp/demo",
                container_env={
                    "CLAWTEAM_DATA_DIR": "/tmp/.clawteam",
                    "CLAWTEAM_TEAM_NAME": "demo",
                    "CLAWTEAM_AGENT_NAME": "worker1",
                    "OPENAI_API_KEY": "secret-key",
                    "CLAWTEAM_BIN": "/tmp/venv/bin/clawteam",
                },
            )
        assert result.final_command[:5] == [
            "docker",
            "run",
            "--rm",
            "-w",
            "/tmp/demo",
        ]
        assert "/tmp/demo:/tmp/demo" in result.final_command
        assert "/tmp/.clawteam:/tmp/.clawteam" in result.final_command
        assert "/tmp/docker-bootstrap:/usr/local/bin/clawteam" in result.final_command
        assert "/tmp/docker-clawteam:/usr/local/bin/clawteam-host" in result.final_command
        assert "/tmp/docker-venv:/tmp/docker-venv" in result.final_command
        assert "/tmp/docker-src:/tmp/docker-src" in result.final_command
        assert "CLAWTEAM_DATA_DIR=/tmp/.clawteam" in result.final_command
        assert "CLAWTEAM_TEAM_NAME=demo" in result.final_command
        assert "CLAWTEAM_AGENT_NAME=worker1" in result.final_command
        assert "CLAWTEAM_BIN=/usr/local/bin/clawteam" in result.final_command
        assert "CLAWTEAM_DOCKER_HOST_WRAPPER=/usr/local/bin/clawteam-host" in result.final_command
        assert "CLAWTEAM_DOCKER_SOURCE_ROOT=/tmp/docker-src" in result.final_command
        assert "OPENAI_API_KEY=secret-key" in result.final_command
        assert result.final_command[-7:] == [
            "hkuds/nanobot",
            "nanobot",
            "agent",
            "-w",
            "/tmp/demo",
            "-m",
            "hello",
        ]


class TestPiCommand:
    """pi-coding-agent specific command preparation."""

    adapter = NativeCliAdapter()

    def test_pi_interactive_gets_positional_prompt(self):
        result = self.adapter.prepare_command(
            ["pi"], prompt="list files", interactive=True,
        )
        # pi takes prompt as positional arg in interactive mode (stays in TUI)
        assert result.final_command == ["pi", "list files"]
        assert result.post_launch_prompt is None

    def test_pi_noninteractive_gets_flag(self):
        result = self.adapter.prepare_command(
            ["pi"], prompt="list files", interactive=False,
        )
        assert result.post_launch_prompt is None
        assert "-p" in result.final_command
        assert "list files" in result.final_command

    def test_pi_skip_permissions_no_special_flag(self):
        result = self.adapter.prepare_command(
            ["pi"], skip_permissions=True,
        )
        # pi is minimal by design, no skip_permissions flag needed
        assert result.final_command == ["pi"]

    def test_pi_without_prompt_unchanged(self):
        result = self.adapter.prepare_command(["pi"])
        assert result.final_command == ["pi"]
        assert result.post_launch_prompt is None


class TestHermesCommandPreparation:
    """Hermes Agent: chat subcommand insertion, --source tool tag, -q prompt, --yolo."""

    adapter = NativeCliAdapter()

    def test_is_hermes_command(self):
        assert is_hermes_command(["hermes"])
        assert is_hermes_command(["/usr/local/bin/hermes"])
        assert not is_hermes_command(["claude"])
        assert not is_hermes_command([])

    def test_hermes_gets_yolo(self):
        result = self.adapter.prepare_command(
            ["hermes"], skip_permissions=True, agent_name="w1",
        )
        assert "--yolo" in result.final_command
        assert "chat" in result.final_command

    def test_hermes_chat_subcommand_inserted(self):
        result = self.adapter.prepare_command(["hermes"], agent_name="w1")
        assert result.final_command[1] == "chat"

    def test_hermes_no_duplicate_chat(self):
        result = self.adapter.prepare_command(["hermes", "chat"], agent_name="w1")
        assert result.final_command.count("chat") == 1

    def test_hermes_preserves_global_options(self):
        # If user passes hermes with global options (e.g., --profile), we must
        # NOT insert 'chat' and break the argv order. Hermes CLI shape is
        # `hermes [global-options] <command>`.
        result = self.adapter.prepare_command(
            ["hermes", "--profile", "foo"], agent_name="w1",
        )
        # chat should NOT be injected when the user passed global options
        assert "chat" not in result.final_command
        # source tag should still apply
        assert "--source" in result.final_command

    def test_hermes_preserves_alternate_subcommand(self):
        # If user passes a non-chat subcommand (e.g., `hermes sessions`),
        # we must not rewrite it as `hermes chat sessions`.
        result = self.adapter.prepare_command(["hermes", "sessions"], agent_name="w1")
        assert result.final_command[1] == "sessions"
        assert "chat" not in result.final_command

    def test_hermes_prompt_via_q_flag(self):
        result = self.adapter.prepare_command(
            ["hermes"], prompt="do work", agent_name="w1",
        )
        assert "-q" in result.final_command
        assert "do work" in result.final_command
        assert result.post_launch_prompt is None

    def test_hermes_tagged_as_tool_source(self):
        # Hermes spawns from clawteam use --source tool so they don't
        # pollute the user's session list (which defaults to cli)
        result = self.adapter.prepare_command(["hermes"], agent_name="w1")
        assert "--source" in result.final_command
        assert "tool" in result.final_command

    def test_hermes_no_continue_flag(self):
        # Hermes --continue resumes an existing session; clawteam spawns
        # are fresh, so we must not pass --continue
        result = self.adapter.prepare_command(["hermes"], agent_name="w1")
        assert "--continue" not in result.final_command

    def test_hermes_yolo_preserved_with_chat(self):
        result = self.adapter.prepare_command(
            ["hermes"], skip_permissions=True, agent_name="w1",
        )
        assert "--yolo" in result.final_command
        assert "chat" in result.final_command
        chat_idx = result.final_command.index("chat")
        assert chat_idx == 1  # chat at position 1
