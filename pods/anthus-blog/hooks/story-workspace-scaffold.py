#!/usr/bin/env python3
"""Scaffold a per-story workspace when a newsroom story is created."""

from __future__ import annotations

import json
import sys
from pathlib import Path

IDEA_TEMPLATE = """# Idea

## Pitch

What is the post about, and why now?

## Audience

Who should care?

## Working title

"""


def main() -> int:
    payload = json.load(sys.stdin)
    operation = payload.get("operation") or {}
    issue = operation.get("issue") or {}
    if issue.get("type") != "story":
        return 0

    story_id = issue.get("id")
    if not story_id:
        return 0

    project_root = Path(payload["mode"]["project_root"])
    workspace = project_root / "stories" / story_id
    workspace.mkdir(parents=True, exist_ok=True)

    idea_path = workspace / "idea.md"
    if not idea_path.exists():
        idea_path.write_text(IDEA_TEMPLATE, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
