"""The keys the References page reads through (docs/reference-feed-indexes.md).

The page asks two indexes on ``Reference`` for a page at a time instead of loading every Reference:

* ``listReferencesByFeedStateAndPrediction``: partition ``feedStateKey``, sort ``predictionSortKey``. Read newest-key-first it is
  "Predictions": the Cyclotron's ORIGINAL P(accept) highest first, ties newest first.
* ``listReferencesByFeedStateAndArrival``: partition ``feedStateKey``, sort ``feedArrivalAt``. Read descending it is "Newest".
* ``listReferencesByStarFeedAndArrival``: partition ``starFeedKey`` (``<corpusId>#stars#<n>``, one per star level), sort ``feedArrivalAt``.
  The Quality sort and the minimum-stars filter merge the levels they want.
* ``listReferencesByMediumFeedAndArrival``: partition ``mediumFeedKey`` (``<corpusId>#<medium>#<status>``, for example ``corpus#video#accepted``),
  sort ``feedArrivalAt``. Sparse: only a current, not archived Reference with a medium has the key. A public page reads the ``accepted``
  partition and gets nothing else.
* ``listReferencesByContentNeededAndArrival``: partition ``contentNeededKey`` (``<corpusId>#<medium>#needs_content#<status>``, for example
  ``corpus#video#needs_content#accepted``), sort ``feedArrivalAt``. Sparse: a current, not archived Reference with a medium whose content the newsroom
  does not hold yet and that nothing else will capture. The transcript worker (``papyrus references capture-transcripts``) reads it; nothing is filtered after reading.

``feedStateKey`` is ``<corpusId>#unrated`` for a pending Reference and ``<corpusId>#rated`` for an accepted or rejected one. A Reference
that is not the current version, or is archived, has no key and is in neither feed. The prediction is a value on the Reference, written
once when the Cyclotron first decides it and never rewritten: a vote moves the Reference between feeds and leaves the prediction alone.
A Reference nobody has predicted sorts as 0.5, between a predicted Accept and a predicted Reject.

The TypeScript twin is lib/reference-feed-keys.ts; scripts/fixtures/reference-feed-key-vectors.json holds the vectors both test.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping

from .reference_capture_state import normalize_capture_state
from .reference_medium import medium_of
from .reference_policy import normalize_reference_curation_status

UNDECIDED_PROBABILITY = 0.5
UNRECORDED_CONFIDENCE = 0.6   # a label with no recorded confidence is a mild lean (lib/reference-feed-ranking.ts)
EPOCH = "1970-01-01T00:00:00.000Z"
ARRIVAL_FIELDS = ("createdAt", "importedAt", "retrievedAt", "sourcePublishedAt", "versionCreatedAt")
FEED_KEY_FIELDS = ("feedStateKey", "feedArrivalAt", "predictionSortKey")
MEDIUM_FEED_KEY_FIELD = "mediumFeedKey"
CONTENT_NEEDED_KEY_FIELD = "contentNeededKey"
CAPTURE_REASON_FIELD = "captureReason"
NEEDS_CONTENT = "needs_content"
# Verdicts after which no further automatic attempt can change the outcome: the Reference stays in the "To capture" queue for a person, and leaves
# the worker's partition so that it is not read and skipped on every run.
SETTLED_CAPTURE_REASONS = ("no_transcript", "unavailable", "unsupported_platform")
PREDICTION_FIELDS = ("predictedAcceptProbability", "predictionDecidedAt")


def accept_probability(label: str | None, positive_label: str | None, confidence: Any) -> float:
    """P(the editor accepts) from a decision: its confidence is in the label it chose."""
    chosen = float(confidence) if confidence is not None else UNRECORDED_CONFIDENCE
    return chosen if label == (positive_label or "include") else 1 - chosen


def _instant(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    parsed = (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S") + f".{parsed.microsecond // 1000:03d}Z"


def arrival_at(reference: Mapping[str, Any]) -> str:
    """When the Reference reached the newsroom, as a sortable UTC instant with milliseconds."""
    for field in ARRIVAL_FIELDS:
        instant = _instant(reference.get(field))
        if instant:
            return instant
    return EPOCH


def feed_state_key(reference: Mapping[str, Any]) -> str | None:
    if reference.get("versionState") not in (None, "current") or not reference.get("corpusId"):
        return None
    status = normalize_reference_curation_status(reference.get("curationStatus"))
    if status == "archived":
        return None
    return f"{reference['corpusId']}#{'unrated' if status == 'pending' else 'rated'}"


def _medium_parts(reference: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """``(corpusId, medium, status)`` of a current, not archived Reference that has a medium (the stored one, or what the address says)."""
    if reference.get("versionState") not in (None, "current") or not reference.get("corpusId"):
        return None
    status = normalize_reference_curation_status(reference.get("curationStatus"))
    medium = reference.get("medium") or medium_of(reference.get("sourceUri"))
    if status == "archived" or not medium:
        return None
    return str(reference["corpusId"]), str(medium), status


def medium_feed_key(reference: Mapping[str, Any]) -> str | None:
    """The medium partition a Reference is in: ``<corpusId>#<medium>#<pending|accepted|rejected>``, None when it has no medium, no corpus, is not the
    current version or is archived. The medium is the stored one, or what the address says when none is stored yet (the rule is a pure function of the
    address, so a vote written before the backfill still lands in the right partition)."""
    parts = _medium_parts(reference)
    return None if parts is None else "#".join(parts)


def content_needed_key(reference: Mapping[str, Any]) -> str | None:
    """The partition of the content-needed index: ``<corpusId>#<medium>#needs_content#<pending|accepted|rejected>`` while the Reference has a medium, is
    current and not archived, its content is not captured in full (``captureState`` empty, ``none`` or ``thin``; a capture ``running`` will finish by
    itself) and no settled verdict (``captureReason``: no transcript, unavailable, unsupported platform) says that nothing automatic can capture it. None otherwise, so the
    key leaves the index when the content arrives. The status is in the key so that rejected videos are never read when the worker asks for the rest."""
    parts = _medium_parts(reference)
    if parts is None or normalize_capture_state(reference.get("captureState")) in ("full", "running"):
        return None
    if reference.get(CAPTURE_REASON_FIELD) in SETTLED_CAPTURE_REASONS:
        return None
    corpus_id, medium, status = parts
    return f"{corpus_id}#{medium}#{NEEDS_CONTENT}#{status}"


def moved_content_key(held: str, reference: Mapping[str, Any]) -> str | None:
    """A held content-needed key after a vote or an archive: the same key with the new status, None when the Reference left every list. It needs no
    capture state, so a writer that read only part of a Reference cannot get it wrong."""
    parts = _medium_parts(reference)
    return None if parts is None else f"{held.rsplit('#', 1)[0]}#{parts[2]}"


def medium_key_patch(reference: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    """``{"mediumFeedKey": ...}`` (and ``contentNeededKey`` when the Reference holds one) for a vote or an archive written as a patch (``changes``
    overrides the Reference's fields, for example the next ``curationStatus``). {} for a Reference with no medium (stored, by its address, or an index
    key it still holds), so a patch for an ordinary page names no new field and works on a backend that does not have the index yet."""
    if not (reference.get("medium") or medium_of(reference.get("sourceUri")) or reference.get(MEDIUM_FEED_KEY_FIELD)):
        return {}
    merged = {**reference, **changes}
    patch = {MEDIUM_FEED_KEY_FIELD: medium_feed_key(merged)}
    held = reference.get(CONTENT_NEEDED_KEY_FIELD)
    if held:
        patch[CONTENT_NEEDED_KEY_FIELD] = moved_content_key(str(held), merged)
    return patch


def star_feed_key(corpus_id: Any, stars: Any) -> str | None:
    """The star partition a Reference is in: ``<corpusId>#stars#<n>`` for a whole star rating of 1 to 5, None when it has none or no corpus.

    Not part of ``feed_keys``: callers spread those keys on partial patches whose input may lack ``starRating``, which would wrongly clear it.
    A star write sets it; the index is sparse, so an unstarred Reference is in no star partition. It ignores the feed state: the reader drops
    a row with no ``feedStateKey`` (archived or superseded) instead.
    """
    if not corpus_id or isinstance(stars, bool) or not isinstance(stars, (int, float)) or not math.isfinite(stars) or stars != int(stars) or not 1 <= stars <= 5:
        return None
    return f"{corpus_id}#stars#{int(stars)}"


def prediction_sort_key(probability: float | None, arrival: str, reference_id: str) -> str:
    chosen = UNDECIDED_PROBABILITY if probability is None else min(1.0, max(0.0, float(probability)))
    return f"{chosen:.6f}#{arrival}#{reference_id}"


def feed_keys(reference: Mapping[str, Any], *, probability: float | None = None) -> dict[str, Any]:
    """The three feed keys for a Reference as it stands. ``probability`` overrides the one stored on the Reference."""
    arrival = arrival_at(reference)
    stored = probability if probability is not None else reference.get("predictedAcceptProbability")
    keys = {"feedStateKey": feed_state_key(reference), "feedArrivalAt": arrival,
            "predictionSortKey": prediction_sort_key(stored, arrival, str(reference["id"]))}
    # The medium key is sparse: written when the Reference has one, cleared only when it is currently set. Never an explicit null on a Reference
    # that has none, because a null on an index key attribute of a new row is not a missing attribute.
    wanted = medium_feed_key(reference)
    if wanted or reference.get("mediumFeedKey"):
        keys["mediumFeedKey"] = wanted
    needed = content_needed_key(reference)
    if needed or reference.get(CONTENT_NEEDED_KEY_FIELD):
        keys[CONTENT_NEEDED_KEY_FIELD] = needed
    return keys


def original_prediction_fields(reference: Mapping[str, Any], *, label: str | None, positive_label: str | None, confidence: Any,
                               decided_at: str) -> dict[str, Any]:
    """The fields that record a Reference's first prediction, or {} when it already has one (the original is never rewritten)."""
    if reference.get("predictionDecidedAt"):
        return {}
    probability = accept_probability(label, positive_label, confidence)
    return {"predictedAcceptProbability": probability, "predictionDecidedAt": _instant(decided_at) or decided_at,
            **feed_keys(reference, probability=probability)}


def stale_star_feed_key(reference: Mapping[str, Any]) -> dict[str, Any]:
    """``{"starFeedKey": wanted}`` when the stored star partition differs from what the Reference's stars and corpus say, else empty."""
    wanted = star_feed_key(reference.get("corpusId"), reference.get("starRating"))
    return {} if reference.get("starFeedKey") == wanted else {"starFeedKey": wanted}


def stale_feed_keys(reference: Mapping[str, Any]) -> dict[str, Any]:
    """The feed keys that differ from what ``feed_keys`` says now (empty when they are right)."""
    wanted = feed_keys(reference)
    wanted.pop(MEDIUM_FEED_KEY_FIELD, None)   # the medium key belongs to `papyrus references backfill-medium`, which writes medium and key together
    wanted.pop(CONTENT_NEEDED_KEY_FIELD, None)   # so does the content-needed key
    return {key: value for key, value in wanted.items() if reference.get(key) != value}
