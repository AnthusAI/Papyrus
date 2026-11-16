"""``papyrus guidelines show|resolve|diff|save|history``: the guideline operations as commands (PPY-8d41d7).

A thin adapter, like ``papyrus images``: the flags come from ``images/cli_generated.COMMANDS`` (generated from the operation table), the handlers are the
signed-in lane's (the person's own session; the backend applies their rights), and the output is the shared JSON envelope. ``save`` writes unless
``--dry-run``; a dry run reads the current guidelines and prints the diff, and saves nothing. ``--help`` is answered from the table and sends nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, TextIO

from papyrus_content.images import cli as images_cli
from papyrus_content.images.handlers import Handler, error_envelope

GROUP = "guidelines"
PREVIEWS = {"guidelines_save": "guidelines_diff"}
CHECK_USAGE = ("Usage: papyrus guidelines check --dir DIR [--scope section/ID|channel/NAME]... [--language TAG] FILE...\n"
               "  Check files against the guideline files in DIR with no network and no model. Reads only; exits 1 when an error guideline finds something.")


def route_tree() -> dict:
    return {**images_cli.route_tree(GROUP), "check": {}}


def usage_for(words: list[str]) -> str | None:
    return CHECK_USAGE if words == ["check"] else images_cli.usage_for(words, GROUP)


def check_command(argv: list[str], stdout: TextIO | None = None) -> int:
    """``papyrus guidelines check``: the offline half of the guideline file form. It reads files and prints; it never connects to a site."""
    from . import files as guideline_files

    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(CHECK_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    directory, scopes, language, targets, rest = None, [], None, [], list(argv)
    while rest:
        word = rest.pop(0)
        if word in ("--dir", "--scope", "--language") and rest:
            value = rest.pop(0)
            if word == "--dir":
                directory = value
            elif word == "--language":
                language = value
            else:
                scopes.append(value)
        elif word.startswith("--"):
            return finish(error_envelope("guidelines_check", "invalid_input", f"{word} is not a flag of guidelines check, or has no value.", details={"path": word}), images_cli.ERROR_EXIT_CODE)
        else:
            targets.append(word)
    if directory is None or not targets:
        return finish(error_envelope("guidelines_check", "invalid_input", "Give --dir with the guideline folders and at least one file to check.", details={"path": "--dir"}), images_cli.ERROR_EXIT_CODE)
    for scope in scopes:
        if guideline_files._SCOPE.match(scope) is None or scope == "publication":
            return finish(error_envelope("guidelines_check", "invalid_input", f"{scope!r} is not a scope to add: use section/<id> or channel/<name>.", details={"path": "--scope"}), images_cli.ERROR_EXIT_CODE)
    missing = [target for target in targets if not Path(target).is_file()]
    if missing:
        return finish(error_envelope("guidelines_check", "invalid_input", f"Not a file: {', '.join(missing)}.", details={"path": "FILE"}), images_cli.ERROR_EXIT_CODE)
    loaded = guideline_files.load_directory(Path(directory))
    if loaded.problems:
        return finish(error_envelope("guidelines_check", "invalid_input", f"The guidelines in {directory} are refused; fix them first.",
                                     details={"problems": [problem.as_dict() for problem in loaded.problems]}), images_cli.ERROR_EXIT_CODE)
    result = guideline_files.check_files(loaded.guidelines, [Path(target) for target in targets], scopes=scopes, language=language)
    failed = result["summary"]["errors"] > 0
    return finish({"ok": not failed, "op": "guidelines_check", "result": result, "warnings": []}, 1 if failed else 0)


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    if argv[:1] == ["check"]:
        return check_command(argv[1:], stdout)
    if handlers is None:
        from .handlers import signed_in_handlers

        handlers = signed_in_handlers()
    return images_cli.command(argv, group=GROUP, handlers=handlers, environ=environ, stdout=stdout, previews=PREVIEWS)
