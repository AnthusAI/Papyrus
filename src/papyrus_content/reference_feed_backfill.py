"""Set the References page keys on existing References (``papyrus references backfill-feed-keys --site KEY [--dry-run]``).

A Reference created before the feed indexes has no ``feedStateKey``, ``feedArrivalAt`` or ``predictionSortKey``, and no recorded
prediction; one starred before the star index has no ``starFeedKey``. This reads each current Reference of one publication's corpus by
its curation status, takes the Cyclotron's current ``relevance_decision_is`` decision for it (when it has one) as its original
prediction, and writes only those fields: it changes no vote, no curation field and no relation. A Reference that already has a
prediction keeps it. Archived References get no feed-state key; one that somehow has a key loses it. ``starFeedKey`` (the star
partition, ``<corpusId>#stars#<n>``) is set from ``starRating`` where it differs and cleared where a Reference has a key but no stars.
``captureState`` (how much content the newsroom holds: full, thin, none, running) is set from the Reference's attachments by the rule in
``reference_capture_state.py``, which reads them only for a Reference that could have a capture (not an archived one with the field empty);
a Reference with no capture keeps the field empty and writes nothing, and a stale value on one that now has none is cleared (never set to
``none``). Nothing it writes is derived from anything but the Reference, its status, its decision and its attachments, so running it again writes nothing.
"""
from __future__ import annotations

from typing import Any, Callable

from .ideas.digest import relations_of, relevance_of
from .reference_capture_state import attachments_for_state, capture_state, normalize_capture_state
from .reference_policy import normalize_reference_curation_status
from .reference_feed_keys import FEED_KEY_FIELDS, PREDICTION_FIELDS, feed_keys, original_prediction_fields, stale_feed_keys, stale_star_feed_key

STATUSES = ("pending", "accepted", "rejected", "archived")


def corpus_ids_for(client: Any, *, site: str | None, corpus_keys: str | None, all_corpora: bool) -> list[str]:
    """The corpora one run covers: every KnowledgeCorpus the backend lists (``--all-corpora``), the comma-separated ``--corpus-key`` list, or
    the site's own ``knowledge-corpus-<site>``. A publication's References can sit in corpora named for something else than its site."""
    if all_corpora:
        found = sorted({str(row["id"]) for row in client.list_records("KnowledgeCorpus") if row.get("id")})
        if not found:
            raise ValueError("references backfill-feed-keys --all-corpora found no KnowledgeCorpus rows.")
        return found
    keys = [key.strip() for key in (corpus_keys or site or "").split(",") if key.strip()]
    if not keys:
        raise ValueError("references backfill-feed-keys needs --site KEY, --corpus-key KEY[,KEY...] or --all-corpora.")
    return [f"knowledge-corpus-{key}" for key in dict.fromkeys(keys)]


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
    fields.update(stale_star_feed_key(working))
    fields.update(planned_capture_state(client, reference))
    return fields


def planned_capture_state(client: Any, reference: dict[str, Any]) -> dict[str, Any]:
    """``{"captureState": ...}`` when the stored state is wrong, else {}. Never writes ``none``: a Reference with no capture stays empty."""
    stored = normalize_capture_state(reference.get("captureState"))
    if stored == "none" and normalize_reference_curation_status(reference.get("curationStatus")) == "archived":
        return {}   # archived and nothing stored: no feed shows it, so the attachments are not read
    state = capture_state(attachments_for_state(client, reference))
    if state == stored:
        return {}
    return {"captureState": None if state == "none" else state}


def backfill_feed_keys(client: Any, *, corpus_id: str, positive_label: str = "include", dry_run: bool = False,
                       progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    counts = {"corpusId": corpus_id, "dryRun": dry_run, "scanned": 0, "changed": 0, "predictionsRecorded": 0, "unpredicted": 0,
              "keysCleared": 0, "starKeysChanged": 0, "captureStatesChanged": 0, "alreadyRight": 0, "written": 0}
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
            counts["starKeysChanged"] += int("starFeedKey" in fields)
            counts["captureStatesChanged"] += int("captureState" in fields)
            counts["keysCleared"] += int(fields.get("feedStateKey", True) is None and bool(reference.get("feedStateKey")))
            if not (reference.get("predictionDecidedAt") or "predictionDecidedAt" in fields):
                counts["unpredicted"] += 1
            if not dry_run:
                client.update_record("Reference", {"id": reference["id"], **fields})
                counts["written"] += 1
                progress(f"{counts['written']} written")
    return counts
