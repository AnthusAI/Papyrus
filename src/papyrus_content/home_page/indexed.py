"""The public blocks of a page, read from the indexes they show (``homePage.references.source: "index"``; docs/plans/public-blocks-from-indexes.md, PPY-7f1e54).

The snapshot path reads every public Reference into one file and every block picks its few cards from it in memory. Here a block asks for exactly the rows it
shows, in the order it shows them, and each row already carries what its card needs (``cardImage``, ``cardSummary``, ``cardSiteName``, ``cardPageTitle``), so
no decision and no preview is read. :class:`IndexReader` turns one include's attributes into the smallest set of public records for which the unchanged block
code (``projection/standard/home_page_blocks.py``) chooses exactly what it would choose from the whole file, so the HTML does not change.

* ``recent`` reads the accepted list newest accepted first (``curationStatusKey``); ``confident`` reads the accepted partition of the public index by stored
  prediction; ``recommended`` reads the pending partition of the prediction index down to the threshold. A block asks for ``count + placed`` rows, ``placed``
  being what the page already shows (the page ledger skips them), and reads whole tie groups so the order at the cut is the order of the file.
* An editor's stars order the page (3 to 5 first, 1 and 2 last) and are private, so they are in no key: the star partitions are read once per run and
  their rows are placed by their stars wherever they arrived; the confidence order skips them so each row is placed once.
* ``bucket`` windows are the rolling windows of ``ordering.rolling_age``: accepted rows are read newest accepted first until the windows read hold enough;
  recommended rows are read one day partition of the public index at a time (a ``week`` is seven queries), newest window first.
* ``medium="video"`` reads the video partitions (small by nature) and orders them in memory; ``section`` reads on until it has enough matches.
* A row is ordered by its stored original prediction at full precision. The snapshot ranks on the prediction rounded to two places; the two orders differ
  only inside a rounding tier (the parity command says so).

The reader counts its requests by kind (``requests``) so a test can hold it to the numbers in the design.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..public_text import WithheldReference, public_url, scrub
from ..reference_feed_keys import PUBLIC_RECOMMENDED, stored_probability
from ..reference_medium import MEDIUM_VIDEO, medium_of
from .export import (
    PUBLIC_REFERENCE_FIELDS,
    EXCLUDED_REFERENCE_FIELDS,
    STATUS_ACCEPTED,
    STATUS_RECOMMENDED,
    authors_of,
    clip_summary,
    decimal,
    displayed_title,
    host_of,
    public_key,
)
from .ordering import BUCKET_DAYS, RANK_FIELD, bucket_moment, ordered, rolling_age, valid_stars
from .settings import HomePageSettings

PAGE_SIZE = 100
WHOLE = 2**62   # a paged list is the whole selection: the block reads to the end of it
NOT_PENDING = ("accepted", "rejected", "archived")


@dataclass
class Item:
    """One public Reference as a block orders it: its public record, and the private signals the order reads (stars and the stored prediction)."""

    row: Mapping[str, Any]
    record: dict[str, Any]
    stars: int | None
    probability: float | None
    key: str
    arrived: str
    accepted_at: str

    @property
    def identifier(self) -> str:
        return str(self.row["id"])


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def indexed_record(row: Mapping[str, Any], labels: Mapping[str, str], settings: HomePageSettings) -> dict[str, Any]:
    """The public record of a row, from the row alone (its card copies stand in for the preview). Raises ``WithheldReference`` as the snapshot's builder does.

    The same fields, the same scrubbing and the same title rule as ``export.public_reference``; the confidence is the stored original prediction."""
    accepted = row.get("curationStatus") == STATUS_ACCEPTED
    address = public_url(row.get("sourceUri"))
    decided_at = row.get("curationStatusUpdatedAt")
    probability = stored_probability(row.get("predictedAcceptProbability"))
    page = {"metadata": {"title": row.get("cardPageTitle"), "siteName": row.get("cardSiteName")}}
    full: dict[str, Any] = {
        "key": public_key(str(row["lineageId"])),
        "status": STATUS_ACCEPTED if accepted else STATUS_RECOMMENDED,
        "title": displayed_title(row, address, page),
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
        "section": scrub(labels.get(str(row.get("curationSectionId") or ""))),
        "reasonCode": row.get("curationReasonCode"),
        "actor": row.get("curationActorKind"),
        "shareable": row.get("curationShareable"),
        "stars": valid_stars(row.get("starRating")) if accepted else None,
        "confidence": None if accepted and row.get("curationActorKind") == "human" else decimal(probability),
        "predictedAcceptProbability": decimal(row.get("predictedAcceptProbability")),
        "predictionDecidedAt": row.get("predictionDecidedAt"),
        "inboundCitationCount": row.get("inboundCitationCount"),
        "outboundCitationCount": row.get("outboundCitationCount"),
        "versionNumber": row.get("versionNumber"),
        "medium": row.get("medium") or medium_of(row.get("sourceUri")),
        "image": row.get("cardImage") or None,
        "summary": clip_summary(row.get("cardSummary"), settings.references.summary_characters),
        "siteName": scrub(row.get("cardSiteName")),
    }
    record = {name: full[name] for name in PUBLIC_REFERENCE_FIELDS if name in settings.references.fields and name in full}
    leaked = sorted(set(record) & set(EXCLUDED_REFERENCE_FIELDS))
    if leaked:
        raise AssertionError(f"excluded fields reached a public record: {', '.join(leaked)}")
    return record


def _shared_order(items: Iterable[Item]) -> list[Item]:
    """The items in the shared order of ``ordering.py``: 3 to 5 stars, then unrated by prediction (the unscored last), then newest, then key; 1 and 2 stars last."""
    return ordered(items, stars=lambda item: item.stars, confidence=lambda item: item.probability, newest=lambda item: item.arrived, key=lambda item: item.key)


def _recent_order(items: Iterable[Item]) -> list[Item]:
    """Newest accepted first, then newest arrival, then key (the ``recent`` order of ``home_page_blocks.ordered``)."""
    chosen = sorted(items, key=lambda item: item.key)
    chosen.sort(key=lambda item: item.arrived, reverse=True)
    chosen.sort(key=lambda item: item.accepted_at, reverse=True)
    return chosen


def _groups(stream: Iterator[Item], group_key: Callable[[Item], Any], order: Callable[[Iterable[Item]], list[Item]]) -> Iterator[list[Item]]:
    """Consecutive items that tie on ``group_key`` as one sorted group, so a cut never falls inside a tie."""
    held: list[Item] = []
    held_key: Any = None
    for item in stream:
        value = group_key(item)
        if held and value != held_key:
            yield order(held)
            held = []
        held.append(item)
        held_key = value
    if held:
        yield order(held)


class IndexReader:
    """The index reads of one run. Everything it reads is remembered, so two pages that ask the same question share the answer."""

    def __init__(self, client: Any, corpus_id: str, settings: HomePageSettings, labels: Callable[[], Mapping[str, str]] | None = None) -> None:
        self.client, self.corpus_id, self.settings = client, corpus_id, settings
        self.threshold = settings.references.recommended_threshold
        self.requests: Counter[str] = Counter()
        self._labels_loader = labels
        self._labels: Mapping[str, str] | None = None
        self._starred: dict[str, Any] | None = None
        self._earliest: date | None | bool = False
        self._blocks: dict[str, Block] = {}
        self._partitions: dict[tuple[str, str, bool], dict[str, Any]] = {}
        self._days: dict[str, DayRows] = {}

    # ------------------------------------------------------------------ reads

    def pages(self, kind: str, index: str, partition: str, *, descending: bool = True) -> Iterator[list[dict[str, Any]]]:
        """The pages of an index partition, read as far as a caller goes and remembered, so two blocks that read the same partition share the pages they both need."""
        entry = self._partitions.setdefault((index, partition, descending), {"source": None, "pages": [], "done": False})
        position = 0
        while True:
            if position < len(entry["pages"]):
                yield entry["pages"][position]
                position += 1
                continue
            if entry["done"]:
                return
            if entry["source"] is None:
                entry["source"] = iter(self.client.iterate_pages(index, partition, page_size=PAGE_SIZE, descending=descending))
            page = next(entry["source"], None)
            if page is None:
                entry["done"] = True
                return
            self.requests[kind] += 1
            entry["pages"].append(page)

    def labels(self) -> Mapping[str, str]:
        if self._labels is None:
            if self._labels_loader is not None:
                self._labels = self._labels_loader()
            else:
                self.requests["sections"] += 1
                self._labels = {str(section["id"]): str(section.get("title") or "") for section in self.client.list_records("NewsroomSection") if section.get("id")}
        return self._labels

    def is_current(self, row: Mapping[str, Any] | None) -> bool:
        return bool(row) and row.get("versionState", "current") == "current" and bool(row.get("lineageId"))

    def is_shown(self, row: Mapping[str, Any]) -> bool:
        """A row a page may show: accepted, or pending with a stored prediction that reaches the threshold (a missing prediction is never a number)."""
        if row.get("curationStatus") == STATUS_ACCEPTED:
            return True
        probability = stored_probability(row.get("predictedAcceptProbability"))
        return row.get("curationStatus") not in NOT_PENDING and probability is not None and probability >= self.threshold

    def item(self, row: Mapping[str, Any]) -> Item | None:
        try:
            record = indexed_record(row, self.labels(), self.settings)
        except WithheldReference:
            return None
        return Item(row=row, record=record, stars=valid_stars(row.get("starRating")), probability=stored_probability(row.get("predictedAcceptProbability")),
                    key=str(record["key"]), arrived=_text(record.get("arrivedAt")), accepted_at=_text(row.get("curationStatusUpdatedAt")) if row.get("curationStatus") == STATUS_ACCEPTED else "")

    def starred(self) -> dict[str, Mapping[str, Any]]:
        """Every row an editor starred and a page may show, by id: the five star partitions, read once per run."""
        if self._starred is None:
            found: dict[str, Mapping[str, Any]] = {}
            for level in (5, 4, 3, 2, 1):
                for page in self.pages("stars", "referencesByStarFeedAndArrival", f"{self.corpus_id}#stars#{level}"):
                    for row in page:
                        if self.is_current(row) and valid_stars(row.get("starRating")) == level and self.is_shown(row):
                            found[str(row["id"])] = row
            self._starred = found
        return self._starred

    def earliest_day(self) -> date | None:
        """The day the oldest pending Reference arrived (one request), where the windows of a recommended block stop."""
        if self._earliest is False:
            self._earliest = None
            for page in self.pages("earliest", "referencesByFeedStateAndArrival", f"{self.corpus_id}#unrated", descending=False):
                for row in page:
                    moment = _text(row.get("feedArrivalAt"))[:10]
                    if moment:
                        self._earliest = date.fromisoformat(moment)
                        break
                break
        return self._earliest or None

    # ------------------------------------------------------------------ the streams

    def accepted_by_time(self) -> Iterator[Mapping[str, Any]]:
        for page in self.pages("accepted", "referencesByCurationStatusKey", f"{self.corpus_id}#accepted"):
            for row in page:
                if self.is_current(row) and row.get("curationStatus") == STATUS_ACCEPTED:
                    yield row

    def accepted_by_confidence(self) -> Iterator[Mapping[str, Any]]:
        for page in self.pages("accepted", "referencesByPublicFeed", f"{self.corpus_id}#accepted"):
            for row in page:
                if self.is_current(row) and row.get("curationStatus") == STATUS_ACCEPTED:
                    yield row

    def pending_by_confidence(self) -> Iterator[Mapping[str, Any]]:
        """Pending rows, highest stored prediction first, read from the prediction index down to the threshold and no further."""
        floor = f"{self.threshold:.6f}"
        for page in self.pages("recommended", "referencesByFeedStateAndPrediction", f"{self.corpus_id}#unrated"):
            for row in page:
                if str(row.get("predictionSortKey") or "") < floor:
                    return
                if self.is_current(row) and self.is_shown(row) and row.get("curationStatus") != STATUS_ACCEPTED:
                    yield row

    def video_rows(self, status: str) -> list[Mapping[str, Any]]:
        rows = []
        for page in self.pages("video", "referencesByMediumFeedAndArrival", f"{self.corpus_id}#{MEDIUM_VIDEO}#{status}"):
            rows.extend(row for row in page if self.is_current(row) and self.is_shown(row))
        return rows

    def day_rows(self, day: date) -> "DayRows":
        key = day.isoformat()
        if key not in self._days:
            self._days[key] = DayRows(self, day)
        return self._days[key]

    # ------------------------------------------------------------------ blocks

    def block(self, attributes: Mapping[str, Any], as_of: date, section_labels: Mapping[str, str] | None = None) -> "Block":
        key = block_key(attributes, as_of)
        if key not in self._blocks:
            self._blocks[key] = Block(self, attributes, as_of, section_labels or {})
        return self._blocks[key]

    def block_states(self) -> dict[str, dict[str, Any]]:
        """What each block read this run remembers for the stream router (``routing.py``)."""
        return {key: block.state() for key, block in self._blocks.items()}


class DayRows:
    """The pending rows of one day partition of the public index, highest prediction first, pulled as far as a block needs and remembered."""

    def __init__(self, reader: IndexReader, day: date) -> None:
        self.reader, self.day = reader, day
        self.groups: list[list[Item]] = []
        self.count = 0
        self.done = False
        self._stream = _groups(self._items(), lambda item: (item.probability, item.arrived), _shared_order)

    def _items(self) -> Iterator[Item]:
        starred = self.reader.starred()
        for page in self.reader.pages("recommended", "referencesByPublicFeed", f"{self.reader.corpus_id}#{PUBLIC_RECOMMENDED}#{self.day.isoformat()}"):
            for row in page:
                if self.reader.is_current(row) and row.get("curationStatus") not in NOT_PENDING and self.reader.is_shown(row) and str(row["id"]) not in starred:
                    item = self.reader.item(row)
                    if item is not None:
                        yield item

    def take(self, wanted: int) -> list[Item]:
        while self.count < wanted and not self.done:
            group = next(self._stream, None)
            if group is None:
                self.done = True
            else:
                self.groups.append(group)
                self.count += len(group)
        return [item for group in self.groups for item in group]


def block_key(attributes: Mapping[str, Any], as_of: date) -> str:
    """The identity of a block's question: its attributes that change the answer, and the day when it is windowed (a rolling window moves with the day)."""
    relevant = {name: attributes[name] for name in ("select", "section", "bucket", "medium", "paged") if attributes.get(name)}
    if relevant.get("bucket"):
        relevant["asOf"] = as_of.isoformat()
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class Block:
    """One include's question, answered as far as pages have asked: ``items`` are the rows pulled, in the order the block places them."""

    def __init__(self, reader: IndexReader, attributes: Mapping[str, Any], as_of: date, section_labels: Mapping[str, str]) -> None:
        self.reader, self.attributes, self.as_of, self.section_labels = reader, attributes, as_of, section_labels
        self.selection = str(attributes["select"])
        self.bucket = attributes.get("bucket")
        self.medium = attributes.get("medium")
        self.section = attributes.get("section")
        self.whole = attributes.get("paged") == "true"
        self.items: list[Item] = []
        self.exhausted = False
        self.wanted = 0
        self._chunks = self._build()
        self._matched = 0

    # ---- filters

    def _matches(self, item: Item) -> bool:
        from ..projection.standard.home_page_blocks import _in_section

        if self.medium and item.record.get("medium") != self.medium:
            return False
        if self.section and not _in_section(item.record, self.section, self.section_labels):
            return False
        return True

    # ---- the chunks, in the order the block places them (each is a list of items that may be placed together)

    def _build(self) -> Iterator[list[Item]]:
        if self.bucket:
            return self._windows()
        return self._flat()

    def _rows_items(self, rows: Iterable[Mapping[str, Any]]) -> Iterator[Item]:
        for row in rows:
            item = self.reader.item(row)
            if item is not None and self._matches(item):
                yield item

    def _medium_items(self) -> list[Item]:
        """A medium's rows are few: all of them, ordered in memory."""
        status = "accepted" if self.selection != "recommended" else "pending"
        return list(self._rows_items(self.reader.video_rows(status)))

    def _flat(self) -> Iterator[list[Item]]:
        reader = self.reader
        if self.medium:
            items = self._medium_items()
            yield from [[item] for item in (_recent_order(items) if self.selection == "recent" else _shared_order(items))]
            return
        if self.selection == "recent":
            yield from _groups(self._rows_items(reader.accepted_by_time()), lambda item: item.accepted_at, _recent_order)
            return
        recommended = self.selection == "recommended"
        starred = [item for item in self._rows_items(reader.starred().values()) if (item.record["status"] == STATUS_RECOMMENDED) == recommended]
        ranked = _shared_order(starred)
        yield from [[item] for item in ranked if item.stars in (5, 4, 3)]
        base = reader.pending_by_confidence() if recommended else reader.accepted_by_confidence()
        skipped = reader.starred()
        unrated = (row for row in base if str(row["id"]) not in skipped)
        yield from _groups(self._rows_items(unrated), lambda item: (item.probability, item.arrived), _shared_order)
        yield from [[item] for item in ranked if item.stars in (2, 1)]

    def _windows(self) -> Iterator[list[Item]]:
        reader, size = self.reader, BUCKET_DAYS[self.bucket]
        if self.medium or self.selection != "recommended":
            if self.medium:
                items = _recent_order(self._medium_items())
            else:
                items = self._rows_items(reader.accepted_by_time())
            window: list[Item] = []
            age = None
            for item in items:
                here = rolling_age(bucket_moment(item.record), self.bucket, self.as_of)
                if age is not None and here != age:
                    yield window
                    window = []
                window.append(item)
                age = here
            if window:
                yield window
            return
        earliest = reader.earliest_day()
        age = 0
        while earliest is not None:
            days = [self.as_of - timedelta(days=age * size + offset) for offset in range(size)]
            if days[0] < earliest:
                return
            window = []
            for day in days:
                window.extend(reader.day_rows(day).take(self.wanted))
            for item in self._rows_items(reader.starred().values()):
                if item.record["status"] == STATUS_RECOMMENDED and date.fromisoformat(item.arrived[:10] or "1970-01-01") in days:
                    window.append(item)
            yield window
            age += 1

    # ---- pulling

    def ensure(self, wanted: int) -> list[Item]:
        """Pull until the block holds ``wanted`` rows or has nothing more. A windowed recommended block is rebuilt when it must go deeper than it did."""
        if self.bucket and self.selection == "recommended" and not self.medium and wanted > self.wanted and self.items:
            self.items, self.exhausted, self._matched = [], False, 0
            self.wanted = wanted
            self._chunks = self._build()
        self.wanted = max(self.wanted, wanted)
        while self._matched < wanted and not self.exhausted:
            chunk = next(self._chunks, None)
            if chunk is None:
                self.exhausted = True
                break
            self.items.extend(chunk)
            self._matched += len(chunk)
        return self.items

    def _placement_order(self) -> list[Item]:
        """The pulled rows in the order the block places them (a window is read in time order and placed in the shared order, the newest window first)."""
        if not self.bucket:
            return self.items if self.selection != "recent" else _recent_order(self.items)
        return sorted(_shared_order(self.items), key=lambda item: rolling_age(bucket_moment(item.record), self.bucket, self.as_of))

    def records(self) -> list[dict[str, Any]]:
        """The pulled rows as public records with a ``rank`` in the shared order, so the unchanged block code chooses from them as it would from the file."""
        ranked = self.items if not self.bucket and self.selection != "recent" else _shared_order(self.items)
        return [{**item.record, RANK_FIELD: position} for position, item in enumerate(ranked, start=1)]

    def state(self) -> dict[str, Any]:
        """What the stream router needs to say whether a changed row can touch this block (``routing.py``)."""
        if self.whole:   # the whole list: the router cannot tell where a row would fall without it, so any row that can be public in its partition touches the block
            return {"attributes": {name: self.attributes[name] for name in ("select", "section", "bucket", "medium", "paged") if self.attributes.get(name)},
                    "whole": True, "sectionIds": self._section_ids() if self.section else None, "asOf": self.as_of.isoformat() if self.bucket else None}
        placed = self._placement_order()
        last = placed[min(self.wanted, len(placed)) - 1] if placed else None   # the last row a page could show: the router asks whether a change sorts ahead of it
        return {
            "attributes": {name: self.attributes[name] for name in ("select", "section", "bucket", "medium") if self.attributes.get(name)},
            "ids": sorted(item.identifier for item in self.items),
            "frontier": None if last is None else {"acceptedAt": last.accepted_at, "arrivedAt": last.arrived, "probability": last.probability, "stars": last.stars},
            "short": self.exhausted and self._matched < self.wanted,
            "asOf": self.as_of.isoformat() if self.bucket else None,
            "sectionIds": self._section_ids() if self.section else None,
        }

    def _section_ids(self) -> list[str]:
        """The ids of the sections this block's ``section`` names (by name or by label, as ``_in_section`` matches)."""
        wanted = {str(self.section).casefold(), self.section_labels.get(str(self.section), "").casefold()} - {""}
        return sorted(identifier for identifier, title in self.reader.labels().items() if title.casefold() in wanted)


