"""Link exploration: from any address (and whatever we know about the item) to its real destination and readable text.

``explore(url, context)`` is the one tool every caller uses: email intake candidates, monitor stories' source text, reference
intake. It

1. **resolves** the address: HTTP redirects, ``<meta http-equiv=refresh>``, simple JavaScript ``location =`` pages and the
   destinations that known tracker wrappers carry in their own parameters (Google, Substack, ``?url=`` redirectors). A wrapper that
   hides the destination (SendGrid ``ls/click?upn=``, Beehiiv, Mailchimp) is simply followed. Public http(s) only: every hop is
   checked again, the default transport connects to the address it verified, and the work is bounded only by real constraints
   (a redirect loop, a response-size guard, per-request timeouts and one overall deadline), never by a hop count;
2. **reads** the destination (HTML or PDF) with the readers the monitor stories already use;
3. **falls back to search** when the address cannot be followed or read: it searches the web for the headline (or summary, or link
   text), picks the result that best matches by title, snippet and domain, and returns it marked ``via="search"`` with the query
   and the match score so an editor knows it is not the original address;
4. returns a **typed, URL-free reason** for every failure (``REASONS``), so a failure never has to be explained from a log.

Privacy: the result carries the canonical destination only (tracking parameters stripped, fragment dropped). The address that was
passed in, and every hop between, appear nowhere in the result, in a reason, or in a log line.

Nothing here raises for a bad link. No network is used unless the default transport or search provider is used.
"""

from __future__ import annotations

import base64
import binascii
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any

from papyrus_content import pdf_text
from papyrus_content.ideas.excerpt import MAXIMUM_BYTES, TIMEOUT_SECONDS, USER_AGENT, excerpt_from_html
from papyrus_content.ideas.source_text import MAXIMUM_PDF_BYTES, WRAPPER_TEXT_CHARACTERS, excerpt_from_pdf, main_pdf_link
from papyrus_content.link_search import (
    RESULTS_REQUESTED,
    SearchError,
    SearchHit,
    SearchProvider,
    SearchUnavailable,
    default_search_provider,
)

# Every failure is one of these. None names or contains an address.
REASONS = (
    "invalid_url",          # not an absolute http(s) address
    "not_public",           # a private, loopback, link-local or otherwise non-public address, or credentials in the address
    "dns",                  # the host name does not resolve
    "timeout",              # a request, or the whole exploration, ran out of time
    "connection",           # connection refused or reset
    "tls",                  # certificate or handshake failure
    "loop",                 # redirects led back to an address already visited
    "http_4xx",             # the page is gone or refused the request (404, 410, ...)
    "http_5xx",             # the server failed
    "blocked",              # 401, 403, 429 or 999: the page exists but will not serve us
    "too_large",            # a PDF larger than the size guard
    "unreadable",           # not HTML or PDF, empty, a redirect without a target, or no text in it
    "unsafe_destination",   # the destination failed the caller's acceptance check (it looks private or like an account action)
    "no_query",             # nothing to search for (no usable headline, summary or link text)
    "search_unavailable",   # no search key is configured
    "search_error",         # the search provider failed
    "no_match",             # the search found nothing that matches
)

TEXT_LIMIT = 4000
DEADLINE_SECONDS = 90.0
MATCH_THRESHOLD = 0.6
REDIRECT_STATUSES = frozenset({300, 301, 302, 303, 307, 308})
BLOCKED_STATUSES = frozenset({401, 403, 407, 429, 999})
ACCEPT = "text/html,application/pdf;q=0.9,*/*;q=0.5"

