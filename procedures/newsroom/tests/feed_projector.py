"""A projector shaped like Pilobol.us, for the incremental projection tests.

Derived from Pilobol.us ``web/pilobol_feed.py``: the home page lists every
article that is not hidden from the feed (``feed: false``), newest first, and
takes its cover from the newest; the archive lists every article, newest first,
with no pagination; navigation is static; the sitemap lists every page. The
chrome is Papyrus's own; wiring the real Pilobol.us chrome is the site's
migration, not this test double's concern.
"""

from __future__ import annotations

import html
from collections.abc import Collection

from papyrus_content.markus_renderer.pages import HOME_HREF, build_nav_items, render_home_page
from papyrus_content.markus_renderer.shell import render_page
from papyrus_content.projection.model import ItemSummary, SiteIndex
from papyrus_content.projection.projector import MarkusSiteProjector, digest_of

ARCHIVE_PATH = "articles/index.html"
SITEMAP_PATH = "sitemap.xml"
FEED_FIELDS = ("title", "description", "date", "card_image", "image_effect")


def feed_hidden(summary: ItemSummary) -> bool:
    return str(summary.front_matter.get("feed", "")).strip().lower() in {"false", "0", "no", "off"}


def newest_first(summaries: list[ItemSummary]) -> list[ItemSummary]:
    return sorted(
        sorted(summaries, key=lambda summary: summary.slug),
        key=lambda summary: str(summary.front_matter.get("date", "")),
        reverse=True,
    )


def card_fields(summary: ItemSummary) -> list:
    return [summary.slug, *[summary.front_matter.get(name) for name in FEED_FIELDS]]


class FeedSiteProjector(MarkusSiteProjector):
    def _nav_items(self, site: SiteIndex):
        return build_nav_items([("index", "Spores")])

    def _article_summaries(self, site: SiteIndex) -> list[ItemSummary]:
        return [summary for summary in self._articles(site) if self._is_page_source(summary)]

    def _home_members(self, site: SiteIndex) -> list[ItemSummary]:
        return newest_first([summary for summary in self._article_summaries(site) if not feed_hidden(summary)])

    def _page_keys(self, site: SiteIndex) -> list[str]:
        keys = {HOME_HREF, ARCHIVE_PATH}
        for summary in site.items:
            keys.update(self.item_page_paths(summary))
        return sorted(keys)

    def listing_inputs(self, site: SiteIndex) -> dict[str, str]:
        everything = newest_first(self._article_summaries(site))
        home = self._home_members(site)
        return {
            HOME_HREF: digest_of([card_fields(summary) for summary in home]),
            ARCHIVE_PATH: digest_of([card_fields(summary) for summary in everything]),
            SITEMAP_PATH: digest_of(self._page_keys(site)),
        }

    def shared_inputs(self, site: SiteIndex) -> str:
        return digest_of("static navigation")

    def owns_page_key(self, key: str) -> bool:
        return key in (HOME_HREF, SITEMAP_PATH) or (key.startswith("articles/") and key.endswith(".html"))

    @staticmethod
    def _card(summary: ItemSummary, prefix: str) -> str:
        title = html.escape(str(summary.front_matter.get("title") or summary.slug))
        blurb = html.escape(str(summary.front_matter.get("description") or ""))
        date = html.escape(str(summary.front_matter.get("date") or ""))
        image = summary.front_matter.get("card_image")
        picture = f'<img src="{html.escape(str(image))}" alt="{title}">' if image else ""
        return f'<article class="card"><h3><a href="{prefix}{summary.slug}.html">{title}</a></h3>{picture}<p>{blurb}</p><em>{date}</em></article>'

    def listing_pages(self, site: SiteIndex, keys: Collection[str] | None = None) -> dict[str, bytes]:
        wanted = set(self.listing_inputs(site)) if keys is None else set(keys)
        pages: dict[str, bytes] = {}
        nav = self._nav_items(site)
        if HOME_HREF in wanted:
            members = self._home_members(site)
            cover = members[0].front_matter.get("card_image") if members else None
            fragment = f'<div data-cover="{html.escape(str(cover or ""))}">' + "".join(
                self._card(summary, "articles/") for summary in members
            ) + "</div>"
            pages[HOME_HREF] = render_home_page(
                fragment=fragment, title="Home", nav_items=nav, chrome=self._settings.chrome, css_version=self.version
            ).encode("utf-8")
        if ARCHIVE_PATH in wanted:
            fragment = "<h1>Spores</h1>" + "".join(
                self._card(summary, "") for summary in newest_first(self._article_summaries(site))
            )
            pages[ARCHIVE_PATH] = render_page(
                title="Spores",
                fragment=fragment,
                active_href=ARCHIVE_PATH,
                nav_items=nav,
                depth=1,
                chrome=self._settings.chrome,
                css_version=self.version,
            ).encode("utf-8")
        if SITEMAP_PATH in wanted:
            body = "".join(f"<url><loc>https://example.test/{key}</loc></url>" for key in self._page_keys(site))
            pages[SITEMAP_PATH] = (
                f'<?xml version="1.0" encoding="UTF-8"?><urlset>{body}</urlset>\n'.encode("utf-8")
            )
        return pages
