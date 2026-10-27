"""The one PDF text extractor: download a PDF (a decision, a paper, a filing) and read its text page by page with pypdf.

Shared by the Tactus tool ``papyrus_fetch_pdf_text`` and by the monitor-stories source reader, so a host's quirks live here once.
"""

from __future__ import annotations

import io
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

PDF_FETCH_TIMEOUT_SECONDS = 60
PDF_FETCH_USER_AGENT = "Papyrus procedure (+https://github.com/AnthusAI/Papyrus)"
TTAB_READING_ROOM_HOST = "ttab-reading-room.uspto.gov"
TTAB_DOCUMENT_PREFIX = "/ttab-document/"


def downloadable_url(url: str) -> str:
    """The address that actually serves the file. The TTAB Reading Room's canonical single-slash document path answers 404;
    the double-slash form it links itself downloads the PDF (PPY-401430). Every other address is returned unchanged."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() == TTAB_READING_ROOM_HOST and parts.path.startswith(TTAB_DOCUMENT_PREFIX) and not parts.path.startswith(TTAB_DOCUMENT_PREFIX + "/"):
        return urlunsplit(parts._replace(path=TTAB_DOCUMENT_PREFIX + "/" + parts.path[len(TTAB_DOCUMENT_PREFIX):]))
    return url


def is_pdf_bytes(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF")


def download_pdf(url: str, *, timeout: float = PDF_FETCH_TIMEOUT_SECONDS, maximum_bytes: int | None = None,
                 opener: Callable[..., object] | None = None) -> bytes:
    """The bytes at the address (made downloadable first). With ``maximum_bytes`` a larger file is truncated, not read whole."""
    request = urllib.request.Request(downloadable_url(url), headers={"User-Agent": PDF_FETCH_USER_AGENT, "Accept": "application/pdf"})
    with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
        return response.read() if maximum_bytes is None else response.read(maximum_bytes)


def extract_pages(data: bytes, first_page: int = 1, last_page: int = 0) -> tuple[int, list[dict]]:
    """(page count, [{page, text}]) for the pages in the range, numbered as in the file. last_page 0 means the end."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    page_count = len(reader.pages)
    end = page_count if last_page <= 0 else min(last_page, page_count)
    return page_count, [{"page": number, "text": reader.pages[number - 1].extract_text() or ""} for number in range(max(first_page, 1), end + 1)]