TRACKING_PARAMETERS = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "twclid", "igshid", "li_fat_id", "mc_cid", "mc_eid",
    "_hsenc", "_hsmi", "__hssc", "__hstc", "__hsfp", "mkt_tok", "vero_id", "vero_conv", "oly_enc_id", "oly_anon_id", "_bhlid",
    "bhlid", "ck_subscriber_id", "s_cid", "cmpid", "ref_src", "ss_source", "ss_campaign_id", "trk", "trkcampaign", "wickedid",
    "elqtrackid", "sg_uid", "rb_clickid", "ito", "__s", "_ga", "_gl", "pk_campaign", "pk_kwd", "sc_cid", "mbid",
})
TRACKING_PREFIXES = ("utm_", "mc_", "hsa_", "elq", "vero_", "sg_", "oly_", "pk_")

GENERIC_LINK_TEXT = re.compile(
    r"^(?:read|view|click|see|learn|watch|listen|get|open|continue|visit|check)\b.{0,24}$|^(?:more|here|link|source|article|story|"
    r"web ?version|view (?:in|online)|unsubscribe)\b", re.IGNORECASE)
STOP_WORDS = frozenset(
    "a an and are as at be but by for from has have in is it its of on or that the their this to was were will with your you we our".split())


# --- the data the caller gets back ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """What the caller knows about the item. Only title, summary and anchor text are ever searched; none of it is an address."""

    title: str = ""
    summary: str = ""
    anchor_text: str = ""
    sender: str = ""
    publication: str = ""


@dataclass(frozen=True)
class SearchMatch:
    query: str
    score: float
    provider: str
    title: str = ""
    provider_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"query": self.query, "matchScore": self.score, "provider": self.provider, "matchedTitle": self.title,
                **({"providerScore": self.provider_score} if self.provider_score is not None else {})}


@dataclass(frozen=True)
class Exploration:
    """The result. ``ok`` means ``url`` is a destination (and, when text was wanted, ``text`` is its readable text).

    ``via`` is ``"direct"`` for the address that was given and ``"search"`` for a page found by searching, in which case
    ``search`` holds the query and the match score. ``failure`` is the final reason when not ok; ``direct_failure`` is why the
    given address fell short (it can be set on an ok result too: found via search, or resolved but not readable).
    """

    ok: bool
    url: str | None = None
    text: str | None = None
    via: str | None = None
    failure: str | None = None
    direct_failure: str | None = None
    search_failure: str | None = None
    search: SearchMatch | None = None
    readable: bool = False
    text_source: str | None = None  # "page" or "search_snippet"
    hops: int = 0

    def as_record(self) -> dict[str, Any]:
        """A JSON-safe, URL-free-except-for-the-destination description for ledgers and receipts."""
        record: dict[str, Any] = {"ok": self.ok, "via": self.via, "readable": self.readable, "hops": self.hops}
        if self.url:
            record["url"] = self.url
        for key, value in (("failure", self.failure), ("directFailure", self.direct_failure), ("searchFailure", self.search_failure),
                           ("textSource", self.text_source)):
            if value:
                record[key] = value
        if self.search:
            record["search"] = self.search.as_dict()
        return record


# --- the HTTP layer ---------------------------------------------------------------------------------------------------


