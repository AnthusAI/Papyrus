"""Laying a section's guideline document, and a language's overlays, over the publication's, field by field, by the rule each field has in its kind's table
(``document.py``). The publication's voice and binding constraints are written once and apply in every language; a language overlay adds only what is
particular to that language (PPY-d0132d).

Nothing here names a kind or a field: the rules are the table's. The answer says where every field came from (``fieldSources``) and which versions were
used (``layers``), so a draft can always be traced to the exact guidelines it was written with.
"""
from __future__ import annotations

import copy
from typing import Any

from .document import AVOID, CHOICE, CONSTRAINTS, EXEMPLARS, GLOSSARY, JOIN, LEXICON, PROSE, PUBLICATION_ONLY, GuidelineError, kind_spec
from .store import GuidelineStore

PUBLICATION, SECTION, LANGUAGE, SECTION_LANGUAGE = "publication", "section", "language", "section-language"


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


def lay_over(kind: str, publication: dict, publication_version: int, overlays: list[tuple[dict | None, dict]]) -> tuple[dict, dict, list[dict]]:
    """(document, fieldSources, warnings): each overlay laid over the publication's document in turn, by the rule each field has.

    ``overlays`` are ``(document, source)`` pairs, most general first: a section's document, a language overlay, a section's language overlay. ``source`` is
    what ``fieldSources`` records for a field the overlay set (``{"layer": "section", "version": 3}``, ``{"layer": "language", "language": "zh-Hans",
    "version": 1}``). Binding constraints and locks are the publication's alone, in every layer."""
    fields = kind_spec(kind).fields
    locked = set(publication.get("locked") or [])
    document: dict[str, Any] = {key: copy.deepcopy(value) for key, value in publication.items() if key not in ("schemaVersion",) and _present(value)}
    sources: dict[str, list[dict]] = {key: [{"layer": PUBLICATION, "version": publication_version}] for key in document}
    warnings: list[dict] = []

    for overlay, entry in overlays:
        layer = entry["layer"]

        def add(key: str, merged: Any) -> None:
            had = key in document
            document[key] = merged
            sources[key] = (sources[key] if had else []) + [dict(entry)]

        for key, value in (overlay or {}).items():
            definition = fields.get(key)
            if key == "schemaVersion" or definition is None or not _present(value):
                continue
            rule = definition.rule
            if rule == CONSTRAINTS:
                warnings.append({"code": f"{layer.replace('-', '_')}_constraint_ignored", "field": key,
                                 "message": f"A {layer.replace('-', ' ')} layer cannot set binding constraints; only the publication's guidelines do. Its constraints were ignored."
                                 if layer != SECTION else "A section cannot set binding constraints; only the publication's guidelines do. The section's were ignored."})
            elif rule == PUBLICATION_ONLY:
                continue   # `locked` and the legacy publication-only fields: not an overlay's to set (a save refuses them; stored data is ignored)
            elif rule == CHOICE:
                if key in locked:
                    if value != publication.get(key):
                        warnings.append({"code": "locked_field_ignored", "field": key, "message": f"The publication locks {key}; the {layer.replace('-', ' ')}'s value was ignored."})
                else:
                    document[key] = copy.deepcopy(value)
                    sources[key] = [dict(entry)]
            elif rule in (PROSE, JOIN, AVOID):
                add(key, _prose(document.get(key), value) if rule == PROSE else _join(document.get(key) or [], value))
            elif rule == GLOSSARY:
                add(key, _glossary(document.get(key) or [], value, key in locked))
            elif rule == EXEMPLARS:
                add(key, _exemplars(document.get(key) or [], value))
            elif rule == LEXICON:
                add(key, _lexicon(document.get(key) or {}, value))
    return document, sources, warnings


def _layer(scope: str, found: dict, language: str | None = None) -> dict:
    return {"scope": scope, **({"language": language} if language else {}), **{k: found["reference"][k] for k in ("itemId", "slug", "versionNumber", "contentHash")}}


