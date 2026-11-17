"""The one-time conversion of a site's writing guidelines from schema version 1 (one JSON document each) to schema version 2 (a set of guideline files): PPY-1d5c43.

This module is the **only** reader of the old shape, and it is deleted as soon as the last site has been converted (the cutover plan is in
``docs/guidelines-files-cutover.md``). Nothing else in the guideline system reads a JSON writing document: the store, the resolver, the door and the commands read files.

For each lineage of a site (the publication's and each section's, and for each language overlay) it reads the current version's document, writes it as its fixed-name field files
(``field_files.files_from_document``), reads those files back, and refuses the lineage unless the document it reads back is the document it started with. That equality is
the proof that the resolved result is unchanged: the resolver lays documents over each other, and the same documents give the same answer. A dry run (the default) does all of
this and stores nothing; ``apply`` stores each converted set as the lineage's next version, naming the version it replaces, so a change made in between is refused as stale.
Running it again converts nothing: a lineage whose current version is already a set of files is left alone.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from . import field_files
from .document import GuidelineError, digest, kind_spec, overlay_language, slug_for, validate_document
from .store import ROLE, GuidelineStore

KIND = "writing"
REASON = "Converted to guideline files (schema version 2); the guidelines are unchanged."


def _legacy_document(store: GuidelineStore, row: dict) -> dict:
    """The JSON document of a version saved in the old shape."""
    attachments = store.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", row["id"], limit=100)
    wanted = [a for a in attachments if a.get("role") == ROLE and str(a.get("status") or "active").lower() not in {"deleted", "aborted"}]
    if not wanted:
        raise GuidelineError("not_found", f"The guidelines {row.get('slug')} version {row.get('versionNumber')} have no stored document.", {"itemId": row["id"]})
    body = store.files.get(wanted[0])
    if body is None:
        raise GuidelineError("not_found", f"The document file of {row['id']} could not be read.", {"itemId": row["id"]})
    document = json.loads(body.decode("utf-8"))
    if row.get("contentHash") and digest(document) != row["contentHash"]:
        raise GuidelineError("document_hash_mismatch", f"The stored document of {row['id']} does not match its content hash.", {"itemId": row["id"]})
    return document


def _differences(before: dict, after: dict) -> list[str]:
    return sorted(key for key in {*before, *after} if before.get(key) != after.get(key))


def convert_lineage(store: GuidelineStore, section: str | None, language: str | None, *, apply: bool, actor: str, saved_by: dict | None = None) -> dict[str, Any]:
    """The outcome of one lineage: ``{section?, language?, state, ...}``. ``state`` is none (nothing saved), already_files, ready (dry run), converted, or refused (with ``reasons``)."""
    outcome: dict[str, Any] = {**({"section": section} if section else {}), **({"language": language} if language else {})}
    tag = overlay_language(KIND, language)
    current = store.current_row(KIND, section, language=tag)
    if current is None:
        return {**outcome, "state": "none"}
    outcome["version"] = int(current.get("versionNumber") or 1)
    try:
        store._set_of(current)
        return {**outcome, "state": "already_files"}
    except GuidelineError as error:
        if error.code != "legacy_version":
            return {**outcome, "state": "refused", "reasons": [error.message]}
    try:
        document = _legacy_document(store, current)
    except (GuidelineError, ValueError) as error:
        return {**outcome, "state": "refused", "reasons": [getattr(error, "message", str(error))]}
    document = {**document, "schemaVersion": kind_spec(KIND).schema_version}
    scope = "section" if section or tag else "publication"
    problems = validate_document(KIND, document, scope)
    if problems:
        return {**outcome, "state": "refused", "reasons": [f"{p.path or 'document'} {p.message}" for p in problems]}
    try:
        files = field_files.files_from_document(document, slug=slug_for(KIND, section, tag), section=section, language=tag)
        view = field_files.view_of(files, section=section, language=tag)
    except GuidelineError as error:
        return {**outcome, "state": "refused", "reasons": [error.message]}
    changed = _differences(document, view.document)
    if changed:
        return {**outcome, "state": "refused", "reasons": [f"{key} does not read back the same from its file" for key in changed]}
    outcome.update(files=len(files), resolvedUnchanged=True)
    if not apply:
        return {**outcome, "state": "ready"}
    store.save(KIND, document, section=section, language=tag, files=files, expected_current_version_id=current["id"], actor=actor, reason=REASON, saved_by=saved_by)
    return {**outcome, "state": "converted"}


def convert_site(client, files, *, sections: Iterable[str], languages: Iterable[str], apply: bool, actor: str, saved_by: dict | None = None) -> list[dict[str, Any]]:
    """Every lineage of the site, publication first, then each section, each with the shared guidelines and each language overlay: one index query to find each, nothing scanned."""
    store = GuidelineStore(client, files)
    tags = [None, *dict.fromkeys(languages)]
    lineages = [(section, tag) for section in [None, *dict.fromkeys(sections)] for tag in tags]
    results = [convert_lineage(store, section, tag, apply=apply, actor=actor, saved_by=saved_by) for section, tag in lineages]
    return [result for result in results if result["state"] != "none"]


__all__ = ["REASON", "convert_lineage", "convert_site"]
