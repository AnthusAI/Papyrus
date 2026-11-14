"""What a hook is told about the page it is asked to render."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ..model import ItemSummary
from . import components
from .config import SectionConfig, StandardSettings
from .entries import StandardEntry
from .environment import SiteEnvironment
from .head import PageHead
from .hooks import HookSite
from .page_ledger import PageLedger

def _same_site_page(path: str) -> bool:
    """A path of a page of this site in the primary language (not a file, not under a language prefix the link map would know)."""
    return path.startswith("/") and not path.startswith("//") and not path.rsplit("/", 1)[-1].count(".")


KINDS = ("item", "home", "listing", "tags", "tag", "custom", "showcase", "archive", "not_found", "newsletter_page", "notifications_page", "plugin_page", "thread", "reference_list")


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
    page_actions: str = ""                      # the page-actions markup core would place (empty when off or when the page has no twin), for hooks that compose their own body
    wiki_stamp: str = ""                        # wiki pages: the review stamp and any superseded notice, placed above the text
    wiki_footer: str = ""                       # wiki pages: "Updated", the data link and the suggest-an-edit form, placed below the text
    section_index: SectionIndexView | None = None    # section front pages: what the generated layout shows (empty fragment unless the index is authored)
    home_sections: tuple[HomeSectionBlock, ...] = ()  # the home of sections: one block per section
    concept_links: tuple[Mapping, ...] = ()     # item pages: the public concept pages the Story's relations reach, most used first: {slug, name, href, stories}
    related_references: tuple[Mapping, ...] = ()   # item pages: the accepted References the Story points a reader to (see_also, newest linked first): {referenceId, lineageId, title, url, host, image, summary, medium, acceptedAt, note}
    related_stories: tuple[Mapping, ...] = ()   # item pages: the published Stories this one is related to (related_to, either direction), newest first: {itemId, type, section, title, url, image, summary, date}
    thread: Mapping | None = None               # thread pages: the per-thread document the snapshot wrote
    thread_reference: Mapping | None = None     # thread pages: the anchor Reference's record when the snapshot holds it
    ledger: PageLedger = field(default_factory=PageLedger)   # what this page render has placed so far; shared by every include on it
    ranker: Callable | None = field(default=None, repr=False, compare=False)   # the projector's Story ranking; ``ranked`` calls it
    # Languages (docs/multilingual-serving.md). ``language`` is the page's BCP 47 tag (also ``<html lang>``); ``strings`` the site's interface strings in it.
    # On a site that serves several languages: ``primary_language``; ``alternates``, the page in every public language it exists in, itself included,
    # ``{tag, name, url}`` with the primary first (empty when it exists in one language); ``link_map``, ``{page path: {tag: path}}`` for every page that
    # exists in more than one language (see ``link_in_language``).
    language: str = ""
    strings: Mapping[str, str] = field(default_factory=dict)
    primary_language: str = ""
    alternates: tuple[Mapping[str, str], ...] = ()
    link_map: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    components = components

    def ranked(self, entries, bucket: str | None = None) -> list[StandardEntry]:
        """``entries`` (newest first, as ``page.entries`` is) in the Story ranking the home page and listings use: the newest rolling bucket first, the
        editors' private stars inside each bucket (``story_order.py``). ``bucket`` is ``day``, ``week`` or ``none`` and defaults to the site's ``listings.bucket``.
        Nothing rated, or a page built without a projector: the list is unchanged. A page that calls it is rendered again when a rating moves the order."""
        return list(entries) if self.ranker is None else self.ranker(entries, bucket)

    def link_in_language(self, path: str) -> tuple[str, bool]:
        """Where a link to ``path`` (a page of this site, in any language) goes from this page: ``(path, leaves_the_language)``. A page that exists in this
        page's language is linked there; one that does not keeps its own address and ``leaves_the_language`` is True, so the site marks the link. The
        translator never chooses the target: the published language groups do."""
        found = self.link_map.get(path)
        if found is None:
            if not self.primary_language or self.language == self.primary_language or not _same_site_page(path):
                return path, False
            own_root = "/" + (f"{self.settings.base_path}/" if self.settings.base_path else "") + f"{self.settings.language_prefix}/"
            return path, not path.startswith(own_root)   # a page of this language that exists in no other stays; any other page is in another language
        if self.language in found:
            return found[self.language], False
        return path, True

    @property
    def site_name(self) -> str:
        return self.settings.identity.name

    @property
    def skip_link(self) -> str:
        return components.skip_link()

    def article_actions(self) -> str:
        """The shared page actions for this page (View as Markdown, Copy, Open in ..., and with ``pageActions.display: "icons"``
        X, Reddit and Share), exactly as core would place them; empty when the page is not eligible. A hook that returns its own
        ``main`` or ``page_body`` calls this where the actions belong; the script and stylesheet load because the page has actions.
        On the home page, listings, tag, archive and paged list pages it returns the markup only when the site sets
        ``pageActions.everywhere``; each page's own title, canonical address and Markdown twin are used."""
        return self.page_actions

    def form(self, form_id: str) -> str:
        """The markup of a ``forms`` entry, for a hook composing its own page."""
        from .forms import render_form

        return render_form(next(spec for spec in self.settings.forms if spec.id == form_id))

    def render_nav(self) -> str:
        return components.nav(self.settings.nav, self.path, disclosure=self.settings.nav_disclosure)
