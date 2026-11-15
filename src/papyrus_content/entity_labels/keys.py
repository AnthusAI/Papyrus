"""The keys of a EntityLabel. Pure, no I/O.

``fold`` is how two spellings of one name are the same name: Unicode compatibility form (full-width letters, ligatures), case folded, white space collapsed.
The tenant goes in front of every key a shared stack stores (``tenant_knowledge_keys.global_key``); a dedicated stack keeps them bare.
"""
from __future__ import annotations

import unicodedata

from ..tenant_knowledge_keys import global_key

PREFERRED, ALIAS, HIDDEN = "preferred", "alias", "hidden"
ROLES = (PREFERRED, ALIAS, HIDDEN)

CURRENT, STALE, CONFLICT, HELD = "current", "stale", "conflict", "held"
WORK_STATES = (STALE, CONFLICT, HELD)   # a label in one of these carries a workKey; a current one does not


def fold(text: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())


CONCEPT, SECTION = "concept", "section"
KINDS = (CONCEPT, SECTION)


def entity_key(kind: str, entity_id: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"A label belongs to a {' or a '.join(KINDS)}, not a {kind}.")
    return f"{kind}#{entity_id}"


def label_id(key: str, language: str, role: str = PREFERRED, text: str | None = None) -> str:
    """``{entityKey}#{language}`` for the preferred name, ``{entityKey}#{language}#{role}#{folded text}`` for any other."""
    if role == PREFERRED:
        return f"{key}#{language}"
    if role not in ROLES or not fold(text):
        raise ValueError(f"A {role} label of {key} needs its text.")
    return f"{key}#{language}#{role}#{fold(text)}"


def name_key(language: str, text: str, tenant_id: str | None = None, kind: str = CONCEPT) -> str:
    """The same name is two keys for a concept and for a section: ``Safety`` the concept is not ``Safety`` the section."""
    folded = fold(text)
    if not folded:
        raise ValueError("A name is empty.")
    return global_key(f"{kind}#{language}#{folded}", tenant_id)


def sort_key(language: str, role: str, text: str) -> str:
    return f"{language}#{role}#{fold(text)}"


def work_key(language: str, state: str, tenant_id: str | None = None, kind: str = CONCEPT) -> str | None:
    """The sparse index key of a label that needs work, or None for one that does not."""
    return global_key(f"{kind}#{language}#{state}", tenant_id) if state in WORK_STATES else None
