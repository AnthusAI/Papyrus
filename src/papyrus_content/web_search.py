"""Web search behind one interface: several providers, an ordered fallback chain, chosen by configuration alone.

Standard library only (plus ``boto3`` / ``botocore`` where the Lambda runtime already provides them), because the monitoring
Lambda bundles ``papyrus_content`` and nothing else. ``papyrus_newsroom.web_search_providers`` calls this module; it keeps no
second copy of any provider.

Providers (``PROVIDERS``): ``tavily``, ``openai`` (Responses API ``web_search`` tool), ``perplexity`` (Search API), ``gemini``
(Google Search grounding) and ``bedrock`` (Web Search on Amazon Bedrock, the OpenAI-compatible Responses endpoint). Each turns a
``SearchRequest`` into that vendor's HTTP call and the answer into ``SearchHit`` rows: url, title, snippet, optional score.

Configuration (``chain_names``), first match wins:

1. a per-call override, such as a monitor's own ``searchProviders``;
2. ``WEB_SEARCH_PROVIDERS``, an ordered comma list such as ``openai,tavily``;
3. ``WEB_SEARCH_PROVIDER``, the single name that always worked;
4. ``perplexity,openai`` (``DEFAULT_CHAIN``): Perplexity Search first (about $5 per 1,000 requests), OpenAI web search when it cannot answer.

Keys (``Provider.api_key``): ``<PROVIDER>_API_KEY`` (``TAVILY_API_KEY``, ``OPENAI_API_KEY``, ``PERPLEXITY_API_KEY``,
``GEMINI_API_KEY``), or the SSM SecureString named by ``PAPYRUS_<PROVIDER>_KEY_PARAMETER``; the standard parameter names are
``/papyrus/search/<provider>-api-key``. Bedrock has no key: it signs with the AWS credentials of the caller.

Failure handling (``SearchChain.run``): a provider with no key is skipped as *unavailable*, which is not a failure. A provider
that is reached and fails is skipped with a named kind (``FAILURE_LABELS``) and the next provider is tried; the answer records
which provider answered and why each earlier one was skipped (``SearchResponse.skipped``, ``Skip.describe``). A 429 is retried
once, after the provider's ``Retry-After`` when that is short, before it counts as ``rate_limited``.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .model_defaults import DEFAULT_LLM_MODEL

TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 8_000_000
RESULTS_REQUESTED = 8
RETRY_WAIT_SECONDS = 2.0          # the pause before the one retry of a 429 that names no Retry-After
RETRY_WAIT_LIMIT_SECONDS = 10.0   # the longest idle inside one request; a longer Retry-After is left to the caller's own pacing
CHAIN_ENV = "WEB_SEARCH_PROVIDERS"
SINGLE_ENV = "WEB_SEARCH_PROVIDER"
DEFAULT_CHAIN = ("perplexity", "openai")   # Perplexity first (the normal search, cheapest), OpenAI as its fallback; Gemini and Tavily are opt-in by configuration


class SearchUnavailable(RuntimeError):
    """No provider is usable (no key). Not a failure of the search itself."""


class SearchError(RuntimeError):
    """A provider was reached and failed (HTTP error, bad answer, timeout)."""


#: The named failure kinds, as the monitor log shows them: ``tavily: plan exhausted (432)``.
FAILURE_LABELS = {
    "plan_exhausted": "plan exhausted",       # billing or quota: 402, Tavily 432/433, a 429 that says the quota is spent
    "auth": "authentication failed",           # 401, 403
    "rate_limited": "rate limited",            # 429 that persisted through the retry
    "bad_request": "request rejected",         # other 4xx
    "server_error": "provider error",          # 5xx
    "network": "unreachable",                  # timeout, DNS, connection
    "bad_response": "unreadable answer",       # 200 with a body that is not a result list
}
UNAVAILABLE = "unavailable"


class ProviderFailure(SearchError):
    """One provider was reached and failed. ``kind`` is a key of ``FAILURE_LABELS``."""

    def __init__(self, provider: str, kind: str, status: int | None = None, detail: str = "", retry_after: float | None = None):
        self.provider, self.kind, self.status, self.detail, self.retry_after = provider, kind, status, detail, retry_after
        label = FAILURE_LABELS.get(kind, kind)
        suffix = f" ({status})" if status else (f" ({detail})" if detail else "")
        super().__init__(f"{provider}: {label}{suffix}")


class SearchChainFailed(SearchError):
    """Every provider in the chain was skipped and at least one of them failed. ``skipped`` says why, in chain order."""

    def __init__(self, skipped: list["Skip"]):
        self.skipped = skipped
        waits = [s.retry_after for s in skipped if s.kind == "rate_limited"]
        self.rate_limited = bool(skipped) and all(s.kind in ("rate_limited", UNAVAILABLE) for s in skipped) and bool(waits)
        self.retry_after = max((w for w in waits if w is not None), default=None)
        super().__init__("; ".join(s.describe() for s in skipped))


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    score: float | None = None
    published: str | None = None


@dataclass(frozen=True)
class Skip:
    provider: str
    kind: str                       # UNAVAILABLE or a key of FAILURE_LABELS
    status: int | None = None
    detail: str = ""
    retry_after: float | None = None

    @property
    def failure(self) -> bool:
        return self.kind != UNAVAILABLE

    def describe(self) -> str:
        if self.kind == UNAVAILABLE:
            return f"{self.provider}: no key ({self.detail})" if self.detail else f"{self.provider}: no key"
        label = FAILURE_LABELS.get(self.kind, self.kind)
        return f"{self.provider}: {label} ({self.status})" if self.status else f"{self.provider}: {label}" + (f" ({self.detail})" if self.detail else "")

    def as_record(self) -> dict:
        return {"provider": self.provider, "kind": self.kind, **({"status": self.status} if self.status else {}),
                "message": self.describe()}


@dataclass(frozen=True)
class SearchRequest:
    query: str
    limit: int = RESULTS_REQUESTED
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    start_date: str | None = None   # YYYY-MM-DD; honoured only by providers with ``supports_date_range``
    end_date: str | None = None
    topic: str | None = None        # "news" or "general"; only Tavily has the notion
    want_answer: bool = False       # also ask for the provider's written answer, where it has one


@dataclass
class SearchResponse:
    hits: list[SearchHit]
    provider: str
    answer: str = ""
    usage: dict | None = None
    meta: dict = field(default_factory=dict)
    skipped: list[Skip] = field(default_factory=list)
    date_bounded: bool = False      # did the answering provider apply start_date / end_date

    def skipped_records(self) -> list[dict]:
        return [s.as_record() for s in self.skipped]


# --- HTTP ----------------------------------------------------------------------------------------------------------------------

class HttpStatusError(Exception):
    def __init__(self, status: int, body: str = "", headers: Mapping[str, str] | None = None):
        super().__init__(f"HTTP {status}")
        self.status, self.body, self.headers = status, body, headers or {}


Http = Callable[[str, dict, dict], dict]      # (url, headers, json payload) -> parsed JSON; raises HttpStatusError / OSError
KeyReader = Callable[[str], str]


def http_post_json(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https endpoints
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise HttpStatusError(error.code, error.read(4000).decode("utf-8", errors="replace"), dict(error.headers or {})) from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds the size bound")
    return json.loads(body.decode("utf-8"))


def read_ssm_secret(parameter: str) -> str:
    import boto3  # the Lambda runtime provides it

    return boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()


def classify(status: int, body: str = "") -> str:
    lowered = body.lower()
    if status in (402, 432, 433):
        return "plan_exhausted"
    if status in (401, 403):
        return "auth"
    if status == 429:   # OpenAI and Gemini send 429 for a spent quota as well as for pacing; the body tells them apart
        return "plan_exhausted" if any(word in lowered for word in ("insufficient_quota", "billing", "quota exceeded")) \
            and "rate limit" not in lowered else "rate_limited"
    if 500 <= status:
        return "server_error"
    return "bad_request"


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(0.0, float(str(value).strip()))
            except ValueError:
                return None
    return None


# --- Domain and text helpers ---------------------------------------------------------------------------------------------------

def bare_domain(value: str) -> str:
    return value.strip().lower().removeprefix("www.")


def host_of(url: str) -> str:
    return bare_domain(urllib.parse.urlsplit(url).hostname or "")


def _in_domains(host: str, domains: Sequence[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in map(bare_domain, domains))


def apply_domain_filters(hits: list[SearchHit], request: SearchRequest) -> list[SearchHit]:
    """Every provider's answer is filtered again here, so a filter a vendor cannot express natively still holds."""
    kept = []
    for hit in hits:
        host = host_of(hit.url)
        if request.include_domains and not _in_domains(host, request.include_domains):
            continue
        if request.exclude_domains and _in_domains(host, request.exclude_domains):
            continue
        kept.append(hit)
    return kept


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _us_date(value: str | None) -> str | None:
    return date.fromisoformat(value).strftime("%m/%d/%Y") if value else None


