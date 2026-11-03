"""The Story types a site offers, read from the site's own ``projection.json``.

A Story has a type (``article``, ``post``, ``guide``, anything a site names). Nothing in the engine lists the types: every Item type outside the fixed
system set (``SYSTEM_ITEM_TYPES`` in ``content_item_lifecycle``) is a Story type. What a site *offers* an editor, and which type a new Story gets, is declared
in ``web/projection.json``, the file the projector already reads, so the newsroom and the Python code read one source:

.. code-block:: json

    "storyTypes": { "default": "article", "types": ["article", "post"] }

Both keys are optional. With no default, a new Story has no type until an editor picks one (it is stored as ``untyped``, ``UNTYPED_ITEM_TYPE``, and cannot
be published until it has one). With no ``types`` the offered types are the default, when there is one, plus every type the site gives a URL base in ``urls.types``. ``lib/site-story-types.ts`` derives the same ``default`` and ``types`` from the same JSON; ``scripts/fixtures/story-types-cases.json``
holds the cases both test suites run.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .content_item_lifecycle import SYSTEM_ITEM_TYPES, UNTYPED_ITEM_TYPE

SITE_STATIC_DIRECTORY_ENV = "PAPYRUS_SITE_STATIC_DIR"
PROJECTION_SETTINGS_FILE = "projection.json"
TYPE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class StoryTypes:
    default: str | None
    offered: tuple[str, ...]


def require_story_type(item_type: object, where: str = "A Story type") -> str:
    """A lowercase type name that is not a system type; anything else is an error naming ``where``."""
    name = str(item_type or "")
    if not TYPE_NAME.match(name):
        raise ValueError(f"{where} is a lowercase name such as 'article' or 'guide', not {item_type!r}.")
    if name == UNTYPED_ITEM_TYPE:
        raise ValueError(f"{where} cannot be {name!r}: that is the value of a Story with no type yet, not a type to choose.")
    if name in SYSTEM_ITEM_TYPES:
        raise ValueError(f"{where} cannot be {name!r}: that type is not a Story ({', '.join(SYSTEM_ITEM_TYPES)} are system types).")
    return name


def story_types_from_mapping(raw: Mapping | None) -> StoryTypes:
    """The default and the offered types of a ``projection.json`` mapping (the whole file, or just its ``storyTypes`` and ``urls`` keys)."""
    raw = raw or {}
    declared = dict(raw.get("storyTypes") or {})
    unknown = set(declared) - {"default", "types"}
    if unknown:
        raise ValueError(f"Unknown storyTypes settings: {', '.join(sorted(unknown))}")
    default = require_story_type(declared["default"], "storyTypes.default") if declared.get("default") is not None else None
    listed = declared.get("types")
    if listed is not None:
        offered = tuple(dict.fromkeys(require_story_type(name, "storyTypes.types entries") for name in listed))
        if default is not None and default not in offered:
            raise ValueError(f"storyTypes.default {default!r} is not one of storyTypes.types ({', '.join(offered)}).")
        return StoryTypes(default, offered)
    routed = [str(name) for name in dict((raw.get("urls") or {}).get("types") or {}) if str(name) not in SYSTEM_ITEM_TYPES]
    return StoryTypes(default, tuple(dict.fromkeys([*([default] if default else []), *routed])))


def read_projection_settings(static_directory: Path | None) -> dict:
    path = static_directory / PROJECTION_SETTINGS_FILE if static_directory is not None else None
    return json.loads(path.read_text(encoding="utf-8")) if path is not None and path.is_file() else {}


def site_story_types(environ: Mapping[str, str] | None = None) -> StoryTypes:
    """The site's Story types: from the ``projection.json`` in ``PAPYRUS_SITE_STATIC_DIR``, or no types and no default when there is none."""
    environment = os.environ if environ is None else environ
    directory = (environment.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
    return story_types_from_mapping(read_projection_settings(Path(directory) if directory else None))


def default_story_type(environ: Mapping[str, str] | None = None) -> str | None:
    """The site's default Story type (``storyTypes.default``), or ``None`` when it names none."""
    return site_story_types(environ).default


def type_for_new_story(environ: Mapping[str, str] | None = None) -> str:
    """The type a new Story is stored with: the site's default, else ``UNTYPED_ITEM_TYPE`` (an editor picks one before it is published)."""
    return default_story_type(environ) or UNTYPED_ITEM_TYPE
