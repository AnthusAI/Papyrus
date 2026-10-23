"""A short plain-text excerpt of a reference's source page, for the digest (opt-in; the only network read the digest makes)."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAXIMUM_BYTES = 400_000
EXCERPT_CHARACTERS = 1200
TIMEOUT_SECONDS = 10
USER_AGENT = "Papyrus-Ideas/0.1 (+https://github.com/AnthusAI/Papyrus)"
SKIPPED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "template"}

Fetcher = Callable[[str], str | None]


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.description = ""
        self.paragraphs: list[str] = []
        self._skip = 0
        self._paragraph: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self._skip += 1
        elif tag == "meta" and not self.description:
            fields = dict(attrs)
            if (fields.get("name") or fields.get("property") or "").lower() in {"description", "og:description"}:
                self.description = (fields.get("content") or "").strip()
        elif tag == "p" and not self._skip:
            self._paragraph = []

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS and self._skip:
            self._skip -= 1
        elif tag == "p" and self._paragraph is not None:
            text = re.sub(r"\s+", " ", "".join(self._paragraph)).strip()
            if len(text) >= 60:
                self.paragraphs.append(text)
            self._paragraph = None

    def handle_data(self, data: str) -> None:
        if self._paragraph is not None and not self._skip:
            self._paragraph.append(data)


def excerpt_from_html(html: str, limit: int = EXCERPT_CHARACTERS) -> str | None:
    parser = _Text()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - a page that will not parse has no excerpt
        return None
    parts = ([parser.description] if parser.description else []) + parser.paragraphs
    text = " ".join(parts).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def public_http_url(url: str) -> bool:
    """Only http(s) pages on public addresses: a digest must not make the machine read a local or private address."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def fetch_html(url: str) -> str | None:
    if not public_http_url(url):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - checked above
            if "html" not in (response.headers.get("Content-Type") or "").lower():
                return None
            return response.read(MAXIMUM_BYTES).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - an unreachable page only means no excerpt
        return None


def excerpt_for(url: str, fetch: Fetcher = fetch_html) -> str | None:
    html = fetch(url)
    return excerpt_from_html(html) if html else None
