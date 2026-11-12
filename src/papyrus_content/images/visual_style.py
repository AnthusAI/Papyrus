"""The publication's visual style profile: what a saved document may contain, and how the layers resolve into the style for one request.

The profile is data an editor saves (a third kind of doctrine, ``editorial-doctrine-visual-style``). This module holds no style of its own: it checks
the shape of a saved document, merges and compares documents, and resolves the layers (identity, treatment, use, image type with its parents first,
section, Story) into one effective guidance with the layer every field came from. Design: project/wiki/image-toolchain.md sections 5.2 to 5.6.
Plain-language guide: docs/image-style-profiles.md.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

SCHEMA_VERSION = 2
USES = ("cover", "inline", "social")
SOURCES = ("figure-system", "stock", "generated")
IMAGE_REVIEW = ("before_publish", "after_the_fact")
DEFAULT_IMAGE_REVIEW = "before_publish"
LOCKABLE = ("sizes", "sources", "palette", "display")
# What an operation needs from the image type, and which origin the picture would have (design 5.3, 5.4).
OPERATION_SOURCE = {"generate": "generated", "search": "stock", "figure": "figure-system"}
KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

PROFILE_MISSING = ("This publication has no image style guidelines, so the style of generated images will be undefined and unpredictable. "
                   "Editors can fix this by writing style guidelines and adding example images in Administration > Policies > Visual style.")

TOP_LEVEL = frozenset({"schemaVersion", "identity", "techniques", "subjects", "treatments", "uses", "imageTypes", "typePreference", "attribution",
                       "constraints", "designSources", "generation", "locked", "imageReview", "bodyMarkus"})
TYPE_FIELDS = frozenset({"extends", "label", "description", "treatment", "use", "display", "guidance", "avoid", "techniques", "palette", "sizes",
                         "safeZones", "sources", "examples", "figureSystem", "removeFromParent", "retired"})
BASE_FIELDS = frozenset({"label", "where", "guidance", "avoid", "palette", "sizes", "safeZones", "sources", "display"})
OVERRIDE_FIELDS = frozenset({"guidance", "avoid", "palette", "sizes", "display", "safeZones", "sources", "treatment", "imageTypes"})
REMOVABLE = frozenset({"avoid", "safeZones"})


@dataclass(frozen=True)
class Problem:
    path: str
    message: str
    code: str = "invalid_input"     # or constraint_conflict


class StyleError(Exception):
    """A resolution that cannot be completed. ``code`` is one of the image operation error codes."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


# --- small helpers ---------------------------------------------------------------------------------------------------------------------------------

def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _texts(value: Any) -> bool:
    return isinstance(value, list) and all(_is_text(item) for item in value)


def as_object(value: Any) -> dict:
    """A JSON field as a dict: the stored value may be a JSON string or already parsed; anything else is empty."""
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def image_review_of(document: dict | None) -> str:
    value = (document or {}).get("imageReview")
    return value if value in IMAGE_REVIEW else DEFAULT_IMAGE_REVIEW


# --- the image type tree ----------------------------------------------------------------------------------------------------------------------------

def type_chain(types: dict, key: str) -> list[str]:
    """The type and its parents, root first. Raises StyleError on an unknown parent or a cycle (a saved profile has neither)."""
    chain: list[str] = []
    current: str | None = key
    while current is not None:
        if current in chain:
            raise StyleError("invalid_input", f"The image types {' -> '.join([*chain, current])} extend each other in a circle.")
        if current not in types:
            raise StyleError("invalid_input", f"The image type {current} does not exist.")
        chain.append(current)
        current = (types[current] or {}).get("extends")
    return list(reversed(chain))


def type_field(types: dict, key: str, field: str) -> Any:
    """The nearest value of ``field`` from the type up through its parents; None when no one sets it."""
    for name in reversed(type_chain(types, key)):
        if field in (types[name] or {}):
            return types[name][field]
    return None


def type_use(types: dict, key: str) -> str | None:
    return type_field(types, key, "use")


def type_sources(types: dict, key: str) -> list[str]:
    return list(type_field(types, key, "sources") or [])


def available_types(profile: dict, use: str) -> list[dict]:
    """The publication's types for this use that are still offered (not retired), in the order the profile lists them."""
    types = profile.get("imageTypes") or {}
    rows = []
    for key, definition in types.items():
        if definition.get("retired") or type_use(types, key) != use:
            continue
        rows.append({"key": key, "label": definition.get("label") or key, "description": definition.get("description") or "", "sources": type_sources(types, key)})
    return rows


# --- checking a document on save -------------------------------------------------------------------------------------------------------------------

