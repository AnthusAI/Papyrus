"""Selecting entries by section and tag: one definition for collections, tag pages and ``::include`` listings.

A selection is data (``{"sections": ["articles"], "tags": ["posts"], "notTags": ["solutions"]}``) and it is the only
thing a listing renders from, so it is also the only thing a page that shows the listing depends on: the page is
re-rendered when the selected entries change, and not when anything else does.

``sections``  an entry in any of these sections (``@root`` is the items with no section); empty: every section
``tags``      an entry with at least one of these tags
``allTags``   an entry with every one of these tags
``notTags``   an entry with none of these tags
``types``     an entry whose Story type is one of these (``article``, ``post``, ...); empty: every listed type
``notTypes``  an entry whose Story type is none of these
Tags and types compare case-insensitively. Only listed entries (published, not drafts, of a listed type) are ever selected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SELECTION_KEYS = {"sections", "tags", "allTags", "notTags", "types", "notTypes"}


@dataclass(frozen=True)
class Selection:
    sections: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    all_tags: tuple[str, ...] = ()
    not_tags: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    not_types: tuple[str, ...] = ()

    def matches(self, entry, *, drafts: bool = False) -> bool:
        """``drafts``: the entries of draft state that the selection would pick if they were published."""
        if not (entry.draft if drafts else entry.listed):
            return False
        if self.sections and (entry.section.name if entry.section else "@root") not in self.sections:
            return False
        have = {tag.casefold() for tag in entry.tags}
        if self.tags and not have & {tag.casefold() for tag in self.tags}:
            return False
        if self.all_tags and not {tag.casefold() for tag in self.all_tags} <= have:
            return False
        if have & {tag.casefold() for tag in self.not_tags}:
            return False
        kind = entry.type.casefold()
        if self.types and kind not in {name.casefold() for name in self.types}:
            return False
        return kind not in {name.casefold() for name in self.not_types}

    def select(self, entries, *, drafts: bool = False) -> list:
        return [entry for entry in entries if self.matches(entry, drafts=drafts)]


def _names(raw: Mapping, key: str, where: str) -> tuple[str, ...]:
    value = raw.get(key, ())
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{where}.{key} must be a list of names")
    return tuple(item.strip() for item in value)


def selection_from_mapping(raw: Mapping | None, where: str) -> Selection:
    raw = dict(raw or {})
    unknown = set(raw) - SELECTION_KEYS
    if unknown:
        raise ValueError(f"Unknown {where} settings: {', '.join(sorted(unknown))}")
    return Selection(
        sections=_names(raw, "sections", where),
        tags=_names(raw, "tags", where),
        all_tags=_names(raw, "allTags", where),
        not_tags=_names(raw, "notTags", where),
        types=_names(raw, "types", where),
        not_types=_names(raw, "notTypes", where),
    )
