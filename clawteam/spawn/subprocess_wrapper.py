"""Small wrapper that runs an agent command and reports its exit."""

from __future__ import annotations

import argparse
import subprocess
import sys

from clawteam.team.lifecycle import handle_agent_exit


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
        handle_agent_exit(args.team, args.agent)

    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
