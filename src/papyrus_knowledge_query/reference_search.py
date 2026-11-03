"""Search the References of a site by words and by meaning at once (the ``searchReferences`` query on the ``knowledgeQuery`` Lambda).

The newsroom References page has one search box. It finds a Reference again whatever its state: unrated, accepted or rejected.

Two lanes run together and are fused:

* **Words.** A plain-Python inverted index held in the Lambda's memory over four fields of the Reference row itself: title, authors, source URL and
  ``externalItemId``. Nothing is read per Reference. The first query after a cold start reads every current Reference once from
  ``listReferencesByVersionStateAndUpdatedAt`` (a page of 1000 at a time) and logs how long that took; each later query reads only the rows whose
  ``updatedAt`` is after the last row seen (less a small overlap), keyed by lineage, so a Reference changed a moment ago is found. A row with no
  ``feedStateKey`` (archived, superseded) is in no feed and is dropped.
* **Meaning.** The query is embedded and ``QueryVectors`` returns the nearest ``reference_summary`` vectors whose ``curationStatus`` is in what the
  ``show`` choice asks for, at most S3 Vectors' real limit of 100. The list is cut at the bend of the whole similarity curve (``cuts.search_cut_count``), not at its largest single drop.
  Rejected References have no vectors today, so only the words lane can find those.

Fusion is Reciprocal Rank Fusion, ``1 / (60 + rank)`` summed over the lanes a Reference appears in, one entry per lineage. A Reference whose terms
all appear in its title, authors, URL or id ("strong" word matches) sits above every meaning match, and a meaning match above a partial word match. If one
lane fails the other's results are returned with that lane's status.

After fusing, the page can be narrowed to a minimum of stars (``minStars``: 3, 4 or 5) and ordered by ``sort``: ``relevance`` keeps the fused order,
``newest`` is ``feedArrivalAt`` descending, ``quality`` is stars descending (a Reference with none last, so a search never loses a match) and then
newest first. Both are stable, so ties keep the fused order. Stars are an editor's interest, not relevance: they never change a match, only the order.

The cursor is opaque: an offset plus a hash of the query, filter, sort and minimum, so a cursor from another search or ordering is refused. The words lane is deterministic;
the meaning lane is cached for a few minutes per query so paging does not embed again.
"""
from __future__ import annotations

import base64
import bisect
import math
import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .cuts import search_cut_count

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

SHOW_CHOICES = ("unrated", "rated", "accepted", "all")
SORT_CHOICES = ("relevance", "newest", "quality")
CAPTURED_CHOICES = ("any", "yes", "no")
MIN_STARS_CHOICES = (3, 4, 5)   # never "only 3" or "only 2": a minimum is a floor, and the lowest floor worth asking for is 3
DEFAULT_LIMIT = 24
MAX_LIMIT = 100
MAX_QUERY_LENGTH = 500
RRF_K = 60
MEANING_TOP_K = 100   # S3 Vectors' real limit for one QueryVectors call
REFERENCE_SUMMARY_VECTOR_KIND = "reference_summary"
MEANING_STATUSES = {"unrated": ["pending"], "rated": ["accepted", "rejected"], "accepted": ["accepted"], "all": ["pending", "accepted", "rejected"]}
INDEX_PAGE_SIZE = 1000
REFRESH_OVERLAP = timedelta(minutes=2)
MEANING_CACHE_SECONDS = 300
MEANING_CACHE_ENTRIES = 32
MEANING_TIMEOUT_SECONDS = 20
EDITOR_GROUPS = ("editor", "admin")

# Same fields the newsroom feed reads (components/news-desk-taxonomy-client.ts, REFERENCE_RECORD_GRAPHQL_FIELDS), so a row goes straight to a card.
REFERENCE_FIELDS = (
    "id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId "
    "title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount "
    "outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy "
    "curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId "
    "starRating starRatedAt starRatedBy captureState newsroomFeedKey reviewedFeedKey feedStateKey feedArrivalAt predictedAcceptProbability predictionDecidedAt "
    "predictionSortKey discoveredByMonitorId updatedAt"
)
LIST_CURRENT_REFERENCES_QUERY = (
    "query ReferencesForSearch($versionState: String!, $updatedAt: ModelStringKeyConditionInput, $sortDirection: ModelSortDirection, "
    "$limit: Int, $nextToken: String) { listReferencesByVersionStateAndUpdatedAt(versionState: $versionState, updatedAt: $updatedAt, "
    "sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) { items { " + REFERENCE_FIELDS + " } nextToken } }"
)

