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
