"""The guideline document: what a saved document may hold, and the registry of document kinds.

A document has a *kind* (``writing``, ``image``, ``video``, ...). A kind is registered **data**: a name, the slug word its Item lineages use, and a
table of fields (how to check each one, how a section layers it over the site's). The store and the resolver read only that table, so adding a kind
is one ``register_kind`` call and changes neither the store nor the S3 layout (PPY-0796f2; Ryan, 2026-11-10, for video guidelines).

Validation errors are reported by field path (``lexicon.avoid[2]``), never raised one at a time, so an editor sees every problem at once.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

SCOPES = ("publication", "section")

# How a field layers: the same rule table as the image resolver (docs/plans/guidelines-as-data.md section 4).
PROSE = "prose"                    # kept in order, publication first; a section adds and never replaces
JOIN = "join"                      # lists to prefer: joined
AVOID = "avoid"                    # lists to avoid: joined; a section cannot remove an item the publication avoids
CHOICE = "choice"                  # the section wins unless the publication locks the field
GLOSSARY = "glossary"              # joined by term; a section's entry for a term replaces the publication's unless glossary is locked
EXEMPLARS = "exemplars"            # joined by story; a section's note for the same story replaces the publication's
LEXICON = "lexicon"                # prefer joined, avoid joined
CONSTRAINTS = "constraints"        # the publication's alone; a section that sets them is ignored with a warning
PUBLICATION_ONLY = "publication_only"   # not a section field at all: refused in a section document


@dataclass(frozen=True)
class Problem:
    path: str
    message: str
    code: str = "invalid_input"


class GuidelineError(Exception):
    """A refused operation. ``code``: invalid_input, unknown_kind, stale_version, not_found, document_hash_mismatch, resolver_not_available."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


@dataclass(frozen=True)
class Field:
    check: Callable[[Any], str | None]     # returns a message when the value is wrong, None when it is fine
    rule: str
    lockable: bool = False


@dataclass(frozen=True)
class KindSpec:
    name: str
    slug_word: str                         # editorial-doctrine-<slug_word>, desk-doctrine-<sectionKey>-<slug_word>
    schema_version: int = 1
    fields: dict[str, Field] = field(default_factory=dict)
    validate: Callable[[Any, str], list[Problem]] | None = None   # a kind owned by another module (image) supplies its own validation
    layers: bool = True                    # False when another module resolves this kind (image: visual_style.py)


# --- small checks -----------------------------------------------------------------------------------------------------------------------------------

def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def text(value: Any) -> str | None:
    return None if _is_text(value) else "must be a non-empty sentence"


def texts(value: Any) -> str | None:
    if not isinstance(value, list):
        return "must be a list"
    for index, item in enumerate(value):
        if not _is_text(item):
            return f"item {index + 1} must be a non-empty sentence"
    return None


def markus(value: Any) -> str | None:
    return None if isinstance(value, str) else "must be text"


def obj(value: Any) -> str | None:
    return None if isinstance(value, dict) else "must be an object"


def listing(value: Any) -> str | None:
    return None if isinstance(value, list) else "must be a list"


def voice(value: Any) -> str | None:
    if not isinstance(value, dict) or not _is_text(value.get("name")):
        return "must be an object with a name"
    return None


