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

from papyrus_content.agent_rungs import PERSON_ONLY, RUNGS

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
    agent_rung: str = ""                   # the lowest rung of the site's agent policy that lets an agent call it, or "person" when no rung does (see below)
    agent_refusal: Literal["human_required", "blocked"] = "human_required"   # what the gate answers an agent that may never call it
    audience: Literal["staff"] = "staff"   # readers get no image operations
    positional: tuple[str, ...] = ()       # input properties the CLI takes as plain words, in order
    flags: tuple[tuple[str, str], ...] = ()    # (input property, CLI flag name) where the flag is not the property in kebab-case
    file_field: str | None = None          # the property the CLI fills from --file (a JSON or YAML document)
    picture_field: str | None = None       # the property the CLI fills by uploading the picture --file names (an id the upload step returns)
    notes: str = ""                        # anything a reader needs that the schemas cannot say
    delegable: bool = False                # an agent working in a person's own signed-in session (no run gate) may call it on that person's named instruction; a gated run never may
    group: Literal["images", "guidelines", "announcements", "ratings", "handoffs", "agents"] = "images"   # the CLI group (papyrus <group> ...) and the door family the operation is run through

    def __post_init__(self) -> None:
        # A read names no rung and is allowed from `observe`. Every operation that writes or spends must say its rung: there is no default to forget.
        if not self.agent_rung and self.effect == "read":
            object.__setattr__(self, "agent_rung", "observe")
        if self.agent_rung != PERSON_ONLY and self.agent_rung not in RUNGS[1:]:
            raise ValueError(f"{self.name} must name the lowest rung that lets an agent call it ({', '.join(RUNGS[1:])}), or {PERSON_ONLY!r}")

    @property
    def agent_allowed(self) -> bool:
        """Whether any rung lets an agent call it. False: only a person may; the gate answers an agent ``agent_refusal`` at every rung."""
        return self.agent_rung != PERSON_ONLY

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
    ErrorCode("human_required", "A person has to do this one, or approve it; the agent's rung does not let it through. A review request is raised and the run ends asked."),
    ErrorCode("blocked", "No agent may do this at any rung: it changes policy, budget or accounts."),
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
    ErrorCode("stale_version", "The Story or the Delivery has a newer version than the one you named. Read it again.",
              details="for a Delivery, replacedBy names the version that replaced the one you read (number, by, at) and head the newest version"),
    ErrorCode("locked", "The Delivery is locked for sending, so a late edit is refused until a person unlocks it.", details="lockedAt, lockedVersion"),
    ErrorCode("candidate_not_ready", "The picture is still being made."),
    ErrorCode("candidate_closed", "The picture was already discarded, expired or applied."),
    ErrorCode("settings_refused", "The announcement settings break a rule, so nothing was saved.", details="code names the rule"),
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
        agent_rung="prepare",
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
        agent_rung="prepare",
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
        agent_rung="prepare",
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
        agent_rung="draft",
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
        agent_rung="draft",
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
        agent_rung="draft",
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
        agent_rung="draft",
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
        agent_rung="draft",
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
        agent_rung="draft",
    ),
    Operation(
        "image_review", ("review",), "Keep or remove a picture that was added without a person looking at it. Only a person may.", "write",
        obj({"mediaAssetId": text(), "decision": choice("keep", "remove"), "note": text(),
             "expectedCurrentVersionId": text("Needed to remove: the Story's current version id when you read it.")}, ("mediaAssetId", "decision")),
        record({"mediaAssetId": text(), "decision": choice("keep", "remove"), "reviewStatus": choice("unreviewed", "human-verified"),
                "savedVersion": record({"versionId": text(), "versionNumber": whole()})}, ("mediaAssetId", "decision", "reviewStatus")),
        ("human_required", "not_found", "stale_version"),
        (Example({"mediaAssetId": "media-asset-1", "decision": "keep"}, {"mediaAssetId": "media-asset-1", "decision": "keep", "reviewStatus": "human-verified"}),),
        positional=("mediaAssetId",),
        notes="Keep marks the picture human-verified with who and when. Remove runs image_unapply. Either answers the linked review request.",
        agent_rung=PERSON_ONLY,
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
             "imageType": IMAGE_TYPE, "alt": text("Alt text written by someone who has seen the picture. Required: it describes what the picture shows, and is refused when empty or when it equals or contains the generation brief."),
             "reviewed": flag("A person says they looked at the picture. Only a person may; an agent is refused. Without it the picture stays unreviewed and a review request is opened."),
             "caption": text(), "expectedCurrentVersionId": VERSION_GUARD,
             "save": flag("Make the new Story version now (default true). The newsroom editor passes false and saves itself.")},
            ("target", "use", "alt", "expectedCurrentVersionId"), **one_of("candidateId", "candidateRef")),
        record({"patch": record({"bodyDirective": text(), "frontMatter": {"type": "object"}}, ("bodyDirective", "frontMatter")), "mediaAsset": {"type": "object"},
                "imageType": text(), "reviewStatus": choice("unreviewed", "human-verified"), "reviewRequestId": text(),
                "savedVersion": record({"versionId": text(), "versionNumber": whole()})}, ("patch", "mediaAsset", "reviewStatus")),
        ("candidate_closed", "candidate_not_ready", "checks_failed", "human_required", "image_type_unknown", "not_found", "source_not_allowed", "stale_version"),
        (Example({"candidateId": "candidate-1", "target": _STORY, "use": "cover", "imageType": "cover-illustration", "alt": "A locked steel filing cabinet in an empty room.",
                  "expectedCurrentVersionId": _GUARD},
                 {"patch": {"bodyDirective": "::image{src=\"assets/containment/cover.png\"}", "frontMatter": {"image": "assets/containment/cover.png"}},
                  "mediaAsset": {"id": "media-asset-1"}, "imageType": "cover-illustration", "reviewStatus": "unreviewed", "reviewRequestId": "review-1",
                  "savedVersion": {"versionId": "item-story-containment-note-v8", "versionNumber": 8}}),),
        positional=("candidateId",),
        notes="Alt text is required and must describe the picture: never copy the brief, which is an instruction to the model. A picture is human-verified only when a person passes reviewed "
              "(recorded with who and when). Every other apply, an agent's always, leaves it unreviewed and opens a review request.",
        agent_rung="draft",
    ),
    Operation(
        "image_discard", ("discard",), "Reject a picture, or a whole round (which keeps the placeholder). The private file is deleted; the record stays.", "write",
        obj({"candidateId": text(), "roundId": text(), "reason": REASON}, ("reason",), **one_of("candidateId", "roundId")),
        record({"discarded": many(text(), "The ids of the pictures that were discarded.")}, ("discarded",)),
        ("candidate_closed", "not_found"),
        (Example({"roundId": "round-1", "reason": "Kept the placeholder."}, {"discarded": ["candidate-1", "candidate-2"]}),),
        positional=("candidateId",), flags=(("roundId", "round"),),
        agent_rung="draft",
    ),
)

# --- guidelines (PPY-8d41d7; design: docs/plans/guidelines-as-data.md) -----------------------------------------------------------------------------
KIND = text("The kind of guidelines: writing, image or video, or any kind the site has registered. An unknown kind is refused with the list of known ones.")
SECTION = text("A section key. Leave it out for the publication's own guidelines.")
LANGUAGE = text("A language overlay (en, es, es-419, zh-Hans ...): only what is particular to that language, laid over the guidelines every language shares. "
                "Leave it out for the shared guidelines.")
RESOLVE_LANGUAGE = text("The language of the text the guidelines are for: its overlays (a variant's base language first) are laid over the shared guidelines. "
                        "Leave it out for the guidelines every language shares.")
GUIDELINE_DOCUMENT = {"type": "object", "description": "A guideline document of that kind: schemaVersion and the fields the kind allows."}
GUIDELINE_FILES = {"type": "object", "additionalProperties": {"type": "string"},
                   "description": "Guideline files by path, such as plain-claims/GUIDELINE.md: the exact text of each file of the set. Writing guidelines are stored as this set."}
GUIDELINE_GUARD = text("The current version id of that guideline lineage when you read it (guidelines_get returns it as expectedCurrentVersionId), "
                       "or none for the first save.")
GUIDELINE_CHANGES = many(record({"path": text(), "from": anything(), "to": anything()}, ("path",)))
_GUIDELINE_REF = {"itemId": "item-editorial-doctrine-writing-v2", "versionNumber": 2, "contentHash": "sha256:5c1e"}
_GUIDELINE_DOCUMENT = {"schemaVersion": 2, "audience": "General readers", "tone": ["Warm and plain."], "constraints": [{"id": "no-hype", "text": "No hype."}]}

