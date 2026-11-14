"""``papyrus guidelines show|resolve|diff|save|history``: the guideline operations as commands (PPY-8d41d7).

A thin adapter, like ``papyrus images``: the flags come from ``images/cli_generated.COMMANDS`` (generated from the operation table), the handlers are the
signed-in lane's (the person's own session; the backend applies their rights), and the output is the shared JSON envelope. ``save`` writes unless
``--dry-run``; a dry run reads the current guidelines and prints the diff, and saves nothing. ``--help`` is answered from the table and sends nothing.
"""
from __future__ import annotations

from typing import Mapping, TextIO

from papyrus_content.images import cli as images_cli
from papyrus_content.images.handlers import Handler

GROUP = "guidelines"
PREVIEWS = {"guidelines_save": "guidelines_diff"}


def route_tree() -> dict:
    return images_cli.route_tree(GROUP)


def usage_for(words: list[str]) -> str | None:
    return images_cli.usage_for(words, GROUP)


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    if handlers is None:
        from .handlers import signed_in_handlers

        handlers = signed_in_handlers()
    return images_cli.command(argv, group=GROUP, handlers=handlers, environ=environ, stdout=stdout, previews=PREVIEWS)
