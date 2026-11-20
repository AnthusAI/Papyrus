"""A site owns the whole text of its agents' role instructions (PPY-c05a3c; Ryan, 2026-11-11, reversing the add-only rule of 2026-11-08).

The document has one field, ``roles``: for each agent profile of the shared context pack (``reporter``, ``copywriter``, ``editor``, ``illustrator``) the complete
role text. A role the site writes **replaces** the engine's default for that agent; a role it leaves out keeps the default. Nothing is merged or appended, so the
site decides everything an agent is told about its job; the editorial context (mission, policy) and the layers still follow it.
"""
from __future__ import annotations

from typing import Any

from .document import Field, Problem
from .site_rules import read_rule, register_rule_kind

KIND = "agent-instructions"
PROFILES = ("reporter", "copywriter", "editor", "illustrator")


def _roles(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return "must be an object with the role text of at least one agent"
    for key, text in value.items():
        if key not in PROFILES:
            return f"has an unknown agent {key!r}; the agents are {', '.join(PROFILES)}"
        if not isinstance(text, str) or not text.strip():
            return f"the role of {key} must be text"
    return None


register_rule_kind(KIND, {"roles": Field(_roles, "choice")})


def site_roles(store: Any, guidelines: Any = None) -> dict[str, Any]:
    """``{roles, reference}``: the roles the site wrote (possibly none) and the version they came from (None when the site saved nothing)."""
    found = read_rule(store, KIND, {"roles": {}}, guidelines)
    return {"roles": found["document"]["roles"], "reference": found["reference"]}
