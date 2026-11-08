"""``papyrus topics ...``: a thin adapter over the operation table, the same shape as ``papyrus images``.

It turns flags into the operation's input with the image command's parser (which flags exist comes from ``cli_generated.COMMANDS``, generated from
the table), runs ``execute`` and prints the envelope as JSON. Exit code 0 when the operation succeeded, 2 for any error envelope.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Mapping, TextIO

from papyrus_content.images.cli import ERROR_EXIT_CODE, _BadFlags, caller_from, parse
from papyrus_content.images.handlers import Handler

from .cli_generated import COMMANDS
from .handlers import error_envelope, execute, signed_in_handlers


def route_tree() -> dict:
    """The words under ``papyrus topics`` as nested dicts, a leaf being {} (the shape ``papyrus --help`` walks)."""
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


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    """Run ``papyrus topics <argv>`` and print the JSON envelope. ``handlers`` and ``environ`` are for tests."""
    out = stdout or sys.stdout
    environ = os.environ if environ is None else environ

    def finish(envelope: dict) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return 0 if envelope["ok"] else ERROR_EXIT_CODE

    spec = next((entry for entry in COMMANDS if argv[:len(entry["words"])] == entry["words"]), None)
    if spec is None:
        asked = ("papyrus topics " + " ".join(argv[:3])).strip()
        return finish(error_envelope("topics", "unknown_operation", f"There is no topics command: {asked}.", details={"command": asked}))
    try:
        arguments, _ = parse(spec, argv[len(spec["words"]):])
    except _BadFlags as bad:
        return finish(error_envelope(spec["op"], "invalid_input", str(bad), details={"path": bad.path}))
    return finish(execute(spec["op"], arguments, caller_from(environ), handlers if handlers is not None else signed_in_handlers()))
