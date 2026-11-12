"""The backend's store for rounds of generated pictures: catalog rows in DynamoDB, every record and picture in S3, every read by index.

Nothing here adds a table or an index. A round, a candidate, a repeated-request note and a spend note are each a private ``Item`` of their own type, versioned
like a guideline document (a new version for every change, the earlier one superseded, so a discarded picture's record stays). The row holds catalog fields
only; the record itself is one JSON file attached to that version as a ModelAttachment, and a picture is one more attachment (the same payload helpers the
guideline documents use). Reads:

* a round or a candidate by id: ``itemBySlug`` on ``image-round-<id>`` or ``image-candidate-<id>``, then one download;
* the candidates of a round: ``itemsByParent`` on the round's lineage (an existing index), current versions only;
* a repeated request: ``itemBySlug`` on ``image-request-<hash>``;
* the day's spend: ``itemBySlug`` on ``image-spend-<day>``, a small partition of one row per priced picture.

A picture's file lives under ``newsroom/payloads/`` (private to editors and admins), never under ``media/``, until apply copies it there.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from papyrus_content.editorial_context import _check_tenant
from papyrus_content.guidelines.document import digest
from papyrus_content.guidelines.store import DocumentFiles, ModelAttachmentFiles
from papyrus_content.record_helpers import to_aws_json

RECORD_ROLE = "image_record"
PICTURE_ROLE = "image_candidate_file"
ROUND_TYPE, CANDIDATE_TYPE, REQUEST_TYPE, SPEND_TYPE = "image-round", "image-candidate", "image-request", "image-spend"
INACTIVE = {"deleted", "aborted"}


def _media_type_of(path: str) -> str:
    return {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}.get(path.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ItemCandidateStore:
    def __init__(self, client: Any, files: DocumentFiles | None = None, *, now: Callable[[], str] = _now, delete_object: Callable[[str], None] | None = None):
        self.client, self.files, self.now, self.delete_object = client, files or ModelAttachmentFiles(client), now, delete_object

    def _rows(self, slug: str, type_: str) -> list[dict]:
        rows = [row for row in self.client.list_by_index("itemBySlug", slug) if row.get("type") == type_ and row.get("status") == "private"]
        for row in rows:
            _check_tenant(self.client, row)
        return sorted(rows, key=lambda row: int(row.get("versionNumber") or 0), reverse=True)

    def _record_of(self, row: dict) -> dict | None:
        attachments = self.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", row["id"], limit=100)
        wanted = [a for a in attachments if a.get("role") == RECORD_ROLE and str(a.get("status") or "active").lower() not in INACTIVE]
        body = self.files.get(wanted[0]) if wanted else None
        return json.loads(body.decode("utf-8")) if body is not None else None

    def _current(self, slug: str, type_: str) -> tuple[dict | None, dict | None]:
        current = next((row for row in self._rows(slug, type_) if row.get("versionState") == "current"), None)
        return (self._record_of(current), current) if current else (None, None)

    def _save(self, slug: str, type_: str, record: dict, catalog: dict, *, parent: str | None = None, order: str | None = None, key: str | None = None) -> dict:
        """The next version of one lineage. Rows that share a slug (the day's spend notes) are told apart by ``key`` in their lineage id."""
        from papyrus_content.model_attachments import build_json_model_payload_attachment, semantic_version_key

        lineage = f"item-{slug}" + (f"-{key}" if key else "")
        versions = [row for row in self._rows(slug, type_) if row.get("lineageId") == lineage]
        number = int(versions[0].get("versionNumber") or 0) + 1 if versions else 1
        stamp = self.now()
        row_id = f"{lineage}-v{number}"
        row = {"id": row_id, "lineageId": lineage, "versionNumber": number, "versionState": "current", "versionCreatedAt": stamp, "versionCreatedBy": record.get("createdBy") or "image-service",
               "type": type_, "status": "private", "typeStatus": f"{type_}#private", "slug": slug, "title": f"{type_} {slug}", "headline": type_, "body": [], "bodyMarkus": "",
               "metadata": to_aws_json(catalog), "contentHash": digest(record), "updatedAt": stamp}
        tenant_slug = getattr(self.client, "tenant_slug", None)
        if tenant_slug:
            row["tenantSlug"] = tenant_slug
        if parent:
            row["parentLineageId"], row["sortTitle"] = parent, order or ""
        if versions:
            row["previousVersionId"] = versions[0]["id"]
        entry = build_json_model_payload_attachment({"ownerKind": "item", "ownerId": row_id, "ownerLineageId": row["lineageId"], "ownerVersionNumber": number,
                                                     "ownerVersionKey": semantic_version_key("item", row_id), "role": RECORD_ROLE, "sortKey": "record",
                                                     "filename": "record.json", "content": record, "now": stamp})
        self.files.put(entry["attachment"], entry["body"])
        self.client.create_record("Item", row)
        for earlier in versions:
            if earlier.get("versionState") == "current":
                self.client.update_record("Item", {"id": earlier["id"], "versionState": "superseded"})
        return row

    def save_round(self, round_record: dict) -> None:
        self._save(f"image-round-{round_record['roundId']}", ROUND_TYPE, round_record, {"roundId": round_record["roundId"], "createdAt": round_record.get("createdAt")})
        if round_record.get("requestId"):
            key = self._request_slug(round_record["requestId"], round_record.get("createdBy") or "")
            if not self._rows(key, REQUEST_TYPE):
                self._save(key, REQUEST_TYPE, {"roundId": round_record["roundId"], "createdBy": round_record.get("createdBy")}, {"roundId": round_record["roundId"]})

    def get_round(self, round_id: str) -> dict | None:
        return self._current(f"image-round-{round_id}", ROUND_TYPE)[0]

    @staticmethod
    def _request_slug(request_id: str, subject: str) -> str:
        return "image-request-" + hashlib.sha256(f"{subject}\n{request_id}".encode()).hexdigest()[:24]

    def round_for_request(self, request_id: str, subject: str) -> dict | None:
        pointer, _ = self._current(self._request_slug(request_id, subject), REQUEST_TYPE)
        return self.get_round(pointer["roundId"]) if pointer else None

    def save_candidate(self, candidate: dict) -> None:
        slug = f"image-candidate-{candidate['id']}"
        before, _ = self._current(slug, CANDIDATE_TYPE)
        catalog = {"roundId": candidate["roundId"], "position": candidate["position"], "status": candidate["status"], "costUsd": candidate.get("costUsd") or 0}
        self._save(slug, CANDIDATE_TYPE, candidate, catalog, parent=f"item-image-round-{candidate['roundId']}", order=f"{int(candidate['position']):04d}")
        if (candidate.get("costUsd") or 0) > 0 and not (before or {}).get("costUsd"):
            day = str(candidate.get("createdAt") or self.now())[:10]
            self._save(f"image-spend-{day}", SPEND_TYPE, {"candidateId": candidate["id"], "costUsd": candidate["costUsd"], "day": day},
                       {"costUsd": candidate["costUsd"], "day": day}, key=candidate["id"])

    def get_candidate(self, candidate_id: str) -> dict | None:
        return self._current(f"image-candidate-{candidate_id}", CANDIDATE_TYPE)[0]

    def candidates_of(self, round_id: str) -> list[dict]:
        rows = [row for row in self.client.list_by_index("itemsByParent", f"item-image-round-{round_id}") if row.get("type") == CANDIDATE_TYPE and row.get("versionState") == "current"]
        records = []
        for row in sorted(rows, key=lambda r: str(r.get("sortTitle") or "")):
            _check_tenant(self.client, row)
            records.append(self._record_of(row))
        return [record for record in records if record]

    def spent_on(self, day: str) -> float:
        rows = [row for row in self._rows(f"image-spend-{day}", SPEND_TYPE) if row.get("versionState") == "current"]
        return round(sum(float(json.loads(row["metadata"]).get("costUsd") or 0) if isinstance(row.get("metadata"), str) else float((row.get("metadata") or {}).get("costUsd") or 0)
                         for row in rows), 6)

    def _picture_owner(self, path: str) -> str:
        return "image-file-" + hashlib.sha256(path.encode()).hexdigest()[:24]

    def put_file(self, path: str, data: bytes) -> None:
        from papyrus_content.model_attachments import build_model_payload_attachment

        owner = self._picture_owner(path)
        entry = build_model_payload_attachment({"ownerKind": "item", "ownerId": owner, "role": PICTURE_ROLE, "sortKey": "file", "filename": path.rsplit("/", 1)[-1],
                                                "content": bytes(data), "mediaType": _media_type_of(path), "now": self.now()})
        self.files.put(entry["attachment"], entry["body"])

    def _picture_attachments(self, path: str) -> list[dict]:
        attachments = self.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", self._picture_owner(path), limit=100)
        return [a for a in attachments if a.get("role") == PICTURE_ROLE and str(a.get("status") or "active").lower() not in INACTIVE]

    def read_file(self, path: str) -> bytes | None:
        found = self._picture_attachments(path)
        return self.files.get(found[0]) if found else None

    def delete_file(self, path: str) -> None:
        for attachment in self._picture_attachments(path):
            if self.delete_object and attachment.get("storagePath"):
                self.delete_object(attachment["storagePath"])
            self.client.update_record("ModelAttachment", {"id": attachment["id"], "status": "deleted"})
