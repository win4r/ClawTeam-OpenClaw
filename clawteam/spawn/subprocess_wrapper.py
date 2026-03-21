"""Small wrapper that runs an agent command and reports its exit."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from clawteam.spawn.cli_env import resolve_clawteam_executable


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a spawned agent command and report its exit.")
    parser.add_argument("--team", required=True, help="Team name")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return 2

    returncode = 1
    try:
        completed = subprocess.run(command, check=False)
        returncode = completed.returncode
    finally:
        clawteam_bin = os.environ.get("CLAWTEAM_BIN") or resolve_clawteam_executable()
        lifecycle_cmd = [
            clawteam_bin,
            "lifecycle",
            "on-exit",
            "--team",
            args.team,
            "--agent",
            args.agent,
        ]
        try:
            subprocess.run(lifecycle_cmd, check=False)
        except FileNotFoundError:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "clawteam",
                    "lifecycle",
                    "on-exit",
                    "--team",
                    args.team,
                    "--agent",
                    args.agent,
                ],
                check=False,
            )

    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
