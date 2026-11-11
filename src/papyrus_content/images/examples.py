"""Example and avoid-this pictures on the style profile: ``image_profile_example_add`` and ``image_profile_example_remove`` (design section 5.8).

A picture is uploaded first, through the existing attachment upload (the newsroom or the command line does that), and arrives as a ``ModelAttachment``
row whose id is the one thing these operations take. Adding or removing an example is a new profile version that lists the picture under one image type
(or ``identity`` for the brand). The file itself is never copied or moved: it is immutable and private, each profile version lists the files it was
saved with, and so an older version, and every picture made from it, still points at exactly the examples it had.

* Examples belong to one image type. The same file may be listed by two types (one attachment row, two entries). A child type does not inherit its
  parent's examples: ``provider_examples`` answers for the one type it is asked about.
* Only a person may let a picture go to an image provider (``sendToProvider``): the service cannot tell whether a picture shows identifiable people or
  logos, so the default is no, and an agent can never turn it on. ``save_profile`` enforces the same for a whole document.
"""
from __future__ import annotations

from typing import Any

from papyrus_content.publishing import utc_now_iso

from .handlers import Caller, ImageOperationError, Outcome
from .profile_handlers import _publication, _read_current, save_profile
from .profile_store import NO_PROFILE_GUARD
from .visual_style import as_object

IDENTITY = "identity"
ROLE_BY_KIND = {"exemplar": "visual_example", "negative": "visual_negative"}
MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_EXAMPLE_BYTES = 10 * 1024 * 1024   # the editor's own MAX_IMAGE_BYTES; the upload function enforces the same cap for these roles


def example_lists(document: dict | None) -> dict[str, list[dict]]:
    """Every list of examples in a document, by scope: ``identity`` and each image type's key."""
    document = document or {}
    lists = {IDENTITY: list(as_object(document.get("identity")).get("examples") or [])}
    for key, definition in as_object(document.get("imageTypes")).items():
        lists[key] = list(as_object(definition).get("examples") or [])
    return lists


def provider_grants(document: dict | None) -> set[tuple[str, str]]:
    """(scope, attachment id) of every example a person has allowed to go to an image provider."""
    return {(scope, str(example.get("attachmentId"))) for scope, examples in example_lists(document).items() for example in examples
            if isinstance(example, dict) and example.get("sendToProvider") is True}


def provider_examples(document: dict | None, image_type: str) -> list[dict]:
    """The good examples of this one image type that may be sent to a provider as style references: its own, never its parent's, only those a person allowed."""
    return [example for example in example_lists(document).get(image_type, []) if example.get("kind") == "exemplar" and example.get("sendToProvider") is True]


def _type_choices(document: dict) -> list[dict]:
    return [{"key": key, "label": definition.get("label") or key, "description": definition.get("description") or "", "sources": definition.get("sources") or []}
            for key, definition in as_object(document.get("imageTypes")).items() if isinstance(definition, dict) and not definition.get("retired")]


def _partial(scope: str, examples: list[dict]) -> dict:
    """A document that changes only one list of examples (lists replace, objects merge)."""
    return {"identity": {"examples": examples}} if scope == IDENTITY else {"imageTypes": {scope: {"examples": examples}}}


def _read_profile(client) -> tuple[dict, dict]:
    document, _, row = _read_current(client)
    if document is None or row is None:
        raise ImageOperationError("not_found", "This publication has no visual style profile yet, so there is no image type to add a picture to. Save a profile first.",
                                  details={"expectedCurrentVersionId": NO_PROFILE_GUARD})
    return document, row


def _check_guard(row: dict, arguments: dict) -> None:
    if row["id"] != arguments["expectedCurrentVersionId"]:
        raise ImageOperationError("stale_version", "The profile has changed since you read it. Read it again and apply your change to the new version.",
                                  details={"currentVersionId": row["id"]})