GUIDELINE_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "guidelines_get", ("show",), "Read a kind of guidelines for the publication or one section, the current version or an older one.", "read",
        obj({"kind": KIND, "section": SECTION, "language": LANGUAGE, "version": whole("A version number; the current version when left out.")}, ("kind",)),
        record({"kind": text(), "section": text(), "language": text(), "document": GUIDELINE_DOCUMENT, "files": GUIDELINE_FILES, "itemId": text(), "versionNumber": whole(), "contentHash": text(), "updatedAt": text(),
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
        "guidelines_resolve", ("resolve",), "Show the effective guidelines for the publication or a section laid over it, and for one language, with where every field came from.", "read",
        obj({"kind": KIND, "section": SECTION, "language": RESOLVE_LANGUAGE,
             "channel": text("The channel the text is for (x, linkedin, email): a rule file scoped to channel/<name> is in the answer only for that channel.")}, ("kind",)),
        record({"kind": text(), "section": text(), "language": text(), "channel": text(), "found": flag("False when the publication has no guidelines of this kind yet."), "document": GUIDELINE_DOCUMENT,
                "fieldSources": {"type": "object", "description": "For every field, the layers it came from: publication, section, language or section-language (with the language)."},
                "layers": many(record({"scope": choice("publication", "section", "language", "section-language"), "language": text(), "itemId": text(), "slug": text(),
                                       "versionNumber": whole(), "contentHash": text()},
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
        obj({"kind": KIND, "section": SECTION, "language": LANGUAGE, "document": GUIDELINE_DOCUMENT, "files": GUIDELINE_FILES}, ("kind",)),
        record({"kind": text(), "section": text(), "language": text(), "changes": GUIDELINE_CHANGES, "constraintChanges": many({"type": "object"}), "wouldCreateVersion": whole(minimum=0),
                "fileChanges": many(record({"path": text(), "change": choice("added", "changed", "removed")}, ("path", "change")))},
               ("kind", "changes", "constraintChanges", "wouldCreateVersion")),
        ("unknown_kind",),
        (Example({"kind": "writing", "document": _GUIDELINE_DOCUMENT}, {"kind": "writing", "changes": [{"path": "audience", "from": "Engineers", "to": "General readers"}],
                                                                     "constraintChanges": [], "wouldCreateVersion": 3}),),
        file_field="document", group="guidelines",
        notes="Give a document, or for guidelines stored as files (writing) the files. A document is compared with the current one field by field, and a writing "
              "document's field files over the rule files the current version holds; fileChanges lists the files that would be added, changed or removed. An image document "
              "is laid over the current profile, as image_profile_diff does.",
    ),
    Operation(
        "guidelines_save", ("save",), "Save a guideline document as the next version of its kind and scope.", "write",
        obj({"kind": KIND, "section": SECTION, "language": LANGUAGE, "document": GUIDELINE_DOCUMENT, "files": GUIDELINE_FILES, "reason": REASON, "expectedCurrentVersionId": GUIDELINE_GUARD},
            ("kind", "reason", "expectedCurrentVersionId")),
        record({"kind": text(), "section": text(), "language": text(), "itemId": text(), "versionNumber": whole(), "contentHash": text(),
                "unchanged": flag("True when the document equals the current version, so no version was made."),
                "repeated": flag("True when this is the first answer to the same request id, returned again.")}, ("kind", "itemId", "versionNumber", "contentHash")),
        ("human_required", "stale_version", "unknown_kind"),
        (Example({"kind": "writing", "document": _GUIDELINE_DOCUMENT, "reason": "Narrowed the audience.", "expectedCurrentVersionId": "item-editorial-doctrine-writing-v1"},
                 {"kind": "writing", **_GUIDELINE_REF}),),
        file_field="document", group="guidelines",
        notes="Only an admin may save; an editor gets not_authorized. Adding, changing or removing a binding constraint needs an admin who is a person: an agent gets "
              "human_required and nothing is saved. The first save of a lineage passes none as expectedCurrentVersionId. Give a document, or for writing guidelines the "
              "files (papyrus guidelines save --dir DIR): the set is stored exactly as given and exports back byte for byte. Saving structured fields keeps the rule files "
              "the current version holds. Saving what equals the current version makes no version. Every problem with a document is listed by field in details.problems.",
        agent_rung="prepare",
    ),
    Operation(
        "guidelines_history", ("history",), "List the versions of a kind of guidelines, newest first, with who changed it and why.", "read",
        obj({"kind": KIND, "section": SECTION, "language": LANGUAGE}, ("kind",)),
        record({"kind": text(), "section": text(), "language": text(),
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

# --- announcements (PPY-09ee86): the same table serves `papyrus announcements ...`, the MCP tools and the console ----------------------------------------
STORY_LINEAGE = text("The lineage id of the Story.")
EDIT_WINDOW = record({"kind": text("The kind of Announcement, such as story_published or roundup. Absent: every kind."), "channel": text("The channel, such as x or email. Absent: every channel."),
                      "windowMinutes": whole("Minutes from the Delivery's creation to its release: how long it stays a draft that people edit.", minimum=0),
                      "lockLeadMinutes": whole("Minutes before the release that the Delivery locks for the send job. At most the window; 0 is no separate lock.", minimum=0)}, ("windowMinutes",))
SETTINGS = record({
    "mode": choice("off", "dry_run", "on"), "rules": {"type": "object", "description": "minStars, storyTypes, sections and requireReviewedSource: what is announced."},
    "budget": {"type": ["number", "null"], "description": "Dollars for each X billing cycle. No default."}, "billingCycleDay": {"type": ["integer", "null"]},
    "prices": {"type": "object", "description": "X's price list: createPost, createPostWithUrl, deletePost, readPost in dollars, and asOf, the date it was copied."},
    "labelConfirmed": flag(), "spacing": {"type": "object", "description": "Minutes between posts on each channel account, by <channel>#<account>. Empty: no spacing."},
    "pause": {"type": "object", "description": "paused, reason (budget, disconnected or manual), detail, by and at."},
    "editWindows": many(EDIT_WINDOW),
}, ("mode",))
_EX_SETTINGS = {"mode": "dry_run", "rules": {"minStars": 5, "storyTypes": ["article"], "sections": [], "requireReviewedSource": False}, "budget": 10, "billingCycleDay": 1,
                "prices": {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}, "labelConfirmed": True,
                "editWindows": [{"kind": "story_published", "channel": "x", "windowMinutes": 20, "lockLeadMinutes": 5}],
                "pause": {"paused": False, "reason": None, "detail": None, "by": None, "at": None}}

ANNOUNCEMENT_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "announcements_dry_run", ("dry-run",), "Build the exact post a Story would get (text, link with its UTM tags, length, every check) without sending or recording anything.", "read",
        obj({"story": STORY_LINEAGE}, ("story",)),
        record({"lineageId": text(), "eligible": flag(), "reason": text(), "text": text(), "post": text(), "link": text(), "weight": whole(minimum=0),
                "checks": many({"type": "object"}), "passed": flag(), "failures": many(text()), "sent": flag()}, ("lineageId", "post", "weight", "passed", "sent")),
        ("not_found",), (Example({"story": "story-1"}, {"lineageId": "story-1", "eligible": True, "reason": "eligible", "text": "A look at secrets.", "post": "A look at secrets.\n\nhttps://example.org/s?utm_source=x",
                                                          "link": "https://example.org/s?utm_source=x", "weight": 45, "checks": [], "passed": True, "failures": [], "sent": False}),),
        positional=("story",), group="announcements",
        notes="Makes one model call to draft the text. Works for any Story, announced or not, in any mode; `eligible` and `reason` say whether the site's rules would announce it.",
    ),
    Operation(
        "announcements_pause", ("pause",), "Pause announcements: nothing is posted, and an X Delivery that comes due waits as Blocked: paused.", "write",
        obj({}),
        record({"paused": flag(), "pausedBy": text(), "pausedAt": text(), "pauseReason": text()}, ("paused",)), (),
        (Example({}, {"paused": True, "pausedBy": "Ada Admin", "pausedAt": "2026-11-13T10:02:00Z", "pauseReason": "Paused by hand."}),), group="announcements",
        notes="The site's announcements function lets only an admin change the pause. Announcements also pause by themselves, for the budget or a broken X connection, and say why.",
        agent_rung="propose",
    ),
    Operation(
        "announcements_resume", ("resume",), "Resume announcements and put back the X Deliveries that waited.", "write",
        obj({}), record({"released": many({"type": "object"}), "paused": flag()}, ("released", "paused")), (),
        (Example({}, {"released": [], "paused": False}),), group="announcements",
        agent_rung=PERSON_ONLY,
    ),
    Operation(
        "announcements_settings_show", ("settings", "show"), "Show the site's announcement settings: mode, bar, Story types, sections, account, budget, prices and the pause.", "read",
        obj({}), record({"settings": SETTINGS, "connection": {"type": "object", "description": "The X connection's status: connection, handle, accountId and refresh health. Never a secret."}}, ("settings", "connection")), (),
        (Example({}, {"settings": _EX_SETTINGS, "connection": {"connection": "connected", "handle": "@mom_test", "accountId": "mom"}}),), group="announcements",
    ),
    Operation(
        "announcements_settings_set", ("settings", "set"), "Change announcement settings. Every rule is checked and every problem listed; nothing is saved when any fails.", "write",
        obj({"mode": choice("off", "dry_run", "on", description="Off (default), Dry run (builds the post, sends nothing) or On."),
             "minStars": whole("The lowest star rating that is announced, 1 to 5, never below the quality floor (3 stars)."),
             "storyTypes": many(text(), "Story types that are announced: article, post. References are never announced."), "sections": many(text(), "Limit to these sections."),
             "requireReviewedSource": flag("On: an Announcement is made only for a Story a person has reviewed on its current version (its review step done by a person, or by an agent "
                                          "on a person's recorded instruction). Off by default."),
             "budget": text("Dollars for each X billing cycle, such as 10.00. No default."), "billingCycleDay": whole("The day of the month your X billing cycle starts."),
             "prices": {"type": "object", "description": "X's price list in dollars: createPost, createPostWithUrl, deletePost, readPost, and asOf (YYYY-MM-DD, the date you copied it)."},
             "labelConfirmed": flag("The account shows X's Automated label, managed by a person's account."),
             "spacing": {"type": "object", "description": "Minutes between one post and the next on a channel account, by account (<channel>#<account>, such as x#handle). A number sets it, null takes it away; "
                                                           "an account that is not named keeps what it has. Empty by default: no spacing."},
             "editWindows": many(EDIT_WINDOW, "How long a Delivery stays a draft that people edit, and how long before its release it locks, for each kind of Announcement and channel. "
                                                "The narrowest entry that fits wins. This replaces the whole list; an empty list means no window.")}),
        record({"settings": SETTINGS, "released": many({"type": "object"})}, ("settings", "released")), ("settings_refused", "blocked"),
        (Example({"minStars": 5}, {"settings": _EX_SETTINGS, "released": []}),), group="announcements",
        notes="A person only: it sets what the publication says in public and how much it may spend. Human review is not here: it is the announce rung of the agent policy (announcements_review_set). "
              "prices, spacing and editWindows are given with --input-file. The X account is connected in the browser, never here. Raising the budget, or any change while Deliveries wait on a guard, puts the Deliveries that waited back to ready.",
        agent_rung=PERSON_ONLY, agent_refusal="blocked",
    ),
    Operation(
        "announcements_account_status", ("account", "status"), "Show mode, pause, the cycle's spend against the budget, and the connected account.", "read",
        obj({}), record({"mode": text(), "paused": flag(), "accountId": text(), "accountHandle": text(), "standing": text("For example $0.60 spent of $10.00 this cycle."),
                         "postCount": whole("Our count of the posts this account sent in the current billing cycle, a post later deleted included (X charged for it). X's own count is read beside it on the page.", minimum=0),
                         "suggestion": record({"eligibleCount": whole(minimum=0), "windowDays": whole(), "postsPerMonth": {"type": "number"}, "dollarsPerMonth": {"type": "number"}, "sentence": text()},
                                              ("sentence",)),
                         "pauseReason": text(), "pricesAsOf": text()}, ("mode", "paused")), (),
        (Example({}, {"mode": "dry_run", "paused": False, "accountId": "mom", "standing": "$0.00 spent of $10.00 this cycle"}),), group="announcements",
        notes="Connecting an X account needs the browser (OAuth): the newsroom's Administration > Announcements page (`announcements account connect` prints the link). The app's keys are saved with `announcements account set-app`; the secret is never a flag. "
              "`suggestion` is the site's own pace over the last 60 days at the link price, shown as a pace and never applied as a limit; it is left out until the prices are entered.",
    ),
    Operation(
        "announcements_account_connect", ("account", "connect"), "Print the newsroom page where the X account is connected. Connecting is a browser step (OAuth): nothing is connected from here.", "read",
        obj({}), record({"url": text("The address of Administration > Announcements in the newsroom."), "words": text()}, ("url", "words")), ("service_unavailable",),
        (Example({}, {"url": "https://news.example.test/newsroom/administration/announcements", "words": "Open this page in the newsroom and choose Connect X account. Connecting needs the browser; no secret is ever typed here."}),),
        group="announcements",
        notes="The address is built from the console's own address (PAPYRUS_CONSOLE_URL, or the one the signed-in site publishes), never guessed: without one it says so and prints nothing. It reads nothing "
              "from the site and writes nothing.",
    ),
    Operation(
        "announcements_account_set_app", ("account", "set-app"), "Save the X developer app's client ID and client secret: the secret into SSM SecureString and the ID into the connection record, together.", "write",
        obj({"clientId": text("The OAuth 2.0 client ID of the X app."), "clientSecret": text("The OAuth 2.0 client secret. On the command line it is read from PAPYRUS_X_CLIENT_SECRET or from standard input, never from a flag.")},
            ("clientId", "clientSecret")),
        record({"status": record({"connection": text()}, ("connection",)), "saved": flag("True when both the secret and the client ID were saved.")}, ("saved",)), (),
        (Example({"clientId": "client-id-1", "clientSecret": "client-secret-1"}, {"status": {"connection": "not_connected"}, "saved": True}),), group="announcements",
        agent_rung=PERSON_ONLY, agent_refusal="blocked",
        notes="A person only, and an admin of the site. It saves the app keys the console's Save keys button saves, and the answer never carries the secret: a --dry-run shows it as (hidden). "
              "At a terminal, run it with no flags: it asks for the client ID and the secret (hidden). The secret is never a flag: set PAPYRUS_X_CLIENT_SECRET, or pipe it in (`printf %s \"$SECRET\" | papyrus announcements account set-app --client-id ID`). "
              "Connecting the account itself is still the browser step (`announcements account connect`).",
    ),
    Operation(
        "announcements_hashtags", ("hashtags",), "List the hashtags a Story's announcement may use: its accepted tagged concepts, most-used first.", "read",
        obj({"story": STORY_LINEAGE}, ("story",)),
        record({"lineageId": text(), "hashtags": many(text("A hashtag with its #, in CamelCase, for example #VoiceCloning."))}, ("lineageId", "hashtags")), (),
        (Example({"story": "story-1"}, {"lineageId": "story-1", "hashtags": ["#VoiceCloning", "#Newsrooms"]}),), positional=("story",), group="announcements",
        notes="Reads only. The announcement draft may add at most two of these and no other hashtag; a Story with no accepted concept has none. The order is how many Stories use the concept.",
    ),
    Operation(
        "announcements_blocked", ("blocked",), "List the Stories that qualified for X and are waiting, each with its reason (paused, budget reached, the account needs connecting again, a failed check).", "read",
        obj({}), record({"blocked": many(record({"delivery": text(), "announcementId": text(), "stories": many(record({"lineageId": text()}, ("lineageId",))), "reason": text(), "words": text(),
                                                  "since": text()}, ("delivery", "announcementId", "stories", "reason", "words")))}, ("blocked",)), (),
        (Example({}, {"blocked": [{"delivery": "announcement-1#x#handle-1#g1", "announcementId": "announcement-1", "stories": [{"lineageId": "slow-water"}], "reason": "paused",
                                   "words": "Blocked: paused", "since": "2026-11-17T09:00:00Z"}]}),), group="announcements",
        notes="One entry for each blocked X Delivery of the connected account, newest first, read from the account's Deliveries index. A Story that never qualified is not listed: `explain` says why it did not. "
              "Resuming (a bigger budget, `resume`, a reconnected account) puts the Deliveries back to ready.",
    ),
    Operation(
        "announcements_retry", ("retry",), "Try a failed Delivery again: it goes back to ready, and the next try is the next attempt. The attempts so far stay in its log.", "write",
        obj({"delivery": text("The Delivery's id.")}, ("delivery",)),
        record({"id": text(), "state": text("The Delivery's state afterwards: ready.")}, ("id", "state")), ("not_found", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle-1#g1"}, {"id": "announcement-1#x#handle-1#g1", "state": "ready"}),), positional=("delivery",), group="announcements", agent_rung=PERSON_ONLY,
        notes="A person only: an agent is told human_required, because a failed post may be failing for a reason a person should read first. Only a failed Delivery is retried; any other state is refused as "
              "constraint_conflict with the state named. A Delivery whose draft was blocked by a failed check is not retried: change its words or answer its review request.",
    ),
)

OPERATIONS = OPERATIONS + ANNOUNCEMENT_OPERATIONS

# --- review: the announce rung, its overrides, and what an agent may do with a Delivery (PPY-97c0f2) ---------------------------------------------------------
_APPROVAL = choice("none", "soft", "hard", description="none: fully automatic. soft: a person may edit or stop it before its lock time; silence lets it go. hard: a person must release it.")
_REVIEW_SCOPE = {"channel": text("Narrow to one channel, such as linkedin."), "kind": text("Narrow to one kind of Announcement, such as roundup or story_published."),
                 "list": text("Narrow to one newsletter list.")}
_REVIEW_RESULT = record({"policyVersion": whole(minimum=0), "approval": {"type": ["string", "null"]}, "rung": text(), "scope": {"type": ["object", "null"]}, "changed": flag()},
                        ("policyVersion", "changed"))

_DRAFT_RESULT = record({"id": text(), "status": choice("saved", "preferred", "unchanged", "dropped", "candidate", description="saved: a new version. preferred: saved while an attempt is open, so it never changes that attempt. "
                                                      "unchanged: the words are the ones you read. dropped: a machine's redraft that the person's newer version outranks. candidate: kept beside the draft."),
                        "version": whole(), "replaces": {"type": ["integer", "null"]}, "reason": text(), "candidate": text("The candidate's id, when one was kept."),
                        "approvedVersion": {"type": ["integer", "null"]}, "lockedVersion": {"type": ["integer", "null"]}, "preferredVersion": {"type": ["integer", "null"]},
                        "blocks": many({"type": "object"}, "Each block's owner (human or machine) and whether it is pinned.")}, ("id", "status"))

REVIEW_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "announcements_review_show", ("review", "show"), "Show the publication's announcement review and each override, and what a channel and kind would get.", "read",
        obj({"channel": _REVIEW_SCOPE["channel"], "kind": _REVIEW_SCOPE["kind"], "list": _REVIEW_SCOPE["list"]}),
        record({"policyVersion": whole(minimum=0), "approval": {"type": ["string", "null"]}, "rung": text(), "overrides": many({"type": "object"}),
                "chosen": {"type": ["object", "null"], "description": "With a channel and kind: the approval, the rung and where it came from."}}, ("policyVersion", "rung", "overrides")), (),
        (Example({"channel": "linkedin", "kind": "roundup"}, {"policyVersion": 3, "approval": "soft", "rung": "publish_soft", "overrides": [{"scope": {"kind": "roundup"}, "approval": "hard", "rung": "prepare"}],
                                                              "chosen": {"approval": "hard", "rung": "prepare", "policy": "override: kind roundup (agent policy version 3)"}}),), group="announcements",
        notes="announcementReview is the rung of the announce responsibility in the site's agent policy: hard is prepare, soft is publish_soft, none is publish_auto. "
              "Narrowest wins: the publication, then a channel, then an Announcement kind, then a list.",
    ),
    Operation(
        "announcements_review_set", ("review", "set"), "Set the announcement review for the publication, or for one channel, kind or list. Applies to Announcements made afterwards.", "write",
        obj({"approval": choice("none", "soft", "hard", "inherit", description=f"{_APPROVAL['description']} inherit takes an override away, so that scope follows the next wider one."), **_REVIEW_SCOPE,
             "reason": REASON,
             "onInstructionOf": text("For an agent only: the person whose signed-in admin session it runs in, on whose instruction it acts."),
             "quote": text("For an agent only: that person's own words."), "agent": text("For an agent only: its name, recorded as the one who entered the change.")}, ("approval", "reason")),
        _REVIEW_RESULT, ("constraint_conflict",),
        (Example({"approval": "hard", "kind": "roundup", "reason": "Roundups wait for a person."}, {"policyVersion": 4, "approval": "hard", "rung": "prepare", "scope": {"kind": "roundup"}, "changed": True}),),
        group="announcements", agent_rung=PERSON_ONLY, agent_refusal="blocked", delegable=True,
        notes="An admin who is a person, or an agent in that person's own session on that person's instruction (never an agent run under the ladder's gate, which is blocked at every rung): it gives onInstructionOf (the person whose admin session it runs in), quote and agent, and may go no higher than hard (prepare); "
              "the change is recorded as the person's via the agent, with their words in the reason. An agent that gives none of them is blocked. Each change is a new version of the agent policy with who, when and why. An Announcement already planned keeps the review it was "
              "made under unless an editor changes that one (announcements_delivery_review_set). none is the rung publish_auto, which the ladder's hard floor refuses until the doubt gate exists (PPY-36e7c9).",
    ),
    Operation(
        "announcements_delivery_review_set", ("delivery", "review"), "Change the review of one Delivery that has not gone. The publication's policy and the other Deliveries do not change.", "write",
        obj({"delivery": text("The Delivery's id."), "approval": _APPROVAL,
             "onInstructionOf": text("For an agent only: the person whose signed-in admin session it runs in, on whose instruction it acts."),
             "quote": text("For an agent only: that person's own words."), "agent": text("For an agent only: its name, recorded as the one who entered the change.")}, ("delivery", "approval")),
        record({"id": text(), "approval": text(), "approvalPolicy": text(), "approvedBy": {"type": ["string", "null"]}}, ("id", "approval", "approvalPolicy")), ("not_found",),
        (Example({"delivery": "announcement-1#linkedin#page#g1", "approval": "hard"}, {"id": "announcement-1#linkedin#page#g1", "approval": "hard", "approvalPolicy": "set for this Delivery by Ada Admin", "approvedBy": None}),),
        group="announcements", positional=("delivery",), agent_rung=PERSON_ONLY, delegable=True,
        notes="A person (an editor or an admin), or an agent in an admin's own session on that person's named instruction (onInstructionOf, quote, agent; never a gated run): "
              "the person chose this one Delivery's review, recorded as theirs via the agent with their words. none approves the current version, so the person should have read it. "
              "An agent that names nobody gets human_required.",
    ),
    Operation(
        "announcements_draft", ("draft",), "Save a Delivery's words as the next version, or keep a text or picture beside the draft as a candidate.", "write",
        obj({"delivery": text("The Delivery's id."), "replaces": whole("The version of the Delivery you read. Refused as stale_version, naming the version that replaced it, when the Delivery has moved on."),
             "text": text("The words. A person's save marks the blocks it changed as theirs and pinned; an agent's redraft keeps every pinned block as it is."),
             "imageKey": text("The picture of the version, or of the candidate."),
             "candidate": flag("Keep this text or picture beside the draft as a candidate (nothing goes out differently) instead of saving a version. No replaces is needed.")}, ("delivery",)),
        _DRAFT_RESULT, ("not_found", "stale_version", "locked", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle#g1", "replaces": 1, "text": "The tide tables are out."},
                 {"id": "announcement-1#x#handle#g1", "status": "saved", "version": 2, "replaces": 1, "approvedVersion": None, "lockedVersion": None}),),
        group="announcements", positional=("delivery",), agent_rung="draft",
        notes="Every save is a new version and no version is overwritten. A person's edit while an attempt is open does not change that attempt: it is saved as the next version, flagged preferred (status preferred). "
              "After the lock a late edit is refused (locked) until a person unlocks the Delivery. An agent's redraft that is stale, late or against an attempt in flight is dropped (status dropped, nothing written) because "
              "the person's version is newer. Sending it is not part of saving: it goes at its release time as its review says.",
    ),
    Operation(
        "announcements_candidate_choose", ("candidate", "choose"), "Choose one candidate as the Delivery's words: a new version. The other candidates are kept.", "write",
        obj({"delivery": text("The Delivery's id."), "candidate": text("The candidate's id, such as c1."), "replaces": whole("The version of the Delivery you read.")}, ("delivery", "candidate", "replaces")),
        _DRAFT_RESULT, ("not_found", "stale_version", "locked"),
        (Example({"delivery": "announcement-1#x#handle#g1", "candidate": "c1", "replaces": 2},
                 {"id": "announcement-1#x#handle#g1", "status": "saved", "version": 3, "replaces": 2, "approvedVersion": None, "lockedVersion": None}),),
        group="announcements", positional=("delivery", "candidate"), agent_rung="draft",
        notes="A save like any other: it names the version it replaces, is refused after the lock, and an agent's choice keeps every pinned block.",
    ),
    Operation(
        "announcements_versions", ("versions",), "List a Delivery's versions and candidates: who saved each, when, what it replaced and which blocks are pinned. With a version or a candidate, its words.", "read",
        obj({"delivery": text("The Delivery's id."), "version": whole("Show the words of this version."), "candidate": text("Show the words of this candidate.")}, ("delivery",)),
        record({"id": text(), "version": whole(), "approvedVersion": {"type": ["integer", "null"]}, "lockedVersion": {"type": ["integer", "null"]}, "lockedAt": {"type": ["string", "null"]},
                "preferredVersion": {"type": ["integer", "null"]}, "versions": many({"type": "object"}), "candidates": many({"type": "object"}), "text": text("The words asked for.")},
               ("id", "version", "versions", "candidates")), ("not_found",),
        (Example({"delivery": "announcement-1#x#handle#g1"},
                 {"id": "announcement-1#x#handle#g1", "version": 2, "approvedVersion": None, "lockedVersion": None, "lockedAt": None, "preferredVersion": None,
                  "versions": [{"number": 1, "by": "announce", "owner": "machine", "at": "2026-11-16T14:00:00Z", "replaces": None, "blocks": [{"owner": "machine", "pinned": False}]},
                               {"number": 2, "by": "ellie", "owner": "human", "at": "2026-11-16T14:05:00Z", "replaces": 1, "blocks": [{"owner": "human", "pinned": True}]}],
                  "candidates": []}),),
        group="announcements", positional=("delivery",),
        notes="Read this to know the version to name when you save: a save names the version it replaces.",
    ),
    Operation(
        "announcements_pinned_change", ("pinned",), "Change or unpin a block a person pinned, as the next version.", "write",
        obj({"delivery": text("The Delivery's id."), "replaces": whole("The version of the Delivery you read."), "block": whole("The block, counting from 1."),
             "text": text("The block's new words, one paragraph. It stays pinned."), "unpin": flag("Unpin the block, so a later redraft may rewrite it.")}, ("delivery", "replaces", "block")),
        _DRAFT_RESULT, ("not_found", "stale_version", "locked", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle#g1", "replaces": 2, "block": 1, "unpin": True},
                 {"id": "announcement-1#x#handle#g1", "status": "saved", "version": 3, "replaces": 2, "approvedVersion": None, "lockedVersion": None}),),
        group="announcements", positional=("delivery",), agent_rung=PERSON_ONLY, agent_refusal="blocked",
        notes="A person only. An agent is blocked at every rung: what a person pinned stays.",
    ),
    Operation(
        "announcements_release", ("release",), "Release a Delivery: hand it to its channel now.", "write",
        obj({"delivery": text("The Delivery's id.")}, ("delivery",)), record({"id": text()}, ("id",)), ("not_found",), (Example({"delivery": "announcement-1#x#handle#g1"}, {"id": "announcement-1#x#handle#g1"}),),
        group="announcements", positional=("delivery",), agent_rung="publish_auto",
        notes="Under none the policy released it, so an agent at publish_auto may. Under soft or hard an agent is told human_required: a person releases it. A person always may. "
              "Releasing approves the version that would go, as the caller; the announce agent wakes for that approval and sends it through the channel. Releasing one already approved changes nothing.",
    ),
    Operation(
        "announcements_unlock", ("unlock",), "Unlock a Delivery after its lock time, so it can be edited again.", "write",
        obj({"delivery": text("The Delivery's id."), "lockAt": text("When it locks again (UTC), after now and no later than the release. By default the release time."),
             "releaseAt": text("A new release time (UTC), when the old one has passed.")}, ("delivery",)),
        record({"id": text(), "lockAt": text(), "releaseAt": text(), "lockedVersion": {"type": ["integer", "null"]}}, ("id", "lockAt", "releaseAt")), ("not_found", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle#g1", "lockAt": "2026-11-17T08:55:00Z"},
                 {"id": "announcement-1#x#handle#g1", "lockAt": "2026-11-17T08:55:00Z", "releaseAt": "2026-11-17T09:00:00Z", "lockedVersion": None}),),
        group="announcements", positional=("delivery",), agent_rung=PERSON_ONLY,
        notes="A person only; an agent is told human_required. Unlocking is an event, not a lease: nothing expires, and a Delivery nobody unlocks stays as locked. The version that was approved stays approved; "
              "an edit makes a new, unapproved version. Refused while an attempt is open (an edit then is saved as a preferred version) and after the Delivery went.",
    ),
    Operation(
        "announcements_example", ("example",), "Say how far what a person changed in an announcement should reach, so later drafts can follow it.", "write",
        obj({"delivery": text("The Delivery's id: one that went out, or one with a preferred version."),
             "scope": choice("this_one", "channel", "kind", "publication", description="How far the change reaches: just this one, this channel, this kind of announcement on this channel, or the whole publication. Leave it out to keep the edit as a candidate."),
             "reason": text("One line on why, kept with the words in S3 and never in the catalog. It goes with a scope.")}, ("delivery",)),
        record({"id": text(), "recorded": {"type": "boolean"}, "exampleState": {"type": ["string", "null"]}, "exampleScope": {"type": ["string", "null"]}, "machineVersion": {"type": ["integer", "null"]},
                "finalVersion": {"type": ["integer", "null"]}, "reason": {"type": ["string", "null"]}}, ("id", "recorded")),
        ("not_found", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle#g1", "scope": "channel", "reason": "Lead with the place, not the title."},
                 {"id": "announcement-1#x#handle#g1", "recorded": True, "exampleState": "active", "exampleScope": "channel", "machineVersion": 1, "finalVersion": 2, "reason": None}),),
        group="announcements", positional=("delivery",), agent_rung=PERSON_ONLY,
        notes="A person only: an edit becomes an example only when a person says so. With no scope the edit is a candidate and changes nothing about any later draft; a scope of this_one also changes nothing. "
              "Nothing is recorded for a Delivery whose final version has no words a person changed.",
    ),
    Operation(
        "announcements_preferred", ("preferred",), "Save how a Delivery that went out should have read, as a preferred version that is never sent. It teaches; it changes no public text.", "write",
        obj({"delivery": text("The Delivery's id: one that went out, or has an attempt open."), "replaces": whole("The version of the Delivery you read."), "text": text("How it should have read."),
             "scope": choice("this_one", "channel", "kind", "publication", description="Also record how far it reaches, in the same step. Leave it out to keep it as a candidate."),
             "reason": text("One line on why. It goes with a scope.")}, ("delivery", "replaces", "text")),
        _DRAFT_RESULT, ("not_found", "stale_version", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle#g1", "replaces": 1, "text": "Slow water has landed.", "scope": "channel"},
                 {"id": "announcement-1#x#handle#g1", "status": "preferred", "version": 2, "replaces": 1, "approvedVersion": None, "lockedVersion": 1, "preferredVersion": 2}),),
        group="announcements", positional=("delivery",), agent_rung=PERSON_ONLY,
        notes="A person only. It sends nothing and changes no public text: an email cannot be recalled and a new post costs money and attention. Whether to also correct the public post is a separate choice "
              "(announcements correct, a superseding Delivery where the channel can delete); teaching and correcting are decided one at a time.",
    ),
    Operation(
        "announcements_correct", ("correct",), "Correct a Delivery that went with a new public text: the next generation, which supersedes the one that went.", "write",
        obj({"delivery": text("The id of the Delivery that went and is to be corrected."), "text": text("The corrected public text. It is checked like the text of a new Delivery.")}, ("delivery", "text")),
        record({"id": text("The new Delivery's id."), "generation": {"type": "integer", "description": "The new Delivery's generation."}, "supersedes": text("The id of the Delivery it replaces."),
                "state": text("The new Delivery's state."), "approval": text("The review the new Delivery goes under: the one the old Delivery had."),
                "checks": many(obj({"name": text(), "passed": {"type": "boolean"}}, ("name", "passed")), "The checks the new text passed.")}, ("id", "generation", "supersedes", "state", "approval", "checks")),
        ("not_found", "constraint_conflict", "checks_failed"),
        (Example({"delivery": "announcement-1#x#handle#g1", "text": "A look at how slow water shapes stone, corrected."},
                 {"id": "announcement-1#x#handle#g2", "generation": 2, "supersedes": "announcement-1#x#handle#g1", "state": "ready", "approval": "none",
                  "checks": [{"name": "length", "passed": True}, {"name": "markup", "passed": True}, {"name": "facts", "passed": True}]}),),
        group="announcements", positional=("delivery",), agent_rung="prepare",
        notes="An agent follows that Delivery's review value: the correction is made at prepare, and it goes only as its own approval says. Only a Delivery that went is corrected, and only once an "
              "attempt has an answer: a Delivery that never went is edited, an open attempt is settled first, another person's different correction is a conflict, and a Delivery that "
              "already has a correction is refused, each as constraint_conflict with the reason in plain words. The text goes through the checks of a new Delivery before anything is "
              "written; a check that fails is checks_failed and nothing is written. The old post on X is deleted as part of the correction when the site's own X channel makes it, and otherwise when the corrected Delivery is sent; the deletion cost is written on the old Delivery.",
    ),
    Operation(
        "announcements_record_manual", ("record-manual",), "Record the address of a post a person made by hand for a manual Delivery: the Delivery becomes sent and its attempt names that person.", "write",
        obj({"delivery": text("The Delivery's id."), "url": text("The address of the post, an http or https URL.")}, ("delivery", "url")),
        record({"id": text(), "state": text(), "resultUrl": text(), "attempt": {"type": "object", "description": "The attempt that was written: number, at, outcome, by and url."}}, ("id", "state", "resultUrl", "attempt")),
        ("not_found", "constraint_conflict"),
        (Example({"delivery": "announcement-1#x#handle#g1", "url": "https://example.org/status/1"},
                 {"id": "announcement-1#x#handle#g1", "state": "sent", "resultUrl": "https://example.org/status/1",
                  "attempt": {"number": 1, "at": "2026-11-17T09:05:00Z", "outcome": "sent", "by": "Ada Admin", "url": "https://example.org/status/1"}}),),
        group="announcements", positional=("delivery",), agent_rung=PERSON_ONLY,
        notes="A person only, and the attempt names the signed-in person who posted it: an agent is told human_required. Only a manual Delivery that is ready (its words drafted and checked) is recorded, "
              "once. No channel ever sends a manual Delivery.",
    ),
    Operation(
        "announcements_withdraw", ("withdraw",), "Withdraw a Delivery: stop one that has not gone, or take back one that went where the channel can (a post on X is deleted).", "write",
        obj({"delivery": text("The Delivery's id.")}, ("delivery",)),
        record({"id": text(), "state": text("The Delivery's state afterwards: withdrawn."), "withdrawnBy": text("Who withdrew it."), "cost": {"type": ["string", "null"], "description": "What Caducus has charged for the post in all, deletion included, when a post was deleted."},
                "announcementState": text("The Announcement's state afterwards: withdrawn once every Delivery is, cancelled when none had gone.")}, ("id", "state", "withdrawnBy", "announcementState")),
        ("not_found", "constraint_conflict", "human_required", "service_unavailable"),
        (Example({"delivery": "announcement-1#x#handle#g1"},
                 {"id": "announcement-1#x#handle#g1", "state": "withdrawn", "withdrawnBy": "Ada Admin", "cost": "0.210", "announcementState": "withdrawn"}),),
        group="announcements", positional=("delivery",), agent_rung="prepare",
        notes="A person always may. An agent may withdraw only when every Story the Announcement is about was retired: otherwise it is told human_required, and nothing is changed. A Delivery that has not "
              "gone is stopped and nothing public changes. A post on X is deleted (never blocked by a pause or the budget), and the Delivery records who withdrew it and what the post cost. A "
              "channel that cannot take its message back (a sent email, a post made by hand) is refused as constraint_conflict and the Delivery stays sent: send a correction. Deleting a post "
              "needs the site's own X channel; the signed-in command line holds none and says service_unavailable for a post that went. A Delivery a correction replaced is not "
              "withdrawn: its post is deleted with the correction.",
    ),
)

