"""Save, publish and unpublish Items and their Published* projection (PPY-b3a10e).

One module used by the CLI now and by the editor Lambda later. An ``Item`` is
edited in place; each publish increments ``versionNumber`` and writes the same
number to the single ``PublishedItem`` row of the lineage.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .markus_renderer.derive import BodyError, derive_body
from .record_helpers import compact_dict, content_hash_for, slugify, to_aws_json

PUBLISHED_ID_PREFIX = "published-"
DATE_FORMATS = ("%A, %B %d, %Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%Y/%m/%d")
MEDIA_COMMON_FIELDS = (
    "type role sortKey storagePath externalUrl alt caption credit width height aspectRatio focalX focalY "
    "minHeight preferredHeight maxHeight crop wrapsText metadata"
).split()


@dataclass
class ItemFields:
    type: str
    slug: str
    section: str | None
    front_matter_yaml: str | None
    body_markus: str
    aliases: list[str]
    id: str | None = None
    source_path: str | None = None
    overrides: dict | None = None


@dataclass
class PublishResult:
    changed: bool
    item_id: str
    published_item_id: str
    version_number: int | None
    deleted_media_ids: list[str] = field(default_factory=list)


class PublishError(Exception):
    def __init__(self, code: str, message: str = "", errors: list[BodyError] | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.errors = list(errors or [])


def item_id_for(section: str | None, slug: str) -> str:
    section_slug = slugify(section or "")
    return f"item-{section_slug}-{slug}" if section_slug else f"item-{slug}"


def new_item_id() -> str:
    return "item-" + uuid.uuid4().hex[:12]


def published_item_id_for(lineage_id: str) -> str:
    return PUBLISHED_ID_PREFIX + lineage_id


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_from_date_value(value: Any) -> str | None:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if "T" not in text and " " not in text:
            return parsed.strftime("%Y-%m-%dT00:00:00Z")
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            continue
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def columns_from_front_matter(fm: dict) -> dict:
    title = _first_text(fm.get("title"))
    authors = fm.get("authors")
    if isinstance(authors, list) and authors:
        byline = ", ".join(str(author) for author in authors)
    else:
        byline = fm.get("author") if isinstance(fm.get("author"), str) else None
    return {
        "title": title,
        "headline": title,
        "sortTitle": title,
        "deck": _first_text(fm.get("deck"), fm.get("standfirst"), fm.get("description")),
        "byline": byline,
        "publishedAt": _iso_from_date_value(fm.get("date")),
    }


def _load_front_matter(front_matter_yaml: str | None) -> dict:
    if not front_matter_yaml or not front_matter_yaml.strip():
        return {}
    import yaml

    loaded = yaml.safe_load(front_matter_yaml)
    return loaded if isinstance(loaded, dict) else {}


def _parse_json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _derive_or_raise(front_matter_yaml: str | None, body_markus: str) -> dict:
    derivation = derive_body(front_matter_yaml, body_markus)
    if not derivation.ok:
        first = derivation.errors[0]
        raise PublishError(first.code, first.message, list(derivation.errors))
    return derivation.body_ir


def _status_keys(item_type: str, section: str | None, status: str) -> dict[str, str]:
    return {
        "typeStatus": f"{item_type}#{status}",
        "sectionStatus": f"{slugify(section or '')}#{status}",
    }


def _source_content_hash(fields: ItemFields) -> str:
    return content_hash_for(
        {
            "type": fields.type,
            "slug": fields.slug,
            "section": fields.section,
            "frontMatterYaml": fields.front_matter_yaml,
            "bodyMarkus": fields.body_markus,
            "aliases": list(fields.aliases),
        }
    )


def _without_server_fields(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in ("createdAt", "updatedAt")}


def save_item(
    client,
    fields: ItemFields,
    *,
    actor: str,
    now: str | None = None,
    expected_content_hash: str | None = None,
) -> dict:
    now = now or utc_now_iso()
    item_id = fields.id or new_item_id()
    envelope = _derive_or_raise(fields.front_matter_yaml, fields.body_markus)
    columns = columns_from_front_matter(_load_front_matter(fields.front_matter_yaml))
    existing = client.get_record("Item", item_id)

    if existing is not None:
        if expected_content_hash is not None and expected_content_hash != existing.get("contentHash"):
            raise PublishError("conflict", "The item changed since it was loaded.")
        if existing.get("slug") != fields.slug:
            lineage_id = existing.get("lineageId") or item_id
            was_published = (
                existing.get("status") == "published"
                or client.get_record("PublishedItem", published_item_id_for(lineage_id)) is not None
            )
            if was_published:
                raise PublishError("slug-locked", "The slug cannot change once the item has been published.")
        base = _without_server_fields(existing)
        status = existing.get("status") or "draft"
        columns["publishedAt"] = existing.get("publishedAt")
        metadata = _parse_json_object(existing.get("metadata"))
        if fields.source_path is None:
            fields.source_path = (metadata.get("source") or {}).get("path")
    else:
        base = {
            "id": item_id,
            "lineageId": item_id,
            "versionNumber": 1,
            "versionState": "current",
            "versionCreatedAt": now,
            "versionCreatedBy": actor,
            "changeReason": "created",
        }
        status = "draft"
        metadata = {}

    columns.update({key: value for key, value in (fields.overrides or {}).items()})
    metadata["frontMatterYaml"] = fields.front_matter_yaml
    metadata["source"] = {"path": fields.source_path}

    record = {
        **base,
        **compact_dict(columns),
        "type": fields.type,
        "slug": fields.slug,
        "section": fields.section,
        "status": status,
        **_status_keys(fields.type, fields.section, status),
        "bodyMarkus": fields.body_markus,
        "bodyIr": to_aws_json(envelope),
        "aliases": list(fields.aliases),
        "metadata": to_aws_json(metadata),
        "contentHash": _source_content_hash(fields),
    }
    client.upsert("Item", compact_dict(record))
    return record


def _media_src_paths(media: list[dict]) -> set[str]:
    return {
        str(_parse_json_object(row.get("metadata")).get("srcPath"))
        for row in media
        if _parse_json_object(row.get("metadata")).get("srcPath")
    }


def _require_images_present(envelope: dict, media: list[dict]) -> None:
    available = _media_src_paths(media)
    for image in envelope["papyrus"]["images"].values():
        src = image.get("src") or ""
        if src.startswith(("http://", "https://")):
            continue
        if src not in available:
            raise PublishError("image-missing", src)


def project_item_to_published(
    item: dict,
    media: list[dict],
    *,
    published_at: str,
    version_number: int,
) -> tuple[dict, list[dict]]:
    lineage_id = item.get("lineageId") or item["id"]
    published_id = published_item_id_for(lineage_id)
    section = item.get("section")
    metadata = _parse_json_object(item.get("metadata"))
    metadata["sourceContentHash"] = item.get("contentHash")
    published = {
        "id": published_id,
        "sourceItemId": item["id"],
        "itemLineageId": lineage_id,
        "versionNumber": version_number,
        "type": item.get("type"),
        "status": "published",
        **_status_keys(item.get("type") or "", section, "published"),
        "slug": item.get("slug"),
        "shortSlug": item.get("shortSlug"),
        "section": section,
        "title": item.get("title"),
        "headline": item.get("headline"),
        "deck": item.get("deck"),
        "bodyMarkus": item.get("bodyMarkus"),
        "bodyIr": item.get("bodyIr"),
        "aliases": list(item.get("aliases") or []),
        "metadata": to_aws_json(metadata),
        "byline": item.get("byline"),
        "dateline": item.get("dateline"),
        "publishedAt": published_at,
        "sortTitle": item.get("sortTitle"),
        "pullQuotes": [],
        "layout": to_aws_json({"source": "cms"}),
        "editorial": to_aws_json({}),
    }
    published_media = [
        compact_dict(
            {
                "id": published_item_id_for(row["id"]),
                "sourceMediaAssetId": row["id"],
                "publishedItemId": published_id,
                "sourceItemId": item["id"],
                "itemLineageId": lineage_id,
                **{name: row.get(name) for name in MEDIA_COMMON_FIELDS},
            }
        )
        for row in media
    ]
    return compact_dict(published), published_media


def _load_item(client, item_id: str) -> dict:
    item = client.get_record("Item", item_id)
    if item is None:
        raise PublishError("not-found", f"No item {item_id}")
    return item


def publish_item(client, item_id: str, *, actor: str, now: str | None = None) -> PublishResult:
    now = now or utc_now_iso()
    item = _load_item(client, item_id)
    lineage_id = item.get("lineageId") or item_id
    published_id = published_item_id_for(lineage_id)
    metadata = _parse_json_object(item.get("metadata"))
    envelope = _derive_or_raise(metadata.get("frontMatterYaml"), item.get("bodyMarkus") or "")
    media = client.list_by_index("mediaAssetsByItemAndSortKey", item_id)
    _require_images_present(envelope, media)

    existing = client.get_record("PublishedItem", published_id)
    existing_hash = _parse_json_object((existing or {}).get("metadata")).get("sourceContentHash")
    already_projected = existing is not None and existing_hash == item.get("contentHash")
    if already_projected and item.get("status") == "published":
        return PublishResult(False, item_id, published_id, existing.get("versionNumber"))
    if already_projected:
        version_number = existing.get("versionNumber") or 1
    elif existing is not None:
        version_number = (existing.get("versionNumber") or 0) + 1
    else:
        version_number = 1

    projectable = {**item, "bodyIr": to_aws_json(envelope)}
    published, published_media = project_item_to_published(
        projectable,
        media,
        published_at=item.get("publishedAt") or now,
        version_number=version_number,
    )

    for row in published_media:
        client.upsert("PublishedMediaAsset", row)
    keep_ids = {row["id"] for row in published_media}
    deleted = []
    for row in client.list_by_index("publishedMediaAssetsByItemAndSortKey", published_id):
        if row["id"] not in keep_ids:
            client.delete_record("PublishedMediaAsset", row["id"])
            deleted.append(row["id"])
    client.upsert("PublishedItem", published)
    client.update_record(
        "Item",
        {
            "id": item_id,
            "status": "published",
            **_status_keys(item.get("type") or "", item.get("section"), "published"),
            "versionNumber": version_number,
            "publishedAt": published["publishedAt"],
            "versionState": "current",
            "versionCreatedAt": now,
            "versionCreatedBy": actor,
            "changeReason": "publish",
            "bodyIr": to_aws_json(envelope),
        },
    )
    return PublishResult(True, item_id, published_id, version_number, deleted)


def unpublish_item(client, item_id: str, *, actor: str, now: str | None = None) -> PublishResult:
    now = now or utc_now_iso()
    item = _load_item(client, item_id)
    lineage_id = item.get("lineageId") or item_id
    published_id = published_item_id_for(lineage_id)
    published = client.get_record("PublishedItem", published_id)
    media_rows = client.list_by_index("publishedMediaAssetsByItemAndSortKey", published_id)
    if published is None and not media_rows and item.get("status") != "published":
        return PublishResult(False, item_id, published_id, item.get("versionNumber"))

    deleted = []
    for row in media_rows:
        client.delete_record("PublishedMediaAsset", row["id"])
        deleted.append(row["id"])
    if published is not None:
        client.delete_record("PublishedItem", published_id)
    client.update_record(
        "Item",
        {
            "id": item_id,
            "status": "draft",
            **_status_keys(item.get("type") or "", item.get("section"), "draft"),
            "versionCreatedAt": now,
            "versionCreatedBy": actor,
            "changeReason": "unpublish",
        },
    )
    return PublishResult(True, item_id, published_id, item.get("versionNumber"), deleted)


class DryRunClient:
    """Passes reads through and records writes without performing them."""

    def __init__(self, client) -> None:
        self._client = client
        self.planned: list[dict[str, str]] = []

    def get_record(self, model_name: str, record_id: str):
        return self._client.get_record(model_name, record_id)

    def list_by_index(self, index_name: str, key_value: str, **kwargs):
        return self._client.list_by_index(index_name, key_value, **kwargs)

    def upsert(self, model_name: str, payload: dict) -> str:
        self.planned.append({"operation": "upsert", "model": model_name, "id": payload["id"]})
        return "planned"

    def update_record(self, model_name: str, payload: dict) -> None:
        self.planned.append({"operation": "update", "model": model_name, "id": payload["id"]})

    def delete_record(self, model_name: str, record_id: str) -> None:
        self.planned.append({"operation": "delete", "model": model_name, "id": record_id})
