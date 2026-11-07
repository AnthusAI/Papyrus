"""The persistent word index behind the References search (docs/reference-search.md#word-search).

One row per word per Reference, in a small DynamoDB table of its own, written when a Reference is created or changes (a DynamoDB Streams consumer on the
Reference table, ``stream_handler``) and read by exact word or by prefix (``DynamoWordSource``). A search never reads the Reference table beyond the rows it
matched, and nothing walks the corpus on a schedule or on a cold start.

Table shape (``PAPYRUS_REFERENCE_WORD_TABLE``):

* partition key ``shard``: the first two characters of the word (a one-character word is its own shard);
* sort key ``entry``: ``<word>#<lineageId>``, so one Query with ``begins_with`` returns every Reference holding a word, or every word beginning with the typed
  letters (a prefix of three or more letters stays inside one shard);
* ``referenceId`` (the id of the Reference row that is current) and ``versionNumber``.

One more row per Reference, the pointer (``pointer_key``), names the current row by lineage for meaning matches.

Words come from the four fields the search has always used: title, authors, source address and ``externalItemId``. Only the current version of a
Reference that is in a feed (``feedStateKey`` set) has words. A newer version's rows are never replaced or deleted by an older version's event, because
every write and delete is conditioned on the version number (events from different rows of one lineage can arrive in either order).
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

WORD_TABLE_ENV = "PAPYRUS_REFERENCE_WORD_TABLE"
REFERENCE_TABLE_ENV = "PAPYRUS_REFERENCE_TABLE_NAME"
PREFIX_FROM_LENGTH = 3   # a typed word of three or more letters also matches the start of a longer word
BATCH_GET_SIZE = 100     # DynamoDB's BatchGetItem limit

FIELDS = ("title", "authors", "sourceUri", "externalItemId")
# The parts of an address every link has; indexing them would put one row per Reference in a few huge shards and find everything.
ADDRESS_NOISE = frozenset("http https www com org net html htm php".split())


def _normalize(text: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(character for character in folded if not unicodedata.combining(character)).casefold()


def tokenize(text: Any) -> list[str]:
    return re.findall(r"[^\W_]+", _normalize(text))


def field_texts(row: dict[str, Any]) -> dict[str, str]:
    authors = row.get("authors")
    return {
        "title": str(row.get("title") or ""),
        "authors": " ".join(str(author) for author in authors) if isinstance(authors, list) else str(authors or ""),
        "sourceUri": str(row.get("sourceUri") or ""),
        "externalItemId": str(row.get("externalItemId") or ""),
    }


def is_indexed(row: dict[str, Any] | None) -> bool:
    """A Reference has words only while it is the current version and in a feed (not archived)."""
    return bool(row) and str(row.get("versionState") or "current") == "current" and bool(row.get("feedStateKey")) and bool(row.get("lineageId"))


def row_words(row: dict[str, Any] | None) -> set[str]:
    """The distinct words of a Reference, or none when it is not indexed."""
    if not is_indexed(row):
        return set()
    assert row is not None
    words: set[str] = set()
    for name, text in field_texts(row).items():
        for token in tokenize(text):
            if name == "sourceUri" and token in ADDRESS_NOISE:
                continue
            words.add(token)
    return words


def shard_of(word: str) -> str:
    return word[:2]


def entry_of(word: str, lineage_id: str) -> str:
    return f"{word}#{lineage_id}"


def pointer_key(lineage_id: str) -> dict[str, str]:
    """The one row per indexed Reference that says which Reference row is current. A meaning match knows only the lineage; this finds its row without
    a search of any kind. Its shard starts with ``~``, which no word does."""
    return {"shard": f"~{lineage_id[:2]}", "entry": lineage_id}


@dataclass(frozen=True)
class Posting:
    word: str
    lineage_id: str
    reference_id: str
    version_number: int


def plain(value: Any) -> Any:
    """DynamoDB numbers arrive as Decimal; the rest of the search (and JSON) wants int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, set):
        return [plain(item) for item in sorted(value, key=str)]
    return value


class ConditionFailed(Exception):
    """A conditional write lost to a newer version; not an error."""


# --- the writing side ----------------------------------------------------------------------------------------------------------------------