OPERATIONS = OPERATIONS + REVIEW_OPERATIONS

# --- the Announcements list, the Story drawer's lines and "why not announced" (PPY-e4ae3a) ---------------------------------------------------------------
_MARKED = record({"words": text("The words a person reads."), "mark": text("The name of a Lucide icon drawn beside the words; the words always carry the meaning.")}, ("words", "mark"))
_ATTENTION = record({"kind": choice("overdue", "outcome_unknown", "check_failed"), "words": text(), "mark": text(), "since": text("When it began, as a UTC time.")}, ("kind", "words", "mark"))
DELIVERY_LINE = record({
    "id": text("The Delivery's id."), "announcementId": text(), "channel": text(), "accountId": text(), "generation": whole(), "state": text("The Delivery's state."),
    "words": text("The state in words, such as Sent or Blocked: check failed."), "mark": text("The Lucide icon of the state."),
    "approval": {"type": ["object", "null"], "description": "The review in words and a mark: words, mark and approval (none, soft or hard). Null for a Delivery that will not go."},
    "releaseAt": {"type": ["string", "null"]}, "lockAt": {"type": ["string", "null"]}, "dueAt": {"type": ["string", "null"], "description": "The earliest time it is still waiting for."},
    "waitingFor": {"type": ["string", "null"]}, "nextAttemptAt": {"type": ["string", "null"]}, "blockedReason": {"type": ["string", "null"]},
    "attempts": whole("How many attempts were opened.", minimum=0), "lastAttempt": {"type": ["object", "null"], "description": "The last attempt: number, at, outcome, code, words and mark."},
    "resultUrl": {"type": ["string", "null"]},
    "attention": many(_ATTENTION, "What needs a person's eye: Overdue (due, with no attempt), Outcome unknown (an attempt with no answer yet, until Caducus settles it), "
                                  "or a failed check."),
}, ("id", "announcementId", "channel", "accountId", "state", "words", "mark", "attempts", "attention"))
ANNOUNCEMENT_ENTRY = record({
    "id": text(), "kind": text(), "state": text(), "releaseAt": text(), "trigger": {"type": ["string", "null"]}, "createdBy": {"type": ["string", "null"]},
    "versionLookedAt": {"type": ["integer", "null"], "description": "The version of the Story the Announcement looked at."},
    "reviewFlag": {"type": ["object", "null"], "description": "The one open review flag for a blocked draft, once for each Announcement: id, words, mark, reason and ask."},
    "deliveries": many(DELIVERY_LINE, "One line for each live Delivery, in channel order."),
    "stories": many({"type": "object"}, "In the list: the Stories it is about, each with lineageId and title."),
}, ("id", "kind", "state", "releaseAt", "deliveries"))
_EX_LINE = {"id": "announcement-1#x#handle-1#g1", "announcementId": "announcement-1", "channel": "x", "accountId": "handle-1", "generation": 1, "state": "ready", "words": "Ready",
            "mark": "calendar-check", "approval": {"words": "Goes at its lock time unless a person stops it (publication policy)", "mark": "hourglass", "approval": "soft"},
            "releaseAt": "2026-11-17T09:00:00Z", "lockAt": "2026-11-17T09:00:00Z", "dueAt": "2026-11-17T09:00:00Z", "waitingFor": None, "nextAttemptAt": None, "blockedReason": None,
            "attempts": 0, "lastAttempt": None, "resultUrl": None, "attention": [{"kind": "overdue", "words": "Overdue", "mark": "clock-alert", "since": "2026-11-17T09:00:00Z"}]}
