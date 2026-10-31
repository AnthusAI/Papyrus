"""Public records in, the ``_data/home-page/references.json`` document out.

Nothing here knows a site, a storage layer or a clock: ``build_snapshot`` takes records and a time. The freshness stamp alone is never a
change, so a run that finds the same References writes nothing and re-renders nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .export import PUBLIC_REFERENCE_FIELDS

HOME_PAGE_DATA_DIRECTORY = "_data/home-page"
REFERENCES_FILE = f"{HOME_PAGE_DATA_DIRECTORY}/references.json"
THREADS_FILE = f"{HOME_PAGE_DATA_DIRECTORY}/threads.json"
THREADS_DIRECTORY = f"{HOME_PAGE_DATA_DIRECTORY}/threads"
GENERATED_AT = "generatedAt"


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def build_snapshot(
    records: Iterable[Mapping[str, Any]],
    now: datetime,
    *,
    corpus: str = "",
    fields: Iterable[str] = PUBLIC_REFERENCE_FIELDS,
) -> dict[str, Any]:
    """The document: newest accepted first (``acceptedAt`` descending), then the recommended ones newest arrival first."""
    ordered = sorted(
        (dict(record) for record in records),
        key=lambda record: (record.get("acceptedAt") or "", record.get("arrivedAt") or "", record.get("key") or ""),
        reverse=True,
    )
    return {GENERATED_AT: _stamp(now), "corpus": corpus, "fields": list(fields), "references": ordered}


def thread_file(key: str) -> str:
    return f"{THREADS_DIRECTORY}/{key}.json"


def build_threads_snapshot(threads: Iterable[Mapping[str, Any]], now: datetime) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """``threads.json`` (one entry per thread, most recently active first) and one document per thread keyed by file name.

    Each entry carries the count of public Messages, the time of the latest one and the latest Message itself; the per-thread document
    holds every public Message in sequence.
    """
    ordered = sorted((dict(thread) for thread in threads), key=lambda thread: (thread["messages"][-1].get("at") or "", thread["key"]), reverse=True)
    entries = [
        {
            "key": thread["key"],
            "title": thread["title"],
            "anchor": thread["anchor"],
            "messages": len(thread["messages"]),
            "lastAt": thread["messages"][-1].get("at"),
            "latest": thread["messages"][-1],
        }
        for thread in ordered
    ]
    documents = {
        thread["key"]: {"key": thread["key"], "title": thread["title"], "anchor": thread["anchor"], "messages": thread["messages"]}
        for thread in ordered
    }
    return {GENERATED_AT: _stamp(now), "threads": entries}, documents


def snapshot_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def changed_without_generated_at(old_bytes: bytes | None, new_bytes: bytes) -> bool:
    """True when the new document differs from the old one in anything but its freshness stamp (or when there is no readable old one)."""
    if old_bytes is None:
        return True
    try:
        old = json.loads(old_bytes)
        new = json.loads(new_bytes)
    except ValueError:
        return True
    return _without_generated_at(old) != _without_generated_at(new)


def _without_generated_at(document: Any) -> Any:
    if isinstance(document, Mapping):
        return {key: value for key, value in document.items() if key != GENERATED_AT}
    return document
