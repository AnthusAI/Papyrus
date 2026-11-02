"""Put the open link suggestions that already exist into the suggestion index (``papyrus references backfill-suggestion-index [--dry-run]``).

A suggestion written before the index has no ``openSuggestionKey`` or ``openSuggestionScore``, so the Needs me queue cannot see it. This reads
every row of the reference-link feed, sets the two fields on each row that is a ``suggested`` link and clears them from any other row that
somehow carries them, and writes nothing else: no state, no score, no decision, no metadata. A row that is already right is not written, so
running it again writes nothing. A person's decision is never undone: only a row whose state is ``suggested`` gets a key.
"""
from __future__ import annotations

from typing import Any, Callable

from .reference_links import REFERENCE_LINK_FEED_KEY, open_suggestion_fields


def planned_fields(row: dict[str, Any]) -> dict[str, Any]:
    """The index fields to write for one row, or {} when it is already right."""
    wanted = open_suggestion_fields(str(row.get("relationState") or ""), row.get("score"))
    current = {name: row.get(name) for name in wanted}
    return {} if current == wanted else wanted


def backfill_suggestion_index(client: Any, *, dry_run: bool = False, progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    counts = {"dryRun": dry_run, "scanned": 0, "openSuggestions": 0, "keyed": 0, "unscored": 0, "keysCleared": 0, "alreadyRight": 0, "written": 0}
    for row in client.list_by_index("semanticRelationsByNewsroomFeedWithOpenSuggestionFields", REFERENCE_LINK_FEED_KEY):
        counts["scanned"] += 1
        is_open = row.get("relationState") == "suggested"
        counts["openSuggestions"] += int(is_open)
        counts["unscored"] += int(is_open and not isinstance(row.get("score"), (int, float)))
        fields = planned_fields(row)
        if not fields:
            counts["alreadyRight"] += 1
            continue
        counts["keyed" if is_open else "keysCleared"] += 1
        if not dry_run:
            client.update_record("SemanticRelation", {"id": row["id"], **fields})
            counts["written"] += 1
            progress(f"{counts['written']} written")
    return counts
