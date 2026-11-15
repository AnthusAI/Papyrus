"""One resumable pass that gives every concept its language and its name rows (``papyrus relations label-backfill``).

The stream consumer keeps the rows true from now on; this writes them for the concepts that exist before it was deployed. It reads the concept table whole
once, which is the point of a migration, and calls ``sync_node`` for each current concept: a concept that is already in order costs one query and writes
nothing, so an interrupted pass is simply run again.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .. import request_meter
from ..graphql_authoring import SEMANTIC_NODE_LANGUAGE_FIELDS, _list_query
from .primary import sync_node


def backfill_entity_labels(client: Any, *, apply: bool, limit: int | None = None, now: str | None = None, say: Callable[[str], None] | None = None) -> dict[str, Any]:
    """``{concepts, language, created, updated, deleted, stale, wouldChange}``. A dry run reads the concepts and the labels and writes nothing."""
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    primary = client.primary_language()
    nodes = [row for row in _every_node(client) if row.get("versionState", "current") == "current"]
    nodes.sort(key=lambda row: str(row.get("nodeKey") or ""))
    report: dict[str, Any] = {"concepts": 0, "language": 0, "created": 0, "updated": 0, "deleted": 0, "stale": 0, "wouldChange": 0, "primaryLanguage": primary}
    for node in nodes[:limit]:
        report["concepts"] += 1
        if apply:
            counts = sync_node(client, node, primary_language=primary, now=stamp)
        else:
            counts = _would_change(client, node, primary, stamp)
        for name, value in counts.items():
            report[name] += value
        if not apply and any(counts.values()):
            report["wouldChange"] += 1
        if say and report["concepts"] % 50 == 0:
            say(f"{report['concepts']} of {len(nodes[:limit])} concepts")
    return report


def _would_change(client: Any, node: dict[str, Any], primary: str, now: str) -> dict[str, int]:
    """What ``sync_node`` would write for one concept, counted without writing (the same code against a recording stand-in for the writes)."""
    from .store import LabelStore

    class Recorder:
        """Reads go to the site; every write is only counted."""

        def __init__(self) -> None:
            self.tenant_id = getattr(client, "tenant_id", None)
            self.writes: list[tuple[str, str]] = []

        def list_by_index(self, *args: Any, **kwargs: Any):
            return client.list_by_index(*args, **kwargs)

        def create_record(self, model: str, row: dict[str, Any]) -> None:
            self.writes.append(("create", row["id"]))

        def update_record(self, model: str, row: dict[str, Any]) -> None:
            self.writes.append(("update", row["id"]))

        def delete_record(self, model: str, record_id: str) -> None:
            self.writes.append(("delete", record_id))

    recorder = Recorder()
    return sync_node(recorder, node, primary_language=primary, now=now)


def _every_node(client: Any) -> list[dict[str, Any]]:
    """Every concept row with its language: the one whole-table read of the migration (a named sweep), paged like ``list_records``."""
    query, rows, token = _list_query("listSemanticNodes", SEMANTIC_NODE_LANGUAGE_FIELDS), [], None
    with request_meter.sweep("entity-label-backfill"):
        while True:
            connection = client.graphql(query, {"limit": 100, "nextToken": token}).get("listSemanticNodes") or {}
            rows.extend(entry for entry in connection.get("items") or [] if entry)
            token = connection.get("nextToken")
            if not token:
                return rows
