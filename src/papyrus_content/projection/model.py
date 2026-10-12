"""Data the projection reads and the contract between the engine and a site projector."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal


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


@dataclass(frozen=True)
class ProjectedItem:
    summary: ItemSummary
    source_text: str


@dataclass(frozen=True)
class SiteIndex:
    """Every published, projectable item of the site, ordered by output path."""

    items: tuple[ItemSummary, ...]
    load_item: Callable[[str], ProjectedItem]


ChangeKind = Literal["published", "unpublished"]


@dataclass(frozen=True)
class ItemChange:
    kind: ChangeKind
    summary: ItemSummary


@dataclass
class ProjectionReport:
    item_paths: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    redirects_written: int = 0
    redirects_deleted: int = 0
    invalidated: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

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
            "errors": list(self.errors),
        }