def validate_profile(document: Any) -> list[Problem]:
    """Every reason this document may not be saved, in plain words. An empty list means it may."""
    problems: list[Problem] = []

    def add(path: str, message: str, code: str = "invalid_input") -> None:
        problems.append(Problem(path, message, code))

    if not isinstance(document, dict):
        return [Problem("document", "The style document must be an object.")]
    if document.get("schemaVersion") != SCHEMA_VERSION:
        add("schemaVersion", f"schemaVersion must be {SCHEMA_VERSION}.")
    for name in document:
        if name not in TOP_LEVEL:
            add(name, f"{name} is not part of a style document.")
    if "imageReview" in document and document["imageReview"] not in IMAGE_REVIEW:
        add("imageReview", f"imageReview must be one of: {', '.join(IMAGE_REVIEW)}.")
    if "bodyMarkus" in document and not isinstance(document["bodyMarkus"], str):
        add("bodyMarkus", "bodyMarkus must be text.")
    for name in ("identity", "techniques", "subjects", "treatments", "uses", "imageTypes", "attribution", "generation"):
        if name in document and not isinstance(document[name], dict):
            add(name, f"{name} must be an object.")
    from .generation_settings import check_generation

    check_generation(document.get("generation"), add)
    palette = _check_identity(document.get("identity"), add)
    _check_lists(document, add)
    _check_locked(document, add)
    treatments, uses = document.get("treatments") or {}, document.get("uses") or {}
    if isinstance(treatments, dict):
        for key, base in treatments.items():
            _check_key(f"treatments.{key}", key, add)
            _check_base(f"treatments.{key}", base, palette, add)
    if isinstance(uses, dict):
        for key, base in uses.items():
            if key not in USES:
                add(f"uses.{key}", f"A use must be one of: {', '.join(USES)}.")
            _check_base(f"uses.{key}", base, palette, add)
    constraints = _check_constraints(document.get("constraints"), treatments if isinstance(treatments, dict) else {}, add)
    types = document.get("imageTypes") if isinstance(document.get("imageTypes"), dict) else {}
    _check_types(types, document, palette, constraints, add)
    _check_preference(document.get("typePreference"), types, add)
    return problems


SECTION_TOP_LEVEL = OVERRIDE_FIELDS | {"schemaVersion", "bodyMarkus", "typePreference"}


def validate_section_style(document: Any) -> list[Problem]:
    """Every reason a section's image document may not be saved. A section may narrow and add guidance; it never sets what the publication alone owns."""
    problems: list[Problem] = []

    def add(path: str, message: str, code: str = "invalid_input") -> None:
        problems.append(Problem(path, message, code))

    if not isinstance(document, dict):
        return [Problem("document", "The section's image document must be an object.")]
    if document.get("schemaVersion") != SCHEMA_VERSION:
        add("schemaVersion", f"schemaVersion must be {SCHEMA_VERSION}.")
    for name in document:
        if name not in SECTION_TOP_LEVEL:
            add(name, f"{name} cannot be set from a section. Binding rules and what the publication forbids belong to the publication's image guidelines.")
    if "bodyMarkus" in document and not isinstance(document["bodyMarkus"], str):
        add("bodyMarkus", "bodyMarkus must be text.")
    _check_style_fields("section", {key: value for key, value in document.items() if key in OVERRIDE_FIELDS and key != "imageTypes"}, set(), add)
    aimed = document.get("imageTypes")
    if aimed is not None and not isinstance(aimed, dict):
        add("imageTypes", "imageTypes must be an object keyed by image type.")
        aimed = {}
    for key, definition in (aimed or {}).items():
        where = f"imageTypes.{key}"
        _check_key(where, key, add)
        if not isinstance(definition, dict):
            add(where, "A section's change to an image type must be an object.")
            continue
        for field in definition:
            if field == "constraints":
                add(f"{where}.constraints", "Binding rules belong to the publication only.")
            elif field not in TYPE_FIELDS:
                add(f"{where}.{field}", f"{field} is not part of an image type.")
        _check_style_fields(where, definition, set(), add)
    if "typePreference" in document and not isinstance(document["typePreference"], dict):
        add("typePreference", "typePreference must be an object keyed by use.")
    return problems


def section_style_of(section: dict | None) -> dict:
    return as_object((section or {}).get("visualStyle"))


def section_type_keys(profile: dict | None, section_style: dict) -> list[str]:
    """The image types a section's document defines that the publication does not have: types of the section's own."""
    own = (profile or {}).get("imageTypes") or {}
    return [key for key, definition in as_object(section_style.get("imageTypes")).items() if key not in own and isinstance(definition, dict)]


def with_section_types(profile: dict, section_style: dict) -> tuple[dict, list[str]]:
    """The profile with a section's own image types added and its typePreference appended to the publication's. Visible only to the one section."""
    keys = section_type_keys(profile, section_style)
    preference = {use: (None if listing is None else list(listing)) for use, listing in (profile.get("typePreference") or {}).items()}
    for use, listing in as_object(section_style.get("typePreference")).items():
        if isinstance(listing, list):
            base = preference.get(use) or []
            preference[use] = [*base, *(key for key in listing if key not in base)]
    if not keys and not as_object(section_style.get("typePreference")):
        return profile, []
    types = {**(profile.get("imageTypes") or {}), **{key: section_style["imageTypes"][key] for key in keys}}
    return {**profile, "imageTypes": types, "typePreference": preference}, keys


