"""Reference rows in, public-safe records out.

Every exported record is built from ``PUBLIC_REFERENCE_FIELDS`` and nothing else. ``EXCLUDED_REFERENCE_FIELDS`` names every other
Reference field with the reason it stays private, and a unit test proves that together the two cover each field of the Reference model
exactly once. Text that leaves the building is scrubbed of anything shaped like an email address, a UUID or a site subject.

Nothing here imports the CLI login library: the Lambda bundles that run the snapshot task do not ship it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ..ideas.digest import RELEVANCE_PREDICATE, relations_of, relevance_of
from ..knowledge_snapshot.parallel import map_with_clients
from ..reference_feed_keys import UNDECIDED_PROBABILITY, accept_probability as decision_probability

if TYPE_CHECKING:
    from .settings import HomePageSettings

STATUS_ACCEPTED = "accepted"
STATUS_RECOMMENDED = "recommended"
PREVIEW_ROLE = "preview"
KEY_LENGTH = 12
CONFIDENCE_DECIMALS = 2
REQUIRED_PUBLISHED_FIELDS = ("key", "status")
NOT_PUBLIC_STATUSES = ("rejected", "archived")

PUBLIC_REFERENCE_FIELDS = (
    "key", "status", "title", "authors", "url", "host", "mediaType", "sourceDate", "sourceUpdatedAt", "retrievedAt", "importedAt",
    "arrivedAt", "acceptedAt", "decidedAt", "section", "reasonCode", "actor", "shareable", "confidence", "predictedAcceptProbability",
    "predictionDecidedAt", "inboundCitationCount", "outboundCitationCount", "versionNumber", "image", "summary", "siteName",
)

PUBLIC_SOURCE_FIELDS = (
    "versionNumber", "title", "authors", "sourceUri", "mediaType", "sourcePublishedAt", "sourceUpdatedAt", "retrievedAt",
    "inboundCitationCount", "outboundCitationCount", "importedAt", "createdAt", "curationStatus", "curationStatusUpdatedAt",
    "curationReasonCode", "curationActorKind", "curationSectionId", "curationShareable", "feedArrivalAt", "predictedAcceptProbability",
    "predictionDecidedAt",
)

IDENTITY = "identity: can name a person or carry an address"
THIRD_PARTY_TEXT = "third-party text: republishing captured text is a copyright risk"
PLUMBING = "plumbing: an internal id, key or storage detail no reader needs"

EXCLUDED_REFERENCE_FIELDS = {
    "curationStatusUpdatedBy": IDENTITY + " (often an email)",
    "versionCreatedBy": IDENTITY,
    "curationDelegation": IDENTITY + " (who relayed the decision)",
    "curationStatusReason": IDENTITY + " (an editor's private note may name people)",
    "discoveryDetails": IDENTITY + " (intake provenance may carry email-intake addresses)",
    "discoveryRule": IDENTITY + " (intake provenance may carry email-intake addresses)",
    "changeReason": IDENTITY + " (free text written by an editor)",
    "storagePath": THIRD_PARTY_TEXT + " (where the captured body lives)",
    "sha256": THIRD_PARTY_TEXT + " (fingerprint of the captured body)",
    "byteSize": THIRD_PARTY_TEXT + " (size of the captured body)",
    "contentHash": THIRD_PARTY_TEXT + " (fingerprint of the captured body)",
    "id": PLUMBING,
    "lineageId": PLUMBING + " (only its hash is published, as key)",
    "previousVersionId": PLUMBING,
    "corpusId": PLUMBING,
    "externalItemId": PLUMBING,
    "importRunId": PLUMBING,
    "discoveredByMonitorId": PLUMBING,
    "curationDecisionRelationId": PLUMBING,
    "newsroomFeedKey": PLUMBING,
    "reviewedFeedKey": PLUMBING,
    "feedStateKey": PLUMBING,
    "predictionSortKey": PLUMBING,
    "versionState": PLUMBING + " (only current versions are read)",
    "versionCreatedAt": PLUMBING,
    "curationStatusKey": PLUMBING,
    "updatedAt": PLUMBING,
}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*\.)+[A-Za-z]{2,}")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SITE_SUBJECT = re.compile(r"ss(?:1|dev)_[A-Za-z0-9_-]{8,}")
PRIVATE_SHAPES = (EMAIL, UUID, SITE_SUBJECT)
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


class WithheldReference(ValueError):
    """A Reference whose address cannot be made public without identity in it."""


def public_key(lineage_id: str) -> str:
    return hashlib.sha256(lineage_id.encode()).hexdigest()[:KEY_LENGTH]


def accept_probability(decision: Mapping[str, Any] | None) -> float:
    """P(the editor accepts) from a ``relevance_of`` decision, as ``lib/reference-feed-ranking.ts`` ``acceptProbability`` computes it."""
    if not decision:
        return UNDECIDED_PROBABILITY
    return decision_probability(decision.get("label"), decision.get("positiveLabel"), decision.get("confidence"))


def contains_private_shape(text: str) -> bool:
    return any(pattern.search(text) for pattern in PRIVATE_SHAPES)


def scrub(text: Any) -> str | None:
    if text is None:
        return None
    cleaned = str(text)
    for pattern in PRIVATE_SHAPES:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or None


def clip_summary(text: Any, characters: int) -> str | None:
    cleaned = scrub(text)
    if cleaned is None:
        return None
    if len(cleaned) <= characters:
        return cleaned
    window = cleaned[:characters]
    ends = [match.end() for match in SENTENCE_END.finditer(window)]
    if ends:
        return window[: ends[-1]].strip()
    boundary = window.rfind(" ")
    return (window[:boundary] if boundary > 0 else window).rstrip(" ,;:") + "…"


def public_url(address: Any) -> str | None:
    """The address as it is public: a query or fragment that carries identity is dropped, and a path that does is withheld."""
    if not address:
        return None
    text = str(address).strip()
    if not contains_private_shape(text):
        return text
    parts = urlsplit(text)
    bare = parts._replace(query="", fragment="").geturl()
    if contains_private_shape(bare):
        raise WithheldReference("address carries identity")
    return bare


def host_of(address: str | None) -> str | None:
    if not address:
        return None
    host = (urlsplit(address).hostname or "").lower()
    return host.removeprefix("www.") or None


def authors_of(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [value]
    if not isinstance(value, list):
        return []
    names = (scrub(name) for name in value if isinstance(name, str))
    return [name for name in names if name]


def decimal(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return round(float(value), CONFIDENCE_DECIMALS)
    except (TypeError, ValueError):
        return None


def preview_details(preview: Mapping[str, Any] | None, summary_characters: int) -> dict[str, str | None]:
    if not preview:
        return {"image": None, "summary": None, "siteName": None}
    metadata = preview.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    metadata = metadata if isinstance(metadata, Mapping) else {}
    image = preview.get("sourceUri")
    try:
        image = public_url(image)
    except WithheldReference:
        image = None
    return {
        "image": image,
        "summary": clip_summary(metadata.get("description"), summary_characters),
        "siteName": scrub(metadata.get("siteName")),
    }


def public_reference(
    row: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
    preview: Mapping[str, Any] | None,
    section_labels: Mapping[str, str],
    settings: HomePageSettings,
) -> dict[str, Any]:
    """One public record: the allowlisted fields of ``settings.references.fields``, in allowlist order."""
    accepted = row.get("curationStatus") == STATUS_ACCEPTED
    address = public_url(row.get("sourceUri"))
    decided_at = row.get("curationStatusUpdatedAt")
    full: dict[str, Any] = {
        "key": public_key(str(row["lineageId"])),
        "status": STATUS_ACCEPTED if accepted else STATUS_RECOMMENDED,
        "title": scrub(row.get("title")) or host_of(address) or "Untitled",
        "authors": authors_of(row.get("authors")),
        "url": address,
        "host": host_of(address),
        "mediaType": row.get("mediaType"),
        "sourceDate": row.get("sourcePublishedAt"),
        "sourceUpdatedAt": row.get("sourceUpdatedAt"),
        "retrievedAt": row.get("retrievedAt"),
        "importedAt": row.get("importedAt"),
        "arrivedAt": row.get("feedArrivalAt") or row.get("createdAt"),
        "acceptedAt": decided_at if accepted else None,
        "decidedAt": decided_at,
        "section": scrub(section_labels.get(str(row.get("curationSectionId") or ""))),
        "reasonCode": row.get("curationReasonCode"),
        "actor": row.get("curationActorKind"),
        "shareable": row.get("curationShareable"),
        "confidence": decimal(accept_probability(decision)),
        "predictedAcceptProbability": decimal(row.get("predictedAcceptProbability")),
        "predictionDecidedAt": row.get("predictionDecidedAt"),
        "inboundCitationCount": row.get("inboundCitationCount"),
        "outboundCitationCount": row.get("outboundCitationCount"),
        "versionNumber": row.get("versionNumber"),
        **preview_details(preview, settings.references.summary_characters),
    }
    record = {name: full[name] for name in PUBLIC_REFERENCE_FIELDS if name in settings.references.fields}
    leaked = sorted(set(record) & set(EXCLUDED_REFERENCE_FIELDS))
    if leaked:
        raise AssertionError(f"excluded fields reached a public record: {', '.join(leaked)}")
    return record


def current_references(client: Any, index_name: str, partition_key: str) -> list[dict[str, Any]]:
    rows = client.list_by_index(index_name, partition_key)
    return [row for row in rows if row and row.get("versionState", "current") == "current" and row.get("lineageId")]


def decision_of(client: Any, row: Mapping[str, Any]) -> dict[str, Any] | None:
    relations = [relation for relation in relations_of(client, dict(row)) if relation.get("predicate") == RELEVANCE_PREDICATE]
    return relevance_of(relations)


def preview_of(client: Any, row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    attachments = [item for item in client.list_reference_attachments_by_lineage(str(row["lineageId"])) if item and item.get("role") == PREVIEW_ROLE]
    imaged = [item for item in attachments if item.get("sourceUri")]
    chosen = imaged or attachments
    return max(chosen, key=lambda item: str(item.get("importedAt") or "")) if chosen else None


def section_labels_of(client: Any) -> dict[str, str]:
    return {str(section["id"]): str(section.get("title") or "") for section in client.list_records("NewsroomSection") if section.get("id")}


def collect_references(
    client: Any,
    corpus_id: str,
    settings: HomePageSettings,
    *,
    client_factory: Callable[[], Any] | None = None,
    workers: int = 1,
) -> list[dict[str, Any]]:
    """The public records of a corpus: its accepted References, and its pending ones the Cyclotron expects an editor to accept.

    Newest accepted first, then the recommended ones newest first. Rejected, archived and superseded References are never read into
    the result. A Reference whose address would carry identity is left out rather than published.
    """
    accepted = current_references(client, "referencesByCurationStatusKey", f"{corpus_id}#{STATUS_ACCEPTED}")
    pending = [row for row in current_references(client, "referencesByFeedStateAndPrediction", f"{corpus_id}#unrated") if row.get("curationStatus") not in (STATUS_ACCEPTED, *NOT_PUBLIC_STATUSES)]
    decisions = map_with_clients([*accepted, *pending], lambda worker, row: decision_of(worker, row), client=client, client_factory=client_factory, workers=workers)
    decided = list(zip([*accepted, *pending], decisions))
    threshold = settings.references.recommended_threshold
    chosen = [(row, decision) for row, decision in decided if row.get("curationStatus") == STATUS_ACCEPTED or accept_probability(decision) >= threshold]
    previews = map_with_clients([row for row, _ in chosen], lambda worker, row: preview_of(worker, row), client=client, client_factory=client_factory, workers=workers)
    labels = section_labels_of(client)
    ordered = sorted(zip(chosen, previews), key=lambda entry: _newest_first(entry[0][0]), reverse=True)
    records: list[dict[str, Any]] = []
    for (row, decision), preview in ordered:
        try:
            records.append(public_reference(row, decision, preview, labels, settings))
        except WithheldReference:
            continue
    return records


def _newest_first(row: Mapping[str, Any]) -> tuple[int, str, str, str]:
    accepted = row.get("curationStatus") == STATUS_ACCEPTED
    return (1 if accepted else 0, str(row.get("curationStatusUpdatedAt") or "") if accepted else "", str(row.get("feedArrivalAt") or row.get("createdAt") or ""), public_key(str(row["lineageId"])))
