"""Reference rows in, public-safe records out.

Every exported record is built from ``PUBLIC_REFERENCE_FIELDS`` and nothing else. ``EXCLUDED_REFERENCE_FIELDS`` names every other
Reference field with the reason it stays private, and a unit test proves that together the two cover each field of the Reference model
exactly once. Text that leaves the building is scrubbed of anything shaped like an email address, a UUID or a site subject.

Nothing here imports the CLI login library: the Lambda bundles that run the snapshot task do not ship it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ..public_text import PRIVATE_SHAPES, WithheldReference, contains_private_shape, public_url, scrub  # noqa: F401 - re-exported: the scrub rule moved to public_text.py
from ..reference_public_fields import chosen_preview, preview_metadata
from ..ideas.digest import RELEVANCE_PREDICATE, relations_of, relevance_of
from ..knowledge_snapshot.parallel import map_with_clients
from ..reference_medium import MEDIUM_VIDEO, medium_of
from ..reference_thumbnails import EDITOR_IMAGE, public_image as thumbnail_image
from ..reference_feed_keys import accept_probability as decision_probability
from ..reference_titles import first_usable_title, needs_title, readable_name
from ..tenancy import STORED_RECORD_ID_FIELD
from .ordering import RANK_FIELD, rank_records, valid_stars

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
    "arrivedAt", "acceptedAt", "decidedAt", "section", "reasonCode", "actor", "shareable", "stars", "confidence", "predictedAcceptProbability",
    "predictionDecidedAt", "inboundCitationCount", "outboundCitationCount", "versionNumber", "medium", "image", "summary", "siteName",
    RANK_FIELD,
)
#: ``rank`` is a position in the shared order (``ordering.py``), never a star count. The build orders by it, so every record has it whatever ``homePage.references.fields`` lists.
ALWAYS_PUBLISHED_FIELDS = (RANK_FIELD,)

PUBLIC_SOURCE_FIELDS = (
    "versionNumber", "title", "authors", "sourceUri", "mediaType", "sourcePublishedAt", "sourceUpdatedAt", "retrievedAt",
    "inboundCitationCount", "outboundCitationCount", "importedAt", "createdAt", "curationStatus", "curationStatusUpdatedAt",
    "curationReasonCode", "curationActorKind", "curationSectionId", "curationShareable", "feedArrivalAt", "predictedAcceptProbability",
    "predictionDecidedAt", "medium", "thumbnailPath", "starRating",
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
    "curationSectionUpdatedBy": IDENTITY + " (who set the Section)",
    "curationSectionUpdatedAt": "editorial provenance: when the Section was set is private; the pages treat a machine and a person's Section the same",
    "curationSectionActorKind": "editorial provenance: whether a person or the site cyclotron set the Section is private (docs/reference-auto-section.md)",
    "curationSectionReason": "editorial provenance: the machine's evidence for its Section",
    "curationSectionDecisionRelationId": PLUMBING,
    "starRatedAt": "editorial signal: when an editor rated it is private (the count itself is published as stars on an accepted Reference)",
    "starRatedBy": IDENTITY + " (who rated it)",
    "newsroomFeedKey": PLUMBING,
    "reviewedFeedKey": PLUMBING,
    "feedStateKey": PLUMBING,
    "predictionSortKey": PLUMBING,
    "starFeedKey": PLUMBING,
    "captureState": PLUMBING,
    "mediumFeedKey": PLUMBING,
    "contentNeededKey": PLUMBING,
    "publicFeedKey": PLUMBING + " (the public-blocks index partition, PPY-7f1e54)",
    "publicOrderKey": PLUMBING + " (the public-blocks index sort key, PPY-7f1e54)",
    "cardImage": "card copy: the picture address a card shows, stored on the row so a block needs no attachment read; published as image, never under this name",
    "cardSummary": "card copy: the preview description, scrubbed and not clipped; published (clipped) as summary, never under this name",
    "cardSiteName": "card copy: the preview site name, scrubbed; published as siteName, never under this name",
    "cardPageTitle": "card copy: the title the page declared for link previews, scrubbed; a card that still has only an address for a title shows it (displayed_title), never under this name",
    "captureReason": PLUMBING,
    "evidenceLevel": "editorial classification: not shown to readers yet (the decision model will write it, PPY-f8ff49)",
    "playlistUrl": "plumbing: the playlist a video address also names, kept for following it later (PPY-566e82)",
    "versionState": PLUMBING + " (only current versions are read)",
    "versionCreatedAt": PLUMBING,
    "curationStatusKey": PLUMBING,
    "updatedAt": PLUMBING,
}

SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def public_key(lineage_id: str) -> str:
    return hashlib.sha256(lineage_id.encode()).hexdigest()[:KEY_LENGTH]


def accept_probability(decision: Mapping[str, Any] | None) -> float | None:
    """P(the editor accepts) from a ``relevance_of`` decision, as ``lib/reference-feed-ranking.ts`` ``acceptProbability`` computes it; None with no decision.

    No decision is not 0.5: a number here would read as a prediction. The Newsroom's own feed still sorts an unpredicted Reference as 0.5, which is an editor's
    queue and shows no confidence; nothing public does.
    """
    if not decision:
        return None
    return decision_probability(decision.get("label"), decision.get("positiveLabel"), decision.get("confidence"))


def stored_prediction(row: Mapping[str, Any]) -> float | None:
    """The Cyclotron's original P(accept) written onto the row (``predictedAcceptProbability``), or None when the row has none.

    This is the one definition of "a real prediction" on the row, and the home-page trigger (``amplify/plugins/home-page/function/handler.py``, ``can_show``,
    which cannot import this package) mirrors it; a test feeds both the same rows. Only a finite number counts. ``predictionDecidedAt`` always
    travels with it (they are written together, once) and is not the test. ``predictionSortKey`` is NOT evidence: every Reference gets one at creation,
    ``0.500000#...`` for an unpredicted row, because the index needs a sort key, so it says nothing about whether a prediction exists.
    """
    value = row.get("predictedAcceptProbability")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return min(1.0, max(0.0, float(value)))


def has_prediction(row: Mapping[str, Any]) -> bool:
    return stored_prediction(row) is not None


def live_probability(row: Mapping[str, Any], decision: Mapping[str, Any] | None) -> float | None:
    """The P(accept) a card shows and the order reads: the current decision's, else the row's stored prediction, else None (never a stand-in number)."""
    live = accept_probability(decision)
    return live if live is not None else stored_prediction(row)


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
    metadata = preview_metadata(preview)
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


def displayed_title(row: Mapping[str, Any], address: str | None, preview: Mapping[str, Any] | None) -> str:
    """The title a card shows. A Reference titled with its own address shows the title its page declared for link previews when the preview holds one,
    else a readable name made from the site and the address's own words (reference_titles.readable_name); never the raw address. Display only: the
    stored title is left to the repair (``papyrus references repair-titles``) and to capture."""
    title = None if needs_title(row) else scrub(row.get("title"))
    if title:
        return title
    metadata = preview_metadata(preview)
    found = first_usable_title(scrub(metadata.get("title")))
    if found:
        return found
    if address:
        return readable_name(address, scrub(metadata.get("siteName")))
    return host_of(address) or "Untitled"


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
        "title": displayed_title(row, address, preview),
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
        # An accepted Reference shows the count an editor gave it (1 to 5); who gave it and when stay private. A pending one shows its confidence instead, and a
        # Reference nobody rated has no count. The rank, which orders the page, is computed from the row in every case.
        "stars": valid_stars(row.get("starRating")) if accepted else None,
        # Once an editor has accepted a Reference the Cyclotron's confidence no longer matters, so it is not published (the rank, which
        # orders the page, is computed from the row, below). A Reference accepted by a Cyclotron or a rule keeps it, and so does a pending one.
        "confidence": None if accepted and row.get("curationActorKind") == "human" else decimal(live_probability(row, decision)),
        "predictedAcceptProbability": decimal(row.get("predictedAcceptProbability")),
        "predictionDecidedAt": row.get("predictionDecidedAt"),
        "inboundCitationCount": row.get("inboundCitationCount"),
        "outboundCitationCount": row.get("outboundCitationCount"),
        "versionNumber": row.get("versionNumber"),
        "medium": row.get("medium") or medium_of(row.get("sourceUri")),
        **preview_details(preview, settings.references.summary_characters),
    }
    if full["medium"] == MEDIUM_VIDEO and preview_metadata(preview).get("via") != EDITOR_IMAGE:
        # A video's card shows its own thumbnail from our storage, never an address on the platform (a reader's browser must not contact it,
        # and a takedown must not break the card). No copy yet means no image. An image an editor set is the exception: it is theirs.
        full["image"] = thumbnail_image(row)
    record = {name: full[name] for name in PUBLIC_REFERENCE_FIELDS if name in settings.references.fields and name in full}
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
    return chosen_preview(client.list_reference_attachments_by_lineage(str(row["lineageId"])))   # the rule the card copies on the row share


def section_labels_of(client: Any) -> dict[str, str]:
    """Section titles keyed by the section id exactly as a Reference's ``curationSectionId`` (and a thread's ``sectionId``) stores it.

    The client hands a section back with its tenant prefix stripped from ``id`` and the stored form in ``storedId`` ("publication#slug"); a
    client of a backend without a tenant has no ``storedId`` and ``id`` is the stored form. Keying by the stored form means every lookup is a
    plain one, and an id that matches no section finds no title.
    """
    return {
        str(section.get(STORED_RECORD_ID_FIELD) or section["id"]): str(section.get("title") or "")
        for section in client.list_records("NewsroomSection")
        if section.get("id")
    }


@dataclass(frozen=True)
class Standing:
    """What the shared order (and the run that keeps the snapshot current) remembers about one public Reference besides its public record.

    ``stars`` is an editor's private rating and ``confidence`` the live P(accept) the order reads (a record that an editor accepted does not
    publish it), so a Standing is never written to a public file: it lives only in the private state the home-page task keeps
    (``incremental.py``). ``id`` is the id of the Reference version the record was built from, ``arrived`` its arrival time and ``section`` its
    section id, which the section label is looked up from on every run.
    """

    id: str
    stars: int | None
    confidence: float | None
    arrived: str | None
    section: str | None

    def to_json(self) -> list[Any]:
        return [self.id, self.stars, self.confidence, self.arrived, self.section]

    @classmethod
    def from_json(cls, value: Any) -> Standing:
        identifier, stars, confidence, arrived, section = value
        return cls(str(identifier), stars, confidence, arrived, section)


@dataclass(frozen=True)
class PublicEntry:
    """A public record without its ``rank`` (the rank is a position among all the records), and the Standing the rank is computed from."""

    key: str
    record: dict[str, Any]
    standing: Standing


def entry_of(
    row: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
    preview: Mapping[str, Any] | None,
    section_labels: Mapping[str, str],
    settings: HomePageSettings,
) -> PublicEntry:
    """The public entry of a row; raises ``WithheldReference`` when its address would carry identity."""
    record = public_reference(row, decision, preview, section_labels, settings)
    standing = Standing(
        id=str(row["id"]),
        stars=valid_stars(row.get("starRating")),
        confidence=decimal(live_probability(row, decision)),
        arrived=row.get("feedArrivalAt") or row.get("createdAt"),
        section=row.get("curationSectionId") or None,
    )
    return PublicEntry(public_key(str(row["lineageId"])), record, standing)


def ranked_records(entries: Iterable[PublicEntry]) -> list[dict[str, Any]]:
    """The entries' records with their ``rank`` in the shared order (``ordering.py``), in the order the entries came."""
    chosen = list(entries)
    # An editor's stars order the page and stay here: only the position they give each Reference is published.
    ranks = rank_records(({"key": entry.key, "confidence": entry.standing.confidence, "arrivedAt": entry.standing.arrived}, entry.standing.stars) for entry in chosen)
    return [{**entry.record, RANK_FIELD: ranks[entry.key]} for entry in chosen]


