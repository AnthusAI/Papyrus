"""The router's daily vector pass for one publication (docs/monitoring-cloud.md#vector-index-and-suggestions).

Before packs and single items, ``monitoring_stories.run_publication`` calls ``run_vector_pass``:

1. Sync the publication's vector index: the summary, source and passage vectors of the References accepted since the last pass, and the concept cards
   (content-hash skipping, so an unchanged card costs nothing). It is ``papyrus_knowledge_query.vector_index.index_reference_passages`` with
   ``action="sync"``, reached through the publication's own API with the router's IAM access and the site's storage bucket for the extracted text.
2. Suggest related References and concepts for each Reference accepted since the last pass (``reference_suggestions.suggest_for``), cut where the
   site's own decided suggestions say (``suggestion_calibration.load_calibration``).

The only bounds are the run's time and its cost meter: embedding cost (text-embedding-3-small, from the characters embedded) is added to the model
spend of the publication's run. "Since the last pass" is a watermark, the newest acceptance time the pass completed, which the router keeps in its
own table next to its other per-publication state. A pass that is stopped or fails leaves the watermark where it was, so the next pass takes up the
same References (already-written vectors are skipped by key).

Without ``vectorIndexArn`` in the publication's ``monitorStories`` the pass does nothing and says why, and packs run without vectors.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

EMBEDDING_USD_PER_MILLION_TOKENS = 0.02   # text-embedding-3-small
CHARACTERS_PER_TOKEN = 4   # the usual English estimate; the exact count is only known to the embedding service
ACCEPTED_INDEX = "referencesByCurationStatusKey"
WATERMARK_SORT_KEY_PREFIX = "STATE#vectorSync#"
WRITTEN_OUTCOMES = ("created", "updated")
EMPTY_RESULT = {"indexed": 0, "conceptCardsWritten": 0, "suggestionsWritten": 0, "suggestionsSkippedReason": None, "indexSkippedReason": None,
                "costUsd": 0.0, "stoppedBy": None, "newlyAccepted": 0}


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


def accepted_since(client: Any, publication: dict[str, Any], watermark: str | None) -> list[dict[str, Any]]:
    """The publication's accepted References whose acceptance is newer than the watermark (all of them when there is none), oldest first."""
    rows = client.list_by_index(ACCEPTED_INDEX, f"{publication['corpusId']}#accepted")

    def accepted_at(row: dict[str, Any]) -> str:
        return str(row.get("curationStatusUpdatedAt") or row.get("updatedAt") or "")

    newer = [row for row in rows if row.get("id") and row.get("versionState", "current") == "current" and (not watermark or accepted_at(row) > watermark)]
    return sorted(newer, key=accepted_at)


