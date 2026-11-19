"""``papyrus announcements where|recent|explain|dry-run|pause|resume|withdraw|settings show|settings set|account status|review ...``: a thin adapter over the operation table, like ``papyrus guidelines``."""
from __future__ import annotations

from typing import Mapping, TextIO

from papyrus_content.images import cli as images_cli
from papyrus_content.images.handlers import Handler

GROUP = "announcements"


def route_tree() -> dict:
    return images_cli.route_tree(GROUP)


def usage_for(words: list[str]) -> str | None:
    return images_cli.usage_for(words, GROUP)


def default_handlers() -> dict[str, Handler]:
    """Every announcements operation that is built, on the signed-in lane: the settings and the X rows, the review policy (PPY-97c0f2), and the list, a Story's lines and
    ``explain`` (PPY-e4ae3a). They are the operation table's own handlers (``images/handlers.py``), so a person at a terminal, an agent's tool and the console door all reach the same code."""
    from papyrus_content.images.handlers import HANDLERS
    from papyrus_content.images.operations import OPERATIONS

    names = {operation.name for operation in OPERATIONS if operation.group == GROUP}
    return {name: handler for name, handler in HANDLERS.items() if name in names}


def command(argv: list[str], *, handlers: dict[str, Handler] | None = None, environ: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    if handlers is None:
        handlers = default_handlers()
    return images_cli.command(argv, group=GROUP, handlers=handlers, environ=environ, stdout=stdout)