_EX_ENTRY = {"id": "announcement-1", "kind": "story_published", "state": "planned", "releaseAt": "2026-11-17T09:00:00Z", "trigger": "story published", "createdBy": "announce",
             "versionLookedAt": 3, "reviewFlag": None, "deliveries": [_EX_LINE]}

LIST_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "announcements_where", ("where",), "Where a Story was announced: each Announcement that announces it, with one line for each live Delivery.", "read",
        obj({"story": STORY_LINEAGE}, ("story",)), record({"story": text(), "announcements": many(ANNOUNCEMENT_ENTRY)}, ("story", "announcements")), (),
        (Example({"story": "slow-water"}, {"story": "slow-water", "announcements": [_EX_ENTRY]}),), positional=("story",), group="announcements",
        notes="Read through the announces relation from the Story's side, then each Announcement's Deliveries from its index; nothing lists a table. A Story that was never announced answers with no "
              "Announcements. Each line says its state, its review and what needs a person (Overdue, Outcome unknown) in words, with a mark. A blocked draft shows its one review flag once for each Announcement.",
    ),
    Operation(
        "announcements_recent", ("recent",), "The Announcements list: Announcements newest first, one line for each live Delivery, and every Delivery that is overdue.", "read",
        obj({"limit": whole("The size of a page; 25 when left out. A page never splits Announcements released at the same moment."),
             "before": text("The next value of the last page: shows the Announcements released before that time.")}),
        record({"announcements": many(ANNOUNCEMENT_ENTRY), "overdue": many(DELIVERY_LINE, "Every Delivery that is due and has no attempt, read from the sparse due index."),
                "next": {"type": ["string", "null"], "description": "Pass as before for the next page; null on the last page."}}, ("announcements", "overdue", "next")), (),
        (Example({}, {"announcements": [_EX_ENTRY], "overdue": [_EX_LINE], "next": None}),), group="announcements",
        notes="Newest release first from the planned-by-release-time index, one partition for each state; overdue from the due index. Each line says what it waits for, in words and a mark: "
              "Overdue for a due Delivery with no attempt, Outcome unknown for an attempt left open until Caducus settles it. Nothing is subscribed to.",
    ),
    Operation(
        "announcements_explain", ("explain",), "Why a Story was or was not announced, for each channel, naming the rule; or what a Delivery's draft read. Reads the rules; writes nothing.", "read",
        obj({"story": STORY_LINEAGE, "delivery": text("Ask instead about a Delivery: the guideline layers (scope, item, version, hash) and the examples its draft read.")}),
        record({"story": text(), "title": text(), "stars": whole(minimum=0),
                "channels": many(record({"channel": text(), "announced": flag(), "rule": text("The rule: announced, off, not_published, type_not_announced, section_not_announced, below_bar, "
                                                                                                 "below_floor, machine_five, story_not_reviewed, no_delivery or would_announce."),
                                         "words": text(), "delivery": text()}, ("channel", "announced", "rule", "words"))),
                "delivery": text("The Delivery asked about."), "recorded": flag(), "words": text(), "storyVersion": {"type": ["integer", "null"]}, "model": {"type": ["string", "null"]},
                "guidelineLayers": many({"type": "object"}, "Each guideline layer the draft read: scope, itemId, versionNumber, contentHash."),
                "examples": many(record({"delivery": text(), "state": text(), "scope": {"type": ["string", "null"]}}, ("delivery", "state")), "The examples the draft read, and whether each is still on.")}, ()),
        ("not_found", "invalid_input"),
        (Example({"story": "slow-water"}, {"story": "slow-water", "title": "Slow water", "stars": 2,
                                           "channels": [{"channel": "x", "announced": False, "rule": "below_bar", "words": "It has 2 stars, and the bar for announcements is 3 stars."}]}),
         Example({"delivery": "announcement-1#x#handle#g1"}, {"delivery": "announcement-1#x#handle#g1", "recorded": True, "storyVersion": 3, "model": "gpt-6-luna",
                                                                "guidelineLayers": [{"scope": "publication", "itemId": "item-1", "versionNumber": 4, "contentHash": "ab12"}],
                                                                "examples": [{"delivery": "announcement-0#x#handle#g1", "state": "active", "scope": "channel"}],
                                                                "words": "announcement-1#x#handle#g1 was drafted from version 3 of the Story under 1 guideline layer and 1 example."})),
        group="announcements",
        notes="The one question that is not a row: nothing is written for a Story that was not announced. The answer follows the order the announce path runs its rules.",
    ),
)