def run_vector_pass(client: Any, publication: dict[str, Any], policy: dict[str, Any], *, now: datetime, out_of_time: Callable[[], bool],
                    maximum_cost_usd: float, embedding_key: str | None, read_watermark: Callable[[], str | None], write_watermark: Callable[[str], None],
                    services_for: Callable[..., Any] = build_services, indexer: Callable[..., dict] | None = None,
                    suggester: Callable[..., dict] | None = None, provider_for: Callable[..., Any] | None = None,
                    calibration_loader: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """Syncs the index and suggests for the newly accepted References; returns ``{"indexed", "conceptCardsWritten", "suggestionsWritten",
    "suggestionsSkippedReason", "indexSkippedReason", "costUsd", "stoppedBy", "newlyAccepted"}``. Never raises: a failure is reported as the reason.
    The callables are the real ones unless a test passes fakes."""
    result = dict(EMPTY_RESULT)
    arn = policy.get("vectorIndexArn")
    if not arn:
        reason = "no vectorIndexArn in the publication's monitorStories"
        return {**result, "indexSkippedReason": reason, "suggestionsSkippedReason": reason}
    missing_client = s3vectors_client_missing_reason()
    if missing_client:
        return {**result, "indexSkippedReason": missing_client, "suggestionsSkippedReason": missing_client}
    try:
        watermark = read_watermark()
        newly = accepted_since(client, publication, watermark)
    except Exception as error:  # noqa: BLE001
        reason = f"could not read the accepted References ({type(error).__name__}: {str(error)[:160]})"
        return {**result, "indexSkippedReason": reason, "suggestionsSkippedReason": reason}
    result["newlyAccepted"] = len(newly)
    bucket = policy.get("storageBucketName")
    indexing_ok = False
    if not embedding_key:
        result["indexSkippedReason"] = "openai_not_configured"
    elif not bucket:
        result["indexSkippedReason"] = "no storageBucketName in the publication's monitorStories"
    else:
        indexing_ok = _sync_index(publication, policy, newly, result, services_for=services_for, indexer=indexer, embedding_key=embedding_key,
                                  out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd)
    if not (policy.get("suggestions") or {}).get("enabled", True):
        result["suggestionsSkippedReason"] = "suggestions are off in the publication's monitorStories"
    elif result["stoppedBy"]:
        result["suggestionsSkippedReason"] = f"stopped by {result['stoppedBy']} while indexing"
    else:
        _suggest(client, publication, arn, newly, result, now=now, out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd, suggester=suggester,
                 provider_for=provider_for, calibration_loader=calibration_loader)
    if newly and indexing_ok and not result["stoppedBy"] and not result.get("suggestionsError"):
        try:
            write_watermark(max(str(row.get("curationStatusUpdatedAt") or row.get("updatedAt") or "") for row in newly))
        except Exception as error:  # noqa: BLE001
            result["watermarkError"] = f"{type(error).__name__}: {str(error)[:160]}"
    result["costUsd"] = round(result["costUsd"], 6)
    return result


def _sync_index(publication: dict[str, Any], policy: dict[str, Any], newly: list[dict[str, Any]], result: dict[str, Any], *, services_for: Callable[..., Any],
                indexer: Callable[..., dict] | None, embedding_key: str, out_of_time: Callable[[], bool], maximum_cost_usd: float) -> bool:
    """Runs ``index_reference_passages(action="sync")`` for the newly accepted References and the concept cards. True when it completed."""
    from papyrus_knowledge_query import vector_index

    def stop_check(stats: dict[str, Any]) -> str | None:
        if out_of_time():
            return "time"
        if embedding_cost_usd(int(stats.get("embeddingInputCharacters") or 0)) >= maximum_cost_usd:
            return "cost"
        return None

    options = vector_index.VectorIndexOptions(
        action="sync", corpus_id=publication["corpusId"], reference_ids=tuple(str(row["id"]) for row in newly), skip_references=not newly,
        include_ontology_vectors=False, include_concept_cards=True, stop_check=stop_check)
    try:
        with process_environment(PAPYRUS_S3_VECTOR_INDEX_ARN=policy["vectorIndexArn"], OPENAI_API_KEY=embedding_key):
            stats = (indexer or vector_index.index_reference_passages)(services_for(publication, policy.get("storageBucketName")), options)
    except Exception as error:  # noqa: BLE001
        result["indexSkippedReason"] = f"index sync failed ({type(error).__name__}: {str(error)[:160]})"
        return False
    result["conceptCardsWritten"] = int(stats.get("conceptCardsToWrite") or 0)
    result["indexed"] = max(int(stats.get("vectorsWritten") or 0) - result["conceptCardsWritten"], 0)
    result["costUsd"] += embedding_cost_usd(int(stats.get("embeddingInputCharacters") or 0))
    result["stoppedBy"] = stats.get("stoppedBy")
    return not result["stoppedBy"]


def _suggest(client: Any, publication: dict[str, Any], arn: str, newly: list[dict[str, Any]], result: dict[str, Any], *, now: datetime,
             out_of_time: Callable[[], bool], maximum_cost_usd: float, suggester: Callable[..., dict] | None, provider_for: Callable[..., Any] | None,
             calibration_loader: Callable[[Any], Any] | None) -> None:
    from papyrus_knowledge_query.services import S3VectorsProvider

    from . import reference_suggestions, suggestion_calibration

    suggest = suggester or reference_suggestions.suggest_for
    try:
        provider = provider_for(arn) if provider_for else S3VectorsProvider(vector_index_arn=arn, region_name=os.environ.get("AWS_REGION"))
        calibration = (calibration_loader or suggestion_calibration.load_calibration)(client)
    except Exception as error:  # noqa: BLE001
        result["suggestionsSkippedReason"] = f"suggestions could not start ({type(error).__name__}: {str(error)[:160]})"
        result["suggestionsError"] = True
        return
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    missing_vector = 0
    failures = 0
    for row in newly:
        if out_of_time():
            result["stoppedBy"] = "time"
            break
        if result["costUsd"] >= maximum_cost_usd:
            result["stoppedBy"] = "cost"
            break
        try:
            outcome = suggest(client, provider, str(row["id"]), corpus_id=publication["corpusId"], calibration=calibration, now=timestamp)
        except Exception:  # noqa: BLE001 - one Reference that fails does not stop the rest
            failures += 1
            continue
        if outcome.get("skipped"):
            missing_vector += 1
            continue
        result["suggestionsWritten"] += sum(1 for entry in (*outcome.get("references", []), *outcome.get("concepts", [])) if entry.get("outcome") in WRITTEN_OUTCOMES)
    if failures:
        result["suggestionsFailed"] = failures
    if missing_vector:
        result["suggestionsWithoutVector"] = missing_vector
