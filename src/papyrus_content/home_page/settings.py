"""The ``homePage`` setting of a site's ``projection.json``, parsed once and validated.

A site without the key has no home-page behaviour at all: the standard settings hold ``None`` for it. An unknown key anywhere in the
block is a build error that names the key, so a misspelt setting never silently does nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .export import PUBLIC_REFERENCE_FIELDS, REQUIRED_PUBLISHED_FIELDS

LAYOUTS = ("latest", "sections")
THREAD_AUTHOR_POLICIES = ("handle", "none", "anonymous")
DEFAULT_SUMMARY_CHARACTERS = 240


@dataclass(frozen=True)
class ReferencesSettings:
    corpus: str | None = None
    fields: tuple[str, ...] = PUBLIC_REFERENCE_FIELDS
    default_count: int = 6
    recommended_threshold: float = 0.5
    summary_characters: int = DEFAULT_SUMMARY_CHARACTERS


@dataclass(frozen=True)
class ThreadsSettings:
    enabled: bool = False
    authors: str = "handle"
    anonymous_label: str = "Editor"


@dataclass(frozen=True)
class FreshnessSettings:
    debounce_seconds: int = 300
    interval_hours: float | None = None
    purge: bool = False


@dataclass(frozen=True)
class HomePageSettings:
    layout: str = "latest"
    per_section: int = 4
    references: ReferencesSettings = field(default_factory=ReferencesSettings)
    threads: ThreadsSettings = field(default_factory=ThreadsSettings)
    freshness: FreshnessSettings = field(default_factory=FreshnessSettings)


def _only(mapping: Mapping, allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ValueError(f"Unknown {where} settings: {', '.join(unknown)}")


def _section(raw: Mapping, name: str, where: str) -> Mapping:
    value = raw.get(name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{where}.{name} must be an object")
    return value


def _whole_number(value: Any, where: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{where} must be a whole number of at least {minimum}")
    return value


def _flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be true or false")
    return value


def _fields(value: Any) -> tuple[str, ...]:
    if value == "all":
        return PUBLIC_REFERENCE_FIELDS
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise ValueError('homePage.references.fields must be "all" or a list of field names')
    unknown = sorted(set(value) - set(PUBLIC_REFERENCE_FIELDS))
    if unknown:
        raise ValueError(f"homePage.references.fields names fields that are not public: {', '.join(unknown)}")
    missing = [name for name in REQUIRED_PUBLISHED_FIELDS if name not in value]
    if missing:
        raise ValueError(f"homePage.references.fields must include {', '.join(missing)}")
    return tuple(name for name in PUBLIC_REFERENCE_FIELDS if name in value)


def home_page_settings_from_mapping(raw: Any) -> HomePageSettings:
    if not isinstance(raw, Mapping):
        raise ValueError("homePage must be an object")
    _only(raw, ("layout", "perSection", "references", "threads", "freshness"), "homePage")
    defaults = HomePageSettings()
    layout = raw.get("layout", defaults.layout)
    if layout not in LAYOUTS:
        raise ValueError(f"homePage.layout must be one of {', '.join(LAYOUTS)}")
    references_raw = _section(raw, "references", "homePage")
    _only(references_raw, ("corpus", "fields", "defaultCount", "recommendedThreshold"), "homePage.references")
    threads_raw = _section(raw, "threads", "homePage")
    _only(threads_raw, ("enabled", "authors", "anonymousLabel"), "homePage.threads")
    freshness_raw = _section(raw, "freshness", "homePage")
    _only(freshness_raw, ("debounceSeconds", "intervalHours", "purge"), "homePage.freshness")
    corpus = references_raw.get("corpus")
    if corpus is not None and (not isinstance(corpus, str) or not corpus.strip()):
        raise ValueError("homePage.references.corpus must be a corpus id")
    threshold = references_raw.get("recommendedThreshold", defaults.references.recommended_threshold)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("homePage.references.recommendedThreshold must be a number from 0 to 1")
    authors = threads_raw.get("authors", defaults.threads.authors)
    if authors not in THREAD_AUTHOR_POLICIES:
        raise ValueError(f"homePage.threads.authors must be one of {', '.join(THREAD_AUTHOR_POLICIES)}")
    label = threads_raw.get("anonymousLabel", defaults.threads.anonymous_label)
    if not isinstance(label, str) or not label.strip() or "@" in label:
        raise ValueError("homePage.threads.anonymousLabel must be a short label without an @")
    interval = freshness_raw.get("intervalHours", defaults.freshness.interval_hours)
    if interval is not None and (isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0):
        raise ValueError("homePage.freshness.intervalHours must be a positive number or null")
    return HomePageSettings(
        layout=layout,
        per_section=_whole_number(raw.get("perSection", defaults.per_section), "homePage.perSection", 1),
        references=ReferencesSettings(
            corpus=corpus.strip() if corpus else None,
            fields=_fields(references_raw.get("fields", "all")),
            default_count=_whole_number(references_raw.get("defaultCount", defaults.references.default_count), "homePage.references.defaultCount", 1),
            recommended_threshold=float(threshold),
        ),
        threads=ThreadsSettings(
            enabled=_flag(threads_raw.get("enabled", defaults.threads.enabled), "homePage.threads.enabled"),
            authors=authors,
            anonymous_label=label.strip(),
        ),
        freshness=FreshnessSettings(
            debounce_seconds=_whole_number(freshness_raw.get("debounceSeconds", defaults.freshness.debounce_seconds), "homePage.freshness.debounceSeconds", 0),
            interval_hours=float(interval) if interval is not None else None,
            purge=_flag(freshness_raw.get("purge", defaults.freshness.purge), "homePage.freshness.purge"),
        ),
    )
