"""Language editions: one standard projection per public language, under that language's URL prefix (docs/multilingual-serving.md).

A site that serves more than one language is projected as one **edition** per public language. The primary edition is the site as it always was
(the primary language at the root, "primary at root"); every other edition is the same front end over that language's published Stories only, with
its pages under ``/<prefix>/`` and its settings' words taken from the language's interface strings. So a Spanish section page lists only Spanish
Stories, the Spanish home lists the newest Spanish Stories, and an English page never lists a translation.

What joins the editions is the **language group**: the published Stories that are one Story in several languages (``ItemSummary.language_group_id``,
the primary Story's lineage). :class:`LanguageView` is read once per version of the site and gives every page:

* ``alternates``: the page in every public language it exists in, itself included, ``{tag, name, url}``, primary first; a page that exists in one
  language only has none. Only published localizations appear, and only while the primary Story is published (its group facts come from it).
* the head's ``hreflang`` links with ``x-default`` (the primary language's page), ``og:locale`` and JSON-LD ``inLanguage``;
* ``link_map``: for a page path in any language, the same page in each language, so a site keeps a reader inside their language and marks a link that
  must leave it. The translator never chooses a link target; this data does.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ...item_language import is_localization_of
from ...url_paths import encoded_path
from ..model import ItemSummary
from .config import NavLink, StandardSettings
from .interface_strings import FEEDS_TITLE_KEY, SEO_IMAGE_ALT_KEY, SEO_IMAGE_KEY, LANGUAGE_NAME_KEY, SITE_NAME_KEY, SITE_PUBLISHER_KEY, SITE_SHORT_NAME_KEY
from .wiki import DEFAULT_WIKI_SECTION


def hreflang_value(tag: str) -> str:
    """The value of ``hreflang`` for a language tag. Search engines accept a language, an optional script and an optional two-letter country region (``es``, ``zh-Hans``,
    ``pt-BR``) and refuse a UN M.49 region such as ``es-419``, so the numeric region is left off the ``hreflang`` of a page (and of a link to it). ``<html lang>``,
    ``og:locale`` and JSON-LD ``inLanguage`` keep the full tag: they are for readers and assistive technology, not for search engines."""
    return re.sub(r"-\d{3}\b", "", tag)


@dataclass(frozen=True)
class Alternate:
    tag: str
    name: str
    url: str
    #: False for an edition's listing that has nothing in it yet: the switcher offers it, the head's ``hreflang`` does not (it is ``noindex``).
    indexed: bool = True

    def as_dict(self) -> dict[str, str]:
        return {"tag": self.tag, "name": self.name, "url": self.url, "hreflang": hreflang_value(self.tag)}


@dataclass(frozen=True)
class LanguageView:
    """The language groups of one version of the site, as every edition reads them."""

    primary: str
    public: tuple[str, ...]
    names: Mapping[str, str]
    #: ``{group id: {tag: summary}}``: the published members of each group in a public language; a group appears only while its primary is published.
    groups: Mapping[str, Mapping[str, ItemSummary]]
    #: ``{tag: url of a summary in that language's edition}``
    item_url: Callable[[str, ItemSummary], str | None] = field(repr=False, compare=False, default=lambda tag, summary: None)
    #: ``{site-relative listing base: (tag, ...)}``: which editions have the listing page at that base ("" is the home)
    listing_bases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: ``{site-relative listing base: {tag: that edition's base}}``: where a listing lives in a language whose base differs (the Concepts: ``wiki`` in the
    #: primary language, ``concepts`` in every other); an edition not named here uses the base itself
    listing_paths: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    #: ``{tag: root}``: each edition's page root (``""``, ``es/``)
    roots: Mapping[str, str] = field(default_factory=dict)
    #: ``{site-relative listing base: (tag, ...)}``: the editions whose listing at that base has no Story yet (the page exists, with a notice)
    empty_bases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def multilingual(self) -> bool:
        return len(self.public) > 1

    def member_of(self, summary: ItemSummary) -> Mapping[str, ItemSummary]:
        return self.groups.get(summary.language_group_id or "", {})

    def item_alternates(self, summary: ItemSummary) -> tuple[Alternate, ...]:
        members = self.member_of(summary)
        if len(members) < 2:
            return ()
        found = []
        for tag in self.public:
            member = members.get(tag)
            url = self.item_url(tag, member) if member is not None else None
            if url:
                found.append(Alternate(tag, self.names[tag], url))
        return tuple(found) if len(found) > 1 else ()

    def original_of(self, summary: ItemSummary) -> Alternate | None:
        """The primary-language page a served translation is a translation of; None for any page that is not one (a Story of its own, in any language)."""
        if not is_localization_of(summary.lineage_id, summary.language_group_id, summary.language):
            return None
        original = self.member_of(summary).get(self.primary)
        url = self.item_url(self.primary, original) if original is not None else None
        return Alternate(self.primary, self.names[self.primary], url) if url else None

    def listing_alternates(self, base: str) -> tuple[Alternate, ...]:
        tags = self.listing_bases.get(base, ())
        if len(tags) < 2:
            return ()
        empty = self.empty_bases.get(base, ())
        paths = self.listing_paths.get(base, {})
        return tuple(
            Alternate(tag, self.names[tag], encoded_path("/" + self.roots[tag] + (f"{paths.get(tag, base)}/" if base else "")), tag not in empty)
            for tag in self.public if tag in tags
        )

    def is_empty_listing(self, base: str, tag: str) -> bool:
        return tag in self.empty_bases.get(base, ())

    def group_digest(self, summary: ItemSummary) -> list:
        """What a page of ``summary`` depends on beyond its own content: the URLs of its group's other published languages."""
        return [[alternate.tag, alternate.url] for alternate in self.item_alternates(summary)]

    @functools.cached_property
    def links(self) -> dict[str, dict[str, str]]:
        """:meth:`link_map`, built once per version of the site."""
        return self.link_map()

    def link_map(self) -> dict[str, dict[str, str]]:
        """``{path of a page in any public language: {tag: path of that page in the tag's language}}``, for Story pages and listings that exist in
        more than one language. A page in one language only is not in it: a link to it stays where it is, and the site may mark it."""
        found: dict[str, dict[str, str]] = {}
        for members in self.groups.values():
            urls = {tag: url for tag in self.public if (member := members.get(tag)) is not None and (url := self.item_url(tag, member))}
            if len(urls) > 1:
                for url in urls.values():
                    found[url] = urls
        for base in self.listing_bases:
            urls = {alternate.tag: alternate.url for alternate in self.listing_alternates(base)}
            for url in urls.values():
                found[url] = urls
        return found

    def digest_input(self) -> list:
        return [self.primary, list(self.public), sorted(self.names.items()), sorted((url, sorted(urls.items())) for url, urls in self.links.items()), sorted((base, list(tags)) for base, tags in self.empty_bases.items()), sorted((base, sorted(paths.items())) for base, paths in self.listing_paths.items())]


