"""The extended public entry model: one record per published item, built from summaries only.

Listings, feeds, the sitemap and hooks all read this model, never item bodies, so
a projection of one item stays cheap and a listing's inputs are exactly the
fields it shows.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..model import ItemSummary
from ..public_data import SUMMARY_FIELD_NAMES, clipped, tags_of
from .config import SectionConfig, StandardSettings
from .urls import UrlPolicy

SUMMARY_FIELDS = (*SUMMARY_FIELD_NAMES, "dek", "standfirst")
IMAGE_FIELDS = ("image", "cover", "ogImage", "thumbnail")
UPDATED_FIELDS = ("updated", "modified", "lastmod", "dateModified")
FALSE_VALUES = {"false", "0", "no", "off"}
TRUE_VALUES = {"true", "1", "yes", "on"}


def truthy(value) -> bool:
    return str(value).strip().lower() in TRUE_VALUES


def falsy(value) -> bool:
    return str(value).strip().lower() in FALSE_VALUES


def first_text(front_matter: dict, names) -> str:
    for name in names:
        value = front_matter.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def authors_of(front_matter: dict) -> tuple[str, ...]:
    raw = front_matter.get("authors", front_matter.get("author"))
    if raw is None:
        return ()
    values = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


WRITTEN_DATE_FORMATS = ("%A, %B %d, %Y", "%B %d, %Y", "%A, %b %d, %Y", "%b %d, %Y", "%d %B %Y")


def calendar_date(value) -> str:
    """``YYYY-MM-DD`` of a date-ish value (ISO, or written out as in "Sunday, September 6, 2026"), or an empty string."""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip().strip("'\"")
    try:
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    for date_format in WRITTEN_DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


@dataclass(frozen=True)
class StandardEntry:
    summary: ItemSummary
    section: SectionConfig | None
    key: str | None          # page key; None for a link-only item
    url: str | None          # site path; None for a link-only item
    title: str
    summary_text: str
    date: str
    updated: str
    image: str | None
    authors: tuple[str, ...]
    type: str
    canonical: str | None
    feed_eligible: bool
    noindex: bool
    listed: bool             # appears in listings, tag pages and feeds' selection
    tags: tuple[str, ...]
    link: str | None         # external target of a link-only item

    @property
    def slug(self) -> str:
        return self.summary.slug

    @property
    def item_id(self) -> str:
        return self.summary.item_id

    @property
    def data(self) -> dict:
        return self.summary.front_matter

    @property
    def in_sitemap(self) -> bool:
        return self.key is not None and not self.noindex and (self.section is None or self.section.sitemap)

    @property
    def sort_key(self) -> tuple:
        return (self.date, self.updated, self.slug)

    def fingerprint(self, *, full: bool = False) -> list:
        """What a listing card renders from. ``full`` is for pages a hook composes: every field, plus the raw front matter."""
        card = [self.key, self.title, self.summary_text, self.date, self.image, list(self.authors), self.link]
        if not full:
            return card
        return card + [
            self.item_id, self.updated, self.type, self.canonical, self.feed_eligible, self.noindex, self.listed,
            list(self.tags), self.section.name if self.section else None, self.summary.front_matter,
        ]


def entry_title(summary: ItemSummary) -> str:
    """The parsed front matter title first: the stored page title comes from a line scan that keeps YAML quote escapes."""
    parsed = str(summary.front_matter.get("title") or "").strip()
    return clipped(parsed or summary.page_title or summary.title or summary.slug.replace("-", " ").title(), 200)


def build_entries(items, settings: StandardSettings, policy: UrlPolicy) -> list[StandardEntry]:
    entries = []
    for summary in items:
        entry = entry_for_summary(summary, settings, policy)
        if entry is not None:
            entries.append(entry)
    return entries


def entry_for_summary(summary: ItemSummary, settings: StandardSettings, policy: UrlPolicy) -> StandardEntry | None:
    if PurePosixPath(summary.output_path).name.startswith(("_", ".")):
        return None
    if settings.showcase is not None and summary.section == settings.showcase.section:
        return None  # showcase items are data for the logo wall, not pages
    if summary.section is None and summary.slug == "index":
        return None  # the authored home page is an item page of its own, not a listed entry
    section: SectionConfig | None = None
    if settings.sectioned and summary.section is not None:
        section = settings.section(summary.section)
        if section is None:
            return None
    front_matter = summary.front_matter
    has_page = section.pages if section is not None else True
    key = policy.item_key(section, summary.slug) if has_page else None
    link = first_text(front_matter, (section.link_field, "url", "sourceUrl", "link")) if (section is not None and not has_page) else None
    draft = truthy(front_matter.get("draft")) or str(front_matter.get("status", "")).strip().lower() == "draft"
    robots = str(front_matter.get("robots", "")).lower()
    noindex = draft or truthy(front_matter.get("noindex")) or "noindex" in robots
    feed_flag = front_matter.get("feed")
    in_selection = summary.type in settings.listings.types and not draft
    section_listed = section.listing if section is not None else True
    feed_eligible = (
        in_selection
        and not (feed_flag is not None and falsy(feed_flag))
        and (section.feed if section is not None else True)
        and key is not None
    )
    date = calendar_date(front_matter.get("date")) or calendar_date(summary.published_at)
    updated = calendar_date(first_text(front_matter, UPDATED_FIELDS)) or calendar_date(summary.published_at) or date
    return StandardEntry(
        summary=summary,
        section=section,
        key=key,
        url=policy.url_for_key(key) if key else None,
        title=entry_title(summary),
        summary_text=clipped(first_text(front_matter, settings.summary_fields or SUMMARY_FIELDS), 300),
        date=date,
        updated=updated,
        image=first_text(front_matter, IMAGE_FIELDS) or None,
        authors=authors_of(front_matter),
        type=summary.type,
        canonical=first_text(front_matter, ("canonical",)) or None,
        feed_eligible=feed_eligible,
        noindex=noindex,
        listed=in_selection and section_listed,
        tags=tags_of(front_matter.get("tags")),
        link=link,
    )


def newest_first(entries) -> list[StandardEntry]:
    return sorted(entries, key=lambda entry: (entry.date, entry.updated, entry.slug), reverse=True)
