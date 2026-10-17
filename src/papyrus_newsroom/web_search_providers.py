"""Pluggable web search providers for Papyrus reference research."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal
from papyrus_content.model_defaults import DEFAULT_LLM_MODEL

WebSearchProviderName = Literal["tavily", "openai"]
WEB_SEARCH_PROVIDER_ENV = "WEB_SEARCH_PROVIDER"
WEB_SEARCH_PATH = "papyrus.reference.web_search"
DEFAULT_WEB_SEARCH_PROVIDER: WebSearchProviderName = "tavily"
_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"tavily", "openai"})


def normalize_web_search_provider(value: Any) -> WebSearchProviderName:
    text = str(value or "").strip().lower()
    if text in _SUPPORTED_PROVIDERS:
        return text  # type: ignore[return-value]
    configured = str(os.environ.get(WEB_SEARCH_PROVIDER_ENV, "") or "").strip().lower()
    if configured in _SUPPORTED_PROVIDERS:
        return configured  # type: ignore[return-value]
    return DEFAULT_WEB_SEARCH_PROVIDER


def configured_web_search_provider() -> WebSearchProviderName:
    return normalize_web_search_provider(None)


def reference_web_search(
    *,
    query: str,
    max_results: int = 20,
    model: str = DEFAULT_LLM_MODEL,
    return_token_budget: str = "default",
    provider: str | None = None,
) -> dict[str, Any]:
    query = _required(query, "query")
    provider_name = normalize_web_search_provider(provider)
    try:
        limit = int(max_results)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))
    if provider_name == "openai":
        payload = _search_with_openai(
            query=query,
            max_results=limit,
            model=model,
            return_token_budget=return_token_budget or "default",
        )
    else:
        payload = _search_with_tavily(query=query, max_results=limit)
    payload.setdefault("metadata", {})
    metadata = payload["metadata"]
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata["web_search_provider"] = provider_name
    metadata["web_search_path"] = WEB_SEARCH_PATH
    payload["provider"] = provider_name
    return payload


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


def _search_with_tavily(*, query: str, max_results: int) -> dict[str, Any]:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for Tavily web search.")
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": True,
    }
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tavily web search request failed: {error.code} {body[:400]}") from error
    answer = str(parsed.get("answer") or "").strip()
    raw_results = parsed.get("results") if isinstance(parsed.get("results"), list) else []
    results: list[dict[str, Any]] = []
    for rank, row in enumerate(raw_results, start=1):
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        parsed_url = urllib.parse.urlparse(url)
        title = str(row.get("title") or url).strip()
        results.append({
            "rank": rank,
            "url": url,
            "source_domain": parsed_url.netloc.lower(),
            "title": title,
            "evidence_candidate_id": f"evidence-candidate-{_hash_short([query, url, rank])}",
            "snippet": str(row.get("content") or "").strip(),
            "score": row.get("score"),
        })
    return {
        "query": query,
        "results": results,
        "metadata": {
            "answer": answer,
            "result_count": len(results),
            "untruncated_result_count": len(raw_results),
            "request": {
                "endpoint": "https://api.tavily.com/search",
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            "response_time": parsed.get("response_time"),
            "request_id": parsed.get("request_id"),
            "usage": parsed.get("usage"),
        },
    }


def _search_with_openai(
    *,
    query: str,
    max_results: int,
    model: str,
    return_token_budget: str,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI web search.")
    payload = {
        "model": model,
        "input": query,
        "tools": [{"type": "web_search", "return_token_budget": return_token_budget or "default"}],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI web search request failed: {error.code} {body[:400]}") from error
    answer = _extract_openai_response_text(parsed).strip()
    urls: list[str] = []
    seen: set[str] = set()
    for url in _openai_web_search_source_urls(parsed):
        normalized = str(url).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    results: list[dict[str, Any]] = []
    for rank, url in enumerate(urls[:max_results], start=1):
        parsed_url = urllib.parse.urlparse(url)
        results.append({
            "rank": rank,
            "url": url,
            "source_domain": parsed_url.netloc.lower(),
            "title": url,
            "evidence_candidate_id": f"evidence-candidate-{_hash_short([query, url, rank])}",
        })
    usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
    return {
        "query": query,
        "results": results,
        "metadata": {
            "answer": answer,
            "result_count": len(results),
            "untruncated_result_count": len(urls),
            "request": {
                "model": model,
                "input": query,
                "tool_choice": "required",
                "tools": [{"type": "web_search", "return_token_budget": return_token_budget or "default"}],
                "include": ["web_search_call.action.sources"],
            },
            "model": parsed.get("model"),
            "id": parsed.get("id"),
            "usage": usage,
        },
    }


def _openai_web_search_source_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for item in payload.get("output") or []:
        action = item.get("action") if isinstance(item, dict) else None
        sources = action.get("sources") if isinstance(action, dict) else None
        if isinstance(sources, list):
            urls.extend(str(source.get("url") or "") for source in sources if isinstance(source, dict))
    return [url for url in urls if url]


def _extract_openai_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _hash_short(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
