"""Entity keys and name matching."""

from __future__ import annotations

import hashlib
import re
import unicodedata

KEY_SEPARATOR = "--"
MAXIMUM_SLUG_LENGTH = 100
PUBLIC_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*--[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def kind_key(text: str) -> str:
    """The one form of an entity kind: lower case, runs of other characters one underscore (``model_family``).

    It is the form of a Biblicus vocabulary key, kept as is in nodes, the registry and the snapshot. Only the entity
    key (``model-family--tern-3``) folds the kind to hyphens, through ``slug``.
    """
    return slug(text).replace("-", "_")


def bounded_slug(text: str) -> str:
    """A slug of at most ``MAXIMUM_SLUG_LENGTH`` characters; a longer one ends in a hash of the whole text."""
    value = slug(text)
    if len(value) <= MAXIMUM_SLUG_LENGTH:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[: MAXIMUM_SLUG_LENGTH - 9].rstrip('-')}-{digest}"


def entity_key(kind: str, name: str) -> str:
    """``task--voice-cloning``: the slug of the kind, two hyphens, the slug of the name. ``""`` when either is empty."""
    kind_slug, name_slug = bounded_slug(kind), bounded_slug(name)
    return f"{kind_slug}{KEY_SEPARATOR}{name_slug}" if kind_slug and name_slug else ""


def is_public_key(key: str) -> bool:
    return bool(PUBLIC_KEY.match(key or ""))


def normalize_name(name: str) -> str:
    """Case and white space insensitive form used to match names and aliases."""
    return " ".join(unicodedata.normalize("NFKC", str(name or "")).split()).casefold()


def contains_email(text: str | None) -> bool:
    return bool(text and EMAIL.search(text))


def kind_label(kind: str) -> str:
    return kind.replace("-", " ").replace("_", " ").title()


def concept_name_part(node_key: str) -> str:
    """The name part of an entity key: ``concept--voice-cloning`` gives ``voice-cloning``. ``""`` when there is none."""
    kind_part, separator, name_part = str(node_key or "").partition(KEY_SEPARATOR)
    return name_part if kind_part and separator else ""


def concept_hashtag(node_key: str) -> str:
    """``#voice-cloning`` for ``concept--voice-cloning``. ``""`` when the key has no name part."""
    name = concept_name_part(node_key)
    return f"#{name}" if name else ""


def concept_hashtag_label(node_key: str, all_node_keys: list[str]) -> str:
    """The hashtag as shown: ``#translation``, or ``#translation (task)`` when another kind shares the name."""
    hashtag = concept_hashtag(node_key)
    if not hashtag:
        return ""
    name = concept_name_part(node_key)
    sharing_kinds = {key for key in all_node_keys if key != node_key and concept_name_part(key) == name}
    if not sharing_kinds:
        return hashtag
    kind_part = node_key.partition(KEY_SEPARATOR)[0]
    return f"{hashtag} ({kind_part})"


def concept_keys_for_hashtag(text: str, all_node_keys: list[str]) -> list[str]:
    """The node keys a typed hashtag can mean: an exact key match first, then every key with that name.

    ``#concept--voice-cloning`` names one key. ``#translation`` names every kind's ``translation``, sorted by key, and
    ``#translation (task)`` narrows that to one kind.
    """
    typed = str(text or "").strip().lstrip("#").strip().casefold()
    kind_filter = None
    if typed.endswith(")") and " (" in typed:
        typed, _, kind_text = typed[:-1].rpartition(" (")
        kind_filter = kind_text.strip()
    if not typed:
        return []
    exact = [key for key in all_node_keys if key.casefold() == typed]
    if exact:
        return exact[:1]
    named = sorted(key for key in all_node_keys if concept_name_part(key).casefold() == typed)
    if kind_filter is not None:
        named = [key for key in named if key.partition(KEY_SEPARATOR)[0].casefold() == kind_filter]
    return named