FIELDS = ("title", "authors", "sourceUri", "externalItemId")   # the bit of each field in a match mask is 1 << position
FIELD_WEIGHT = {"title": 4, "authors": 4, "sourceUri": 1, "externalItemId": 2}
STOP_WORDS = frozenset(
    ("a an and are as at be but by for from has have in is it its of on or that the this to was were will with "
     "why how what when where which who whom whose do does did can could should would may might shall am been being had having "
     "i me my we our you your he she they them their his her there these those than then so if not no about into over under").split()
)
# A partial word match (some terms of a long query) is kept only if the terms it holds carry at least this share of the query's distinctive
# weight (each term weighed by how rare it is in this site's index). Below it the match is a common word or two, which the meaning lane answers better.
PARTIAL_COVERAGE_FLOOR = 0.5
LONG_QUERY_TERMS = 3   # a query of fewer distinctive terms keeps every partial match: with two terms, one of them is half the question

# Word-match classes, best first. Classes up to ALL_TERMS_CLASS are "strong": every term was found. ALL_TERMS_IN_TITLE means every term is in the title
# or the authors (a name and a title word count together). Meaning matches rank between the strong classes and partial word matches.
EXACT_TITLE_PHRASE, ALL_TERMS_IN_TITLE, ALL_TERMS_ACROSS_FIELDS, SOME_TERMS = 0, 1, 2, 3
ALL_TERMS_CLASS = ALL_TERMS_ACROSS_FIELDS


class SearchError(ValueError):
    """The request cannot be answered as asked (a bad cursor, a refused caller). The message is safe to show."""


class VectorSearch(Protocol):
    def embed_text(self, text: str) -> list[float]: ...

    def query_by_vector(self, vector: list[float], top_k: int, metadata_filter: dict[str, Any] | None) -> list[dict[str, Any]]: ...


