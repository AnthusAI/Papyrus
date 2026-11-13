"""``image_profile_init``: draft a starting style document for an editor to correct and save. It saves nothing and holds no style wording.

The draft is the shape of a profile (a few image types with where they appear and how big they are shown) plus whatever the site's brand says: its name
and its colours. Every adjective of style, every rule and every example is left for the editor, and the notes say so. The labels below name places a
picture goes, not how it should look.
"""
from __future__ import annotations

from .handlers import Caller, Outcome
from .profile_handlers import _publication, _read_current
from .profile_store import NO_PROFILE_GUARD
from .visual_style import as_object, validate_profile

# Structure only: where a picture appears, its size and whether it is shown as a card thumbnail.
STARTER_USES = {"cover": {"label": "Headline picture"}, "inline": {"label": "Picture in the article"}, "social": {"label": "Social card"}}
STARTER_TYPES = {
    "cover-picture": {"label": "Headline picture", "description": "The picture at the top of a Story and on its cards.", "use": "cover",
                      "display": {"where": "article top and cards", "smallestWidthPx": 160, "thumbnail": True},
                      "sizes": {"aspectRatio": "16:9", "width": 1920, "height": 1088}, "sources": ["stock", "generated"]},
    "inline-picture": {"label": "Picture in the article", "description": "A picture inside the article body.", "use": "inline",
                       "display": {"where": "article body", "smallestWidthPx": 343, "thumbnail": False},
                       "sizes": {"aspectRatio": "16:9", "width": 1920, "height": 1088}, "sources": ["stock", "generated"]},
    "social-card": {"label": "Social card", "description": "The picture in link previews on other sites.", "use": "social",
                    "display": {"where": "link previews", "smallestWidthPx": 120, "thumbnail": True},
                    "sizes": {"aspectRatio": "1.91:1", "width": 1200, "height": 630}, "sources": ["stock", "generated"]},
}


def draft_document(brand: dict | None) -> tuple[dict, list[str]]:
    brand = as_object(brand)
    identity: dict = {}
    palette = [{key: entry[key] for key in ("name", "hex", "token", "role") if entry.get(key)} for entry in brand.get("palette") or [] if isinstance(entry, dict)]
    if palette:
        identity["palette"] = palette
    document: dict = {"schemaVersion": 2, "uses": {key: dict(value) for key, value in STARTER_USES.items()},
                      "imageTypes": {key: {name: (dict(value) if isinstance(value, dict) else list(value) if isinstance(value, list) else value) for name, value in definition.items()}
                                     for key, definition in STARTER_TYPES.items()},
                      "typePreference": {"cover": ["cover-picture"], "inline": None, "social": ["social-card"]}}
    if identity:
        document["identity"] = identity
    notes = ["Write identity.summary and identity.masterPrompt: how this publication's pictures should look, in your own words.",
             "Write guidance for each image type, and list what each should avoid.",
             "Add example pictures to each image type (Administration > Policies > Visual style), good ones and ones to avoid.",
             "Choose imageReview: before_publish (the default) or after_the_fact.",
             "These image types are a starting set: rename their labels, add or retire types as the publication needs. A type's key cannot be changed once it is saved."]
    if not palette:
        notes.insert(0, "No brand colours were given, so identity.palette is empty. Add the brand colours.")
    return document, notes


def init_profile(client, arguments: dict, caller: Caller, files=None) -> Outcome:
    publication = _publication(client)
    document, _, row = _read_current(client, files)
    drafted, notes = draft_document(arguments.get("brand"))
    problems = validate_profile(drafted)
    if problems:
        from .profile_handlers import _refuse

        _refuse(problems)
    warnings = ()
    if document is not None:
        warnings = ({"code": "profile_exists", "message": "This publication already has a style profile. Saving this draft would add its image types beside yours and replace any "
                                                           "lists it shares; run `profile diff` first and keep what you have."},)
    return Outcome({"document": drafted, "expectedCurrentVersionId": row["id"] if row else NO_PROFILE_GUARD, "notes": notes, "profileExists": document is not None},
                   publication, warnings)
