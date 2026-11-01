"""Shared web structured metadata for references (BeautifulSoup heuristics via Biblicus)."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Callable

_HTTP_URI_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
_LOCAL_HTML_SOURCE_URI = "https://papyrus.local/imported-html"


class WebStructuredMetadataError(RuntimeError):
    def __init__(self, *, reason: dict[str, Any]):
        self.reason = dict(reason)
        super().__init__(str(self.reason.get("message") or self.reason.get("code") or "Web metadata failed."))


def is_http_source_uri(source_uri: str | None) -> bool:
    return bool(_HTTP_URI_PATTERN.match(str(source_uri or "").strip()))


def resolve_web_reference_metadata(
    source_uri: str,
    *,
    html_content: str = "",
    reference_title: str = "",
    use_llm_fallback: bool = False,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """
    Resolve title, authors, and structured metadata for a web reference URL.

    Uses the same Biblicus BeautifulSoup heuristic stack as URL text extraction
    and graph entity intake.
    """
    uri = str(source_uri or "").strip()
    html = str(html_content or "").strip()
    if html and not uri:
        uri = _LOCAL_HTML_SOURCE_URI
    if not html and fetcher is not None and is_http_source_uri(uri):
        try:
            html = str(fetcher(uri) or "")
        except Exception as exc:
            raise WebStructuredMetadataError(
                reason={"code": "html_fetch_failed", "message": str(exc), "details": {"sourceUri": uri}}
            ) from exc
    return _run_biblicus_web_metadata(
        {
            "source_uri": uri,
            "html_content": html,
            "reference_title": reference_title,
            "use_llm_fallback": use_llm_fallback,
        }
    )


def resolve_web_title_subtitle(
    source_uri: str,
    *,
    html_content: str = "",
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Return title/subtitle resolution dict for reference curation signals."""
    if html_content.strip():
        metadata = resolve_web_reference_metadata(
            source_uri or _LOCAL_HTML_SOURCE_URI,
            html_content=html_content,
            fetcher=None,
        )
    elif is_http_source_uri(source_uri):
        metadata = resolve_web_reference_metadata(source_uri, fetcher=fetcher)
    else:
        return {}
    title = str(metadata.get("title") or "").strip()
    if not title:
        return {}
    subtitle = str(metadata.get("subtitle") or "").strip()
    layers = metadata.get("layers") if isinstance(metadata.get("layers"), list) else []
    layer_hint = ", ".join(str(layer) for layer in layers[:4]) if layers else "html_heuristics"
    return {
        "title": title,
        "subtitle": subtitle,
        "titleMode": "original_web_metadata",
        "subtitleMode": "original_web_metadata" if subtitle else "unresolved",
        "source": str(metadata.get("method") or "html_heuristics"),
        "sourceUrls": [str(metadata.get("sourceUri") or source_uri).strip()] if source_uri else [],
        "rationale": f"Resolved from structured HTML metadata ({layer_hint}).",
    }


def enrich_catalog_item_web_metadata(item: dict[str, Any], *, fetcher: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Fill missing title/authors on a catalog item from web heuristics when possible."""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source_uri = str(
        item.get("source_uri")
        or item.get("sourceUri")
        or item.get("url")
        or metadata.get("source_uri")
        or metadata.get("sourceUri")
        or ""
    ).strip()
    if not source_uri and not str(item.get("html_content") or item.get("htmlContent") or "").strip():
        return item
    try:
        web_metadata = resolve_web_reference_metadata(
            source_uri,
            html_content=str(item.get("html_content") or item.get("htmlContent") or ""),
            reference_title=str(item.get("title") or ""),
            fetcher=fetcher,
        )
    except WebStructuredMetadataError:
        return item
    updated = dict(item)
    if not str(updated.get("title") or "").strip() and web_metadata.get("title"):
        updated["title"] = web_metadata["title"]
    authors = web_metadata.get("authors")
    if not updated.get("authors") and isinstance(authors, list) and authors:
        updated["authors"] = list(authors)
    meta = dict(metadata)
    meta["webStructuredMetadata"] = _web_metadata_summary(web_metadata)
    updated["metadata"] = meta
    return updated


def merge_web_metadata_into_enrichment(
    enrichment: dict[str, Any],
    *,
    source_uri: str,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Attach web heuristic summary to generic site-plugin enrichment metadata."""
    if not is_http_source_uri(source_uri):
        return enrichment
    try:
        web_metadata = resolve_web_reference_metadata(source_uri, fetcher=fetcher)
    except WebStructuredMetadataError:
        return enrichment
    merged = dict(enrichment)
    metadata = merged.get("metadata") if isinstance(merged.get("metadata"), dict) else {}
    metadata = {**metadata, "webStructuredMetadata": _web_metadata_summary(web_metadata)}
    if not str(metadata.get("title") or "").strip() and web_metadata.get("title"):
        metadata["title"] = web_metadata["title"]
    authors = web_metadata.get("authors")
    if not metadata.get("authors") and isinstance(authors, list) and authors:
        metadata["authors"] = list(authors)
    merged["metadata"] = metadata
    return merged


def _web_metadata_summary(payload: dict[str, Any]) -> dict[str, Any]:
    structured = payload.get("structured") if isinstance(payload.get("structured"), dict) else {}
    return {
        "method": payload.get("method"),
        "sourceUri": payload.get("sourceUri"),
        "title": payload.get("title"),
        "subtitle": payload.get("subtitle"),
        "authors": payload.get("authors"),
        "publicationDate": payload.get("publicationDate"),
        "layers": payload.get("layers"),
        "citationCount": payload.get("citationCount"),
        "structured": structured,
    }


def _run_biblicus_web_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    from biblicus.api import WebMetadataRequest

    from .biblicus_runner import BiblicusRunner, BiblicusRunnerError  # lazy: pydantic stays out of the Lambda zips

    try:
        response = BiblicusRunner.from_environment().extract_web_metadata(WebMetadataRequest(**payload))
    except BiblicusRunnerError as error:
        raise WebStructuredMetadataError(reason=error.failure_reason()) from error
    return response.model_dump(mode="json", exclude={"status"})


_ISO_DATE_PREFIX = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?![\d])")
_PRECISIONS = {"day": 0, "month": 1, "year": 2}
_JSON_LD_DATE_KEY = "datePublished"