class TransportError(Exception):
    """A request that produced no response. ``category`` is one of ``REASONS``."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names
    body: bytes = b""
    truncated: bool = False  # the body was cut at the size guard


Transport = Callable[[str], Response]
AcceptDestination = Callable[[str], "str | None"]


def public_addresses(host: str, port: int) -> list[str]:
    """Every address the host resolves to, refusing the host unless all of them are global."""
    try:
        found = sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except socket.gaierror:
        raise TransportError("dns") from None
    except (OSError, ValueError):
        raise TransportError("dns") from None
    if not found:
        raise TransportError("dns")
    for address in found:
        try:
            if not ipaddress.ip_address(address.split("%")[0]).is_global:
                raise TransportError("not_public")
        except ValueError:
            raise TransportError("not_public") from None
    return found


def http_transport(url: str, *, timeout: float = TIMEOUT_SECONDS) -> Response:
    """One GET, no redirects, no cookies, no ambient proxy, connected to the public address that was verified."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    addresses = public_addresses(host, port)
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    context = ssl.create_default_context() if https else None

    class Pinned(http.client.HTTPSConnection if https else http.client.HTTPConnection):  # type: ignore[misc]
        def connect(self) -> None:
            last: OSError | None = None
            for address in addresses:
                try:
                    raw = socket.create_connection((address, port), timeout=self.timeout)
                except OSError as error:
                    last = error
                    continue
                self.sock = context.wrap_socket(raw, server_hostname=host) if context else raw
                return
            raise last or OSError("no address")

    connection = Pinned(host, port, timeout=timeout, **({"context": context} if https else {}))
    try:
        connection.request("GET", path, headers={"Host": parts.netloc.rsplit("@", 1)[-1], "User-Agent": USER_AGENT, "Accept": ACCEPT,
                                                 "Accept-Encoding": "identity", "Connection": "close"})
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        kind = headers.get("content-type", "").lower()
        limit = MAXIMUM_PDF_BYTES if "pdf" in kind or parts.path.lower().endswith(".pdf") else MAXIMUM_BYTES
        body = b"" if response.status in REDIRECT_STATUSES else response.read(limit + 1)
        return Response(response.status, headers, body[:limit], truncated=len(body) > limit)
    except TransportError:
        raise
    except socket.timeout:
        raise TransportError("timeout") from None
    except ssl.SSLError:
        raise TransportError("tls") from None
    except (OSError, http.client.HTTPException):
        raise TransportError("connection") from None
    finally:
        connection.close()


# --- addresses --------------------------------------------------------------------------------------------------------


def _address_problem(url: str) -> str | None:
    """A reason this address cannot be fetched, from its text alone (DNS is the transport's job, hop by hop)."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        return "invalid_url"
    if parts.scheme not in {"http", "https"} or not host:
        return "invalid_url"
    if parts.username or parts.password:
        return "not_public"
    lowered = host.rstrip(".").lower()
    if lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".onion")):
        return "not_public"
    try:
        address = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return None if "." in lowered else "not_public"
    return None if address.is_global else "not_public"


def is_tracking_parameter(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAMETERS or lowered.startswith(TRACKING_PREFIXES)


def canonical_url(url: str) -> str:
    """The address without tracking parameters, fragment, default port or host case. Other parameters keep their order."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    port = parts.port
    if port and port != (443 if parts.scheme == "https" else 80):
        host = f"{host}:{port}"
    if ":" in (parts.hostname or "") and not host.startswith("["):
        host = f"[{host}]"
    kept = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if not is_tracking_parameter(key)]
    return urllib.parse.urlunsplit((parts.scheme.lower(), host, parts.path or "/", urllib.parse.urlencode(kept, quote_via=urllib.parse.quote), ""))


_WRAPPER_HOST_LABELS = frozenset({"click", "clicks", "link", "links", "track", "trk", "tracking", "email", "mail", "e", "em", "r", "url",
                                  "redirect", "go", "t", "l", "out", "lnk", "ct", "mandrillapp", "sendgrid", "list-manage"})
_WRAPPER_PATH = re.compile(r"(?:^|/)(?:redirect|url|click|clicks|track|r|l|out|go|away|ls/click|lt|e)(?:/|$)", re.IGNORECASE)
_WRAPPER_KEYS = ("url", "u", "q", "destination", "dest", "redirect", "redirect_url", "redirect_uri", "target", "to", "link", "href", "goto",
                 "l", "r", "e")
_JWT = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?$")


def _base64_text(value: str) -> str | None:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError):
        return None


def _http_address(value: str | None) -> str | None:
    text = (value or "").strip()
    return text if re.match(r"^https?://[^\s]+$", text, re.IGNORECASE) and _address_problem(text) is None else None


