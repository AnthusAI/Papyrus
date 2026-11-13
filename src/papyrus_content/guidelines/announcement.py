"""The site's announcement voice (PPY-64378c): how a post on the publication's X account sounds, beyond its writing guidelines.

A publication-only site rule, saved like the others (``papyrus guidelines save --kind announcement``). The post is drafted under the site's writing guidelines
(voice, audience, binding rules) and these rules. The wording of a site's voice is data; nothing here names a site.
"""
from __future__ import annotations

from typing import Any

from .document import Field, texts
from .site_rules import read_rule, register_rule_kind

KIND = "announcement"
DEFAULT: dict[str, Any] = {}

register_rule_kind(KIND, {"rules": Field(texts, "prose"), "examples": Field(texts, "join"), "avoid": Field(texts, "join")})


def announcement_rules(store: Any, guidelines: Any = None) -> dict[str, Any]:
    return read_rule(store, KIND, DEFAULT, guidelines)


def announcement_text(document: dict) -> str:
    """The rules as plain text for the drafting model."""
    lines: list[str] = []
    for label, key in (("Rules for announcement posts", "rules"), ("Words and moves to avoid", "avoid"), ("Examples of posts in this voice", "examples")):
        if document.get(key):
            lines += [f"{label}:", *(f"- {item}" for item in document[key])]
    return "\n".join(lines)
