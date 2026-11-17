"""``papyrus agents validate``: check a folder of agent definition files with no network, no sign-in and no model (slice D1, PPY-68abaa).

Later slices add the other ``papyrus agents`` commands (set-rung, runbook, explain) to this group; this one only reads files and prints.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from papyrus_content.images.cli import ERROR_EXIT_CODE
from papyrus_content.images.handlers import error_envelope

from . import definition

GROUP = "agents"
VALIDATE_USAGE = ("Usage: papyrus agents validate --dir DIR [--core DIR]\n"
                  "  Check the agent definition files in DIR (one <id>.yaml each) with no network and no model. A site's files may extend the engine's core\n"
                  "  definitions (or those in --core) with instructions and must-never rules; nothing else may change and no rule may be removed.\n"
                  "  Exits 0 when every definition is valid and 2 when any is refused, naming each problem by definition and line.")


def route_tree() -> dict:
    return {"validate": {}}


def usage_for(words: list[str]) -> str | None:
    return VALIDATE_USAGE if words == ["validate"] else None


def validate_command(argv: list[str], stdout: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(VALIDATE_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    directory, core, rest = None, None, list(argv)
    while rest:
        word = rest.pop(0)
        if word in ("--dir", "--core") and rest:
            value = rest.pop(0)
            if word == "--dir":
                directory = value
            else:
                core = value
        else:
            return finish(error_envelope("agents_validate", "invalid_input", f"{word} is not a flag of agents validate, or has no value.", details={"path": word}), ERROR_EXIT_CODE)
    if directory is None:
        return finish(error_envelope("agents_validate", "invalid_input", "Give --dir with the definition files.", details={"path": "--dir"}), ERROR_EXIT_CODE)
    loaded = definition.load_sets(Path(directory), Path(core) if core else definition.CORE_DIRECTORY)
    if loaded.problems:
        return finish(error_envelope("agents_validate", "invalid_input", f"The definitions in {directory} are refused; fix them first.",
                                     details={"problems": [problem.as_dict() for problem in loaded.problems]}), ERROR_EXIT_CODE)
    result = {"definitions": [{"id": item.id, "responsibility": item.responsibility, "source": item.source, "extended": item.extended,
                               "operations": item.data["operations"], "mustNever": item.must_never} for item in loaded.definitions]}
    return finish({"ok": True, "op": "agents_validate", "result": result, "warnings": []}, 0)


def command(argv: list[str], stdout: TextIO | None = None) -> int:
    if argv[:1] == ["validate"]:
        return validate_command(argv[1:], stdout)
    out = stdout or sys.stdout
    out.write(json.dumps(error_envelope("agents", "unknown_operation", f"{' '.join(argv) or '(nothing)'} is not an agents command; try: validate.", details={"command": " ".join(argv)}), indent=2) + "\n")
    return ERROR_EXIT_CODE