class WordWriter:
    """Applies a Reference change to the word table. ``table`` is a boto3 ``Table`` (or anything with ``put_item`` and ``delete_item``)."""

    def __init__(self, table: Any, *, conflict_errors: tuple[type[BaseException], ...] = ()) -> None:
        self._table = table
        self._conflicts = conflict_errors

    @classmethod
    def from_environment(cls) -> "WordWriter":
        import boto3

        table = boto3.resource("dynamodb").Table(os.environ[WORD_TABLE_ENV])
        return cls(table, conflict_errors=(table.meta.client.exceptions.ConditionalCheckFailedException,))

    def _put(self, key: dict[str, str], row: dict[str, Any]) -> None:
        version = int(row.get("versionNumber") or 0)
        try:
            self._table.put_item(
                Item={**key, "referenceId": str(row["id"]), "versionNumber": version},
                ConditionExpression="attribute_not_exists(entry) OR versionNumber <= :v",
                ExpressionAttributeValues={":v": version},
            )
        except self._conflicts:
            pass

    def _delete(self, key: dict[str, str], row: dict[str, Any]) -> None:
        version = int(row.get("versionNumber") or 0)
        try:
            self._table.delete_item(
                Key=key,
                ConditionExpression="attribute_not_exists(entry) OR versionNumber <= :v",
                ExpressionAttributeValues={":v": version},
            )
        except self._conflicts:
            pass

    def put(self, word: str, row: dict[str, Any]) -> None:
        self._put({"shard": shard_of(word), "entry": entry_of(word, str(row["lineageId"]))}, row)

    def delete(self, word: str, row: dict[str, Any]) -> None:
        self._delete({"shard": shard_of(word), "entry": entry_of(word, str(row["lineageId"]))}, row)

    def pointer_is_current(self, row: dict[str, Any]) -> bool:
        """The Reference's pointer row already names this row (so its words were written: the pointer is written last)."""
        held = (self._table.get_item(Key=pointer_key(str(row["lineageId"]))) or {}).get("Item")
        return bool(held) and str(held.get("referenceId")) == str(row["id"]) and int(held.get("versionNumber") or 0) == int(row.get("versionNumber") or 0)

    def apply_change(self, old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, int]:
        """Bring the word rows in line with one Reference row changing from ``old`` to ``new`` (either may be None). Writes only the difference, so a
        vote, a star or a prediction (no word changes) writes nothing."""
        old_words, new_words = row_words(old), row_words(new)
        same_row = bool(old_words) and bool(new_words) and old is not None and new is not None and old.get("id") == new.get("id")
        same_version = same_row and int(old.get("versionNumber") or 0) == int(new.get("versionNumber") or 0)   # type: ignore[union-attr]
        to_put = new_words - old_words if same_version else new_words
        to_delete = old_words - new_words if same_row else old_words
        for word in sorted(to_put):
            assert new is not None
            self.put(word, new)
        for word in sorted(to_delete):
            assert old is not None
            self.delete(word, old)
        if new_words and not same_row:
            assert new is not None
            self._put(pointer_key(str(new["lineageId"])), new)
        elif old_words and not new_words:
            assert old is not None
            self._delete(pointer_key(str(old["lineageId"])), old)
        return {"put": len(to_put), "deleted": len(to_delete)}


def deserialize_image(image: dict[str, Any] | None) -> dict[str, Any] | None:
    if not image:
        return None
    from boto3.dynamodb.types import TypeDeserializer

    deserializer = TypeDeserializer()
    return {key: plain(deserializer.deserialize(value)) for key, value in image.items()}


def stream_handler(event: dict[str, Any], context: Any = None, *, writer: WordWriter | None = None) -> dict[str, Any]:
    """The Lambda entry for the Reference table's stream. A record that fails is reported so only it is retried."""
    writer = writer or WordWriter.from_environment()
    failures: list[dict[str, str]] = []
    changed = {"put": 0, "deleted": 0}
    for record in event.get("Records") or []:
        try:
            images = record.get("dynamodb") or {}
            counts = writer.apply_change(deserialize_image(images.get("OldImage")), deserialize_image(images.get("NewImage")))
            changed["put"] += counts["put"]
            changed["deleted"] += counts["deleted"]
        except Exception:   # noqa: BLE001 - one bad record must not lose the batch
            LOGGER.exception("reference word index: record failed")
            sequence = (record.get("dynamodb") or {}).get("SequenceNumber")
            if sequence:
                failures.append({"itemIdentifier": sequence})
            else:
                raise
    LOGGER.info("reference word index: %d records, %d word rows written, %d deleted, %d failed", len(event.get("Records") or []), changed["put"], changed["deleted"], len(failures))
    return {"batchItemFailures": failures}


# --- the reading side ----------------------------------------------------------------------------------------------------------------------

REFERENCE_ATTRIBUTES = (
    "id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId "
    "title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount "
    "outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy "
    "curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId "
    "starRating starRatedAt starRatedBy captureState medium evidenceLevel playlistUrl newsroomFeedKey reviewedFeedKey feedStateKey feedArrivalAt predictedAcceptProbability predictionDecidedAt "
    "predictionSortKey discoveredByMonitorId updatedAt"
).split()


