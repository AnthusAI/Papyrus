"""The router's daily vector pass for one publication (docs/monitoring-cloud.md#vector-index-and-suggestions).

Before packs and single items, ``monitoring_stories.run_publication`` calls ``run_vector_pass``:

1. Sync the publication's vector index: the summary, source and passage vectors of the References accepted since the last pass, the summary vector of the
   pending ones (context only: their vectors are marked ``curationStatus: pending`` and every reader-facing query filters to accepted), and the concept
   cards (content-hash skipping, so an unchanged card costs nothing), and the editors' explanations of accepted links (``link_explanation`` vectors, internal
   notes: see "Link explanations" below). Every pass also reconciles the status of what is already indexed: a pending Reference
   accepted since gets its metadata rewritten (no embedding call) and its passages written, and the vectors of a rejected, archived or superseded Reference
   are deleted (``index_reference_passages`` does this on every ``sync``, whatever References it is asked to index). It is ``papyrus_knowledge_query.vector_index.index_reference_passages`` with
   ``action="sync"``, reached through the publication's own API with the router's IAM access and the site's storage bucket for the extracted text.
2. Suggest related References and concepts for each Reference accepted or pending since the last pass (``reference_suggestions.suggest_for``), cut where the
   site's own decided suggestions say (``suggestion_calibration.load_calibration``).

Link explanations: a person's note on an accepted Reference-to-Reference link or concept tag (``SemanticRelation`` ``metadata.note``) is embedded with both ends'
titles, one vector per link, marked ``audience: editor``. The vector's own ``contentHash`` and ``curationStatus`` are its watermark (the router keeps no extra
state for it): a new or edited explanation is embedded and written, an unchanged one costs nothing, and a link later rejected or with its note cleared loses its
vector, or, where this role has no ``s3vectors:DeleteVectors``, is re-marked ``curationStatus: withdrawn`` (the AccessDenied fallback above). A link read that
fails is reported as a warning and deletes nothing. Only the editors' internal knowledge query returns them (docs/internal-knowledge-research.md).

The only bounds are the run's time and its cost meter: embedding cost (text-embedding-3-small, from the characters embedded) is added to the model
spend of the publication's run. "Since the last pass" is a watermark, which the router keeps in its own table next to its other per-publication state, and the suggestions
go in the order an editor looks at the site, not in the order of the data:

* **Tier 1, signal**: a Reference a person voted on, or that has a conversation anchored on it. Newest first. The watermark lists the ids already done (the few
  hundred Reference a person touched), so a Reference that gains a vote later is suggested at the next pass wherever its date falls.
* **Tier 2, pending**, **tier 3, accepted with no human signal** (bulk imports and machine acceptances; drafting wants these, they wait last).
* Within tiers 2 and 3: **new arrivals first, then the backlog newest first**. Each tier keeps an interval ``[low, high]`` of positions (``timestamp#id``) it
  has been through. A Reference newer than ``high`` is a new arrival and is done first, oldest of the new ones first, so ``high`` only ever moves up over a finished
  prefix; the backlog is whatever is older than ``low``, newest first, so ``low`` moves down over a finished prefix. A pass the time or cost stopped saves exactly
  that, so the next pass resumes without redoing anything, and a Reference that arrives meanwhile is never behind the backlog: it is above ``high``.
  A plain timestamp written by an older pass reads as "everything up to it is done" (``high`` = it, ``low`` = nothing). A watermark in any other shape starts over.

A pass whose index sync stopped or failed leaves the watermark where it was (the vectors already written are skipped by key). The result says how much is
left (``suggestionsRemaining``).

Without ``vectorIndexArn`` in the publication's ``monitorStories`` the pass does nothing and says why, and packs run without vectors.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

EMBEDDING_USD_PER_MILLION_TOKENS = 0.02   # text-embedding-3-small
CHARACTERS_PER_TOKEN = 4   # the usual English estimate; the exact count is only known to the embedding service
ACCEPTED_INDEX = "referencesByCurationStatusKey"
INDEXED_STATUSES = ("accepted", "pending")
WATERMARK_SORT_KEY_PREFIX = "STATE#vectorSync#"
WRITTEN_OUTCOMES = ("created", "updated")
EMPTY_RESULT = {"indexed": 0, "conceptCardsWritten": 0, "linkExplanationsWritten": 0, "suggestionsWritten": 0, "suggestionsSkippedReason": None, "indexSkippedReason": None,
                "costUsd": 0.0, "stoppedBy": None, "newlyAccepted": 0, "newlyPending": 0, "suggestionsRemaining": 0}


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


def _changed_at(row: dict[str, Any]) -> str:
    return str(row.get("curationStatusUpdatedAt") or row.get("updatedAt") or row.get("createdAt") or "")


def _status_of(row: dict[str, Any]) -> str:
    pending = row.get("curationStatus") == "pending" or str(row.get("curationStatusKey") or "").endswith("#pending")
    return "pending" if pending else "accepted"


REFERENCE_ANCHOR_PREFIX = "reference#"   # the anchor key of a conversation about a Reference (home_page/threads.py)
TIERS = ("pending", "accepted")


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return (_changed_at(row), str(row["id"]))


def _split(position: str | None) -> tuple[str, str] | None:
    """A saved position as a sort key: ``timestamp#id``, or a bare timestamp (an older pass: everything up to it)."""
    if not position:
        return None
    stamp, _, identifier = position.partition("#")
    return (stamp, identifier)


