"""Pluggable web search for Papyrus reference research.

A thin adapter over ``papyrus_content.web_search``, which owns every provider (tavily, openai, perplexity, gemini, bedrock), the
key lookup and the fallback chain. This module only shapes the answer into the reference-research payload the Tactus tools
read. Configuration: ``WEB_SEARCH_PROVIDERS`` (ordered, comma separated; a fallback chain) or the older ``WEB_SEARCH_PROVIDER``.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from typing import Any

from papyrus_content.model_defaults import DEFAULT_LLM_MODEL
from papyrus_content.web_search import (CHAIN_ENV, DEFAULT_CHAIN, PROVIDERS, SINGLE_ENV, OpenAIProvider, SearchChain, SearchRequest, SearchResponse,
                                        chain_names, parse_names)

WebSearchProviderName = str
WEB_SEARCH_PROVIDER_ENV = SINGLE_ENV
WEB_SEARCH_PROVIDERS_ENV = CHAIN_ENV
WEB_SEARCH_PATH = "papyrus.reference.web_search"
DEFAULT_WEB_SEARCH_PROVIDER: WebSearchProviderName = DEFAULT_CHAIN[0]
_SUPPORTED_PROVIDERS: frozenset[str] = frozenset(PROVIDERS)


def normalize_web_search_provider(value: Any) -> WebSearchProviderName:
    """The first provider of the configured chain: an explicit name wins, then ``WEB_SEARCH_PROVIDERS``, ``WEB_SEARCH_PROVIDER``, tavily."""
    return web_search_chain_names(value)[0]


def web_search_chain_names(value: Any = None) -> list[str]:
    """The ordered provider chain. ``value`` (a name, a comma list or a list) overrides the environment."""
    return chain_names(parse_names(value) or None)


def configured_web_search_provider() -> WebSearchProviderName:
    return normalize_web_search_provider(None)


def reference_web_search(
    *,
    query: str,
    max_results: int = 20,
    model: str = DEFAULT_LLM_MODEL,
    return_token_budget: str = "default",
    provider: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    query = _required(query, "query")
    try:
        limit = int(max_results)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))
    names = web_search_chain_names(provider)
    chosen = {"openai": OpenAIProvider(model=model)} if model and model != DEFAULT_LLM_MODEL else {}   # a caller's model is the OpenAI one
    chain = SearchChain(names, providers=chosen)
    request = SearchRequest(query, limit=limit, want_answer=True, include_domains=tuple(include_domains or ()),
                            exclude_domains=tuple(exclude_domains or ()))
    response = chain.run(request)
    payload = _payload(query, limit, response, model=model, return_token_budget=return_token_budget)
    payload["provider"] = response.provider
    payload["metadata"]["web_search_provider"] = response.provider
    payload["metadata"]["web_search_path"] = WEB_SEARCH_PATH
    payload["metadata"]["web_search_chain"] = names
    payload["metadata"]["web_search_skipped"] = response.skipped_records()
    return payload


def _payload(query: str, limit: int, response: SearchResponse, *, model: str, return_token_budget: str) -> dict[str, Any]:
    results = []
    for rank, hit in enumerate(response.hits, start=1):
        row: dict[str, Any] = {
            "rank": rank,
            "url": hit.url,
            "source_domain": urllib.parse.urlparse(hit.url).netloc.lower(),
            "title": hit.title or hit.url,
            "evidence_candidate_id": f"evidence-candidate-{_hash_short([query, hit.url, rank])}",
        }
        if hit.snippet:
            row["snippet"] = hit.snippet
        if hit.score is not None:
            row["score"] = hit.score
        results.append(row)
    metadata = {
        "answer": response.answer,
        "result_count": len(results),
        "untruncated_result_count": response.meta.get("untruncated_result_count", len(results)),
        "request": {"query": query, "max_results": limit},
        "usage": response.usage,
        **{k: v for k, v in response.meta.items() if k in ("response_time", "request_id", "model", "id")},
    }
    return {"query": query, "results": results, "metadata": metadata}


def web_search_urls_for_title_subtitle(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any] | None = None,
    known_title: str = "",
    max_results: int = 8,
    provider: str | None = None,
) -> tuple[list[str], str]:
    catalog_entry = catalog_entry or {}
    query = _title_subtitle_search_query(
        reference=reference,
        catalog_entry=catalog_entry,
        known_title=known_title,
    )
    search = reference_web_search(
        query=query,
        max_results=max_results,
        provider=provider,
    )
    metadata = search.get("metadata") if isinstance(search.get("metadata"), dict) else {}
    answer = str(metadata.get("answer") or "").strip()
    urls: list[str] = []
    seen: set[str] = set()
    for row in search.get("results") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls, answer


def _title_subtitle_search_query(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any],
    known_title: str,
) -> str:
    parts = [
        str(known_title or "").strip(),
        str(reference.get("title") or "").strip(),
        str(reference.get("externalItemId") or "").strip(),
        str(reference.get("sourceUri") or catalog_entry.get("source_uri") or catalog_entry.get("sourceUri") or "").strip(),
        str(catalog_entry.get("doi") or "").strip(),
        str(catalog_entry.get("arxiv_id") or catalog_entry.get("arxivId") or "").strip(),
    ]
    query = " ".join(part for part in parts if part).strip()
    return query[:500] if query else "reference bibliographic title subtitle"


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _hash_short(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
