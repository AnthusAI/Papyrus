"""Site rules: small publication-only documents that a site owns and Papyrus code merely reads (PPY-804b7b and the other Anthus-defaults stories).

A *site rule* is a guideline kind with no section layer. It is saved, versioned and read exactly like the other guideline documents (``papyrus guidelines save
--kind NAME``), and its defaults live here as one neutral, honest value that applies until the site saves its own. ``read_rule`` answers the document in force
and where it came from, so every reader can say whether it used the default or the site's own.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from .document import Field, GuidelineError, KindSpec, Problem, kind_spec, register_kind, validate_document
from .store import GuidelineStore


def publication_only_validator(kind: str, fields: dict[str, Field], after: Callable[[dict], list[Problem]] | None = None) -> Callable[[Any, str], list[Problem]]:
    """A validator for a kind that has only a publication document: an object with schemaVersion 1 and the declared fields, checked one by one."""
    def validate(document: Any, scope: str) -> list[Problem]:
        if scope != "publication":
            return [Problem("", f"The {kind} rules belong to the publication; a section has none.", "publication_only")]
        if not isinstance(document, dict):
            return [Problem("", "A rules document is an object.")]
        problems = [Problem("schemaVersion", "must be 1")] if document.get("schemaVersion") != 1 else []
        for key, value in document.items():
            if key == "schemaVersion":
                continue
            definition = fields.get(key)
            if definition is None:
                problems.append(Problem(key, "is not a field of these rules", "unknown_field"))
            elif (message := definition.check(value)):
                problems.append(Problem(key, message))
        return problems + (after(document) if after and not problems else [])
    return validate


def register_rule_kind(name: str, fields: dict[str, Field], after: Callable[[dict], list[Problem]] | None = None) -> KindSpec:
    return register_kind(KindSpec(name, name, 1, validate=publication_only_validator(name, fields, after), layers=False))


def read_rule(store: Any, kind: str, defaults: dict[str, Any], guidelines: GuidelineStore | None = None) -> dict[str, Any]:
    """``{document, source, reference}``: the site's saved document laid over ``defaults``, field by field, or the defaults alone.

    ``source`` is ``"site"`` when the site has a saved document and ``"default"`` otherwise. A document that cannot be read raises ``GuidelineError``;
    the caller decides whether that stops its work (nothing here guesses).
    """
    kind_spec(kind)
    found = (guidelines or GuidelineStore(store)).read(kind)
    if found is None:
        return {"document": copy.deepcopy(defaults), "source": "default", "reference": None}
    document = {**copy.deepcopy(defaults), **{key: value for key, value in found["document"].items() if key != "schemaVersion"}}
    return {"document": document, "source": "site", "reference": found["reference"]}


__all__ = ["GuidelineError", "publication_only_validator", "read_rule", "register_rule_kind", "validate_document"]
