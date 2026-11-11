"""Laying a section's guideline document over the publication's, field by field, by the rule each field has in its kind's table (``document.py``).

Nothing here names a kind or a field: the rules are the table's. The answer says where every field came from (``fieldSources``) and which versions were
used (``layers``), so a draft can always be traced to the exact guidelines it was written with.
"""
from __future__ import annotations

import copy
from typing import Any

from .document import AVOID, CHOICE, CONSTRAINTS, EXEMPLARS, GLOSSARY, JOIN, LEXICON, PROSE, PUBLICATION_ONLY, GuidelineError, kind_spec
from .store import GuidelineStore

PUBLICATION, SECTION = "publication", "section"


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _join(first: list, second: list) -> list:
    out = list(first)
    out.extend(item for item in second if item not in out)
    return out


def _prose(first: Any, second: Any) -> Any:
    if isinstance(first, str) or isinstance(second, str):
        return "\n\n".join(part for part in (first or "", second or "") if part)
    return _join(first or [], second or [])


def _glossary(base: list, extra: list, locked: bool) -> list:
    out = copy.deepcopy(base)
    index = {entry["term"]: i for i, entry in enumerate(out)}
    for entry in extra:
        if entry["term"] not in index:
            index[entry["term"]] = len(out)
            out.append(copy.deepcopy(entry))
        elif not locked:
            old = out[index[entry["term"]]]
            merged = copy.deepcopy(entry)
            avoid = _join(old.get("avoid") or [], entry.get("avoid") or [])   # a replaced entry still avoids what the publication avoids
            if avoid:
                merged["avoid"] = avoid
            out[index[entry["term"]]] = merged
    return out


def _exemplars(base: list, extra: list) -> list:
    out = copy.deepcopy(base)
    index = {entry["storyLineageId"]: i for i, entry in enumerate(out)}
    for entry in extra:
        if entry["storyLineageId"] in index:
            out[index[entry["storyLineageId"]]] = copy.deepcopy(entry)
        else:
            index[entry["storyLineageId"]] = len(out)
            out.append(copy.deepcopy(entry))
    return out


def _lexicon(base: dict, extra: dict) -> dict:
    out = {key: _join(base.get(key) or [], extra.get(key) or []) for key in ("prefer", "avoid")}
    return {key: value for key, value in out.items() if value}


def lay_over(kind: str, publication: dict, section: dict | None, publication_version: int, section_version: int | None) -> tuple[dict, dict, list[dict]]:
    """(document, fieldSources, warnings): the section's document laid over the publication's."""
    fields = kind_spec(kind).fields
    section = section or {}
    locked = set(publication.get("locked") or [])
    document: dict[str, Any] = {key: copy.deepcopy(value) for key, value in publication.items() if key not in ("schemaVersion",) and _present(value)}
    sources: dict[str, list[dict]] = {key: [{"layer": PUBLICATION, "version": publication_version}] for key in document}
    warnings: list[dict] = []

    def source(key: str, *layers: tuple[str, int | None]) -> None:
        sources[key] = [{"layer": layer, "version": version} for layer, version in layers]

    for key, value in section.items():
        definition = fields.get(key)
        if key == "schemaVersion" or definition is None or not _present(value):
            continue
        rule = definition.rule
        if rule == CONSTRAINTS:
            warnings.append({"code": "section_constraint_ignored", "field": key,
                             "message": "A section cannot set binding constraints; only the publication's guidelines do. The section's were ignored."})
        elif rule == PUBLICATION_ONLY:
            continue   # `locked` and the legacy publication-only fields: not a section's to set (a save refuses them; stored data is ignored)
        elif rule == CHOICE:
            if key in locked:
                if value != publication.get(key):
                    warnings.append({"code": "locked_field_ignored", "field": key, "message": f"The publication locks {key}; the section's value was ignored."})
            else:
                document[key] = copy.deepcopy(value)
                source(key, (SECTION, section_version))
        elif rule in (PROSE, JOIN, AVOID):
            had = key in document
            document[key] = _prose(publication.get(key), value) if rule == PROSE else _join(publication.get(key) or [], value)
            source(key, *(([(PUBLICATION, publication_version)] if had else []) + [(SECTION, section_version)]))
        elif rule == GLOSSARY:
            had = key in document
            document[key] = _glossary(publication.get(key) or [], value, key in locked)
            source(key, *(([(PUBLICATION, publication_version)] if had else []) + [(SECTION, section_version)]))
        elif rule == EXEMPLARS:
            had = key in document
            document[key] = _exemplars(publication.get(key) or [], value)
            source(key, *(([(PUBLICATION, publication_version)] if had else []) + [(SECTION, section_version)]))
        elif rule == LEXICON:
            had = key in document
            document[key] = _lexicon(publication.get(key) or {}, value)
            source(key, *(([(PUBLICATION, publication_version)] if had else []) + [(SECTION, section_version)]))
    return document, sources, warnings


def resolve_guidelines(store: GuidelineStore, kind: str, section: str | None = None) -> dict:
    """The effective guidelines of ``kind`` for the publication, or for ``section`` laid over it.

    ``{kind, section, found, document, fieldSources, layers, warnings}``. A publication with no document of this kind resolves to nothing with the warning
    ``<kind>_guidelines_missing`` and is never refused. A section with no document of its own resolves to the publication's alone.
    """
    spec = kind_spec(kind)
    if not spec.layers:
        raise GuidelineError("resolver_not_available", f"{kind} guidelines are resolved by their own resolver, not this one.")
    answer: dict[str, Any] = {"kind": kind, "section": section, "found": False, "document": {}, "fieldSources": {}, "layers": [], "warnings": []}
    base = store.read(kind)
    if base is None:
        answer["warnings"].append({"code": f"{kind}_guidelines_missing", "message": f"This publication has no {kind} guidelines yet. Nothing was applied."})
        return answer
    layers = [{"scope": PUBLICATION, **{k: base["reference"][k] for k in ("itemId", "slug", "versionNumber", "contentHash")}}]
    overlay = store.read(kind, section) if section else None
    document, sources, warnings = lay_over(kind, base["document"], overlay["document"] if overlay else None, base["reference"]["versionNumber"],
                                           overlay["reference"]["versionNumber"] if overlay else None)
    if overlay:
        layers.append({"scope": SECTION, **{k: overlay["reference"][k] for k in ("itemId", "slug", "versionNumber", "contentHash")}})
    answer.update(found=True, document=document, fieldSources=sources, layers=layers, warnings=warnings)
    return answer
