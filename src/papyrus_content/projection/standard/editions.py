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
from ..model import ItemSummary
from .config import NavLink, StandardSettings
from .interface_strings import LANGUAGE_NAME_KEY
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
            Alternate(tag, self.names[tag], "/" + self.roots[tag] + (f"{paths.get(tag, base)}/" if base else ""), tag not in empty)
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


def edition_settings(standard: StandardSettings, tag: str, prefix: str, strings: Mapping[str, str]) -> StandardSettings:
    """The settings of the ``tag`` edition: the site's settings, its words in the language, its pages under the prefix, and only what an edition renders.

    An edition renders the language's Story pages, its home and section listings (with paging and archives), its feeds and sitemap. It renders no
    authored page, collection, tag page, showcase, Reference grid, plugin page, form, page action or ``llms.txt``: their words are the primary
    language's, and an English page inside a Spanish edition is what the rule forbids. Navigation keeps the home and the section listings, named in
    the language; every other link leaves the edition and is dropped."""
    identity = dataclasses.replace(
        standard.identity, language=tag,
        description=localized(standard.identity.description, strings, "site.description"),
        tagline=localized(standard.identity.tagline, strings, "site.tagline"),
    )
    sections = tuple(
        dataclasses.replace(
            section,
            base=edition_base(standard, section),
            label=strings[f"section.{section.name}.label"] if section.listing and section.listing_page else section.label,
            description=localized(section.description, strings, f"section.{section.name}.description") if section.listing and section.listing_page else section.description,
            index=None,   # a section front page carries a Reference grid and authored words
        )
        for section in standard.sections
    )
    hrefs = edition_nav_hrefs(standard)
    moved = {f"/{section.base}/": f"/{edition_base(standard, section)}/" for section in standard.sections if section.base}
    nav = tuple(NavLink(label=strings[f"nav.{link.href}.label"], href=f"/{prefix}" + moved.get(link.href, link.href), cta=link.cta)
                for link in standard.nav if link.href in hrefs)
    return dataclasses.replace(
        standard,
        identity=identity,
        language_prefix=prefix,
        sections=sections,
        nav=nav,
        collections=(),
        pages=(),
        showcase=None,
        home_page=None,
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
