"""Set the References page keys on existing References (``papyrus references backfill-feed-keys --site KEY [--dry-run]``).

A Reference created before the feed indexes has no ``feedStateKey``, ``feedArrivalAt`` or ``predictionSortKey``, and no recorded
prediction. This reads each current Reference of one publication's corpus by its curation status, takes the Cyclotron's current
``relevance_decision_is`` decision for it (when it has one) as its original prediction, and writes only those fields: it changes no
vote, no curation field and no relation. A Reference that already has a prediction keeps it. Archived References get no key; one that
somehow has a key loses it. Nothing it writes is derived from anything but the Reference, its status and its decision, so running it
again writes nothing.
"""
from __future__ import annotations

from typing import Any, Callable

from .ideas.digest import relations_of, relevance_of
from .reference_feed_keys import FEED_KEY_FIELDS, PREDICTION_FIELDS, feed_keys, original_prediction_fields, stale_feed_keys

STATUSES = ("pending", "accepted", "rejected", "archived")


def planned_fields(client: Any, reference: dict[str, Any], positive_label: str) -> dict[str, Any]:
    """The fields to write for one Reference, or {} when it is already right."""
    fields: dict[str, Any] = {}
    working = dict(reference)
    if not reference.get("predictionDecidedAt"):
        decision = relevance_of(relations_of(client, reference))
        if decision:
            fields.update(original_prediction_fields(
                reference, label=decision["label"], positive_label=decision.get("positiveLabel") or positive_label,
                confidence=decision["confidence"] if decision.get("confidence") is not None else decision.get("score"),
                decided_at=decision.get("decidedAt") or feed_keys(reference)["feedArrivalAt"]))
            working.update({key: fields[key] for key in PREDICTION_FIELDS})
    fields.update(stale_feed_keys(working))
    return fields


def backfill_feed_keys(client: Any, *, corpus_id: str, positive_label: str = "include", dry_run: bool = False,
                       progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    counts = {"corpusId": corpus_id, "dryRun": dry_run, "scanned": 0, "changed": 0, "predictionsRecorded": 0, "unpredicted": 0,
              "keysCleared": 0, "alreadyRight": 0, "written": 0}
    for status in STATUSES:
        for reference in client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}"):
            if not reference or reference.get("versionState", "current") != "current":
                continue
            counts["scanned"] += 1
            fields = planned_fields(client, reference, positive_label)
            if not fields:
                counts["alreadyRight"] += 1
                continue
            counts["changed"] += 1
            counts["predictionsRecorded"] += int("predictionDecidedAt" in fields)
            counts["keysCleared"] += int(fields.get("feedStateKey", True) is None and bool(reference.get("feedStateKey")))
            if not (reference.get("predictionDecidedAt") or "predictionDecidedAt" in fields):
                counts["unpredicted"] += 1
            if not dry_run:
                client.update_record("Reference", {"id": reference["id"], **fields})
                counts["written"] += 1
                progress(f"{counts['written']} written")
    return counts
