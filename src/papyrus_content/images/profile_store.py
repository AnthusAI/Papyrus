"""Reading and saving the publication's visual style profile and each section's image document, on the guideline store (PPY-c16829).

The profile is the ``image`` guideline document: a private ``Item`` of type doctrine, slug ``editorial-doctrine-visual-style``, one lineage, a new version for
every edit, with the document itself one S3 file and only catalog fields in the row. A section's image document is the same kind at section scope, slug
``desk-doctrine-<sectionKey>-visual-style``. The *document* an editor reads and saves is the profile with its review setting and prose guidance beside it.

A site that has not yet re-saved its profile still holds the old inline shape: the structured profile in ``metadata.visualStyle``, the review setting in
``metadata.imageReview`` and the prose in ``bodyMarkus``. Those rows are read as they are and never rewritten; the next save of the profile writes the new shape
as the next version of the same lineage, and the older versions stay. Old versions stay as superseded rows, so a candidate that names a version can always
resolve against the exact style it was made with.
"""
from __future__ import annotations

from typing import Any

from papyrus_content.guidelines.store import DocumentFiles, GuidelineStore
from papyrus_content.newsroom_doctrine import VISUAL_STYLE_DEFINITION
from papyrus_content.record_helpers import to_aws_json

from .visual_style import DEFAULT_IMAGE_REVIEW, as_object, digest

NO_PROFILE_GUARD = "none"   # expectedCurrentVersionId for the very first save, when there is nothing to be stale against
IMAGE_KIND = "image"
SECTION_STYLE_KEYS = ("schemaVersion", "bodyMarkus")


def document_store(client, files: DocumentFiles | None = None) -> GuidelineStore:
    """The guideline store over this client. A client may carry its own document files (the in-memory backend of the tests); otherwise the signed-in session's."""
    return GuidelineStore(client, files or getattr(client, "document_files", None))


def profile_versions(client, section: str | None = None, files: DocumentFiles | None = None) -> list[dict]:
    """Every stored version of the profile (or of one section's image document), newest first: one index query on the slug, never a table scan."""
    return document_store(client, files).versions(IMAGE_KIND, section)


def current_version(versions: list[dict]) -> dict | None:
    current = [row for row in versions if row.get("versionState") == "current"]
    return current[0] if current else None


def is_inline_shape(row: dict) -> bool:
    """True for a version saved before the move: its profile is inline in ``metadata.visualStyle``."""
    return bool(as_object(as_object(row.get("metadata")).get("visualStyle")))


def inline_document(row: dict) -> dict:
    metadata = as_object(row.get("metadata"))
    document = dict(as_object(metadata.get("visualStyle")))
    if metadata.get("imageReview"):
        document["imageReview"] = metadata["imageReview"]
    if row.get("bodyMarkus"):
        document["bodyMarkus"] = row["bodyMarkus"]
    return document


def to_document(row: dict, store: GuidelineStore | None = None) -> dict:
    """The document a version holds: the visual style profile, with its review setting and prose guidance when it has them.

    An old inline version is read from its row. A version in the new shape is read from its S3 file through ``store`` (one index query and one download)."""
    if is_inline_shape(row) or store is None:
        return inline_document(row)
    return store.document_of(row)


def reference(row: dict) -> dict:
    return {"itemId": row["id"], "versionNumber": int(row.get("versionNumber") or 1), "contentHash": row.get("contentHash") or digest(inline_document(row))}


def saved_by_of(row: dict) -> dict:
    return as_object(as_object(row.get("metadata")).get("savedBy"))


def read_current_profile(client, files: DocumentFiles | None = None) -> tuple[dict | None, dict | None, dict | None]:
    """(document, reference, row) of the current profile, or (None, None, None) when the publication has none."""
    store = document_store(client, files)
    row = current_version(store.versions(IMAGE_KIND))
    if row is None:
        return None, None, None
    return to_document(row, store), reference(row), row


def section_key_of(section: dict | None) -> str:
    return str((section or {}).get("id") or "").split("#")[-1]


def read_section_document(client, section: dict | None, files: DocumentFiles | None = None) -> dict | None:
    """The section's image document as the resolver's section layer, or None when the section has none (its old ``visualStyle`` and ``visualGuidance`` then apply).

    One index query for the section's lineage and, when it has a current version, one attachment query and one download."""
    key = section_key_of(section)
    if not key:
        return None
    found = document_store(client, files).read(IMAGE_KIND, key)
    if found is None:
        return None
    document = found["document"]
    return {"visualStyle": {name: value for name, value in document.items() if name not in SECTION_STYLE_KEYS},
            "visualGuidance": document.get("bodyMarkus") or "",
            "documentSource": {"itemId": found["row"]["id"], "versionNumber": int(found["row"].get("versionNumber") or 1), "contentHash": found["row"].get("contentHash")}}


# --- the old inline shape, written only to seed a site that has not moved yet (the specs and the tests) ---------------------------------------------

def inline_fields(document: dict) -> dict:
    profile = {key: value for key, value in document.items() if key not in ("imageReview", "bodyMarkus")}
    metadata: dict[str, Any] = {"visualStyle": profile, "imageReview": document.get("imageReview") or DEFAULT_IMAGE_REVIEW}
    return {"metadata": metadata, "bodyMarkus": document.get("bodyMarkus") or ""}


def inline_next_record(versions: list[dict], document: dict, *, actor: str, reason: str, now: str, saved_by: dict) -> dict:
    """The Item record the old shape stored for the next version of the profile."""
    latest = versions[0] if versions else None
    number = int(latest.get("versionNumber") or 0) + 1 if latest else 1
    fields = inline_fields(document)
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
