"""Derive and validate the ``bodyIr`` envelope from an article's Markus source (PPY-e169c5).

``derive_body`` is the single function every write path calls so ``bodyIr`` is
always consistent with ``bodyMarkus``. It runs Markus in-process (no
subprocess) and never enables raw HTML passthrough.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .citations import CitationCollector, CitationError, CitationRendering
from .content_markup import ContentMarkupError, prepare_page, read_citation_entries
from .images import ImagePipeline, ImagePipelineError, assert_safe_asset_src
from .security import MARKUS_REQUIRED_VERSION

BODY_IR_SCHEMA_VERSION = 1
MAX_BODY_IR_BYTES = 300_000

_SENTINEL_TOKEN_RE = re.compile(r"PAPYRUSMARKUP\d{5}END")


@dataclass(frozen=True)
class BodyError:
    code: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "line": self.line}


@dataclass(frozen=True)
class BodyDerivation:
    ok: bool
    body_ir: dict | None
    errors: tuple[BodyError, ...]


def _failure(*errors: BodyError) -> BodyDerivation:
    return BodyDerivation(ok=False, body_ir=None, errors=tuple(errors))


def compose_source(front_matter_yaml: str | None, body_markus: str) -> str:
    """Join front matter and body; the body is kept verbatim."""
    yaml_text = (front_matter_yaml or "").strip("\n")
    if not yaml_text.strip():
        return body_markus
    return "---\n" + yaml_text + "\n---\n" + body_markus


def _front_matter_error(front_matter_yaml: str | None) -> BodyError | None:
    if not front_matter_yaml or not front_matter_yaml.strip():
        return None
    import yaml

    try:
        loaded = yaml.safe_load(front_matter_yaml)
    except yaml.YAMLError as exc:
        return BodyError("front-matter", f"Front matter is not valid YAML: {exc}")
    if loaded is not None and not isinstance(loaded, dict):
        return BodyError("front-matter", "Front matter must be a YAML mapping")
    return None


def _markus_document(markdown: str) -> dict[str, Any]:
    import markusmd
    from markusmd.render import make_markdown

    if markusmd.__version__ != MARKUS_REQUIRED_VERSION:
        raise RuntimeError(
            f"Markus {MARKUS_REQUIRED_VERSION} required to derive bodyIr; "
            f"got {markusmd.__version__!r}."
        )
    document = markusmd.parse(markdown)
    return document.to_dict(markdown=make_markdown(allow_html=False))


def derive_body(front_matter_yaml: str | None, body_markus: str) -> BodyDerivation:
    source = compose_source(front_matter_yaml, body_markus)

    front_matter_problem = _front_matter_error(front_matter_yaml)
    if front_matter_problem is not None:
        return _failure(front_matter_problem)

    try:
        entries = read_citation_entries(source)
    except ContentMarkupError as exc:
        return _failure(BodyError("front-matter", str(exc)))

    citations = CitationRendering()
    try:
        prepared = prepare_page(source, images=ImagePipeline(), citations=citations)
    except ContentMarkupError as exc:
        return _failure(BodyError("image-attrs", str(exc)))

    image_errors = []
    for request in prepared.images.values():
        try:
            assert_safe_asset_src(request.src)
        except ImagePipelineError as exc:
            image_errors.append(BodyError("image-src", str(exc)))
    if image_errors:
        return _failure(*image_errors)

    from markusmd.errors import MarkusSyntaxError, MarkusValidationError

    try:
        document = _markus_document(prepared.markdown)
    except MarkusSyntaxError as exc:
        return _failure(BodyError("markus-syntax", str(exc), getattr(exc, "line", None)))
    except MarkusValidationError as exc:
        return _failure(BodyError("markus-validation", str(exc), getattr(exc, "line", None)))

    collector = CitationCollector(entries, citations)
    first_cited_keys: list[str] = []
    try:
        for token in _SENTINEL_TOKEN_RE.findall(prepared.markdown):
            for key in prepared.citation_keys.get(token, ()):
                collector.number_for(key)
                if key not in first_cited_keys:
                    first_cited_keys.append(key)
        for citation_format in prepared.citation_lists.values():
            citations.formatter(citation_format or citations.default_format)
        format_apa = citations.formatter("apa")
        bibliography = [format_apa(entries[key]) for key in first_cited_keys]
    except CitationError as exc:
        return _failure(BodyError("citation-key", str(exc)))

    envelope = {
        "schemaVersion": BODY_IR_SCHEMA_VERSION,
        "markus": {"version": MARKUS_REQUIRED_VERSION, "irSchemaVersion": document["schema_version"]},
        "document": document,
        "papyrus": {
            "images": {
                token: {
                    "src": request.src,
                    "alt": request.alt,
                    "layout": request.layout,
                    "caption": request.caption,
                    "credit": request.credit,
                    "sizes": request.sizes,
                    "loading": request.loading,
                }
                for token, request in prepared.images.items()
            },
            "citations": {token: list(keys) for token, keys in prepared.citation_keys.items()},
            "citationLists": dict(prepared.citation_lists),
            "entries": entries,
            "bibliography": bibliography,
        },
    }
    size = envelope_byte_count(envelope)
    if size > MAX_BODY_IR_BYTES:
        return _failure(
            BodyError(
                "too-large",
                f"Article is too long to store; split it ({size} bytes of IR, limit {MAX_BODY_IR_BYTES}).",
            )
        )
    return BodyDerivation(ok=True, body_ir=envelope, errors=())


def envelope_byte_count(envelope: dict) -> int:
    return len(json.dumps(envelope, separators=(",", ":")).encode("utf-8"))


def _inline_text(nodes: list[dict]) -> str:
    parts: list[str] = []
    for node in nodes:
        kind = node.get("type")
        if kind == "text":
            parts.append(node.get("text", ""))
        elif kind == "code_span":
            parts.append(node.get("code", ""))
        elif kind in ("soft_break", "hard_break"):
            parts.append(" ")
        elif "children" in node:
            parts.append(_inline_text(node["children"]))
    return "".join(parts)


def plain_paragraphs(envelope: dict) -> list[str]:
    return [
        _inline_text(block.get("inline", []))
        for block in envelope["document"]["children"]
        if block.get("type") == "paragraph"
    ]