def lexicon(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "must be an object with prefer and avoid"
    for key, items in value.items():
        if key not in ("prefer", "avoid"):
            return f"has an unknown key {key!r}; use prefer or avoid"
        problem = texts(items)
        if problem:
            return f"{key} {problem}"
    return None


def glossary(value: Any) -> str | None:
    if not isinstance(value, list):
        return "must be a list"
    seen: set[str] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or not _is_text(entry.get("term")):
            return f"entry {index + 1} needs a term"
        if entry["term"] in seen:
            return f"the term {entry['term']!r} appears twice"
        seen.add(entry["term"])
        for key in ("use",):
            if key in entry and not _is_text(entry[key]):
                return f"entry {index + 1}: {key} must be a non-empty sentence"
        if "avoid" in entry and texts(entry["avoid"]):
            return f"entry {index + 1}: avoid must be a list of words"
    return None


def exemplars(value: Any) -> str | None:
    if not isinstance(value, list):
        return "must be a list"
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or not _is_text(entry.get("storyLineageId")):
            return f"entry {index + 1} needs a storyLineageId"
        if "note" in entry and not isinstance(entry["note"], str):
            return f"entry {index + 1}: note must be text"
    return None


def constraints(value: Any) -> str | None:
    if not isinstance(value, list):
        return "must be a list"
    seen: set[str] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or not _is_text(entry.get("id")) or not _is_text(entry.get("text")):
            return f"constraint {index + 1} needs an id and a text"
        if entry["id"] in seen:
            return f"the constraint id {entry['id']!r} appears twice"
        seen.add(entry["id"])
    return None


def _locked_check(lockable: Callable[[], set[str]]) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        problem = texts(value)
        if problem:
            return problem
        allowed = lockable()
        bad = [item for item in value if item not in allowed]
        return f"can lock only {', '.join(sorted(allowed)) or 'nothing'}; not {', '.join(bad)}" if bad else None
    return check


# --- the registry -----------------------------------------------------------------------------------------------------------------------------------

_REGISTRY: dict[str, KindSpec] = {}


def register_kind(spec: KindSpec) -> KindSpec:
    """Make a kind of guideline document known. Replaces an earlier registration of the same name. No schema, store or storage change is needed."""
    if not re.fullmatch(r"[a-z][a-z0-9-]*", spec.name) or not re.fullmatch(r"[a-z][a-z0-9-]*", spec.slug_word):
        raise ValueError("A kind name and its slug word are lowercase words joined by hyphens.")
    fields = dict(spec.fields)
    if spec.validate is None:
        if "schemaVersion" in fields:
            raise ValueError("schemaVersion is added to every kind; do not declare it.")
        fields["locked"] = Field(_locked_check(lambda: {name for name, f in fields.items() if f.lockable}), PUBLICATION_ONLY)
        spec = KindSpec(spec.name, spec.slug_word, spec.schema_version, fields, spec.validate, spec.layers)
    _REGISTRY[spec.name] = spec
    return spec


def unregister_kind(name: str) -> None:
    _REGISTRY.pop(name, None)


def kind_names() -> list[str]:
    return sorted(_REGISTRY)


def kind_spec(kind: Any) -> KindSpec:
    spec = _REGISTRY.get(kind) if isinstance(kind, str) else None
    if spec is None:
        raise GuidelineError("unknown_kind", f"Unknown guideline kind {kind!r}. Known kinds: {', '.join(kind_names())}.", {"kinds": kind_names()})
    return spec


def safe_key(value: str) -> str:
    """The section key as lib/doctrine.ts ``safeDoctrineKey`` makes it."""
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower())) or "topic"


def slug_for(kind: str, section: str | None = None, language: str | None = None) -> str:
    """editorial-doctrine-<word> for the publication, desk-doctrine-<sectionKey>-<word> for a section (mirrors lib/doctrine.ts).

    A language overlay adds ``-lang-<tag>`` (``editorial-doctrine-writing-lang-zh-hans``, ``desk-doctrine-security-writing-lang-zh-hans``)."""
    word = kind_spec(kind).slug_word
    slug = f"editorial-doctrine-{word}" if not section else f"desk-doctrine-{safe_key(section)}-{word}"
    return f"{slug}-lang-{safe_key(language)}" if language else slug


def overlay_language(kind: str, language: str | None) -> str | None:
    """The language of a language overlay, in Humanus's spelling (``zh-CN`` is ``zh-Hans``), or None for a document every language shares.

    Only a kind that layers takes an overlay; a language Humanus has no pack for is refused, naming it."""
    if not language:
        return None
    spec = kind_spec(kind)
    if not spec.layers:
        raise GuidelineError("invalid_input", f"{kind} guidelines have no language overlays.")
    from papyrus_content.editorial_languages import ANY_LANGUAGE, canonical

    try:
        tag = canonical(language)
    except LookupError as error:
        raise GuidelineError("invalid_input", str(error)) from error
    if tag == ANY_LANGUAGE:
        raise GuidelineError("invalid_input", "A language overlay names one language; leave the language out for the guidelines every language shares.")
    return tag


