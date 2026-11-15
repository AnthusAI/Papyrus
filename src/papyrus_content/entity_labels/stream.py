"""The consumer of the concept table's change stream: the one writer of the primary-language label rows.

Every change of a ``SemanticNode`` reaches ``handle_changes``, whoever made it (the console, a command, the knowledge run, a merge). The rows are brought to
what the node's text says (``primary.sync_node``) only when the text, the key, the language or the version state actually changed, so the writes the
consumer itself makes (the language, the label rows) never start another round of work, and a concept nobody renamed costs nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..localize.dispatch import decode_image
from .keys import CONCEPT, entity_key
from .primary import PRIMARY, lineage_of, sync_node
from .store import LabelStore

WATCHED = ("displayName", "aliases", "description", "nodeKey", "language", "versionState")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current(row: dict[str, Any] | None) -> bool:
    return row is not None and row.get("versionState", "current") == "current"


def changed(old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    return old is None or any(old.get(name) != new.get(name) for name in WATCHED)


def handle_changes(events: list[dict[str, Any]], client: Any, *, now: str | None = None) -> dict[str, int]:
    """``events`` are ``{"event": INSERT|MODIFY|REMOVE, "old": row|None, "new": row|None}``. Counts of the label rows written."""
    totals = {"nodes": 0, "created": 0, "updated": 0, "deleted": 0, "language": 0, "stale": 0}
    stamp = now or _now()
    primary = None
    for event in events:
        old, new = event.get("old"), event.get("new")
        if event.get("event") == "REMOVE":
            if old is not None:
                store = LabelStore(client)
                for row in store.of_entity(entity_key(CONCEPT, lineage_of(old))):
                    if row.get("origin") == PRIMARY:
                        store.delete(row["id"])
                        totals["deleted"] += 1
            continue
        if not _current(new) or not changed(old, new):
            continue
        primary = primary or client.primary_language()
        counts = sync_node(client, new, primary_language=primary, now=stamp)
        totals["nodes"] += 1
        for name, value in counts.items():
            totals[name] += value
    return totals


def events_from_stream(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"event": record["eventName"], "old": decode_image(record["dynamodb"].get("OldImage")), "new": decode_image(record["dynamodb"].get("NewImage"))}
            for record in records if record.get("eventName") in ("INSERT", "MODIFY", "REMOVE")]
