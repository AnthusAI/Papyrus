"""Multi-search research assignments (``research.multi``): one brief, several search providers, one merged research packet.

An editor opts an assignment into this mode when it deserves a wider net than the site's normal search. It is never the default
and nothing runs it automatically. The run has four steps, each a function that takes its collaborators as arguments so tests use
fake providers and a fake model and never reach the network:

1. ``plan_queries``: one model call turns the brief (title, summary, notes, instructions and the assignment's existing context)
   into search queries, each with a short purpose. The number of queries comes from the brief.
2. ``fan_out``: every query runs on every configured provider of ``papyrus_content.web_search``, one worker per provider so a
   provider's own rate limit is respected. A provider that fails is recorded with its failure kind and never stops the others.
3. ``merge_hits``: URLs are canonicalised and de-duplicated; each source keeps the providers and queries that found it, its best
   rank, its title and its snippets. A source only one provider found is kept.
4. ``synthesise``: one model call over the merged sources, cited by index, writes the claims with their supporting sources, where
   sources or providers disagree, and what nobody answered.

``research_multi`` writes the result through the same research-packet path as ``research.tavily-deep``
(``apply_research_packet`` and ``intake_research_packet_proposals``), so the newsroom shows it like any other packet. When no
provider answers, no packet is written: an error Message and an AssignmentEvent say why.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .assignments import assignment_metadata
from .assignments_workflow import (
    _utc_now,
    apply_research_packet,
    intake_research_packet_proposals,
    normalize_proposal_url,
    normalize_research_mode,
    update_newsroom_summary_after_research_packet_creates,
)
from .catalog import message_record
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .ids import hash_short
from .link_exploration import canonical_url
from .model_defaults import DEFAULT_LLM_MODEL
from .options import normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .records import apply_record_changes, build_record_changes
from .steering import default_corpus_key
from .tavily_deep_research import _assignment_event_record, _produces_assignment_message_relation
from .web_search import (
    PROVIDERS,
    BedrockProvider,
    OpenAIProvider,
    ProviderFailure,
    SearchError,
    SearchHit,
    SearchRequest,
    SearchUnavailable,
    http_post_json,
)

MULTI_ASSIGNMENT_TYPE = "research.multi"
MULTI_ERROR_MESSAGE_KIND = "multi_search_error"
MULTI_BACKEND = "multi_search"
RESPONSES_URL = "https://api.openai.com/v1/responses"
#: A provider that refuses its key or has spent its plan will refuse every further query too, so its remaining queries are skipped.
STOP_FAILURE_KINDS = frozenset({"auth", "plan_exhausted"})
#: The model's context window is the real bound on the synthesis input; sources past it are listed by title only.
SYNTHESIS_INPUT_CHARACTERS = 200_000

#: ``(system prompt, user text, json schema) -> parsed json``
Llm = Callable[[str, str, dict], dict]


class MultiSearchFailed(RuntimeError):
    """No packet could be made. ``message`` is what the assignment records."""


# --- planning --------------------------------------------------------------------------------------------------------------------

PLAN_SYSTEM = """You plan web searches for a reporting assignment at a publication. Given the assignment brief, return the search queries a careful reporter would run, each with a short purpose.

