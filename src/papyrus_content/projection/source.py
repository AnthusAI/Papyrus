"""Read published content from the CMS as projection input."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from ..content_item_lifecycle import RETIRED_INTO_KEY, RETIRED_STAGE
from ..story_head_index import head_of
from ..markus_export import EXPORTED_TYPES, item_output_path
from ..markus_renderer.build import page_slug
from ..markus_renderer.derive import compose_source
from ..publishing import published_item_id_for
from .body_cache import BodyCache, version_fingerprint
from .model import ItemSummary, ProjectedItem, SiteIndex
from .story_stars import known_stars, stars_of_lineage
from .site_relations import SiteRelations, read_site_relations
from .stored import PROJECTION_METADATA_KEY, projection_metadata
from ..item_language import bare_group_id, item_language, item_language_group


class ProjectionSourceError(Exception):
    pass


@dataclass(frozen=True)
class Retirement:
    """A Story that ``papyrus stories retire`` took down: its lineage, the lineage its address redirects to, and a summary of each version that was served."""

    lineage_id: str
    to_lineage: str
    summaries: tuple[ItemSummary, ...]


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
        return section, "/".join(page_slug(segment) for segment in segments)
    return section, page_slug(path.stem)


def summary_from_row(row: dict, *, item_id: str | None = None, tenant_id: str | None = None) -> ItemSummary:
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
        lineage_id=row.get("itemLineageId") or row.get("lineageId") or None,
        language=row.get("language") or None,
        language_group_id=bare_group_id(row.get("languageGroupId"), tenant_id),
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
    return dataclasses.replace(site, items=ordered)


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

    @property
    def _tenant_id(self) -> str | None:
        return getattr(self._client, "tenant_id", None)

    def _summary(self, row: dict, *, item_id: str | None = None) -> ItemSummary:
        """A summary of a published row (or an Item row): every row a CMS source reads carries its language and group (``papyrus stories languages``
        writes them on rows older than the fields); a row without them is refused, never read as the primary language."""
        item_language(row), item_language_group(row)
        return summary_from_row(row, item_id=item_id, tenant_id=self._tenant_id)

    def serving_languages(self):
        """The site's languages as served (``language_serving.serving_languages``), from the editorial check settings: one read."""
        from ..editorial_checks import settings_from_row
        from ..language_serving import serving_languages

        return serving_languages(settings_from_row(self._client.get_record("EditorialCheckSettings", "settings")))

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
        item = self._projected(row)
        if self.body_cache is not None:
            self.body_cache.put(item.summary.item_id, version_fingerprint(row), item.source_text)
        return item

    def _projected(self, row: dict) -> ProjectedItem:
        return ProjectedItem(summary=self._summary(row), source_text=projected_item_from_row(row).source_text)

    def retirement(self, item_id: str) -> Retirement | None:
        """Where a retired Story's address goes (``papyrus stories retire``), or None when the Story is not retired.

        Reads the Story's head row: ``stage`` is ``retired`` and ``metadata.retiredInto`` names the lineage it redirects to. The summaries are
        those of every version the command recorded as served (``versionIds``) and of the head row, so the addresses a Story
        had before a rename or a change of type redirect too.
        """
        item = self._client.get_record("Item", item_id)
        if item is None:
            return None
        lineage_id = item.get("lineageId") or item_id
        rows = self._client.list_by_index("itemsByLineageAndVersion", lineage_id) or [item]
        head = head_of(rows) or item
        info = _metadata_of(head).get(RETIRED_INTO_KEY)
        if head.get("stage") != RETIRED_STAGE or not isinstance(info, dict) or not info.get("toLineageId"):
            return None
        recorded = set(info.get("versionIds") or ())
        served = [row for row in rows if row["id"] in recorded or row["id"] in (head["id"], item_id)]
        distinct = {(row.get("type"), item_output_path(row), tuple(row.get("aliases") or ())): row for row in served}
        summaries = tuple(self._summary(row, item_id=item_id) for row in distinct.values())
        return Retirement(lineage_id=lineage_id, to_lineage=str(info["toLineageId"]), summaries=summaries)

    def item_summary(self, item_id: str) -> ItemSummary:
        item = self._client.get_record("Item", item_id)
        if item is None:
            raise ProjectionSourceError(f"No item {item_id}")
        return self._summary(item, item_id=item_id)

    def load_item(self, item_id: str) -> ProjectedItem:
        """An item with its body, for a page that needs another Story's text (``llms-full.txt``, a section's introduction, the item-pages follow-up).

        In order: a row this source already read; the body cache, when the listing data says the published version is the one kept; AppSync."""
        cached = self._loaded_rows.get(item_id)
        indexed = self._indexed.get(item_id)
        if cached is not None and indexed is not None and version_fingerprint(cached) != indexed[1]:
            cached = None   # read before a later publish of this item: the listing data names a newer version
        if cached is not None:
            return self._projected(cached)
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
                summary = self._summary(row)
                indexed[summary.item_id] = (summary, version_fingerprint(row))
        self._indexed = indexed
        ordered = tuple(sorted((summary for summary, _fingerprint in indexed.values()), key=lambda summary: summary.output_path))
        return SiteIndex(items=ordered, load_item=self.load_item, story_stars=self.story_stars(ordered), relations=self.site_relations(ordered))

    def story_stars(self, summaries) -> dict[str, int]:
        """``{lineage id: stars}`` of the rated Stories among ``summaries``: one request for the stored ratings, and one more for each Story not seen before.

        Stars are private and are read here, at projection time. They go to the projector inside the :class:`SiteIndex` and nowhere else.
        """
        if self.star_store is None:
            return {}
        return known_stars(self.star_store, (summary.lineage_id for summary in summaries), lambda lineage: stars_of_lineage(self._client, lineage))

    def site_relations(self, summaries) -> SiteRelations:
        """The ``based_on`` Reference addresses and concept links of the published Stories (``site_relations.py``): indexed reads, about ten requests for a site of 120 Stories."""
        summaries = tuple(summaries)
        return read_site_relations(
            self._client,
            [(summary.item_id, summary.lineage_id, summary.published_at) for summary in summaries],
            [str(summary.front_matter["entityKey"]) for summary in summaries if isinstance(summary.front_matter.get("entityKey"), str)],
        )

    def all_published_items(self) -> list[ProjectedItem]:
        """Every published item with its body: a whole-table read, for the whole-site render. It also fills the body cache."""
        rows = [row for row in self._client.list_records("PublishedItem") if is_projectable(row, self.extra_types)]
        for row in rows:
            self._loaded_rows[row.get("sourceItemId") or row["id"]] = row
        items = [self._projected(row) for row in rows]
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
