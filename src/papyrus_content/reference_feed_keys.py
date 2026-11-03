"""The keys the References page reads through (docs/reference-feed-indexes.md).

The page asks two indexes on ``Reference`` for a page at a time instead of loading every Reference:

* ``listReferencesByFeedStateAndPrediction``: partition ``feedStateKey``, sort ``predictionSortKey``. Read newest-key-first it is
  "Predictions": the Cyclotron's ORIGINAL P(accept) highest first, ties newest first.
* ``listReferencesByFeedStateAndArrival``: partition ``feedStateKey``, sort ``feedArrivalAt``. Read descending it is "Newest".
* ``listReferencesByStarFeedAndArrival``: partition ``starFeedKey`` (``<corpusId>#stars#<n>``, one per star level), sort ``feedArrivalAt``.
  The Quality sort and the minimum-stars filter merge the levels they want.

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

from .reference_policy import normalize_reference_curation_status

UNDECIDED_PROBABILITY = 0.5
UNRECORDED_CONFIDENCE = 0.6   # a label with no recorded confidence is a mild lean (lib/reference-feed-ranking.ts)
EPOCH = "1970-01-01T00:00:00.000Z"
ARRIVAL_FIELDS = ("createdAt", "importedAt", "retrievedAt", "sourcePublishedAt", "versionCreatedAt")
FEED_KEY_FIELDS = ("feedStateKey", "feedArrivalAt", "predictionSortKey")
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
    return {"feedStateKey": feed_state_key(reference), "feedArrivalAt": arrival,
            "predictionSortKey": prediction_sort_key(stored, arrival, str(reference["id"]))}


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
    return {key: value for key, value in wanted.items() if reference.get(key) != value}
