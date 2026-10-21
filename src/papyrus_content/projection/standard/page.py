"""What a hook is told about the page it is asked to render."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import ItemSummary
from . import components
from .config import StandardSettings
from .entries import StandardEntry
from .environment import SiteEnvironment
from .head import PageHead
from .hooks import HookSite

KINDS = ("item", "home", "listing", "tags", "tag", "custom", "showcase", "archive", "not_found")


@dataclass(frozen=True)
class ListingView:
    """One page of a listing: ``entries`` is this page's slice, ``featured`` its leading entries."""

    base: str
    label: str
    entries: tuple[StandardEntry, ...]
    all_entries: tuple[StandardEntry, ...]
    page: int
    pages: int
    featured: tuple[StandardEntry, ...] = ()
    section: str | None = None
    tag: str | None = None
    groups: tuple = ()          # ((key, label, entries), ...) when the section sets groupBy, newest group first
    group: str | None = None    # archive pages: the month or year this page lists
    archive_keys: tuple = ()    # archive pages: every key that has a page, newest first
    collection: str | None = None   # the id of the collection this page lists
    drafts: tuple[StandardEntry, ...] = ()   # page 1 of a collection with drafts: the draft entries its selection matches

    def url_for_page(self, number: int) -> str:
        prefix = f"/{self.base}" if self.base else ""
        return f"{prefix}/" if number == 1 else f"{prefix}/page/{number}/"


@dataclass(frozen=True)
class StandardPage:
    kind: str
    path: str
    title: str
    description: str
    settings: StandardSettings
    environment: SiteEnvironment
    head: PageHead
    entries: tuple[StandardEntry, ...]          # every listed entry of the site, newest first
    summaries: tuple[ItemSummary, ...]          # every published item, for hooks that build their own model
    entry: StandardEntry | None = None
    fragment: str = ""                          # item pages: the converted article, decorated
    listing: ListingView | None = None
    custom_id: str | None = None
    breadcrumbs: tuple[tuple[str, str], ...] = ()
    tags: dict = field(default_factory=dict)    # tag index: tag -> entries
    showcase: tuple = ()                        # showcase page: the ShowcaseSite records, sorted
    site: HookSite | None = None                # the site-wide view the item-level hooks also get
    page_actions: str = ""                      # item pages: the page-actions markup core would place (empty when off), for hooks that compose their own body
    components = components

    @property
    def site_name(self) -> str:
        return self.settings.identity.name

    @property
    def skip_link(self) -> str:
        return components.skip_link()

    def form(self, form_id: str) -> str:
        """The markup of a ``forms`` entry, for a hook composing its own page."""
        from .forms import render_form

        return render_form(next(spec for spec in self.settings.forms if spec.id == form_id))

    def render_nav(self) -> str:
        return components.nav(self.settings.nav, self.path, disclosure=self.settings.nav_disclosure)
