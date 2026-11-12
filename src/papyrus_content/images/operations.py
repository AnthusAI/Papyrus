"""The one table of image operations (docs/images.md; design: project/wiki/image-toolchain.md section 3; PPY-1232dc).

Every image action is one ``Operation`` here: its MCP tool name, CLI command, input and result schemas, the errors it may return, who may call it and
a plain sentence about it. The CLI group ``papyrus images``, the MCP tool schema, the newsroom's TypeScript types, the skill's reference block and
docs/images.md are all generated from this table by ``scripts/generate-image-operations.py``; a test fails when any of them differs.

To add or change an operation: edit ``OPERATIONS`` below, then run ``python scripts/generate-image-operations.py``.
This module describes operations only. What they do is in ``handlers.py`` (every handler answers ``not_implemented`` until its build step).

The table also holds the guideline operations (``group="guidelines"``: ``guidelines_get`` and the rest, PPY-8d41d7). They are the same kind of thing, so the
generated MCP schema and TypeScript types cover them too; their CLI group is ``papyrus guidelines`` and their door is ``guidelinesRead`` / ``guidelinesWrite``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# --- schema helpers (JSON Schema, camelCase properties, kept to the small subset the MCP table and the validator understand) ------------------------


def text(description: str | None = None, **extra) -> dict:
    return {"type": "string", "minLength": 1, **({"description": description} if description else {}), **extra}


def whole(description: str | None = None, minimum: int = 1) -> dict:
    return {"type": "integer", "minimum": minimum, **({"description": description} if description else {})}


def flag(description: str | None = None) -> dict:
    return {"type": "boolean", **({"description": description} if description else {})}


def choice(*values: str, description: str | None = None) -> dict:
    return {"type": "string", "enum": list(values), **({"description": description} if description else {})}


def many(item: dict, description: str | None = None) -> dict:
    return {"type": "array", "items": item, **({"description": description} if description else {})}


def anything(description: str | None = None) -> dict:
    return {"description": description} if description else {}


def obj(properties: dict, required: tuple[str, ...] = (), description: str | None = None, **extra) -> dict:
    """A closed object: input shapes refuse properties they do not list."""
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False,
            **({"description": description} if description else {}), **extra}


def record(properties: dict, required: tuple[str, ...] = (), description: str | None = None) -> dict:
    """An open object: result shapes may grow without breaking readers."""
    return {"type": "object", "properties": properties, "required": list(required), **({"description": description} if description else {})}


def one_of(*names: str) -> dict:
    """Exactly one of these properties must be present."""
    return {"oneOf": [{"required": [name]} for name in names]}


# --- shared pieces ---------------------------------------------------------------------------------------------------------------------------------

USES = ("cover", "inline", "social")
STATUSES = ("queued", "pending", "running", "ready", "failed", "rejected", "applied", "unapplied", "expired")

TARGET = obj({"kind": choice("story", "reference"), "lineageId": text("The lineage id of the Story or Reference.")}, ("kind", "lineageId"),
             "What the picture is for: a Story or a Reference.")
USE = choice(*USES, description="Where the picture goes: the cover, inline in the body, or a social card.")
VERSION_GUARD = text("The Story's current version id when you read it. The write is refused with stale_version if the Story has moved on.")
REASON = text("Why, in plain words. It is recorded with who and when.")
IMAGE_TYPE = text("A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; "
                  "inside the article you must name one.")
TYPE_CHOSEN_BY = choice("request", "default-for-use", description="Whether the caller named the image type or the use's default supplied it.")
IMAGE_TYPE_CHOICE = record({"key": text(), "label": text(), "description": text(), "sources": many(text())}, ("key",))
PROFILE_DOCUMENT = {"type": "object", "description": "The visual style document: a full or partial profile (design section 5.2)."}

COST_ESTIMATE = record({"priced": flag("False means the model has no price on file yet. Unpriced is never free."), "usd": {"type": "number"},
                        "perCandidate": {"type": "number"}, "basis": text()}, ("priced",), "What it would cost; spends nothing.")
SELECTION = record({"by": text(), "byKind": choice("human", "agent"), "delegatedBy": text(), "at": text(), "reason": text()}, ("by", "byKind", "at", "reason"))
CANDIDATE_SUMMARY = record({
    "id": text(), "position": whole(minimum=0), "status": choice(*STATUSES), "treatment": text(), "imageType": text(),
    "origin": choice("generated", "stock", "figure"), "lane": choice("standard", "batch"),
    "reviewStatus": choice("unreviewed", "human-verified"), "previewUrl": text("Short-lived signed address of the picture."),
    "retryOf": text(), "error": record({"code": text(), "message": text(), "retryable": flag()}, ("code", "message")),
}, ("id", "position", "status"))
STOCK_CANDIDATE = record({
    "candidateRef": text("Opaque reference to pass to image_select or image_apply."), "id": text(), "source": text(), "sourceLabel": text(), "title": text(),
    "description": {"type": "string"}, "creator": text(), "licence": record({"kind": text(), "name": text(), "url": {"type": ["string", "null"]}}),
    "sourceUrl": text(), "imageUrl": text(), "width": whole(), "height": whole(),
}, ("candidateRef", "id", "source", "title", "creator", "licence", "sourceUrl", "imageUrl"))
PAGE = {"nextToken": text("Pass this to get the next page. Absent when there is no more.")}

# image_generate and image_prompt_preview take the same input.
GENERATE_INPUT = obj({
    "target": TARGET, "sectionId": text("A section id; worked out from the Story when left out. With no target it is the only place the section layer comes from."), "use": USE, "imageType": IMAGE_TYPE, "brief": text("What the picture should show. The publication's style rules are added by the service, never written here."),
    "count": whole("How many to make (default 1). More than 1 is for a person choosing; an agent asking for more gets set_needs_person."),
    "spread": choice("variations", "types", description="Four takes of one image type, or one take of each type the use allows that can be generated."),
    "imageTypes": many(text(), "Image types to spread across, from the profile."),
    "model": text("A configured, approved model. Recorded as requested and never swapped."),
    "acceptFallback": text("Id of a fallback offered in a capability_unsupported error, to use instead."),
    "references": many(text(), "Example ids of the chosen image type to send as style references. Nothing else is accepted."),
    "speed": choice("auto", "standard", "batch", description="Which lane: auto picks by who is asking (a person standard, an agent batch at half price)."),
}, ("use", "brief"), "target may be left out: with no Story or Reference the round is private, there is nothing to apply, and it is for ad assets and section art.")
ROUND_RESULT = record({
    "roundId": text(), "imageType": text(), "imageTypeChosenBy": TYPE_CHOSEN_BY, "candidates": many(CANDIDATE_SUMMARY), "estimate": COST_ESTIMATE,
}, ("roundId", "candidates"), "Returned at once; the pictures arrive later (image_round_get).")

# --- the table ------------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Example:
    input: dict
    result: dict


@dataclass(frozen=True)
class Operation:
    name: str                              # the MCP tool name, for example "image_generate"
    cli: tuple[str, ...]                   # the words after "papyrus images", for example ("profile", "get")
    summary: str                           # one plain sentence: MCP description, CLI help, docs, skill
    effect: Literal["read", "write", "spend"]
    input: dict                            # JSON Schema, camelCase properties
    result: dict                           # JSON Schema of the success result
    errors: tuple[str, ...]                # codes from ERRORS this operation may return, beyond COMMON_ERRORS
    examples: tuple[Example, ...]          # input and result pairs: docs, skill and the parity tests
    permission: Literal["editor"] = "editor"   # editor: an editor or admin of this site. Spend also needs the site's approved generation.
    agent_allowed: bool = True             # False: only a person may call it; an agent gets human_required
    audience: Literal["staff"] = "staff"   # readers get no image operations
    positional: tuple[str, ...] = ()       # input properties the CLI takes as plain words, in order
    flags: tuple[tuple[str, str], ...] = ()    # (input property, CLI flag name) where the flag is not the property in kebab-case
    file_field: str | None = None          # the property the CLI fills from --file (a JSON or YAML document)
    picture_field: str | None = None       # the property the CLI fills by uploading the picture --file names (an id the upload step returns)
    notes: str = ""                        # anything a reader needs that the schemas cannot say
    group: Literal["images", "guidelines"] = "images"   # the CLI group (papyrus <group> ...) and the door family the operation is run through

    @property
    def mcp_name(self) -> str:
        return self.name

    @property
    def command(self) -> str:
        return " ".join(("papyrus", self.group, *self.cli))


@dataclass(frozen=True)
class ErrorCode:
    code: str
    message: str      # plain words; the default message of an error with this code
    retryable: bool = False
    details: str = ""  # what `details` carries, if anything


ERRORS = (
    ErrorCode("invalid_input", "The request does not fit the operation's input.", details="path names the field"),
    ErrorCode("unknown_operation", "There is no image operation by that name.", details="operation, or command for the CLI"),
    ErrorCode("not_implemented", "This operation is described but not built yet.", details="operation"),
    ErrorCode("not_authorized", "You are not an editor or admin of this site, or the grant lacks the permission."),
    ErrorCode("human_required", "A person has to do this one; an agent may not."),
    ErrorCode("set_needs_person", "A set of several pictures is for a person choosing. Unattended work gets one picture."),
    ErrorCode("not_found", "No such Story, Reference, round or picture in this publication."),
    ErrorCode("constraint_conflict", "The request asks for something one of the publication's rules forbids.", details="the constraint"),
    ErrorCode("image_type_required", "This request has to name an image type: an inline picture, or a use with no default, did not.",
              details="choices lists the publication's image types for that use, with their descriptions"),
    ErrorCode("image_type_unknown", "There is no such image type in this publication's profile, or it has been retired.",
              details="choices lists the publication's image types for that use, with their descriptions"),
    ErrorCode("source_not_allowed", "This image type does not allow that way of getting a picture.",
              details="allowed lists the type's sources in order, and where their rules live"),
    ErrorCode("checks_failed", "A check failed, so the picture cannot be applied.", details="checks lists which"),
    ErrorCode("generation_not_configured", "No approved image model is set up for this site, so nothing was made.", details="how to configure it"),
    ErrorCode("capability_unsupported", "The configured model cannot do what was asked.", details="alternatives lists fallbacks the caller may opt into"),
    ErrorCode("provider_failed", "The image provider refused or failed.", retryable=True, details="providerMessage, retryable"),
    ErrorCode("provider_busy", "The image provider is busy. Try again shortly.", retryable=True, details="retryAfterSeconds"),
    ErrorCode("spend_ceiling_exceeded", "The site's spending ceiling for a round or a day is reached, so this picture was not made.", details="the ceiling"),
    ErrorCode("batch_expired", "The picture was not ready within the batch window (24 hours). Nothing was charged.", retryable=True),
    ErrorCode("stale_version", "The Story has a newer version than the one you named. Read it again."),
    ErrorCode("candidate_not_ready", "The picture is still being made."),
    ErrorCode("candidate_closed", "The picture was already discarded, expired or applied."),
    ErrorCode("unknown_kind", "There is no such kind of guidelines.", details="kinds lists the kinds this site knows"),
    ErrorCode("resolver_not_available", "This kind of guidelines is resolved by its own command, not this one.", details="use names the command"),
    ErrorCode("document_hash_mismatch", "The stored guideline document does not match its recorded hash, so it was not used.", details="itemId"),
    ErrorCode("service_unavailable", "A permission or storage check could not be made. Nothing was changed.", retryable=True),
)
ERROR_BY_CODE = {error.code: error for error in ERRORS}
# Any operation may return these, so the per-operation lists leave them out.
COMMON_ERRORS = ("invalid_input", "not_authorized", "service_unavailable", "not_implemented")

# Example ids below are made up. There are no real people, sites or addresses in this file.
_STORY = {"kind": "story", "lineageId": "story-containment-note"}
_GUARD = "item-story-containment-note-v7"
_CANDIDATE = {"id": "candidate-1", "position": 0, "status": "ready", "treatment": "editorial-illustration", "imageType": "cover-illustration", "origin": "generated", "lane": "standard", "reviewStatus": "unreviewed"}
_ESTIMATE = {"priced": False}
_TYPE_CHOICE = {"key": "cover-illustration", "label": "Cover illustration", "description": "A calm editorial illustration for the cover.", "sources": ["generated", "stock"]}
_PROFILE_REF = {"itemId": "item-editorial-doctrine-visual-style-v3", "versionNumber": 3, "contentHash": "sha256:0f3a"}

OPERATIONS: tuple[Operation, ...] = (
    # --- style profile
    Operation(
        "image_profile_get", ("profile", "get"), "Read the publication's visual style profile, the current version or an older one.", "read",
        obj({"version": whole("A version number; the current version when left out.")}),
        record({"profile": PROFILE_DOCUMENT, "itemId": text(), "versionNumber": whole(), "updatedAt": text(), "updatedBy": text(), "contentHash": text()},
               ("profile", "itemId", "versionNumber", "contentHash")),
        ("not_found",),
        (Example({}, {"profile": {"schemaVersion": 1, "identity": {"summary": "Flat, calm editorial illustration."}}, "itemId": "item-editorial-doctrine-visual-style-v3",
                      "versionNumber": 3, "updatedAt": "2026-11-07T17:51:39Z", "updatedBy": "account-1", "contentHash": "sha256:0f3a"}),),
    ),
    Operation(
        "image_profile_resolve", ("profile", "resolve"),
        "Show the style that would apply to a Story, section and use, with the layer every field came from.", "read",
        obj({"target": TARGET, "sectionId": text("A section id; worked out from the Story when left out."), "use": USE,
             "imageType": IMAGE_TYPE}, ("use",)),
        record({"resolutionHash": text(), "profile": {"type": ["object", "null"], "description": "Which profile version; null when the publication has none."},
                "layers": many(record({"layer": text()}, ("layer",))), "effective": {"type": "object"}, "fieldSources": {"type": "object"},
                "imageType": text(), "imageTypeChosenBy": TYPE_CHOSEN_BY, "availableTypes": many(IMAGE_TYPE_CHOICE),
                "constraints": many({"type": "object"}), "warnings": many(record({"code": text(), "message": text()}, ("code", "message")))},
               ("resolutionHash", "profile", "layers", "effective", "fieldSources", "imageType", "imageTypeChosenBy", "availableTypes", "constraints", "warnings"),
               "The effective guidance. A publication with no profile gets the profile_missing warning, not an error."),
        ("constraint_conflict", "image_type_required", "image_type_unknown", "not_found"),
        (Example({"target": _STORY, "use": "cover", "imageType": "cover-illustration"}, {
            "resolutionHash": "sha256:91bc", "profile": _PROFILE_REF, "layers": [{"layer": "publication"}, {"layer": "use"}, {"layer": "image-type"}],
            "effective": {"aspectRatio": "16:9"}, "fieldSources": {"aspectRatio": "use:cover"}, "imageType": "cover-illustration", "imageTypeChosenBy": "request",
            "availableTypes": [_TYPE_CHOICE], "constraints": [], "warnings": []}),),
        flags=(("sectionId", "section"),),
    ),
    Operation(
        "image_profile_diff", ("profile", "diff"), "Show what saving a style document would change, without saving it.", "read",
        obj({"document": PROFILE_DOCUMENT}, ("document",)),
        record({"changes": many(record({"path": text(), "from": anything(), "to": anything()}, ("path",))),
                "constraintChanges": many({"type": "object"}), "wouldCreateVersion": whole()}, ("changes", "constraintChanges", "wouldCreateVersion")),
        ("constraint_conflict",), (Example({"document": {"identity": {"mood": ["calm"]}}}, {"changes": [{"path": "identity.mood", "from": ["calm", "precise"], "to": ["calm"]}],
                                                                   "constraintChanges": [], "wouldCreateVersion": 4}),),
        file_field="document",
    ),
    Operation(
        "image_profile_save", ("profile", "save"), "Save a style document as a new profile version.", "write",
        obj({"document": PROFILE_DOCUMENT, "reason": REASON, "expectedCurrentVersionId": text("The profile's current version id when you read it.")},
            ("document", "reason", "expectedCurrentVersionId")),
        record({"itemId": text(), "versionNumber": whole(), "contentHash": text()}, ("itemId", "versionNumber", "contentHash")),
        ("human_required", "stale_version", "constraint_conflict"),
        (Example({"document": {"identity": {"mood": ["calm"]}}, "reason": "Dropped one mood word.", "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v3"},
                 {"itemId": "item-editorial-doctrine-visual-style-v4", "versionNumber": 4, "contentHash": "sha256:7d21"}),),
        file_field="document",
        notes="Adding, changing or removing a binding constraint needs an admin who is a person; an agent gets human_required. The document is laid over the current profile "
              "(objects merge, lists replace, null removes a key). For the very first profile pass none as expectedCurrentVersionId. Saving a document that changes nothing makes no version.",
    ),
    Operation(
        "image_profile_history", ("profile", "history"), "List the profile's versions, newest first, with who changed it and why.", "read",
        obj({"limit": whole("How many versions to return."), "nextToken": PAGE["nextToken"]}),
        record({"versions": many(record({"versionNumber": whole(), "at": text(), "by": text(), "byKind": choice("human", "agent"), "reason": text(),
                                         "contentHash": text()}, ("versionNumber", "at", "by", "byKind", "contentHash"))), **PAGE}, ("versions",)),
        (), (Example({"limit": 2}, {"versions": [{"versionNumber": 3, "at": "2026-11-07T17:51:39Z", "by": "account-1", "byKind": "human", "reason": "First profile.",
                                                   "contentHash": "sha256:0f3a"}]}),),
    ),
    Operation(
        "image_profile_init", ("profile", "init"), "Draft a starting style document from the site's brand, for an editor to correct and save. Saves nothing.", "read",
        obj({"brand": record({"name": text("The publication's name."), "palette": many(record({"name": text(), "hex": text("Like #1f2a44."), "token": text(), "role": text()},
                                                                                              ("name", "hex")), "The brand colours, if known.")},
                             (), "What the site's brand files say. Everything in it is optional.")}),
        record({"document": PROFILE_DOCUMENT, "expectedCurrentVersionId": text("Pass this to image_profile_save when saving the draft."),
                "notes": many(text(), "What an editor still has to write."), "profileExists": flag()}, ("document", "expectedCurrentVersionId", "notes", "profileExists")),
        (),
        (Example({"brand": {"name": "Example Daily", "palette": [{"name": "Ink blue", "hex": "#1f2a44", "token": "brand"}]}},
                 {"document": {"schemaVersion": 2, "identity": {"palette": [{"name": "Ink blue", "hex": "#1f2a44", "token": "brand"}]}}, "expectedCurrentVersionId": "none",
                  "notes": ["Write identity.summary and identity.masterPrompt."], "profileExists": False}),),
        file_field="brand",
        notes="The draft holds the shape of a profile and the colours the brand names, and no style wording: an editor writes that. Nothing is saved; save the draft "
              "with image_profile_save after correcting it.",
    ),
    Operation(
        "image_profile_example_add", ("profile", "example", "add"), "Add an example or an avoid-this picture to the profile, as a new version.", "write",
        obj({"attachmentId": text("The id of a picture already uploaded through the newsroom's upload step (PNG, JPEG or WebP, at most 10 MB)."),
             "kind": choice("exemplar", "negative"),
             "note": text("Why this picture is a good example, or what to avoid."),
             "imageType": text("The image type this example belongs to, or identity for a brand-wide example."),
             "sendToProvider": flag("Send it to the image model as a style reference. Default false."), "reason": REASON,
             "expectedCurrentVersionId": text("The profile's current version id when you read it.")},
            ("attachmentId", "imageType", "kind", "note", "reason", "expectedCurrentVersionId")),
        record({"attachmentId": text(), "sha256": text(), "versionNumber": whole(), "imageType": text()}, ("attachmentId", "sha256", "versionNumber")),
        ("human_required", "image_type_unknown", "not_found", "stale_version"),
        (Example({"attachmentId": "model-attachment-1", "imageType": "cover-illustration", "kind": "exemplar", "note": "The calm we want.", "reason": "Cover from the containment Story.",
                  "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v3"},
                 {"attachmentId": "model-attachment-1", "sha256": "sha256:aa10", "versionNumber": 4, "imageType": "cover-illustration"}),),
        picture_field="attachmentId",
        notes="From the command line, --file PICTURE uploads the picture first (the same three steps the newsroom takes) and fills in attachmentId. "
              "Only a person may set sendToProvider: an agent asking for it gets human_required, because the service cannot tell whether a picture shows identifiable "
              "people or logos. An example belongs to one image type; a child type does not inherit its parent's examples.",
    ),
    Operation(
        "image_profile_example_remove", ("profile", "example", "remove"), "Remove an example picture from the profile, as a new version.", "write",
        obj({"attachmentId": text(), "imageType": text("Remove it from this image type only (or identity). Left out, it is removed from every list that has it."),
             "reason": REASON, "expectedCurrentVersionId": text("The profile's current version id when you read it.")},
            ("attachmentId", "reason", "expectedCurrentVersionId")),
        record({"versionNumber": whole(), "removedFrom": many(text(), "The image types (or identity) it was removed from.")}, ("versionNumber",)),
        ("not_found", "stale_version"),
        (Example({"attachmentId": "model-attachment-1", "reason": "Too photographic.", "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v4"},
                 {"versionNumber": 5, "removedFrom": ["cover-illustration"]}),),
        positional=("attachmentId",),
        notes="The file stays for older profile versions, so a picture made from an older version keeps the examples it was made with.",
    ),
    # --- planning
    Operation(
        "image_capabilities", ("capabilities",), "Say which image models this site can use and whether spending is approved.", "read",
        obj({}),
        record({"configured": flag(), "models": many({"type": "object"}), "approvedForSpend": flag(), "unreviewedMayPublish": flag(),
                "spendCeilings": record({"perRoundUsd": {"type": ["number", "null"]}, "perDayUsd": {"type": ["number", "null"]}}), "spentTodayUsd": {"type": "number"}},
               ("configured", "models", "approvedForSpend")),
        (), (Example({}, {"configured": False, "models": [], "approvedForSpend": False}),),
    ),
    Operation(
        "image_brief_draft", ("brief",), "Work out a starting brief and stock search from a Story's title and deck.", "read",
        obj({"target": TARGET, "use": USE, "imageType": IMAGE_TYPE}, ("target", "use")),
        record({"brief": text(), "searchTarget": text(), "imageType": text(), "imageTypeChosenBy": TYPE_CHOSEN_BY, "typeChoices": many(IMAGE_TYPE_CHOICE),
                "derivedFrom": many(text()), "workedOut": flag()}, ("brief", "searchTarget", "derivedFrom", "workedOut")),
        ("image_type_required", "not_found"),
        (Example({"target": _STORY, "use": "cover", "imageType": "cover-illustration"},
                 {"brief": "A locked filing cabinet with one drawer ajar", "searchTarget": "filing cabinet", "imageType": "cover-illustration",
                  "imageTypeChosenBy": "request", "typeChoices": [_TYPE_CHOICE], "derivedFrom": ["title", "deck"], "workedOut": True}),),
    ),
    Operation(
        "image_prompt_preview", ("prompt",), "Show exactly what would be asked of the image model, and what it would cost, without making anything.", "read",
        GENERATE_INPUT,
        record({"plans": many({"type": "object"}), "estimate": COST_ESTIMATE, "capabilityCheck": {"type": "object"}}, ("plans", "estimate", "capabilityCheck")),
        ("capability_unsupported", "constraint_conflict", "generation_not_configured", "image_type_required", "image_type_unknown", "not_found",
         "set_needs_person", "source_not_allowed"),
        (Example({"target": _STORY, "use": "cover", "imageType": "cover-illustration", "brief": "A locked filing cabinet with one drawer ajar"},
                 {"plans": [{"planVersion": "image-prompt/v2", "imageType": "cover-illustration", "segments": [], "avoid": []}], "estimate": _ESTIMATE, "capabilityCheck": {"ok": True}}),),
        flags=(("sectionId", "section"),),
    ),
    # --- finding and making
    Operation(
        "image_search", ("search",), "Find stock pictures for a Story, four at a time.", "read",
        obj({"target": TARGET, "use": USE, "imageType": IMAGE_TYPE, "query": text("Search words; worked out from the Story when left out."), "source": text("A stock source, for example wikimedia-commons."),
             "cursor": text("The nextCursor of the previous page."), "exclude": many(text(), "Candidate ids already shown, which never come back.")}, ("target",)),
        record({"imageType": text(), "imageTypeChosenBy": TYPE_CHOSEN_BY, "candidates": many(STOCK_CANDIDATE), "nextCursor": {"type": ["string", "null"]}, "searched": text(), "searchedFromStory": flag()},
               ("candidates", "nextCursor", "searched", "searchedFromStory")),
        ("image_type_required", "image_type_unknown", "not_found", "source_not_allowed"),
        (Example({"target": _STORY, "use": "cover", "imageType": "cover-illustration"},
                 {"imageType": "cover-illustration", "imageTypeChosenBy": "request", "candidates": [], "nextCursor": None, "searched": "filing cabinet", "searchedFromStory": True}),),
        notes="Nothing is stored until a picture is selected or applied.",
    ),
    Operation(
        "image_generate", ("generate",), "Make pictures from a brief in the publication's style. The pictures arrive later.", "spend",
        GENERATE_INPUT, ROUND_RESULT,
        ("capability_unsupported", "constraint_conflict", "generation_not_configured", "image_type_required", "image_type_unknown", "not_found", "provider_busy",
         "set_needs_person", "source_not_allowed", "spend_ceiling_exceeded"),
        (Example({"target": _STORY, "use": "cover", "imageType": "cover-illustration", "brief": "A locked filing cabinet with one drawer ajar"},
                 {"roundId": "round-1", "imageType": "cover-illustration", "imageTypeChosenBy": "request",
                  "candidates": [{"id": "candidate-1", "position": 0, "status": "queued", "imageType": "cover-illustration", "origin": "generated", "lane": "batch"}],
                  "estimate": _ESTIMATE}),),
        flags=(("imageTypes", "image-types"), ("sectionId", "section")),
        notes="Spends only when the site's image generation is configured and approved.",
    ),
    Operation(
        "image_figure_add", ("figure", "add"),
        "Record a figure drawn with the publication's figure system as a picture to preview, review and apply. It draws and generates nothing.", "write",
        obj({"target": TARGET, "imageType": text("The image type the figure is for, such as cover-diagram. It must allow the figure-system source."),
             "uploadIds": obj({"light": text("The id of the uploaded light PNG."), "dark": text("The id of the uploaded dark PNG.")}, ("light",),
                              "Pictures already uploaded through the newsroom's upload step."),
             "figureId": text("The id of the figure record, once the backend stores figures (PPY-cd4585)."),
             "figure": obj({"audience": text(), "shows": text(), "complements": text(), "approvedBy": text()}, ("audience", "shows", "complements"),
                           "The figure.json acceptance fields.")},
            ("target", "imageType", "figure"), **one_of("uploadIds", "figureId")),
        record({"candidateId": text(), "origin": choice("figure"), "checks": many({"type": "object"})}, ("candidateId", "origin", "checks")),
        ("checks_failed", "image_type_unknown", "not_found", "source_not_allowed"),
        (Example({"target": _STORY, "imageType": "cover-diagram", "uploadIds": {"light": "upload-2", "dark": "upload-3"},
                  "figure": {"audience": "Editors deciding what to publish.", "shows": "Which checks run before a picture is applied.",
                             "complements": "The paragraph on review."}},
                 {"candidateId": "candidate-7", "origin": "figure", "checks": [{"name": "alt-text", "passed": True}]}),),
        file_field="figure",
        notes="Needs an image type whose sources include figure-system. The figure is drawn and rendered elsewhere; this only records it. "
              "The CLI reads the figure.json acceptance fields from --file and takes uploadIds through --input-file.",
    ),
    Operation(
        "image_round_get", ("round",), "Read a round of pictures and say whether they are all done.", "read",
        obj({"roundId": text()}, ("roundId",)),
        record({"roundId": text(), "target": TARGET, "use": USE, "imageType": text(), "brief": {"type": "string"}, "candidates": many(CANDIDATE_SUMMARY), "done": flag()},
               ("roundId", "use", "candidates", "done"), "target is absent for a private round."),
        ("not_found",),
        (Example({"roundId": "round-1"}, {"roundId": "round-1", "target": _STORY, "use": "cover", "imageType": "cover-illustration", "brief": "A locked filing cabinet with one drawer ajar",
                                          "candidates": [_CANDIDATE], "done": True}),),
        positional=("roundId",),
    ),
    Operation(
        "image_candidate_get", ("show",), "Read one picture's full record, with a short-lived preview address.", "read",
        obj({"candidateId": text()}, ("candidateId",)),
        record({"candidate": {"type": "object", "description": "The full ImageCandidate record."}, "previewUrl": text()}, ("candidate",)),
        ("not_found",),
        (Example({"candidateId": "candidate-1"}, {"candidate": dict(_CANDIDATE), "previewUrl": "https://example.invalid/preview/candidate-1"}),),
        positional=("candidateId",),
    ),
    Operation(
        "image_list", ("list",), "List the rounds and pictures made for a Story or Reference, newest first.", "read",
        obj({"target": TARGET, "status": choice(*STATUSES), "nextToken": PAGE["nextToken"]}, ("target",)),
        record({"rounds": many(record({"roundId": text(), "use": USE, "imageType": text(), "brief": {"type": "string"}, "createdAt": text(), "candidates": many(CANDIDATE_SUMMARY)},
                                      ("roundId", "candidates"))), **PAGE}, ("rounds",)),
        ("not_found",),
        (Example({"target": _STORY}, {"rounds": [{"roundId": "round-1", "use": "cover", "imageType": "cover-illustration", "brief": "A locked filing cabinet", "createdAt": "2026-11-07T18:00:00Z",
                                                  "candidates": [_CANDIDATE]}]}),),
    ),
    Operation(
        "image_retry", ("retry",), "Make a new picture to replace one that failed. The ones that worked stay.", "spend",
        obj({"candidateId": text("A failed picture."), "speed": choice("auto", "standard", "batch", description="Lane for the new picture; a batch failure retries as batch by default.")},
            ("candidateId",)),
        record({"roundId": text(), "candidate": CANDIDATE_SUMMARY, "estimate": COST_ESTIMATE}, ("roundId", "candidate"), "The new picture, with retryOf naming the failed one."),
        ("candidate_closed", "candidate_not_ready", "capability_unsupported", "generation_not_configured", "not_found", "provider_busy"),
        (Example({"candidateId": "candidate-3"}, {"roundId": "round-1", "candidate": {"id": "candidate-5", "position": 4, "status": "queued", "retryOf": "candidate-3"},
                                                   "estimate": _ESTIMATE}),),
        positional=("candidateId",),
        notes="The design lists only candidateId; speed is added because it says a retry can choose standard (section 7.4).",
    ),
    Operation(
        "image_iterate", ("iterate",), "Make new pictures from one you have, with an instruction such as 'less busy'.", "spend",
        obj({"candidateId": text(), "instruction": text("What to change, in plain words."),
             "count": whole("How many to make (default 1). More than 1 is for a person choosing."),
             "useAsReference": flag("Send the picture to the model as a reference. Default true when the model can edit.")}, ("candidateId", "instruction")),
        ROUND_RESULT,
        ("candidate_closed", "candidate_not_ready", "capability_unsupported", "constraint_conflict", "generation_not_configured", "not_found", "provider_busy",
         "set_needs_person"),
        (Example({"candidateId": "candidate-1", "instruction": "less busy, subject lower"},
                 {"roundId": "round-2", "candidates": [{"id": "candidate-6", "position": 0, "status": "queued", "lane": "batch"}], "estimate": _ESTIMATE}),),
        positional=("candidateId",),
        notes="The profile and its rules are resolved again and put back into the request; an instruction cannot remove them.",
    ),
    # --- deciding
    Operation(
        "image_select", ("select",), "Record a picture as the pick. It changes no Story and is not approval.", "write",
        obj({"candidateId": text(), "candidateRef": text("A stock picture's reference from image_search."), "reason": REASON}, ("reason",), **one_of("candidateId", "candidateRef")),
        record({"candidateId": text(), "selection": SELECTION}, ("candidateId", "selection")),
        ("candidate_closed", "candidate_not_ready", "not_found"),
        (Example({"candidateId": "candidate-1", "reason": "Calmest of the four."},
                 {"candidateId": "candidate-1", "selection": {"by": "account-1", "byKind": "agent", "at": "2026-11-07T18:05:00Z", "reason": "Calmest of the four."}}),),
        positional=("candidateId",),
    ),
    Operation(
        "image_unapply", ("unapply",), "Undo an applied picture: the Story gets a new version with the old cover or the placeholder back.", "write",
        obj({"target": TARGET, "mediaAssetId": text(), "expectedCurrentVersionId": VERSION_GUARD, "reason": REASON,
             "save": flag("Make the new Story version now (default true). The newsroom editor passes false and saves itself.")},
            ("target", "mediaAssetId", "expectedCurrentVersionId", "reason")),
        record({"patch": {"type": "object"}, "restored": choice("previous-cover", "placeholder"), "savedVersion": record({"versionId": text(), "versionNumber": whole()})},
               ("patch", "restored")),
        ("candidate_closed", "not_found", "stale_version"),
        (Example({"target": _STORY, "mediaAssetId": "media-asset-1", "expectedCurrentVersionId": _GUARD, "reason": "Looks like a photograph."},
                 {"patch": {"frontMatter": {"image": None}}, "restored": "placeholder", "savedVersion": {"versionId": "item-story-containment-note-v8", "versionNumber": 8}}),),
        flags=(("mediaAssetId", "media-asset"),),
        notes="The media asset and its record stay. Any editor or agent may unapply.",
    ),
    Operation(
        "image_review", ("review",), "Keep or remove a picture that was added without a person looking at it. Only a person may.", "write",
        obj({"mediaAssetId": text(), "decision": choice("keep", "remove"), "note": text(),
             "expectedCurrentVersionId": text("Needed to remove: the Story's current version id when you read it.")}, ("mediaAssetId", "decision")),
        record({"mediaAssetId": text(), "decision": choice("keep", "remove"), "reviewStatus": choice("unreviewed", "human-verified"),
                "savedVersion": record({"versionId": text(), "versionNumber": whole()})}, ("mediaAssetId", "decision", "reviewStatus")),
        ("human_required", "not_found", "stale_version"),
        (Example({"mediaAssetId": "media-asset-1", "decision": "keep"}, {"mediaAssetId": "media-asset-1", "decision": "keep", "reviewStatus": "human-verified"}),),
        agent_allowed=False, positional=("mediaAssetId",),
        notes="Keep marks the picture human-verified with who and when. Remove runs image_unapply. Either answers the linked review request.",
    ),
    Operation(
        "image_review_queue", ("review-queue",), "List the pictures that were added without a person, oldest first.", "read",
        obj({"nextToken": PAGE["nextToken"]}),
        record({"items": many(record({"mediaAssetId": text(), "target": TARGET, "candidateId": text(), "appliedAt": text(), "appliedBy": text(),
                                      "reviewRequestId": text(), "previewUrl": text()}, ("mediaAssetId", "target"))), **PAGE}, ("items",)),
        (), (Example({}, {"items": [{"mediaAssetId": "media-asset-1", "target": _STORY, "candidateId": "candidate-1", "appliedAt": "2026-11-07T18:10:00Z",
                                     "appliedBy": "account-1", "reviewRequestId": "review-1"}]}),),
    ),
    Operation(
        "image_apply", ("apply",), "Put a picture on a Story: copy it into the site's media and record where it came from. It never publishes.", "write",
        obj({"candidateId": text(), "candidateRef": text("A stock picture's reference from image_search."), "target": TARGET, "use": USE,
             "imageType": IMAGE_TYPE, "alt": text("Alt text; the picture's own draft when left out."), "caption": text(), "expectedCurrentVersionId": VERSION_GUARD,
             "save": flag("Make the new Story version now (default true). The newsroom editor passes false and saves itself.")},
            ("target", "use", "expectedCurrentVersionId"), **one_of("candidateId", "candidateRef")),
        record({"patch": record({"bodyDirective": text(), "frontMatter": {"type": "object"}}, ("bodyDirective", "frontMatter")), "mediaAsset": {"type": "object"},
                "imageType": text(), "reviewStatus": choice("unreviewed", "human-verified"), "reviewRequestId": text(),
                "savedVersion": record({"versionId": text(), "versionNumber": whole()})}, ("patch", "mediaAsset", "reviewStatus")),
        ("candidate_closed", "candidate_not_ready", "checks_failed", "image_type_unknown", "not_found", "source_not_allowed", "stale_version"),
        (Example({"candidateId": "candidate-1", "target": _STORY, "use": "cover", "imageType": "cover-illustration", "expectedCurrentVersionId": _GUARD},
                 {"patch": {"bodyDirective": "::image{src=\"media/assets/containment/cover.png\"}", "frontMatter": {"image": "media/assets/containment/cover.png"}},
                  "mediaAsset": {"id": "media-asset-1"}, "imageType": "cover-illustration", "reviewStatus": "unreviewed", "reviewRequestId": "review-1",
                  "savedVersion": {"versionId": "item-story-containment-note-v8", "versionNumber": 8}}),),
        positional=("candidateId",),
        notes="A person applying from a set they looked at makes it human-verified. Anyone else makes it unreviewed and opens a review request.",
    ),
    Operation(
        "image_discard", ("discard",), "Reject a picture, or a whole round (which keeps the placeholder). The private file is deleted; the record stays.", "write",
        obj({"candidateId": text(), "roundId": text(), "reason": REASON}, ("reason",), **one_of("candidateId", "roundId")),
        record({"discarded": many(text(), "The ids of the pictures that were discarded.")}, ("discarded",)),
        ("candidate_closed", "not_found"),
        (Example({"roundId": "round-1", "reason": "Kept the placeholder."}, {"discarded": ["candidate-1", "candidate-2"]}),),
        positional=("candidateId",), flags=(("roundId", "round"),),
    ),
)

# --- guidelines (PPY-8d41d7; design: docs/plans/guidelines-as-data.md) -----------------------------------------------------------------------------
KIND = text("The kind of guidelines: writing, image or video, or any kind the site has registered. An unknown kind is refused with the list of known ones.")
SECTION = text("A section key. Leave it out for the publication's own guidelines.")
GUIDELINE_DOCUMENT = {"type": "object", "description": "A guideline document of that kind: schemaVersion and the fields the kind allows."}
GUIDELINE_GUARD = text("The current version id of that guideline lineage when you read it (guidelines_get returns it as expectedCurrentVersionId), "
                       "or none for the first save.")
GUIDELINE_CHANGES = many(record({"path": text(), "from": anything(), "to": anything()}, ("path",)))
_GUIDELINE_REF = {"itemId": "item-editorial-doctrine-writing-v2", "versionNumber": 2, "contentHash": "sha256:5c1e"}
_GUIDELINE_DOCUMENT = {"schemaVersion": 1, "audience": "General readers", "tone": ["Warm and plain."], "constraints": [{"id": "no-hype", "text": "No hype."}]}

GUIDELINE_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "guidelines_get", ("show",), "Read a kind of guidelines for the publication or one section, the current version or an older one.", "read",
        obj({"kind": KIND, "section": SECTION, "version": whole("A version number; the current version when left out.")}, ("kind",)),
        record({"kind": text(), "section": text(), "document": GUIDELINE_DOCUMENT, "itemId": text(), "versionNumber": whole(), "contentHash": text(), "updatedAt": text(),
                "updatedBy": text(), "changeReason": {"type": "string"}, "isCurrent": flag(),
                "expectedCurrentVersionId": text("What to pass to guidelines_save to replace this lineage's current version.")},
               ("kind", "document", "itemId", "versionNumber", "contentHash", "expectedCurrentVersionId")),
        ("not_found", "unknown_kind"),
        (Example({"kind": "writing"}, {"kind": "writing", "document": _GUIDELINE_DOCUMENT, **_GUIDELINE_REF, "updatedAt": "2026-11-10T10:00:00Z", "updatedBy": "Ada Admin",
                                       "changeReason": "Narrowed the audience.", "isCurrent": True, "expectedCurrentVersionId": "item-editorial-doctrine-writing-v2"}),),
        group="guidelines",
        notes="Nothing stored yet gives not_found with expectedCurrentVersionId none in details: pass that to the first save.",
    ),
    Operation(
        "guidelines_resolve", ("resolve",), "Show the effective guidelines for the publication or a section laid over it, with where every field came from.", "read",
        obj({"kind": KIND, "section": SECTION}, ("kind",)),
        record({"kind": text(), "section": text(), "found": flag("False when the publication has no guidelines of this kind yet."), "document": GUIDELINE_DOCUMENT,
                "fieldSources": {"type": "object", "description": "For every field, the layer it came from: publication, section, or locked by the publication."},
                "layers": many(record({"scope": choice("publication", "section"), "itemId": text(), "slug": text(), "versionNumber": whole(), "contentHash": text()},
                                      ("scope", "itemId", "versionNumber"))),
                "warnings": many(record({"code": text(), "message": text()}, ("code", "message")))},
               ("kind", "found", "document", "fieldSources", "layers", "warnings")),
        ("unknown_kind", "resolver_not_available", "document_hash_mismatch"),
        (Example({"kind": "writing", "section": "news"}, {"kind": "writing", "section": "news", "found": True, "document": _GUIDELINE_DOCUMENT,
                                                          "fieldSources": {"audience": "publication", "tone": "publication"},
                                                          "layers": [{"scope": "publication", **{**_GUIDELINE_REF, "slug": "editorial-doctrine-writing"}}], "warnings": []}),),
        group="guidelines",
        notes="A publication with no guidelines of the kind gets found false and the warning <kind>_guidelines_missing, not an error. Image guidelines are resolved by "
              "papyrus images profile resolve.",
    ),
    Operation(
        "guidelines_diff", ("diff",), "Show what saving a guideline document would change, without saving it.", "read",
        obj({"kind": KIND, "section": SECTION, "document": GUIDELINE_DOCUMENT}, ("kind", "document")),
        record({"kind": text(), "changes": GUIDELINE_CHANGES, "constraintChanges": many({"type": "object"}), "wouldCreateVersion": whole(minimum=0)},
               ("kind", "changes", "constraintChanges", "wouldCreateVersion")),
        ("unknown_kind",),
        (Example({"kind": "writing", "document": _GUIDELINE_DOCUMENT}, {"kind": "writing", "changes": [{"path": "audience", "from": "Engineers", "to": "General readers"}],
                                                                     "constraintChanges": [], "wouldCreateVersion": 3}),),
        file_field="document", group="guidelines",
        notes="A writing or video document is stored whole, so the diff compares it with the current document field by field. An image document is laid over the "
              "current profile, as image_profile_diff does.",
    ),
    Operation(
        "guidelines_save", ("save",), "Save a guideline document as the next version of its kind and scope.", "write",
        obj({"kind": KIND, "section": SECTION, "document": GUIDELINE_DOCUMENT, "reason": REASON, "expectedCurrentVersionId": GUIDELINE_GUARD},
            ("kind", "document", "reason", "expectedCurrentVersionId")),
        record({"kind": text(), "section": text(), "itemId": text(), "versionNumber": whole(), "contentHash": text(),
                "unchanged": flag("True when the document equals the current version, so no version was made."),
                "repeated": flag("True when this is the first answer to the same request id, returned again.")}, ("kind", "itemId", "versionNumber", "contentHash")),
        ("human_required", "stale_version", "unknown_kind"),
        (Example({"kind": "writing", "document": _GUIDELINE_DOCUMENT, "reason": "Narrowed the audience.", "expectedCurrentVersionId": "item-editorial-doctrine-writing-v1"},
                 {"kind": "writing", **_GUIDELINE_REF}),),
        file_field="document", group="guidelines",
        notes="Only an admin may save; an editor gets not_authorized. Adding, changing or removing a binding constraint needs an admin who is a person: an agent gets "
              "human_required and nothing is saved. The first save of a lineage passes none as expectedCurrentVersionId. The document is stored whole, as given. "
              "Saving a document that equals the current one makes no version. Every problem with a document is listed by field in details.problems.",
    ),
    Operation(
        "guidelines_history", ("history",), "List the versions of a kind of guidelines, newest first, with who changed it and why.", "read",
        obj({"kind": KIND, "section": SECTION}, ("kind",)),
        record({"kind": text(), "section": text(),
                "versions": many(record({"itemId": text(), "versionNumber": whole(), "isCurrent": flag(), "at": text(), "by": text(), "byKind": choice("human", "agent"),
                                         "reason": {"type": "string"}, "contentHash": text()}, ("itemId", "versionNumber", "contentHash")))},
               ("kind", "versions")),
        ("unknown_kind",),
        (Example({"kind": "writing"}, {"kind": "writing", "versions": [{"itemId": "item-editorial-doctrine-writing-v2", "versionNumber": 2, "isCurrent": True,
                                                                         "at": "2026-11-10T10:00:00Z", "by": "Ada Admin", "byKind": "human",
                                                                         "reason": "Narrowed the audience.", "contentHash": "sha256:5c1e"}]}),),
        group="guidelines",
    ),
)

OPERATIONS = OPERATIONS + GUIDELINE_OPERATIONS

BY_NAME = {operation.name: operation for operation in OPERATIONS}
BY_CLI = {(operation.group, operation.cli): operation for operation in OPERATIONS}


def operation(name: str) -> Operation | None:
    return BY_NAME.get(name)