def embedded_destination(url: str) -> str | None:
    """The destination a known wrapper carries in its own address, or None (follow it instead).

    Applies only to wrapper-looking addresses (a tracker host label, a redirect/click path, Google/Substack/Facebook redirectors),
    so an ordinary page that happens to have a ``url`` parameter is left alone. SendGrid ``upn=`` and Beehiiv/Mailchimp tokens hide
    the destination and are followed, not decoded.
    """
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    labels = host.split(".")
    named = (host.endswith(("google.com", "facebook.com")) and parts.path in {"/url", "/l.php"}) or host.endswith("substack.com")
    wrapper = named or bool(set(labels[:-2]) & _WRAPPER_HOST_LABELS) or bool(_WRAPPER_PATH.search(parts.path))
    if not wrapper:
        return None
    if host.endswith("substack.com"):
        for token in [*parts.path.split("/"), *dict(urllib.parse.parse_qsl(parts.query)).values()]:
            if _JWT.match(token):
                payload = _base64_text(token.split(".")[1])
                try:
                    found = _http_address(json.loads(payload).get("e")) if payload else None
                except (ValueError, AttributeError):
                    found = None
                if found:
                    return found
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    for key in _WRAPPER_KEYS:
        value = query.get(key)
        if not value:
            continue
        found = _http_address(value) or _http_address(_base64_text(value))
        if found:
            return found
    return None


