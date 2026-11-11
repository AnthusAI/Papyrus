"""The style profile operations: get, resolve, diff, save and history (design sections 3.4 and 5).

Each handler takes the backend's client, so the same code runs in the signed-in command line (``signed_in_handlers``: the client is the person's own
session) and in the image-service function (PR 2b: the client acts with the caller's own identity). The permission rules live here:

* anyone who can write the profile may save a document, but adding, changing or removing a binding constraint needs an admin who is a person;
* an agent that tries gets ``human_required``, and nothing is saved.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable

from papyrus_content.editorial_context import _check_tenant, find_section, hosted_publication
from papyrus_content.story_reporting import story_versions

from papyrus_content.guidelines.document import GuidelineError
from papyrus_content.guidelines.store import DocumentFiles
from papyrus_content.publishing import utc_now_iso

from .handlers import Caller, Handler, ImageOperationError, Outcome
from .profile_store import (IMAGE_KIND, NO_PROFILE_GUARD, current_version, document_store, profile_versions, read_current_profile, read_section_document, is_inline_shape, reference,
                            to_document)
from .visual_style import (Problem, StyleError, as_object, constraint_changes, diff_documents, image_review_of, keys_permanent, merge_document,
                           resolve_visual_style, stamp_constraints, validate_profile)

DEFAULT_HISTORY_LIMIT = 20


def _publication(client) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def _refuse(problems: list[Problem]) -> None:
    first = problems[0]
    code = "constraint_conflict" if any(p.code == "constraint_conflict" for p in problems) and first.code == "constraint_conflict" else "invalid_input"
    raise ImageOperationError(code, f"{first.path}: {first.message}", details={"path": first.path, "problems": [{"path": p.path, "message": p.message} for p in problems]})


def _as_error(error: StyleError) -> ImageOperationError:
    return ImageOperationError(error.code, error.message, details=error.details)


def _row_by_version(versions: list[dict], number: int) -> dict | None:
    return next((row for row in versions if int(row.get("versionNumber") or 0) == number), None)


def _who(row: dict) -> str:
    return str(row.get("versionCreatedBy") or "")


def _kind_of(row: dict) -> str:
    saved = as_object(as_object(row.get("metadata")).get("savedBy"))
    return "agent" if saved.get("kind") == "agent" else "human"


def _stored(error: GuidelineError) -> ImageOperationError:
    return ImageOperationError("not_found" if error.code == "not_found" else "invalid_input", error.message, details=error.details)


def get_profile(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    store = document_store(client, files)
    versions = profile_versions(client, files=files)
    row = _row_by_version(versions, arguments["version"]) if arguments.get("version") else current_version(versions)
    if row is None:
        raise ImageOperationError("not_found", "This publication has no visual style profile" + (f" version {arguments['version']}." if arguments.get("version") else " yet."),
                                  details={"expectedCurrentVersionId": NO_PROFILE_GUARD})
    try:
        document = to_document(row, store)
    except GuidelineError as error:
        raise _stored(error) from error
    return Outcome({"profile": document, "itemId": row["id"], "versionNumber": int(row.get("versionNumber") or 1), "updatedAt": row.get("versionCreatedAt") or row.get("updatedAt") or "",
                    "updatedBy": _who(row), "contentHash": reference(row)["contentHash"], "imageReview": image_review_of(document),
                    "isCurrent": row.get("versionState") == "current", "changeReason": row.get("changeReason") or ""}, publication)


def _story_for(client, target: dict) -> dict | None:
    if target["kind"] != "story":
        return None
    versions = story_versions(client, target["lineageId"])
    if not versions:
        raise ImageOperationError("not_found", f"No Story {target['lineageId']} in this publication.")
    for row in versions:
        _check_tenant(client, row)
    current = [row for row in versions if row.get("versionState") == "current"]
    return (current or sorted(versions, key=lambda row: int(row.get("versionNumber") or 0)))[-1]


SECTION_STYLE_FIELD = "visualStyle"


def resolve_for_request(client, arguments: dict, *, operation: str = "resolve", allow_retired: bool = False,
                        section_fields: str | None = None, files: DocumentFiles | None = None) -> tuple[dict, list[dict]]:
    """The resolved style for a request of the shape image_profile_resolve takes, and the warnings the section lookup added.

    ``section_fields`` names fields to read from the section beyond the fixed list (``visualStyle``, which only a site whose data API has the field can
    answer): both lanes ask for it and, when a site's data API does not have it yet, a warning says so.

    A section's own image document (the ``image`` guideline at section scope) is the section layer when it exists; otherwise the section's ``visualStyle`` and
    ``visualGuidance`` fields are, so a site that has not moved its section styles resolves as before.
    """
    try:
        document, ref, _ = read_current_profile(client, files)
    except GuidelineError as error:
        raise _stored(error) from error
    story = _story_for(client, arguments["target"]) if arguments.get("target") else None
    warnings: list[dict] = []
    section = None
    wanted = arguments.get("sectionId") or (story or {}).get("section")
    if wanted:
        try:
            section = find_section(client, str(wanted))
        except ValueError as error:
            warnings.append({"code": "section_unknown", "message": str(error)})
        if section is not None:
            _check_tenant(client, section)
            if section_fields:
                try:
                    section = {**section, **(client.get_record_with_fields("NewsroomSection", section.get("storedId") or section["id"], section_fields) or {}), "id": section["id"]}
                except Exception:
                    warnings.append({"code": "section_style_unreadable", "message": "This site's data API cannot yet read a section's visualStyle field, so only the section's image document and visual guidance were applied."})
            try:
                layer = read_section_document(client, section, files)
            except GuidelineError as error:
                raise _stored(error) from error
            if layer is not None:
                section = {**section, **layer}
        elif arguments.get("sectionId"):
            raise ImageOperationError("not_found", f"No section {arguments['sectionId']} in this publication.")
        else:
            warnings.append({"code": "section_unknown", "message": f"The Story's section {wanted!r} matches no newsroom section, so no section style was applied."})
    story_style = None
    if story is not None:
        raw = as_object(as_object(story.get("metadata")).get("imageStyle"))
        if raw:
            story_style = {**raw, "source": {"itemId": story["id"], "versionNumber": int(story.get("versionNumber") or 1)}}
    try:
        resolved = resolve_visual_style(document, profile_ref=ref, use=arguments["use"], image_type=arguments.get("imageType"), operation=operation,
                                        section=section, story_style=story_style, allow_retired=allow_retired)
    except StyleError as error:
        raise _as_error(error) from error
    resolved["warnings"] = [*resolved["warnings"], *warnings]
    return resolved, resolved["warnings"]


def _read_current(client, files: DocumentFiles | None = None) -> tuple[dict | None, dict | None, dict | None]:
    try:
        return read_current_profile(client, files)
    except GuidelineError as error:
        raise _stored(error) from error


def resolve_profile(client, arguments: dict, caller: Caller, section_fields: str | None = None, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    resolved, warnings = resolve_for_request(client, arguments, section_fields=section_fields, files=files)
    return Outcome(resolved, publication, tuple(warnings))


@dataclass
class Prepared:
    """A document a save would store, checked: with the stored versions it was laid over and the binding rules it would change."""
    document: dict
    versions: list[dict]
    row: dict | None
    old: dict | None
    constraint_changes: list[dict]


def _prepare(client, arguments: dict, files: DocumentFiles | None = None) -> Prepared:
    versions = profile_versions(client, files=files)
    row = current_version(versions)
    try:
        old = to_document(row, document_store(client, files)) if row else None
    except GuidelineError as error:
        raise _stored(error) from error
    merged = merge_document(old, arguments["document"])
    problems = [*keys_permanent(old, merged), *validate_profile(merged)]
    if problems:
        _refuse(problems)
    return Prepared(merged, versions, row, old, constraint_changes((old or {}).get("constraints"), merged.get("constraints")))


def diff_profile(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    prepared = _prepare(client, arguments, files)
    changes = diff_documents(prepared.old, prepared.document)
    current = int(prepared.row.get("versionNumber") or 1) if prepared.row else 0
    return Outcome({"changes": changes, "constraintChanges": prepared.constraint_changes, "wouldCreateVersion": current + 1 if changes else current}, publication)


def _require_person_admin(caller: Caller, changes: list[dict]) -> None:
    ids = [change["id"] for change in changes]
    if caller.kind == "agent":
        raise ImageOperationError("human_required", "Adding, changing or removing a binding constraint needs a person who is an admin. Nothing was saved.", details={"constraints": ids})
    if not caller.is_admin:
        raise ImageOperationError("not_authorized", "Only an admin may add, change or remove a binding constraint. Nothing was saved.", details={"constraints": ids})


def _already_saved(versions: list[dict], caller: Caller) -> dict | None:
    """The version an earlier try of this same write (the same requestId, the same person) made, so a retry gets the first answer instead of a stale-version refusal."""
    if not caller.request_id:
        return None
    for row in versions:
        saved = as_object(as_object(row.get("metadata")).get("savedBy"))
        if saved.get("requestId") == caller.request_id and saved.get("sub") == caller.subject:
            return row
    return None


def save_profile(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    earlier = _already_saved(profile_versions(client, files=files), caller)
    if earlier is not None:
        return Outcome({"itemId": earlier["id"], "versionNumber": int(earlier.get("versionNumber") or 1), "contentHash": reference(earlier)["contentHash"], "repeated": True}, publication)
    prepared = _prepare(client, arguments, files)
    merged, row, old = prepared.document, prepared.row, prepared.old
    guard = arguments["expectedCurrentVersionId"]
    if (row["id"] if row else NO_PROFILE_GUARD) != guard:
        raise ImageOperationError("stale_version", "The profile has changed since you read it. Read it again and apply your change to the new version.",
                                  details={"currentVersionId": row["id"] if row else NO_PROFILE_GUARD})
    if prepared.constraint_changes:
        _require_person_admin(caller, prepared.constraint_changes)
    if caller.kind == "agent":
        from .generation_settings import spend_fields_of

        if spend_fields_of(merged) != spend_fields_of(old):
            raise ImageOperationError("human_required", "Only a person may change whether spending on image generation is approved, or its ceilings. Nothing was saved.",
                                      details={"fields": [name for name, value in spend_fields_of(merged).items() if value != spend_fields_of(old)[name]]})
        from .examples import provider_grants

        allowed = sorted(provider_grants(merged) - provider_grants(old))
        if allowed:
            raise ImageOperationError("human_required", "Only a person may allow a picture to be sent to an image provider. Nothing was saved.",
                                      details={"examples": [attachment for _, attachment in allowed]})
    if not caller.subject:
        raise ImageOperationError("not_authorized", "The caller is not identified, so the version cannot record who saved it.")
    now = utc_now_iso()
    if "constraints" in merged:
        merged["constraints"] = stamp_constraints((old or {}).get("constraints"), merged["constraints"], by=caller.subject, at=now, reason=arguments["reason"])
    inline = row is not None and is_inline_shape(row)
    if old is not None and not inline and not diff_documents(old, merged):
        return Outcome({"itemId": row["id"], "versionNumber": int(row.get("versionNumber") or 1), "contentHash": reference(row)["contentHash"], "unchanged": True}, publication)
    saved_by = {"sub": caller.subject, "kind": caller.kind, **({"delegatedBy": caller.delegated_by} if caller.delegated_by else {}),
                **({"requestId": caller.request_id} if caller.request_id else {})}
    try:
        saved = document_store(client, files).save(IMAGE_KIND, merged, expected_current_version_id=guard, actor=caller.subject, reason=arguments["reason"], now=now, saved_by=saved_by,
                                                             even_if_unchanged=inline)
    except GuidelineError as error:
        if error.code == "stale_version":
            raise ImageOperationError("stale_version", "The profile has changed since you read it. Read it again and apply your change to the new version.",
                                      details={"currentVersionId": error.details.get("expectedCurrentVersionId")}) from error
        raise _stored(error) from error
    ref = saved["reference"]
    return Outcome({"itemId": ref["itemId"], "versionNumber": ref["versionNumber"], "contentHash": ref["contentHash"]}, publication)


def profile_history(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    versions = profile_versions(client, files=files)
    limit = int(arguments.get("limit") or DEFAULT_HISTORY_LIMIT)
    try:
        start = int(arguments.get("nextToken") or 0)
    except ValueError:
        raise ImageOperationError("invalid_input", "nextToken is not one this operation gave.", details={"path": "nextToken"}) from None
    page = versions[start:start + limit]
    result: dict[str, Any] = {"versions": [{"versionNumber": int(row.get("versionNumber") or 1), "at": row.get("versionCreatedAt") or "", "by": _who(row), "byKind": _kind_of(row),
                                            "reason": row.get("changeReason") or "", "contentHash": reference(row)["contentHash"]} for row in page]}
    if start + limit < len(versions):
        result["nextToken"] = str(start + limit)
    return Outcome(result, publication)


# --- the signed-in lane ---------------------------------------------------------------------------------------------------------------------------------

from .examples import example_add, example_remove  # noqa: E402  (they build on save_profile and the helpers above)
from .profile_init import init_profile  # noqa: E402
from .prompt_preview import preview_prompt  # noqa: E402

PROFILE_HANDLERS: dict[str, Callable[..., Outcome]] = {
    "image_profile_get": get_profile, "image_profile_resolve": resolve_profile, "image_profile_diff": diff_profile,
    "image_profile_save": save_profile, "image_profile_history": profile_history,
    "image_prompt_preview": preview_prompt,
    "image_profile_init": init_profile, "image_profile_example_add": example_add, "image_profile_example_remove": example_remove,
}


def groups_from_token(authorization: str | None) -> tuple[str, ...]:
    """The Cognito groups an ID token names. The token is not verified here: this only tells the command line what to expect, and the backend decides."""
    try:
        payload = (authorization or "").split(" ")[-1].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return tuple(claims.get("cognito:groups") or ())
    except (IndexError, ValueError):
        return ()


def identify(client, caller: Caller) -> Caller:
    """Fill in who the signed-in session is when the caller does not say: the person's label, and whether the session is in the admin group."""
    from dataclasses import replace

    from papyrus_content.cli_user_auth import selected_headers, signed_in_label

    endpoint = getattr(client, "endpoint", None)
    if not endpoint:
        return caller
    subject = caller.subject or signed_in_label(endpoint) or ""
    headers = selected_headers(endpoint) or {}
    groups = groups_from_token(headers.get("Authorization") or headers.get("authorization"))
    return replace(caller, subject=subject, is_admin=caller.is_admin or "admin" in groups)


def signed_in_handlers(client_factory: Callable[[], Any] | None = None) -> dict[str, Handler]:
    """The profile handlers on the signed-in lane: each call opens the person's own authoring client, so the backend applies their own rights."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(name, function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            if name == "image_profile_resolve":
                return function(client, arguments, identify(client, caller), SECTION_STYLE_FIELD)
            if name == "image_prompt_preview":
                return function(client, arguments, identify(client, caller))
            return function(client, arguments, identify(client, caller))
        return handler

    return {name: wrap(name, function) for name, function in PROFILE_HANDLERS.items()}


def with_client(client, caller_filter: Callable[[Caller], Caller] | None = None, *, section_fields: str | None = None,
                files: DocumentFiles | None = None) -> dict[str, Handler]:
    """The same handlers bound to one client and the files its documents are kept in (the image-service function and the tests)."""
    def bind(name, function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            caller = caller_filter(caller) if caller_filter else caller
            if name == "image_profile_resolve":
                return function(client, arguments, caller, section_fields, files)
            return function(client, arguments, caller, files)
        return handler

    return {name: bind(name, function) for name, function in PROFILE_HANDLERS.items()}