def resolve_guidelines(store: GuidelineStore, kind: str, section: str | None = None, language: str | None = None) -> dict:
    """The effective guidelines of ``kind`` for the publication, or for ``section`` laid over it, and for text in ``language``.

    The layers, most general first: the publication's document (voice, audience, binding constraints: written once, for every language), the section's,
    then for a language each of its language overlays (a variant's base language first: ``es`` then ``es-419``), then the section's own overlays for that
    language. An overlay holds only what is particular to the language: words to prefer and avoid, register notes, the locale's naming conventions, glossary
    entries. Without ``language`` the answer has the layers every language shares.

    ``{kind, section, language?, found, document, fieldSources, layers, warnings}``. A publication with no document of this kind resolves to nothing with the
    warning ``<kind>_guidelines_missing`` and is never refused. A layer with no document of its own adds nothing.
    """
    spec = kind_spec(kind)
    if not spec.layers:
        raise GuidelineError("resolver_not_available", f"{kind} guidelines are resolved by their own resolver, not this one.")
    answer: dict[str, Any] = {"kind": kind, "section": section, **({"language": language} if language else {}),
                              "found": False, "document": {}, "fieldSources": {}, "layers": [], "warnings": []}
    base = store.read(kind)
    if base is None:
        answer["warnings"].append({"code": f"{kind}_guidelines_missing", "message": f"This publication has no {kind} guidelines yet. Nothing was applied."})
        return answer
    layers = [_layer(PUBLICATION, base)]
    overlays: list[tuple[dict | None, dict]] = []

    def take(scope: str, found: dict | None, entry: dict) -> None:
        if found is None:
            return
        layers.append(_layer(scope, found, entry.get("language")))
        overlays.append((found["document"], {**entry, "version": found["reference"]["versionNumber"]}))

    if section:
        take(SECTION, store.read(kind, section), {"layer": SECTION})
    tags = language_overlay_tags(language) if language else ()
    for tag in tags:
        take(LANGUAGE, store.read(kind, None, language=tag), {"layer": LANGUAGE, "language": tag})
    if section:
        for tag in tags:
            take(SECTION_LANGUAGE, store.read(kind, section, language=tag), {"layer": SECTION_LANGUAGE, "language": tag})
    document, sources, warnings = lay_over(kind, base["document"], base["reference"]["versionNumber"], overlays)
    answer.update(found=True, document=document, fieldSources=sources, layers=layers, warnings=warnings)
    return answer


def language_overlay_tags(language: str) -> tuple[str, ...]:
    """The language overlays text in ``language`` reads, base language first (``es-419``: ``es``, ``es-419``). Refuses a language Humanus has no pack for."""
    from papyrus_content.editorial_languages import languages_served

    return languages_served(language)[1:]


def resolve_image_guidelines(store: GuidelineStore, section: str | None = None) -> dict:
    """The image guidelines of the publication, with a section's own image types and type preferences added when a section is named.

    The same shape as ``resolve_guidelines``. The effective guidance for one picture (a use, an image type, a Story) is the image resolver's
    (``papyrus images profile resolve``); this is the layered document it starts from, with ``fieldSources`` saying which image types came from the section."""
    from papyrus_content.images.visual_style import section_type_keys, with_section_types

    answer: dict[str, Any] = {"kind": "image", "section": section, "found": False, "document": {}, "fieldSources": {}, "layers": [], "warnings": []}
    base = store.read("image")
    if base is None:
        answer["warnings"].append({"code": "image_guidelines_missing", "message": "This publication has no image guidelines yet. Nothing was applied."})
        return answer
    reference_keys = ("itemId", "slug", "versionNumber", "contentHash")
    layers = [{"scope": PUBLICATION, **{k: base["reference"][k] for k in reference_keys}}]
    document = copy.deepcopy(base["document"])
    sources: dict[str, Any] = {key: [{"layer": PUBLICATION, "version": base["reference"]["versionNumber"]}] for key in document if key != "schemaVersion"}
    overlay = store.read("image", section) if section else None
    if overlay:
        layers.append({"scope": SECTION, **{k: overlay["reference"][k] for k in reference_keys}})
        version = overlay["reference"]["versionNumber"]
        style = {name: value for name, value in overlay["document"].items() if name not in ("schemaVersion", "bodyMarkus")}
        own = section_type_keys(document, style)
        merged, _ = with_section_types(document, style)
        document["imageTypes"], document["typePreference"] = merged.get("imageTypes", {}), merged.get("typePreference", {})
        for key in own:
            sources[f"imageTypes.{key}"] = [{"layer": SECTION, "version": version}]
        if own or style.get("typePreference"):
            sources["typePreference"] = [{"layer": PUBLICATION, "version": base["reference"]["versionNumber"]}, {"layer": SECTION, "version": version}]
        if overlay["document"].get("bodyMarkus"):
            document["bodyMarkus"] = "\n\n".join(part for part in (document.get("bodyMarkus"), overlay["document"]["bodyMarkus"]) if part)
            sources["bodyMarkus"] = [{"layer": PUBLICATION, "version": base["reference"]["versionNumber"]}, {"layer": SECTION, "version": version}]
    answer.update(found=True, document=document, fieldSources=sources, layers=layers)
    return answer
