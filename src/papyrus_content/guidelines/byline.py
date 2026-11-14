"""The site's byline policy (PPY-804b7b): who a story may be credited to.

The default is the honest rule: agent work is attributed to "AI", and no human author is invented. A site that publishes under pen names (satire) saves its own
policy with ``mode: pen-names`` and the names it uses. The policy reaches the writer as a layer of its context pack; Papyrus code does not otherwise decide who
signs a story.
"""
from __future__ import annotations

from typing import Any

from .document import Field, Problem, text, texts
from .site_rules import read_rule, register_rule_kind

KIND = "byline"
MODES = ("honest", "pen-names")
DEFAULT = {"mode": "honest"}


def _mode(value: Any) -> str | None:
    return None if value in MODES else f"must be one of {', '.join(MODES)}"


def _after(document: dict) -> list[Problem]:
    mode = document.get("mode", "honest")
    if mode == "pen-names" and not document.get("penNames"):
        return [Problem("penNames", "a pen-names policy needs at least one pen name")]
    if mode == "honest" and document.get("penNames"):
        return [Problem("penNames", "pen names need mode pen-names")]
    return []


register_rule_kind(KIND, {"mode": Field(_mode, "choice"), "penNames": Field(texts, "join"), "note": Field(text, "prose")}, _after)


def byline_policy(store: Any, guidelines: Any = None) -> dict[str, Any]:
    return read_rule(store, KIND, DEFAULT, guidelines)


def byline_text(document: dict) -> str:
    """The policy as plain text for the writer."""
    if document.get("mode") == "pen-names":
        names = ", ".join(document["penNames"])
        lines = [f"This publication publishes under pen names. Put one of these names in the story's `author` front matter: {names}.",
                 "A pen name is never a real person's name, and a story never claims to be written by a real person who did not write it."]
    else:
        lines = ['Attribute agent work to "AI" (`drafting: {by: AI}` in the front matter). Name a human in `author` only if that person worked on the story.',
                 "Never invent an author."]
    if document.get("note"):
        lines.append(str(document["note"]).strip())
    return "\n".join(lines)
