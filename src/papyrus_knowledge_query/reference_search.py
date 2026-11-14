"""Search the References of a site by words and by meaning at once (the ``searchReferences`` query on the ``knowledgeQuery`` Lambda).

The newsroom References page and the top-bar search box share this one search. It finds a Reference again whatever its state: pending, accepted or rejected
(editors and admins only; the public pages and the reader-facing answers use ``knowledgeQuery``, which stays accepted-only).

Two lanes run together and are fused:

* **Words.** The persistent word index (``reference_words``: one DynamoDB row per word per Reference, written when a Reference is created or changes). A
  search looks up each typed word by exact match or prefix (a Query per word), reads only the Reference rows those hits point at (BatchGetItem), and ranks
  them in a small in-memory ``ReferenceWordIndex`` built for that query alone. Nothing reads the whole Reference table, on a cold start or at any other time.
  The four fields searched are title, authors, source address and ``externalItemId``.
* **Meaning.** The query is embedded and ``QueryVectors`` returns the nearest ``reference_summary`` vectors whose ``curationStatus`` is in what the
  ``show`` choice asks for, at most S3 Vectors' real limit of 100. The list is cut at the bend of the whole similarity curve (``cuts.search_cut_count``), not at its largest single drop.
  Rejected References have no vectors today, so only the words lane can find those.

Fusion is Reciprocal Rank Fusion, ``1 / (60 + rank)`` summed over the lanes a Reference appears in, one entry per lineage. A Reference whose terms
all appear in its title, authors, URL or id ("strong" word matches) sits above every other match, a partial word match (some of the terms, past the coverage floor) above every match found only by meaning. If one
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
from typing import Any, Callable, Protocol

from .cuts import search_cut_count
from .reference_words import REFERENCE_ATTRIBUTES, DynamoWordSource, _normalize, field_texts as _field_texts, tokenize

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

SHOW_CHOICES = ("unrated", "rated", "accepted", "rejected", "all")
SORT_CHOICES = ("relevance", "newest", "quality")
CAPTURED_CHOICES = ("any", "yes", "no")
MIN_STARS_CHOICES = (3, 4, 5)   # never "only 3" or "only 2": a minimum is a floor, and the lowest floor worth asking for is 3
DEFAULT_LIMIT = 24
MAX_LIMIT = 100
MAX_QUERY_LENGTH = 500
RRF_K = 60
MEANING_TOP_K = 100   # S3 Vectors' real limit for one QueryVectors call
REFERENCE_SUMMARY_VECTOR_KIND = "reference_summary"
MEANING_STATUSES = {"unrated": ["pending"], "rated": ["accepted", "rejected"], "accepted": ["accepted"], "rejected": ["rejected"], "all": ["pending", "accepted", "rejected"]}
MEANING_CACHE_SECONDS = 300
MEANING_CACHE_ENTRIES = 32
MEANING_TIMEOUT_SECONDS = 20
EDITOR_GROUPS = ("editor", "admin")

# Same fields the newsroom feed reads (components/news-desk-taxonomy-client.ts, REFERENCE_RECORD_GRAPHQL_FIELDS), so a row goes straight to a card. The
# change feed of the router's vector pass (monitoring_vectors) reads the same list through this query; the word index reads the same attributes by key.
REFERENCE_FIELDS = " ".join(REFERENCE_ATTRIBUTES)
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


class ReferenceWordIndex:
    """The inverted index of a set of Reference rows, held in memory, and the ranking over it.

    A search builds one for its own query from the rows its word lookups matched (``words_lane``), so it holds only candidates. ``population`` is how many
    References the site has, for weighing how rare a word is; without it the index's own size is used (tests, small sets). Thread safe."""

    def __init__(self, *, population: int | None = None) -> None:
        self._entries: dict[str, _Entry] = {}
        self._postings: dict[str, dict[str, int]] = {}   # token -> {lineage id -> mask of fields holding it}
        self._vocabulary: list[str] = []
        self._vocabulary_dirty = False
        self._lock = threading.RLock()
        self.population = population

    def __len__(self) -> int:
        return len(self._entries)

    def row(self, lineage_id: str) -> dict[str, Any] | None:
        entry = self._entries.get(lineage_id)
        return entry.row if entry else None

    # --- filling -------------------------------------------------------------------------------------------------------------------------

    def upsert(self, row: dict[str, Any]) -> None:
        lineage_id = str(row.get("lineageId") or "")
        if not lineage_id:
            return
        with self._lock:
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
            total = max(1, self.population or len(self._entries))
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
    if show == "rejected":
        return key.endswith("#rated") and str(row.get("curationStatus") or "") == "rejected"
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
    tier: int = 0   # the word class for a strong match, then PARTIAL_TIER (found by words), then MEANING_TIER (found only by meaning)


PARTIAL_TIER = ALL_TERMS_CLASS + 1
MEANING_TIER = PARTIAL_TIER + 1