def validate_section_types(publication: dict | None, section_document: dict, previous: dict | None = None) -> list[Problem]:
    """What only the publication's document can decide about a section's image types: a type may not shadow a publication type, a new type is checked like any
    type (use, sources, treatment, the binding rules and locks), the section's typePreference names real types of that use, and a type, once saved in the
    section, is retired and never removed."""
    problems: list[Problem] = []
    own = (publication or {}).get("imageTypes") or {}
    aimed = as_object(section_document.get("imageTypes"))
    for key, definition in aimed.items():
        if key in own and isinstance(definition, dict):
            extra = sorted(set(definition) - OVERRIDE_FIELDS)
            if extra:
                problems.append(Problem(f"imageTypes.{key}", f"{key} is already an image type of the publication; a section may narrow it ({', '.join(sorted(OVERRIDE_FIELDS - {'imageTypes'}))}) "
                                                          f"but not redefine it ({', '.join(extra)}). Use another key for a type of the section's own.", "type_shadowed"))
    section_style = {name: value for name, value in section_document.items() if name not in ("schemaVersion", "bodyMarkus")}
    merged, keys = with_section_types(publication or {}, section_style)
    if keys and not publication:
        problems.append(Problem("imageTypes", "Save the publication's image guidelines first: a section's own image type is checked against their treatments and binding rules."))
        return problems
    if keys or section_document.get("typePreference"):
        found = validate_profile({**merged, "schemaVersion": SCHEMA_VERSION})
        wanted = tuple(f"imageTypes.{key}" for key in keys)
        problems.extend(p for p in found if p.path.startswith(wanted) or (p.path.startswith("typePreference") and section_document.get("typePreference")))
        for key in keys:
            if (merged["imageTypes"][key] or {}).get("treatment") is None and type_field(merged["imageTypes"], key, "treatment") is None:
                problems.append(Problem(f"imageTypes.{key}.treatment", f"{key} needs a treatment of the publication, its own or from the type it extends."))
    if previous is not None:
        old = [key for key in section_type_keys(publication, {"imageTypes": as_object(previous.get("imageTypes"))}) if key not in aimed]
        problems.extend(Problem(f"imageTypes.{key}", f"The section's image type {key} cannot be removed or renamed. Retire it with retired: true instead.") for key in old)
    return problems


def _check_key(path: str, key: str, add) -> None:
    if not KEY_PATTERN.match(key):
        add(path, f"{key!r} is not a valid key: use lowercase words joined by hyphens.")


