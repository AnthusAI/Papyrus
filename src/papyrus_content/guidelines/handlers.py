"""The guideline operations: get, resolve, diff, save and history for any registered kind and scope (PPY-8d41d7).

Each handler takes the backend's client (and, in the image-service function, the S3 files), so one set of rules serves the signed-in command line
(``signed_in_handlers``) and the door (``with_client``). Nothing here names a kind: the registry in ``document.py`` says what a kind allows, and the store
keeps every kind the same way. The permission rules live here:

* anyone who may use the operations reads; only an admin saves (an editor gets ``not_authorized``);
* adding, changing or removing a binding constraint needs an admin who is a person: an agent gets ``human_required`` and nothing is saved;
* a write repeated with the same request id by the same person gives the first answer, not a stale-version refusal.

The ``image`` kind keeps its own document and resolver (``images/visual_style.py``): for the publication's document, get, diff, save and history are the
``image_profile_*`` handlers, which stay as the operations' aliases; resolve points at ``papyrus images profile resolve``, which also lays a section's image
document over the profile. A section's image document is stored, read, diffed and saved by the generic path like any other kind's.
"""
from __future__ import annotations

from typing import Any, Callable

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome
from papyrus_content.images.operations import ERROR_BY_CODE
from papyrus_content.images.profile_handlers import diff_profile, get_profile, identify, profile_history, save_profile
from papyrus_content.images.visual_style import constraint_changes, diff_documents

from .derived_policies import apply_derived_plan, changed_steps, describe_plan, plan_derived_policies
from .document import CONSTRAINTS, GuidelineError, kind_spec, overlay_language, validate_document
from .layering import resolve_guidelines, resolve_image_guidelines
from .store import DocumentFiles, GuidelineStore, reference, saved_by_of

IMAGE_KIND = "image"


def _publication(client) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def _refused(error: GuidelineError) -> ImageOperationError:
    code = error.code if error.code in ERROR_BY_CODE else "invalid_input"
    return ImageOperationError(code, error.message, details=error.details)


def _scope(arguments: dict) -> tuple[str, str | None]:
    kind, section = arguments["kind"], arguments.get("section")
    try:
        kind_spec(kind)
    except GuidelineError as error:
        raise _refused(error) from error
    return kind, section


def _language(kind: str, arguments: dict) -> str | None:
    """The language overlay an operation names (in Humanus's spelling), or None for the guidelines every language shares."""
    try:
        return overlay_language(kind, arguments.get("language"))
    except GuidelineError as error:
        raise _refused(error) from error


def _described(kind: str, section: str | None, language: str | None = None, **fields: Any) -> dict:
    return {"kind": kind, **({"section": section} if section else {}), **({"language": language} if language else {}), **fields}


def _image_alias(function: Callable, client, arguments: dict, caller: Caller, files: DocumentFiles | None) -> Outcome:
    """Run an ``image_profile_*`` handler for the publication's ``kind: image`` document. A section's image document has no special rules and uses the generic path."""
    inner = {key: value for key, value in arguments.items() if key not in ("kind", "section")}
    outcome = function(client, inner, caller, files)
    result = {**outcome.result, "kind": IMAGE_KIND}
    if "profile" in result:
        result["document"] = result["profile"]
    return Outcome(result, outcome.publication, outcome.warnings)


# --- reads ------------------------------------------------------------------------------------------------------------------------------------------

