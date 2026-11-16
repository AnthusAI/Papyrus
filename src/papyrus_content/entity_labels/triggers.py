"""When a concept is named in another language: only when a page in that language needs the name.

A name costs a model call and a check, and most concepts never appear on a page in a language besides the primary one. So the procedure that names a concept
(``localize_concept``) runs from triggers, and each trigger asks here whether the name is needed: a Story in a served language is tagged with the concept
(``name_concepts_for_story``). A concept with a label in that language is left alone, whatever state the label is in, except a stale one (made from words that
have since changed), which the procedure makes again. A held label is a question for a person; a trigger never asks it twice.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from .keys import CONCEPT, PREFERRED, STALE, entity_key
from .primary import lineage_of
from .store import LabelStore
from .settings import site_primary_language


def needs_name(client: Any, node: dict[str, Any], language: str) -> bool:
    rows = [row for row in LabelStore(client).of_entity(entity_key(CONCEPT, lineage_of(node)), language) if row.get("role") == PREFERRED]
    return not rows or all(row.get("syncState") == STALE for row in rows)


def name_concepts_for_story(client: Any, *, story_language: str | None, nodes: Iterable[dict[str, Any]],
                            localize: Callable[..., list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The labels made because a Story in ``story_language`` is tagged with ``nodes`` (``localize(client, node, language)`` is the procedure that makes one; the caller
    gives it, so what only records a need never loads the model code): nothing for the primary language, for a concept that already has a label, or
    for a concept written in the Story's own language."""
    if not story_language or story_language == site_primary_language(client):
        return []
    report: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("language") == story_language or not needs_name(client, node, story_language):
            continue
        report.extend(localize(client, node, story_language))
    return report
