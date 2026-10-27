"""Plain text of a monitored item's source for monitor stories: an HTML page, a PDF, or a thin HTML page that wraps a PDF.

``fetch_source`` returns HTML as ``str`` and a PDF as ``bytes``; ``read_source_text`` turns either into a short excerpt for the
model (the model input budget, not a limit on the source). Public http(s) only, with size and redirect guards. Never raises.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urljoin

from papyrus_content import pdf_text

from .excerpt import MAXIMUM_BYTES, TIMEOUT_SECONDS, USER_AGENT, excerpt_from_html, public_http_url

SourceFetcher = Callable[[str], str | bytes | None]

MAXIMUM_PDF_BYTES = 8_000_000
MAXIMUM_REDIRECTS = 5
EXCERPT_PAGES = 4
WRAPPER_TEXT_CHARACTERS = 300


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect may not lead off the public internet or on forever."""

    max_redirections = MAXIMUM_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urljoin(req.full_url, newurl)
        if not public_http_url(absolute):
            raise urllib.error.HTTPError(newurl, code, "redirect to a non-public address", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def fetch_source(url: str) -> str | bytes | None:
    """HTML text, PDF bytes, or None (not public, not HTML or PDF, too large, unreachable)."""
    url = pdf_text.downloadable_url(url)
    if not public_http_url(url):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"})
    try:
        with urllib.request.build_opener(_PublicRedirects).open(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - checked above
            kind = (response.headers.get("Content-Type") or "").lower()
            if "pdf" in kind or url.lower().split("?")[0].endswith(".pdf"):
                data = response.read(MAXIMUM_PDF_BYTES + 1)
                return data if pdf_text.is_pdf_bytes(data) and len(data) <= MAXIMUM_PDF_BYTES else None
            if "html" not in kind:
                return None
            return response.read(MAXIMUM_BYTES).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - an unreachable source only means no text
        return None


class _PdfLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href") if tag == "a" else None
        if href and re.search(r"\.pdf($|[?#])", href, re.IGNORECASE) and href not in self.links:
            self.links.append(href)


def main_pdf_link(html: str, base_url: str) -> str | None:
    """The first PDF a page links, as an absolute address on the page's own host (the same document, not a third party's)."""
    parser = _PdfLinks()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        return None
    host = urllib.parse.urlsplit(base_url).hostname
    for href in parser.links:
        absolute = urljoin(base_url, href)
        if urllib.parse.urlsplit(absolute).hostname == host:
            return absolute
    return None


def excerpt_from_pdf(data: bytes, limit: int) -> str | None:
    """The first pages' text, whitespace collapsed: for a decision the caption, the holding and the grounds come first."""
    try:
        _, pages = pdf_text.extract_pages(data, 1, EXCERPT_PAGES)
    except Exception:  # noqa: BLE001 - a file that will not parse has no text
        return None
    text = re.sub(r"\s+", " ", " ".join(page["text"] for page in pages)).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def read_source_text(url: str, fetch: SourceFetcher, limit: int) -> str | None:
    """Excerpt of the source at the address (HTML, PDF, or the PDF a thin page wraps), or None. Never raises."""
    try:
        content = fetch(url)
        if isinstance(content, bytes):
            return excerpt_from_pdf(content, limit)
        if not content:
            return None
        text = excerpt_from_html(content, limit)
        if text and len(text) >= WRAPPER_TEXT_CHARACTERS:
            return text
        link = main_pdf_link(content, url)
        linked = fetch(link) if link else None
        return (excerpt_from_pdf(linked, limit) if isinstance(linked, bytes) else None) or text
    except Exception:  # noqa: BLE001 - an unreadable source only means no text
        return None
