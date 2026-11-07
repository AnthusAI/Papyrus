"""The one table of image operations (docs/images.md; design: project/wiki/image-toolchain.md section 3; PPY-1232dc).

Every image action is one ``Operation`` here: its MCP tool name, CLI command, input and result schemas, the errors it may return, who may call it and
a plain sentence about it. The CLI group ``papyrus images``, the MCP tool schema, the newsroom's TypeScript types, the skill's reference block and
docs/images.md are all generated from this table by ``scripts/generate-image-operations.py``; a test fails when any of them differs.

To add or change an operation: edit ``OPERATIONS`` below, then run ``python scripts/generate-image-operations.py``.
This module describes operations only. What they do is in ``handlers.py`` (every handler answers ``not_implemented`` until its build step).
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
PROFILE_DOCUMENT = {"type": "object", "description": "The visual style document: a full or partial profile (design section 5.2)."}

COST_ESTIMATE = record({"priced": flag("False means the model has no price on file yet. Unpriced is never free."), "usd": {"type": "number"},
                        "perCandidate": {"type": "number"}, "basis": text()}, ("priced",), "What it would cost; spends nothing.")
SELECTION = record({"by": text(), "byKind": choice("human", "agent"), "delegatedBy": text(), "at": text(), "reason": text()}, ("by", "byKind", "at", "reason"))
CANDIDATE_SUMMARY = record({
    "id": text(), "position": whole(minimum=0), "status": choice(*STATUSES), "treatment": text(), "lane": choice("standard", "batch"),
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
    "target": TARGET, "use": USE, "brief": text("What the picture should show. The publication's style rules are added by the service, never written here."),
    "count": whole("How many to make (default 1). More than 1 is for a person choosing; an agent asking for more gets set_needs_person."),
    "spread": choice("variations", "treatments", description="Four takes of one treatment, or one take of each treatment the use allows."),
    "treatments": many(text(), "Treatments to use, from the profile."),
    "model": text("A configured, approved model. Recorded as requested and never swapped."),
    "acceptFallback": text("Id of a fallback offered in a capability_unsupported error, to use instead."),
    "references": many(text(), "Profile example ids to send as style references. Nothing else is accepted."),
    "speed": choice("auto", "standard", "batch", description="Which lane: auto picks by who is asking (a person standard, an agent batch at half price)."),
}, ("target", "use", "brief"))
ROUND_RESULT = record({
    "roundId": text(), "candidates": many(CANDIDATE_SUMMARY), "estimate": COST_ESTIMATE,
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
    notes: str = ""                        # anything a reader needs that the schemas cannot say

    @property
    def mcp_name(self) -> str:
        return self.name

    @property
    def command(self) -> str:
        return " ".join(("papyrus", "images", *self.cli))


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
    ErrorCode("checks_failed", "A check failed, so the picture cannot be applied.", details="checks lists which"),
    ErrorCode("generation_not_configured", "No approved image model is set up for this site, so nothing was made.", details="how to configure it"),
    ErrorCode("capability_unsupported", "The configured model cannot do what was asked.", details="alternatives lists fallbacks the caller may opt into"),
    ErrorCode("provider_failed", "The image provider refused or failed.", retryable=True, details="providerMessage, retryable"),
    ErrorCode("provider_busy", "The image provider is busy. Try again shortly.", retryable=True, details="retryAfterSeconds"),
    ErrorCode("batch_expired", "The picture was not ready within the batch window (24 hours). Nothing was charged.", retryable=True),
    ErrorCode("stale_version", "The Story has a newer version than the one you named. Read it again."),
    ErrorCode("candidate_not_ready", "The picture is still being made."),
    ErrorCode("candidate_closed", "The picture was already discarded, expired or applied."),
    ErrorCode("service_unavailable", "A permission or storage check could not be made. Nothing was changed.", retryable=True),
)
ERROR_BY_CODE = {error.code: error for error in ERRORS}
# Any operation may return these, so the per-operation lists leave them out.
COMMON_ERRORS = ("invalid_input", "not_authorized", "service_unavailable", "not_implemented")

# Example ids below are made up. There are no real people, sites or addresses in this file.
_STORY = {"kind": "story", "lineageId": "story-containment-note"}
_GUARD = "item-story-containment-note-v7"
_CANDIDATE = {"id": "candidate-1", "position": 0, "status": "ready", "treatment": "editorial-illustration", "lane": "standard", "reviewStatus": "unreviewed"}
_ESTIMATE = {"priced": False}
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
             "treatment": text("A treatment from the profile.")}, ("use",)),
        record({"resolutionHash": text(), "profile": {"type": ["object", "null"], "description": "Which profile version; null when the publication has none."},
                "layers": many(record({"layer": text()}, ("layer",))), "effective": {"type": "object"}, "fieldSources": {"type": "object"},
                "constraints": many({"type": "object"}), "warnings": many(record({"code": text(), "message": text()}, ("code", "message")))},
               ("resolutionHash", "profile", "layers", "effective", "fieldSources", "constraints", "warnings"),
               "The effective guidance. A publication with no profile gets the profile_missing warning, not an error."),
        ("constraint_conflict", "not_found"),
        (Example({"target": _STORY, "use": "cover"}, {
            "resolutionHash": "sha256:91bc", "profile": _PROFILE_REF, "layers": [{"layer": "publication"}, {"layer": "use"}],
            "effective": {"aspectRatio": "16:9"}, "fieldSources": {"aspectRatio": "use:cover"}, "constraints": [], "warnings": []}),),
        flags=(("sectionId", "section"),),
    ),
    Operation(
        "image_profile_diff", ("profile", "diff"), "Show what saving a style document would change, without saving it.", "read",
        obj({"document": PROFILE_DOCUMENT}, ("document",)),
        record({"changes": many(record({"path": text(), "from": anything(), "to": anything()}, ("path",))),
                "constraintChanges": many({"type": "object"}), "wouldCreateVersion": whole()}, ("changes", "constraintChanges", "wouldCreateVersion")),
        (), (Example({"document": {"identity": {"mood": ["calm"]}}}, {"changes": [{"path": "identity.mood", "from": ["calm", "precise"], "to": ["calm"]}],
                                                                   "constraintChanges": [], "wouldCreateVersion": 4}),),
        file_field="document",
    ),
    Operation(
        "image_profile_save", ("profile", "save"), "Save a style document as a new profile version.", "write",
        obj({"document": PROFILE_DOCUMENT, "reason": REASON, "expectedCurrentVersionId": text("The profile's current version id when you read it.")},
            ("document", "reason", "expectedCurrentVersionId")),
        record({"itemId": text(), "versionNumber": whole(), "contentHash": text()}, ("itemId", "versionNumber", "contentHash")),
        ("human_required", "stale_version"),
        (Example({"document": {"identity": {"mood": ["calm"]}}, "reason": "Dropped one mood word.", "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v3"},
                 {"itemId": "item-editorial-doctrine-visual-style-v4", "versionNumber": 4, "contentHash": "sha256:7d21"}),),
        file_field="document",
        notes="Adding, changing or removing a binding constraint needs an admin who is a person; an agent gets human_required.",
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
        "image_profile_example_add", ("profile", "example", "add"), "Add an example or an avoid-this picture to the profile, as a new version.", "write",
        obj({"uploadId": text("The id of a picture already uploaded through the newsroom's upload step."), "kind": choice("exemplar", "negative"),
             "note": text("Why this picture is a good example, or what to avoid."), "treatment": text(),
             "sendToProvider": flag("Send it to the image model as a style reference. Default false."), "reason": REASON,
             "expectedCurrentVersionId": text("The profile's current version id when you read it.")},
            ("uploadId", "kind", "note", "reason", "expectedCurrentVersionId")),
        record({"attachmentId": text(), "sha256": text(), "versionNumber": whole()}, ("attachmentId", "sha256", "versionNumber")),
        ("human_required", "not_found", "stale_version"),
        (Example({"uploadId": "upload-1", "kind": "exemplar", "note": "The calm we want.", "reason": "Cover from the containment Story.",
                  "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v3"},
                 {"attachmentId": "model-attachment-1", "sha256": "sha256:aa10", "versionNumber": 4}),),
        notes="Only a person may set sendToProvider for a picture that shows identifiable people or logos.",
    ),
    Operation(
        "image_profile_example_remove", ("profile", "example", "remove"), "Remove an example picture from the profile, as a new version.", "write",
        obj({"attachmentId": text(), "reason": REASON, "expectedCurrentVersionId": text("The profile's current version id when you read it.")},
            ("attachmentId", "reason", "expectedCurrentVersionId")),
        record({"versionNumber": whole()}, ("versionNumber",)),
        ("not_found", "stale_version"),
        (Example({"attachmentId": "model-attachment-1", "reason": "Too photographic.", "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v4"},
                 {"versionNumber": 5}),),
        positional=("attachmentId",),
        notes="The file stays for older profile versions.",
    ),
    # --- planning
    Operation(
        "image_capabilities", ("capabilities",), "Say which image models this site can use and whether spending is approved.", "read",
        obj({}),
        record({"configured": flag(), "models": many({"type": "object"}), "approvedForSpend": flag()}, ("configured", "models", "approvedForSpend")),
        (), (Example({}, {"configured": False, "models": [], "approvedForSpend": False}),),
    ),
    Operation(
        "image_brief_draft", ("brief",), "Work out a starting brief and stock search from a Story's title and deck.", "read",
        obj({"target": TARGET, "use": USE}, ("target", "use")),
        record({"brief": text(), "searchTarget": text(), "derivedFrom": many(text()), "workedOut": flag()}, ("brief", "searchTarget", "derivedFrom", "workedOut")),
        ("not_found",),
        (Example({"target": _STORY, "use": "cover"}, {"brief": "A locked filing cabinet with one drawer ajar", "searchTarget": "filing cabinet",
                                                       "derivedFrom": ["title", "deck"], "workedOut": True}),),
    ),
    Operation(
        "image_prompt_preview", ("prompt",), "Show exactly what would be asked of the image model, and what it would cost, without making anything.", "read",
        GENERATE_INPUT,
        record({"plans": many({"type": "object"}), "estimate": COST_ESTIMATE, "capabilityCheck": {"type": "object"}}, ("plans", "estimate", "capabilityCheck")),
        ("capability_unsupported", "constraint_conflict", "generation_not_configured", "not_found", "set_needs_person"),
        (Example({"target": _STORY, "use": "cover", "brief": "A locked filing cabinet with one drawer ajar"},
                 {"plans": [{"planVersion": "image-prompt/v1", "segments": [], "avoid": []}], "estimate": _ESTIMATE, "capabilityCheck": {"ok": True}}),),
    ),
    # --- finding and making
    Operation(
        "image_search", ("search",), "Find stock pictures for a Story, four at a time.", "read",
        obj({"target": TARGET, "query": text("Search words; worked out from the Story when left out."), "source": text("A stock source, for example wikimedia-commons."),
             "cursor": text("The nextCursor of the previous page."), "exclude": many(text(), "Candidate ids already shown, which never come back.")}, ("target",)),
        record({"candidates": many(STOCK_CANDIDATE), "nextCursor": {"type": ["string", "null"]}, "searched": text(), "searchedFromStory": flag()},
               ("candidates", "nextCursor", "searched", "searchedFromStory")),
        ("not_found",),
        (Example({"target": _STORY}, {"candidates": [], "nextCursor": None, "searched": "filing cabinet", "searchedFromStory": True}),),
        notes="Nothing is stored until a picture is selected or applied.",
    ),
    Operation(
        "image_generate", ("generate",), "Make pictures from a brief in the publication's style. The pictures arrive later.", "spend",
        GENERATE_INPUT, ROUND_RESULT,
        ("capability_unsupported", "constraint_conflict", "generation_not_configured", "not_found", "provider_busy", "set_needs_person"),
        (Example({"target": _STORY, "use": "cover", "brief": "A locked filing cabinet with one drawer ajar"},
                 {"roundId": "round-1", "candidates": [{"id": "candidate-1", "position": 0, "status": "queued", "lane": "batch"}], "estimate": _ESTIMATE}),),
        flags=(("treatments", "treatment"),),
        notes="Spends only when the site's image generation is configured and approved.",
    ),
    Operation(
        "image_round_get", ("round",), "Read a round of pictures and say whether they are all done.", "read",
        obj({"roundId": text()}, ("roundId",)),
        record({"roundId": text(), "target": TARGET, "use": USE, "brief": {"type": "string"}, "candidates": many(CANDIDATE_SUMMARY), "done": flag()},
               ("roundId", "target", "use", "candidates", "done")),
        ("not_found",),
        (Example({"roundId": "round-1"}, {"roundId": "round-1", "target": _STORY, "use": "cover", "brief": "A locked filing cabinet with one drawer ajar",
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
        record({"rounds": many(record({"roundId": text(), "use": USE, "brief": {"type": "string"}, "createdAt": text(), "candidates": many(CANDIDATE_SUMMARY)},
                                      ("roundId", "candidates"))), **PAGE}, ("rounds",)),
        ("not_found",),
        (Example({"target": _STORY}, {"rounds": [{"roundId": "round-1", "use": "cover", "brief": "A locked filing cabinet", "createdAt": "2026-11-07T18:00:00Z",
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
             "alt": text("Alt text; the picture's own draft when left out."), "caption": text(), "expectedCurrentVersionId": VERSION_GUARD,
             "save": flag("Make the new Story version now (default true). The newsroom editor passes false and saves itself.")},
            ("target", "use", "expectedCurrentVersionId"), **one_of("candidateId", "candidateRef")),
        record({"patch": record({"bodyDirective": text(), "frontMatter": {"type": "object"}}, ("bodyDirective", "frontMatter")), "mediaAsset": {"type": "object"},
                "reviewStatus": choice("unreviewed", "human-verified"), "reviewRequestId": text(),
                "savedVersion": record({"versionId": text(), "versionNumber": whole()})}, ("patch", "mediaAsset", "reviewStatus")),
        ("candidate_closed", "candidate_not_ready", "checks_failed", "not_found", "stale_version"),
        (Example({"candidateId": "candidate-1", "target": _STORY, "use": "cover", "expectedCurrentVersionId": _GUARD},
                 {"patch": {"bodyDirective": "::image{src=\"media/assets/containment/cover.png\"}", "frontMatter": {"image": "media/assets/containment/cover.png"}},
                  "mediaAsset": {"id": "media-asset-1"}, "reviewStatus": "unreviewed", "reviewRequestId": "review-1",
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

BY_NAME = {operation.name: operation for operation in OPERATIONS}
BY_CLI = {operation.cli: operation for operation in OPERATIONS}


def operation(name: str) -> Operation | None:
    return BY_NAME.get(name)
