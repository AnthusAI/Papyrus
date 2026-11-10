"""`papyrus guide [TASK | --list]`: print the agent CLI guide (docs/agent-cli-guide.md), whole or one task's section.

Read only; it needs no sign-in and no network. The text is the packaged copy `data/agent-cli-guide.md`; a test fails when it differs
from `docs/agent-cli-guide.md`, so the guide, the CLI and the usage table cannot drift apart unnoticed.
"""
from __future__ import annotations

import re
from pathlib import Path

GUIDE_PATH = Path(__file__).parent / "data" / "agent-cli-guide.md"
MARKER = re.compile(r"^<!-- guide:([a-z0-9-]+) -->\s*$")


def guide_text() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8")


def sections(text: str | None = None) -> list[tuple[str, str, str]]:
    """Every task section as (name, heading, body), in file order. A section runs from its `## ` heading to the next one."""
    lines = (text if text is not None else guide_text()).splitlines()
    found: list[tuple[str, str, str]] = []
    for index, line in enumerate(lines):
        match = MARKER.match(line)
        if not match or match.group(1) == "top" or index == 0 or not lines[index - 1].startswith("## "):
            continue
        end = next((later for later in range(index + 1, len(lines)) if lines[later].startswith("## ")), len(lines))
        heading = lines[index - 1][3:].strip()
        found.append((match.group(1), heading, "\n".join([lines[index - 1], *lines[index + 1:end]]).rstrip() + "\n"))
    return found


def guide_command(flags: list[str]) -> None:
    """papyrus guide [TASK | --list]"""
    words = [flag for flag in flags if not flag.startswith("--")]
    unknown = [flag for flag in flags if flag.startswith("--") and flag != "--list"]
    if unknown:
        raise ValueError(f"papyrus guide takes a task name or --list, not {unknown[0]}. Usage: papyrus guide [TASK | --list]")
    parts = sections()
    if "--list" in flags:
        print("Tasks (print one with `papyrus guide TASK`; no argument prints the whole guide):")
        for name, heading, _ in parts:
            print(f"  {name.ljust(16)} {heading}")
        return
    if not words:
        print(guide_text(), end="")
        return
    wanted = words[0].lower()
    for name, _heading, body in parts:
        if name == wanted:
            print(body, end="")
            return
    raise ValueError(f"No guide task named {words[0]!r}. Tasks: {', '.join(name for name, _, _ in parts)}. `papyrus guide --list` describes them.")
