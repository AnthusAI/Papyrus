"""``papyrus images ...`` and ``papyrus guidelines ...``: a thin adapter over the operation table (the group is the operation's ``group``). It turns flags into the operation's input, runs ``execute`` and prints the
envelope as JSON. Which flags exist comes from ``cli_generated.COMMANDS`` (generated from the table), so nothing about an operation is written here.

Exit code: 0 when the operation succeeded, 2 for any error envelope (the operator-facing code the other commands use). The JSON says which error.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from papyrus_content.actor_identity import ACTOR_KIND_VARIABLE, actor_kind

from .cli_generated import COMMANDS
from .handlers import Caller, Handler, Outcome, error_envelope, execute

ERROR_EXIT_CODE = 2
PICTURE_KEY = "_picture"   # parse() keeps the path --file names here for an operation that uploads a picture; command() replaces it with the attachment id


def commands_of(group: str) -> list[dict]:
    return [entry for entry in COMMANDS if entry["group"] == group]


def route_tree(group: str = "images") -> dict:
    """The words under ``papyrus <group>`` as nested dicts, a leaf being {} (the shape ``papyrus --help`` walks)."""
    tree: dict = {}
    for entry in commands_of(group):
        node = tree
        for word in entry["words"]:
            node = node.setdefault(word, {})
    return tree


def usage_for(words: list[str], group: str = "images") -> str | None:
    for entry in commands_of(group):
        if entry["words"] == words:
            return f"Usage: {entry['usage']}\n  {entry['summary']}"
    return None


def caller_from(environ: Mapping[str, str]) -> Caller:
    return Caller(kind=actor_kind(environ))


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
        elif flag == "--file" and spec.get("picture"):
            values[PICTURE_KEY] = take(flag, inline)
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
            raise _BadFlags(f"{flag} is not a flag of papyrus {spec['group']} {' '.join(spec['words'])}.", flag)
    if len(positional) > len(spec["positional"]):
        raise _BadFlags(f"Unexpected argument {positional[len(spec['positional'])]!r}.", "arguments")
    for field, raw in zip(spec["positional"], positional):
        values[field] = raw
    return {**base, **values}, dry_run


def signed_in_uploader(path: str, kind: str) -> str:
    from papyrus_content.graphql_authoring import create_authoring_client

    from .upload import upload_picture

    return upload_picture(create_authoring_client()[0], path, kind)


#: operation -> (input field, environment variable): a secret the command line takes from the environment or standard input, never from a flag
SECRET_INPUTS = {"announcements_account_set_app": ("clientSecret", "PAPYRUS_X_CLIENT_SECRET")}
REDACTED = "(hidden)"
#: operation -> (input field, question): asked at a terminal when the flag is left out
PROMPTED_INPUTS = {"announcements_account_set_app": ("clientId", "X app client ID: ")}


def ask_visible(question: str) -> str:
    sys.stderr.write(question)
    sys.stderr.flush()
    return sys.stdin.readline().strip()


def ask_hidden(question: str) -> str:
    import getpass

    return getpass.getpass(question).strip()


def command(argv: list[str], *, group: str = "images", handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None,
            stdout: TextIO | None = None, previews: Mapping[str, str] | None = None, uploader: Callable[[str, str], str] | None = None,
            stdin: TextIO | None = None, preflight: Callable[[], None] | None = None) -> int:
    """Run ``papyrus <group> <argv>`` and print the JSON envelope. ``handlers``, ``environ`` and ``uploader`` are for tests and later front ends.

    ``previews`` maps a write operation to the read operation its ``--dry-run`` runs, so a dry run shows what would change instead of echoing the input.
    """
    out = stdout or sys.stdout
    environ = os.environ if environ is None else environ

    def finish(envelope: dict) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return 0 if envelope["ok"] else ERROR_EXIT_CODE

    spec, used = None, 0
    for entry in commands_of(group):
        size = len(entry["words"])
        if argv[:size] == entry["words"] and size > used:
            spec, used = entry, size
    if spec is None:
        asked = f"papyrus {group} " + " ".join(argv[:3])
        return finish(error_envelope(group, "unknown_operation", f"There is no {group} command: {asked.strip()}.", details={"command": asked.strip()}))
    try:
        arguments, dry_run = parse(spec, argv[used:])
    except _BadFlags as bad:
        return finish(error_envelope(spec["op"], "invalid_input", str(bad), details={"path": bad.path}))
    caller = caller_from(environ)
    secret = SECRET_INPUTS.get(spec["op"])
    if preflight is not None and not dry_run and (secret or spec["op"] in PROMPTED_INPUTS):
        try:
            preflight()   # the site and the sign-in, checked before anything is asked: no one types a secret for a command that cannot run
        except Exception as unavailable:
            return finish(error_envelope(spec["op"], "service_unavailable", str(unavailable)))
    source = stdin if stdin is not None else sys.stdin
    asked = PROMPTED_INPUTS.get(spec["op"])
    if asked and asked[0] not in arguments and source.isatty():
        value = ask_visible(asked[1])
        if value:
            arguments[asked[0]] = value
    if secret and secret[0] not in arguments:
        value = (environ.get(secret[1]) or "").strip()
        if not value and not source.isatty():
            value = source.read().strip()
        if not value and source.isatty():
            value = ask_hidden("X app client secret (hidden): ")
        if value:
            arguments[secret[0]] = value
    picture = arguments.pop(PICTURE_KEY, None)
    if picture is not None:
        if dry_run:
            arguments[spec["picture"]] = "(not uploaded: dry run)"
        else:
            from .upload import PictureError, describe_picture

            kind = arguments.get("kind")
            if kind not in ("exemplar", "negative"):
                return finish(error_envelope(spec["op"], "invalid_input", "Say whether the picture is an exemplar or a negative (--kind) before uploading it.", details={"path": "kind"}))
            try:
                describe_picture(picture, kind)   # refuse a wrong type or size before asking the backend for anything
                arguments[spec["picture"]] = (uploader or signed_in_uploader)(picture, kind)
            except PictureError as bad:
                return finish(error_envelope(spec["op"], "invalid_input", str(bad), details={"path": "file"}))
    if dry_run and secret and secret[0] in arguments:
        arguments = {**arguments, secret[0]: REDACTED}
    if dry_run:
        # Check the input and the caller exactly as a real call would, then stop before the handler: nothing is sent, nothing is spent.
        envelope = execute(spec["op"], arguments, caller, handlers={spec["op"]: _dry_run_handler})
        preview = (previews or {}).get(spec["op"])
        if preview and envelope["ok"]:
            asked = {name: arguments[name] for name in ("kind", "section", "language", "document") if name in arguments}
            shown = execute(preview, asked, caller, handlers)
            if not shown["ok"]:
                return finish(shown)
            envelope["result"]["preview"] = {"op": preview, **shown["result"]}
        return finish(envelope)
    return finish(execute(spec["op"], arguments, caller, handlers))


def _dry_run_handler(arguments: dict, caller: Caller):
    return Outcome(result={"dryRun": True, "input": arguments}, publication="")

