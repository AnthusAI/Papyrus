"""``papyrus guidelines show|resolve|diff|save|history``: the guideline operations as commands (PPY-8d41d7).

A thin adapter, like ``papyrus images``: the flags come from ``images/cli_generated.COMMANDS`` (generated from the operation table), the handlers are the
signed-in lane's (the person's own session; the backend applies their rights), and the output is the shared JSON envelope. ``save`` writes unless
``--dry-run``; a dry run reads the current guidelines and prints the diff, and saves nothing. ``--help`` is answered from the table and sends nothing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from papyrus_content.actor_identity import actor_kind
from papyrus_content.images import cli as images_cli
from papyrus_content.images.handlers import Handler, error_envelope

GROUP = "guidelines"
PREVIEWS = {"guidelines_save": "guidelines_diff"}
DIR_OPERATIONS = ("guidelines_save", "guidelines_diff")
CHECK_USAGE = ("Usage: papyrus guidelines check --dir DIR [--scope section/ID|channel/NAME]... [--language TAG] FILE...\n"
               "  Check files against the guideline files in DIR with no network and no model. Reads only; exits 1 when an error guideline finds something.")


EXPORT_USAGE = ("Usage: papyrus guidelines export --kind KIND --dir DIR [--section KEY] [--language TAG] [--version N]\n"
                "  Write the guideline files of a kind (writing) to DIR, byte for byte as they were saved. Reads the site; changes nothing there.")
CONVERT_USAGE = ("Usage: papyrus guidelines convert [--apply] [--section KEY]... [--language TAG]...\n"
                 "  Convert this site's writing guidelines from one JSON document each to guideline files, once. Without --apply it only reports, for every lineage, whether the\n"
                 "  files read back as the same guidelines; with --apply (an admin who is a person) each lineage is saved as its next version. Run again, it converts nothing.")
DIR_NOTE = "\n  With --dir DIR the guideline files in DIR are the set (writing guidelines); the folder must hold one folder per guideline, each with GUIDELINE.md."


def route_tree() -> dict:
    return {**images_cli.route_tree(GROUP), "check": {}, "export": {}, "convert": {}}


def usage_for(words: list[str]) -> str | None:
    if words == ["check"]:
        return CHECK_USAGE
    if words == ["export"]:
        return EXPORT_USAGE
    if words == ["convert"]:
        return CONVERT_USAGE
    found = images_cli.usage_for(words, GROUP)
    return found + DIR_NOTE if found and words in (["save"], ["diff"]) else found


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


def _flags(argv: list[str], names: tuple[str, ...], switches: tuple[str, ...] = ()) -> tuple[dict[str, list[str]], list[str], str | None]:
    """``({flag: [values]}, leftover words, problem)`` for the few flags a command of this module reads itself."""
    found: dict[str, list[str]] = {}
    rest, left = list(argv), []
    while rest:
        word = rest.pop(0)
        flag, _, inline = word.partition("=")
        if flag in switches and not inline:
            found.setdefault(flag, []).append("true")
        elif flag in names:
            if inline:
                found.setdefault(flag, []).append(inline)
            elif rest and not rest[0].startswith("--"):
                found.setdefault(flag, []).append(rest.pop(0))
            else:
                return found, left, f"{flag} needs a value."
        else:
            left.append(word)
    return found, left, None


def _print(out: TextIO, envelope: dict) -> int:
    out.write(json.dumps(envelope, indent=2) + "\n")
    return 0 if envelope["ok"] else images_cli.ERROR_EXIT_CODE


def export_command(argv: list[str], handlers: dict[str, Handler], environ: Mapping[str, str] | None, stdout: TextIO | None) -> int:
    """``papyrus guidelines export``: ask the site for a kind's guidelines and write the files exactly as stored."""
    from . import files as guideline_files

    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(EXPORT_USAGE + "\n")
        return 0
    flags, left, problem = _flags(argv, ("--dir", "--kind", "--section", "--language", "--version"))
    if problem or left or "--dir" not in flags or "--kind" not in flags:
        return _print(out, error_envelope("guidelines_export", "invalid_input", problem or "Give --kind and --dir (and nothing else but --section, --language, --version).", details={"path": "--dir"}))
    arguments: dict = {"kind": flags["--kind"][-1]}
    for flag, name in (("--section", "section"), ("--language", "language")):
        if flag in flags:
            arguments[name] = flags[flag][-1]
    if "--version" in flags:
        try:
            arguments["version"] = int(flags["--version"][-1])
        except ValueError:
            return _print(out, error_envelope("guidelines_export", "invalid_input", "--version needs a whole number.", details={"path": "--version"}))
    from papyrus_content.images.handlers import execute

    envelope = execute("guidelines_get", arguments, images_cli.caller_from(os.environ if environ is None else environ), handlers)
    if not envelope["ok"]:
        return _print(out, envelope)
    files = envelope["result"].get("files")
    if files is None:
        return _print(out, error_envelope("guidelines_export", "invalid_input", f"{arguments['kind']} guidelines are one document, not guideline files; use show.", details={"path": "--kind"}))
    try:
        guideline_files.write_directory(Path(flags["--dir"][-1]), files)
    except (OSError, ValueError) as error:
        return _print(out, error_envelope("guidelines_export", "invalid_input", str(error), details={"path": "--dir"}))
    result = {"kind": arguments["kind"], "dir": flags["--dir"][-1], "files": sorted(files), "itemId": envelope["result"]["itemId"], "versionNumber": envelope["result"]["versionNumber"],
              "contentHash": envelope["result"]["contentHash"]}
    return _print(out, {"ok": True, "op": "guidelines_export", "result": result, "warnings": []})


