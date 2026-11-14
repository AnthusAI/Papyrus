"""GROBID structured extraction for research papers: title, authors, abstract, sections and references.

GROBID is a service (Docker image ``grobid/grobid``), not a library. This module only talks to one that already exists:

* ``BIBLICUS_GROBID_URL`` names a reachable service (a developer's container, a shared service in the same network), or
* on a developer machine where Biblicus is installed, ``start=True`` lets Biblicus start its own local container
  (``biblicus.grobid_runtime.ensure_grobid_running``).

The cloud procedure runner (``infra/procedures``) has neither, so there the stage ends as a typed skip
(``grobid_not_configured``) and the rest of curation proceeds. A skip is data, not an error.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any
from xml.etree import ElementTree

GROBID_URL_ENVIRONMENT_VARIABLE = "BIBLICUS_GROBID_URL"
GROBID_TIMEOUT_SECONDS = 180
NAMESPACE = {"tei": "http://www.tei-c.org/ns/1.0"}

# Reasons a paper did not get GROBID fields. The first group are final; the second say a later run may succeed.
SKIP_REASONS_FINAL = frozenset({"not_a_paper", "pdf_unavailable", "capture_failed", "grobid_parse_failed", "grobid_empty"})
SKIP_REASONS_RETRYABLE = frozenset({"grobid_not_configured", "grobid_unreachable", "grobid_busy", "grobid_request_failed", "grobid_timeout"})


class GrobidUnavailable(Exception):
    """GROBID could not be used. ``reason`` is one of the typed reasons above."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve_grobid_url(environment: dict[str, str] | None = None, *, explicit: str | None = None, start: bool = False) -> str | None:
    """The service address to use, or None when there is none (the stage then skips as ``grobid_not_configured``)."""
    environment = os.environ if environment is None else environment
    configured = (explicit or environment.get(GROBID_URL_ENVIRONMENT_VARIABLE) or "").strip()
    if configured and not start:
        return configured
    if not start:
        return None
    try:  # a developer machine: Biblicus starts and health-checks its own container
        from biblicus.grobid_runtime import ensure_grobid_running
    except ImportError:
        return configured or None
    try:
        return ensure_grobid_running(configured or None)
    except Exception:  # noqa: BLE001 - Docker missing or the container would not start: that is "not available"
        raise GrobidUnavailable("grobid_unreachable") from None


Post = Callable[..., Any]


def process_fulltext(pdf_bytes: bytes, service_url: str, *, post: Post | None = None, timeout: float = GROBID_TIMEOUT_SECONDS) -> str:
    """The TEI XML GROBID returns for one PDF. Raises ``GrobidUnavailable`` with a typed reason."""
    import requests

    sender = post or requests.post
    endpoint = f"{service_url.rstrip('/')}/api/processFulltextDocument"
    try:
        response = sender(endpoint, files={"input": ("source.pdf", pdf_bytes, "application/pdf")},
                          data={"consolidateHeader": "0", "consolidateCitations": "0", "includeRawCitations": "1"}, timeout=timeout)
    except requests.Timeout:
        raise GrobidUnavailable("grobid_timeout") from None
    except requests.RequestException:
        raise GrobidUnavailable("grobid_unreachable") from None
    status = getattr(response, "status_code", 0)
    if status == 503:
        raise GrobidUnavailable("grobid_busy")
    if status == 204:
        raise GrobidUnavailable("grobid_empty")
    if status != 200:
        raise GrobidUnavailable("grobid_request_failed")
    return str(response.text)


# --- TEI -> fields ---------------------------------------------------------------------------------------------------


