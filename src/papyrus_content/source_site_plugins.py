from __future__ import annotations

import json
import re
from html import unescape
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_IDENTIFIER_PRECEDENCE = (
    "arxiv_id",
    "doi",
    "youtube_video_id",
    "canonical_uri",
    "source_uri",
)


class SourceSitePlugin:
    key = "default"

    def match(self, source_uri: str) -> bool:
        raise NotImplementedError

    def enrich(self, *, reference: dict[str, Any], source_uri: str, fetcher: Callable[[str], str]) -> dict[str, Any]:
        raise NotImplementedError


class DoiSourcePlugin(SourceSitePlugin):
    key = "doi"
    _DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", flags=re.IGNORECASE)

    def match(self, source_uri: str) -> bool:
        parsed = urllib.parse.urlparse(source_uri)
        host = (parsed.hostname or "").lower().strip()
        if host in {"doi.org", "dx.doi.org"}:
            return True
        return bool(self._doi_from_source(source_uri))

    def enrich(self, *, reference: dict[str, Any], source_uri: str, fetcher: Callable[[str], str]) -> dict[str, Any]:
        now = _utc_now()
        doi = self._doi_from_source(source_uri)
        if not doi:
            return {
                "pluginKey": self.key,
                "canonicalSourceUri": source_uri,
                "sourceVariants": {"inputUrl": source_uri},
                "identifiers": {
                    "resolved": {"source_uri": source_uri, "canonical_uri": source_uri},
                    "candidates": [],
                    "primary": None,
                    "warnings": [{"code": "doi_unresolved", "message": "Could not parse DOI from source URI."}],
                },
                "metadata": {
                    "doiResolution": {
                        "outcome": "doi_unresolved",
                        "doi": "",
                        "resolvedAt": now,
                        "searchUsed": False,
                        "searchHit": False,
                        "apiFallbackUsed": False,
                        "candidateCount": 0,
                    }
                },
                "attachmentMetadata": {
                    "sitePlugin": self.key,
                    "doiResolution": {
                        "outcome": "doi_unresolved",
                        "doi": "",
                        "resolvedAt": now,
                    },
                },
                "warnings": [{"code": "doi_unresolved", "message": "Could not parse DOI from source URI."}],
            }

        warnings: list[dict[str, Any]] = []
        doi_url = f"https://doi.org/{doi}"
        redirect_chain: list[dict[str, Any]] = []
        final_url = doi_url
        final_content_type = ""
        resolution_outcome = "pdf_not_found"
        selected_pdf_url = ""
        selected_via = ""
        paywalled_or_blocked = False

        try:
            redirect_result = _resolve_redirect_chain(doi_url, max_hops=8)
            redirect_chain = redirect_result.get("chain") or []
            final_url = str(redirect_result.get("finalUrl") or doi_url)
            final_content_type = str(redirect_result.get("contentType") or "")
        except Exception as error:
            warnings.append({"code": "doi_redirect_failed", "message": str(error), "url": doi_url})
            resolution_outcome = "doi_unresolved"

        candidate_rows: list[dict[str, Any]] = []
        for row in _pdf_candidates_from_final_url(final_url):
            candidate_rows.append({"url": row, "source": "redirect_rules"})
        for row in _pdf_links_from_landing_page(final_url, fetcher=fetcher):
            candidate_rows.append({"url": row, "source": "landing_page"})

        delegated = self._delegate_to_known_plugin(reference=reference, source_uri=final_url, fetcher=fetcher)
        if delegated:
            delegated_canonical = _normalize_http_url(delegated.get("canonicalSourceUri"))
            if delegated_canonical:
                candidate_rows.insert(0, {"url": delegated_canonical, "source": "delegated_plugin"})
                if not selected_via:
                    selected_via = "delegated_plugin"

        selected_pdf_url, selected_via, blocked = _select_verified_pdf_candidate(candidate_rows)
        paywalled_or_blocked = paywalled_or_blocked or blocked

        search_used = False
        search_hit = False
        if not selected_pdf_url:
            search_used = True
            for query in _doi_search_queries(reference=reference, doi=doi, final_url=final_url):
                for candidate in _search_pdf_candidates(query=query, max_results=6):
                    candidate_rows.append({"url": candidate, "source": "web_search", "query": query})
                    for linked_pdf in _pdf_links_from_landing_page(candidate, fetcher=fetcher):
                        candidate_rows.append(
                            {
                                "url": linked_pdf,
                                "source": "web_search_landing_page",
                                "query": query,
                                "parentUrl": candidate,
                            }
                        )
            selected_pdf_url, selected_via, blocked = _select_verified_pdf_candidate(candidate_rows)
            paywalled_or_blocked = paywalled_or_blocked or blocked
            search_hit = bool(selected_pdf_url and selected_via == "web_search")
            if selected_pdf_url and selected_via == "web_search_landing_page":
                search_hit = True

        api_fallback_used = False
        if not selected_pdf_url:
            api_fallback_used = True
            for candidate in _metadata_pdf_candidates(doi=doi):
                candidate_rows.append(candidate)
            selected_pdf_url, selected_via, blocked = _select_verified_pdf_candidate(candidate_rows)
            paywalled_or_blocked = paywalled_or_blocked or blocked

        canonical_source_uri = selected_pdf_url or _normalize_http_url(final_url) or doi_url
        if selected_pdf_url:
            resolution_outcome = "pdf_selected"
        elif resolution_outcome != "doi_unresolved" and paywalled_or_blocked:
            resolution_outcome = "paywalled_or_blocked"
        elif resolution_outcome != "doi_unresolved":
            resolution_outcome = "pdf_not_found"

        resolved = {
            "doi": doi,
            "source_uri": source_uri,
            "canonical_uri": canonical_source_uri,
            "doi_url": doi_url,
            "redirect_final_url": final_url,
        }
        candidates = [
            {"type": "doi", "value": doi, "source": "doi_source", "confidence": 1.0, "rank": 10},
        ]
        if selected_pdf_url:
            candidates.append(
                {
                    "type": "canonical_uri",
                    "value": selected_pdf_url,
                    "source": selected_via or "pdf_probe",
                    "confidence": 0.95,
                    "rank": 20,
                }
            )

        variants = {
            "inputUrl": source_uri,
            "doiUrl": doi_url,
            "redirectFinalUrl": final_url,
            "selectedPdfUrl": selected_pdf_url or None,
            "selectedPdfSource": selected_via or None,
            "redirectChain": redirect_chain,
            "candidatePdfUrls": [row.get("url") for row in candidate_rows if _normalize_http_url(row.get("url"))][:30],
        }
        resolution_payload = {
            "outcome": resolution_outcome,
            "doi": doi,
            "doiUrl": doi_url,
            "redirectFinalUrl": final_url,
            "redirectFinalContentType": final_content_type,
            "selectedPdfUrl": selected_pdf_url or None,
            "selectedPdfSource": selected_via or None,
            "searchUsed": search_used,
            "searchHit": search_hit,
            "apiFallbackUsed": api_fallback_used,
            "paywalledOrBlocked": paywalled_or_blocked,
            "candidateCount": len(candidate_rows),
            "resolvedAt": now,
            "redirectChain": redirect_chain,
            "candidates": candidate_rows[:40],
        }

        return {
            "pluginKey": self.key,
            "canonicalSourceUri": canonical_source_uri,
            "sourceVariants": variants,
            "identifiers": {
                "resolved": resolved,
                "candidates": candidates,
                "primary": {"type": "doi", "value": doi},
                "warnings": warnings,
            },
            "metadata": {
                "doi": doi,
                "doiResolution": resolution_payload,
                "resolvedAt": now,
            },
            "attachmentMetadata": {
                "sitePlugin": self.key,
                "doi": doi,
                "doiResolution": resolution_payload,
                "resolvedAt": now,
            },
            "warnings": warnings,
        }

    def _delegate_to_known_plugin(
        self,
        *,
        reference: dict[str, Any],
        source_uri: str,
        fetcher: Callable[[str], str],
    ) -> dict[str, Any] | None:
        normalized = _normalize_http_url(source_uri)
        if not normalized:
            return None
        for plugin in _PLUGINS:
            if plugin.key == self.key:
                continue
            if plugin.match(normalized):
                return plugin.enrich(reference=reference, source_uri=normalized, fetcher=fetcher)
        return None

    def _doi_from_source(self, source_uri: str) -> str:
        parsed = urllib.parse.urlparse(source_uri)
        host = (parsed.hostname or "").lower().strip()
        if host in {"doi.org", "dx.doi.org"}:
            token = (parsed.path or "").strip("/").strip()
            return _normalize_doi(token)
        match = self._DOI_PATTERN.search(source_uri.strip())
        return _normalize_doi(match.group(0)) if match else ""