def convert_command(argv: list[str], stdout: TextIO | None, *, client_factory: Callable[[], Any] | None = None, files: Any = None) -> int:
    """``papyrus guidelines convert``: the one-time conversion of a site's writing guidelines (``convert_v1.py``). A dry run unless ``--apply``."""
    from . import convert_v1

    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(CONVERT_USAGE + "\n")
        return 0
    flags, left, problem = _flags(argv, ("--section", "--language"), ("--apply",))
    if problem or left:
        return _print(out, error_envelope("guidelines_convert", "invalid_input", problem or f"{left[0]} is not a flag of guidelines convert.", details={"path": left[0] if left else "arguments"}))
    apply = "--apply" in flags
    from papyrus_content.images.handlers import Caller
    from papyrus_content.images.profile_handlers import identify

    if client_factory is None:
        from papyrus_content.graphql_authoring import create_authoring_client

        client_factory = lambda: create_authoring_client()[0]   # noqa: E731
    client = client_factory()
    caller = identify(client, Caller(kind=actor_kind()))
    if apply and not (caller.is_admin and caller.subject):
        return _print(out, error_envelope("guidelines_convert", "not_authorized", "Only an admin who is signed in may convert the guidelines. Nothing was saved.", details={}))
    sections = flags.get("--section") or _site_sections(client)
    languages = flags.get("--language") or _site_languages(client)
    results = convert_v1.convert_site(client, files, sections=sections, languages=languages, apply=apply, actor=caller.subject or "dry run")
    refused = [item for item in results if item["state"] == "refused"]
    summary = {state: sum(1 for item in results if item["state"] == state) for state in ("ready", "converted", "already_files", "refused")}
    return _print(out, {"ok": not refused, "op": "guidelines_convert", "result": {"applied": apply, "lineages": results, "summary": summary}, "warnings": []})


def _site_sections(client: Any) -> list[str]:
    """Every section key, enabled or not, read from the sections' own index (a small partition for each state), never by listing the table."""
    rows = [row for state in ("enabled", "disabled") for row in client.list_by_index("newsroomSectionsByEnabledStatus", state)]
    return [str(row.get("id") or "").split("#")[-1] for row in rows if row.get("id")]


def _site_languages(client: Any) -> list[str]:
    from papyrus_content.editorial_checks import GraphQLEditorialStore, settings_from
    from papyrus_content.editorial_languages import site_languages

    settings = settings_from(GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None)))
    return site_languages(settings)["enabled"]


def _with_directory(handlers: dict[str, Handler], files: dict[str, str]) -> dict[str, Handler]:
    """The handlers of a command given --dir: the save and the diff are handed the set read from the folder."""
    def wrap(handler: Handler) -> Handler:
        return lambda arguments, caller: handler({**arguments, "files": files}, caller)

    return {name: wrap(handler) if name in DIR_OPERATIONS else handler for name, handler in handlers.items()}


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    if argv[:1] == ["check"]:
        return check_command(argv[1:], stdout)
    if argv[:1] == ["convert"]:
        return convert_command(argv[1:], stdout)
    if handlers is None:
        from .handlers import signed_in_handlers

        handlers = signed_in_handlers()
    if argv[:1] == ["export"]:
        return export_command(argv[1:], handlers, environ, stdout)
    if argv[:1] in (["save"], ["diff"]) and any(word == "--dir" or word.startswith("--dir=") for word in argv):
        from . import files as guideline_files

        flags, left, problem = _flags(argv[1:], ("--dir",))
        out = stdout or sys.stdout
        if problem or len(flags.get("--dir", [])) != 1:
            return _print(out, error_envelope(f"guidelines_{argv[0]}", "invalid_input", problem or "Give --dir once.", details={"path": "--dir"}))
        directory = Path(flags["--dir"][0])
        if not directory.is_dir():
            return _print(out, error_envelope(f"guidelines_{argv[0]}", "invalid_input", f"{directory} is not a folder.", details={"path": "--dir"}))
        try:
            files = guideline_files.read_directory(directory)
        except ValueError as error:
            return _print(out, error_envelope(f"guidelines_{argv[0]}", "invalid_input", str(error), details={"path": "--dir"}))
        return images_cli.command([argv[0], *left], group=GROUP, handlers=_with_directory(handlers, files), environ=environ, stdout=stdout, previews=PREVIEWS)
    return images_cli.command(argv, group=GROUP, handlers=handlers, environ=environ, stdout=stdout, previews=PREVIEWS)