class _Refresh(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.target: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta" or self.target:
            return
        fields = {name.lower(): value or "" for name, value in attrs}
        if fields.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", fields.get("content", ""), re.IGNORECASE)
            if match:
                self.target = match.group(1).strip()


_SCRIPT_LOCATION = re.compile(
    r"""(?:(?:window|document|top|self|parent)\s*\.\s*)?location(?:\s*\.\s*href)?\s*=\s*(?!=)["']([^"']+)["']"""
    r"""|location\s*\.\s*(?:replace|assign)\s*\(\s*["']([^"']+)["']\s*\)""", re.IGNORECASE)


def page_redirect(html: str, base: str, *, thin: bool) -> str | None:
    """Where an HTML page sends the browser: a meta refresh always; a script ``location`` only on a page with no article text."""
    parser = _Refresh()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        parser.target = None
    target = parser.target
    if not target and thin:
        for match in _SCRIPT_LOCATION.finditer(html):
            raw = next(group for group in match.groups() if group)
            target = unescape(raw.replace("\\/", "/").replace("\\u0026", "&").replace("\\x26", "&"))
            if not target.startswith(("#", "javascript:", "mailto:")):
                break
            target = None
    if not target:
        return None
    absolute = urllib.parse.urljoin(base, unescape(target))
    return absolute if absolute.lower().startswith(("http://", "https://")) else None


# --- following and reading --------------------------------------------------------------------------------------------


@dataclass
class _Trace:
    url: str | None = None          # the terminal address reached (may be unreadable)
    response: Response | None = None  # its 2xx response
    failure: str | None = None
    hops: int = 0


def _charset(response: Response) -> str:
    match = re.search(r"charset=([\w-]+)", response.headers.get("content-type", ""), re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _html(response: Response) -> str:
    try:
        return response.body.decode(_charset(response), errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


def _is_pdf(response: Response, url: str) -> bool:
    return "pdf" in response.headers.get("content-type", "").lower() or pdf_text.is_pdf_bytes(response.body) or urllib.parse.urlsplit(url).path.lower().endswith(".pdf")


def _follow(start: str, transport: Transport, *, expired: Callable[[], bool]) -> _Trace:
    current, seen, hops = start, set(), 0
    while True:
        problem = _address_problem(current)
        if problem:
            return _Trace(failure=problem, hops=hops)
        if expired():
            return _Trace(failure="timeout", hops=hops)
        marker = urllib.parse.urldefrag(current)[0]
        if marker in seen:
            return _Trace(failure="loop", hops=hops)
        seen.add(marker)
        embedded = embedded_destination(current)
        if embedded:
            current, hops = embedded, hops + 1
            continue
        try:
            response = transport(pdf_text.downloadable_url(current))
        except TransportError as error:
            return _Trace(failure=error.category if error.category in REASONS else "connection", hops=hops)
        status = response.status
        if status in REDIRECT_STATUSES:
            location = response.headers.get("location", "").strip()
            if not location:
                return _Trace(failure="unreadable", hops=hops)
            current, hops = urllib.parse.urljoin(current, location), hops + 1
            continue
        if status in BLOCKED_STATUSES:
            return _Trace(url=current, failure="blocked", hops=hops)
        if 400 <= status < 500:
            return _Trace(failure="http_4xx", hops=hops)
        if status >= 500 or status < 200 or status >= 300:
            return _Trace(failure="http_5xx" if status >= 500 else "unreadable", hops=hops)
        if "html" in response.headers.get("content-type", "").lower() and not _is_pdf(response, current):
            html = _html(response)
            thin = len(excerpt_from_html(html, TEXT_LIMIT) or "") < WRAPPER_TEXT_CHARACTERS
            target = page_redirect(html, current, thin=thin)
            if target:
                current, hops = target, hops + 1
                continue
        return _Trace(url=current, response=response, hops=hops)


def _read(trace: _Trace, transport: Transport, limit: int, expired: Callable[[], bool]) -> tuple[str | None, str | None]:
    """The readable text of the terminal page and, when there is none, why."""
    response, url = trace.response, trace.url or ""
    if response is None:
        return None, trace.failure
    if _is_pdf(response, url):
        if response.truncated:
            return None, "too_large"
        text = excerpt_from_pdf(response.body, limit)
        return (text, None) if text else (None, "unreadable")
    if "html" not in response.headers.get("content-type", "").lower():
        return None, "unreadable"
    html = _html(response)
    text = excerpt_from_html(html, limit)
    if text and len(text) >= WRAPPER_TEXT_CHARACTERS:
        return text, None
    link = main_pdf_link(html, url)
    if link:
        linked = _follow(link, transport, expired=expired)
        if linked.response is not None and _is_pdf(linked.response, linked.url or ""):
            pdf, _ = _read(linked, transport, limit, expired)
            if pdf:
                return pdf, None
    return (text, None) if text else (None, "unreadable")


# --- search -----------------------------------------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS and (len(word) > 1 or word.isdigit())]


def search_query(context: Context) -> str | None:
    """The best text to search for: the headline, else the summary, else the link text. None when nothing is searchable."""
    for text in (context.title, context.summary, context.anchor_text):
        cleaned = re.sub(r"https?://\S+", " ", unescape(text or ""))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and not GENERIC_LINK_TEXT.match(cleaned) and len(_tokens(cleaned)) >= 3:
            return cleaned[:300]
    return None


def match_score(query: str, hit: SearchHit, context: Context) -> float:
    """0..1: how well the result's title and snippet cover the query's words, plus a small bonus when the domain or title names the
    publication or sender. A different story on the same site scores low because its title lacks the query's words."""
    words = set(_tokens(query))
    if not words:
        return 0.0
    title_words, snippet_words = set(_tokens(hit.title)), set(_tokens(hit.snippet))
    title_cover = len(words & title_words) / len(words)
    any_cover = len(words & (title_words | snippet_words)) / len(words)
    score = 0.7 * title_cover + 0.3 * any_cover
    host = (urllib.parse.urlsplit(hit.url).hostname or "").lower()
    names = set(_tokens(context.publication)) | set(_tokens(re.sub(r"<[^>]*>|@.*", " ", context.sender)))
    if any(name in host.replace("-", "") for name in names if len(name) > 2):
        score += 0.1
    return round(min(score, 1.0), 3)


def _search(query: str, context: Context, provider: SearchProvider, *, want_text: bool, transport: Transport, limit: int,
            accept: AcceptDestination | None, expired: Callable[[], bool]) -> tuple[Exploration | None, str]:
    """The found-via-search exploration, or (None, reason)."""
    try:
        hits = provider.search(query, limit=RESULTS_REQUESTED)
    except SearchUnavailable:
        return None, "search_unavailable"
    except SearchError:
        return None, "search_error"
    except Exception:  # noqa: BLE001 - a provider bug is a search failure, never a crash
        return None, "search_error"
    scored = sorted(((match_score(query, hit, context), hit) for hit in hits if _address_problem(hit.url) is None), key=lambda row: -row[0])
    for score, hit in scored:
        if score < MATCH_THRESHOLD:
            break
        destination = canonical_url(hit.url)
        if accept and accept(destination) is None:
            continue
        match = SearchMatch(query, score, getattr(provider, "name", "search"), hit.title, hit.score)
        if not want_text:
            return Exploration(True, destination, None, "search", None, search=match, hops=0), ""
        trace = _follow(hit.url, transport, expired=expired)
        text, _ = _read(trace, transport, limit, expired)
        source = "page"
        if not text and hit.snippet:
            text, source = hit.snippet[:limit], "search_snippet"
        if not text:
            continue
        final = canonical_url(trace.url) if trace.url else destination
        if accept and accept(final) is None:
            continue
        return Exploration(True, final, text, "search", None, search=match, readable=True, text_source=source, hops=trace.hops), ""
    return None, "no_match"


# --- the entry point --------------------------------------------------------------------------------------------------


def explore(
    url: str,
    context: Context | None = None,
    *,
    want_text: bool = True,
    text_limit: int = TEXT_LIMIT,
    transport: Transport | None = None,
    search: SearchProvider | None = None,
    accept: AcceptDestination | None = None,
    use_search: bool = True,
    deadline_seconds: float = DEADLINE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Exploration:
    """Resolve, read and (if needed) search. Never raises.

    ``want_text=False`` is for callers that need the destination only (email intake): a destination that resolves but cannot be
    read (a bot-blocked publisher, say) is still a success, marked ``readable=False``. ``accept`` receives each canonical
    destination and returns it (possibly normalized) or None to refuse it as ``unsafe_destination``. ``transport`` and ``search``
    default to the real HTTP layer and Tavily; tests pass fakes. ``use_search=False`` disables the fallback.
    """
    context = context or Context()
    transport = transport or http_transport
    started = clock()

    def expired() -> bool:
        return clock() - started > deadline_seconds

    try:
        trace = _follow(url if isinstance(url, str) else "", transport, expired=expired)
        destination = canonical_url(trace.url) if trace.url else None
        failure = trace.failure
        if destination and accept:
            accepted = accept(destination)
            if accepted is None:
                destination, failure = None, "unsafe_destination"
            else:
                destination = accepted
        text, read_failure = (None, failure)
        if destination and trace.response is not None:
            text, read_failure = _read(trace, transport, text_limit, expired) if want_text else (None, None)
        direct_failure = failure or read_failure
        if destination and (text or not want_text):
            return Exploration(True, destination, text, "direct", None, direct_failure, readable=bool(text), text_source="page" if text else None, hops=trace.hops)

        search_failure = None
        if use_search:
            query = search_query(context)
            if query is None:
                search_failure = "no_query"
            else:
                found, search_failure = _search(query, context, search or default_search_provider(), want_text=want_text, transport=transport,
                                                limit=text_limit, accept=accept, expired=expired)
                if found:
                    return Exploration(**{**found.__dict__, "direct_failure": direct_failure or "unreadable", "hops": trace.hops})
        # A destination that resolved but cannot be read is still reported when text was wanted: the caller may use the address.
        final_failure = search_failure or direct_failure or "unreadable"
        return Exploration(False, destination, None, None, final_failure, direct_failure or "unreadable", search_failure, hops=trace.hops)
    except Exception:  # noqa: BLE001 - exploration is best effort; a bug must not take down intake or a run
        return Exploration(False, None, None, None, "unreadable", "unreadable")