class AcmSourcePlugin(SourceSitePlugin):
    key = "acm"

    _DOI_PATH_PATTERN = re.compile(
        r"^/doi/(?:(?:abs|pdf|epdf|fullHtml)/)?(10\.\d{4,9}/[^/?#]+)",
        flags=re.IGNORECASE,
    )

    def match(self, source_uri: str) -> bool:
        parsed = urllib.parse.urlparse(source_uri)
        host = (parsed.hostname or "").lower().strip()
        if host != "dl.acm.org":
            return False
        return bool(self._doi_from_uri(source_uri))

    def enrich(self, *, reference: dict[str, Any], source_uri: str, fetcher: Callable[[str], str]) -> dict[str, Any]:
        doi = self._doi_from_uri(source_uri)
        if not doi:
            return {
                "pluginKey": self.key,
                "canonicalSourceUri": source_uri,
                "sourceVariants": {"inputUrl": source_uri},
                "identifiers": {
                    "resolved": {},
                    "candidates": [],
                    "primary": None,
                    "warnings": [
                        {
                            "code": "acm_doi_unresolved",
                            "message": "Could not parse DOI from ACM Digital Library source URI.",
                        }
                    ],
                },
                "metadata": {},
                "attachmentMetadata": {},
                "warnings": [
                    {
                        "code": "acm_doi_unresolved",
                        "message": "Could not parse DOI from ACM Digital Library source URI.",
                    }
                ],
            }

        canonical_landing_url = f"https://dl.acm.org/doi/{doi}"
        canonical_pdf_url = f"https://dl.acm.org/doi/pdf/{doi}?download=true"

        abstract = ""
        warnings: list[dict[str, Any]] = []
        try:
            landing_body = fetcher(canonical_landing_url)
            abstract = _acm_abstract_from_html(landing_body)
        except Exception as error:  # pragma: no cover - network errors are mocked in tests
            warnings.append(
                {
                    "code": "acm_landing_fetch_failed",
                    "message": str(error),
                    "url": canonical_landing_url,
                }
            )

        resolved: dict[str, str] = {"doi": doi}
        candidates = [
            {
                "type": "doi",
                "value": doi,
                "source": "acm_url",
                "confidence": 1.0,
                "rank": 10,
            }
        ]
        pdf_resolution = resolve_accessible_pdf_url(
            reference=reference,
            source_uri=source_uri,
            primary_candidates=[{"url": canonical_pdf_url, "source": "acm_canonical"}],
            doi=doi,
            fetcher=fetcher,
            exclude_hosts_when_blocked={"dl.acm.org"},
        )
        selected_pdf_url = _normalize_http_url(pdf_resolution.get("selectedPdfUrl")) or canonical_pdf_url
        if selected_pdf_url != canonical_pdf_url:
            warnings.append(
                {
                    "code": "acm_pdf_fallback",
                    "message": (
                        "ACM publisher PDF was blocked or unavailable; "
                        f"using fallback from {pdf_resolution.get('selectedPdfSource') or 'pdf_fallback'}."
                    ),
                    "publisherPdfUrl": canonical_pdf_url,
                    "selectedPdfUrl": selected_pdf_url,
                }
            )
        elif pdf_resolution.get("paywalledOrBlocked"):
            warnings.append(
                {
                    "code": "acm_pdf_blocked",
                    "message": "ACM publisher PDF appears paywalled or blocked and no open fallback was found.",
                    "publisherPdfUrl": canonical_pdf_url,
                }
            )

        now = _utc_now()
        pdf_resolution_payload = {
            "outcome": "pdf_selected" if selected_pdf_url else "pdf_not_found",
            "publisherPdfUrl": canonical_pdf_url,
            "selectedPdfUrl": selected_pdf_url or None,
            "selectedPdfSource": pdf_resolution.get("selectedPdfSource") or None,
            "searchUsed": bool(pdf_resolution.get("searchUsed")),
            "searchHit": bool(pdf_resolution.get("searchHit")),
            "apiFallbackUsed": bool(pdf_resolution.get("apiFallbackUsed")),
            "paywalledOrBlocked": bool(pdf_resolution.get("paywalledOrBlocked")),
            "candidateCount": int(pdf_resolution.get("candidateCount") or 0),
            "resolvedAt": now,
        }
        return {
            "pluginKey": self.key,
            "canonicalSourceUri": selected_pdf_url,
            "sourceVariants": {
                "inputUrl": source_uri,
                "canonicalLandingUrl": canonical_landing_url,
                "canonicalPdfUrl": selected_pdf_url,
                "publisherCanonicalPdfUrl": canonical_pdf_url,
            },
            "identifiers": {
                "resolved": resolved,
                "candidates": candidates,
                "primary": {"type": "doi", "value": doi},
                "warnings": list(warnings),
            },
            "metadata": {
                "doi": doi,
                "canonicalLandingUrl": canonical_landing_url,
                "canonicalPdfUrl": selected_pdf_url,
                "publisherCanonicalPdfUrl": canonical_pdf_url,
                "abstract": abstract,
                "abstractSource": "acm_landing_structured" if abstract else "",
                "pdfResolution": pdf_resolution_payload,
                "resolvedAt": now,
            },
            "attachmentMetadata": {
                "sitePlugin": self.key,
                "doi": doi,
                "canonicalLandingUrl": canonical_landing_url,
                "canonicalPdfUrl": selected_pdf_url,
                "pdfResolution": pdf_resolution_payload,
                "resolvedAt": now,
            },
            "warnings": warnings,
        }

    def _doi_from_uri(self, source_uri: str) -> str:
        parsed = urllib.parse.urlparse(source_uri)
        match = self._DOI_PATH_PATTERN.match(parsed.path or "")
        if not match:
            fallback = re.search(r"(10\.\d{4,9}/[^/?#]+)", parsed.path or "", flags=re.IGNORECASE)
            if not fallback:
                return ""
            return _normalize_doi(fallback.group(1))
        return _normalize_doi(match.group(1))


