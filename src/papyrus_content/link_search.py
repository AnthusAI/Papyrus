"""Web search for link exploration: find the page a headline belongs to when its own address cannot be followed or read.

The providers live in ``web_search`` (one interface, several vendors, a configured fallback chain). This module keeps the names
link exploration has always used: ``SearchProvider``, ``SearchHit``, ``SearchUnavailable``, ``SearchError``, ``TavilySearch``
and ``default_search_provider``, which is now the configured chain (``WEB_SEARCH_PROVIDERS``; Tavily when nothing is set). With
no usable key, ``SearchUnavailable`` is raised and the explorer records ``search_unavailable``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Protocol

from .web_search import (RESULTS_REQUESTED, TIMEOUT_SECONDS, KeyReader, SearchChain, SearchError, SearchHit, SearchUnavailable,
                         TavilyProvider, read_ssm_secret)

TAVILY_ENDPOINT = TavilyProvider.endpoint
TAVILY_KEY_ENV = "TAVILY_API_KEY"
TAVILY_KEY_PARAMETER_ENV = "PAPYRUS_TAVILY_KEY_PARAMETER"

__all__ = ["RESULTS_REQUESTED", "TAVILY_ENDPOINT", "TIMEOUT_SECONDS", "SearchError", "SearchHit", "SearchProvider", "SearchUnavailable",
           "TavilySearch", "default_search_provider"]


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = RESULTS_REQUESTED) -> list[SearchHit]: ...


Post = Callable[[dict, str], dict]


class TavilySearch(TavilyProvider):
    """Tavily alone, with the ``post(payload, key)`` hook the link-exploration tests use. The key is read lazily."""

    def __init__(self, *, environ: Mapping[str, str] | None = None, post: Post | None = None, read_secret: KeyReader = read_ssm_secret) -> None:
        http = None
        if post is not None:
            def http(url, headers, payload):  # noqa: ANN001, ANN202 - adapts the hook to the shared HTTP signature
                return post(payload, headers["Authorization"].removeprefix("Bearer "))
        super().__init__(environ=os.environ if environ is None else environ, http=http, read_secret=read_secret)

    def search(self, query: str, *, limit: int = RESULTS_REQUESTED) -> list[SearchHit]:
        try:
            return super().search(query, limit=limit)
        except SearchUnavailable:
            raise SearchUnavailable("no Tavily key is configured") from None


def default_search_provider() -> SearchProvider:
    return SearchChain()
