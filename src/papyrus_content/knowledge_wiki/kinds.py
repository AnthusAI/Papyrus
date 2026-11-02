"""Which entity kinds belong in a public wiki, and how a name reads on a page.

A site's semantic graph also holds nodes that are bookkeeping, not subjects: the editorial concepts a comment is filed
under, quality ratings, relevance decisions, coverage questions, editorial forms. They are accepted nodes like any other,
so a wiki that publishes every accepted node publishes them. These kinds are never public, whatever a vocabulary says.

Paper authors (``personAuthor``) are public only when the site's vocabulary names the kind. A site that gives the sync
its vocabulary publishes the kinds that vocabulary declares and nothing else; with no vocabulary the sync publishes
every kind except the bookkeeping ones and the authors.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from ..knowledge_snapshot.keys import kind_key
from ..options import normalize_string

#: Bookkeeping kinds of the semantic graph. Never public.
INTERNAL_KINDS = frozenset(
    kind_key(kind) for kind in ("commentConcept", "qualityRating", "relevanceDecision", "coverageQuestion", "editorialForm")
)
#: Hidden unless the vocabulary names them.
OPT_IN_KINDS = frozenset({kind_key("personAuthor")})
#: Kinds that name a person: a compacted name (``AaronCohen``) is spaced again.
PERSON_KINDS = frozenset({kind_key("personAuthor"), "person", "author"})

_LOWER_UPPER = re.compile(r"(?<=[a-z])(?=[A-Z])")
_UPPER_RUN = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


def vocabulary_kinds(text: str) -> tuple[str, ...]:
    """The entity kinds a vocabulary file declares, in the form of ``kind_key``. Empty when the file declares none."""
    loaded = yaml.safe_load(text) if text and text.strip() else None
    declared = loaded.get("entity_kinds") if isinstance(loaded, dict) else None
    keys: list[str] = []
    for entry in declared or ():
        key = entry.get("key") if isinstance(entry, dict) else entry
        if isinstance(key, str) and kind_key(key) and kind_key(key) not in keys:
            keys.append(kind_key(key))
    return tuple(keys)


def parse_kind_list(value: str | Iterable[str] | None) -> tuple[str, ...] | None:
    """A comma separated list of kinds (``--public-kinds``), in the form of ``kind_key``; ``None`` for no list."""
    if value is None:
        return None
    parts = value.split(",") if isinstance(value, str) else list(value)
    kinds = tuple(dict.fromkeys(kind_key(part) for part in parts if kind_key(part)))
    return kinds or None


def is_public_kind(kind: str, allowed: Iterable[str] | None = None) -> bool:
    """Whether an entity of ``kind`` gets a public page. ``allowed`` is the kinds of the site's vocabulary, or ``None`` for no vocabulary."""
    key = kind_key(kind)
    if not key or key in INTERNAL_KINDS:
        return False
    if allowed is None:
        return key not in OPT_IN_KINDS
    return key in {kind_key(entry) for entry in allowed}


def display_name(name: str, kind: str) -> str:
    """The name as a page shows it. A person's name that arrived without spaces (``AlexanderMRush``) is spaced again."""
    text = " ".join(str(name or "").split())
    if kind_key(kind) not in PERSON_KINDS or not text or " " in text:
        return text
    spaced = _UPPER_RUN.sub(" ", _LOWER_UPPER.sub(" ", text))
    return re.sub(r"\bMc (?=[A-Z])", "Mc", spaced)  # McDonald is one word


def public_kinds_of(options: Mapping[str, Any]) -> tuple[str, ...] | None:
    """The kinds that get pages: ``--public-kinds a,b``, else the entity kinds of ``--vocabulary FILE``, else ``None`` (every kind but the bookkeeping ones and the authors)."""
    listed = parse_kind_list(normalize_string(options.get("public-kinds")))
    if listed is not None:
        return listed
    path = normalize_string(options.get("vocabulary"))
    if not path:
        return None
    kinds = vocabulary_kinds(Path(path).read_text(encoding="utf-8"))
    if not kinds:
        raise ValueError(f"--vocabulary {path} declares no entity kinds; refusing to publish every kind.")
    return kinds
