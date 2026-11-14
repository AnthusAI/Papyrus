"""``papyrus announcements list|show|dry-run|pause|resume|settings show|settings set|account status``: a thin adapter over the operation table, like ``papyrus guidelines``."""
from __future__ import annotations

from typing import Mapping, TextIO

from papyrus_content.images import cli as images_cli
from papyrus_content.images.handlers import Handler

GROUP = "announcements"


def route_tree() -> dict:
    return images_cli.route_tree(GROUP)


def usage_for(words: list[str]) -> str | None:
    return images_cli.usage_for(words, GROUP)


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    if handlers is None:
        from .handlers import signed_in_handlers

        handlers = signed_in_handlers()
    return images_cli.command(argv, group=GROUP, handlers=handlers, environ=environ, stdout=stdout)