def _text(node: ElementTree.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip() if node is not None else ""


def _person(node: ElementTree.Element) -> dict[str, str]:
    name = node.find("tei:persName", NAMESPACE)
    if name is None:
        return {"name": _text(node)} if _text(node) else {}
    forenames = " ".join(_text(part) for part in name.findall("tei:forename", NAMESPACE) if _text(part))
    surname = _text(name.find("tei:surname", NAMESPACE))
    person = {"name": " ".join(part for part in (forenames, surname) if part), "forenames": forenames, "surname": surname}
    affiliation = _text(node.find("tei:affiliation/tei:orgName", NAMESPACE))
    email = _text(node.find("tei:email", NAMESPACE))
    if affiliation:
        person["affiliation"] = affiliation
    if email:
        person["email"] = email
    return {key: value for key, value in person.items() if value}


def _reference(node: ElementTree.Element) -> dict[str, Any]:
    title = _text(node.find("tei:analytic/tei:title", NAMESPACE)) or _text(node.find("tei:monogr/tei:title", NAMESPACE))
    venue = _text(node.find("tei:monogr/tei:title", NAMESPACE)) if _text(node.find("tei:analytic/tei:title", NAMESPACE)) else ""
    date = node.find("tei:monogr/tei:imprint/tei:date", NAMESPACE)
    authors = [person for person in (_person(a) for a in node.findall("tei:analytic/tei:author", NAMESPACE)
                                     or node.findall("tei:monogr/tei:author", NAMESPACE)) if person]
    doi = next((_text(i) for i in node.findall(".//tei:idno", NAMESPACE) if (i.get("type") or "").lower() == "doi"), "")
    arxiv = next((_text(i) for i in node.findall(".//tei:idno", NAMESPACE) if (i.get("type") or "").lower() == "arxiv"), "")
    raw = _text(next((n for n in node.findall("tei:note", NAMESPACE) if n.get("type") == "raw_reference"), None))
    entry = {"title": title, "venue": venue, "authors": authors, "year": (date.get("when") or _text(date))[:4] if date is not None else "",
             "doi": doi, "arxivId": arxiv, "raw": raw}
    return {key: value for key, value in entry.items() if value}


def parse_tei(tei: str) -> dict[str, Any]:
    """Structured fields from GROBID's TEI. Raises ``GrobidUnavailable('grobid_parse_failed')`` for text that is not TEI."""
    try:
        root = ElementTree.fromstring(tei)
    except ElementTree.ParseError:
        raise GrobidUnavailable("grobid_parse_failed") from None
    header = root.find("tei:teiHeader", NAMESPACE)
    if header is None:
        raise GrobidUnavailable("grobid_parse_failed")
    title = _text(header.find(".//tei:titleStmt/tei:title[@type='main']", NAMESPACE)) or _text(header.find(".//tei:titleStmt/tei:title", NAMESPACE))
    authors = [person for person in (_person(a) for a in header.findall(".//tei:sourceDesc/tei:biblStruct/tei:analytic/tei:author", NAMESPACE)) if person]
    abstract = " ".join(_text(p) for p in header.findall(".//tei:profileDesc/tei:abstract//tei:p", NAMESPACE) if _text(p))
    doi = next((_text(i) for i in header.findall(".//tei:sourceDesc//tei:idno", NAMESPACE) if (i.get("type") or "").lower() == "doi"), "")
    keywords = [_text(t) for t in header.findall(".//tei:profileDesc/tei:textClass/tei:keywords//tei:term", NAMESPACE) if _text(t)]
    sections = []
    for division in root.findall("tei:text/tei:body/tei:div", NAMESPACE):
        head = division.find("tei:head", NAMESPACE)
        paragraphs = [_text(p) for p in division.findall("tei:p", NAMESPACE) if _text(p)]
        if head is None and not paragraphs:
            continue
        sections.append({"heading": _text(head), **({"number": head.get("n")} if head is not None and head.get("n") else {}),
                         "text": "\n\n".join(paragraphs)})
    references = [entry for entry in (_reference(b) for b in root.findall(".//tei:text/tei:back//tei:listBibl/tei:biblStruct", NAMESPACE)) if entry]
    fields = {"title": title, "authors": authors, "abstract": abstract, "doi": doi, "keywords": keywords, "sections": sections,
              "references": references}
    return {key: value for key, value in fields.items() if value or key in {"authors", "sections", "references"}}


def summarize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """The small facts a review list needs without opening the fields."""
    return {"title": fields.get("title") or "", "authorCount": len(fields.get("authors") or []), "hasAbstract": bool(fields.get("abstract")),
            "sectionCount": len(fields.get("sections") or []), "referenceCount": len(fields.get("references") or [])}
