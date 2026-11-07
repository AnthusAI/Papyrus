"""Reading and saving the publication's visual style profile: a private ``Item`` of type doctrine, one lineage, a new version for every edit.

The stored shape: the structured profile is ``metadata.visualStyle``, the review setting is ``metadata.imageReview`` and the prose guidance is
``bodyMarkus``. The *document* an editor reads and saves is those three together (``to_document`` and ``to_fields``). Old versions stay as superseded
rows, so a candidate that names a version can always resolve against the exact style it was made with.
"""
from __future__ import annotations

from typing import Any

from papyrus_content.editorial_context import _check_tenant
from papyrus_content.newsroom_doctrine import VISUAL_STYLE_DEFINITION
from papyrus_content.record_helpers import to_aws_json

from .visual_style import DEFAULT_IMAGE_REVIEW, as_object, digest

NO_PROFILE_GUARD = "none"   # expectedCurrentVersionId for the very first save, when there is nothing to be stale against


def profile_versions(client) -> list[dict]:
    """Every stored version of the profile, newest first, read by the doctrine slug (one small partition, never a table scan)."""
    rows = [row for row in client.list_by_index("itemBySlug", VISUAL_STYLE_DEFINITION["slug"])
            if row.get("type") == "doctrine" and row.get("status") == "private"]
    for row in rows:
        _check_tenant(client, row)
    return sorted(rows, key=lambda row: int(row.get("versionNumber") or 0), reverse=True)


def current_version(versions: list[dict]) -> dict | None:
    current = [row for row in versions if row.get("versionState") == "current"]
    return current[0] if current else None


def to_document(row: dict) -> dict:
    """The document a version holds: the visual style profile, with its review setting and prose guidance when it has them."""
    metadata = as_object(row.get("metadata"))
    document = dict(as_object(metadata.get("visualStyle")))
    if metadata.get("imageReview"):
        document["imageReview"] = metadata["imageReview"]
    if row.get("bodyMarkus"):
        document["bodyMarkus"] = row["bodyMarkus"]
    return document


def reference(row: dict) -> dict:
    return {"itemId": row["id"], "versionNumber": int(row.get("versionNumber") or 1), "contentHash": row.get("contentHash") or digest(to_document(row))}


def style_fields(document: dict) -> dict:
    """The Item columns a document is stored in."""
    profile = {key: value for key, value in document.items() if key not in ("imageReview", "bodyMarkus")}
    metadata: dict[str, Any] = {"visualStyle": profile, "imageReview": document.get("imageReview") or DEFAULT_IMAGE_REVIEW}
    return {"metadata": metadata, "bodyMarkus": document.get("bodyMarkus") or ""}


def next_record(versions: list[dict], document: dict, *, actor: str, reason: str, now: str, saved_by: dict) -> dict:
    """The Item record for the next version of the profile (the first version when there is none)."""
    latest = versions[0] if versions else None
    number = int(latest.get("versionNumber") or 0) + 1 if latest else 1
    fields = style_fields(document)
    fields["metadata"]["savedBy"] = saved_by
    record = {
        "id": f"item-editorial-doctrine-visual-style-v{number}", "lineageId": VISUAL_STYLE_DEFINITION["lineageId"], "versionNumber": number,
        "versionState": "current", "versionCreatedAt": now, "versionCreatedBy": actor, "changeReason": reason,
        "type": "doctrine", "status": "private", "typeStatus": "doctrine#private", "slug": VISUAL_STYLE_DEFINITION["slug"],
        "title": VISUAL_STYLE_DEFINITION["title"], "headline": VISUAL_STYLE_DEFINITION["title"], "body": [],
        "bodyMarkus": fields["bodyMarkus"], "metadata": to_aws_json(fields["metadata"]), "contentHash": digest(document), "updatedAt": now,
    }
    if latest:
        record["previousVersionId"] = latest["id"]
    return record


def store_next_version(client, versions: list[dict], record: dict) -> None:
    """Write the new version, then supersede the one it replaces (the order publishing uses, so a failure never leaves no current version)."""
    client.create_record("Item", record)
    for row in versions:
        if row.get("versionState") == "current":
            client.update_record("Item", {"id": row["id"], "versionState": "superseded"})


def saved_by_of(row: dict) -> dict:
    return as_object(as_object(row.get("metadata")).get("savedBy"))


def read_current_profile(client) -> tuple[dict | None, dict | None, dict | None]:
    """(document, reference, row) of the current profile, or (None, None, None) when the publication has none."""
    row = current_version(profile_versions(client))
    if row is None:
        return None, None, None
    return to_document(row), reference(row), row
