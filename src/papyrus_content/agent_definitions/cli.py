"""``papyrus agents``: ``validate`` checks a folder of agent definition files with no network, no sign-in and no model (slice D1, PPY-68abaa);
``apply`` applies the definitions to a site as its deploy does (slice D2, PPY-df3e74, ``release.py``).

Later slices add the other ``papyrus agents`` commands (set-rung, runbook, explain) to this group.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from papyrus_content.images.cli import ERROR_EXIT_CODE
from papyrus_content.images.handlers import error_envelope

from . import definition, release

GROUP = "agents"
VALIDATE_USAGE = ("Usage: papyrus agents validate --dir DIR [--core DIR]\n"
                  "  Check the agent definition files in DIR (one <id>.yaml each) with no network and no model. A site's files may extend the engine's core\n"
                  "  definitions (or those in --core) with instructions and must-never rules; nothing else may change and no rule may be removed.\n"
                  "  Exits 0 when every definition is valid and 2 when any is refused, naming each problem by definition and line.")


APPLY_USAGE = ("Usage: papyrus agents apply [--dir DIR] [--core DIR] [--root DIR] [--site-registry FILE] [--dry-run | --check]\n"
               "  Apply the agent definitions to the site as its deploy does, after the procedures are registered. It first checks every definition as\n"
               "  `papyrus agents validate` does and that each names a registered procedure, and stops with a plain error before any write when one does not.\n"
               "  Each definition becomes the registered copy on an automation named for it (created disabled when the site has none; the same digest writes\n"
               "  nothing, a changed one writes the next version); a definition gone from Git is retired, disabled and given no schedule, its history kept.\n"
               "  It never writes the agent policy document and never adopts an automation: a new agent arrives at the rung off.\n"
               f"  --dir is the site's folder of definitions (default ./{release.SITE_FOLDER} under --root, when it exists; the core definitions alone otherwise);\n"
               "  --root is the site's checkout (default the current folder), where papyrus-site-procedures.json is read. --dry-run reads the site and says what\n"
               "  would change; --check also exits 2 when anything differs from Git. Run it as the operator (PAPYRUS_GRAPHQL_AUTH=iam).")


def route_tree() -> dict:
    return {"validate": {}, "apply": {}}


def usage_for(words: list[str]) -> str | None:
    return {"validate": VALIDATE_USAGE, "apply": APPLY_USAGE}.get(" ".join(words))


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


def _client():
    from papyrus_content.graphql_authoring import create_authoring_client

    return create_authoring_client()[0]


def apply_command(argv: list[str], stdout: TextIO | None = None, client_factory=None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(APPLY_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    def refuse(message: str, code: str = "invalid_input", **details) -> int:
        return finish(error_envelope("agents_apply", code, message, details=details), ERROR_EXIT_CODE)

    values: dict[str, str] = {}
    dry_run = check = False
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--dry-run":
            dry_run = True
        elif word == "--check":
            check = True
        elif word in ("--dir", "--core", "--root", "--site-registry") and rest:
            values[word] = rest.pop(0)
        else:
            return refuse(f"{word} is not a flag of agents apply, or has no value.", path=word)
    if dry_run and check:
        return refuse("agents apply takes --check or --dry-run, not both: both read only, --check also fails on a difference.")
    root = Path(values.get("--root", "."))
    site_folder = Path(values["--dir"]) if "--dir" in values else root / release.SITE_FOLDER
    if "--dir" in values and not site_folder.is_dir():
        return refuse(f"The folder of definitions {site_folder} is not there.", path="--dir")
    registry = Path(values["--site-registry"]) if "--site-registry" in values else root / "papyrus-site-procedures.json"
    if "--site-registry" not in values and not registry.is_file():
        registry = None
    core = Path(values["--core"]) if "--core" in values else definition.CORE_DIRECTORY
    try:
        definitions = release.load(site_folder if site_folder.is_dir() else None, core)
        procedures = release.known_procedures(registry)
        client = (client_factory or _client)()
        if check:
            results, action = release.check_drift(client, definitions, procedures), "check"
        else:
            results, action = release.apply_release(client, definitions, procedures, apply=not dry_run), "dry-run" if dry_run else "apply"
    except release.ReleaseDriftError as error:
        return refuse(str(error), "constraint_conflict")
    except release.ReleaseError as error:
        return refuse(str(error))
    return finish({"ok": True, "op": "agents_apply", "result": {"action": action, "definitions": results}, "warnings": []}, 0)


def command(argv: list[str], stdout: TextIO | None = None) -> int:
    if argv[:1] == ["validate"]:
        return validate_command(argv[1:], stdout)
    if argv[:1] == ["apply"]:
        return apply_command(argv[1:], stdout)
    out = stdout or sys.stdout
    out.write(json.dumps(error_envelope("agents", "unknown_operation", f"{' '.join(argv) or '(nothing)'} is not an agents command; try: validate, apply.", details={"command": " ".join(argv)}), indent=2) + "\n")
    return ERROR_EXIT_CODE