def _check_identity(identity: Any, add) -> set[str]:
    names: set[str] = set()
    if not isinstance(identity, dict):
        return names
    for field in ("summary", "masterPrompt"):
        if field in identity and not isinstance(identity[field], str):
            add(f"identity.{field}", f"{field} must be text.")
    if "mood" in identity and not _texts(identity["mood"]):
        add("identity.mood", "mood must be a list of words.")
    entries = identity.get("palette", [])
    if not isinstance(entries, list):
        add("identity.palette", "palette must be a list.")
        entries = []
    for index, entry in enumerate(entries):
        where = f"identity.palette[{index}]"
        if not isinstance(entry, dict) or not _is_text(entry.get("name")) or not HEX_PATTERN.match(str(entry.get("hex") or "")):
            add(where, "A palette colour needs a name and a hex value like #1f2a44.")
            continue
        names.update(str(entry[field]) for field in ("name", "token") if entry.get(field))
    limit = identity.get("paletteLimit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        add("identity.paletteLimit", "paletteLimit must be a whole number of at least 1.")
    elif isinstance(limit, int) and len(entries) > limit:
        add("identity.palette", f"The palette has {len(entries)} colours but paletteLimit is {limit}.")
    _check_examples("identity.examples", identity.get("examples", []), add)
    return names


def _check_examples(path: str, examples: Any, add) -> None:
    if not isinstance(examples, list):
        add(path, "examples must be a list.")
        return
    for index, example in enumerate(examples):
        where = f"{path}[{index}]"
        if (not isinstance(example, dict) or not _is_text(example.get("attachmentId")) or example.get("kind") not in ("exemplar", "negative")
                or not isinstance(example.get("sendToProvider", False), bool) or not isinstance(example.get("note", ""), str)):
            add(where, "An example needs an attachmentId and a kind of exemplar or negative, with an optional note and sendToProvider yes or no.")


def _check_lists(document: dict, add) -> None:
    techniques = document.get("techniques") or {}
    if isinstance(techniques, dict):
        for field in ("preferred", "avoided"):
            if field in techniques and not _texts(techniques[field]):
                add(f"techniques.{field}", f"{field} must be a list of phrases.")
    subjects = document.get("subjects") or {}
    if isinstance(subjects, dict):
        if "never" in subjects and not _texts(subjects["never"]):
            add("subjects.never", "never must be a list of phrases.")
        if "representation" in subjects and not isinstance(subjects["representation"], str):
            add("subjects.representation", "representation must be text.")


def _check_locked(document: dict, add) -> None:
    locked = document.get("locked", [])
    if not isinstance(locked, list) or any(item not in LOCKABLE for item in locked):
        add("locked", f"locked must be a list of: {', '.join(LOCKABLE)}.")


def _check_base(path: str, base: Any, palette_names: set[str], add) -> None:
    if not isinstance(base, dict):
        add(path, "must be an object.")
        return
    for field in base:
        if field not in BASE_FIELDS:
            add(f"{path}.{field}", f"{field} is not part of a treatment or use.")
    _check_style_fields(path, base, palette_names, add)


def _check_style_fields(path: str, data: dict, palette_names: set[str], add) -> None:
    """The fields a type, a treatment or a use may set the same way."""
    if "guidance" in data and not isinstance(data["guidance"], str):
        add(f"{path}.guidance", "guidance must be text.")
    if "avoid" in data and not _texts(data["avoid"]):
        add(f"{path}.avoid", "avoid must be a list of phrases.")
    if "sizes" in data:
        sizes = data["sizes"]
        ok = (isinstance(sizes, dict) and re.match(r"^\d+(?:\.\d+)?:\d+(?:\.\d+)?$", str(sizes.get("aspectRatio") or ""))
              and all(isinstance(sizes.get(name), int) and not isinstance(sizes.get(name), bool) and sizes[name] > 0 for name in ("width", "height")))
        if not ok:
            add(f"{path}.sizes", "sizes needs an aspectRatio like 16:9 and a whole width and height.")
    if "display" in data:
        display = data["display"]
        if (not isinstance(display, dict) or ("where" in display and not isinstance(display["where"], str))
                or ("thumbnail" in display and not isinstance(display["thumbnail"], bool))
                or ("smallestWidthPx" in display and (not isinstance(display["smallestWidthPx"], int) or isinstance(display["smallestWidthPx"], bool)
                                                      or display["smallestWidthPx"] < 1))):
            add(f"{path}.display", "display takes where (text), smallestWidthPx (a whole number) and thumbnail (yes or no).")
    if "safeZones" in data:
        zones = data["safeZones"]
        if not isinstance(zones, list) or any(not isinstance(zone, dict) or not _is_text(zone.get("region")) or not _is_text(zone.get("instruction")) for zone in zones):
            add(f"{path}.safeZones", "Each safe zone needs a region and an instruction.")
    if "sources" in data:
        sources = data["sources"]
        if (not isinstance(sources, list) or not sources or len(set(sources)) != len(sources) or any(source not in SOURCES for source in sources)):
            add(f"{path}.sources", f"sources must be a list of at least one of: {', '.join(SOURCES)}, best first, with none repeated.")
    if "palette" in data:
        subset = data["palette"]
        if not _texts(subset):
            add(f"{path}.palette", "palette must be a list of colour names or tokens from the identity palette.")
        elif palette_names and not set(subset) <= palette_names:
            add(f"{path}.palette", f"These are not in the identity palette: {', '.join(sorted(set(subset) - palette_names))}.")


def _check_constraints(constraints: Any, treatments: dict, add) -> list[dict]:
    if constraints is None:
        return []
    if not isinstance(constraints, list):
        add("constraints", "constraints must be a list.")
        return []
    seen: set[str] = set()
    good: list[dict] = []
    for index, item in enumerate(constraints):
        where = f"constraints[{index}]"
        if not isinstance(item, dict) or not KEY_PATTERN.match(str(item.get("id") or "")) or not _is_text(item.get("text")):
            add(where, "A constraint needs an id (lowercase words with hyphens) and its text.")
            continue
        if item["id"] in seen:
            add(where, f"Two constraints have the id {item['id']}.")
        seen.add(item["id"])
        if "version" in item and (not isinstance(item["version"], int) or isinstance(item["version"], bool) or item["version"] < 1):
            add(f"{where}.version", "version must be a whole number of at least 1.")
        if "promptDirective" in item and not isinstance(item["promptDirective"], str):
            add(f"{where}.promptDirective", "promptDirective must be text.")
        if "promptAvoid" in item and not _texts(item["promptAvoid"]):
            add(f"{where}.promptAvoid", "promptAvoid must be a list of phrases.")
        origins = (item.get("appliesTo") or {}).get("origins", [])
        if not isinstance(origins, list) or any(origin not in ("generated", "stock", "figure-system", "figure") for origin in origins):
            add(f"{where}.appliesTo.origins", "origins must be a list of generated, stock or figure-system.")
        prohibited = (item.get("prohibits") or {}).get("treatments", [])
        if prohibited and not _texts(prohibited):
            add(f"{where}.prohibits.treatments", "treatments must be a list of treatment keys.")
        good.append(item)
    return good


def _check_types(types: dict, document: dict, palette: set[str], constraints: list[dict], add) -> None:
    treatments = document.get("treatments") or {}
    publication_avoid = _publication_never(document)
    for key, definition in types.items():
        where = f"imageTypes.{key}"
        _check_key(where, key, add)
        if not isinstance(definition, dict):
            add(where, "An image type must be an object.")
            continue
        for field in definition:
            if field == "constraints":
                add(f"{where}.constraints", "Binding rules belong to the publication only: put this under constraints at the top of the document.")
            elif field not in TYPE_FIELDS:
                add(f"{where}.{field}", f"{field} is not part of an image type.")
        for field in ("label", "description"):
            if field in definition and not isinstance(definition[field], str):
                add(f"{where}.{field}", f"{field} must be text.")
        if "retired" in definition and not isinstance(definition["retired"], bool):
            add(f"{where}.retired", "retired must be yes or no.")
        if definition.get("use") is not None and definition["use"] not in USES:
            add(f"{where}.use", f"use must be one of: {', '.join(USES)}.")
        if definition.get("treatment") is not None and definition["treatment"] not in treatments:
            add(f"{where}.treatment", f"The treatment {definition['treatment']!r} is not defined under treatments.")
        _check_style_fields(where, definition, palette, add)
        if "techniques" in definition and not isinstance(definition["techniques"], dict):
            add(f"{where}.techniques", "techniques must be an object.")
        _check_examples(f"{where}.examples", definition.get("examples", []), add)
        figure = definition.get("figureSystem")
        if figure is not None and (not isinstance(figure, dict) or any(not isinstance(value, str) for value in figure.values())):
            add(f"{where}.figureSystem", "figureSystem is an object of text values (rules, mapping, variant, renderTool, records).")
    # The tree: parents must exist, nothing may extend in a circle.
    for key, definition in types.items():
        if not isinstance(definition, dict):
            continue
        parent = definition.get("extends")
        if parent is None:
            continue
        if not isinstance(parent, str) or parent not in types:
            add(f"imageTypes.{key}.extends", f"{key} extends {parent!r}, which is not an image type in this profile.")
            continue
        seen, current = [key], parent
        while current is not None and current in types:
            if current in seen:
                add(f"imageTypes.{key}.extends", f"The image types {' -> '.join([*seen, current])} extend each other in a circle.")
                break
            seen.append(current)
            current = (types[current] or {}).get("extends") if isinstance(types[current], dict) else None
    # What each type is once it has taken what its parents give.
    sound: dict[str, list[str]] = {}
    for key, definition in types.items():
        try:
            if isinstance(definition, dict):
                sound[key] = type_chain(types, key)
        except StyleError:
            pass
    for key, chain in sound.items():
        definition = types[key]
        use, sources = type_use(types, key), type_sources(types, key)
        if use is None:
            add(f"imageTypes.{key}.use", f"{key} needs a use (cover, inline or social), its own or from the type it extends.")
        if not sources:
            add(f"imageTypes.{key}.sources", f"{key} needs sources (figure-system, stock, generated), its own or from the type it extends.")
        _check_remove_from_parent(key, definition, chain, types, publication_avoid, constraints, add)
        treatment = type_field(types, key, "treatment")
        for constraint in constraints:
            applies = (constraint.get("appliesTo") or {}).get("origins")
            forbidden = (constraint.get("prohibits") or {}).get("treatments") or []
            origins_hit = [s for s in sources if not applies or _origin_of(s) in [_origin_of(o) for o in applies]]
            if treatment in forbidden and origins_hit:
                add(f"imageTypes.{key}", f"{key} is a {treatment} type that allows {', '.join(origins_hit)}, which the rule {constraint['id']} forbids.", "constraint_conflict")
    # A locked field is set in the use and not overridden by a type.
    locked = document.get("locked") if isinstance(document.get("locked"), list) else []
    for key in sound:
        definition = types[key]
        use = type_use(types, key)
        for field in locked:
            if field in definition and field in ((document.get("uses") or {}).get(use) or {}):
                add(f"imageTypes.{key}.{field}", f"{field} is locked by the publication, so an image type cannot change it.")


def _origin_of(source: str) -> str:
    return "figure-system" if source in ("figure", "figure-system") else source


def _publication_never(document: dict) -> set[str]:
    """What the publication forbids outright: its never and avoided lists. No narrower layer can lift any of it."""
    never = set((document.get("subjects") or {}).get("never") or [])
    never |= set((document.get("techniques") or {}).get("avoided") or [])
    for constraint in document.get("constraints") or []:
        if isinstance(constraint, dict):
            never |= set(constraint.get("promptAvoid") or [])
    return never


def _check_remove_from_parent(key: str, definition: dict, chain: list[str], types: dict, never: set[str], constraints: list[dict], add) -> None:
    removal = definition.get("removeFromParent")
    if removal is None:
        return
    where = f"imageTypes.{key}.removeFromParent"
    if not isinstance(removal, dict):
        add(where, "removeFromParent must be an object.")
        return
    constraint_ids = {c.get("id") for c in constraints}
    for field in removal:
        if field in ("constraints", "never") or field in constraint_ids:
            add(f"{where}.{field}", "A type cannot remove a binding rule or a never item: those belong to the publication.", "constraint_conflict")
        elif field not in REMOVABLE:
            add(f"{where}.{field}", f"removeFromParent can only list avoid items and safeZones, not {field}.")
    if definition.get("extends") is None:
        add(where, f"{key} extends no type, so there is nothing to remove from.")
        return
    avoid_items = removal.get("avoid", [])
    if not _texts(avoid_items):
        add(f"{where}.avoid", "avoid must be a list of phrases.")
        return
    inherited = {item for name in chain[:-1] for item in (types[name] or {}).get("avoid") or []}
    for item in avoid_items:
        if item in never:
            add(f"{where}.avoid", f"{item!r} is something the publication forbids outright, so no image type can remove it.", "constraint_conflict")
        elif item not in inherited:
            add(f"{where}.avoid", f"{item!r} is not something a type {key} extends asks to avoid.")
    if "safeZones" in removal and not isinstance(removal["safeZones"], bool):
        add(f"{where}.safeZones", "safeZones must be yes or no.")


def _safe_use(types: dict, key: str) -> str | None:
    try:
        return type_use(types, key)
    except StyleError:
        return None


def _check_preference(preference: Any, types: dict, add) -> None:
    if preference is None:
        return
    if not isinstance(preference, dict):
        add("typePreference", "typePreference must be an object keyed by use.")
        return
    for use, keys in preference.items():
        where = f"typePreference.{use}"
        if use not in USES:
            add(where, f"A use must be one of: {', '.join(USES)}.")
        elif keys is None:
            continue
        elif not isinstance(keys, list):
            add(where, "Give a list of image type keys, or null when the use has no default.")
        else:
            for key in keys:
                if key not in types:
                    add(where, f"{key!r} is not an image type in this profile.")
                elif isinstance(types[key], dict) and _safe_use(types, key) not in (None, use):
                    add(where, f"{key} is a {_safe_use(types, key)} type, not a {use} type.")


def keys_permanent(previous: dict | None, document: dict) -> list[Problem]:
    """An image type key, once saved, stays: a type is retired (retired: true), never renamed or removed."""
    old = ((previous or {}).get("imageTypes") or {})
    new = document.get("imageTypes") or {}
    return [Problem(f"imageTypes.{key}", f"The image type {key} cannot be removed or renamed. Retire it with retired: true instead.") for key in old if key not in new]


# --- merging and comparing documents ---------------------------------------------------------------------------------------------------------------

def merge_document(base: dict | None, patch: dict) -> dict:
    """The document a save would store: ``patch`` laid over ``base``. Objects merge key by key; lists and values replace; null removes a key."""
    result = copy.deepcopy(base or {})
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_document(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def diff_documents(old: dict | None, new: dict | None, prefix: str = "") -> list[dict]:
    """Changed leaves as {path, from, to}. Lists and values compare whole."""
    old, new = old or {}, new or {}
    changes: list[dict] = []
    for key in [*old, *(key for key in new if key not in old)]:
        path = f"{prefix}.{key}" if prefix else key
        before, after = old.get(key), new.get(key)
        if isinstance(before, dict) and isinstance(after, dict):
            changes.extend(diff_documents(before, after, path))
        elif before != after:
            changes.append({"path": path, "from": before, "to": after})
    return changes


def _constraint_body(constraint: dict) -> dict:
    return {key: value for key, value in constraint.items() if key not in ("adoptedBy", "adoptedAt", "reason", "version")}


def constraint_changes(old: Iterable[dict] | None, new: Iterable[dict] | None) -> list[dict]:
    """Which binding rules a new document adds, changes or removes, compared with the stored ones."""
    before = {c["id"]: c for c in old or [] if isinstance(c, dict) and "id" in c}
    after = {c["id"]: c for c in new or [] if isinstance(c, dict) and "id" in c}
    changes = [{"id": key, "change": "removed", "from": before[key]} for key in before if key not in after]
    for key, constraint in after.items():
        if key not in before:
            changes.append({"id": key, "change": "added", "to": constraint})
        elif _constraint_body(before[key]) != _constraint_body(constraint):
            changes.append({"id": key, "change": "changed", "from": before[key], "to": constraint})
    return changes


def stamp_constraints(old: Iterable[dict] | None, new: Iterable[dict] | None, *, by: str, at: str, reason: str) -> list[dict]:
    """The constraints to store: an unchanged rule keeps its record exactly; an added or changed one gets its next version and who, when and why."""
    before = {c["id"]: c for c in old or [] if isinstance(c, dict) and "id" in c}
    stamped = []
    for constraint in new or []:
        previous = before.get(constraint["id"])
        if previous is not None and _constraint_body(previous) == _constraint_body(constraint):
            stamped.append(previous)
        else:
            stamped.append({**_constraint_body(constraint), "version": (previous or {}).get("version", 0) + 1 if previous else max(int(constraint.get("version") or 1), 1),
                            "adoptedBy": by, "adoptedAt": at, "reason": reason})
    return stamped


# --- resolving the layers ---------------------------------------------------------------------------------------------------------------------------

def _listify(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [item for item in value or [] if isinstance(item, str) and item.strip()]


def _section_name(section: dict | None) -> str:
    return str((section or {}).get("id") or "").split("#")[-1]


def resolve_visual_style(profile: dict | None, *, profile_ref: dict | None = None, use: str, image_type: str | None = None, operation: str = "resolve",
                         section: dict | None = None, story_style: dict | None = None, allow_retired: bool = False) -> dict:
    """The effective guidance for one image type, with the layer every field came from (design 5.3).

    ``operation`` is resolve, generate, search or figure: it decides which sources a default type must allow and whether the type may be used at all.
    Raises StyleError for image_type_required, image_type_unknown, source_not_allowed and constraint_conflict.
    """
    if use not in USES:
        raise StyleError("invalid_input", f"use must be one of: {', '.join(USES)}.", {"path": "use"})
    if not profile or not (profile.get("imageTypes") or profile.get("identity")):
        return {"resolutionHash": digest({"profile": None, "imageType": image_type, "use": use}), "profile": None, "layers": [], "effective": {}, "fieldSources": {},
                "imageType": image_type or "", "imageTypeChosenBy": "request", "availableTypes": [], "constraints": [], "imageReview": DEFAULT_IMAGE_REVIEW,
                "warnings": [{"code": "profile_missing", "message": PROFILE_MISSING}]}
    profile, section_types = with_section_types(profile, section_style_of(section)) if section else (profile, [])
    types = profile.get("imageTypes") or {}
    warnings: list[dict] = []
    choices = [{**row, "origin": "section"} if row["key"] in section_types else row for row in available_types(profile, use)]
    chosen_by = "request"
    required_source = OPERATION_SOURCE.get(operation)
    if image_type:
        definition = types.get(image_type)
        if definition is None or (definition.get("retired") and not allow_retired):
            raise StyleError("image_type_unknown", f"There is no image type {image_type} in this publication's profile, or it has been retired.", {"choices": choices})
        if type_use(types, image_type) != use:
            raise StyleError("image_type_unknown", f"{image_type} is a {type_use(types, image_type)} type, not a {use} type.", {"choices": choices})
    else:
        preferred = (profile.get("typePreference") or {}).get(use)
        usable = [key for key in preferred or [] if key in types and not types[key].get("retired") and type_use(types, key) == use
                  and (required_source is None or required_source in type_sources(types, key))]
        if not usable:
            why = ("An inline picture has to name its image type." if use == "inline" or preferred is None
                   else "None of the default image types for this use can do that.")
            raise StyleError("image_type_required", f"{why} Choose one of: {', '.join(c['key'] for c in choices) or 'none defined'}.", {"choices": choices})
        image_type, chosen_by = usable[0], "default-for-use"
        warnings.append({"code": "image_type_defaulted", "message": f"No image type was named, so {image_type} was used: the first for {use} in this publication's order of preference."})

    chain = type_chain(types, image_type)
    locked = set(profile.get("locked") or [])
    layers: list[dict] = []
    guidance: list[tuple[str, str]] = []
    avoid: list[tuple[str, str]] = []
    removed: list[str] = []
    preferred_techniques: list[tuple[str, str]] = []
    scalars: dict[str, tuple[Any, str]] = {}
    ignored: list[str] = []

    def put(field: str, value: Any, source: str) -> None:
        if field in locked and field in scalars:
            ignored.append(f"{field} from {source} (locked by the publication)")
            return
        scalars[field] = (value, source)

    def take(data: dict, source: str, *, narrowing: bool = False) -> None:
        """Lay one layer's fields over what is there. ``narrowing`` is for a section or a Story: it may only reduce a list of choices, never add."""
        for text in _listify(data.get("guidance")):
            guidance.append((text, source))
        for item in _listify(data.get("avoid")):
            if all(item != existing for existing, _ in avoid):
                avoid.append((item, source))
        for field in ("sizes", "display", "safeZones", "treatment", "use"):
            if field in data:
                put(field, data[field], source)
        for field in ("sources", "palette"):
            if field not in data:
                continue
            if narrowing and field in scalars:
                current = scalars[field][0]
                kept = [item for item in current if item in data[field]]
                extra = [item for item in data[field] if item not in current]
                if extra:
                    warnings.append({"code": "choice_not_added", "message": f"{source} asked for {', '.join(extra)} under {field}, which the image type does not allow; a section or Story can narrow the choices but never add one."})
                if kept:
                    put(field, kept, source)
                else:
                    warnings.append({"code": "choice_ignored", "message": f"{source} narrowed {field} to nothing the image type allows, so it was ignored."})
            else:
                put(field, list(data[field]), source)

    identity, techniques, subjects = profile.get("identity") or {}, profile.get("techniques") or {}, profile.get("subjects") or {}
    layers.append({"layer": "publication", **({"source": dict(profile_ref)} if profile_ref else {})})
    if identity.get("masterPrompt"):
        scalars["masterPrompt"] = (identity["masterPrompt"], "publication")
    if identity.get("summary"):
        scalars["summary"] = (identity["summary"], "publication")
    for item in techniques.get("preferred") or []:
        preferred_techniques.append((item, "publication"))
    for item in [*(techniques.get("avoided") or []), *(subjects.get("never") or [])]:
        if all(item != existing for existing, _ in avoid):
            avoid.append((item, "publication"))
    if subjects.get("representation"):
        scalars["representation"] = (subjects["representation"], "publication")

    treatment_key = type_field(types, image_type, "treatment")
    base_treatment = (profile.get("treatments") or {}).get(treatment_key)
    if treatment_key:
        layers.append({"layer": "treatment", "key": treatment_key})
    if base_treatment:
        take(base_treatment, f"treatment:{treatment_key}")
    layers.append({"layer": "use", "key": use})
    take((profile.get("uses") or {}).get(use) or {}, f"use:{use}")

    for name in chain:
        definition = types[name]
        source = f"section-image-type:{name}" if name in section_types else f"image-type:{name}"
        layers.append({"layer": "image-type", "key": name, **({"via": "extends"} if name != image_type else {}), **({"origin": "section"} if name in section_types else {})})
        removal = definition.get("removeFromParent") or {}
        for item in removal.get("avoid") or []:
            kept = [(text, where) for text, where in avoid if not (text == item and "image-type:" in where and where != source)]
            if len(kept) != len(avoid):
                avoid[:] = kept
                removed.append(f"avoid:{item!r} by {source}")
        if removal.get("safeZones") and "safeZones" in scalars and "image-type:" in scalars["safeZones"][1]:
            del scalars["safeZones"]
            removed.append(f"safeZones by {source}")
        take(definition, source)
        for item in (definition.get("techniques") or {}).get("preferred") or []:
            preferred_techniques.append((item, source))
        for item in (definition.get("techniques") or {}).get("avoided") or []:
            if all(item != existing for existing, _ in avoid):
                avoid.append((item, source))

    def override(raw: Any, layer: str, label: str, key: str | None, prose: str | None = None) -> None:
        data = as_object(raw)
        source = f"{layer}:{key}" if key else layer
        if not data and not prose:
            return
        layers.append({"layer": layer, **({"source": {"sectionId": section.get("id"), "updatedAt": section.get("updatedAt"), **(section.get("documentSource") or {})}} if layer == "section" and section else {}),
                       **({"source": dict(story_style["source"])} if layer == "story" and isinstance(story_style, dict) and story_style.get("source") else {})})
        for field in data:
            if field not in OVERRIDE_FIELDS and field != "typePreference":
                warnings.append({"code": "override_field_ignored", "message": f"{label} cannot change {field}; it was ignored. Binding rules and what the publication forbids cannot be changed from a section or a Story."})
        if prose:
            guidance.append((prose.strip(), source))
        scoped = {field: value for field, value in data.items() if field in OVERRIDE_FIELDS and field != "imageTypes"}
        take(scoped, source, narrowing=True)
        aimed = None if image_type in section_types else as_object(data.get("imageTypes")).get(image_type)
        if aimed:
            aimed = as_object(aimed)
            for field in aimed:
                if field not in OVERRIDE_FIELDS - {"imageTypes"}:
                    warnings.append({"code": "override_field_ignored", "message": f"{label} cannot change {field}; it was ignored."})
            take({field: value for field, value in aimed.items() if field in OVERRIDE_FIELDS - {"imageTypes"}}, f"{source}/{image_type}", narrowing=True)

    if section:
        override(section.get("visualStyle"), "section", "A section", _section_name(section), prose=str(section.get("visualGuidance") or "").strip() or None)
    story_data = story_style if isinstance(story_style, dict) else {}
    override({key: value for key, value in story_data.items() if key not in ("source", "notes")}, "story", "A Story",
             str((story_data.get("source") or {}).get("itemId") or "") or None,
             prose=str(story_data.get("notes") or "").strip() or None)

    effective_sources = list(scalars.get("sources", ([], ""))[0])
    if required_source and required_source not in effective_sources:
        raise StyleError("source_not_allowed", f"The image type {image_type} does not allow pictures from {required_source}. It allows: {', '.join(effective_sources) or 'nothing'}.",
                         {"allowed": effective_sources, "imageType": image_type,
                          "rules": {name: figure for name, figure in [("figureSystem", type_field(types, image_type, "figureSystem"))] if figure}})
    treatment = scalars.get("treatment", (None, ""))[0]
    constraints = []
    origins = {_origin_of(required_source)} if required_source else {_origin_of(s) for s in effective_sources}
    for constraint in profile.get("constraints") or []:
        applies = {_origin_of(o) for o in (constraint.get("appliesTo") or {}).get("origins") or []}
        if applies and not (applies & origins):
            continue
        constraints.append({key: constraint[key] for key in ("id", "version", "text", "promptDirective", "promptAvoid", "appliesTo") if key in constraint})
        if treatment and treatment in ((constraint.get("prohibits") or {}).get("treatments") or []):
            raise StyleError("constraint_conflict", f"The rule {constraint['id']} forbids a {treatment} picture here: {constraint['text']}",
                             {"constraint": {"id": constraint["id"], "version": constraint.get("version"), "text": constraint["text"]}})

    palette_all = identity.get("palette") or []
    subset = scalars.get("palette", (None, ""))[0]
    palette = [c for c in palette_all if not subset or c.get("name") in subset or c.get("token") in subset]
    field_sources: dict[str, Any] = {name: scalars[name][1] for name in ("sizes", "display", "safeZones", "sources", "treatment", "use", "masterPrompt", "summary", "representation") if name in scalars}
    if subset:
        field_sources["palette"] = scalars["palette"][1]
    elif palette_all:
        field_sources["palette"] = "publication"
    for index, (_, where) in enumerate(guidance):
        field_sources[f"guidance[{index}]"] = where
    for index, (_, where) in enumerate(avoid):
        field_sources[f"avoid[{index}]"] = where
    for index, (_, where) in enumerate(preferred_techniques):
        field_sources[f"techniques.preferred[{index}]"] = where
    if removed:
        field_sources["removed"] = removed
    if ignored:
        field_sources["ignored"] = ignored
    effective = {"masterPrompt": scalars.get("masterPrompt", ("", ""))[0], "summary": scalars.get("summary", ("", ""))[0],
                 "representation": scalars.get("representation", ("", ""))[0], "treatment": treatment, "use": use,
                 "guidance": [text for text, _ in guidance], "avoid": [text for text, _ in avoid], "preferredTechniques": [text for text, _ in preferred_techniques],
                 "palette": palette, "sizes": scalars.get("sizes", (None, ""))[0], "display": scalars.get("display", (None, ""))[0] or {},
                 "safeZones": scalars.get("safeZones", ([], ""))[0], "sources": effective_sources}
    result = {"profile": dict(profile_ref) if profile_ref else None, "layers": layers, "effective": effective, "fieldSources": field_sources,
              "imageType": image_type, "imageTypeChosenBy": chosen_by, "availableTypes": choices, "constraints": constraints,
              "imageReview": image_review_of(profile), "warnings": warnings}
    result["resolutionHash"] = digest({key: result[key] for key in ("profile", "layers", "effective", "imageType", "constraints")})
    return result


# --- plain lines for agents ------------------------------------------------------------------------------------------------------------------------

SOURCE_WORDS = {"figure-system": "drawn with the figure system", "stock": "found as stock", "generated": "generated"}


def type_line(profile: dict, row: dict) -> str:
    """One plain line about an image type, from its data: its key, label, description, how small it is shown and where its pictures may come from."""
    types = profile.get("imageTypes") or {}
    display = type_field(types, row["key"], "display") or {}
    shown = []
    if display.get("smallestWidthPx"):
        shown.append(f"shown as small as {display['smallestWidthPx']}px")
    if display.get("thumbnail") is True:
        shown.append("read as a thumbnail")
    elif display.get("thumbnail") is False:
        shown.append("never a thumbnail")
    sources = [SOURCE_WORDS.get(source, source) for source in row["sources"]]
    if "generated" not in row["sources"]:
        sources.append("never generated")
    parts = [part for part in (row["description"].rstrip("."), ", ".join(shown)) if part]
    return f"`{row['key']}` ({row['label']}): {'; '.join(parts)}. Sources, best first: {', '.join(sources)}."
