"""``papyrus images ...``: a thin adapter over the operation table. It turns flags into the operation's input, runs ``execute`` and prints the
envelope as JSON. Which flags exist comes from ``cli_generated.COMMANDS`` (generated from the table), so nothing about an operation is written here.

Exit code: 0 when the operation succeeded, 2 for any error envelope (the operator-facing code the other commands use). The JSON says which error.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, TextIO

from .cli_generated import COMMANDS
from .handlers import Caller, Handler, Outcome, error_envelope, execute

ACTOR_KIND_VARIABLE = "PAPYRUS_ACTOR_KIND"   # "agent" for procedures, automations and agent shells; anything else is a person (design section 3.6)
ERROR_EXIT_CODE = 2


def route_tree() -> dict:
    """The words under ``papyrus images`` as nested dicts, a leaf being {} (the shape ``papyrus --help`` walks)."""
    tree: dict = {}
    for entry in COMMANDS:
        node = tree
        for word in entry["words"]:
            node = node.setdefault(word, {})
    return tree


def usage_for(words: list[str]) -> str | None:
    for entry in COMMANDS:
        if entry["words"] == words:
            return f"Usage: {entry['usage']}\n  {entry['summary']}"
    return None


def caller_from(environ: Mapping[str, str]) -> Caller:
    return Caller(kind="agent" if environ.get(ACTOR_KIND_VARIABLE, "").strip().lower() == "agent" else "person")


class _BadFlags(Exception):
    def __init__(self, message: str, path: str):
        super().__init__(message)
        self.path = path


def _read_document(path: str, flag: str) -> Any:
    try:
        import yaml

        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))   # JSON is YAML, so one reader covers both
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _BadFlags(f"Could not read {path} for {flag}: {error}", flag) from error


def _convert(entry: dict, raw: str) -> Any:
    if entry["kind"] == "integer":
        try:
            return int(raw)
        except ValueError:
            raise _BadFlags(f"{entry['flag']} needs a whole number, not {raw!r}.", entry["flag"]) from None
    return raw


def parse(spec: dict, tokens: list[str]) -> tuple[dict, bool]:
    """The operation input the tokens ask for, and whether --dry-run was given."""
    by_flag = {entry["flag"]: entry for entry in spec["flags"]}
    booleans = {entry["flag"][2:]: entry for entry in spec["flags"] if entry["kind"] == "boolean"}
    values: dict = {}
    positional: list[str] = []
    dry_run = False
    base: dict = {}
    pending = list(tokens)

    def take(flag: str, inline: str | None) -> str:
        if inline is not None:
            return inline
        if not pending or pending[0].startswith("--"):
            raise _BadFlags(f"{flag} needs a value.", flag)
        return pending.pop(0)

    while pending:
        token = pending.pop(0)
        if not token.startswith("--"):
            positional.append(token)
            continue
        flag, _, inline = token.partition("=")
        inline = inline if "=" in token else None
        if flag == "--dry-run" and spec["effect"] != "read":
            dry_run = True
        elif flag == "--input-file":
            document = _read_document(take(flag, inline), flag)
            if not isinstance(document, dict):
                raise _BadFlags("--input-file must hold a JSON object.", flag)
            base = document
        elif flag == "--file" and spec["file"]:
            values[spec["file"]] = _read_document(take(flag, inline), flag)
        elif flag.startswith("--no-") and flag[5:] in booleans:
            values[booleans[flag[5:]]["field"]] = False
        elif flag in by_flag and by_flag[flag]["kind"] == "boolean":
            values[by_flag[flag]["field"]] = True
        elif flag in by_flag:
            entry = by_flag[flag]
            raw = take(flag, inline)
            if entry["kind"] == "target":
                values[entry["field"]] = {"kind": entry["targetKind"], "lineageId": raw}
            elif entry["kind"] == "array":
                values.setdefault(entry["field"], []).append(raw)
            else:
                values[entry["field"]] = _convert(entry, raw)
        else:
            raise _BadFlags(f"{flag} is not a flag of papyrus images {' '.join(spec['words'])}.", flag)
    if len(positional) > len(spec["positional"]):
        raise _BadFlags(f"Unexpected argument {positional[len(spec['positional'])]!r}.", "arguments")
    for field, raw in zip(spec["positional"], positional):
        values[field] = raw
    return {**base, **values}, dry_run


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None,
            stdout: TextIO | None = None) -> int:
    """Run ``papyrus images <argv>`` and print the JSON envelope. ``handlers`` and ``environ`` are for tests and later front ends."""
    out = stdout or sys.stdout
    environ = os.environ if environ is None else environ

    def finish(envelope: dict) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return 0 if envelope["ok"] else ERROR_EXIT_CODE

    spec, used = None, 0
    for entry in COMMANDS:
        size = len(entry["words"])
        if argv[:size] == entry["words"] and size > used:
            spec, used = entry, size
    if spec is None:
        asked = "papyrus images " + " ".join(argv[:3])
        return finish(error_envelope("images", "unknown_operation", f"There is no image command: {asked.strip()}.", details={"command": asked.strip()}))
    try:
        arguments, dry_run = parse(spec, argv[used:])
    except _BadFlags as bad:
        return finish(error_envelope(spec["op"], "invalid_input", str(bad), details={"path": bad.path}))
    caller = caller_from(environ)
    if dry_run:
        # Check the input and the caller exactly as a real call would, then stop before the handler: nothing is sent, nothing is spent.
        envelope = execute(spec["op"], arguments, caller, handlers={spec["op"]: _dry_run_handler})
        return finish(envelope)
    return finish(execute(spec["op"], arguments, caller, handlers))


def _dry_run_handler(arguments: dict, caller: Caller):
    return Outcome(result={"dryRun": True, "input": arguments}, publication="")

