"""The router's daily vector pass for one publication (docs/monitoring-cloud.md#vector-index-and-suggestions).

Before packs and single items, ``monitoring_stories.run_publication`` calls ``run_vector_pass``. The pass is proportional to what CHANGED since the last pass, never
to the size of the site, and it never lists the Reference table, the vector index, the concepts or the links:

1. It asks the ``updatedAt`` indexes for the Reference rows and concept rows changed since its saved place (``listReferencesByVersionStateAndUpdatedAt``,
   ``listSemanticNodesByVersionStateAndUpdatedAt``, oldest first, a page of 1,000 at a time). A site with nothing new costs one read per index.
2. It hands only those rows to ``papyrus_knowledge_query.vector_index.index_changes``: the status of what is indexed is reconciled for those References (rejected,
   archived or sent back to pending), their summary, source and passage vectors are written when the vector is missing or its text hash changed, and the cards of the
   changed concepts are written. A vote, a star or a metadata edit bumps ``updatedAt`` too; it finds its vector as it is and writes nothing.
3. Each Reference summary vector that is stored makes ONE suggestion check, queued for it (``reference_suggest_once``), and never any other way: there is no
   suggestion step in the pass, no plan, no watermark of suggestions and no backlog.

The saved place is ``{"v": 3, "since", "seen", "nodesSince", "nodesSeen"}`` in the router's table: the newest ``updatedAt`` it has indexed, and the ids (with their
``updatedAt``) of the rows within ``OVERLAP`` of it, so a row written a little late with an earlier clock is still read once and a row already done is skipped. A page
moves the place as soon as it is done, so a run that the time or the cost stops resumes exactly there.

A site with no saved place (its first run after this change, or a new site) is indexed once with the full sync (``index_reference_passages``, the by-hand
command's code, skipping what is already indexed); the place is set to the newest change read BEFORE that sync started, and only when the sync completed. That one run
is proportional to the site, once. Link explanations (editors' notes on links) are not part of the daily pass: they have no changed-since index, so they are indexed by
the by-hand sync until they get one or are indexed when a note is saved (docs/monitoring-cloud.md).

The only bounds are the run's time and its cost meter: embedding cost (text-embedding-3-small, from the characters embedded) is added to the model spend of the
publication's run. Without ``vectorIndexArn`` in the publication's ``monitorStories`` the pass does nothing and says why, and packs run without vectors.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

EMBEDDING_USD_PER_MILLION_TOKENS = 0.02   # text-embedding-3-small
CHARACTERS_PER_TOKEN = 4   # the usual English estimate; the exact count is only known to the embedding service
WATERMARK_SORT_KEY_PREFIX = "STATE#vectorSync#"
PAGE_SIZE = 1000
OVERLAP = timedelta(minutes=10)   # rows within this of the saved place are remembered by id, so a late writer's row is read once and none is read twice
STATE_VERSION = 3
EPOCH = "1970-01-01T00:00:00.000Z"
EMPTY_RESULT = {"indexed": 0, "conceptCardsWritten": 0, "suggestionsQueued": 0, "suggestionsSkippedReason": None, "indexSkippedReason": None, "costUsd": 0.0,
                "stoppedBy": None, "changedReferences": 0, "changedConcepts": 0, "changeReads": 0, "bootstrapped": False}

CHANGED_NODES_QUERY = (
    "query ChangedSemanticNodes($versionState: String!, $updatedAt: ModelStringKeyConditionInput, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) "
    "{ listSemanticNodesByVersionStateAndUpdatedAt(versionState: $versionState, updatedAt: $updatedAt, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) "
    "{ items { id lineageId versionState nodeKey nodeKind displayName description aliases status updatedAt } nextToken } }"
)


def _changed_references_query() -> str:
    from papyrus_knowledge_query.reference_search import LIST_CURRENT_REFERENCES_QUERY

    return LIST_CURRENT_REFERENCES_QUERY


FEEDS = {"references": ("listReferencesByVersionStateAndUpdatedAt", _changed_references_query), "concepts": ("listSemanticNodesByVersionStateAndUpdatedAt", lambda: CHANGED_NODES_QUERY)}


def watermark_sort_key(publication_id: str) -> str:
    return f"{WATERMARK_SORT_KEY_PREFIX}{publication_id}"


def embedding_cost_usd(characters: int) -> float:
    return characters / CHARACTERS_PER_TOKEN / 1_000_000 * EMBEDDING_USD_PER_MILLION_TOKENS


@contextmanager
def process_environment(**values: str | None) -> Iterator[None]:
    """The vector index code reads the index ARN and the embedding key from the process environment; set them for one publication and restore after."""
    earlier = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
        yield
    finally:
        for name, value in earlier.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def s3vectors_client_missing_reason(region_name: str | None = None) -> str | None:
    """None when this runtime's boto3 has the S3 Vectors client, else the reason (an older runtime bundles an older boto3)."""
    try:
        import boto3

        boto3.client("s3vectors", region_name=region_name or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
        return None
    except Exception as error:  # noqa: BLE001 - any failure to build the client means the pass cannot run
        return f"the runtime's boto3 has no usable s3vectors client ({type(error).__name__})"


def build_services(publication: dict[str, Any], bucket_name: str | None) -> Any:
    """Knowledge-query services for one publication: its AppSync API with the router's IAM signature, and its storage bucket for extracted text."""
    from papyrus_knowledge_query.services import GraphQLKnowledgeGraphProvider, KnowledgeQueryServices, S3CorpusTextProvider

    from .graphql_http import iam_signed_graphql_headers

    endpoint = publication["appsyncEndpoint"]
    graph = GraphQLKnowledgeGraphProvider(endpoint=endpoint, authorization_header="", header_factory=lambda body: iam_signed_graphql_headers(endpoint, body))
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return KnowledgeQueryServices(graph=graph, corpus_text=S3CorpusTextProvider(bucket_name=bucket_name, region_name=region) if bucket_name else None)


def vector_provider_for(policy: dict[str, Any], provider_for: Callable[..., Any] | None = None) -> Any:
    """The S3 Vectors provider for the publication's index (the one the suggestions use), or None when it has no ``vectorIndexArn`` or the runtime
    cannot build one; the signal packs then run without the cluster signal."""
    arn = policy.get("vectorIndexArn")
    if not arn:
        return None
    try:
        if provider_for:
            return provider_for(arn)
        from papyrus_knowledge_query.services import S3VectorsProvider

        return S3VectorsProvider(vector_index_arn=arn, region_name=os.environ.get("AWS_REGION"))
    except Exception:  # noqa: BLE001 - no provider means no cluster signal, not a failed run
        return None


REFERENCE_ANCHOR_PREFIX = "reference#"   # the anchor key of a conversation about a Reference (home_page/threads.py)


def signal_lineages(client: Any) -> set[str]:
    """The lineage ids of the References a person worked on besides voting: a conversation is anchored on it, or an editor tagged it with a concept (a vote is on
    the Reference row itself). Unreadable threads or links mean no signal from them. Read by the drafting step (``monitoring_stories``), not by the vector pass."""
    from .ideas.signal_inputs import human_tagged_lineages

    try:
        anchored = {str(thread.get("primaryAnchorKey") or "").removeprefix(REFERENCE_ANCHOR_PREFIX)
                    for thread in client.list_records("MessageThread") if thread and str(thread.get("primaryAnchorKey") or "").startswith(REFERENCE_ANCHOR_PREFIX)}
    except Exception:  # noqa: BLE001
        anchored = set()
    return anchored | human_tagged_lineages(client)


# --- the saved place -------------------------------------------------------------------------------------------------------------------------

def parse_state(value: str | None) -> dict[str, Any] | None:
    """The saved place, or None when there is none (no value, or one written by an older pass: its watermark was over a different order, so it is not trusted)."""
    if not value or not value.startswith("{"):
        return None
    try:
        loaded = json.loads(value)
    except ValueError:
        return None
    if not isinstance(loaded, dict) or loaded.get("v") != STATE_VERSION:
        return None
    return {"since": loaded.get("since") or EPOCH, "seen": dict(loaded.get("seen") or {}), "nodesSince": loaded.get("nodesSince") or EPOCH, "nodesSeen": dict(loaded.get("nodesSeen") or {})}


def dump_state(state: dict[str, Any]) -> str:
    return json.dumps({"v": STATE_VERSION, **state}, sort_keys=True, separators=(",", ":"))


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _bound(since: str) -> str:
    """The lower bound of a read: the saved place less the overlap, in the form the index stores."""
    if since == EPOCH:
        return EPOCH
    return (_parse_time(since) - OVERLAP).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def read_changed_page(client: Any, feed: str, since: str, token: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """One page (at most ``PAGE_SIZE``) of the rows changed since ``since`` less the overlap, oldest first, and the token of the next page. One AppSync request."""
    field, query = FEEDS[feed]
    variables: dict[str, Any] = {"versionState": "current", "sortDirection": "ASC", "limit": PAGE_SIZE, "nextToken": token}
    if since != EPOCH:
        variables["updatedAt"] = {"ge": _bound(since)}
    connection = (client.graphql(query(), variables) or {}).get(field) or {}
    return [row for row in connection.get("items") or [] if row], connection.get("nextToken")


def newest_change(client: Any, feed: str) -> str:
    """The ``updatedAt`` of the newest row of a feed (one request), or the epoch when it has none."""
    field, query = FEEDS[feed]
    connection = (client.graphql(query(), {"versionState": "current", "sortDirection": "DESC", "limit": 1}) or {}).get(field) or {}
    rows = [row for row in connection.get("items") or [] if row]
    return str(rows[0].get("updatedAt") or EPOCH) if rows else EPOCH


def advance_place(since: str, seen: dict[str, str], rows: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """The saved place after ``rows`` (a finished page): the newest ``updatedAt``, and the ids within the overlap of it."""
    for row in rows:
        stamp = str(row.get("updatedAt") or "")
        if stamp and (since == EPOCH or stamp > since):
            since = stamp
    floor = _bound(since)
    remembered = {**seen, **{str(row["id"]): str(row.get("updatedAt") or "") for row in rows if row.get("id")}}
    return since, {identifier: stamp for identifier, stamp in remembered.items() if stamp >= floor}


def _fresh(rows: list[dict[str, Any]], seen: dict[str, str]) -> list[dict[str, Any]]:
    """The rows not already done: a row is done when the saved place remembers its id with the same ``updatedAt``."""
    return [row for row in rows if seen.get(str(row.get("id"))) != str(row.get("updatedAt") or "")]


# --- the pass ---------------------------------------------------------------------------------------------------------------------------------

def run_vector_pass(client: Any, publication: dict[str, Any], policy: dict[str, Any], *, now: datetime, out_of_time: Callable[[], bool],
                    maximum_cost_usd: float, embedding_key: str | None, read_watermark: Callable[[], str | None], write_watermark: Callable[[str], None],
                    services_for: Callable[..., Any] = build_services, indexer: Callable[..., dict] | None = None, full_indexer: Callable[..., dict] | None = None,
                    on_summary_written: Callable[[list[dict[str, Any]]], None] | None = None) -> dict[str, Any]:
    """Indexes what changed since the saved place; returns ``{"indexed", "conceptCardsWritten", "suggestionsQueued", "suggestionsSkippedReason",
    "indexSkippedReason", "costUsd", "stoppedBy", "changedReferences", "changedConcepts", "changeReads", "bootstrapped", "timings"}``. Never raises: a failure is
    reported as the reason. ``on_summary_written`` hears about each stored Reference summary vector (the router queues its one suggestion check there); the callables
    are the real ones unless a test passes fakes."""
    result = dict(EMPTY_RESULT)
    result["timings"] = timings = {}
    arn = policy.get("vectorIndexArn")
    if not arn:
        reason = "no vectorIndexArn in the publication's monitorStories"
        return {**result, "indexSkippedReason": reason, "suggestionsSkippedReason": reason}
    missing_client = s3vectors_client_missing_reason()
    if missing_client:
        return {**result, "indexSkippedReason": missing_client, "suggestionsSkippedReason": missing_client}
    suggestions_on = bool((policy.get("suggestions") or {}).get("enabled", True))
    if not suggestions_on:
        result["suggestionsSkippedReason"] = "suggestions are off in the publication's monitorStories"
    if not embedding_key:
        result["indexSkippedReason"] = "openai_not_configured"
        return result
    if not policy.get("storageBucketName"):
        result["indexSkippedReason"] = "no storageBucketName in the publication's monitorStories"
        return result

    from papyrus_knowledge_query import vector_index

    queued_errors: list[str] = []

    def heard(entries: list[dict[str, Any]]) -> None:
        if not suggestions_on or on_summary_written is None:
            return
        try:
            on_summary_written(entries)
            result["suggestionsQueued"] += len(entries)
        except Exception as error:  # noqa: BLE001 - the vectors are stored; the failure is reported and the by-hand command finds these References
            queued_errors.append(f"{type(error).__name__}: {str(error)[:160]}")
            result["suggestionsNotQueued"] = result.get("suggestionsNotQueued", 0) + len(entries)

    def stop_check(stats: dict[str, Any]) -> str | None:
        if out_of_time():
            return "time"
        if result["costUsd"] + embedding_cost_usd(int(stats.get("embeddingInputCharacters") or 0)) >= maximum_cost_usd:
            return "cost"
        return None

    def options(**more: Any) -> Any:
        return vector_index.VectorIndexOptions(corpus_id=publication["corpusId"], include_ontology_vectors=False, include_link_explanations=False, include_notes=False,
                                               stop_check=stop_check, on_summary_written=heard, skip_indexed=True, **more)

    def take(stats: dict[str, Any]) -> None:
        result["conceptCardsWritten"] += int(stats.get("conceptCardsToWrite") or 0)
        result["indexed"] += max(int(stats.get("vectorsWritten") or 0) - int(stats.get("conceptCardsToWrite") or 0), 0)
        result["costUsd"] += embedding_cost_usd(int(stats.get("embeddingInputCharacters") or 0))
        result["stoppedBy"] = result["stoppedBy"] or stats.get("stoppedBy")
        for name, seconds in (stats.get("timings") or {}).items():
            timings[f"index{name[0].upper()}{name[1:]}"] = round(timings.get(f"index{name[0].upper()}{name[1:]}", 0) + seconds, 2)

    def spent_all() -> str | None:
        if out_of_time():
            return "time"
        return "cost" if result["costUsd"] >= maximum_cost_usd else None

    mark = time.monotonic()
    try:
        state = parse_state(read_watermark())
        with process_environment(PAPYRUS_S3_VECTOR_INDEX_ARN=arn, OPENAI_API_KEY=embedding_key):
            services = services_for(publication, policy["storageBucketName"])
            if state is None:
                _bootstrap(client, services, options, result, take, full_indexer or vector_index.index_reference_passages, write_watermark)
            else:
                for feed in ("references", "concepts"):
                    if spent_all():
                        result["stoppedBy"] = result["stoppedBy"] or spent_all()
                        break
                    state = _follow(client, services, feed, state, options, result, take, indexer or vector_index.index_changes, write_watermark, spent_all)
    except Exception as error:  # noqa: BLE001
        result["indexSkippedReason"] = f"index sync failed ({type(error).__name__}: {str(error)[:400]})"
    if queued_errors:
        result["suggestionsQueueError"] = queued_errors[0]
    timings["passSeconds"] = round(time.monotonic() - mark, 1)
    result["costUsd"] = round(result["costUsd"], 6)
    return result


def _bootstrap(client: Any, services: Any, options: Callable[..., Any], result: dict[str, Any], take: Callable[[dict[str, Any]], None],
               full_indexer: Callable[..., dict], write_watermark: Callable[[str], None]) -> None:
    """A site with no saved place: the full sync once (what is already indexed is skipped), then the place is set to the newest change read BEFORE it started."""
    since, nodes_since = newest_change(client, "references"), newest_change(client, "concepts")
    result["changeReads"] += 2
    result["bootstrapped"] = True
    stats = full_indexer(services, options(action="sync", include_concept_cards=True))
    take(stats)
    if stats.get("stoppedBy"):
        return   # not finished: no place is saved, the next run does the same sync again (the vectors it wrote are skipped)
    write_watermark(dump_state({"since": since, "seen": {}, "nodesSince": nodes_since, "nodesSeen": {}}))


def _follow(client: Any, services: Any, feed: str, state: dict[str, Any], options: Callable[..., Any], result: dict[str, Any], take: Callable[[dict[str, Any]], None],
            changes_indexer: Callable[..., dict], write_watermark: Callable[[str], None], spent_all: Callable[[], str | None]) -> dict[str, Any]:
    """Reads the pages of one feed from the saved place, indexes the rows of each that are not already done, and moves the place over each finished page."""
    since_key, seen_key = ("since", "seen") if feed == "references" else ("nodesSince", "nodesSeen")
    token: str | None = None
    read_from = state[since_key]   # every page of this read asks from the same place: a token belongs to one query
    while True:
        rows, token = read_changed_page(client, feed, read_from, token)
        result["changeReads"] += 1
        fresh = _fresh(rows, state[seen_key])
        if fresh:
            result["changedReferences" if feed == "references" else "changedConcepts"] += len(fresh)
            stats = changes_indexer(services, options(action="sync", include_concept_cards=feed == "concepts"),
                                    references=fresh if feed == "references" else [], nodes=fresh if feed == "concepts" else [])
            take(stats)
            if stats.get("stoppedBy"):
                return state   # the page is not finished: the place stays, and the next run reads it again (what is stored is skipped)
        before = dump_state(state)
        state[since_key], state[seen_key] = advance_place(state[since_key], state[seen_key], rows)
        if dump_state(state) != before:   # a quiet day writes nothing
            write_watermark(dump_state(state))
        if not token:
            return state
        stopped = spent_all()
        if stopped:
            result["stoppedBy"] = result["stoppedBy"] or stopped
            return state