class IndexDocument(Mapping):
    """What a projector hands the block code in place of the snapshot document: asked per include, it answers with the records that include needs."""

    def __init__(self, reader: IndexReader) -> None:
        self.reader = reader

    def for_block(self, attributes: Mapping[str, Any], wanted: int, as_of: date, section_labels: Mapping[str, str] | None = None) -> dict[str, Any]:
        block = self.reader.block(attributes, as_of, section_labels)
        block.ensure(wanted)
        return {"references": block.records()}

    def __getitem__(self, name: str) -> Any:
        if name == "references":
            return []
        raise KeyError(name)

    def __iter__(self):
        yield "references"

    def __len__(self) -> int:
        return 1


class IndexAnchors:
    """Answers ``threads.anchor_of`` for a site served from the index: is the Reference a thread is about public, and what is its title. One lineage read for each
    anchor, remembered for the run (the snapshot path had the whole list in memory)."""

    def __init__(self, reader: IndexReader) -> None:
        self.reader = reader
        self._titles: dict[str, str | None] = {}

    def title_of_lineage(self, lineage: str) -> str | None:
        if lineage not in self._titles:
            self.reader.requests["anchors"] += 1
            rows = [row for row in self.reader.client.list_by_index("referencesByLineageAndVersion", lineage) if self.reader.is_current(row)]
            item = self.reader.item(rows[0]) if rows and self.reader.is_shown(rows[0]) else None
            self._titles[lineage] = str(item.record["title"]) if item is not None else None
        return self._titles[lineage]