def parse_watermark(value: str | None) -> dict[str, Any]:
    """The saved place: ``{"done": [ids of tier 1], "pending": {"high", "low"}, "accepted": {...}}``. A bare timestamp is the old watermark and means "all of
    it up to here is done" (``high`` = the timestamp, ``low`` = ``""``: nothing older is left). Anything else is no place: the pass starts over (vectors
    already written are skipped, so this costs time and loses nothing)."""
    if not value:
        return {}
    if value.startswith("{"):
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        if not isinstance(loaded, dict) or loaded.get("v") != 2:
            return {}
        return {"done": [str(item) for item in loaded.get("done") or []],
                **{tier: {"high": (loaded.get(tier) or {}).get("high"), "low": (loaded.get(tier) or {}).get("low")} for tier in TIERS}}
    return {"done": [], **{tier: {"high": value, "low": ""} for tier in TIERS}}


def plan_since(client: Any, publication: dict[str, Any], watermark: str | None, signal_lineages: Iterable[str] = ()) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(the References still to do in the order to do them, how that order is made of parts). A rejected Reference is not listed
    (``index_reference_passages`` removes its vectors on every sync, from the whole Reference list); a pending one accepted later changes its
    ``curationStatusUpdatedAt`` and comes round as a new accepted arrival. The parts are what ``advance`` needs to move the saved place."""
    state = parse_watermark(watermark)
    done_ids = set(state.get("done") or [])
    signalled = set(signal_lineages)
    rows: dict[str, dict[str, Any]] = {}
    for status in INDEXED_STATUSES:
        for row in client.list_by_index(ACCEPTED_INDEX, f"{publication['corpusId']}#{status}"):
            if row.get("id") and row.get("versionState", "current") == "current":
                rows[str(row["id"])] = row
    signal = [row for row in rows.values() if _is_signal(row, signalled) and str(row["id"]) not in done_ids]
    signal.sort(key=_key, reverse=True)
    others = [row for row in rows.values() if not _is_signal(row, signalled)]
    news: list[dict[str, Any]] = []
    backlog: dict[str, list[dict[str, Any]]] = {}
    for tier in TIERS:
        members = sorted((row for row in others if _status_of(row) == tier), key=_key)
        place = state.get(tier) or {}
        high, low = _split(place.get("high")), _split(place.get("low"))
        if not place or (high is None and low is None):
            backlog[tier] = members[::-1]
            continue
        news += [row for row in members if high is not None and _beyond(_key(row), high)]
        backlog[tier] = [row for row in reversed(members) if low is not None and _key(row) < low]
    ordered = [*signal, *news, *backlog["pending"], *backlog["accepted"]]
    parts = {"signal": len(signal), "news": len(news), "backlog": {tier: len(backlog[tier]) for tier in TIERS}, "state": state}
    return ordered, parts


def _beyond(key: tuple[str, str], high: tuple[str, str]) -> bool:
    """Newer than a saved ``high``: by timestamp alone when the position has no id (an older pass saved only the time)."""
    return key > high if high[1] else key[0] > high[0]


def _is_signal(row: dict[str, Any], signalled: set[str]) -> bool:
    return row.get("curationActorKind") == "human" or str(row.get("lineageId") or row["id"]) in signalled


def signal_lineages(client: Any) -> set[str]:
    """The lineage ids of the References a person worked on besides voting: a conversation is anchored on it, or an editor tagged it with a concept (a vote is on
    the Reference row itself). Unreadable threads or links mean no signal from them."""
    from .ideas.signal_inputs import human_tagged_lineages

    try:
        anchored = {str(thread.get("primaryAnchorKey") or "").removeprefix(REFERENCE_ANCHOR_PREFIX)
                    for thread in client.list_records("MessageThread") if thread and str(thread.get("primaryAnchorKey") or "").startswith(REFERENCE_ANCHOR_PREFIX)}
    except Exception:  # noqa: BLE001
        anchored = set()
    return anchored | human_tagged_lineages(client)


def references_since(client: Any, publication: dict[str, Any], watermark: str | None, signal_ids: Iterable[str] = ()) -> list[dict[str, Any]]:
    return plan_since(client, publication, watermark, signal_ids)[0]


def advance(parts: dict[str, Any], processed: list[dict[str, Any]]) -> str:
    """The saved place after the pass got through ``processed`` (a prefix of the plan's order)."""
    state = parts["state"]
    place = {"v": 2, "done": list(state.get("done") or []), **{tier: dict(state.get(tier) or {"high": None, "low": None}) for tier in TIERS}}
    signal_count, news_count = parts["signal"], parts["news"]
    for number, row in enumerate(processed):
        if number < signal_count:
            if str(row["id"]) not in place["done"]:
                place["done"].append(str(row["id"]))
            continue
        tier = _status_of(row)
        position = "#".join(_key(row))
        current = place[tier]
        if number < signal_count + news_count:   # oldest new arrival first, so `high` moves up over a finished prefix
            if not _split(current.get("high")) or _beyond(_key(row), _split(current["high"])):
                current["high"] = position
        else:   # the backlog, newest first, so `low` moves down; the first ever row also fixes `high`
            if _split(current.get("high")) is None:
                current["high"] = position
            if _split(current.get("low")) is None or _key(row) < _split(current["low"]):
                current["low"] = position
    return json.dumps(place, sort_keys=True)


def run_vector_pass(client: Any, publication: dict[str, Any], policy: dict[str, Any], *, now: datetime, out_of_time: Callable[[], bool],
                    maximum_cost_usd: float, embedding_key: str | None, read_watermark: Callable[[], str | None], write_watermark: Callable[[str], None],
                    services_for: Callable[..., Any] = build_services, indexer: Callable[..., dict] | None = None,
                    suggester: Callable[..., dict] | None = None, provider_for: Callable[..., Any] | None = None,
                    calibration_loader: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """Syncs the index and suggests for the References accepted or pending since the watermark; returns ``{"indexed", "conceptCardsWritten", "suggestionsWritten",
    "suggestionsSkippedReason", "indexSkippedReason", "costUsd", "stoppedBy", "newlyAccepted", "newlyPending"}``. Never raises: a failure is reported as the reason.
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
        newly, parts = plan_since(client, publication, watermark, signal_lineages(client))
    except Exception as error:  # noqa: BLE001
        reason = f"could not read the accepted and pending References ({type(error).__name__}: {str(error)[:160]})"
        return {**result, "indexSkippedReason": reason, "suggestionsSkippedReason": reason}
    result["newlyPending"] = sum(1 for row in newly if _status_of(row) == "pending")
    result["newlyAccepted"] = len(newly) - result["newlyPending"]
    result["suggestionsRemaining"] = len(newly)
    bucket = policy.get("storageBucketName")
    indexing_ok = False
    if not embedding_key:
        result["indexSkippedReason"] = "openai_not_configured"
    elif not bucket:
        result["indexSkippedReason"] = "no storageBucketName in the publication's monitorStories"
    else:
        indexing_ok = _sync_index(publication, policy, newly, result, services_for=services_for, indexer=indexer, embedding_key=embedding_key,
                                  out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd)
    done = 0   # how many of `newly` the pass got through
    if not (policy.get("suggestions") or {}).get("enabled", True):
        result["suggestionsSkippedReason"] = "suggestions are off in the publication's monitorStories"
        done = len(newly) if indexing_ok else 0
    elif result["stoppedBy"]:
        result["suggestionsSkippedReason"] = f"stopped by {result['stoppedBy']} while indexing"
    else:
        done = _suggest(client, publication, arn, newly, result, now=now, out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd, suggester=suggester,
                        provider_for=provider_for, calibration_loader=calibration_loader)
    result["suggestionsRemaining"] = len(newly) - done
    if newly and indexing_ok and not result.get("suggestionsError"):
        # The index is complete for everything in `newly`; the watermark moves over the References the pass got through (all of them when it finished).
        value = advance(parts, newly[:done]) if done else None
        if value:
            try:
                write_watermark(value)
            except Exception as error:  # noqa: BLE001
                result["watermarkError"] = f"{type(error).__name__}: {str(error)[:160]}"
    result["costUsd"] = round(result["costUsd"], 6)
    return result


def _sync_index(publication: dict[str, Any], policy: dict[str, Any], newly: list[dict[str, Any]], result: dict[str, Any], *, services_for: Callable[..., Any],
                indexer: Callable[..., dict] | None, embedding_key: str, out_of_time: Callable[[], bool], maximum_cost_usd: float) -> bool:
    """Runs ``index_reference_passages(action="sync")`` for the newly accepted and pending References and the concept cards. True when it completed."""
    from papyrus_knowledge_query import vector_index

    def stop_check(stats: dict[str, Any]) -> str | None:
        if out_of_time():
            return "time"
        if embedding_cost_usd(int(stats.get("embeddingInputCharacters") or 0)) >= maximum_cost_usd:
            return "cost"
        return None

    options = vector_index.VectorIndexOptions(
        action="sync", corpus_id=publication["corpusId"], reference_ids=tuple(str(row["id"]) for row in newly), skip_references=not newly,
        include_ontology_vectors=False, include_concept_cards=True, stop_check=stop_check, skip_indexed=True, include_notes=False)
    try:
        with process_environment(PAPYRUS_S3_VECTOR_INDEX_ARN=policy["vectorIndexArn"], OPENAI_API_KEY=embedding_key):
            stats = (indexer or vector_index.index_reference_passages)(services_for(publication, policy.get("storageBucketName")), options)
    except Exception as error:  # noqa: BLE001
        result["indexSkippedReason"] = f"index sync failed ({type(error).__name__}: {str(error)[:400]})"
        return False
    result["conceptCardsWritten"] = int(stats.get("conceptCardsToWrite") or 0)
    result["linkExplanationsWritten"] = int(stats.get("linkExplanationsToWrite") or 0)
    result["indexed"] = max(int(stats.get("vectorsWritten") or 0) - result["conceptCardsWritten"] - result["linkExplanationsWritten"], 0)
    result["costUsd"] += embedding_cost_usd(int(stats.get("embeddingInputCharacters") or 0))
    result["stoppedBy"] = stats.get("stoppedBy")
    return not result["stoppedBy"]


def _suggest(client: Any, publication: dict[str, Any], arn: str, newly: list[dict[str, Any]], result: dict[str, Any], *, now: datetime,
             out_of_time: Callable[[], bool], maximum_cost_usd: float, suggester: Callable[..., dict] | None, provider_for: Callable[..., Any] | None,
             calibration_loader: Callable[[Any], Any] | None) -> int:
    """Suggests for each Reference of ``newly`` in order until the time or the cost stops it; returns how many it got through (a Reference that fails or
    has no vector is passed over, as it always was)."""
    from papyrus_knowledge_query.services import S3VectorsProvider

    from . import reference_suggestions, suggestion_calibration

    suggest = suggester or reference_suggestions.suggest_for
    try:
        provider = provider_for(arn) if provider_for else S3VectorsProvider(vector_index_arn=arn, region_name=os.environ.get("AWS_REGION"))
        calibration = (calibration_loader or suggestion_calibration.load_calibration)(client)
    except Exception as error:  # noqa: BLE001
        result["suggestionsSkippedReason"] = f"suggestions could not start ({type(error).__name__}: {str(error)[:160]})"
        result["suggestionsError"] = True
        return 0
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    missing_vector = 0
    failures = 0
    done = 0
    for row in newly:
        if out_of_time():
            result["stoppedBy"] = "time"
            break
        if result["costUsd"] >= maximum_cost_usd:
            result["stoppedBy"] = "cost"
            break
        done += 1
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
    return done
