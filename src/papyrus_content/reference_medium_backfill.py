"""Set the medium fields and the content-needed key on existing References (``papyrus references backfill-medium --site KEY [--write]``).

Reads each current Reference of a corpus by curation status (``referencesByCurationStatusKey``, the same read the feed-key backfill uses), takes
what its address says (``reference_medium.classify_address``) and writes only ``medium``, ``playlistUrl``, ``evidenceLevel``, ``mediumFeedKey`` and
``contentNeededKey`` (a video whose stored ``captureState`` is not ``full`` and that has no settled ``captureReason``; run ``backfill-feed-keys`` first on a
site whose capture states were never stored).
It changes no vote, no curation field, no relation and no other key. ``evidenceLevel`` is only filled where empty (the rule says "aggregation"
for a playlist address), so a value an editor or the decision model wrote is never replaced. Everything written derives from the Reference alone,
so running it again writes nothing. ``dry_run`` (the CLI's default) reports every change and writes none.
"""
from __future__ import annotations

from typing import Any, Callable

from .reference_feed_keys import CONTENT_NEEDED_KEY_FIELD, MEDIUM_FEED_KEY_FIELD, content_needed_key, medium_feed_key
from .reference_medium import stale_medium_fields

STATUSES = ("pending", "accepted", "rejected", "archived")


def planned_fields(reference: dict[str, Any]) -> dict[str, Any]:
    """The fields to write for one Reference, or {} when it is already right."""
    fields = stale_medium_fields(reference)
    working = {**reference, **fields}
    wanted = medium_feed_key(working)
    if (reference.get(MEDIUM_FEED_KEY_FIELD) or None) != wanted:
        fields[MEDIUM_FEED_KEY_FIELD] = wanted
    needed = content_needed_key(working)
    if (reference.get(CONTENT_NEEDED_KEY_FIELD) or None) != needed:
        fields[CONTENT_NEEDED_KEY_FIELD] = needed
    return fields


def backfill_medium(client: Any, *, corpus_id: str, dry_run: bool = True, progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    counts = {"corpusId": corpus_id, "dryRun": dry_run, "scanned": 0, "changed": 0, "videos": 0, "aggregations": 0, "playlistsRecorded": 0,
              "keysSet": 0, "keysCleared": 0, "contentKeysSet": 0, "contentKeysCleared": 0, "alreadyRight": 0, "written": 0}
    for status in STATUSES:
        for reference in client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}"):
            if not reference or reference.get("versionState", "current") != "current":
                continue
            counts["scanned"] += 1
            fields = planned_fields(reference)
            if not fields:
                counts["alreadyRight"] += 1
                continue
            counts["changed"] += 1
            counts["videos"] += int(fields.get("medium") == "video")
            counts["aggregations"] += int(fields.get("evidenceLevel") == "aggregation")
            counts["playlistsRecorded"] += int(bool(fields.get("playlistUrl")))
            if MEDIUM_FEED_KEY_FIELD in fields:
                counts["keysSet" if fields[MEDIUM_FEED_KEY_FIELD] else "keysCleared"] += 1
            if CONTENT_NEEDED_KEY_FIELD in fields:
                counts["contentKeysSet" if fields[CONTENT_NEEDED_KEY_FIELD] else "contentKeysCleared"] += 1
            progress(f"{'would write' if dry_run else 'write'}\t{reference['id']}\t{reference.get('sourceUri')}\t" + ", ".join(f"{key}={value}" for key, value in fields.items()))
            if not dry_run:
                client.update_record("Reference", {"id": reference["id"], **fields})
                counts["written"] += 1
    return counts