class DynamoWordSource:
    """Reads the word table by word or prefix and the matching Reference rows by id. Never scans.

    ``dynamodb`` is a boto3 ``dynamodb`` resource (or a fake with ``Table(name)`` and ``batch_get_item``); ``client`` answers ``describe_table``."""

    def __init__(self, dynamodb: Any, client: Any, *, word_table: str, reference_table: str, population_ttl: float = 6 * 3600,
                 clock: Callable[[], float] | None = None) -> None:
        import time

        self._words = dynamodb.Table(word_table)
        self._dynamodb = dynamodb
        self._client = client
        self._word_table, self._reference_table = word_table, reference_table
        self._clock = clock or time.monotonic
        self._population: tuple[float, int] | None = None
        self._population_ttl = population_ttl
        self.requests = 0   # DynamoDB requests made, for tests and the log

    @classmethod
    def from_environment(cls) -> "DynamoWordSource":
        import boto3

        word_table, reference_table = os.environ.get(WORD_TABLE_ENV, ""), os.environ.get(REFERENCE_TABLE_ENV, "")
        if not word_table or not reference_table:
            raise RuntimeError(f"{WORD_TABLE_ENV} and {REFERENCE_TABLE_ENV} are not set; the word index is not deployed to this site.")
        return cls(boto3.resource("dynamodb"), boto3.client("dynamodb"), word_table=word_table, reference_table=reference_table)

    def lookup(self, term: str) -> list[Posting]:
        """Every Reference holding ``term`` (exact), or holding a word that begins with it when it has three or more letters."""
        prefix = term if len(term) >= PREFIX_FROM_LENGTH else f"{term}#"
        values = {":s": shard_of(term), ":p": prefix}
        postings: list[Posting] = []
        start_key: dict[str, Any] | None = None
        while True:
            # `shard` is a DynamoDB reserved word; a bare name in a key condition is refused ("Attribute name is a reserved keyword"), so both key
            # attributes go through aliases.
            kwargs: dict[str, Any] = {"KeyConditionExpression": "#shard = :s AND begins_with(#entry, :p)",
                                      "ExpressionAttributeNames": {"#shard": "shard", "#entry": "entry"}, "ExpressionAttributeValues": values}
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            page = self._words.query(**kwargs)
            self.requests += 1
            for item in page.get("Items") or []:
                word, _, lineage_id = str(item["entry"]).partition("#")
                postings.append(Posting(word, lineage_id, str(item.get("referenceId") or ""), int(item.get("versionNumber") or 0)))
            start_key = page.get("LastEvaluatedKey")
            if not start_key:
                return postings

    def rows(self, reference_ids: list[str]) -> dict[str, dict[str, Any]]:
        """The Reference rows with these ids (the current versions the word rows point at), by id."""
        found: dict[str, dict[str, Any]] = {}
        names = {f"#a{position}": name for position, name in enumerate(REFERENCE_ATTRIBUTES)}
        projection = ", ".join(names)
        unique = sorted(set(reference_ids))
        for start in range(0, len(unique), BATCH_GET_SIZE):
            request = {self._reference_table: {"Keys": [{"id": reference_id} for reference_id in unique[start:start + BATCH_GET_SIZE]],
                                               "ProjectionExpression": projection, "ExpressionAttributeNames": names}}
            while request:
                response = self._dynamodb.batch_get_item(RequestItems=request)
                self.requests += 1
                for item in (response.get("Responses") or {}).get(self._reference_table) or []:
                    row = plain(item)
                    found[str(row["id"])] = row
                request = response.get("UnprocessedKeys") or {}
        return found

    def pointers(self, lineage_ids: list[str]) -> dict[str, Posting]:
        """The current Reference row of each indexed lineage (BatchGetItem on the word table; a lineage with no pointer is not in any feed)."""
        found: dict[str, Posting] = {}
        unique = sorted(set(lineage_ids))
        for start in range(0, len(unique), BATCH_GET_SIZE):
            request = {self._word_table: {"Keys": [pointer_key(lineage_id) for lineage_id in unique[start:start + BATCH_GET_SIZE]]}}
            while request:
                response = self._dynamodb.batch_get_item(RequestItems=request)
                self.requests += 1
                for item in (response.get("Responses") or {}).get(self._word_table) or []:
                    lineage_id = str(item["entry"])
                    found[lineage_id] = Posting("", lineage_id, str(item.get("referenceId") or ""), int(item.get("versionNumber") or 0))
                request = response.get("UnprocessedKeys") or {}
        return found

    def population(self) -> int:
        """About how many Reference rows the site holds (the table's own item count, refreshed by DynamoDB every few hours): only used to weigh how
        rare a word is, so an approximate count is enough. One DescribeTable, cached."""
        now = self._clock()
        if self._population and now - self._population[0] < self._population_ttl:
            return self._population[1]
        count = int((self._client.describe_table(TableName=self._reference_table).get("Table") or {}).get("ItemCount") or 0)
        self.requests += 1
        self._population = (now, count)
        return count