OPERATIONS = OPERATIONS + LIST_OPERATIONS

RATING_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "ratings_set", ("set",), "Give a Story a star rating, 1 to 5. Only a person rates; an agent suggests with ratings_suggest.", "write",
        obj({"story": STORY_LINEAGE, "stars": whole("The rating, 1 to 5.")}, ("story", "stars")),
        record({"lineageId": text(), "previous": whole("The rating before this one: 0 when the Story had none.", minimum=0), "stars": whole(), "ratedBy": text()},
               ("lineageId", "stars")),
        ("not_found", "not_authorized"),
        (Example({"story": "story-1", "stars": 4}, {"lineageId": "story-1", "previous": 0, "stars": 4, "ratedBy": "an editor"}),), positional=("story",), group="ratings",
        notes="A person's rating is the editor's value and replaces any earlier one. A machine never writes a rating: an agent's call is refused with "
              "not_authorized at every rung (PPY-e61642).",
        agent_rung="person",
    ),
    Operation(
        "ratings_suggest", ("suggest",), "Suggest stars for a Story nobody has rated: three or four, or five for a five-star candidate. It sits beside the rating and is never the rating.", "write",
        obj({"story": STORY_LINEAGE, "stars": whole("3 or 4, or 5 for a five-star candidate a person decides.")}, ("story", "stars")),
        record({"lineageId": text(), "stars": whole(), "candidate": flag(), "suggestedBy": text(), "run": {"type": ["string", "null"]}}, ("lineageId", "stars", "candidate")),
        ("not_found", "invalid_input", "constraint_conflict"),
        (Example({"story": "story-1", "stars": 4}, {"lineageId": "story-1", "stars": 4, "candidate": False, "suggestedBy": "agent:rate", "run": "run-1"}),),
        positional=("story",), group="ratings",
        notes="A Story somebody rated is refused with constraint_conflict: a person's rating always wins. The suggestion records who made it and the run whose "
              "record holds the reason. A person confirms it with ratings_confirm, rates other stars, or leaves it.",
        agent_rung="propose",
    ),
    Operation(
        "ratings_confirm", ("confirm",), "Make a Story's suggested stars your rating, or give other stars instead.", "write",
        obj({"story": STORY_LINEAGE, "stars": whole("Other stars, 1 to 5, instead of the suggested ones. Leave out to confirm the suggestion.")}, ("story",)),
        record({"lineageId": text(), "stars": whole(), "suggested": whole(), "changed": flag(), "ratedBy": text()}, ("lineageId", "stars", "suggested", "changed")),
        ("not_found", "constraint_conflict", "not_authorized"),
        (Example({"story": "story-1"}, {"lineageId": "story-1", "stars": 4, "suggested": 4, "changed": False, "ratedBy": "an editor"}),), positional=("story",), group="ratings",
        notes="Only a person decides a suggestion. A Story with no suggestion is not_found; one already rated is constraint_conflict (rate it with ratings_set).",
        agent_rung="person",
    ),
    Operation(
        "ratings_suggestions_review", ("suggestions-review",), "Raise the day's one review of suggested ratings, or add Stories to it while it is open.", "write",
        obj({"day": text("The day, YYYY-MM-DD, in the site's time zone."),
             "suggestions": many(record({"story": STORY_LINEAGE, "title": text(), "stars": whole(), "reason": text("The agent's one-line reason for these stars.")}, ("story", "stars")),
                                 "The Stories suggested, with their stars and the reason for each.")},
            ("day", "suggestions")),
        record({"request": text(), "reason": text(), "state": text(), "stories": many(text(), "Every Story the request links.")}, ("request", "reason", "state", "stories")),
        ("invalid_input",),
        (Example({"day": "2026-11-21", "suggestions": [{"story": "story-1", "title": "Slow water", "stars": 4, "reason": "Better sourced than the usual Story."}]},
                 {"request": "rr-ratings-2026-11-21", "reason": "1 rating suggested, 0 five-star candidates", "state": "open", "stories": ["story-1"]}),),
        group="ratings",
        notes="One soft review per day: a second call that day adds its Stories to the open request and recounts it; an answered request is left as it is. "
              "Each Story's link carries its title, suggested stars, five-star-candidate flag and reason, and later the person's answer to that row.",
        agent_rung="propose",
    ),
)