def fuse(word_hits: list[WordHit], meaning: list[tuple[str, float]]) -> list[Fused]:
    """Reciprocal Rank Fusion over the lanes, one entry per lineage. Order: exact title phrase, every term in title or author, every term anywhere,
    then every other word match (some of the typed words, past the coverage floor; with or without the meaning lane), then the Related ones, found only by
    meaning; within each, the fused score, then the id. A Reference the words found is never below one only the meaning found."""
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
            entry.tier = PARTIAL_TIER if entry.by_words else MEANING_TIER
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


class WordSource(Protocol):
    """What the words lane reads: the word table (``lookup``), the Reference rows it points at (``rows``) and a rough count of References."""

    def lookup(self, term: str) -> list[Any]: ...

    def rows(self, reference_ids: list[str]) -> dict[str, dict[str, Any]]: ...

    def pointers(self, lineage_ids: list[str]) -> dict[str, Any]: ...

    def population(self) -> int: ...


def words_lane(source: WordSource, query: str, show: str) -> tuple[list[WordHit], ReferenceWordIndex]:
    """Look each typed word up in the word table, read the matching Reference rows, and rank them. Returns the hits and the small index holding the rows.

    Requests: one Query per typed word (more only when a word has more than a page of hits), one BatchGetItem per 100 matching rows, and a cached DescribeTable.
    Nothing reads the Reference table beyond the rows the words matched."""
    terms = query_terms(query)
    postings: dict[str, Any] = {}   # lineage id -> the posting that points at the current row
    for term in terms:
        for posting in source.lookup(term):
            held = postings.get(posting.lineage_id)
            if held is None or posting.version_number > held.version_number:
                postings[posting.lineage_id] = posting
    index = ReferenceWordIndex(population=source.population() if postings else None)
    if not postings:
        return [], index
    rows = source.rows([posting.reference_id for posting in postings.values() if posting.reference_id])
    for lineage_id, posting in postings.items():
        row = rows.get(posting.reference_id)
        if row and str(row.get("lineageId") or "") == lineage_id:
            index.upsert(row)
    return index.search(query, show), index


def add_meaning_rows(source: WordSource, index: ReferenceWordIndex, lineage_ids: list[str]) -> None:
    """A meaning match knows only its lineage. Read the current rows of the matches the words did not already bring (one BatchGetItem for the pointers, one
    for the rows); a lineage with no pointer is in no feed and is dropped."""
    missing = [lineage_id for lineage_id in lineage_ids if index.row(lineage_id) is None]
    if not missing:
        return
    try:
        pointers = source.pointers(missing)
        rows = source.rows([pointer.reference_id for pointer in pointers.values() if pointer.reference_id])
    except Exception as error:   # noqa: BLE001 - the meaning matches without a row are left out, the rest are kept
        LOGGER.warning("reference-search could not read rows for meaning matches: %s: %s", type(error).__name__, error)
        return
    for lineage_id, pointer in pointers.items():
        row = rows.get(pointer.reference_id)
        if row and str(row.get("lineageId") or "") == lineage_id:
            index.upsert(row)


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
    words: WordSource | None,
    vectors: VectorSearch | None,
) -> dict[str, Any]:
    """``{items: [{reference, matchedBy, matchedFields}], nextCursor, lanes: {keyword: {status}, meaning: {status, message?}}}``.

    ``payload``: ``query``, ``show``, ``limit``, ``cursor`` and, to order or narrow the results, ``sort`` (relevance, newest, quality) and ``minStars`` (3, 4, 5) and ``captured`` (any, yes, no: yes is a stored ``captureState`` of full)."""
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

    def word_lane() -> tuple[list[WordHit], ReferenceWordIndex]:
        if words is None:
            raise RuntimeError("the word index is not configured")
        return words_lane(words, query, show)

    def meaning() -> list[tuple[str, float]]:
        if vectors is None:
            raise RuntimeError("OPENAI_API_KEY or the vector index is not configured")
        return meaning_matches(vectors, query, show)

    word_hits: list[WordHit] = []
    index = ReferenceWordIndex()
    meaning_hits: list[tuple[str, float]] = []
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        words_future = pool.submit(word_lane)
        meaning_future = pool.submit(meaning)
        try:
            word_hits, index = words_future.result()
        except Exception as error:   # noqa: BLE001 - one lane failing must not lose the other
            lanes["keyword"] = {"status": "failed", "message": _failure_message("keyword", error)}
        try:
            meaning_hits = meaning_future.result(timeout=MEANING_TIMEOUT_SECONDS)
        except Exception as error:   # noqa: BLE001
            lanes["meaning"] = {"status": "failed", "message": _failure_message("meaning", error)}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)   # a meaning call that ran over its time is abandoned, not waited for

    if words is not None and meaning_hits:
        add_meaning_rows(words, index, [lineage_id for lineage_id, _similarity in meaning_hits])
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