def _check_attachment(client, arguments: dict) -> dict:
    attachment = client.get_record("ModelAttachment", arguments["attachmentId"])
    if attachment is None:
        raise ImageOperationError("not_found", f"No uploaded picture {arguments['attachmentId']}. Upload the picture first, then add it.", details={"path": "attachmentId"})
    role = ROLE_BY_KIND[arguments["kind"]]
    if attachment.get("role") != role:
        raise ImageOperationError("invalid_input", f"That upload is not an {'example' if arguments['kind'] == 'exemplar' else 'avoid-this picture'}: it was uploaded for {attachment.get('role')}.",
                                  details={"path": "attachmentId"})
    if attachment.get("mediaType") not in MEDIA_TYPES:
        raise ImageOperationError("invalid_input", "Example pictures must be PNG, JPEG or WebP.", details={"path": "attachmentId"})
    if int(attachment.get("byteSize") or 0) > MAX_EXAMPLE_BYTES:
        raise ImageOperationError("invalid_input", "Example pictures must be 10 MB or smaller.", details={"path": "attachmentId"})
    if attachment.get("status") not in (None, "active") or not attachment.get("sha256"):
        raise ImageOperationError("invalid_input", "That upload is not finished, so it cannot be used as an example yet.", details={"path": "attachmentId"})
    return attachment


def example_add(client, arguments: dict, caller: Caller) -> Outcome:
    publication = _publication(client)
    document, row = _read_profile(client)
    _check_guard(row, arguments)
    scope = arguments["imageType"]
    if scope != IDENTITY:
        definition = as_object(as_object(document.get("imageTypes")).get(scope))
        if not definition or definition.get("retired"):
            raise ImageOperationError("image_type_unknown", f"There is no image type {scope!r} in this publication's profile, or it has been retired.",
                                      details={"choices": _type_choices(document)})
    send = bool(arguments.get("sendToProvider", False))
    if send and caller.kind == "agent":
        raise ImageOperationError("human_required", "Only a person may allow a picture to be sent to an image provider, because the service cannot tell whether it shows "
                                                    "identifiable people or logos. Nothing was saved.", details={"path": "sendToProvider"})
    attachment = _check_attachment(client, arguments)
    existing = example_lists(document)[scope]
    if any(example.get("attachmentId") == arguments["attachmentId"] for example in existing):
        raise ImageOperationError("invalid_input", f"That picture is already an example under {scope}.", details={"path": "attachmentId"})
    entry = {"attachmentId": arguments["attachmentId"], "sha256": attachment["sha256"], "kind": arguments["kind"], "note": arguments["note"], "sendToProvider": send,
             "mediaType": attachment["mediaType"], "byteSize": int(attachment.get("byteSize") or 0), "filename": attachment.get("filename") or "",
             "addedBy": caller.subject, "addedByKind": caller.kind, "addedAt": utc_now_iso()}
    saved = save_profile(client, {"document": _partial(scope, [*existing, entry]), "reason": arguments["reason"], "expectedCurrentVersionId": arguments["expectedCurrentVersionId"]}, caller)
    return Outcome({"attachmentId": arguments["attachmentId"], "sha256": "sha256:" + str(attachment["sha256"]), "versionNumber": saved.result["versionNumber"],
                    "imageType": scope}, publication)


def example_remove(client, arguments: dict, caller: Caller) -> Outcome:
    publication = _publication(client)
    document, row = _read_profile(client)
    _check_guard(row, arguments)
    wanted = arguments.get("imageType")
    lists = example_lists(document)
    if wanted is not None and wanted not in lists:
        raise ImageOperationError("image_type_unknown", f"There is no image type {wanted!r} in this publication's profile.", details={"choices": _type_choices(document)})
    scopes = [wanted] if wanted else list(lists)
    affected = {scope: [e for e in lists[scope] if e.get("attachmentId") != arguments["attachmentId"]] for scope in scopes
                if any(e.get("attachmentId") == arguments["attachmentId"] for e in lists[scope])}
    if not affected:
        raise ImageOperationError("not_found", f"{arguments['attachmentId']} is not listed as an example" + (f" under {wanted}." if wanted else "."))
    partial: dict = {}
    for scope, kept in affected.items():
        if scope == IDENTITY:
            partial["identity"] = {"examples": kept}
        else:
            partial.setdefault("imageTypes", {})[scope] = {"examples": kept}
    saved = save_profile(client, {"document": partial, "reason": arguments["reason"], "expectedCurrentVersionId": arguments["expectedCurrentVersionId"]}, caller)
    return Outcome({"versionNumber": saved.result["versionNumber"], "removedFrom": list(affected)}, publication)