OPERATIONS = OPERATIONS + RATING_OPERATIONS

HANDOFF_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "handoffs_request", ("request",), "Ask another responsibility for one piece of work on a Story. It appears on the Story as an Assignment that says who asked and why, and wakes the responsible agent once.", "write",
        obj({"story": STORY_LINEAGE, "responsibility": text("The responsibility asked, as the agent catalogue names it, such as research."),
             "why": text("What is needed and why, in plain words. It is the Assignment's brief and what the responsible agent reads.")}, ("story", "responsibility", "why")),
        record({"assignmentId": text(), "responsibility": text(), "story": text(), "status": text(), "askedBy": text(), "created": flag("False when the same ask was already made: nothing new was written and nobody is woken again.")},
               ("assignmentId", "responsibility", "story", "status", "askedBy", "created")),
        ("not_found", "constraint_conflict"),
        (Example({"story": "story-1", "responsibility": "research", "why": "Claim 3 cites no source. Find one."},
                 {"assignmentId": "handoff-3f9a1c5e7b2d4a60", "responsibility": "research", "story": "story-1", "status": "open", "askedBy": "agent:fact_check", "created": True}),),
        positional=("story",), group="handoffs",
        notes="An Assignment is the request between responsibilities: never a Message, and never a chat. An agent asking again with the same words gets the Assignment it already made. The responsible agent's own rung "
              "decides what it may do about it. A person files the same request with the same command; their request is always new. The Assignment closes when the responsible agent's run ends: completed, or failed with one flag for a person.",
        agent_rung="propose",
    ),
)