class ArxivSourcePlugin(SourceSitePlugin):
    key = "arxiv"

    _ID_PATTERN = re.compile(r"^/(?:abs|pdf|html|src)/([^/?#]+)", flags=re.IGNORECASE)

    def match(self, source_uri: str) -> bool:
        parsed = urllib.parse.urlparse(source_uri)
        host = (parsed.hostname or "").lower()
        return host == "arxiv.org" and bool(self._ID_PATTERN.match(parsed.path or ""))

    def enrich(self, *, reference: dict[str, Any], source_uri: str, fetcher: Callable[[str], str]) -> dict[str, Any]:
        paper_id = self._paper_id_from_uri(source_uri)
        if not paper_id:
            return {
                "pluginKey": self.key,
                "canonicalSourceUri": source_uri,
                "sourceVariants": {"inputUrl": source_uri},
                "identifiers": {
                    "resolved": {},
                    "candidates": [],
                    "primary": None,
                    "warnings": [
                        {
                            "code": "arxiv_id_unresolved",
                            "message": "Could not parse arXiv identifier from source URI.",
                        }
                    ],
                },
                "metadata": {},
                "attachmentMetadata": {},
                "warnings": [
                    {
                        "code": "arxiv_id_unresolved",
                        "message": "Could not parse arXiv identifier from source URI.",
                    }
                ],
            }

        canonical_pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"
        canonical_abs_url = f"https://arxiv.org/abs/{paper_id}"
        canonical_html_url = f"https://arxiv.org/html/{paper_id}"

        abstract = ""
        doi = ""
        warnings: list[dict[str, Any]] = []
        try:
            abs_body = fetcher(canonical_abs_url)
            abstract = _arxiv_abstract_from_html(abs_body)
            doi = _arxiv_doi_from_html(abs_body)
        except Exception as error:  # pragma: no cover - network errors are mocked in tests
            warnings.append(
                {
                    "code": "arxiv_abs_fetch_failed",
                    "message": str(error),
                    "url": canonical_abs_url,
                }
            )

        resolved: dict[str, str] = {"arxiv_id": paper_id}
        if doi:
            resolved["doi"] = doi
        candidates = [
            {
                "type": "arxiv_id",
                "value": paper_id,
                "source": "arxiv_url",
                "confidence": 1.0,
                "rank": 10,
            }
        ]
        if doi:
            candidates.append(
                {
                    "type": "doi",
                    "value": doi,
                    "source": "arxiv_abs_metadata",
                    "confidence": 0.95,
                    "rank": 20,
                }
            )

        now = _utc_now()
        return {
            "pluginKey": self.key,
            "canonicalSourceUri": canonical_pdf_url,
            "sourceVariants": {
                "inputUrl": source_uri,
                "canonicalPdfUrl": canonical_pdf_url,
                "canonicalAbsUrl": canonical_abs_url,
                "canonicalHtmlUrl": canonical_html_url,
            },
            "identifiers": {
                "resolved": resolved,
                "candidates": candidates,
                "primary": {"type": "arxiv_id", "value": paper_id},
                "warnings": list(warnings),
            },
            "metadata": {
                "paperId": paper_id,
                "versionedId": paper_id,
                "doi": doi,
                "canonicalPdfUrl": canonical_pdf_url,
                "canonicalAbsUrl": canonical_abs_url,
                "canonicalHtmlUrl": canonical_html_url,
                "abstract": abstract,
                "abstractSource": "arxiv_abs_structured" if abstract else "",
                "resolvedAt": now,
            },
            "attachmentMetadata": {
                "sitePlugin": self.key,
                "canonicalPdfUrl": canonical_pdf_url,
                "canonicalAbsUrl": canonical_abs_url,
                "canonicalHtmlUrl": canonical_html_url,
                "resolvedAt": now,
            },
            "warnings": warnings,
        }

    def _paper_id_from_uri(self, source_uri: str) -> str:
        parsed = urllib.parse.urlparse(source_uri)
        match = self._ID_PATTERN.match(parsed.path or "")
        if not match:
            return ""
        token = re.sub(r"\.pdf$", "", match.group(1), flags=re.IGNORECASE)
        return token.strip()