def _normalize(text: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(character for character in folded if not unicodedata.combining(character)).casefold()


def tokenize(text: Any) -> list[str]:
    return re.findall(r"[^\W_]+", _normalize(text))


def query_terms(query: str) -> list[str]:
    """The distinct terms to look for, in order. Stop words are dropped unless nothing else is left."""
    tokens = tokenize(query)
    terms = [token for token in dict.fromkeys(tokens) if token not in STOP_WORDS]
    return terms or list(dict.fromkeys(tokens))


@dataclass
class WordHit:
    lineage_id: str
    match_class: int
    terms_matched: int
    weight: int
    mask: int
    coverage: float = 1.0   # the share of the query's distinctive (rarity-weighted) terms this Reference holds

    def fields(self) -> list[str]:
        return [name for position, name in enumerate(FIELDS) if self.mask & (1 << position)]


@dataclass
class _Entry:
    row: dict[str, Any]
    tokens_by_field: dict[str, list[str]]
    postings: set[tuple[str, int]] = field(default_factory=set)   # (token, bit) pairs this entry added, to remove them again


def _field_texts(row: dict[str, Any]) -> dict[str, str]:
    authors = row.get("authors")
    return {
        "title": str(row.get("title") or ""),
        "authors": " ".join(str(author) for author in authors) if isinstance(authors, list) else str(authors or ""),
        "sourceUri": str(row.get("sourceUri") or ""),
        "externalItemId": str(row.get("externalItemId") or ""),
    }


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ReferenceWordIndex:
    """The inverted index and the Reference rows behind it. One per Lambda container; thread safe."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: dict[str, _Entry] = {}
        self._postings: dict[str, dict[str, int]] = {}   # token -> {lineage id -> mask of fields holding it}
        self._vocabulary: list[str] = []
        self._vocabulary_dirty = False
        self._watermark: str | None = None   # the greatest updatedAt read so far
        self._lock = threading.RLock()
        self._clock = clock
        self.reads = 0   # GraphQL pages read, for tests and the log
        self.rows_read = 0
        self.built_in_ms: int | None = None

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def watermark(self) -> str | None:
        return self._watermark

    def row(self, lineage_id: str) -> dict[str, Any] | None:
        entry = self._entries.get(lineage_id)
        return entry.row if entry else None

    # --- filling -------------------------------------------------------------------------------------------------------------------------

    def refresh(self, graphql: Callable[[str, dict[str, Any]], dict[str, Any]]) -> int:
        """Read the rows changed since the last read (all of them on the first call); returns how many rows were read."""
        with self._lock:
            cold = self._watermark is None
            started = self._clock()
            variables: dict[str, Any] = {"versionState": "current", "sortDirection": "ASC", "limit": INDEX_PAGE_SIZE, "nextToken": None}
            if self._watermark is not None:
                since = _iso(self._watermark)
                bound = (since - REFRESH_OVERLAP).strftime("%Y-%m-%dT%H:%M:%S.000Z") if since else self._watermark
                variables["updatedAt"] = {"ge": bound}
            read = 0
            while True:
                data = graphql(LIST_CURRENT_REFERENCES_QUERY, dict(variables))
                connection = data.get("listReferencesByVersionStateAndUpdatedAt") or {}
                self.reads += 1
                for row in connection.get("items") or []:
                    if row:
                        read += 1
                        self.upsert(row)
                variables["nextToken"] = connection.get("nextToken")
                if not variables["nextToken"]:
                    break
            self.rows_read += read
            if cold:
                self.built_in_ms = int((self._clock() - started) * 1000)
                LOGGER.info("reference-search index built: %d rows read, %d kept, %d ms", read, len(self._entries), self.built_in_ms)
            elif read:
                LOGGER.info("reference-search index refreshed: %d rows read, %d kept", read, len(self._entries))
            if self._watermark is None:
                self._watermark = "1970-01-01T00:00:00.000Z"   # an empty site is "built"; the next refresh asks for everything after this
            return read

    def upsert(self, row: dict[str, Any]) -> None:
        lineage_id = str(row.get("lineageId") or "")
        if not lineage_id:
            return
        with self._lock:
            updated = row.get("updatedAt")
            if isinstance(updated, str) and (self._watermark is None or updated > self._watermark):
                self._watermark = updated
            existing = self._entries.get(lineage_id)
            if existing and int(existing.row.get("versionNumber") or 0) > int(row.get("versionNumber") or 0):
                return   # an older version of a Reference the index already holds
            if existing:
                self._remove(lineage_id)
            if not row.get("feedStateKey"):
                return   # in no feed: archived, or not the current version
            tokens_by_field = {name: tokenize(text) for name, text in _field_texts(row).items()}
            entry = _Entry(row=row, tokens_by_field=tokens_by_field)
            for position, name in enumerate(FIELDS):
                bit = 1 << position
                for token in set(tokens_by_field[name]):
                    postings = self._postings.get(token)
                    if postings is None:
                        postings = self._postings[token] = {}
                        self._vocabulary_dirty = True
                    postings[lineage_id] = postings.get(lineage_id, 0) | bit
                    entry.postings.add((token, bit))
            self._entries[lineage_id] = entry

    def _remove(self, lineage_id: str) -> None:
        entry = self._entries.pop(lineage_id, None)
        if not entry:
            return
        for token, _bit in entry.postings:
            postings = self._postings.get(token)
            if postings is not None:
                postings.pop(lineage_id, None)
                if not postings:
                    del self._postings[token]
                    self._vocabulary_dirty = True

    # --- searching -----------------------------------------------------------------------------------------------------------------------

    def _tokens_matching(self, term: str) -> list[str]:
        """The indexed tokens a typed term stands for: itself, and (from three characters) every token it begins."""
        if self._vocabulary_dirty:
            self._vocabulary = sorted(self._postings)
            self._vocabulary_dirty = False
        if len(term) < 3:
            return [term] if term in self._postings else []
        matches = []
        for position in range(bisect.bisect_left(self._vocabulary, term), len(self._vocabulary)):
            token = self._vocabulary[position]
            if not token.startswith(term):
                break
            matches.append(token)
        return matches

    def search(self, query: str, show: str) -> list[WordHit]:
        """Every Reference matching at least one term of ``query`` and the ``show`` choice, best first."""
        terms = query_terms(query)
        if not terms:
            return []
        phrase = tokenize(query)
        with self._lock:
            per_lineage: dict[str, dict[str, Any]] = {}
            rarity: list[float] = []   # per term, how distinctive it is here: a word in most titles counts for little, a rare one for a lot
            total = max(1, len(self._entries))
            for term_index, term in enumerate(terms):
                hits: dict[str, int] = {}
                for token in self._tokens_matching(term):
                    for lineage_id, mask in self._postings[token].items():
                        hits[lineage_id] = hits.get(lineage_id, 0) | mask
                rarity.append(math.log(1.0 + total / max(1, len(hits))))
                for lineage_id, mask in hits.items():
                    record = per_lineage.setdefault(lineage_id, {"masks": [], "mask": 0, "weight": 0.0})
                    record["masks"].append(mask)
                    record["weight"] += rarity[term_index]
                    record["mask"] |= mask
            title_bit, title_or_author = 1, 1 | 2   # the bits of "title" and "authors" in FIELDS
            wanted = sum(rarity) or 1.0
            results: list[tuple[tuple, WordHit]] = []
            for lineage_id, record in per_lineage.items():
                entry = self._entries[lineage_id]
                if not _shown(entry.row, show):
                    continue
                masks: list[int] = record["masks"]
                coverage = min(1.0, record["weight"] / wanted)
                if len(masks) == len(terms):
                    if all(mask & title_bit for mask in masks) and _contains_phrase(entry.tokens_by_field["title"], phrase):
                        match_class = EXACT_TITLE_PHRASE
                    elif all(mask & title_or_author for mask in masks):
                        match_class = ALL_TERMS_IN_TITLE
                    else:
                        match_class = ALL_TERMS_ACROSS_FIELDS
                else:
                    if len(terms) >= LONG_QUERY_TERMS and coverage < PARTIAL_COVERAGE_FLOOR:
                        continue   # a common word or two of a long question: left to the meaning lane
                    match_class = SOME_TERMS
                weight = sum(FIELD_WEIGHT[name] for position, name in enumerate(FIELDS) if record["mask"] & (1 << position))
                hit = WordHit(lineage_id, match_class, len(masks), weight, record["mask"], coverage)
                arrival = str(entry.row.get("feedArrivalAt") or entry.row.get("createdAt") or "")
                results.append(((arrival, lineage_id), hit))
        # Newest first, then (a stable sort) by class, share of the distinctive terms found and field weight: the order within a class is recency.
        results.sort(key=lambda item: item[0], reverse=True)
        results.sort(key=lambda item: (item[1].match_class, -round(item[1].coverage, 6), -item[1].weight))
        return [hit for _key, hit in results]


def _contains_phrase(title_tokens: list[str], phrase: list[str]) -> bool:
    """The query's words appear in the title one after another (the last may be the start of a longer word)."""
    if not phrase or len(phrase) > len(title_tokens):
        return False
    for start in range(len(title_tokens) - len(phrase) + 1):
        window = title_tokens[start:start + len(phrase)]
        if window[:-1] == phrase[:-1] and window[-1].startswith(phrase[-1]):
            return True
    return False


def _shown(row: dict[str, Any], show: str) -> bool:
    key = str(row.get("feedStateKey") or "")
    if show == "unrated":
        return key.endswith("#unrated")
    if show == "rated":
        return key.endswith("#rated")
    if show == "accepted":
        # The feed-state suffix cannot tell accepted from rejected, so the status decides.
        return key.endswith("#rated") and str(row.get("curationStatus") or "") == "accepted"
    return bool(key)


# --- the meaning lane --------------------------------------------------------------------------------------------------------------------

_meaning_cache: dict[tuple[str, str], tuple[float, list[tuple[str, float]]]] = {}
_meaning_cache_lock = threading.Lock()


def meaning_matches(vectors: VectorSearch, query: str, show: str, *, now: Callable[[], float] = time.monotonic) -> list[tuple[str, float]]:
    """The Reference lineage ids whose summary vectors are nearest the query, with their similarity, nearest first and cut at the knee."""
    key = (" ".join(_normalize(query).split()), show)
    with _meaning_cache_lock:
        cached = _meaning_cache.get(key)
        if cached and now() - cached[0] < MEANING_CACHE_SECONDS:
            return list(cached[1])
    vector = vectors.embed_text(query)
    metadata_filter = {"$and": [
        {"vectorKind": {"$eq": REFERENCE_SUMMARY_VECTOR_KIND}},
        {"curationStatus": {"$in": MEANING_STATUSES[show]}},
    ]}
    matches = vectors.query_by_vector(vector, MEANING_TOP_K, metadata_filter)
    best: dict[str, float] = {}
    for match in matches:
        metadata = match.get("metadata") or {}
        lineage_id = str(metadata.get("referenceLineageId") or metadata.get("lineageId") or "")
        distance = match.get("distance")
        if not lineage_id or distance is None:
            continue
        similarity = 1.0 - float(distance)
        if lineage_id not in best or similarity > best[lineage_id]:
            best[lineage_id] = similarity
    ordered = sorted(best.items(), key=lambda pair: (-pair[1], pair[0]))
    kept = ordered[: search_cut_count([similarity for _lineage, similarity in ordered])]
    with _meaning_cache_lock:
        if len(_meaning_cache) >= MEANING_CACHE_ENTRIES:
            _meaning_cache.pop(min(_meaning_cache, key=lambda cache_key: _meaning_cache[cache_key][0]), None)
        _meaning_cache[key] = (now(), list(kept))
    return kept


def clear_meaning_cache() -> None:
    with _meaning_cache_lock:
        _meaning_cache.clear()


# --- fusion, cursor and the query --------------------------------------------------------------------------------------------------------

@dataclass
class Fused:
    lineage_id: str
    score: float
    strong: bool
    by_words: bool
    by_meaning: bool
    word_fields: list[str]
    tier: int = 0   # the word class for a strong match, then MEANING_TIER, then PARTIAL_TIER


MEANING_TIER = ALL_TERMS_CLASS + 1
PARTIAL_TIER = MEANING_TIER + 1


def fuse(word_hits: list[WordHit], meaning: list[tuple[str, float]]) -> list[Fused]:
    """Reciprocal Rank Fusion over the lanes, one entry per lineage. Order: exact title phrase, every term in title or author, every term anywhere,
    then anything the meaning lane found (alone or with some of the words), then partial word matches alone; within each, the fused score, then the id."""
    by_lineage: dict[str, Fused] = {}
    for rank, hit in enumerate(word_hits, start=1):
        by_lineage[hit.lineage_id] = Fused(
            hit.lineage_id, 1.0 / (RRF_K + rank), hit.match_class <= ALL_TERMS_CLASS, True, False, hit.fields(), hit.match_class,
        )
    for rank, (lineage_id, _similarity) in enumerate(meaning, start=1):
        entry = by_lineage.get(lineage_id)
        if entry is None:
            by_lineage[lineage_id] = Fused(lineage_id, 1.0 / (RRF_K + rank), False, False, True, [], MEANING_TIER)
        else:
            entry.score += 1.0 / (RRF_K + rank)
            entry.by_meaning = True
    for entry in by_lineage.values():
        if not entry.strong:
            entry.tier = MEANING_TIER if entry.by_meaning else PARTIAL_TIER
    return sorted(by_lineage.values(), key=lambda entry: (entry.tier, -entry.score, entry.lineage_id))


def search_hash(query: str, show: str, sort: str = "relevance", min_stars: int | None = None, captured: str = "any") -> str:
    base = f"{' '.join(_normalize(query).split())}\u0000{show}\u0000{sort}\u0000{min_stars or ''}"
    # "any" adds nothing, so a cursor made before the Captured filter existed stays valid.
    return hashlib.sha256((base if captured == "any" else f"{base}\u0000{captured}").encode("utf-8")).hexdigest()[:16]


def encode_cursor(offset: int, query: str, show: str, sort: str = "relevance", min_stars: int | None = None, captured: str = "any") -> str:
    raw = json.dumps({"o": offset, "h": search_hash(query, show, sort, min_stars, captured)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, query: str, show: str, sort: str = "relevance", min_stars: int | None = None, captured: str = "any") -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        offset, digest = int(payload["o"]), str(payload["h"])
    except (ValueError, KeyError, TypeError):
        raise SearchError("The cursor is not valid.") from None
    if digest != search_hash(query, show, sort, min_stars, captured) or offset < 0:
        raise SearchError("The cursor belongs to a different search.")
    return offset


def stars_of(row: dict[str, Any]) -> int:
    """A Reference's whole star rating, 0 when it has none or the value is not a rating (a float such as 4.0 counts as 4; NaN, 2.5 and 9 do not)."""
    value = row.get("starRating")
    if isinstance(value, bool) or value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if math.isfinite(number) and number == int(number) and 1 <= number <= 5 else 0


def _arrival_of(row: dict[str, Any]) -> str:
    return str(row.get("feedArrivalAt") or row.get("createdAt") or "")


def parse_min_stars(value: Any) -> int | None:
    """The minimum from the payload: nothing (or null) is no minimum; otherwise 3, 4 or 5."""
    if value is None or value == "":
        return None
    try:
        number = float(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        number = None
    if number is None or not math.isfinite(number) or number != int(number) or int(number) not in MIN_STARS_CHOICES:
        raise SearchError(f"minStars must be one of {', '.join(str(choice) for choice in MIN_STARS_CHOICES)}, or empty.")
    return int(number)


def is_captured(row: dict[str, Any]) -> bool:
    """Only a stored ``captureState`` of ``full`` is captured; empty, thin, none and running are not (docs/reference-curation-pipeline.md)."""
    return str(row.get("captureState") or "") == "full"


def order_fused(fused: list[Fused], rows: dict[str, dict[str, Any]], sort: str, min_stars: int | None, captured: str = "any") -> list[Fused]:
    """Narrow the fused results to ``min_stars`` and ``captured`` and order them by ``sort``. Stable: ties keep the fused (relevance) order."""
    kept = [entry for entry in fused if (min_stars is None or stars_of(rows[entry.lineage_id]) >= min_stars)
            and (captured == "any" or is_captured(rows[entry.lineage_id]) == (captured == "yes"))]
    if sort == "newest":
        return sorted(kept, key=lambda entry: _arrival_of(rows[entry.lineage_id]), reverse=True)
    if sort == "quality":
        return sorted(kept, key=lambda entry: (stars_of(rows[entry.lineage_id]), _arrival_of(rows[entry.lineage_id])), reverse=True)
    return kept


_index = ReferenceWordIndex()


def word_index() -> ReferenceWordIndex:
    return _index


def require_editor(event: dict[str, Any] | None) -> None:
    """Defence behind AppSync's own group rule: a call that carries an identity must be an editor or admin."""
    identity = event.get("identity") if isinstance(event, dict) else None
    if not isinstance(identity, dict):
        return
    groups = identity.get("groups")
    if groups is None and isinstance(identity.get("claims"), dict):
        groups = identity["claims"].get("cognito:groups")
    if not isinstance(groups, list) or not set(map(str, groups)) & set(EDITOR_GROUPS):
        raise SearchError("Not Authorized: searching References is for editors and admins.")


def _failure_message(lane: str, error: BaseException) -> str:
    LOGGER.warning("reference-search %s lane failed: %s: %s", lane, type(error).__name__, error)
    if lane == "meaning":
        if "OPENAI_API_KEY" in str(error) or "ParameterNotFound" in str(error):
            return "Meaning search is not set up for this site."
        if isinstance(error, FutureTimeout):
            return "Meaning search took too long."
        return "Meaning search could not be reached."
    return "Word search could not read the References."


def search_references(
    payload: dict[str, Any],
    *,
    graphql: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
    vectors: VectorSearch | None,
    index: ReferenceWordIndex | None = None,
) -> dict[str, Any]:
    """``{items: [{reference, matchedBy, matchedFields}], nextCursor, lanes: {keyword: {status}, meaning: {status, message?}}}``.

    ``payload``: ``query``, ``show``, ``limit``, ``cursor`` and, to order or narrow the results, ``sort`` (relevance, newest, quality) and ``minStars`` (3, 4, 5) and ``captured`` (any, yes, no: yes is a stored ``captureState`` of full)."""
    index = _index if index is None else index
    query = " ".join(str(payload.get("query") or "").split())[:MAX_QUERY_LENGTH]
    show = str(payload.get("show") or "all")
    if show not in SHOW_CHOICES:
        raise SearchError(f"show must be one of {', '.join(SHOW_CHOICES)}.")
    sort = str(payload.get("sort") or "relevance")
    if sort not in SORT_CHOICES:
        raise SearchError(f"sort must be one of {', '.join(SORT_CHOICES)}.")
    min_stars = parse_min_stars(payload.get("minStars"))
    captured = str(payload.get("captured") or "any")
    if captured not in CAPTURED_CHOICES:
        raise SearchError(f"captured must be one of {', '.join(CAPTURED_CHOICES)}.")
    try:
        limit = int(payload.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        raise SearchError("limit must be a whole number.") from None
    limit = max(1, min(limit, MAX_LIMIT))
    cursor = payload.get("cursor")
    offset = decode_cursor(str(cursor), query, show, sort, min_stars, captured) if cursor else 0
    lanes: dict[str, dict[str, Any]] = {"keyword": {"status": "ok"}, "meaning": {"status": "ok"}}
    if not query_terms(query):
        return {"items": [], "nextCursor": None, "lanes": lanes}

    def words() -> list[WordHit]:
        if graphql is None:
            raise RuntimeError("no GraphQL access for this call")
        index.refresh(graphql)
        return index.search(query, show)

    def meaning() -> list[tuple[str, float]]:
        if vectors is None:
            raise RuntimeError("OPENAI_API_KEY or the vector index is not configured")
        return meaning_matches(vectors, query, show)

    word_hits: list[WordHit] = []
    meaning_hits: list[tuple[str, float]] = []
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        words_future = pool.submit(words)
        meaning_future = pool.submit(meaning)
        try:
            word_hits = words_future.result()
        except Exception as error:   # noqa: BLE001 - one lane failing must not lose the other
            lanes["keyword"] = {"status": "failed", "message": _failure_message("keyword", error)}
        try:
            meaning_hits = meaning_future.result(timeout=MEANING_TIMEOUT_SECONDS)
        except Exception as error:   # noqa: BLE001
            lanes["meaning"] = {"status": "failed", "message": _failure_message("meaning", error)}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)   # a meaning call that ran over its time is abandoned, not waited for

    shown_meaning = [(lineage_id, similarity) for lineage_id, similarity in meaning_hits
                     if (row := index.row(lineage_id)) is not None and _shown(row, show)]
    candidates = fuse(word_hits, shown_meaning)
    rows = {entry.lineage_id: row for entry in candidates if (row := index.row(entry.lineage_id)) is not None}
    fused = order_fused([entry for entry in candidates if entry.lineage_id in rows], rows, sort, min_stars, captured)
    page = fused[offset: offset + limit]
    items = []
    for entry in page:
        matched_by = [lane for lane, found in (("keyword", entry.by_words), ("meaning", entry.by_meaning)) if found]
        items.append({"reference": index.row(entry.lineage_id), "matchedBy": matched_by, "matchedFields": entry.word_fields})
    more = offset + limit < len(fused)
    return {"items": items, "nextCursor": encode_cursor(offset + limit, query, show, sort, min_stars, captured) if more else None, "lanes": lanes}
