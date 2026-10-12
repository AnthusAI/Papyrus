"""Read published content from the CMS as projection input."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from ..markus_export import EXPORTED_TYPES, item_output_path
from ..markus_renderer.build import slugify
from ..markus_renderer.derive import compose_source
from ..publishing import published_item_id_for
from .model import ItemChange, ItemSummary, ProjectedItem, SiteIndex
from .stored import PROJECTION_METADATA_KEY, projection_metadata


class ProjectionSourceError(Exception):
    pass


def _metadata_of(row: dict) -> dict:
    value = row.get("metadata")
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else {}
    return value if isinstance(value, dict) else {}


def _stored_projection(metadata: dict) -> dict:
    stored = metadata.get(PROJECTION_METADATA_KEY)
    if isinstance(stored, dict):
        return stored
    return projection_metadata(metadata.get("frontMatterYaml"))


def split_output_path(output_path: str) -> tuple[str | None, str]:
    path = PurePosixPath(output_path)
    section = path.parts[0] if len(path.parts) > 1 else None
    return section, slugify(path.stem)


def summary_from_row(row: dict, *, item_id: str | None = None) -> ItemSummary:
    metadata = _metadata_of(row)
    output_path = item_output_path(row)
    section, slug = split_output_path(output_path)
    stored = _stored_projection(metadata)
    return ItemSummary(
        item_id=item_id or row.get("sourceItemId") or row["id"],
        type=row.get("type") or "",
        section=section,
        slug=slug,
        output_path=output_path,
        version_number=row.get("versionNumber"),
        title=row.get("title"),
        page_title=stored.get("pageTitle"),
        front_matter=dict(stored.get("frontMatter") or {}),
        aliases=tuple(row.get("aliases") or ()),
        published_at=row.get("publishedAt"),
    )


def projected_item_from_row(row: dict) -> ProjectedItem:
    metadata = _metadata_of(row)
    return ProjectedItem(
        summary=summary_from_row(row),
        source_text=compose_source(metadata.get("frontMatterYaml"), row.get("bodyMarkus") or ""),
    )


def is_projectable(row: dict) -> bool:
    return row.get("status") == "published" and row.get("type") in EXPORTED_TYPES


def with_change(site: SiteIndex, change: ItemChange, load_item) -> SiteIndex:
    remaining = [summary for summary in site.items if summary.item_id != change.summary.item_id]
    if change.kind == "published":
        remaining.append(change.summary)
    ordered = tuple(sorted(remaining, key=lambda summary: summary.output_path))
    return SiteIndex(items=ordered, load_item=load_item)


class PublishedContentSource:
    """Published items of one site, read through an authoring (IAM) GraphQL client."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._loaded_rows: dict[str, dict] = {}

    def published_row(self, item_id: str) -> dict | None:
        item = self._client.get_record("Item", item_id)
        if item is None:
            return None
        lineage_id = item.get("lineageId") or item_id
        row = self._client.get_record("PublishedItem", published_item_id_for(lineage_id))
        if row is None or not is_projectable(row):
            return None
        return row

    def published_item(self, item_id: str) -> ProjectedItem | None:
        row = self.published_row(item_id)
        if row is None:
            return None
        self._loaded_rows[item_id] = row
        return projected_item_from_row(row)

    def item_summary(self, item_id: str) -> ItemSummary:
        item = self._client.get_record("Item", item_id)
        if item is None:
            raise ProjectionSourceError(f"No item {item_id}")
        return summary_from_row(item, item_id=item_id)

    def load_item(self, item_id: str) -> ProjectedItem:
        cached = self._loaded_rows.get(item_id)
        if cached is not None:
            return projected_item_from_row(cached)
        item = self.published_item(item_id)
        if item is None:
            raise ProjectionSourceError(f"Item {item_id} is not published")
        return item

    def site_index(self) -> SiteIndex:
        summaries = [
            summary_from_row(row)
            for row in self._client.list_published_item_summaries()
            if is_projectable(row)
        ]
        ordered = tuple(sorted(summaries, key=lambda summary: summary.output_path))
        return SiteIndex(items=ordered, load_item=self.load_item)

    def all_published_items(self) -> list[ProjectedItem]:
        rows = [row for row in self._client.list_records("PublishedItem") if is_projectable(row)]
        for row in rows:
            self._loaded_rows[row.get("sourceItemId") or row["id"]] = row
        items = [projected_item_from_row(row) for row in rows]
        return sorted(items, key=lambda item: item.summary.output_path)