class YouTubeSourcePlugin(SourceSitePlugin):
    key = "youtube"

    def match(self, source_uri: str) -> bool:
        parsed = urllib.parse.urlparse(source_uri)
        host = (parsed.hostname or "").lower()
        return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

    def enrich(self, *, reference: dict[str, Any], source_uri: str, fetcher: Callable[[str], str]) -> dict[str, Any]:
        video_id = _youtube_video_id_from_uri(source_uri)
        canonical_uri = f"https://www.youtube.com/watch?v={video_id}" if video_id else source_uri
        warnings = [
            {
                "code": "youtube_transcript_via_markitdown",
                "message": (
                    "YouTube references resolve video id here; transcript text is extracted via "
                    "Biblicus/MarkItDown during references process-fetch-url-text."
                ),
            }
        ]
        resolved = {"youtube_video_id": video_id} if video_id else {}
        candidates = (
            [
                {
                    "type": "youtube_video_id",
                    "value": video_id,
                    "source": "youtube_url",
                    "confidence": 1.0,
                    "rank": 10,
                }
            ]
            if video_id
            else []
        )
        return {
            "pluginKey": self.key,
            "canonicalSourceUri": canonical_uri,
            "sourceVariants": {
                "inputUrl": source_uri,
                "canonicalWatchUrl": canonical_uri,
            },
            "identifiers": {
                "resolved": resolved,
                "candidates": candidates,
                "primary": {"type": "youtube_video_id", "value": video_id} if video_id else None,
                "warnings": list(warnings),
            },
            "metadata": {
                "videoId": video_id,
                "canonicalWatchUrl": canonical_uri,
                "resolvedAt": _utc_now(),
            },
            "attachmentMetadata": {
                "sitePlugin": self.key,
                "canonicalWatchUrl": canonical_uri,
                "resolvedAt": _utc_now(),
            },
            "warnings": warnings,
        }


class AclAnthologySourcePlugin(SourceSitePlugin):
    key = "acl_anthology"

    def match(self, source_uri: str) -> bool:
        parsed = urllib.parse.urlparse(source_uri)
        host = (parsed.hostname or "").lower()
        if host != "aclanthology.org":
            return False
        path = (parsed.path or "").strip()
        if not path:
            return False
        return bool(re.match(r"^/[A-Za-z0-9._-]+/?$", path))

    def enrich(self, *, reference: dict[str, Any], source_uri: str, fetcher: Callable[[str], str]) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(source_uri)
        slug = (parsed.path or "").strip().strip("/")
        if not slug:
            return {
                "pluginKey": self.key,
                "canonicalSourceUri": source_uri,
                "sourceVariants": {"inputUrl": source_uri},
                "identifiers": {"resolved": {}, "candidates": [], "primary": None, "warnings": []},
                "metadata": {},
                "attachmentMetadata": {"sitePlugin": self.key},
                "warnings": [],
            }
        base_slug = re.sub(r"\.pdf$", "", slug, flags=re.IGNORECASE)
        canonical_landing_url = f"https://aclanthology.org/{base_slug}/"
        canonical_pdf_url = f"https://aclanthology.org/{base_slug}.pdf"
        now = _utc_now()
        resolved = {"acl_anthology_id": base_slug}
        candidates = [
            {
                "type": "acl_anthology_id",
                "value": base_slug,
                "source": "acl_anthology_url",
                "confidence": 1.0,
                "rank": 10,
            }
        ]
        return {
            "pluginKey": self.key,
            "canonicalSourceUri": canonical_pdf_url,
            "sourceVariants": {
                "inputUrl": source_uri,
                "canonicalLandingUrl": canonical_landing_url,
                "canonicalPdfUrl": canonical_pdf_url,
            },
            "identifiers": {
                "resolved": resolved,
                "candidates": candidates,
                "primary": {"type": "acl_anthology_id", "value": base_slug},
                "warnings": [],
            },
            "metadata": {
                "paperId": base_slug,
                "canonicalLandingUrl": canonical_landing_url,
                "canonicalPdfUrl": canonical_pdf_url,
                "resolvedAt": now,
            },
            "attachmentMetadata": {
                "sitePlugin": self.key,
                "canonicalLandingUrl": canonical_landing_url,
                "canonicalPdfUrl": canonical_pdf_url,
                "resolvedAt": now,
            },
            "warnings": [],
        }


_PLUGINS: tuple[SourceSitePlugin, ...] = (
    AcmSourcePlugin(),
    DoiSourcePlugin(),
    ArxivSourcePlugin(),
    AclAnthologySourcePlugin(),
    YouTubeSourcePlugin(),
)