def get_guidelines(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    kind, section = _scope(arguments)
    if kind == IMAGE_KIND and not section and not arguments.get("language"):
        return _image_alias(get_profile, client, arguments, caller, files)
    language = _language(kind, arguments)
    store = GuidelineStore(client, files)
    try:
        found = store.read(kind, section, version=arguments.get("version"), language=language)
        current = store.current_row(kind, section, language=language)
    except GuidelineError as error:
        raise _refused(error) from error
    if found is None:
        asked = f" version {arguments['version']}" if arguments.get("version") else ""
        overlay = f" ({language} overlay)" if language else ""
        raise ImageOperationError("not_found", f"This publication has no {kind} guidelines{overlay}{asked}" + (f" for the section {section}." if section else "."),
                                  details={"expectedCurrentVersionId": "none" if current is None else current["id"]})
    row = found["row"]
    return Outcome(_described(
        kind, section, language, document=found["document"], itemId=row["id"], versionNumber=int(row.get("versionNumber") or 1), contentHash=row.get("contentHash") or "",
        updatedAt=row.get("versionCreatedAt") or row.get("updatedAt") or "", updatedBy=str(row.get("versionCreatedBy") or ""), changeReason=row.get("changeReason") or "",
        isCurrent=row.get("versionState") == "current", expectedCurrentVersionId=current["id"] if current else "none"), publication)


def resolve_guidelines_for(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    kind, section = _scope(arguments)
    if kind == IMAGE_KIND:
        try:
            answer = resolve_image_guidelines(GuidelineStore(client, files), section)
        except GuidelineError as error:
            raise _refused(error) from error
        return Outcome({key: value for key, value in answer.items() if not (key == "section" and value is None)}, publication, tuple(answer["warnings"]))
    try:
        language = arguments.get("language")
        if language:
            from papyrus_content.editorial_languages import canonical

            language = canonical(language)
        answer = resolve_guidelines(GuidelineStore(client, files), kind, section, language)
    except LookupError as error:
        raise ImageOperationError("invalid_input", str(error)) from error
    except GuidelineError as error:
        if error.code == "resolver_not_available" and kind == IMAGE_KIND:
            raise ImageOperationError("resolver_not_available", "Image guidelines are resolved for a Story and a use: run papyrus images profile resolve.",
                                      details={"use": "papyrus images profile resolve"}) from error
        raise _refused(error) from error
    result = {key: value for key, value in answer.items() if not (key == "section" and value is None)}
    return Outcome(result, publication, tuple(answer["warnings"]))


def _constraint_fields(kind: str) -> list[str]:
    return [name for name, field in kind_spec(kind).fields.items() if field.rule == CONSTRAINTS]


def _constraint_changes(kind: str, old: dict | None, new: dict) -> list[dict]:
    changes: list[dict] = []
    for name in _constraint_fields(kind):
        changes.extend(constraint_changes((old or {}).get(name), new.get(name)))
    return changes


def _checked(kind: str, document: Any, section: str | None) -> dict:
    problems = validate_document(kind, document, "section" if section else "publication")
    if problems:
        first = problems[0]
        raise ImageOperationError("invalid_input", f"{first.path or 'document'}: {first.message}",
                                  details={"path": first.path, "problems": [{"path": p.path, "message": p.message, "code": p.code} for p in problems]})
    return document


def _image_section_checked(store: GuidelineStore, document: dict, section: str | None, previous: dict | None) -> None:
    """A section's image document is also checked against the publication's: no shadowed type, every own type valid under its binding rules and locks."""
    if kind_of_check(section):
        from papyrus_content.images.visual_style import validate_section_types

        base = store.read(IMAGE_KIND)
        problems = validate_section_types(base["document"] if base else None, document, previous)
        if problems:
            first = problems[0]
            raise ImageOperationError("constraint_conflict" if first.code == "constraint_conflict" else "invalid_input", f"{first.path or 'document'}: {first.message}",
                                      details={"path": first.path, "problems": [{"path": p.path, "message": p.message, "code": p.code} for p in problems]})


def kind_of_check(section: str | None) -> bool:
    return bool(section)


def _policy_store(client, policies):
    if policies is not None:
        return policies
    if getattr(client, "policies", None) is not None:
        return client.policies
    if hasattr(client, "graphql"):
        from papyrus_content.editorial_checks import GraphQLEditorialStore

        return GraphQLEditorialStore(client.graphql, getattr(client, "tenant_id", None))
    return None


def diff_guidelines(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None, policies=None) -> Outcome:
    publication = _publication(client)
    kind, section = _scope(arguments)
    if kind == IMAGE_KIND and not section and not arguments.get("language"):
        return _image_alias(diff_profile, client, arguments, caller, files)
    language = _language(kind, arguments)
    document = _checked(kind, arguments["document"], section or language)
    store = GuidelineStore(client, files)
    try:
        current = store.read(kind, section, language=language)
    except GuidelineError as error:
        raise _refused(error) from error
    old = current["document"] if current else None
    if kind == IMAGE_KIND:
        try:
            _image_section_checked(store, document, section, old)
        except GuidelineError as error:
            raise _refused(error) from error
    changes = diff_documents(old, document)
    number = int(current["row"].get("versionNumber") or 1) if current else 0
    would_create = number + 1 if changes or current is None else number
    extra: dict = {}
    store_of_policies = _policy_store(client, policies) if kind == "writing" else None
    if store_of_policies is not None:
        try:
            extra["policyPlan"] = describe_plan(plan_derived_policies(store_of_policies, document, section, would_create, language))
        except ModuleNotFoundError:
            extra["policyPlanNotAvailable"] = "The Humanus policy reader is not installed where this diff ran."
    return Outcome(_described(kind, section, language, changes=changes, constraintChanges=_constraint_changes(kind, old, document), wouldCreateVersion=would_create, **extra),
                   publication)


def guidelines_history(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None) -> Outcome:
    publication = _publication(client)
    kind, section = _scope(arguments)
    if kind == IMAGE_KIND and not section and not arguments.get("language"):
        return _image_alias(profile_history, client, arguments, caller, files)
    language = _language(kind, arguments)
    try:
        rows = GuidelineStore(client, files).versions(kind, section, language=language)
    except GuidelineError as error:
        raise _refused(error) from error
    versions = [{"itemId": row["id"], "versionNumber": int(row.get("versionNumber") or 1), "isCurrent": row.get("versionState") == "current",
                 "at": row.get("versionCreatedAt") or "", "by": str(row.get("versionCreatedBy") or ""),
                 "byKind": "agent" if saved_by_of(row).get("kind") == "agent" else "human", "reason": row.get("changeReason") or "",
                 "contentHash": row.get("contentHash") or ""} for row in rows]
    return Outcome(_described(kind, section, language, versions=versions), publication)


# --- the write ----------------------------------------------------------------------------------------------------------------------------------------

def _require_person_admin(caller: Caller, changes: list[dict]) -> None:
    ids = [change["id"] for change in changes]
    if caller.kind == "agent":
        raise ImageOperationError("human_required", "Adding, changing or removing a binding constraint needs a person who is an admin. Nothing was saved.",
                                  details={"constraints": ids})


def _earlier_answer(rows: list[dict], caller: Caller) -> dict | None:
    """The version an earlier try of this same write (same requestId, same person) made."""
    if not caller.request_id:
        return None
    return next((row for row in rows if saved_by_of(row).get("requestId") == caller.request_id and saved_by_of(row).get("sub") == caller.subject), None)


def save_guidelines(client, arguments: dict, caller: Caller, files: DocumentFiles | None = None, policies=None) -> Outcome:
    publication = _publication(client)
    kind, section = _scope(arguments)
    if not caller.is_admin:
        raise ImageOperationError("not_authorized", "Only an admin may save guidelines. Nothing was saved.")
    if not caller.subject:
        raise ImageOperationError("not_authorized", "The caller is not identified, so the version cannot record who saved it.")
    if kind == IMAGE_KIND and not section and not arguments.get("language"):
        return _image_alias(save_profile, client, arguments, caller, files)
    language = _language(kind, arguments)
    store = GuidelineStore(client, files)
    try:
        versions = store.versions(kind, section, language=language)
        earlier = _earlier_answer(versions, caller)
        if earlier is not None:
            ref = reference(earlier)
            return Outcome(_described(kind, section, language, itemId=ref["itemId"], versionNumber=ref["versionNumber"], contentHash=ref["contentHash"] or "", repeated=True),
                           publication)
        document = _checked(kind, arguments["document"], section or language)
        current = next((row for row in versions if row.get("versionState") == "current"), None)
        old = store.read(kind, section, language=language)["document"] if current is not None else None
        if kind == IMAGE_KIND:
            _image_section_checked(store, document, section, old)
        changes = _constraint_changes(kind, old, document)
        if changes:
            _require_person_admin(caller, changes)
        saved_by = {"sub": caller.subject, "kind": caller.kind, **({"delegatedBy": caller.delegated_by} if caller.delegated_by else {}),
                    **({"requestId": caller.request_id} if caller.request_id else {})}
        saved = store.save(kind, document, section=section, expected_current_version_id=arguments["expectedCurrentVersionId"], actor=caller.subject,
                           reason=arguments["reason"], saved_by=saved_by, language=language)
    except GuidelineError as error:
        raise _refused(error) from error
    ref = saved["reference"]
    extra: dict = {}
    store_of_policies = _policy_store(client, policies) if kind == "writing" else None
    if store_of_policies is not None:
        try:
            steps = plan_derived_policies(store_of_policies, document, section, ref["versionNumber"], language)
        except ModuleNotFoundError:
            extra["policiesNotSynced"] = "The Humanus policy reader is not installed where this save ran; save again from the signed-in command line to sync the checks."
        else:
            apply_derived_plan(store_of_policies, steps)
            extra["policies"] = describe_plan(changed_steps(steps))
    return Outcome(_described(kind, section, language, itemId=ref["itemId"], versionNumber=ref["versionNumber"], contentHash=ref["contentHash"] or "",
                              **({} if saved["changed"] else {"unchanged": True}), **extra), publication)


# --- the lanes ---------------------------------------------------------------------------------------------------------------------------------------

GUIDELINE_HANDLERS: dict[str, Callable[..., Outcome]] = {
    "guidelines_get": get_guidelines, "guidelines_resolve": resolve_guidelines_for, "guidelines_diff": diff_guidelines,
    "guidelines_save": save_guidelines, "guidelines_history": guidelines_history,
}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None) -> dict[str, Handler]:
    """The handlers on the signed-in lane: each call opens the person's own authoring client, so the backend applies their own rights."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return function(client, arguments, identify(client, caller))
        return handler

    return {name: wrap(function) for name, function in GUIDELINE_HANDLERS.items()}


def with_client(client, files: DocumentFiles | None = None, caller_filter: Callable[[Caller], Caller] | None = None, policies=None) -> dict[str, Handler]:
    """The same handlers bound to one client and its document files (the image-service function and the tests)."""
    def bind(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            wanted = (files,) + ((policies,) if function in (save_guidelines, diff_guidelines) else ())
            return function(client, arguments, caller_filter(caller) if caller_filter else caller, *wanted)
        return handler

    return {name: bind(function) for name, function in GUIDELINE_HANDLERS.items()}