def _domain(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


# --- Providers -----------------------------------------------------------------------------------------------------------------

class Provider:
    """Base: key lookup, one HTTP call with a single 429 retry, failure classification. Subclasses build and parse."""

    name = ""
    supports_date_range = False

    def __init__(self, *, environ: Mapping[str, str] | None = None, http: Http | None = None, read_secret: KeyReader | None = None,
                 sleep: Callable[[float], None] = time.sleep, model: str | None = None) -> None:
        self._environ = os.environ if environ is None else environ
        self._http = http or http_post_json
        self._read_secret = read_secret or read_ssm_secret
        self._sleep = sleep
        self._model = model
        self._key: str | None = None

    @property
    def key_env(self) -> str:
        return f"{self.name.upper()}_API_KEY"

    @property
    def key_parameter_env(self) -> str:
        return f"PAPYRUS_{self.name.upper()}_KEY_PARAMETER"

    def api_key(self) -> str:
        if self._key:
            return self._key
        key = (self._environ.get(self.key_env) or "").strip()
        parameter = (self._environ.get(self.key_parameter_env) or "").strip()
        if not key and parameter:
            try:
                key = self._read_secret(parameter)
            except Exception:  # noqa: BLE001 - a missing parameter or permission only means no key
                key = ""
        if not key:
            raise SearchUnavailable(f"{self.key_env} (or {self.key_parameter_env}) is not set")
        self._key = key
        return key

    def credential(self) -> str:
        """The secret sent with the request. Raises ``SearchUnavailable``."""
        return self.api_key()

    # subclass interface
    def build(self, request: SearchRequest, credential: str) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def parse(self, request: SearchRequest, body: dict) -> SearchResponse:
        raise NotImplementedError

    def run(self, request: SearchRequest) -> SearchResponse:
        credential = self.credential()
        url, headers, payload = self.build(request, credential)
        body = self._call(url, headers, payload)
        response = self.parse(request, body)
        response.hits = apply_domain_filters(response.hits, request)[: max(1, request.limit)]
        response.provider = self.name
        response.date_bounded = self.supports_date_range and bool(request.start_date)
        return response

    def search(self, query: str, *, limit: int = RESULTS_REQUESTED) -> list[SearchHit]:
        return self.run(SearchRequest(query, limit=limit)).hits

    def _call(self, url: str, headers: dict, payload: dict) -> dict:
        for attempt in (1, 2):
            try:
                body = self._http(url, headers, payload)
            except HttpStatusError as error:
                kind = classify(error.status, error.body)
                wait = _retry_after(error.headers)
                if kind == "rate_limited" and attempt == 1 and (wait is None or wait <= RETRY_WAIT_LIMIT_SECONDS):
                    self._sleep(RETRY_WAIT_SECONDS if wait is None else wait)
                    continue
                raise ProviderFailure(self.name, kind, error.status, retry_after=wait) from None
            except (OSError, urllib.error.URLError) as error:
                raise ProviderFailure(self.name, "network", detail=type(error).__name__) from None
            except ValueError:
                raise ProviderFailure(self.name, "bad_response", detail="not JSON") from None
            if not isinstance(body, dict):
                raise ProviderFailure(self.name, "bad_response", detail="not an object")
            return body
        raise AssertionError("unreachable")  # pragma: no cover


class TavilyProvider(Provider):
    name = "tavily"
    supports_date_range = True
    endpoint = "https://api.tavily.com/search"

    def build(self, request, credential):
        payload: dict = {"query": request.query, "max_results": request.limit, "search_depth": "basic",
                         "include_answer": request.want_answer}
        if request.topic:
            payload["topic"] = request.topic
        if request.start_date:
            payload.update(start_date=request.start_date, end_date=request.end_date)
        if request.include_domains:
            payload["include_domains"] = list(request.include_domains)
        if request.exclude_domains:
            payload["exclude_domains"] = list(request.exclude_domains)
        return self.endpoint, {"Authorization": f"Bearer {credential}"}, payload

    def parse(self, request, body):
        rows = body.get("results")
        if not isinstance(rows, list):
            raise ProviderFailure(self.name, "bad_response", detail="no result list")
        hits = []
        for row in rows:
            if not isinstance(row, dict) or not _text(row.get("url")):
                continue
            score = row.get("score")
            hits.append(SearchHit(_text(row["url"]), _text(row.get("title")), _text(row.get("content")),
                                  float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
                                  _text(row.get("published_date")) or None))
        return SearchResponse(hits, self.name, answer=_text(body.get("answer")), usage=body.get("usage") if isinstance(body.get("usage"), dict) else None,
                              meta={"untruncated_result_count": len(rows), "response_time": body.get("response_time"),
                                    "request_id": body.get("request_id")})


class OpenAIProvider(Provider):
    """The Responses API ``web_search`` tool. The hits are the sources the model consulted, titled and excerpted from its citations."""

    name = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def model(self) -> str:
        return self._model or (self._environ.get("OPENAI_SEARCH_MODEL") or "").strip() or DEFAULT_LLM_MODEL

    def tool(self, request: SearchRequest) -> dict:
        tool: dict = {"type": "web_search"}
        filters = {}
        if request.include_domains:
            filters["allowed_domains"] = [bare_domain(d) for d in request.include_domains]
        if request.exclude_domains:
            filters["blocked_domains"] = [bare_domain(d) for d in request.exclude_domains]
        if filters:
            tool["filters"] = filters
        return tool

    def build(self, request, credential):
        payload = {"model": self.model(), "input": request.query, "tools": [self.tool(request)], "tool_choice": "required",
                   "include": ["web_search_call.action.sources"]}
        return self.endpoint, {"Authorization": f"Bearer {credential}"}, payload

    def parse(self, request, body):
        text = output_text(body)
        cited: dict[str, tuple[str, str]] = {}      # url -> (title, the cited span)
        sources: list[str] = []
        for item in body.get("output") or []:
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            for source in (action.get("sources") if isinstance(action, dict) else None) or []:
                if isinstance(source, dict) and _text(source.get("url")):
                    sources.append(_text(source["url"]))
            for content in item.get("content") or []:
                for note in (content.get("annotations") if isinstance(content, dict) else None) or []:
                    if isinstance(note, dict) and note.get("type") == "url_citation" and _text(note.get("url")):
                        start, end = note.get("start_index"), note.get("end_index")
                        span = _text(text[start:end]) if isinstance(start, int) and isinstance(end, int) else ""
                        cited.setdefault(_text(note["url"]), (_text(note.get("title")), span))
        if not sources and not cited and "output" not in body:
            raise ProviderFailure(self.name, "bad_response", detail="no output")
        hits, seen = [], set()
        for url in [*sources, *cited]:
            if url in seen:
                continue
            seen.add(url)
            title, span = cited.get(url, ("", ""))
            hits.append(SearchHit(url, title or url, span))
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
        return SearchResponse(hits, self.name, answer=text.strip(), usage=usage,
                              meta={"model": body.get("model"), "id": body.get("id"), "untruncated_result_count": len(hits)})


def output_text(body: dict) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    chunks = []
    for item in body.get("output") or []:
        for content in (item.get("content") if isinstance(item, dict) else None) or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


class BedrockProvider(OpenAIProvider):
    """Web Search on Amazon Bedrock: the OpenAI Responses API served by Bedrock, with a short-lived bearer token made from the
    caller's AWS credentials (what ``aws-bedrock-token-generator`` does). The caller needs ``bedrock-websearch:InvokeSearch`` (and
    ``InvokeFetch`` / ``ExternalWebAccess`` for live pages) besides inference access. It has no key to configure."""

    name = "bedrock"

    def __init__(self, *, token: Callable[[str], str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._token = token or bedrock_token
        self._token_value: str | None = None

    @property
    def key_env(self) -> str:
        return "AWS credentials"

    def region(self) -> str:
        return (self._environ.get("AWS_REGION") or self._environ.get("AWS_DEFAULT_REGION") or "us-east-1").strip()

    def model(self) -> str:
        """The Bedrock model id (``BEDROCK_SEARCH_MODEL``, for example an ``openai.`` Luna model); there is no default in code."""
        model = self._model or (self._environ.get("BEDROCK_SEARCH_MODEL") or "").strip()
        if not model:
            raise SearchUnavailable("BEDROCK_SEARCH_MODEL is not set")
        return model

    def credential(self) -> str:
        if self._token_value:
            return self._token_value
        try:
            self._token_value = self._token(self.region())
        except Exception:  # noqa: BLE001 - no AWS credentials, or botocore absent: Bedrock is simply unavailable
            raise SearchUnavailable("no AWS credentials to sign a Bedrock token") from None
        return self._token_value

    def tool(self, request):
        return {"type": "web_search", "external_web_access": False}   # only indexed-web retrieval is served today

    def build(self, request, credential):
        _, headers, payload = super().build(request, credential)
        return f"https://bedrock-mantle.{self.region()}.api.aws/openai/v1/responses", headers, payload


def bedrock_token(region: str) -> str:
    """A Bedrock bearer token (valid 12 hours): a SigV4-presigned ``CallWithBearerToken`` URL, base64, with the key prefix."""
    from botocore.auth import SigV4QueryAuth
    from botocore.awsrequest import AWSRequest
    from botocore.session import Session

    credentials = Session().get_credentials()
    if credentials is None:
        raise RuntimeError("no AWS credentials")
    signed = AWSRequest(method="POST", url="https://bedrock.amazonaws.com/", headers={"host": "bedrock.amazonaws.com"},
                        params={"Action": "CallWithBearerToken"})
    SigV4QueryAuth(credentials.get_frozen_credentials(), "bedrock", region, expires=43200).add_auth(signed)
    return "bedrock-api-key-" + base64.b64encode((signed.url.removeprefix("https://") + "&Version=1").encode()).decode()


class PerplexityProvider(Provider):
    name = "perplexity"
    supports_date_range = True
    endpoint = "https://api.perplexity.ai/search"
    MAX_RESULTS = 20       # the Search API's maximum for web search

    def build(self, request, credential):
        payload: dict = {"query": request.query, "max_results": max(1, min(request.limit, self.MAX_RESULTS))}
        if request.include_domains:
            payload["search_domain_filter"] = [bare_domain(d) for d in request.include_domains][:20]
        if request.start_date:
            payload["search_after_date_filter"] = _us_date(request.start_date)
            if request.end_date:
                payload["search_before_date_filter"] = _us_date(request.end_date)
        return self.endpoint, {"Authorization": f"Bearer {credential}"}, payload

    def parse(self, request, body):
        rows = body.get("results")
        if not isinstance(rows, list):
            raise ProviderFailure(self.name, "bad_response", detail="no result list")
        hits = [SearchHit(_text(r["url"]), _text(r.get("title")), _text(r.get("snippet")), None, _text(r.get("date")) or None)
                for r in rows if isinstance(r, dict) and _text(r.get("url"))]
        return SearchResponse(hits, self.name, meta={"id": body.get("id"), "untruncated_result_count": len(rows)})


class GeminiProvider(Provider):
    """The Gemini API with Google Search grounding (Interactions API). The hits are the model's inline ``url_citation``s; the
    older ``groundingMetadata`` shape is read too."""

    name = "gemini"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/interactions"
    DEFAULT_MODEL = "gemini-3.8-flash"

    def model(self) -> str:
        return self._model or (self._environ.get("GEMINI_SEARCH_MODEL") or "").strip() or self.DEFAULT_MODEL

    def build(self, request, credential):
        payload = {"model": self.model(), "input": request.query, "tools": [{"type": "google_search"}]}
        return self.endpoint, {"x-goog-api-key": credential}, payload

    def parse(self, request, body):
        steps, notes, answer = body.get("steps"), [], []
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict) or step.get("type") != "model_output":
                    continue
                for block in step.get("content") or []:
                    if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                        continue
                    answer.append(block["text"])
                    for note in block.get("annotations") or []:
                        if isinstance(note, dict) and note.get("type") == "url_citation" and _text(note.get("url")):
                            start, end = note.get("start_index"), note.get("end_index")
                            span = _text(block["text"][start:end]) if isinstance(start, int) and isinstance(end, int) else ""
                            notes.append((_text(note["url"]), _text(note.get("title")), span))
        elif isinstance(body.get("candidates"), list):   # generateContent's grounding metadata
            for candidate in body["candidates"]:
                meta = candidate.get("groundingMetadata") if isinstance(candidate, dict) else None
                for chunk in (meta.get("groundingChunks") if isinstance(meta, dict) else None) or []:
                    web = chunk.get("web") if isinstance(chunk, dict) else None
                    if isinstance(web, dict) and _text(web.get("uri")):
                        notes.append((_text(web["uri"]), _text(web.get("title")), ""))
                answer.extend(p.get("text", "") for p in (candidate.get("content") or {}).get("parts", []) if isinstance(p, dict))
        else:
            raise ProviderFailure(self.name, "bad_response", detail="no steps")
        hits, seen = [], set()
        for url, title, span in notes:
            if url not in seen:
                seen.add(url)
                hits.append(SearchHit(url, title or url, span))
        return SearchResponse(hits, self.name, answer="\n".join(answer).strip(), meta={"model": body.get("model") or self.model(),
                                                                                       "untruncated_result_count": len(hits)})


PROVIDERS: dict[str, type[Provider]] = {"tavily": TavilyProvider, "openai": OpenAIProvider, "perplexity": PerplexityProvider,
                                        "gemini": GeminiProvider, "bedrock": BedrockProvider}


# --- Configuration and the chain -----------------------------------------------------------------------------------------------

def parse_names(value, *, strict: bool = False) -> list[str]:
    """An ordered provider list from a comma string or a list. ``strict`` raises on an unknown name; otherwise it is dropped."""
    items = value.split(",") if isinstance(value, str) else list(value or [])
    names: list[str] = []
    for item in items:
        name = str(item or "").strip().lower()
        if not name:
            continue
        if name not in PROVIDERS:
            if strict:
                raise ValueError(f"Unknown web search provider {name!r}; expected one of {', '.join(PROVIDERS)}")
            continue
        if name not in names:
            names.append(name)
    return names


def chain_names(override=None, environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    for value in (override, env.get(CHAIN_ENV), env.get(SINGLE_ENV)):
        names = parse_names(value) if value else []
        if names:
            return names
    return list(DEFAULT_CHAIN)


class SearchChain:
    """Providers tried in order. Satisfies the ``SearchProvider`` protocol (``name``, ``search``) as well as ``run``."""

    def __init__(self, names=None, *, environ: Mapping[str, str] | None = None, providers: Mapping[str, Provider] | None = None,
                 **provider_options) -> None:
        self.names = chain_names(names, environ)
        self._providers = dict(providers or {})
        self._environ, self._options = environ, provider_options
        self.last: SearchResponse | None = None

    @property
    def name(self) -> str:
        return self.last.provider if self.last else self.names[0]

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            self._providers[name] = PROVIDERS[name](environ=self._environ, **self._options)
        return self._providers[name]

    def run(self, request: SearchRequest) -> SearchResponse:
        skipped: list[Skip] = []
        for name in self.names:
            try:
                response = self.provider(name).run(request)
            except SearchUnavailable as error:
                skipped.append(Skip(name, UNAVAILABLE, detail=str(error)))
            except ProviderFailure as error:
                skipped.append(Skip(name, error.kind, error.status, error.detail, error.retry_after))
            except SearchError as error:
                skipped.append(Skip(name, "bad_response", detail=str(error)[:100]))
            else:
                response.skipped = skipped
                self.last = response
                return response
        if all(s.kind == UNAVAILABLE for s in skipped):
            raise SearchUnavailable("no web search provider has a key: " + "; ".join(s.describe() for s in skipped))
        raise SearchChainFailed(skipped)

    def search(self, query: str, *, limit: int = RESULTS_REQUESTED) -> list[SearchHit]:
        return self.run(SearchRequest(query, limit=limit)).hits
