"""Web search for link exploration: find the page a headline belongs to when its own address cannot be followed or read.

A small provider interface (``SearchProvider``) so callers and tests never depend on one vendor, and one real provider,
Tavily. The Tavily client talks to the same endpoint, with the same ``TAVILY_API_KEY`` environment variable, as the newsroom's
``papyrus_newsroom.web_search_providers``; it is repeated here in a few lines of standard library because the monitoring
Lambda bundles ``papyrus_content`` and nothing else. Where an environment variable cannot hold the key (the deployed Lambda),
``PAPYRUS_TAVILY_KEY_PARAMETER`` names an SSM SecureString that is read once. With neither, ``SearchUnavailable`` is raised and
the explorer records ``search_unavailable``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

TAVILY_ENDPOINT = "https://api.tavily.com/search"
TAVILY_KEY_ENV = "TAVILY_API_KEY"
TAVILY_KEY_PARAMETER_ENV = "PAPYRUS_TAVILY_KEY_PARAMETER"
TIMEOUT_SECONDS = 30
RESULTS_REQUESTED = 8


class SearchUnavailable(RuntimeError):
    """No provider is configured (no key). Not a failure of the search itself."""


class SearchError(RuntimeError):
    """The provider was reached and failed (HTTP error, bad answer, timeout)."""


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    score: float | None = None


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = RESULTS_REQUESTED) -> list[SearchHit]: ...


Post = Callable[[dict, str], dict]
KeyReader = Callable[[str], str]


def _post_json(payload: dict, api_key: str) -> dict:
    request = urllib.request.Request(
        TAVILY_ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https endpoint
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SearchError(f"http_{error.code}") from None
    except (OSError, ValueError) as error:
        raise SearchError(type(error).__name__) from None


def _read_ssm_secret(parameter: str) -> str:
    import boto3  # the Lambda runtime provides it

    return boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()


class TavilySearch:
    """Tavily web search. The key is read lazily, so constructing the provider never fails."""

    name = "tavily"

    def __init__(self, *, environ: Mapping[str, str] | None = None, post: Post = _post_json, read_secret: KeyReader = _read_ssm_secret) -> None:
        self._environ = os.environ if environ is None else environ
        self._post = post
        self._read_secret = read_secret
        self._key: str | None = None

    def api_key(self) -> str:
        if self._key:
            return self._key
        key = (self._environ.get(TAVILY_KEY_ENV) or "").strip()
        parameter = (self._environ.get(TAVILY_KEY_PARAMETER_ENV) or "").strip()
        if not key and parameter:
            try:
                key = self._read_secret(parameter)
            except Exception:  # noqa: BLE001 - a missing parameter or permission only means no search
                key = ""
        if not key:
            raise SearchUnavailable("no Tavily key is configured")
        self._key = key
        return key

    def search(self, query: str, *, limit: int = RESULTS_REQUESTED) -> list[SearchHit]:
        parsed = self._post({"query": query, "max_results": limit, "search_depth": "basic", "include_answer": False}, self.api_key())
        rows = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            raise SearchError("bad_response")
        hits = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("url") or "").strip():
                continue
            score = row.get("score")
            hits.append(SearchHit(
                url=str(row["url"]).strip(), title=str(row.get("title") or "").strip(),
                snippet=str(row.get("content") or "").strip(), score=float(score) if isinstance(score, (int, float)) else None,
            ))
        return hits


def default_search_provider() -> SearchProvider:
    return TavilySearch()
