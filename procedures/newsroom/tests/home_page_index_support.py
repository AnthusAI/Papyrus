"""A corpus of References as the public indexes and the snapshot read it, with every request counted. Offline: nothing here touches a network or a model."""
from __future__ import annotations

import copy
import json
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from papyrus_content.reference_feed_keys import feed_keys, star_feed_key

CORPUS = "knowledge-corpus-example"
TODAY = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
SORTS = {
    "referencesByCurationStatusKey": ("curationStatusKey", "curationStatusUpdatedAt"),
    "referencesByPublicFeed": ("publicFeedKey", "publicOrderKey"),
    "referencesByFeedStateAndPrediction": ("feedStateKey", "predictionSortKey"),
    "referencesByFeedStateAndArrival": ("feedStateKey", "feedArrivalAt"),
    "referencesByStarFeedAndArrival": ("starFeedKey", "feedArrivalAt"),
    "referencesByMediumFeedAndArrival": ("mediumFeedKey", "feedArrivalAt"),
}


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def make_row(identifier: str, status: str, *, probability: float | None = None, arrived: datetime, accepted: datetime | None = None, stars: int | None = None,
             medium: str | None = None, section: str | None = None, actor: str | None = None, title: str | None = None, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"{identifier}-v1", "lineageId": identifier, "versionNumber": 1, "versionState": "current", "corpusId": CORPUS, "title": title or f"Title of {identifier}",
        "sourceUri": f"https://example.org/{identifier}", "mediaType": "text/html", "curationStatus": status, "curationStatusKey": f"{CORPUS}#{status}",
        "createdAt": stamp(arrived), "feedArrivalAt": stamp(arrived), "cardImage": f"https://img.example.org/{identifier}.jpg", "cardSummary": f"About {identifier}.",
        "cardSiteName": "Example News", "cardPageTitle": f"Page title of {identifier}", **extra,
    }
    if probability is not None:
        row["predictedAcceptProbability"] = probability
        row["predictionDecidedAt"] = stamp(arrived)
    if status == "accepted":
        row["curationStatusUpdatedAt"] = stamp(accepted or arrived)
        row["curationActorKind"] = actor or "agent"
    if stars:
        row["starRating"] = stars
        row["starFeedKey"] = star_feed_key(CORPUS, stars)
    if medium:
        row["medium"] = medium
        row["mediumFeedKey"] = f"{CORPUS}#{medium}#{status}"
        if medium == "video":
            row["thumbnailPath"] = "assets/reference-thumbnails/0123456789abcdef-0123456789ab.jpg"
            row["cardImage"] = "/" + row["thumbnailPath"]
    if section:
        row["curationSectionId"] = section
    row.update(feed_keys(row))
    return row