Rules:
- Cover different angles of the brief: who or what the subject is, the primary sources, independent verification or benchmarks, criticism and counter-claims, context and history, whatever the brief calls for. Do not repeat a query in other words.
- Write each query as a search engine query (keywords or a short question), not a sentence of instructions.
- The purpose is a few words ("who released it", "independent benchmarks", "criticism").
- Use as many queries as the brief needs. A narrow brief needs few; a broad one needs more. Never pad.
"""

PLAN_SCHEMA = {
    "type": "json_schema", "name": "search_plan", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["queries"], "properties": {"queries": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["query", "purpose"],
                                   "properties": {"query": {"type": "string"}, "purpose": {"type": "string"}}}}}},
}


def brief_text(assignment: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    """The assignment as one block of text for the planner: its title, notes and the context already on the assignment."""
    meta = meta or {}
    lines, seen = [], set()
    for label, value in (("Title", assignment.get("title")), ("Summary", assignment.get("summary")), ("Brief", assignment.get("brief")),
                         ("Instructions", assignment.get("instructions")), ("Notes", assignment.get("notes")),
                         ("Section", meta.get("sectionTitle") or meta.get("sectionKey")),
                         ("Recommended angle", meta.get("recommendedAngle")),
                         ("Focus", meta.get("primaryFocusCategoryKey")),
                         ("Topics", ", ".join(map(str, meta.get("topicScopeCategoryKeys") or [])))):
        text = normalize_string(value)
        if text and text not in seen:      # the summary and brief often repeat the title
            seen.add(text)
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def plan_queries(brief: str, llm: Llm) -> list[dict[str, str]]:
    try:
        data = llm(PLAN_SYSTEM, brief, PLAN_SCHEMA)
    except Exception as error:  # noqa: BLE001 - any model failure is a planning failure the assignment records
        raise MultiSearchFailed(f"multi-search could not plan queries: {error}") from None
    queries, seen = [], set()
    for row in (data.get("queries") if isinstance(data, dict) else None) or []:
        query = normalize_string(row.get("query")) if isinstance(row, dict) else None
        if query and query.lower() not in seen:
            seen.add(query.lower())
            queries.append({"query": query, "purpose": normalize_string(row.get("purpose")) or ""})
    if not queries:
        raise MultiSearchFailed("multi-search could not plan queries: the model returned none")
    return queries


# --- fan out ---------------------------------------------------------------------------------------------------------------------

@dataclass
class ProviderRun:
    name: str
    queries_run: int = 0
    hits: list[tuple[str, SearchHit, int]] = field(default_factory=list)      # (query, hit, rank)
    failures: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0


def configured_providers(providers: Mapping[str, Any] | None = None, environ: Mapping[str, str] | None = None) -> tuple[dict, list[dict]]:
    """The providers that can answer (a key, or credentials for Bedrock), and a record for each that cannot."""
    candidates = dict(providers) if providers is not None else {name: cls(environ=environ) for name, cls in PROVIDERS.items()}
    usable: dict[str, Any] = {}
    unavailable: list[dict] = []
    for name, provider in candidates.items():
        try:
            provider.credential()
            if isinstance(provider, BedrockProvider):
                provider.model()
        except SearchUnavailable as error:
            unavailable.append({"provider": name, "reason": str(error)})
        else:
            usable[name] = provider
    return usable, unavailable


def _run_provider(name: str, provider: Any, queries: Sequence[Mapping[str, str]], limit: int | None) -> ProviderRun:
    run = ProviderRun(name)
    for item in queries:
        started = time.monotonic()
        try:
            request = SearchRequest(item["query"]) if limit is None else SearchRequest(item["query"], limit=limit)
            response = provider.run(request)
        except SearchUnavailable as error:
            run.failures.append({"query": item["query"], "kind": "unavailable", "message": str(error)})
            break
        except ProviderFailure as error:
            run.failures.append({"query": item["query"], "kind": error.kind, **({"status": error.status} if error.status else {}),
                                 "message": str(error)})
            stop = error.kind in STOP_FAILURE_KINDS
        except SearchError as error:
            run.failures.append({"query": item["query"], "kind": "bad_response", "message": str(error)[:200]})
            stop = False
        except Exception as error:  # noqa: BLE001 - one provider's surprise must not take the others down
            run.failures.append({"query": item["query"], "kind": "network", "message": f"{type(error).__name__}: {error}"[:200]})
            stop = False
        else:
            run.queries_run += 1
            run.hits.extend((item["query"], hit, rank) for rank, hit in enumerate(response.hits, start=1))
            stop = False
        finally:
            run.elapsed_ms += int((time.monotonic() - started) * 1000)
        if stop:
            break
    return run


def fan_out(queries: Sequence[Mapping[str, str]], providers: Mapping[str, Any], *, limit: int | None = None) -> list[ProviderRun]:
    """Every query on every provider. One worker per provider, so each provider's queries stay in order and within its own pacing."""
    if not providers:
        return []
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = [pool.submit(_run_provider, name, provider, queries, limit) for name, provider in providers.items()]
        return [future.result() for future in futures]


# --- merge -----------------------------------------------------------------------------------------------------------------------

def source_key(url: str) -> str | None:
    """The identity of a page across providers: tracking parameters, fragment, host case, ``www.`` and a trailing slash don't count."""
    try:
        normalized = normalize_proposal_url(canonical_url(url))
    except ValueError:
        return None
    if not normalized:
        return None
    parts = urlparse(normalized)
    return normalized.replace(parts.netloc, parts.netloc.removeprefix("www."), 1)


