"""Small static JSON files for client-side use: a search index and the latest items.

They are listing-class pages: they depend on every published page, so the engine
re-renders them exactly when their digest moves. The digest is the digest of the
file's bytes, and the entries carry only front matter fields, so an edit that
does not touch the title, summary, tags, date, image, publication or address writes nothing.

Everything in them is already public in the page HTML. Nothing editorial goes in.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .model import ItemSummary
from .writers import request_paths_for_key

PUBLIC_DATA_DIRECTORY = "_data"
SEARCH_INDEX_KEY = f"{PUBLIC_DATA_DIRECTORY}/search-index.json"
LATEST_KEY = f"{PUBLIC_DATA_DIRECTORY}/latest.json"
PUBLIC_DATA_SETTINGS_KEY = "publicData"
SEARCH_COMPONENT_KEY = "_plugins/papyrus-search@1.js"
SEARCH_COMPONENT_SOURCE = Path(__file__).parent / "public_assets" / "papyrus-search.js"
SUMMARY_FIELD_NAMES = ("description", "summary", "excerpt", "blurb")
HIDDEN_FROM_FEED_VALUES = {"false", "0", "no", "off"}


@dataclass(frozen=True)
class PublicDataSettings:
    search_index: bool = True
    latest: bool = True
    latest_count: int = 20
    summary_characters: int = 240


def public_data_settings_from_mapping(raw: Mapping) -> PublicDataSettings:
    known = {"searchIndex", "latest", "latestCount", "summaryCharacters"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"Unknown publicData settings: {', '.join(sorted(unknown))}")
    defaults = PublicDataSettings()
    settings = PublicDataSettings(
        search_index=bool(raw.get("searchIndex", defaults.search_index)),
        latest=bool(raw.get("latest", defaults.latest)),
        latest_count=int(raw.get("latestCount", defaults.latest_count)),
        summary_characters=int(raw.get("summaryCharacters", defaults.summary_characters)),
    )
    if settings.latest_count < 1 or settings.summary_characters < 1:
        raise ValueError("publicData latestCount and summaryCharacters must be positive.")
    return settings


@dataclass(frozen=True)
class PublicEntry:
    title: str
    url: str
    summary: str
    tags: tuple[str, ...]
    date: str
    image: str | None = None  # absolute og/cover image URL; None when the page has none or the site has no URL
    publication: str = ""  # the site's publication name (the feeds' title); empty when unknown


def clipped(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def tags_of(raw) -> tuple[str, ...]:
    if raw is None:
        return ()
    values: Iterable = raw.split(",") if isinstance(raw, str) else raw
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def hidden_from_public_data(summary: ItemSummary) -> bool:
    return str(summary.front_matter.get("feed", "")).strip().lower() in HIDDEN_FROM_FEED_VALUES


def entry_for(
    summary: ItemSummary, page_key: str, settings: PublicDataSettings, *, summary_text: str | None = None, date: str | None = None,
    image: str | None = None, publication: str = ""
) -> PublicEntry:
    """``date`` is the entry's calendar date when the caller has already normalised it (front matter may write it out in words).

    ``image`` is the already absolute og image URL and ``publication`` the site's name; the caller resolves both.
    """
    front_matter = summary.front_matter
    if summary_text is None:
        summary_text = next((str(front_matter[name]) for name in SUMMARY_FIELD_NAMES if front_matter.get(name)), "")
    return PublicEntry(
        title=clipped(summary.page_title or summary.title or summary.slug, 200),
        url=request_paths_for_key(page_key)[0],
        summary=clipped(summary_text, settings.summary_characters),
        tags=tags_of(front_matter.get("tags")),
        date=date if date is not None else str(front_matter.get("date") or summary.published_at or "")[:10],
        image=image or None,
        publication=clipped(publication, 200),
    )


def newest_first(entries: Iterable[PublicEntry]) -> list[PublicEntry]:
    return sorted(sorted(entries, key=lambda entry: entry.url), key=lambda entry: entry.date, reverse=True)


def _entry_record(entry: PublicEntry) -> dict:
    record = {"title": entry.title, "url": entry.url, "summary": entry.summary, "tags": list(entry.tags), "date": entry.date}
    if entry.image:
        record["image"] = entry.image  # omitted, never null, when there is none
    if entry.publication:
        record["publication"] = entry.publication
    return record


def _encoded(payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def public_data_files(entries: Collection[PublicEntry], settings: PublicDataSettings) -> dict[str, bytes]:
    """The enabled files, byte-stable for the same entries."""
    ordered = newest_first(entries)
    files: dict[str, bytes] = {}
    if settings.search_index:
        files[SEARCH_INDEX_KEY] = _encoded([_entry_record(entry) for entry in ordered])
    if settings.latest:
        files[LATEST_KEY] = _encoded([_entry_record(entry) for entry in ordered[: settings.latest_count]])
    return files


def public_data_inputs(entries: Collection[PublicEntry], settings: PublicDataSettings) -> dict[str, str]:
    return {key: hashlib.sha256(body).hexdigest()[:16] for key, body in public_data_files(entries, settings).items()}


def owns_public_data_key(key: str) -> bool:
    return key.startswith(PUBLIC_DATA_DIRECTORY + "/") and key.endswith(".json")


def public_static_files(settings: PublicDataSettings | None) -> dict[str, bytes]:
    """The client component, shipped with the search index it reads; nothing links to it until a page does."""
    if settings is None or not settings.search_index:
        return {}
    return {SEARCH_COMPONENT_KEY: SEARCH_COMPONENT_SOURCE.read_bytes()}