def make_corpus(*, days: int = 14, accepted_per_day: int = 2, pending_per_day: int = 40, seed: int = 7, starred: int = 3, videos: int = 2, places: int = 2) -> list[dict[str, Any]]:
    """A deterministic corpus: ``accepted_per_day`` accepted rows and ``pending_per_day`` pending ones for each of ``days`` days, some starred, a few videos,
    pending rows of every prediction (including none and under one half), one rejected and one archived row, and a superseded version."""
    generator = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for day in range(days):
        moment = TODAY - timedelta(days=day)
        for slot in range(accepted_per_day):
            arrived = moment - timedelta(hours=slot + 1)
            scored = generator.random() > 0.2
            rows.append(make_row(f"acc-{day}-{slot}", "accepted", probability=round(generator.uniform(0.05, 0.99), places) if scored else None, arrived=arrived,
                                 accepted=arrived + timedelta(minutes=30), actor="human" if slot == 0 else "cyclotron", section="s-tools" if slot == 0 else None))
        for slot in range(pending_per_day):
            arrived = moment - timedelta(minutes=slot * 7 + 1)
            kind = generator.random()
            probability = None if kind < 0.1 else round(generator.uniform(0.0, 0.49), places) if kind < 0.4 else round(generator.uniform(0.5, 0.99), places)
            rows.append(make_row(f"pen-{day}-{slot}", "pending", probability=probability, arrived=arrived))
    rows.append(make_row("rej-0", "rejected", probability=0.9, arrived=TODAY - timedelta(hours=3)))
    rows.append(make_row("arc-0", "archived", probability=0.9, arrived=TODAY - timedelta(hours=4)))
    old = make_row("sup-0", "accepted", probability=0.99, arrived=TODAY - timedelta(hours=5), accepted=TODAY - timedelta(hours=4))
    old["versionState"] = "superseded"
    for name in ("publicFeedKey", "publicOrderKey", "feedStateKey"):
        old[name] = None
    rows.append(old)
    candidates = [row for row in rows if row["curationStatus"] in ("accepted", "pending") and row.get("predictedAcceptProbability", 0) >= 0.5 and row["versionState"] == "current"]
    for position, row in enumerate(candidates[:starred]):
        level = (5, 2, 4)[position % 3]
        row["starRating"], row["starFeedKey"] = level, star_feed_key(CORPUS, level)
    for position in range(videos):
        rows.append(make_row(f"vid-{position}", "accepted", probability=0.8, arrived=TODAY - timedelta(days=position, hours=2), accepted=TODAY - timedelta(days=position, hours=1),
                             medium="video"))
    return rows


class IndexedClient:
    """The client calls both paths make, answered from a list of rows, counting each request.

    ``requests`` counts the pages the index reader pulled (one request each), the snapshot path's list reads, and the per-row reads (decisions and previews)."""

    def __init__(self, rows: list[dict[str, Any]], sections: dict[str, str] | None = None, *, with_attachments: bool = True) -> None:
        self.rows = [copy.deepcopy(row) for row in rows]
        self.sections = sections if sections is not None else {"s-tools": "Tools"}
        self.requests: Counter[str] = Counter()
        self.with_attachments = with_attachments

    def reset(self) -> None:
        self.requests.clear()

    def total(self) -> int:
        return sum(self.requests.values())

    def _partition(self, index: str, key: str) -> list[dict[str, Any]]:
        partition, sort = SORTS[index]
        return sorted((row for row in self.rows if row.get(partition) == key), key=lambda row: str(row.get(sort) or ""))

    def iterate_pages(self, index: str, key: str, *, page_size: int = 100, descending: bool = True) -> Iterator[list[dict[str, Any]]]:
        rows = self._partition(index, key)
        if descending:
            rows.reverse()
        for start in range(0, max(len(rows), 1), page_size):
            self.requests[index] += 1
            yield copy.deepcopy(rows[start:start + page_size])
            if start + page_size >= len(rows):
                return

    # the snapshot path
    def list_by_index(self, index: str, key: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._partition(index, key)
        self.requests["snapshot:" + index] += max(1, -(-len(rows) // limit))
        return copy.deepcopy(rows)

    def list_semantic_relations_by_subject_state(self, key: str) -> list[dict[str, Any]]:
        self.requests["snapshot:decision"] += 1
        return []

    def list_reference_attachments_by_lineage(self, lineage: str) -> list[dict[str, Any]]:
        self.requests["snapshot:preview"] += 1
        row = next((row for row in self.rows if row["lineageId"] == lineage and row["versionState"] == "current"), None)
        if row is None or not self.with_attachments:
            return []
        metadata = {"description": row.get("cardSummary"), "siteName": row.get("cardSiteName"), "title": row.get("cardPageTitle")}
        source = row.get("cardImage")
        if row.get("medium") == "video":
            source = "https://i.ytimg.com/vi/x/hqdefault.jpg"   # the platform's own picture: the snapshot never publishes it for a video
        return [{"role": "preview", "sourceUri": source, "importedAt": row["createdAt"], "metadata": json.dumps(metadata)}]

    def list_records(self, model: str) -> list[dict[str, Any]]:
        assert model == "NewsroomSection", model
        self.requests["sections"] += 1
        return [{"id": identifier, "title": title} for identifier, title in self.sections.items()]
