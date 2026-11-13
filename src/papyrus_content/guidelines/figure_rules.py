"""A site's figure rules (PPY-cbc0f3): the whole text of how its diagrams, charts and illustrations are drawn.

Papyrus ships general rules (``data/figures/rules.md``) that name roles and no brand. A site may save its own figure rules, a document with one field,
``bodyMarkus``, the complete text. A site's rules **replace** the packaged ones for that site, so a publication with different needs (for example, no generated
image ever shows a real person) owns the wording instead of working around a general file. Nothing is merged: what an agent reads is one text, and
``figureRules`` says which. Image prompts are built from the site's own image profile (``images/prompt_skeleton.py``), never from this text.
"""
from __future__ import annotations

from typing import Any

from .document import Field, text
from .site_rules import read_rule, register_rule_kind

KIND = "figure-rules"

register_rule_kind(KIND, {"bodyMarkus": Field(text, "prose")})


def figure_rules(store: Any, packaged: str, guidelines: Any = None) -> dict[str, Any]:
    """``{text, source, reference}``: the site's own rules when it saved them, else the ``packaged`` default."""
    found = read_rule(store, KIND, {"bodyMarkus": packaged}, guidelines)
    return {"text": found["document"]["bodyMarkus"], "source": found["source"], "reference": found["reference"]}
