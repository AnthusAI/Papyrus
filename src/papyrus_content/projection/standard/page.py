"""What a hook is told about the page it is asked to render."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..model import ItemSummary
from . import components
from .config import SectionConfig, StandardSettings
from .entries import StandardEntry
from .environment import SiteEnvironment
from .head import PageHead
from .hooks import HookSite
from .page_ledger import PageLedger

KINDS = ("item", "home", "listing", "tags", "tag", "custom", "showcase", "archive", "not_found", "newsletter_page", "plugin_page", "thread")


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
    root: str = ""              # the base path with a trailing slash ("posts/"), or "" for a site at the root

    def url_for_page(self, number: int) -> str:
        prefix = "/" + self.root + (f"{self.base}/" if self.base else "")
        return prefix if number == 1 else f"{prefix}page/{number}/"


@dataclass(frozen=True)
class SectionTab:
    """One entry of the section tabs: the section's label and address, and whether it is the page being shown."""

    label: str
    href: str
    current: bool = False


@dataclass(frozen=True)
class SectionIndexView:
    """Page 1 of a section's listing as a front page: tabs, the section's own words, a lead Story, the latest entries and a Reference grid."""

    section: SectionConfig
    listing: ListingView
    tabs: tuple[SectionTab, ...]
    lead: StandardEntry | None
    latest: tuple[StandardEntry, ...]
    references_html: str = ""
    references_selection: str | None = None
    references_count: int = 0


@dataclass(frozen=True)
class HomeSectionBlock:
    """One block of the home of sections: a section, the address of its index page and its newest entries."""

    section: SectionConfig
    href: str
    entries: tuple[StandardEntry, ...]


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
    wiki_stamp: str = ""                        # wiki pages: the review stamp and any superseded notice, placed above the text
    wiki_footer: str = ""                       # wiki pages: "Updated", the data link and the suggest-an-edit form, placed below the text
    section_index: SectionIndexView | None = None    # section front pages: what the generated layout shows (empty fragment unless the index is authored)
    home_sections: tuple[HomeSectionBlock, ...] = ()  # the home of sections: one block per section
    thread: Mapping | None = None               # thread pages: the per-thread document the snapshot wrote
    thread_reference: Mapping | None = None     # thread pages: the anchor Reference's record when the snapshot holds it
    ledger: PageLedger = field(default_factory=PageLedger)   # what this page render has placed so far; shared by every include on it
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
