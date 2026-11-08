"""Data the projection reads and the contract between the engine and a site projector."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ItemSummary:
    """What listings and navigation need to know about one published item; no body."""

    item_id: str
    type: str
    section: str | None
    slug: str
    output_path: str
    version_number: int | None
    title: str | None
    page_title: str | None
    front_matter: dict
    aliases: tuple[str, ...]
    published_at: str | None
    #: The Story's lineage, which its private star rating is keyed by (``item_stars.py``). Never printed and not part of any fingerprint.
    lineage_id: str | None = None


@dataclass(frozen=True)
class ProjectedItem:
    summary: ItemSummary
    source_text: str


def site_signature(site: "SiteIndex") -> frozenset[tuple[str, int | None]]:
    """Which published versions a site index was read at; used to notice a concurrent publish."""
    return frozenset((summary.item_id, summary.version_number) for summary in site.items)


@dataclass(frozen=True)
class SiteIndex:
    """Every published, projectable item of the site, ordered by output path."""

    items: tuple[ItemSummary, ...]
    load_item: Callable[[str], ProjectedItem]
    #: ``{lineage id: stars (1 to 5)}`` of the rated Stories, read when the index was. Private: listings order by it and nothing prints it.
    story_stars: Mapping[str, int] = field(default_factory=dict)


@dataclass
class ProjectionReport:
    item_paths: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    redirects_written: int = 0
    redirects_deleted: int = 0
    invalidated: list[str] = field(default_factory=list)
    unpurged: list[str] = field(default_factory=list)
    #: Targeted mode only: request paths not purged because the call was over ``maxInvalidationPaths``.
    invalidation_capped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    follow_up_item_pages: bool = False
    rounds: int = 1
    skipped: list[str] = field(default_factory=list)
    #: Items whose content could not be rendered (a deploy-time render only): ``{itemId, slug, error}``. Their pages are left as they are.
    unrenderable: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "written": len(self.written),
            "deleted": len(self.deleted),
            "redirectsWritten": self.redirects_written,
            "redirectsDeleted": self.redirects_deleted,
            "invalidated": len(self.invalidated),
            "unpurged": len(self.unpurged),
            "invalidationCapped": len(self.invalidation_capped),
            "errors": list(self.errors),
            "followUpItemPages": self.follow_up_item_pages,
            "rounds": self.rounds,
            "unrenderable": list(self.unrenderable),
        }
