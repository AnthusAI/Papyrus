"""`--help` / `-h` for every command, answered once before any command runs.

The dispatchers call `wants_help` on the tokens they were given and, when it is true, print usage and return without
signing in, building a backend client, or reading or writing anything. No command parses `--help` itself, so a new
command cannot forget to; and because mutation commands write by default, a `--help` that reached one would perform the write.
"""
from __future__ import annotations

import sys
from collections.abc import Iterable

HELP_FLAGS = frozenset({"--help", "-h"})


def wants_help(tokens: Iterable[str]) -> bool:
    return any(token in HELP_FLAGS for token in tokens)


def ported_commands(group: str) -> list[str]:
    from .cli import PORTED_COMMANDS

    return sorted(route.split(":", 1)[1] for route in PORTED_COMMANDS if route.split(":", 1)[0] == group)


def content_command_help(args: list[str]) -> int:
    """Usage for `<group> [<command>]` of the content dispatcher (args may include the help flag). Returns the exit status."""
    path = [token for token in args if token not in HELP_FLAGS][:2]
    if not path:
        from .cli import print_usage

        print_usage()
        return 0
    group = path[0]
    names = ported_commands(group)
    if not names:
        print("Usage: papyrus <group> <command> [options]", file=sys.stderr)
        raise ValueError(f"Unsupported papyrus group: {group}")  # no site hint: that reads the sign-in registry
    if len(path) == 1:
        print(f"Usage: papyrus {group} <command> [options]\n\nCommands:")
        for name in names:
            print(f"  {name}")
        return 0
    command = path[1]
    if command not in names:
        print(f"Usage: papyrus {group} <command> [options]\n\nCommands: {', '.join(names)}", file=sys.stderr)
        raise ValueError(f"Unsupported papyrus command: {group} {command}")
    print(f"Usage: papyrus {group} {command} [options]")
    try:
        from papyrus.operator.group_commands import COMMAND_USAGE
    except ImportError:
        return 0
    usage = COMMAND_USAGE.get((group, command))
    if usage:
        print(f"  {usage}")
    return 0