def merge_hits(runs: Sequence[ProviderRun], queries: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Merged sources, best supported first: the providers that found each, the queries, best rank, title and snippets."""
    purposes = {item["query"]: item.get("purpose") or "" for item in queries}
    by_key: dict[str, dict[str, Any]] = {}
    for run in runs:
        for query, hit, rank in run.hits:
            key = source_key(hit.url)
            if not key:
                continue
            source = by_key.setdefault(key, {"url": normalize_proposal_url(canonical_url(hit.url)), "title": "", "providers": [],
                                             "queries": [], "purposes": [], "bestRank": rank, "snippets": []})
            if run.name not in source["providers"]:
                source["providers"].append(run.name)
            if query not in source["queries"]:
                source["queries"].append(query)
                if purposes.get(query) and purposes[query] not in source["purposes"]:
                    source["purposes"].append(purposes[query])
            source["bestRank"] = min(source["bestRank"], rank)
            title = normalize_string(hit.title)
            if title and title != hit.url and not source["title"]:
                source["title"] = title
            snippet = normalize_string(hit.snippet)
            if snippet and snippet not in source["snippets"]:
                source["snippets"].append(snippet)
    merged = list(by_key.values())
    for source in merged:
        source["title"] = source["title"] or source["url"]
    merged.sort(key=lambda s: (-len(s["providers"]), s["bestRank"]))     # stable: ties keep the order they were found in
    for index, source in enumerate(merged, start=1):
        source["index"] = index
    return merged


def provider_contributions(runs: Sequence[ProviderRun], sources: Sequence[Mapping[str, Any]], unavailable: Sequence[dict]) -> dict[str, dict]:
    """Per provider: queries run, hits, sources only it found, failures and time. This is what shows which providers earn their cost."""
    contribution: dict[str, dict] = {}
    for run in runs:
        found = [s for s in sources if run.name in s["providers"]]
        contribution[run.name] = {
            "queriesRun": run.queries_run,
            "hits": len(run.hits),
            "sources": len(found),
            "uniqueSources": sum(1 for s in found if s["providers"] == [run.name]),
            "failures": list(run.failures),
            "elapsedMs": run.elapsed_ms,
        }
    for row in unavailable:
        contribution[row["provider"]] = {"queriesRun": 0, "hits": 0, "sources": 0, "uniqueSources": 0, "failures": [],
                                         "elapsedMs": 0, "unavailable": row["reason"]}
    return contribution


# --- synthesis -------------------------------------------------------------------------------------------------------------------

SYNTH_SYSTEM = """You write the research packet for a reporting assignment from web sources found by several search providers. Sources are numbered [1], [2], ... and shown with the providers that found them, the queries that found them and their snippets.

Rules:
- Use only what the snippets and titles say. Do not add facts, numbers, quotes or names. A snippet is evidence of what the page says, not proof it is true.
- Each claim is one plain sentence and cites the source numbers that support it. A claim needs at least one source.
- A disagreement is where sources contradict one another or differ on a figure, a date or a judgement; state each position with the sources behind it. Providers returning different pages is not a disagreement.
- Open questions are things the brief asks that no source answered, or that sources leave unclear.
- The summary is two to four sentences for an editor deciding what to do with this assignment. Say where the evidence is thin.
- The recommended angle is one sentence, and only if the sources support one.
"""

SYNTH_SCHEMA = {
    "type": "json_schema", "name": "research_synthesis", "strict": True,
    "schema": {"type": "object", "additionalProperties": False,
               "required": ["summary", "recommended_angle", "claims", "disagreements", "open_questions"],
               "properties": {
                   "summary": {"type": "string"},
                   "recommended_angle": {"type": "string"},
                   "claims": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["claim", "sources"],
                                                          "properties": {"claim": {"type": "string"},
                                                                         "sources": {"type": "array", "items": {"type": "integer"}}}}},
                   "disagreements": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                "required": ["topic", "positions"], "properties": {
                       "topic": {"type": "string"},
                       "positions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                "required": ["position", "sources"], "properties": {
                           "position": {"type": "string"}, "sources": {"type": "array", "items": {"type": "integer"}}}}}}}},
                   "open_questions": {"type": "array", "items": {"type": "string"}},
               }},
}


def synthesis_input(brief: str, sources: Sequence[Mapping[str, Any]]) -> str:
    parts = [f"Assignment brief:\n{brief}\n\nSources:"]
    budget = SYNTHESIS_INPUT_CHARACTERS - len(parts[0])
    for source in sources:     # best supported first, so the sources cut for length are the least supported
        head = f"[{source['index']}] {source['title']} <{source['url']}> found by {', '.join(source['providers'])} for: " \
               f"{'; '.join(source['purposes'] or source['queries'])}"
        body = "\n".join(f"  - {snippet}" for snippet in source["snippets"])
        block = f"{head}\n{body}" if body and len(head) + len(body) < budget else head
        budget -= len(block) + 1
        parts.append(block)
    return "\n".join(parts)


def _valid_indices(values: Any, count: int) -> list[int]:
    out: list[int] = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= count and value not in out:
            out.append(value)
    return out


def synthesise(brief: str, sources: Sequence[Mapping[str, Any]], llm: Llm) -> dict[str, Any]:
    try:
        data = llm(SYNTH_SYSTEM, synthesis_input(brief, sources), SYNTH_SCHEMA)
    except Exception as error:  # noqa: BLE001
        raise MultiSearchFailed(f"multi-search found {len(sources)} sources but could not synthesise them: {error}") from None
    if not isinstance(data, dict) or not normalize_string(data.get("summary")):
        raise MultiSearchFailed(f"multi-search found {len(sources)} sources but the synthesis had no summary")
    count = len(sources)
    claims, dropped = [], 0
    for row in data.get("claims") or []:
        indices = _valid_indices(row.get("sources") if isinstance(row, dict) else None, count)
        text = normalize_string(row.get("claim")) if isinstance(row, dict) else None
        if text and indices:
            claims.append({"claim": text, "sources": indices})
        else:
            dropped += 1        # a claim without a real source is not kept
    disagreements = []
    for row in data.get("disagreements") or []:
        if not isinstance(row, dict):
            continue
        positions = [{"position": normalize_string(p.get("position")), "sources": _valid_indices(p.get("sources"), count)}
                     for p in row.get("positions") or [] if isinstance(p, dict) and normalize_string(p.get("position"))]
        if normalize_string(row.get("topic")) and positions:
            disagreements.append({"topic": normalize_string(row["topic"]), "positions": positions})
    return {
        "summary": normalize_string(data["summary"]),
        "recommendedAngle": normalize_string(data.get("recommended_angle")) or "",
        "claims": claims,
        "droppedClaims": dropped,
        "disagreements": disagreements,
        "openQuestions": [q for q in (normalize_string(x) for x in data.get("open_questions") or []) if q],
    }


# --- the run, as a pure function ---------------------------------------------------------------------------------------------------

def run_multi_search(
    brief: str,
    *,
    llm: Llm,
    providers: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    limit: int | None = None,
    model: str = DEFAULT_LLM_MODEL,
) -> dict[str, Any]:
    """Plan, fan out, merge, synthesise. Returns the raw research packet (what ``apply_research_packet`` takes) under ``packet``
    plus ``contribution``. Raises ``MultiSearchFailed`` with the message to record when no packet can be made."""
    usable, unavailable = configured_providers(providers, environ)
    if not usable:
        raise MultiSearchFailed("multi-search has no search provider to ask: " +
                                ("; ".join(f"{row['provider']}: {row['reason']}" for row in unavailable) or "none configured"))
    queries = plan_queries(brief, llm)
    runs = fan_out(queries, usable, limit=limit)
    sources = merge_hits(runs, queries)
    contribution = provider_contributions(runs, sources, unavailable)
    if not sources:
        failures = [f"{run.name}: " + ", ".join(sorted({f['message'] for f in run.failures})) for run in runs if run.failures]
        if failures and not any(run.queries_run for run in runs):
            raise MultiSearchFailed("no search provider answered: " + "; ".join(failures))
        raise MultiSearchFailed(f"multi-search ran {len(queries)} queries on {', '.join(usable)} and found no sources")
    synthesis = synthesise(brief, sources, llm)
    return {"packet": build_packet(queries, sources, contribution, synthesis, model=model), "contribution": contribution,
            "sources": sources, "queries": queries}


def build_packet(queries, sources, contribution, synthesis, *, model: str = DEFAULT_LLM_MODEL) -> dict[str, Any]:
    snapshots = []
    references = []
    for source in sources:
        providers = ", ".join(source["providers"])
        snapshot = {
            "rank": source["index"],
            "url": source["url"],
            "title": source["title"],
            "source_domain": (urlparse(source["url"]).netloc or "").lower(),
            "evidence_candidate_id": f"evidence-candidate-{hash_short([source['url'], source['index']])}",
            "discovery_backend": MULTI_BACKEND,
            "providers": source["providers"],
            "queries": source["queries"],
            "bestRank": source["bestRank"],
            "snippets": source["snippets"],
        }
        snapshots.append(snapshot)
        references.append({**snapshot, "ingestion_rationale":
                           f"Found by {providers} ({'; '.join(source['purposes'] or source['queries'])}): {source['title']}"})
    answered = [name for name, row in contribution.items() if row["queriesRun"]]
    return {
        "summary": synthesis["summary"],
        "recommended_angle": synthesis["recommendedAngle"] or synthesis["summary"][:200],
        "source_snapshots": snapshots,
        "proposed_references": references,
        "evidence_item_ids": [],
        "claims": synthesis["claims"],
        "disagreements": synthesis["disagreements"],
        "open_questions": synthesis["openQuestions"],
        "researchTrace": {
            "webSearches": [q["query"] for q in queries],
            "discoveryBoundary": {
                "webSearchPath": "papyrus.multi_search",
                "searchResultCount": len(snapshots),
                "searchMetadataShapeOk": True,
                "discoveryAttemptsTotal": sum(row["queriesRun"] for row in contribution.values()),
                "discoveryQueriesTried": [q["query"] for q in queries],
                "discoveryResultCounts": [len(snapshots)],
                "discoveryTerminalState": "succeeded",
            },
        },
        "synthesis": {"summary": synthesis["summary"], "recommendedAngle": synthesis["recommendedAngle"]},
        "multiSearch": {
            "queries": list(queries),
            "providers": contribution,
            "answeredProviders": answered,
            "sourceProviders": [{"index": s["index"], "url": s["url"], "providers": s["providers"], "bestRank": s["bestRank"]}
                                for s in sources],
            "droppedClaims": synthesis["droppedClaims"],
            "model": model,
        },
    }


# --- the real model call -------------------------------------------------------------------------------------------------------------

def openai_llm(*, model: str = DEFAULT_LLM_MODEL, environ: Mapping[str, str] | None = None, http=http_post_json) -> Llm:
    """The repo's OpenAI path: the Responses API with a JSON schema, keyed the same way as the OpenAI search provider."""
    provider = OpenAIProvider(environ=environ)

    def call(system: str, user: str, schema: dict) -> dict:
        body = http(RESPONSES_URL, {"Authorization": f"Bearer {provider.api_key()}"},
                    {"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                     "text": {"format": schema}})
        text = ""
        for item in body.get("output") or []:
            for part in (item.get("content") if isinstance(item, dict) else None) or []:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    text = part["text"]
        return json.loads(text)

    return call


# --- writing it to the newsroom ------------------------------------------------------------------------------------------------------

def is_multi_assignment(assignment: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> bool:
    if normalize_string(assignment.get("assignmentTypeKey")) == MULTI_ASSIGNMENT_TYPE:
        return True
    return normalize_string((meta or {}).get("researchBackend")) == MULTI_BACKEND


def create_multi_error_records(*, assignment: Mapping[str, Any], error: str, actor_label: str, now: str) -> list[dict[str, Any]]:
    message_id = f"message-multi-search-error-{hash_short([assignment['id'], error, now])}"
    message = message_record({
        "id": message_id, "messageKind": MULTI_ERROR_MESSAGE_KIND, "messageDomain": "assignment_work", "status": "active",
        "summary": "Multi-search failed", "body": error,
        "metadata": {"kind": "research.multi.failed", "assignmentId": assignment["id"], "researchBackend": MULTI_BACKEND},
        "source": "assignments research-multi", "importRunId": assignment.get("importRunId"), "authorLabel": actor_label,
        "createdAt": now, "updatedAt": now,
    })
    return [
        message,
        _produces_assignment_message_relation(assignment=dict(assignment), message_id=message_id, now=now,
                                              lifecycle="assignment-multi-search-error", message_kind=MULTI_ERROR_MESSAGE_KIND,
                                              metadata_kind="research.multi.failed"),
    ]


def research_multi(
    client: PapyrusGraphQLAuthoringClient,
    options: dict[str, Any],
    *,
    llm: Llm | None = None,
    providers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments research-multi")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments research-multi requires an assignment id.")
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    meta = assignment_metadata(client, assignment)
    if not is_multi_assignment(assignment, meta):
        raise ValueError(
            f"Assignment {assignment_id} is not {MULTI_ASSIGNMENT_TYPE}. "
            f"Create one with: papyrus research create --type {MULTI_ASSIGNMENT_TYPE} --title ..."
        )
    research_mode = normalize_research_mode(options.get("research-mode") or meta.get("researchMode") or "source_discovery")
    corpus_key = normalize_string(options.get("corpus-key")) or normalize_string(meta.get("corpusKey")) or default_corpus_key()
    actor_label = normalize_string(options.get("actor-label")) or "Papyrus content CLI"
    model = normalize_string(options.get("model")) or DEFAULT_LLM_MODEL
    brief = brief_text(assignment, meta)
    try:
        outcome = run_multi_search(brief, llm=llm or openai_llm(model=model), providers=providers, model=model)
    except MultiSearchFailed as failure:
        message = str(failure)
        if apply:
            now = _utc_now()
            records = create_multi_error_records(assignment=assignment, error=message, actor_label=actor_label, now=now)
            event = _assignment_event_record(assignment=assignment, event_type="research.multi.failed", note=message,
                                             actor_label=actor_label, now=now)
            apply_record_changes(client, build_record_changes(client, [*records, event]))
        return {"action": "failed", "assignmentId": assignment_id, "error": message}

    packet = {**outcome["packet"], "research_mode": research_mode}
    result = {
        "action": "completed" if apply else "dry-run",
        "assignmentId": assignment_id,
        "queries": outcome["queries"],
        "sourceCount": len(outcome["sources"]),
        "contribution": outcome["contribution"],
        "packet": packet if not apply else None,
    }
    if not apply:
        return result
    apply_result = apply_research_packet(client, {"assignment": assignment_id, "research-json": json.dumps(packet),
                                                  "research-mode": research_mode, "actor-label": actor_label})
    intake_result: dict[str, Any] | None = None
    if parse_boolean_option(options.get("intake-proposals"), True, "--intake-proposals"):
        intake_result = intake_research_packet_proposals(client, {
            "assignment": assignment_id,
            "config": normalize_string(options.get("config")) or "corpora/papyrus-steering.yml",
            "corpus-key": corpus_key,
            "status": options.get("status") or "pending",
            "url-text": options.get("url-text", "false"),
            "metadata-from-text": options.get("metadata-from-text", "false"),
            "actor-label": actor_label,
        })
    now = _utc_now()
    event = _assignment_event_record(
        assignment=assignment, event_type="research.multi.completed", actor_label=actor_label, now=now,
        note=f"Multi-search completed: {len(outcome['queries'])} queries, {len(outcome['sources'])} sources from "
             f"{', '.join(outcome['packet']['multiSearch']['answeredProviders'])}.")
    changes = build_record_changes(client, [event])
    apply_record_changes(client, changes)
    update_newsroom_summary_after_research_packet_creates(client, changes, actor_label=actor_label,
                                                          reason=f"assignments research-multi {assignment_id}")
    return {**result, "researchPacketMessageId": (apply_result or {}).get("messageId"),
            "registeredReferenceCount": (intake_result or {}).get("registeredReferenceCount", 0)}


def research_multi_command(flags: list[str]) -> None:
    from .graphql_authoring import create_authoring_client

    flags = list(flags)
    if flags and not flags[0].startswith("--"):          # papyrus assignments research-multi <assignment> [--dry-run]
        flags = ["--assignment", flags[0], *flags[1:]]
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = research_multi(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))
        return
    print(f"assignments\tresearch-multi\taction\t{result['action']}")
    print(f"assignments\tresearch-multi\tassignment\t{result['assignmentId']}")
    if result["action"] == "failed":
        print(f"assignments\tresearch-multi\terror\t{result['error']}")
        return
    print(f"assignments\tresearch-multi\tqueries\t{len(result['queries'])}")
    print(f"assignments\tresearch-multi\tsources\t{result['sourceCount']}")
    for name, row in result["contribution"].items():
        failed = ",".join(sorted({f["kind"] for f in row["failures"]})) or "-"
        print(f"assignments\tresearch-multi\tprovider\t{name}\tqueries={row['queriesRun']}\thits={row['hits']}\t"
              f"unique={row['uniqueSources']}\tfailures={failed}\tms={row['elapsedMs']}")
    if result.get("researchPacketMessageId"):
        print(f"assignments\tresearch-multi\tpacket\t{result['researchPacketMessageId']}")