class _PublicationDateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_graph_value = ""
        self.json_ld_blocks: list[str] = []
        self.time_values: list[str] = []
        self._json_ld_active = False
        self._json_ld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = {name.lower(): value or "" for name, value in attrs}
        if tag == "meta":
            key = (fields.get("property") or fields.get("name") or "").lower()
            if key == "article:published_time" and not self.open_graph_value:
                self.open_graph_value = fields.get("content", "").strip()
        elif tag == "time" and fields.get("datetime", "").strip():
            self.time_values.append(fields["datetime"].strip())
        elif tag == "script":
            self._json_ld_active = "ld+json" in fields.get("type", "").lower()
            self._json_ld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_ld_active:
            self.json_ld_blocks.append("".join(self._json_ld_buffer))
            self._json_ld_active = False

    def handle_data(self, data: str) -> None:
        if self._json_ld_active:
            self._json_ld_buffer.append(data)


def normalize_html_date(raw_value: Any) -> dict[str, str] | None:
    """Reduce an ISO 8601 date or date-time to ``{"value": YYYY-MM-DD, "precision": day|month|year}``; ``None`` when it is not a date."""
    match = _ISO_DATE_PREFIX.match(str(raw_value or "").strip())
    if not match:
        return None
    year, month, day = match.group(1), match.group(2), match.group(3)
    precision = "day" if day else "month" if month else "year"
    from datetime import date

    try:
        value = date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None
    return {"value": value.isoformat(), "precision": precision}


def _json_ld_published_values(payload: Any) -> list[str]:
    if isinstance(payload, list):
        return [value for entry in payload for value in _json_ld_published_values(entry)]
    if not isinstance(payload, dict):
        return []
    values = [str(payload[_JSON_LD_DATE_KEY])] if isinstance(payload.get(_JSON_LD_DATE_KEY), (str, int)) else []
    for key, child in payload.items():
        if key != _JSON_LD_DATE_KEY and isinstance(child, (list, dict)):
            values.extend(_json_ld_published_values(child))
    return values


def publication_date_from_html(html: str) -> dict[str, str] | None:
    """The source's own publication date read from its HTML, with where it came from.

    Tries ``article:published_time``, then JSON-LD ``datePublished`` (including inside ``@graph``), then the first ``<time datetime>``.
    Returns ``{"value", "precision", "source"}`` or ``None`` when the page declares no readable date. Never raises.
    """
    parser = _PublicationDateParser()
    try:
        parser.feed(str(html or ""))
        parser.close()
    except Exception:  # noqa: BLE001 - a page that breaks the parser declares no date
        return None
    json_ld_values: list[str] = []
    for block in parser.json_ld_blocks:
        try:
            json_ld_values.extend(_json_ld_published_values(json.loads(block)))
        except ValueError:
            continue
    for source, candidates in (
        ("og:article:published_time", [parser.open_graph_value]),
        ("json-ld", json_ld_values),
        ("time-element", parser.time_values),
    ):
        for candidate in candidates:
            normalized = normalize_html_date(candidate)
            if normalized:
                return {**normalized, "source": source}
    return None


def publication_date_resolution_record(*, source: str, precision: str, resolved_at: str) -> dict[str, str]:
    """The ``Reference.metadata.publicationDateResolution`` shape: where the date came from, how precise it is, and when it was resolved."""
    return {"source": source, "precision": precision, "resolvedAt": resolved_at}
