"""What may leave the building as public text: the shapes that are scrubbed, and the address rule.

Shared by the home-page export (``home_page/export.py``) and by the writers that store a card's public fields on a Reference
(``reference_public_fields.py``), so a card field and a published record are scrubbed by one rule. Standard library only: the Lambda bundles that
write a Reference do not ship anything else.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*\.)+[A-Za-z]{2,}")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SITE_SUBJECT = re.compile(r"ss(?:1|dev)_[A-Za-z0-9_-]{8,}")
PRIVATE_SHAPES = (EMAIL, UUID, SITE_SUBJECT)


class WithheldReference(ValueError):
    """A Reference whose address cannot be made public without identity in it."""


def contains_private_shape(text: str) -> bool:
    return any(pattern.search(text) for pattern in PRIVATE_SHAPES)


def scrub(text: Any) -> str | None:
    if text is None:
        return None
    cleaned = str(text)
    for pattern in PRIVATE_SHAPES:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or None


def public_url(address: Any) -> str | None:
    """The address as it is public: a query or fragment that carries identity is dropped, and a path that does is withheld."""
    if not address:
        return None
    text = str(address).strip()
    if not contains_private_shape(text):
        return text
    parts = urlsplit(text)
    bare = parts._replace(query="", fragment="").geturl()
    if contains_private_shape(bare):
        raise WithheldReference("address carries identity")
    return bare