def is_listed(row: Mapping[str, Any], corpus_id: str) -> bool:
    """True for a row the full read would consider: a current Reference that is in the corpus's accepted list, or in its unrated list and not decided."""
    if row.get("versionState", "current") != "current" or not row.get("lineageId"):
        return False
    if row.get("curationStatusKey") == f"{corpus_id}#{STATUS_ACCEPTED}":
        return True
    return row.get("feedStateKey") == f"{corpus_id}#unrated" and row.get("curationStatus") not in (STATUS_ACCEPTED, *NOT_PUBLIC_STATUSES)


def is_chosen(row: Mapping[str, Any], decision: Mapping[str, Any] | None, settings: HomePageSettings) -> bool:
    """An accepted Reference is public. A pending one is public only when it has a real prediction (``stored_prediction``) and its live P(accept) reaches the
    threshold; a prediction of exactly the threshold (0.5 by default) is a prediction and passes. No prediction is never a number, so it never passes."""
    if row.get("curationStatus") == STATUS_ACCEPTED:
        return True
    probability = live_probability(row, decision) if has_prediction(row) else None
    return probability is not None and probability >= settings.references.recommended_threshold


def entry_for_row(client: Any, row: Mapping[str, Any], corpus_id: str, settings: HomePageSettings, labels: Mapping[str, str]) -> PublicEntry | None:
    """The public entry of one row, read the way the full read reads it: its decision, then (only when it will show) its preview. ``None`` when it is not public.

    The cost is a fixed three requests at most, whatever the size of the corpus.
    """
    if not is_listed(row, corpus_id):
        return None
    if row.get("curationStatus") != STATUS_ACCEPTED and not has_prediction(row):
        return None   # nothing is predicted yet: it is on no page, and its relations are not read
    decision = decision_of(client, row)
    if not is_chosen(row, decision, settings):
        return None
    try:
        return entry_of(row, decision, preview_of(client, row), labels, settings)
    except WithheldReference:
        return None