def language_groups(summaries, public: tuple[str, ...], primary: str) -> dict[str, dict[str, ItemSummary]]:
    """``{group id: {tag: summary}}`` of the published summaries in a public language; groups whose primary-language member is not published are left
    out (a localization is served only beside its published original)."""
    groups: dict[str, dict[str, ItemSummary]] = {}
    for summary in summaries:
        if summary.language in public and summary.language_group_id:
            groups.setdefault(summary.language_group_id, {})[summary.language] = summary
    return {group: members for group, members in groups.items() if primary in members}


def localized(text: str, strings: Mapping[str, str], key: str) -> str:
    """The language's text for a setting that has one; a setting the primary leaves empty stays empty (the completeness check guarantees the rest)."""
    return strings[key] if text else text


def translate_path(path: str, segments: Mapping[str, str]) -> str:
    """An English edition path (``articles``, ``security/videos``, with or without slashes at the ends) with each segment replaced by its translation in
    the language's table (``languages.segments``); a segment the table does not list keeps its English form. Applies to the segments of a section, type or
    authored page path, never to a Story's slug."""
    return "/".join(segments.get(part, part) for part in path.split("/"))


def check_segment_collisions(standard: StandardSettings, tag: str, segments: Mapping[str, str]) -> None:
    """Refuses a table under which two different top-level paths of the edition (a section's base, an authored page's path) would be served at one address,
    for example ``posts`` translated to ``articles`` while ``articles`` stays English."""
    owners: dict[str, str] = {}
    paths = [edition_base(standard, section) for section in standard.sections if section.base] + [custom.path for custom in standard.pages if custom.path]
    for path in paths:
        english = path.split("/")[0]
        top = segments.get(english, english)
        if owners.setdefault(top, english) != english:
            raise ValueError(f"languages.segments.{tag}: {owners[top]} and {english} would both be served at /{top}/.")


