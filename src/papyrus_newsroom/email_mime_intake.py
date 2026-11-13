"""MIME parsing helpers for inbound email citation extraction."""

from __future__ import annotations

import html as html_module
import re
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import urlparse

from papyrus_newsroom.email_submissions import (
    _DOI_PATTERN,
    _URL_PATTERN,
    _direct_citation_rationale,
    _html_to_text,
    _title_from_url,
)

_HREF_PATTERN = re.compile(
    r"""href\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))""",
    re.IGNORECASE,
)
_SKIP_URL_MARKERS = (
    "unsubscribe",
    "list-unsubscribe",
    "/unsubscribe",
    "mailchi.mp/unsubscribe",
    "/opt-out",
    "preferences",
    "email-preferences",
    "doubleclick.net",
    "facebook.com/sharer",
    "twitter.com/intent",
    "linkedin.com/sharing",
    "fonts.googleapis.com",
    "schema.org",
    "w3.org/1999",
)
_SKIP_URL_PREFIXES = ("mailto:", "tel:", "javascript:", "cid:", "#")


def _normalize_href_url(raw: str) -> str | None:
    url = html_module.unescape(str(raw or "").strip())
    if not url:
        return None
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    lowered = url.lower()
    if any(lowered.startswith(prefix) for prefix in _SKIP_URL_PREFIXES):
        return None
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    return url.rstrip(".,);]")


def is_skippable_newsletter_url(url: str) -> bool:
    lowered = str(url or "").lower()
    if any(marker in lowered for marker in _SKIP_URL_MARKERS):
        return True
    host = (urlparse(lowered).netloc or "").lower()
    if host.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return True
    return False


def extract_href_urls_from_html(html: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _HREF_PATTERN.finditer(str(html or "")):
        candidate = _normalize_href_url(match.group(1) or match.group(2) or match.group(3) or "")
        if not candidate or candidate in seen:
            continue
        if is_skippable_newsletter_url(candidate):
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _citation_records_from_urls(urls: list[str]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        citations.append(
            {
                "kind": "url",
                "url": url,
                "title": _title_from_url(url),
                "ingestion_rationale": _direct_citation_rationale(url),
            }
        )
    return citations


def extract_direct_citations_from_intake_text(*, body_text: str, html_parts: list[str] | None = None) -> list[dict[str, str]]:
    """Collect citations from visible text and from HTML anchor hrefs."""
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(url: str | None) -> None:
        if not url or url in seen or is_skippable_newsletter_url(url):
            return
        seen.add(url)
        urls.append(url)

    for match in _URL_PATTERN.finditer(str(body_text or "")):
        add_url(match.group(0).rstrip(".,);]"))

    for html in html_parts or []:
        for href in extract_href_urls_from_html(html):
            add_url(href)

    citations = _citation_records_from_urls(urls)

    for match in _DOI_PATTERN.finditer(str(body_text or "")):
        doi = match.group(0).rstrip(".,);]")
        doi_url = f"https://doi.org/{doi}"
        if doi_url in seen:
            continue
        seen.add(doi_url)
        citations.append(
            {
                "kind": "doi",
                "url": doi_url,
                "doi": doi,
                "title": f"DOI {doi}",
                "ingestion_rationale": _direct_citation_rationale(doi_url),
            }
        )
    return citations


def collect_mime_text_parts(raw_bytes: bytes) -> tuple[str, list[str], list[str]]:
    """Return subject, plain text bodies, and raw HTML bodies from a MIME message."""
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            disposition = str(part.get_content_disposition() or "").lower()
            if disposition == "attachment":
                continue
            content_type = str(part.get_content_type() or "").lower()
            try:
                payload = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True)
            if content_type == "text/plain" and isinstance(payload, str):
                plain_parts.append(payload)
            elif content_type == "text/html":
                if isinstance(payload, str):
                    html_parts.append(payload)
                elif isinstance(payload, (bytes, bytearray)):
                    html_parts.append(
                        bytes(payload).decode(part.get_content_charset() or "utf-8", errors="replace")
                    )
    else:
        try:
            payload = message.get_content()
        except Exception:
            payload = message.get_payload(decode=True)
        content_type = str(message.get_content_type() or "").lower()
        if isinstance(payload, str):
            if content_type == "text/html":
                html_parts.append(payload)
            else:
                plain_parts.append(payload)
        elif isinstance(payload, (bytes, bytearray)):
            decoded = bytes(payload).decode(message.get_content_charset() or "utf-8", errors="replace")
            if content_type == "text/html":
                html_parts.append(decoded)
            else:
                plain_parts.append(decoded)
    subject = str(message.get("subject") or "").strip()
    body_text = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if not body_text and html_parts:
        body_text = _html_to_text("\n\n".join(html_parts))
    return subject, plain_parts, html_parts


def parse_inbound_mime_for_intake(raw_bytes: bytes) -> dict[str, Any]:
    subject, _plain_parts, html_parts = collect_mime_text_parts(raw_bytes)
    body_text = "\n\n".join(part.strip() for part in _plain_parts if part.strip())
    if not body_text and html_parts:
        body_text = _html_to_text("\n\n".join(html_parts))
    citations = extract_direct_citations_from_intake_text(body_text=body_text, html_parts=html_parts)
    return {
        "subject": subject,
        "bodyText": body_text.strip(),
        "htmlParts": html_parts,
        "citations": citations,
    }
