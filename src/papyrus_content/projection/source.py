"""Read published content from the CMS as projection input."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from ..markus_export import EXPORTED_TYPES, item_output_path
from ..markus_renderer.build import slugify
from ..markus_renderer.derive import compose_source
from ..publishing import published_item_id_for
from .body_cache import BodyCache, version_fingerprint
from .model import ItemSummary, ProjectedItem, SiteIndex
from .story_stars import known_stars, stars_of_lineage
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


def split_output_path(output_path: str, *, nested: bool = False) -> tuple[str | None, str]:
    """The section (first directory) and slug of an item path.

    The slug is the file stem. With ``nested`` it is the whole path under the section, each segment slugified and
    joined by ``/``, so ``examples/intro/first.md`` is the ``intro/first`` item of ``examples`` (page ``/examples/intro/first/``).
    """
    path = PurePosixPath(output_path)
    section = path.parts[0] if len(path.parts) > 1 else None
    if nested and section is not None:
        segments = [*path.parts[1:-1], path.stem]
        return section, "/".join(slugify(segment) for segment in segments)
    return section, slugify(path.stem)


def summary_from_row(row: dict, *, item_id: str | None = None) -> ItemSummary:
    metadata = _metadata_of(row)
    output_path = item_output_path(row)
    section, slug = split_output_path(output_path, nested=bool(row.get("nestedSlug")))
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
        lineage_id=row.get("itemLineageId") or None,
    )


def projected_item_from_row(row: dict) -> ProjectedItem:
    metadata = _metadata_of(row)
    return ProjectedItem(
        summary=summary_from_row(row),
        source_text=compose_source(metadata.get("frontMatterYaml"), row.get("bodyMarkus") or ""),
    )


def is_projectable(row: dict, extra_types: tuple[str, ...] = ()) -> bool:
    """A published row of a projected type: ``article`` and ``page``, plus the types a site lists (``listings.types`` in projection.json)."""
    return row.get("status") == "published" and (row.get("type") in EXPORTED_TYPES or row.get("type") in extra_types)


def replace_item(site: SiteIndex, item_id: str, summary: ItemSummary | None) -> SiteIndex:
    """The site with one item swapped for ``summary``, or without it when ``summary`` is None."""
    remaining = [existing for existing in site.items if existing.item_id != item_id]
    if summary is not None:
        remaining.append(summary)
    ordered = tuple(sorted(remaining, key=lambda existing: existing.output_path))
    return SiteIndex(items=ordered, load_item=site.load_item, story_stars=site.story_stars)


class PublishedContentSource:
    """Published items of one site, read through an authoring (IAM) GraphQL client."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._loaded_rows: dict[str, dict] = {}
        #: Item types beyond ``article`` and ``page`` that are projected. The projection context fills it from the projector's settings.
        self.extra_types: tuple[str, ...] = ()
        #: Where the editors' private Story ratings are kept (``story_stars.py``). Without one, listings keep their newest-first order.
        self.star_store: Any = None
        #: The kept source texts of published versions (``body_cache.py``). The projection context sets it when it keeps state in the store.
        self.body_cache: BodyCache | None = None
        #: ``{item id: (summary, version fingerprint)}`` from the last :meth:`site_index`, so a body can be taken from the cache without a read.
        self._indexed: dict[str, tuple[ItemSummary, str | None]] = {}

    def published_row(self, item_id: str) -> dict | None:
        item = self._client.get_record("Item", item_id)
        if item is None:
            return None
        lineage_id = item.get("lineageId") or item_id
        row = self._client.get_record("PublishedItem", published_item_id_for(lineage_id))
        if row is None or not is_projectable(row, self.extra_types):
            return None
        return row

    def lineage_id_of(self, item_id: str) -> str:
        item = self._client.get_record("Item", item_id)
        return (item.get("lineageId") if item else None) or item_id

    def published_item(self, item_id: str) -> ProjectedItem | None:
        row = self.published_row(item_id)
        if row is None:
            return None
        self._loaded_rows[item_id] = row
        item = projected_item_from_row(row)
        if self.body_cache is not None:
            self.body_cache.put(item.summary.item_id, version_fingerprint(row), item.source_text)
        return item

    def item_summary(self, item_id: str) -> ItemSummary:
        item = self._client.get_record("Item", item_id)
        if item is None:
            raise ProjectionSourceError(f"No item {item_id}")
        return summary_from_row(item, item_id=item_id)

    def load_item(self, item_id: str) -> ProjectedItem:
        """An item with its body, for a page that needs another Story's text (``llms-full.txt``, a section's introduction, the item-pages follow-up).

        In order: a row this source already read; the body cache, when the listing data says the published version is the one kept; AppSync."""
        cached = self._loaded_rows.get(item_id)
        indexed = self._indexed.get(item_id)
        if cached is not None and indexed is not None and version_fingerprint(cached) != indexed[1]:
            cached = None   # read before a later publish of this item: the listing data names a newer version
        if cached is not None:
            return projected_item_from_row(cached)
        if indexed is not None and self.body_cache is not None:
            source_text = self.body_cache.get(item_id, indexed[1])
            if source_text is not None:
                return ProjectedItem(summary=indexed[0], source_text=source_text)
        item = self.published_item(item_id)
        if item is None:
            raise ProjectionSourceError(f"Item {item_id} is not published")
        return item

    def site_index(self) -> SiteIndex:
        indexed: dict[str, tuple[ItemSummary, str | None]] = {}
        for row in self._client.list_published_item_summaries():
            if is_projectable(row, self.extra_types):
                summary = summary_from_row(row)
                indexed[summary.item_id] = (summary, version_fingerprint(row))
        self._indexed = indexed
        ordered = tuple(sorted((summary for summary, _fingerprint in indexed.values()), key=lambda summary: summary.output_path))
        return SiteIndex(items=ordered, load_item=self.load_item, story_stars=self.story_stars(ordered))

    def story_stars(self, summaries) -> dict[str, int]:
        """``{lineage id: stars}`` of the rated Stories among ``summaries``: one request for the stored ratings, and one more for each Story not seen before.

        Stars are private and are read here, at projection time. They go to the projector inside the :class:`SiteIndex` and nowhere else.
        """
        if self.star_store is None:
            return {}
        return known_stars(self.star_store, (summary.lineage_id for summary in summaries), lambda lineage: stars_of_lineage(self._client, lineage))

    def all_published_items(self) -> list[ProjectedItem]:
        """Every published item with its body: a whole-table read, for the whole-site render. It also fills the body cache."""
        rows = [row for row in self._client.list_records("PublishedItem") if is_projectable(row, self.extra_types)]
        for row in rows:
            self._loaded_rows[row.get("sourceItemId") or row["id"]] = row
        items = [projected_item_from_row(row) for row in rows]
        if self.body_cache is not None:
            for row, item in zip(rows, items):
                self.body_cache.put(item.summary.item_id, version_fingerprint(row), item.source_text)
            self.body_cache.retain(item.summary.item_id for item in items)
        return sorted(items, key=lambda item: item.summary.output_path)

    def indexed_items(self) -> tuple[SiteIndex, list[ProjectedItem]]:
        """The site index and every item with its body, from the listing data and the body cache: the work of
        :meth:`all_published_items` for the item-pages follow-up, at the cost of the listing read plus one read per body not kept."""
        site = self.site_index()
        items = [self.load_item(summary.item_id) for summary in site.items]
        if self.body_cache is not None:
            self.body_cache.retain(summary.item_id for summary in site.items)
        return site, items