def localized_source(source: str | None, tag: str) -> str | None:
    """The file of an authored page in a language: ``pages/findings.md`` is ``pages/findings.es-419.md`` in es-419."""
    if not source:
        return None
    stem, dot, suffix = source.rpartition(".")
    return f"{stem}.{tag}.{suffix}" if dot else f"{source}.{tag}"


def edition_pages(standard: StandardSettings, tag: str, strings: Mapping[str, str], static_directory, segments: Mapping[str, str] | None = None) -> tuple:
    """The authored pages a language renders: those that opt in (``languages: "localize"``) and have a file in the language. Each is the page with its title and
    description from ``page.<id>.title`` and ``page.<id>.description`` (or the page's ``titleKey`` and ``descriptionKey``, as a section page names its section's label) and its source the language's file. A page without a file, or without a title in the language, is not rendered in the language
    (no fallback to the primary's text), so it is no alternate and a site's links to it stay on the primary page."""
    found = []
    for custom in standard.pages:
        source = localized_source(custom.source, tag) if custom.languages == "localize" else None
        title = strings.get(custom.title_key or f"page.{custom.id}.title")
        if source and title and static_directory is not None and (static_directory / source).is_file():
            description = strings.get(custom.description_key or f"page.{custom.id}.description", "") if custom.description else ""
            found.append(dataclasses.replace(custom, source=source, path=translate_path(custom.path, segments or {}), title=title, description=description, languages="localize"))
    return tuple(found)


def site_names(standard: StandardSettings, primary: str, strings: Mapping[str, Mapping[str, str]], tags: tuple[str, ...]) -> dict[str, str]:
    """``{tag: the publication's name in that language}`` for the primary language (``site.name`` of projection.json) and the given editions (their ``site.name``)."""
    return {primary: standard.identity.name, **{tag: strings[tag][SITE_NAME_KEY] for tag in tags}}


def alternate_names_of(names: Mapping[str, str], own: str) -> tuple[str, ...]:
    """The names a language's pages list as ``alternateName``: every other language's name, the primary's first, never the page's own name twice."""
    return tuple(dict.fromkeys(name for name in names.values() if name != own))


