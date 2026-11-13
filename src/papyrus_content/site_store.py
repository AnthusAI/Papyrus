"""Site documents: the SiteConfig, the brand and the nav as versioned JSON in S3, with a catalogue in DynamoDB (PPY-c020ce).

DynamoDB holds only the catalogue: ``SiteDocument`` (one row per tenant and kind, pointing at the live version) and
``SiteDocumentVersion`` (one row per saved version). The body of every version is an S3 object at
``tenants/<tenant>/site/<kind>/<version>.json``; text never goes in DynamoDB.

A save is three writes in a fixed order, so a save that stops half way is never live:

1. the version object goes to S3;
2. the ``SiteDocumentVersion`` row is created;
3. ``SiteDocument.currentVersion`` moves, conditionally on the version the save started from.

Until step 3 succeeds the old version is still the one ``read_current`` returns. An object or version row left behind by a
failed save is harmless: the next save numbers from the highest version row, so it never reuses the orphan.

Nothing calls this yet; the site store and the projection will (PPY-f0ae90, PPY-e572de). S3 and the table are injected:

* ``s3`` has ``put_object(Bucket=, Key=, Body=, ContentType=)`` and ``get_object(Bucket=, Key=)`` returning ``{"Body": <readable>}``
  (a boto3 S3 client does);
* ``table`` has ``get(model, id) -> dict | None``, ``create(model, row)`` (raises ``KeyError`` when the id exists),
  ``update_if(model, id, changes, expected) -> bool`` (applies ``changes`` only while every ``expected`` field still matches) and
  ``latest_version(document_id) -> dict | None`` (one query on the ``documentId`` index, highest ``version`` first, limit 1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from .tenancy import TENANT_KEY_SEPARATOR, TenantError, validate_tenant_id

SITE_DOCUMENT_KINDS = ("site", "brand", "nav")
SCHEMA_VERSION = 1

#: Index query field, as declared in amplify/data/schema.ts and resource.ts.
VERSIONS_BY_DOCUMENT_QUERY = "listSiteDocumentVersionsByDocument"


class SiteStoreError(TenantError):
    pass


class SiteSaveConflict(SiteStoreError):
    """Another save took the version number or moved the pointer first. Nothing of this save is live; read again and retry."""


def _kind(kind: str) -> str:
    if kind not in SITE_DOCUMENT_KINDS:
        raise SiteStoreError(f"Site document kind {kind!r} must be one of: {', '.join(SITE_DOCUMENT_KINDS)}.")
    return kind


def document_id(tenant_id: str, kind: str) -> str:
    return f"{validate_tenant_id(tenant_id)}{TENANT_KEY_SEPARATOR}{_kind(kind)}"


def version_id(tenant_id: str, kind: str, version: int) -> str:
    return f"{document_id(tenant_id, kind)}{TENANT_KEY_SEPARATOR}{version}"


def version_key(tenant_id: str, kind: str, version: int) -> str:
    if not isinstance(version, int) or version < 1:
        raise SiteStoreError("A version is a whole number from 1.")
    return f"tenants/{validate_tenant_id(tenant_id)}/site/{_kind(kind)}/{version}.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SiteStore:
    def __init__(self, s3: Any, bucket: str, table: Any, *, now: Callable[[], str] = _now):
        self._s3 = s3
        self._bucket = bucket
        self._table = table
        self._now = now

    def current_version(self, tenant_id: str, kind: str) -> int:
        """The live version number, 0 when the document has never been saved."""
        row = self._table.get("SiteDocument", document_id(tenant_id, kind))
        return int(row["currentVersion"]) if row else 0

    def read_current(self, tenant_id: str, kind: str) -> dict[str, Any] | None:
        row = self._table.get("SiteDocument", document_id(tenant_id, kind))
        return None if row is None else self._read_object(row)

    def read_version(self, tenant_id: str, kind: str, version: int) -> dict[str, Any]:
        row = self._table.get("SiteDocumentVersion", version_id(tenant_id, kind, version))
        if row is None:
            raise SiteStoreError(f"{document_id(tenant_id, kind)} has no version {version}.")
        return self._read_object(row)

    def save(self, tenant_id: str, kind: str, body: dict[str, Any], updated_by: str, *, note: str | None = None) -> int:
        """Save ``body`` as the next version and make it live. Returns the new version number."""
        data = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._save_bytes(tenant_id, kind, data, updated_by, note)

    def restore(self, tenant_id: str, kind: str, version: int, updated_by: str) -> int:
        """Make an older version's content live again as a NEW version; history is never rewritten."""
        row = self._table.get("SiteDocumentVersion", version_id(tenant_id, kind, version))
        if row is None:
            raise SiteStoreError(f"{document_id(tenant_id, kind)} has no version {version}.")
        return self._save_bytes(tenant_id, kind, self._read_bytes(row), updated_by, f"Restored from version {version}")

    def _save_bytes(self, tenant_id: str, kind: str, data: bytes, updated_by: str, note: str | None) -> int:
        doc_id = document_id(tenant_id, kind)
        document = self._table.get("SiteDocument", doc_id)
        previous = int(document["currentVersion"]) if document else 0
        latest = self._table.latest_version(doc_id)
        version = max(previous, int(latest["version"]) if latest else 0) + 1
        key = version_key(tenant_id, kind, version)
        sha = hashlib.sha256(data).hexdigest()
        stamp = self._now()

        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType="application/json")
        version_row = {
            "id": version_id(tenant_id, kind, version), "tenantId": tenant_id, "documentId": doc_id, "version": version,
            "s3Key": key, "sha256": sha, "createdBy": updated_by, "createdAt": stamp,
        }
        if note:
            version_row["note"] = note
        try:
            self._table.create("SiteDocumentVersion", version_row)
        except KeyError as error:
            raise SiteSaveConflict(f"{doc_id} version {version} was taken by another save.") from error

        pointer = {"s3Key": key, "sha256": sha, "currentVersion": version, "schemaVersion": SCHEMA_VERSION, "updatedBy": updated_by, "updatedAt": stamp}
        if document is None:
            try:
                self._table.create("SiteDocument", {"id": doc_id, "tenantId": tenant_id, "kind": kind, **pointer})
            except KeyError as error:
                raise SiteSaveConflict(f"{doc_id} was created by another save.") from error
        elif not self._table.update_if("SiteDocument", doc_id, pointer, {"currentVersion": previous}):
            raise SiteSaveConflict(f"{doc_id} moved from version {previous} while this save ran.")
        return version

    def _read_bytes(self, row: dict[str, Any]) -> bytes:
        data = self._s3.get_object(Bucket=self._bucket, Key=row["s3Key"])["Body"].read()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise SiteStoreError(f"{row['s3Key']} does not match its recorded sha256.")
        return data

    def _read_object(self, row: dict[str, Any]) -> dict[str, Any]:
        return json.loads(self._read_bytes(row).decode("utf-8"))
