"""What a stored ``Item.section`` may hold: the id of a newsroom section (a topic), or nothing.

A Story's type (``article``, ``post``) and its section are two attributes. The section is a topic and is only ever the id of a
``NewsroomSection``; a site's URL layout is keyed on the type (``urls.types`` in projection.json) or on a section
(``urls.sections``). Older data holds values that are neither: the placeholder ``unsectioned``, type-shaped words such as
``articles``, and section titles written before the ids were used. This module is the one place that tells them apart;
``papyrus ops content sections`` (the migration) and the idea pipeline read it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

UNSECTIONED = "unsectioned"  # the placeholder older writers stored for "no section"; a story with no section stores nothing


def slug_of(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def match_section(rows: Iterable[Mapping[str, Any]], value: str) -> Mapping[str, Any] | None:
    """The newsroom section a stored section value means: by id, then the id's local part (after ``#``), then title or short title.

    ``None`` when nothing matches; two sections matching at the same step is an error. The hosted resolver does the same.
    """
    rows = list(rows)
    for row in rows:
        if row.get("id") == value:
            return row
    wanted = slug_of(value)
    names = lambda row: [name for name in (row.get("title"), row.get("shortTitle")) if isinstance(name, str)]
    steps = (
        lambda row: slug_of(str(row.get("id") or "").split("#")[-1]) == wanted,
        lambda row: any(name.strip().lower() == value.strip().lower() for name in names(row)),
        lambda row: any(slug_of(name) == wanted for name in names(row)),
    )
    for step in steps:
        matches = [row for row in rows if step(row)]
        if len(matches) > 1:
            raise ValueError(f'Section "{value}" is ambiguous: {", ".join(str(row.get("id")) for row in matches)}.')
        if matches:
            return matches[0]
    return None


def type_shaped_names(item_type: str | None) -> frozenset[str]:
    """The section values that only name the Item's type: ``article`` and ``articles`` for an article, ``wiki`` and ``wiki-pages`` for a wiki page."""
    if not item_type:
        return frozenset()
    kind = item_type.lower().replace("_", "-")
    head = kind.split("-")[0]
    return frozenset({kind, f"{kind}s", head, f"{head}s", UNSECTIONED})


def is_type_shaped(value: str | None, item_type: str | None) -> bool:
    return bool(value) and (value or "").strip().lower().replace("_", "-") in type_shaped_names(item_type)