def edition_settings(standard: StandardSettings, tag: str, prefix: str, strings: Mapping[str, str], segments: Mapping[str, str] | None = None,
                     names: Mapping[str, str] | None = None, static_directory=None) -> StandardSettings:
    """The settings of the ``tag`` edition: the site's settings, its words in the language, its pages under the prefix, and only what an edition renders.

    An edition renders the language's Story pages, its home and section listings (with paging and archives), its feeds and sitemap. It renders no
    authored page, collection, tag page, showcase, Reference grid, plugin page, form, page action or ``llms.txt``: their words are the primary
    language's, and an English page inside a Spanish edition is what the rule forbids. Navigation keeps the home and the section listings, named in
    the language; every other link leaves the edition and is dropped."""
    segments = segments or {}
    check_segment_collisions(standard, tag, segments)
    name = strings[SITE_NAME_KEY]
    identity = dataclasses.replace(
        standard.identity, language=tag, date_locale=tag,
        name=name,
        short_name=localized(standard.identity.short_name, strings, SITE_SHORT_NAME_KEY),
        publisher=localized(standard.identity.publisher, strings, SITE_PUBLISHER_KEY),
        alternate_names=alternate_names_of(names or {}, name),
        description=localized(standard.identity.description, strings, "site.description"),
        tagline=localized(standard.identity.tagline, strings, "site.tagline"),
        notice_label=localized(standard.identity.notice_label, strings, "notice.label"),
        notice_text=localized(standard.identity.notice_text, strings, "notice.text"),
    )
    sections = tuple(
        dataclasses.replace(
            section,
            base=translate_path(edition_base(standard, section), segments),
            label=strings[f"section.{section.name}.label"] if section.listing and section.listing_page else section.label,
            description=localized(section.description, strings, f"section.{section.name}.description") if section.listing and section.listing_page else section.description,
            index=None,   # a section front page carries a Reference grid and authored words
        )
        for section in standard.sections
    )
    pages = edition_pages(standard, tag, strings, static_directory, segments)
    home_page = dataclasses.replace(standard.home_page, forum=None) if pages and standard.home_page is not None else None   # the pages' References and threads; no thread pages of its own
    hrefs = edition_nav_hrefs(standard)
    moved = {f"/{section.base}/": f"/{translate_path(edition_base(standard, section), segments)}/" for section in standard.sections if section.base}
    #: ``(the address the edition used before its segments were translated, the address now)`` for each section: the edge redirects the first to the second.
    moved_paths = tuple((english, now) for section in standard.sections if section.base
                        for english, now in [(edition_base(standard, section), translate_path(edition_base(standard, section), segments))] if english != now) + tuple(
        (original.path, custom.path) for original in standard.pages for custom in pages if original.id == custom.id and original.path != custom.path)
    nav = tuple(NavLink(label=strings[f"nav.{link.href}.label"], href=encoded_path(f"/{prefix}" + moved.get(link.href, link.href)), cta=link.cta)
                for link in standard.nav if link.href in hrefs)
    # What the primary language derives from the site's name follows the language's name; what the site set itself has its own string.
    feeds_title = strings[FEEDS_TITLE_KEY] if standard.feeds.title != standard.identity.name else name
    publisher_name = standard.seo.publisher_name
    if publisher_name == (standard.identity.publisher or standard.identity.name):
        publisher_name = identity.publisher or name
    return dataclasses.replace(
        standard,
        identity=identity,
        feeds=dataclasses.replace(standard.feeds, title=feeds_title),
        seo=dataclasses.replace(
            standard.seo, publisher_name=publisher_name,
            default_image=strings[SEO_IMAGE_KEY] if standard.seo.default_image else standard.seo.default_image,
            default_image_alt=strings[SEO_IMAGE_ALT_KEY] if standard.seo.default_image_alt else standard.seo.default_image_alt,
        ),
        language_prefix=prefix,
        moved_paths=moved_paths,
        sections=sections,
        nav=nav,
        collections=(),
        pages=pages,
        showcase=None,
        home_page=home_page,
        forms=(),
        footer_columns=(),
        footer_family=None,
        footer_text=localized(standard.footer_text, strings, "footer.text"),
        home_link_label=strings["home.label"],
        exact_redirects=(),
        pattern_redirects=(),
        sitemap_extra=(),
        listings=dataclasses.replace(standard.listings, tags=False, page_suffix=strings["listing.pageSuffix"]),
        page_actions=dataclasses.replace(standard.page_actions, enabled=False),
        agents=dataclasses.replace(standard.agents, llms_txt=False, llms_full=False),
    )


#: Where a language edition serves its Concepts (the wiki pages): ``/<prefix>/concepts/`` (Ryan, 2026-11-13: the public term). The primary language keeps
#: its address (``/wiki/`` on the sites that have one), because published URLs are never moved.
CONCEPTS_BASE = "concepts"


def is_concepts_group(standard: StandardSettings, section) -> bool:
    """The URL group that holds the site's wiki pages: a type group of a wiki type, or the section the wiki sync files them under."""
    return section.item_type in standard.wiki.types if section.is_type else section.name == DEFAULT_WIKI_SECTION


def edition_base(standard: StandardSettings, section) -> str:
    return CONCEPTS_BASE if is_concepts_group(standard, section) else section.base


def edition_nav_hrefs(standard: StandardSettings) -> tuple[str, ...]:
    """The navigation links an edition keeps: the home and each section listing page."""
    bases = {f"/{section.base}/" for section in standard.sections if section.listing and section.listing_page and section.base}
    return tuple(link.href for link in standard.nav if not link.children and not link.external and (link.href == "/" or link.href in bases))


def language_name(strings: Mapping[str, Mapping[str, str]], tag: str) -> str:
    return strings.get(tag, {}).get(LANGUAGE_NAME_KEY, "")
