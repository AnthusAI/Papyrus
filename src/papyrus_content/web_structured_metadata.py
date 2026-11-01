"""Shared web structured metadata for references (BeautifulSoup heuristics via Biblicus)."""

from __future__ import annotations

import re
from typing import Any, Callable

from .biblicus_runner import BiblicusRunner, BiblicusRunnerError

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

    try:
        response = BiblicusRunner.from_environment().extract_web_metadata(WebMetadataRequest(**payload))
    except BiblicusRunnerError as error:
        raise WebStructuredMetadataError(reason=error.failure_reason()) from error
    return response.model_dump(mode="json", exclude={"status"})


from .publication_dates import normalize_html_date, publication_date_from_html, publication_date_resolution_record  # noqa: E402,F401  re-exported for existing callers
