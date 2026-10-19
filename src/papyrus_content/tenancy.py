"""Tenant keys for one backend that serves several publications.

A tenant is one Prospectus account's publication. Records of the tenant
models carry a ``tenantId``; the index values that would otherwise be global
(type and status, section and status, slug) are prefixed with it, so a
partition lookup can only ever return one tenant's rows. A backend without a
tenant id behaves exactly as before and writes nothing tenant-shaped.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

TENANT_ID_ENVIRONMENT_VARIABLE = "PAPYRUS_TENANT_ID"
TENANT_KEY_SEPARATOR = "#"
TENANT_ITEM_ID_SEPARATOR = "."
TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TENANT_MEDIA_PREFIX_TEMPLATE = "media/{tenant_id}/"

TENANT_MODELS = frozenset(
    {"Item", "PublishedItem", "MediaAsset", "PublishedMediaAsset", "NewsroomSection"}
)
TENANT_SCOPED_INDEX_FIELDS = ("typeStatus", "sectionStatus")
TENANT_SLUG_FIELD = "tenantSlug"
TENANT_SLUG_MODELS = frozenset({"Item", "PublishedItem"})
TENANT_MEDIA_PATH_MODELS = frozenset({"MediaAsset", "PublishedMediaAsset"})
TENANT_SCOPED_RECORD_ID_MODELS = frozenset({"NewsroomSection"})
STORED_RECORD_ID_FIELD = "storedId"
TENANT_INDEX_REDIRECTS = {"itemBySlug": "itemByTenantSlug"}


class TenantError(ValueError):
    pass


def validate_tenant_id(tenant_id: str) -> str:
    if not TENANT_ID_PATTERN.match(tenant_id):
        raise TenantError(
            f"Tenant id {tenant_id!r} must be lowercase letters, digits and hyphens, starting with a letter or digit."
        )
    return tenant_id


def tenant_id_from_environment() -> str | None:
    value = (os.environ.get(TENANT_ID_ENVIRONMENT_VARIABLE) or "").strip()
    return validate_tenant_id(value) if value else None


def tenant_scoped_value(tenant_id: str | None, value: str) -> str:
    if not tenant_id:
        return value
    prefix = f"{tenant_id}{TENANT_KEY_SEPARATOR}"
    return value if value.startswith(prefix) else f"{prefix}{value}"


def tenant_scoped_record_id(model_name: str, tenant_id: str | None, record_id: str) -> str:
    if not tenant_id or model_name not in TENANT_SCOPED_RECORD_ID_MODELS:
        return record_id
    return tenant_scoped_value(tenant_id, record_id)


def tenant_bare_record_id(tenant_id: str | None, record_id: str) -> str:
    prefix = f"{tenant_id}{TENANT_KEY_SEPARATOR}" if tenant_id else ""
    return record_id[len(prefix):] if prefix and record_id.startswith(prefix) else record_id


def tenant_row_with_bare_record_id(model_name: str, tenant_id: str | None, row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not tenant_id or model_name not in TENANT_SCOPED_RECORD_ID_MODELS or not row or not isinstance(row.get("id"), str):
        return row
    bare = dict(row)
    bare[STORED_RECORD_ID_FIELD] = row["id"]
    bare["id"] = tenant_bare_record_id(tenant_id, row["id"])
    return bare


def tenant_scoped_item_id(tenant_id: str | None, item_id: str) -> str:
    if not tenant_id:
        return item_id
    prefix = f"{tenant_id}{TENANT_ITEM_ID_SEPARATOR}"
    return item_id if item_id.startswith(prefix) else f"{prefix}{item_id}"


def tenant_id_from_options(options: dict[str, Any]) -> str | None:
    raw_value = options.get("tenant")
    explicit = raw_value.strip() if isinstance(raw_value, str) else ""
    return validate_tenant_id(explicit) if explicit else tenant_id_from_environment()


def tenant_media_prefix(tenant_id: str) -> str:
    return TENANT_MEDIA_PREFIX_TEMPLATE.format(tenant_id=tenant_id)


def tenant_media_path(tenant_id: str, storage_path: str) -> str:
    prefix = tenant_media_prefix(tenant_id)
    if storage_path.startswith(prefix):
        return storage_path
    if storage_path.startswith("media/"):
        return prefix + storage_path[len("media/"):]
    return storage_path


def tenant_stamped_payload(model_name: str, tenant_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    if not tenant_id or model_name not in TENANT_MODELS:
        return payload
    stamped = dict(payload)
    stamped["tenantId"] = tenant_id
    stamped.pop(STORED_RECORD_ID_FIELD, None)
    if isinstance(stamped.get("id"), str):
        stamped["id"] = tenant_scoped_record_id(model_name, tenant_id, stamped["id"])
    for field_name in TENANT_SCOPED_INDEX_FIELDS:
        if isinstance(stamped.get(field_name), str):
            stamped[field_name] = tenant_scoped_value(tenant_id, stamped[field_name])
    if model_name in TENANT_SLUG_MODELS and isinstance(stamped.get("slug"), str):
        stamped[TENANT_SLUG_FIELD] = tenant_scoped_value(tenant_id, stamped["slug"])
    if model_name in TENANT_MEDIA_PATH_MODELS and isinstance(stamped.get("storagePath"), str):
        stamped["storagePath"] = tenant_media_path(tenant_id, stamped["storagePath"])
    return stamped


def row_belongs_to_tenant(model_name: str, tenant_id: str | None, row: dict[str, Any] | None) -> bool:
    if not tenant_id or model_name not in TENANT_MODELS or row is None:
        return True
    return row.get("tenantId") == tenant_id


def rows_for_tenant(model_name: str, tenant_id: str | None, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row_belongs_to_tenant(model_name, tenant_id, row)]


def tenant_scoped_index(tenant_id: str | None, index_name: str, key_value: str) -> tuple[str, str]:
    if not tenant_id or index_name not in TENANT_INDEX_REDIRECTS:
        return index_name, key_value
    return TENANT_INDEX_REDIRECTS[index_name], tenant_scoped_value(tenant_id, key_value)