OPERATIONS = OPERATIONS + HANDOFF_OPERATIONS

# The poke-in operations (PPY-e6f31e, slice H3; agent_poke_in.py). The newsroom's Automation page and `papyrus agents pause|resume|pauses|wake` run the same code.
PAUSE_AGENT = text("The agent's name in the agent policy (its responsibility, such as announce). Leave it out for every agent on the site.")
PAUSE_SHOWN = record({"paused": flag(), "reason": text(), "pausedAt": text(), "pausedBy": text()}, ("paused",))
POLICY_VERSIONS = record({"before": whole(minimum=0), "after": whole(minimum=0)}, ("before", "after"), "The agent policy's version before and after; the same when nothing changed.")
CAUGHT_UP = record({"agent": text(), "subject": text(), "wakeKey": text(), "repeats": text("The key of the wake the pause stopped.")}, ("agent", "subject", "wakeKey", "repeats"))

AGENT_OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "agents_pause", ("pause",), "Pause one agent, or every agent on the site, with a reason: its next run starts nothing and its run record says why.", "write",
        obj({"agent": PAUSE_AGENT, "reason": REASON}, ("reason",)),
        record({"scope": choice("agent", "site"), "agent": {"type": ["string", "null"]}, "paused": flag(), "reason": text(), "pausedAt": text(), "pausedBy": text(),
                "changed": flag(), "policyVersion": POLICY_VERSIONS}, ("scope", "paused", "changed", "policyVersion")),
        ("blocked", "human_required", "stale_version"),
        (Example({"agent": "announce", "reason": "Checking the X drafts"},
                 {"scope": "agent", "agent": "announce", "paused": True, "reason": "Checking the X drafts", "pausedAt": "2026-11-23T15:00:00Z", "pausedBy": "Ada Admin",
                  "changed": True, "policyVersion": {"before": 4, "after": 5}}),),
        group="agents",
        notes="An admin who is a person only: it is a new version of the agent policy, saved by the site's agent-policy function, which refuses a credential that is not a person's "
              "(the operator's AWS lane writes it directly). The runner reads the policy at the start of every run, so the pause stops the next run; a wake that arrives meanwhile "
              "has a run record that says nothing to do (paused) and keeps the wake, so resuming can send it again. Pausing what is already paused keeps when it began.",
        agent_rung=PERSON_ONLY, agent_refusal="blocked",
    ),
    Operation(
        "agents_resume", ("resume",), "Resume one agent, or the site, with a reason, and send once each change wake the pause stopped.", "write",
        obj({"agent": PAUSE_AGENT, "reason": REASON}, ("reason",)),
        record({"scope": choice("agent", "site"), "agent": {"type": ["string", "null"]}, "paused": flag(), "changed": flag(), "policyVersion": POLICY_VERSIONS,
                "caughtUp": many(CAUGHT_UP, "The wakes sent again: one for each subject whose latest wake the pause stopped."),
                "notes": many(text(), "What was not caught up and why, in words.")}, ("scope", "paused", "changed", "policyVersion", "caughtUp", "notes")),
        ("blocked", "human_required", "stale_version", "service_unavailable"),
        (Example({"agent": "announce", "reason": "Drafts checked"},
                 {"scope": "agent", "agent": "announce", "paused": False, "changed": True, "policyVersion": {"before": 5, "after": 6},
                  "caughtUp": [{"agent": "announce", "subject": "story-1", "wakeKey": "announce|story-1|story-1-v3|stage_entered:published+resumed-v6",
                                "repeats": "announce|story-1|story-1-v3|stage_entered:published"}], "notes": []}),),
        group="agents",
        notes="An admin who is a person only, as agents_pause. A timer's skipped ticks stay skipped. For each agent the pause is lifted from that listens for changes, the runs since "
              "the pause began are read through the run index by agent, and each subject whose latest wake was stopped gets that wake once more, under a key made from the "
              "stopped wake and this resume's policy version, so a repeat sends nothing new. An agent still paused itself, or under a paused site, is left for its own resume.",
        agent_rung=PERSON_ONLY, agent_refusal="blocked",
    ),
    Operation(
        "agents_pauses", ("pauses",), "Show what is paused on the site: the site and each agent the agent policy names, with who paused it, when and why.", "read",
        obj({}),
        record({"policyVersion": whole(minimum=0), "site": PAUSE_SHOWN, "agents": {"type": "object", "description": "By agent: paused, and while paused its reason, when and who."}},
               ("policyVersion", "site", "agents")),
        (),
        (Example({}, {"policyVersion": 5, "site": {"paused": False},
                      "agents": {"announce": {"paused": True, "reason": "Checking the X drafts", "pausedAt": "2026-11-23T15:00:00Z", "pausedBy": "Ada Admin"}}}),),
        group="agents",
        notes="Read by an admin: the command line reads the policy document itself, the newsroom through the agent-policy function.",
    ),
    Operation(
        "agents_wake", ("wake",), "Wake one agent now for one subject: its latest wake for that subject goes on the site's wake queue again, and runs once.", "write",
        obj({"agent": text("The agent's id, such as announce."), "subject": text("What it is woken for: a Story's lineage id, or the record its wakes name, such as a Delivery's id."),
             "reason": REASON}, ("agent", "subject", "reason")),
        record({"agent": text(), "subject": text(), "wakeKey": text(), "repeats": text("The key of the wake sent again."), "requestedBy": text(), "reason": text()},
               ("agent", "subject", "wakeKey", "repeats", "requestedBy", "reason")),
        ("not_found", "human_required", "constraint_conflict"),
        (Example({"agent": "announce", "subject": "story-1", "reason": "The X draft should be made today"},
                 {"agent": "announce", "subject": "story-1", "wakeKey": "announce|story-1|story-1-v3|rated:4+woken-r1", "repeats": "announce|story-1|story-1-v3|rated:4",
                  "requestedBy": "Ada Editor", "reason": "The X draft should be made today"}),),
        group="agents",
        notes="An editor or admin who is a person. The run re-reads the subject as it is now and checks the policy as every run does, so a paused agent still starts nothing. "
              "An agent never woken for the subject has no wake to send again (not_found). The run record's summary names who woke it and why.",
        agent_rung=PERSON_ONLY,
    ),
    Operation(
        "agents_wake_overdue", ("wake-overdue",),
        "Wake now one Overdue record (a Delivery, or a soft review's deadline) that a follow-up timer wakes: its timer's wake goes on the site's wake queue again, "
        "with the same key, and runs once.", "write",
        obj({"record": choice("Delivery", "ReviewRequest", description="The kind of record, as Today names it."), "id": text("The record's id, as Today lists it."),
             "reason": REASON}, ("record", "id", "reason")),
        record({"record": text(), "id": text(), "dueAt": text("The due time it missed."), "waitingFor": {"type": ["string", "null"]},
                "wakeKey": text("The key of the timer's wake; the same key the timer used."), "requestedBy": text(), "reason": text(),
                "shown": text("What happened, in words.")},
               ("record", "id", "dueAt", "wakeKey", "requestedBy", "reason", "shown")),
        ("not_found", "human_required", "constraint_conflict", "service_unavailable"),
        (Example({"record": "Delivery", "id": "announcement-daily#email#site#g1", "reason": "The daily email did not go out"},
                 {"record": "Delivery", "id": "announcement-daily#email#site#g1", "dueAt": "2026-11-16T11:00:00Z", "waitingFor": "release",
                  "wakeKey": "deliver|announcement-daily#email#site#g1|2026-11-16T11:00:00Z|due", "requestedBy": "Ada Editor",
                  "reason": "The daily email did not go out",
                  "shown": "Delivery announcement-daily#email#site#g1 was woken now by Ada Editor: the wake its timer sends for 2026-11-16T11:00:00Z went on the site's queue again, with the same key, so it runs once."}),),
        group="agents",
        notes="An editor or admin who is a person. A Delivery or a soft review's deadline is woken by the engine's follow-up timer, not by an adopted agent, so agents_wake cannot reach it. "
              "This is overdue.recover for one record (overdue.wake_now): the record is read by its id and must be Overdue (still waiting for a due time the queue's own limits "
              "are used up after), else constraint_conflict and nothing is sent. The wake is the timer's own request with the same key, so a repeat inside the queue's "
              "window is dropped and one after it is answered duplicate by the runner: the work is done once. Its trigger says who sent it again and why, and so does the run record's summary.",
        agent_rung=PERSON_ONLY,
    ),
)

OPERATIONS = OPERATIONS + AGENT_OPERATIONS

BY_NAME = {operation.name: operation for operation in OPERATIONS}
BY_CLI = {(operation.group, operation.cli): operation for operation in OPERATIONS}


def operation(name: str) -> Operation | None:
    return BY_NAME.get(name)