def collect_entries(
    client: Any,
    corpus_id: str,
    settings: HomePageSettings,
    *,
    client_factory: Callable[[], Any] | None = None,
    workers: int = 1,
) -> list[PublicEntry]:
    """Every public entry of a corpus, newest accepted first and then the recommended ones (pending, with a real prediction) newest first, read from the whole corpus (a full read)."""
    accepted = current_references(client, "referencesByCurationStatusKey", f"{corpus_id}#{STATUS_ACCEPTED}")
    pending = [row for row in current_references(client, "referencesByFeedStateAndPrediction", f"{corpus_id}#unrated") if row.get("curationStatus") not in (STATUS_ACCEPTED, *NOT_PUBLIC_STATUSES) and has_prediction(row)]
    decisions = map_with_clients([*accepted, *pending], lambda worker, row: decision_of(worker, row), client=client, client_factory=client_factory, workers=workers)
    decided = list(zip([*accepted, *pending], decisions))
    chosen = [(row, decision) for row, decision in decided if is_chosen(row, decision, settings)]
    previews = map_with_clients([row for row, _ in chosen], lambda worker, row: preview_of(worker, row), client=client, client_factory=client_factory, workers=workers)
    labels = section_labels_of(client)
    ordered = sorted(zip(chosen, previews), key=lambda entry: _newest_first(entry[0][0]), reverse=True)
    kept: list[PublicEntry] = []
    for (row, decision), preview in ordered:
        try:
            kept.append(entry_of(row, decision, preview, labels, settings))
        except WithheldReference:
            continue
    return kept


def collect_references(
    client: Any,
    corpus_id: str,
    settings: HomePageSettings,
    *,
    client_factory: Callable[[], Any] | None = None,
    workers: int = 1,
) -> list[dict[str, Any]]:
    """The public records of a corpus: its accepted References, and its pending ones the Cyclotron expects an editor to accept.

    Newest accepted first, then the recommended ones newest first, each with its ``rank`` in the shared order (``ordering.py``). Rejected, archived and superseded References are never read into
    the result. A Reference whose address would carry identity is left out rather than published.

    This reads the whole corpus. The Lambda does it once, to start the private state ``incremental.py`` keeps; after that a change costs a fixed number of requests.
    """
    return ranked_records(collect_entries(client, corpus_id, settings, client_factory=client_factory, workers=workers))


def _newest_first(row: Mapping[str, Any]) -> tuple[int, str, str, str]:
    accepted = row.get("curationStatus") == STATUS_ACCEPTED
    return (1 if accepted else 0, str(row.get("curationStatusUpdatedAt") or "") if accepted else "", str(row.get("feedArrivalAt") or row.get("createdAt") or ""), public_key(str(row["lineageId"])))
