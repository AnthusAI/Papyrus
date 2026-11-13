"""Saving and reading guideline documents: a catalog row in DynamoDB, the document itself in S3.

One lineage of the private ``doctrine`` Item per (kind, scope): a new version for every save that changes something. The Item row holds only catalog
fields (slug, version, who, when, why, contentHash); its ``bodyMarkus`` and ``metadata`` stay empty. The document is one JSON file attached to that
Item version as a ModelAttachment with the role ``doctrine_document`` (``newsroom/payloads/item/<id>/doctrine-document/guidelines.json``, the path writer turning the role into a safe id), the same
pattern Story bodies use. Nothing here knows what is *in* a document or which kinds exist; the kind registry in ``document.py`` is the only place
that changes when a kind is added.

Every read is a query on a named index (``itemBySlug``, ``modelAttachmentsByOwnerRoleAndSortKey``) plus one download; nothing lists a table.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from papyrus_content.editorial_context import _check_tenant
from papyrus_content.record_helpers import to_aws_json

from .document import GuidelineError, digest, kind_spec, slug_for, validate_document

ROLE = "doctrine_document"
ASSET_ROLE = "doctrine_asset"   # binary files a document names (a design system's fonts): one ModelAttachment each, sortKey = the file's name in the document
PENDING = "pending"   # versionState of a version whose row exists but whose files are not all stored yet: no reader sees it, a retry of the same save finishes it
NO_DOCUMENT_GUARD = "none"   # expectedCurrentVersionId for the first save of a lineage


class DocumentFiles(Protocol):
    """Where the document bytes go. The real one is the ModelAttachment upload and download; tests use an in-memory one."""

    def put(self, attachment: dict, body: bytes) -> dict: ...

    def get(self, attachment: dict) -> bytes | None: ...


class ModelAttachmentFiles:
    def __init__(self, client):
        self.client = client

    def put(self, attachment: dict, body: bytes) -> dict:
        from papyrus_content.model_attachments import upload_attachment_body

        return upload_attachment_body(self.client, attachment, body)

    def get(self, attachment: dict) -> bytes | None:
        from papyrus_content.model_attachments import download_attachment_buffer

        return download_attachment_buffer(self.client, attachment)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GuidelineStore:
    def __init__(self, client, files: DocumentFiles | None = None):
        self.client = client
        self.files = files or ModelAttachmentFiles(client)

    # --- reads --------------------------------------------------------------------------------------------------------------------------------------

    def _rows(self, kind: str, section: str | None) -> list[dict]:
        slug = slug_for(kind, section)
        rows = [row for row in self.client.list_by_index("itemBySlug", slug) if row.get("type") == "doctrine" and row.get("status") == "private"]
        for row in rows:
            _check_tenant(self.client, row)
        return sorted(rows, key=lambda row: int(row.get("versionNumber") or 0), reverse=True)

    def versions(self, kind: str, section: str | None = None) -> list[dict]:
        """Every stored catalog row of the lineage, newest first: one index query on the slug (a small partition, never a scan). A version still being saved is not stored yet."""
        return [row for row in self._rows(kind, section) if row.get("versionState") != PENDING]

    def current_row(self, kind: str, section: str | None = None) -> dict | None:
        current = [row for row in self.versions(kind, section) if row.get("versionState") == "current"]
        return current[0] if current else None

    def _document_of(self, row: dict) -> dict:
        attachments = self.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", row["id"], limit=100)
        wanted = [a for a in attachments if a.get("role") == ROLE and str(a.get("status") or "active").lower() not in {"deleted", "aborted"}]
        if not wanted:
            raise GuidelineError("not_found", f"The guidelines {row.get('slug')} version {row.get('versionNumber')} have no stored document.", {"itemId": row["id"]})
        body = self.files.get(wanted[0])
        if body is None:
            raise GuidelineError("not_found", f"The document file of {row['id']} could not be read.", {"itemId": row["id"]})
        document = json.loads(body.decode("utf-8"))
        if row.get("contentHash") and digest(document) != row["contentHash"]:
            raise GuidelineError("document_hash_mismatch", f"The stored document of {row['id']} does not match its content hash.", {"itemId": row["id"]})
        return document

    def document_of(self, row: dict) -> dict:
        """The document one catalog row names: one attachment index query and one download."""
        return self._document_of(row)

    def read(self, kind: str, section: str | None = None, *, version: int | None = None) -> dict | None:
        """``{document, reference}`` of the current version (or the numbered one), or None when there is none."""
        rows = self.versions(kind, section)
        row = next((r for r in rows if int(r.get("versionNumber") or 0) == version), None) if version is not None else \
            next((r for r in rows if r.get("versionState") == "current"), None)
        if row is None:
            return None
        return {"document": self._document_of(row), "reference": reference(row), "row": row}

    def assets_of(self, row: dict) -> dict[str, dict]:
        """The asset attachments of one version by file name: one index query, nothing downloaded."""
        attachments = self.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", row["id"], limit=100)
        return {a["sortKey"]: a for a in attachments if a.get("role") == ASSET_ROLE and str(a.get("status") or "active").lower() not in {"deleted", "aborted"}}

    def get_asset(self, attachment: dict) -> bytes:
        body = self.files.get(attachment)
        if body is None:
            raise GuidelineError("not_found", f"The file {attachment.get('sortKey')} could not be read.", {"attachmentId": attachment.get("id")})
        return body

    def history(self, kind: str, section: str | None = None) -> list[dict]:
        return [{"itemId": r["id"], "versionNumber": int(r.get("versionNumber") or 0), "versionState": r.get("versionState"), "by": r.get("versionCreatedBy"),
                 "at": r.get("versionCreatedAt"), "reason": r.get("changeReason"), "contentHash": r.get("contentHash")} for r in self.versions(kind, section)]

    # --- writes -------------------------------------------------------------------------------------------------------------------------------------

    def save(self, kind: str, document: Any, *, section: str | None = None, expected_current_version_id: str | None = None, actor: str, reason: str,
             now: str | None = None, assets: dict[str, bytes] | None = None, saved_by: dict | None = None, even_if_unchanged: bool = False) -> dict:
        """Save a document as the lineage's next version. ``{changed, reference}``.

        ``assets`` are binary files the document names (file name -> bytes), stored beside it as ModelAttachments of the same version. The caller puts
        their hashes in the document, so the content hash covers them.

        The first save names ``none``; a later one names the Item id it replaces and is refused as stale when that is no longer current. A document equal to
        the current one makes no version, unless ``even_if_unchanged`` (a document whose current version still holds it in an older shape is rewritten in the new one). The row is created first, in the state ``pending``, because the upload function only accepts a file for an Item that exists; the files follow, and only then does the row become
        ``current`` and the older one ``superseded``. A failure in between leaves a ``pending`` row that no reader sees; the same save again finds it and finishes it (same id, same attachment slots), so it never blocks the next save.
        ``saved_by`` (``{sub, kind, requestId}``) is recorded in the row's ``metadata`` when the door or the command line gives it: it is how a repeated request is
        recognised and how history says whether a person or an agent saved a version. Nothing else goes in ``metadata``.
        """
        spec = kind_spec(kind)
        scope = "section" if section else "publication"
        problems = validate_document(kind, document, scope)
        if problems:
            raise GuidelineError("invalid_input", "The document has problems: " + "; ".join(f"{p.path or 'document'} {p.message}" for p in problems),
                                 {"problems": [{"path": p.path, "message": p.message, "code": p.code} for p in problems]})
        if not str(reason or "").strip():
            raise GuidelineError("invalid_input", "A reason is required.")
        rows = self._rows(kind, section)
        versions = [row for row in rows if row.get("versionState") != PENDING]
        pending = next((row for row in rows if row.get("versionState") == PENDING), None)
        current = next((r for r in versions if r.get("versionState") == "current"), None)
        guard = NO_DOCUMENT_GUARD if current is None else current["id"]
        if expected_current_version_id != guard:
            raise GuidelineError("stale_version", "The guidelines have changed since you read them. Read them again and apply your change to the new version.",
                                 {"expectedCurrentVersionId": guard})
        content_hash = digest(document)
        if current is not None and current.get("contentHash") == content_hash and not even_if_unchanged:
            return {"changed": False, "reference": reference(current)}
        stamp = now or _now()
        record = next_record(spec.name, section, versions, content_hash, actor=actor, reason=reason, now=stamp,
                             tenant_slug=getattr(self.client, "tenant_slug", None), saved_by=saved_by)
        if pending is None:
            self.client.create_record("Item", {**record, "versionState": PENDING})
        else:
            self.client.update_record("Item", {**{key: value for key, value in record.items() if key != "id"}, "id": pending["id"], "versionState": PENDING})
        self._put_document(record, document, stamp)
        for name, body in (assets or {}).items():
            self._put_asset(record, name, body, stamp)
        self.client.update_record("Item", {"id": record["id"], "versionState": "current"})
        for row in versions:
            if row.get("versionState") == "current":
                self.client.update_record("Item", {"id": row["id"], "versionState": "superseded"})
        return {"changed": True, "reference": reference(record)}

    def _put_document(self, record: dict, document: dict, now: str) -> dict:
        from papyrus_content.model_attachments import build_json_model_payload_attachment, semantic_version_key

        entry = build_json_model_payload_attachment({
            "ownerKind": "item", "ownerId": record["id"], "ownerLineageId": record["lineageId"], "ownerVersionNumber": record["versionNumber"],
            "ownerVersionKey": semantic_version_key("item", record["id"]), "role": ROLE, "sortKey": "document", "filename": "guidelines.json",
            "content": document, "now": now,
        })
        return self.files.put(entry["attachment"], entry["body"])

    def _put_asset(self, record: dict, name: str, body: bytes, now: str) -> dict:
        from papyrus_content.model_attachments import attachment_safe_id, build_model_payload_attachment, semantic_version_key

        entry = build_model_payload_attachment({
            "ownerKind": "item", "ownerId": record["id"], "ownerLineageId": record["lineageId"], "ownerVersionNumber": record["versionNumber"],
            "ownerVersionKey": semantic_version_key("item", record["id"]), "role": ASSET_ROLE, "sortKey": name, "filename": attachment_safe_id(name),
            "content": bytes(body), "mediaType": "application/octet-stream", "now": now,
        })
        return self.files.put(entry["attachment"], entry["body"])


def reference(row: dict) -> dict:
    return {"itemId": row["id"], "slug": row.get("slug"), "versionNumber": int(row.get("versionNumber") or 1), "contentHash": row.get("contentHash")}


def saved_by_of(row: dict) -> dict:
    """The ``savedBy`` note of a catalog row ({} when the version was saved without one)."""
    metadata = row.get("metadata")
    if isinstance(metadata, str) and metadata.strip():
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return {}
    saved = metadata.get("savedBy") if isinstance(metadata, dict) else None
    return saved if isinstance(saved, dict) else {}


def next_record(kind: str, section: str | None, versions: list[dict], content_hash: str, *, actor: str, reason: str, now: str,
                tenant_slug: str | None = None, saved_by: dict | None = None) -> dict:
    """The catalog row for the next version. Catalog fields only: the text is the S3 document."""
    slug = slug_for(kind, section)
    latest = versions[0] if versions else None
    number = int(latest.get("versionNumber") or 0) + 1 if latest else 1
    title = f"{kind.title()} guidelines" + (f" ({section})" if section else "")
    record = {
        "id": f"item-{slug}-v{number}", "lineageId": f"item-{slug}", "versionNumber": number, "versionState": "current", "versionCreatedAt": now,
        "versionCreatedBy": actor, "changeReason": reason, "type": "doctrine", "status": "private", "typeStatus": "doctrine#private", "slug": slug,
        "title": title, "headline": title, "body": [], "bodyMarkus": "", "metadata": to_aws_json({"savedBy": saved_by} if saved_by else {}), "contentHash": content_hash, "updatedAt": now,
    }
    if section:
        record["section"] = section
    if tenant_slug:
        record["tenantSlug"] = tenant_slug
    if latest:
        record["previousVersionId"] = latest["id"]
    return record