def digest(document: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_document(kind: str, document: Any, scope: str = "publication") -> list[Problem]:
    """Every problem with a document, by field path. An empty list means it can be saved."""
    spec = kind_spec(kind)
    if scope not in SCOPES:
        raise GuidelineError("invalid_input", f"scope must be one of {', '.join(SCOPES)}.")
    if spec.validate is not None:
        return spec.validate(document, scope)
    if not isinstance(document, dict):
        return [Problem("", "A guideline document is an object.")]
    problems: list[Problem] = []
    if document.get("schemaVersion") != spec.schema_version:
        problems.append(Problem("schemaVersion", f"must be {spec.schema_version}"))
    for key, value in document.items():
        if key == "schemaVersion":
            continue
        definition = spec.fields.get(key)
        if definition is None:
            problems.append(Problem(key, "is not a field of this kind of guidelines", "unknown_field"))
        elif scope == "section" and definition.rule == PUBLICATION_ONLY and key != "locked":
            problems.append(Problem(key, "belongs to the publication's guidelines only", "publication_only"))
        else:
            message = definition.check(value)
            if message:
                problems.append(Problem(key, message))
    return problems


# --- the kinds ---------------------------------------------------------------------------------------------------------------------------------------

# Writing: the fields of today's publications/*/style-profile.yml, so the two files validate unchanged. The last group are the legacy fields the
# Humanus policy pack reads; they belong to the publication alone.
WRITING_FIELDS: dict[str, Field] = {
    "voice": Field(voice, CHOICE, lockable=True),
    "audience": Field(text, CHOICE, lockable=True),
    "headline": Field(obj, CHOICE, lockable=True),
    "editorialAim": Field(text, CHOICE, lockable=True),
    "tone": Field(texts, PROSE),
    "sentenceStyle": Field(texts, PROSE),
    "voicePatterns": Field(texts, PROSE),
    "structure": Field(texts, PROSE),
    "evidenceRules": Field(texts, PROSE),
    "bodyMarkus": Field(markus, PROSE),
    "lexicon": Field(lexicon, LEXICON),
    "glossary": Field(glossary, GLOSSARY, lockable=True),
    "exemplars": Field(exemplars, EXEMPLARS),
    "constraints": Field(constraints, CONSTRAINTS),
    "publicationKey": Field(text, PUBLICATION_ONLY),
    "judge": Field(obj, PUBLICATION_ONLY),
    "checks": Field(obj, PUBLICATION_ONLY),
    "density": Field(obj, PUBLICATION_ONLY),
    "rules": Field(obj, PUBLICATION_ONLY),
    "compare": Field(obj, PUBLICATION_ONLY),
    "referenceSamples": Field(listing, PUBLICATION_ONLY),
}

# Video: registered and deliberately minimal (Ryan, 2026-11-10: video guidelines are an experiment). Prose, binding rules and locks only; the real
# fields are added here, as data, when the experiment says what they are.
VIDEO_FIELDS: dict[str, Field] = {
    "bodyMarkus": Field(markus, PROSE),
    "constraints": Field(constraints, CONSTRAINTS),
}


def _validate_image(document: Any, scope: str) -> list[Problem]:
    from papyrus_content.images.visual_style import validate_profile, validate_section_style

    found = validate_section_style(document) if scope == "section" else validate_profile(document)
    return [Problem(p.path, p.message, p.code) for p in found]


def _validate_design_system(document: Any, scope: str) -> list[Problem]:
    from papyrus_content.figures.records import validate_design_system_document

    return validate_design_system_document(document, scope)


register_kind(KindSpec("writing", "writing", 1, WRITING_FIELDS))
register_kind(KindSpec("video", "video", 1, VIDEO_FIELDS))
# Image documents keep their own schema and resolver (images/visual_style.py); the store keeps them the same way as any other kind, the publication's and each section's (PPY-c16829).
register_kind(KindSpec("image", "visual-style", 2, validate=_validate_image, layers=False))
# A site's design system for figures (PPY-74ef89): the mapping, tokens, worked examples and figure settings as text, its fonts as attached files. The site's alone: it
# has no section layer, and its own module (figures/records.py) validates it and reads it back.
register_kind(KindSpec("design-system", "design-system", 1, validate=_validate_design_system, layers=False))