def resolve_source_site_enrichment(
    *,
    reference: dict[str, Any],
    source_uri: str,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    normalized_source = _normalize_http_url(source_uri)
    if not normalized_source:
        return _finalize_enrichment(
            {
                "pluginKey": "default",
                "canonicalSourceUri": source_uri,
                "sourceVariants": {"inputUrl": source_uri},
                "identifiers": {"resolved": {}, "candidates": [], "primary": None, "warnings": []},
                "metadata": {},
                "attachmentMetadata": {},
                "warnings": [],
            },
            source_uri=source_uri,
        )

    active_fetcher = fetcher or _fetch_url_text
    for plugin in _PLUGINS:
        if plugin.match(normalized_source):
            enriched = plugin.enrich(reference=reference, source_uri=normalized_source, fetcher=active_fetcher)
            return _finalize_enrichment(enriched, source_uri=normalized_source)

    return _finalize_enrichment(
        {
            "pluginKey": "default",
            "canonicalSourceUri": normalized_source,
            "sourceVariants": {"inputUrl": normalized_source},
            "identifiers": {
                "resolved": {},
                "candidates": [],
                "primary": None,
                "warnings": [
                    {
                        "code": "no_site_plugin_match",
                        "message": "No site plugin matched source URI; proceeding with generic extraction.",
                    }
                ],
            },
            "metadata": {},
            "attachmentMetadata": {},
            "warnings": [],
        },
        source_uri=normalized_source,
    )


def _finalize_enrichment(enriched: dict[str, Any], *, source_uri: str) -> dict[str, Any]:
    plugin_key = str(enriched.get("pluginKey") or "default")
    canonical_uri = _normalize_http_url(enriched.get("canonicalSourceUri")) or source_uri
    identifiers = enriched.get("identifiers") if isinstance(enriched.get("identifiers"), dict) else {}
    resolved = identifiers.get("resolved") if isinstance(identifiers.get("resolved"), dict) else {}
    resolved = {str(key): str(value) for key, value in resolved.items() if str(value).strip()}
    resolved.setdefault("source_uri", source_uri)
    resolved.setdefault("canonical_uri", canonical_uri)

    candidates = identifiers.get("candidates") if isinstance(identifiers.get("candidates"), list) else []
    normalized_candidates: list[dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        id_type = str(row.get("type") or "").strip()
        value = str(row.get("value") or "").strip()
        if not id_type or not value:
            continue
        normalized_candidates.append(
            {
                "type": id_type,
                "value": value,
                "source": str(row.get("source") or plugin_key),
                "confidence": float(row.get("confidence") or 0.0),
                "rank": int(row.get("rank") or 999),
            }
        )

    normalized_candidates.extend(
        [
            {
                "type": "source_uri",
                "value": source_uri,
                "source": "reference_source_uri",
                "confidence": 1.0,
                "rank": 900,
            },
            {
                "type": "canonical_uri",
                "value": canonical_uri,
                "source": f"{plugin_key}_canonical_uri",
                "confidence": 1.0,
                "rank": 890,
            },
        ]
    )

    deduped_candidates: list[dict[str, Any]] = []
    seen = set()
    for candidate in sorted(normalized_candidates, key=lambda row: (int(row.get("rank") or 999), row.get("type"), row.get("value"))):
        key = (candidate["type"], candidate["value"], candidate["source"])
        if key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(candidate)

    primary = identifiers.get("primary") if isinstance(identifiers.get("primary"), dict) else None
    if not primary or not primary.get("type") or not primary.get("value"):
        primary = _select_primary_identifier(resolved=resolved, candidates=deduped_candidates)

    identifier_warnings = identifiers.get("warnings") if isinstance(identifiers.get("warnings"), list) else []
    warnings = list(enriched.get("warnings") or [])
    warnings.extend(identifier_warnings)

    metadata = enriched.get("metadata") if isinstance(enriched.get("metadata"), dict) else {}
    attachment_metadata = enriched.get("attachmentMetadata") if isinstance(enriched.get("attachmentMetadata"), dict) else {}

    return {
        "pluginKey": plugin_key,
        "canonicalSourceUri": canonical_uri,
        "sourceVariants": enriched.get("sourceVariants") if isinstance(enriched.get("sourceVariants"), dict) else {"inputUrl": source_uri},
        "identifiers": {
            "resolved": resolved,
            "candidates": deduped_candidates,
            "primary": primary,
            "warnings": warnings,
        },
        "metadata": metadata,
        "attachmentMetadata": attachment_metadata,
        "warnings": warnings,
    }


def _select_primary_identifier(*, resolved: dict[str, str], candidates: list[dict[str, Any]]) -> dict[str, str] | None:
    for key in DEFAULT_IDENTIFIER_PRECEDENCE:
        value = str(resolved.get(key) or "").strip()
        if value:
            return {"type": key, "value": value}
    for candidate in candidates:
        value = str(candidate.get("value") or "").strip()
        if value:
            return {"type": str(candidate.get("type") or "unknown"), "value": value}
    return None


def youtube_video_id_from_uri(source_uri: str) -> str:
    return _youtube_video_id_from_uri(source_uri)


def _youtube_video_id_from_uri(source_uri: str) -> str:
    parsed = urllib.parse.urlparse(source_uri)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        token = (parsed.path or "").strip("/")
        return token.split("/")[0] if token else ""
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        query = urllib.parse.parse_qs(parsed.query or "")
        candidate = ""
        if query.get("v"):
            candidate = str(query["v"][0])
        elif parsed.path.startswith("/shorts/"):
            candidate = parsed.path.removeprefix("/shorts/").split("/")[0]
        return candidate.strip()
    return ""


def _fetch_url_text(url: str, *, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Papyrus source-site plugin"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed web fetch URL
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def _normalize_doi(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    token = re.sub(r"^\s*https?://(?:dx\.)?doi\.org/", "", token, flags=re.IGNORECASE)
    token = token.strip().strip("/")
    match = re.search(r"10\.\d{4,9}/\S+", token, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).rstrip(").,;")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _resolve_redirect_chain(url: str, *, max_hops: int = 8) -> dict[str, Any]:
    chain: list[dict[str, Any]] = []
    current = url
    opener = urllib.request.build_opener(_NoRedirectHandler())
    for _ in range(max_hops):
        request = urllib.request.Request(current, headers={"User-Agent": "Papyrus DOI resolver"})
        try:
            response = opener.open(request, timeout=15)  # nosec B310 - fixed web fetch URL
            status = int(getattr(response, "status", response.getcode()))
            content_type = str(response.headers.get("Content-Type") or "")
            chain.append({"url": current, "status": status, "location": "", "contentType": content_type})
            return {"chain": chain, "finalUrl": current, "contentType": content_type}
        except urllib.error.HTTPError as error:
            status = int(getattr(error, "code", 0) or 0)
            location = str(error.headers.get("Location") or "").strip()
            content_type = str(error.headers.get("Content-Type") or "")
            if status in {301, 302, 303, 307, 308} and location:
                next_url = urllib.parse.urljoin(current, location)
                chain.append({"url": current, "status": status, "location": next_url, "contentType": content_type})
                current = next_url
                continue
            chain.append({"url": current, "status": status, "location": "", "contentType": content_type})
            return {"chain": chain, "finalUrl": current, "contentType": content_type}
        except Exception:
            break
    return {"chain": chain, "finalUrl": current, "contentType": ""}


def _pdf_candidates_from_final_url(url: str) -> list[str]:
    normalized = _normalize_http_url(url)
    if not normalized:
        return []
    parsed = urllib.parse.urlparse(normalized)
    host = (parsed.hostname or "").lower().strip()
    path = (parsed.path or "").strip()
    candidates: list[str] = []
    if normalized.lower().endswith(".pdf"):
        candidates.append(normalized)
    if host == "aclanthology.org":
        slug = path.strip("/").rstrip("/")
        if slug and not slug.lower().endswith(".pdf"):
            candidates.append(f"https://aclanthology.org/{slug}.pdf")
    if host == "dl.acm.org":
        doi_match = re.search(
            r"/doi/(?:(?:abs|pdf|epdf|fullHtml)/)?(10\.\d{4,9}/[^/?#]+)",
            path,
            flags=re.IGNORECASE,
        )
        if doi_match:
            doi = _normalize_doi(doi_match.group(1))
            if doi:
                candidates.append(f"https://dl.acm.org/doi/pdf/{doi}?download=true")
    return _dedupe_urls(candidates)


def resolve_accessible_pdf_url(
    *,
    reference: dict[str, Any],
    source_uri: str,
    primary_candidates: list[dict[str, Any]] | None = None,
    doi: str = "",
    fetcher: Callable[[str], str] | None = None,
    exclude_hosts_when_blocked: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    Probe publisher-primary PDF URLs, then search and bibliographic APIs for an
    accessible open copy when the primary host is paywalled or blocked.
    """
    active_fetcher = fetcher or _fetch_url_text
    candidate_rows: list[dict[str, Any]] = [dict(row) for row in (primary_candidates or []) if isinstance(row, dict)]
    normalized_doi = _normalize_doi(doi) or _doi_from_reference(reference)
    final_url = _normalize_http_url(source_uri) or source_uri
    publisher_hosts = {
        host.strip().lower()
        for host in (exclude_hosts_when_blocked or set())
        if str(host or "").strip()
    }

    def _append_candidate(url: Any, *, source: str, **extra: Any) -> None:
        normalized = _normalize_http_url(url)
        if not normalized:
            return
        if publisher_blocked and _url_hostname(normalized) in publisher_hosts:
            return
        candidate_rows.append({"url": normalized, "source": source, **extra})

    selected_pdf_url, selected_via, blocked = _select_verified_pdf_candidate(candidate_rows)
    publisher_blocked = _publisher_pdf_blocked(
        candidate_rows=candidate_rows,
        publisher_hosts=publisher_hosts,
        blocked=blocked,
        selected_pdf_url=selected_pdf_url,
    )

    search_used = False
    search_hit = False
    api_fallback_used = False

    if not selected_pdf_url and normalized_doi:
        api_fallback_used = True
        for row in _metadata_pdf_candidates(doi=normalized_doi):
            _append_candidate(row.get("url"), source=str(row.get("source") or "metadata"), kind=row.get("kind"))
        selected_pdf_url, selected_via, blocked = _select_verified_pdf_candidate(candidate_rows)

    if not selected_pdf_url and normalized_doi:
        search_used = True
        for query in _doi_search_queries(reference=reference, doi=normalized_doi, final_url=final_url):
            for candidate in _search_pdf_candidates(query=query, max_results=6):
                _append_candidate(candidate, source="web_search", query=query)
                for linked_pdf in _pdf_links_from_landing_page(candidate, fetcher=active_fetcher):
                    _append_candidate(
                        linked_pdf,
                        source="web_search_landing_page",
                        query=query,
                        parentUrl=candidate,
                    )
        selected_pdf_url, selected_via, blocked = _select_verified_pdf_candidate(candidate_rows)
        if selected_pdf_url and selected_via in {"web_search", "web_search_landing_page"}:
            search_hit = True

    return {
        "selectedPdfUrl": selected_pdf_url or "",
        "selectedPdfSource": selected_via or "",
        "paywalledOrBlocked": bool(blocked or publisher_blocked),
        "publisherBlocked": publisher_blocked,
        "searchUsed": search_used,
        "searchHit": search_hit,
        "apiFallbackUsed": api_fallback_used,
        "candidateCount": len(candidate_rows),
        "candidates": candidate_rows[:40],
    }


def resolve_accessible_pdf_url_for_reference(
    reference: dict[str, Any],
    *,
    source_uri: str | None = None,
    failed_uri: str | None = None,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    seed_uri = _normalize_http_url(source_uri) or _normalize_http_url(reference.get("sourceUri")) or ""
    failed = _normalize_http_url(failed_uri) or ""
    primary_candidates: list[dict[str, Any]] = []
    if failed:
        primary_candidates.append({"url": failed, "source": "failed_primary"})
    exclude_hosts: set[str] = set()
    host = _url_hostname(failed or seed_uri)
    if host in {"dl.acm.org", "doi.org", "dx.doi.org"}:
        exclude_hosts.add(host)
    if "dl.acm.org" in (failed or seed_uri):
        exclude_hosts.add("dl.acm.org")
    return resolve_accessible_pdf_url(
        reference=reference,
        source_uri=seed_uri,
        primary_candidates=primary_candidates,
        doi=_doi_from_reference(reference),
        fetcher=fetcher,
        exclude_hosts_when_blocked=exclude_hosts,
    )


def _url_hostname(url: str) -> str:
    return (urllib.parse.urlparse(str(url or "")).hostname or "").lower().strip()


def _publisher_pdf_blocked(
    *,
    candidate_rows: list[dict[str, Any]],
    publisher_hosts: set[str],
    blocked: bool,
    selected_pdf_url: str,
) -> bool:
    if selected_pdf_url or not blocked or not publisher_hosts:
        return False
    publisher_urls = [
        _url_hostname(str(row.get("url") or ""))
        for row in candidate_rows
        if _normalize_http_url(row.get("url"))
    ]
    if not publisher_urls:
        return False
    return all(host in publisher_hosts for host in publisher_urls)


def _doi_from_reference(reference: dict[str, Any]) -> str:
    metadata = reference.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if isinstance(metadata, dict):
        identifiers = metadata.get("identifiers")
        if isinstance(identifiers, dict):
            resolved = identifiers.get("resolved")
            if isinstance(resolved, dict):
                doi = _normalize_doi(resolved.get("doi"))
                if doi:
                    return doi
    for value in (
        reference.get("sourceUri"),
        reference.get("doi"),
    ):
        match = re.search(r"(10\.\d{4,9}/[^?\s#]+)", str(value or ""), flags=re.IGNORECASE)
        if match:
            return _normalize_doi(match.group(1))
    return ""


def _pdf_links_from_landing_page(url: str, *, fetcher: Callable[[str], str]) -> list[str]:
    normalized = _normalize_http_url(url)
    if not normalized or normalized.lower().endswith(".pdf"):
        return []
    try:
        body = fetcher(normalized)
    except Exception:
        return []
    links = re.findall(r'href=["\']([^"\']+)["\']', body, flags=re.IGNORECASE)
    candidates: list[str] = []
    for href in links:
        resolved = urllib.parse.urljoin(normalized, unescape(href))
        resolved_url = _normalize_http_url(resolved)
        if not resolved_url:
            continue
        if ".pdf" in resolved_url.lower():
            candidates.append(resolved_url)
    return _dedupe_urls(candidates)


def _select_verified_pdf_candidate(candidate_rows: list[dict[str, Any]]) -> tuple[str, str, bool]:
    blocked_seen = False
    for row in candidate_rows:
        candidate_url = _normalize_http_url(row.get("url"))
        if not candidate_url:
            continue
        probe = _probe_pdf_url(candidate_url)
        row["probe"] = probe
        if probe.get("blocked"):
            blocked_seen = True
        if probe.get("isPdf"):
            return candidate_url, str(row.get("source") or "pdf_probe"), blocked_seen
    return "", "", blocked_seen


def _probe_pdf_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Papyrus DOI PDF probe"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:  # nosec B310 - fixed web fetch URL
            content_type = str(response.headers.get("Content-Type") or "").lower()
            status = int(getattr(response, "status", response.getcode()))
            if "pdf" in content_type:
                return {"ok": True, "isPdf": True, "status": status, "contentType": content_type, "blocked": False}
    except Exception:
        pass

    request = urllib.request.Request(url, headers={"User-Agent": "Papyrus DOI PDF probe"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:  # nosec B310 - fixed web fetch URL
            content_type = str(response.headers.get("Content-Type") or "").lower()
            status = int(getattr(response, "status", response.getcode()))
            is_pdf = "pdf" in content_type or url.lower().endswith(".pdf")
            return {"ok": True, "isPdf": is_pdf, "status": status, "contentType": content_type, "blocked": False}
    except urllib.error.HTTPError as error:
        status = int(getattr(error, "code", 0) or 0)
        return {
            "ok": False,
            "isPdf": False,
            "status": status,
            "contentType": str(error.headers.get("Content-Type") or "").lower(),
            "blocked": status in {401, 403, 407, 451},
        }
    except Exception:
        return {"ok": False, "isPdf": False, "status": 0, "contentType": "", "blocked": False}


def _doi_search_queries(*, reference: dict[str, Any], doi: str, final_url: str) -> list[str]:
    title = str(reference.get("title") or "").strip()
    subtitle = _reference_subtitle(reference)
    authors = _reference_authors(reference)
    rich_parts = [part for part in [title, "PDF", subtitle, authors, doi] if part]
    rich_query = " ".join(rich_parts).strip()

    queries: list[str] = []
    if rich_query:
        queries.append(rich_query)
    queries.extend([f'"{doi}" filetype:pdf', f'"{doi}" pdf'])
    parsed = urllib.parse.urlparse(final_url or "")
    host = (parsed.hostname or "").strip().lower()
    if host:
        queries.append(f'"{doi}" site:{host} pdf')
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(query.strip())
        if len(deduped) >= 3:
            break
    return deduped


def _search_pdf_candidates(*, query: str, max_results: int = 6) -> list[str]:
    if not query.strip():
        return []
    encoded = urllib.parse.quote_plus(query)
    search_url = f"https://duckduckgo.com/html/?q={encoded}"
    request = urllib.request.Request(search_url, headers={"User-Agent": "Papyrus DOI resolver"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310 - fixed web fetch URL
            body = response.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    links = re.findall(r'href=["\']([^"\']+)["\']', body, flags=re.IGNORECASE)
    candidates: list[str] = []
    for href in links:
        link = unescape(href)
        if "uddg=" in link:
            parsed = urllib.parse.urlparse(link)
            params = urllib.parse.parse_qs(parsed.query or "")
            if params.get("uddg"):
                link = params["uddg"][0]
        normalized = _normalize_http_url(link)
        if not normalized:
            continue
        if "duckduckgo.com" in normalized:
            continue
        candidates.append(normalized)
        if len(candidates) >= max_results:
            break
    return _dedupe_urls(candidates)


def _metadata_pdf_candidates(*, doi: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_crossref_pdf_candidates(doi=doi))
    rows.extend(_openalex_pdf_candidates(doi=doi))
    return rows


def _crossref_pdf_candidates(*, doi: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(doi, safe="")
    url = f"https://api.crossref.org/works/{encoded}"
    payload = _json_get(url)
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    rows: list[dict[str, Any]] = []
    links = message.get("link") if isinstance(message, dict) else None
    if isinstance(links, list):
        for entry in links:
            if not isinstance(entry, dict):
                continue
            candidate_url = _normalize_http_url(entry.get("URL"))
            if not candidate_url:
                continue
            rows.append({"url": candidate_url, "source": "crossref", "kind": "link"})
    resource = message.get("resource") if isinstance(message, dict) else None
    if isinstance(resource, dict):
        primary = _normalize_http_url(resource.get("primary", {}).get("URL") if isinstance(resource.get("primary"), dict) else None)
        if primary:
            rows.append({"url": primary, "source": "crossref", "kind": "resource_primary"})
    return _dedupe_candidate_rows(rows)


def _openalex_pdf_candidates(*, doi: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    url = f"https://api.openalex.org/works/{encoded}"
    payload = _json_get(url)
    rows: list[dict[str, Any]] = []
    open_access = payload.get("open_access") if isinstance(payload.get("open_access"), dict) else {}
    for key in ("oa_url",):
        candidate_url = _normalize_http_url(open_access.get(key))
        if candidate_url:
            rows.append({"url": candidate_url, "source": "openalex", "kind": key})
    best = payload.get("best_oa_location") if isinstance(payload.get("best_oa_location"), dict) else {}
    for key in ("pdf_url", "landing_page_url"):
        candidate_url = _normalize_http_url(best.get(key))
        if candidate_url:
            rows.append({"url": candidate_url, "source": "openalex", "kind": key})
    return _dedupe_candidate_rows(rows)


def _json_get(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Papyrus DOI resolver"})
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310 - fixed web fetch URL
        payload = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else {}


def _dedupe_urls(rows: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for row in rows:
        url = _normalize_http_url(row)
        if not url or url in seen:
            continue
        seen.add(url)
        output.append(url)
    return output


def _dedupe_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        candidate_url = _normalize_http_url(row.get("url"))
        if not candidate_url or candidate_url in seen:
            continue
        seen.add(candidate_url)
        output.append({**row, "url": candidate_url})
    return output


def _reference_subtitle(reference: dict[str, Any]) -> str:
    metadata = reference.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return str(
        metadata.get("subtitle")
        or metadata.get("original_subtitle")
        or metadata.get("originalSubtitle")
        or ""
    ).strip()


def _reference_authors(reference: dict[str, Any]) -> str:
    authors = reference.get("authors")
    if isinstance(authors, list):
        parts = [str(value).strip() for value in authors if str(value or "").strip()]
        if parts:
            return ", ".join(parts[:6])
    if isinstance(authors, str):
        return authors.strip()
    return ""


def _acm_abstract_from_html(html: str) -> str:
    for payload in _extract_json_ld_payloads(html):
        abstract = _json_ld_lookup(payload, keys=("description", "abstract"))
        if abstract:
            return _clean_text(abstract)

    meta_match = re.search(
        r'<meta[^>]+name=["\'](?:description|citation_abstract)["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if meta_match:
        return _clean_text(meta_match.group(1))

    paragraph_matches = re.findall(
        r'<div[^>]+class=["\'][^"\']*(?:article__abstract|abstractSection)[^"\']*["\'][^>]*>(.*?)</div>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    paragraphs: list[str] = []
    for block in paragraph_matches:
        for paragraph in re.findall(r"<p[^>]*>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL):
            text = _clean_text(re.sub(r"<[^>]+>", " ", paragraph))
            if text and text.lower() != "no abstract available.":
                paragraphs.append(text)
    if paragraphs:
        return "\n\n".join(paragraphs)
    return ""


def _arxiv_abstract_from_html(html: str) -> str:
    for payload in _extract_json_ld_payloads(html):
        abstract = _json_ld_lookup(payload, keys=("description", "abstract"))
        if abstract:
            return _clean_text(abstract)

    meta_match = re.search(
        r'<meta[^>]+name=["\'](?:description|citation_abstract)["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if meta_match:
        return _clean_text(meta_match.group(1))
    return ""


def _arxiv_doi_from_html(html: str) -> str:
    for payload in _extract_json_ld_payloads(html):
        doi_value = _json_ld_find_doi(payload)
        if doi_value:
            return doi_value

    meta_match = re.search(
        r'<meta[^>]+name=["\']citation_doi["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if meta_match:
        return _clean_text(meta_match.group(1))
    return ""


def _extract_json_ld_payloads(html: str) -> list[Any]:
    payloads: list[Any] = []
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        block = (match.group(1) or "").strip()
        if not block:
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        payloads.append(payload)
    return payloads


def _json_ld_lookup(payload: Any, *, keys: tuple[str, ...]) -> str:
    queue = [payload]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for key in keys:
                value = current.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in current.values():
                queue.append(value)
        elif isinstance(current, list):
            queue.extend(current)
    return ""


def _json_ld_find_doi(payload: Any) -> str:
    queue = [payload]
    doi_pattern = re.compile(r"10\.\d{4,9}/\S+", flags=re.IGNORECASE)
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            identifier = current.get("identifier")
            if isinstance(identifier, dict):
                prop = str(identifier.get("propertyID") or "").strip().lower()
                value = str(identifier.get("value") or "").strip()
                if prop == "doi" and value:
                    return value
            if isinstance(identifier, list):
                queue.extend(identifier)
            if isinstance(identifier, str):
                match = doi_pattern.search(identifier)
                if match:
                    return match.group(0)
            same_as = current.get("sameAs")
            if isinstance(same_as, str):
                match = doi_pattern.search(same_as)
                if match:
                    return match.group(0)
            elif isinstance(same_as, list):
                queue.extend(same_as)
            for value in current.values():
                queue.append(value)
        elif isinstance(current, list):
            queue.extend(current)
        elif isinstance(current, str):
            match = doi_pattern.search(current)
            if match:
                return match.group(0)
    return ""


def _normalize_http_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
