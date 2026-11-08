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

from .body_features import CITATIONS_OFF, IMAGES_OFF, BodyFeatures, current_body_features
from .citations import CitationCollector, CitationError, CitationRendering
from .equations import equation_problems
from .content_markup import ContentMarkupError, VideoMarkupError, prepare_page, read_citation_entries
from .images import ImagePipeline, ImagePipelineError, assert_safe_asset_src
from .security import assert_supported_markus_version
from .video import VideoRendering

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
    #: Problems that do not stop a save: the page still builds and shows the author's text. An equation that
    #: will not convert is shown as its TeX source, and is reported here.
    warnings: tuple[BodyError, ...] = ()


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

    from .wiki_directives import papyrus_registry

    assert_supported_markus_version(markusmd.__version__, purpose="deriving bodyIr")
    document = markusmd.parse(markdown, registry=papyrus_registry())
    return document.to_dict(markdown=make_markdown(allow_html=False))


def derive_body(front_matter_yaml: str | None, body_markus: str, features: BodyFeatures | None = None) -> BodyDerivation:
    """Validate a body and derive its ``bodyIr``.

    ``features`` are the site's (see ``body_features``); the installed ones when omitted. A feature the site turned off
    is not lowered, so Markus meets the markup exactly as it does when the page is projected and rejects it the same way.
    """
    features = features if features is not None else current_body_features()
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
        # Always read the image markup, to say what a body asks of the site; only an enabled feature is lowered below.
        # A ::video is read only on a site whose embeds are on, and only an allowed provider's address; anything else reaches the site's hooks as before.
        videos = VideoRendering(enabled=True) if features.video_embeds and "::video{" in source else None
        requested = prepare_page(source, images=ImagePipeline(), citations=None, videos=videos)
        prepared = prepare_page(
            source,
            images=ImagePipeline() if features.images else None,
            citations=citations if features.citations else None,
            videos=videos,
        )
    except VideoMarkupError as exc:
        return _failure(BodyError("video-attrs", str(exc)))
    except ContentMarkupError as exc:
        return _failure(BodyError("image-attrs", str(exc)))

    if (requested.images or features.plain_images_upgraded) and features.images and features.images_unavailable:
        return _failure(BodyError("images-unavailable", features.images_unavailable))

    image_errors = []
    for request in prepared.images.values():
        try:
            assert_safe_asset_src(request.src)
            if request.src_dark is not None and request.src_dark.strip().lower() != "none":
                assert_safe_asset_src(request.src_dark)
        except ImagePipelineError as exc:
            image_errors.append(BodyError("image-src", str(exc)))
    if image_errors:
        return _failure(*image_errors)

    import markusmd
    from markusmd.errors import MarkusSyntaxError, MarkusValidationError

    try:
        document = _markus_document(prepared.markdown)
    except MarkusSyntaxError as exc:
        return _failure(BodyError("markus-syntax", str(exc), getattr(exc, "line", None)))
    except MarkusValidationError as exc:
        message = str(exc)
        if requested.images and not features.images:
            message = f"{message}. {IMAGES_OFF}"
        elif not features.citations and "citations" in message:
            message = f"{message}. {CITATIONS_OFF}"
        return _failure(BodyError("markus-validation", message, getattr(exc, "line", None)))

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
        "markus": {"version": markusmd.__version__, "irSchemaVersion": document["schema_version"]},
        "document": document,
        "papyrus": {
            "images": {
                token: {
                    "src": request.src,
                    "srcDark": request.src_dark,
                    "alt": request.alt,
                    "layout": request.layout,
                    "caption": request.caption,
                    "credit": request.credit,
                    "sizes": request.sizes,
                    "loading": request.loading,
                }
                for token, request in prepared.images.items()
            },
            **(
                {
                    "videos": {
                        token: {
                            "src": request.src,
                            "videoId": request.video_id,
                            "title": request.title,
                            "caption": request.caption,
                            "credit": request.credit,
                            "start": request.start,
                            "layout": request.layout,
                        }
                        for token, request in prepared.videos.items()
                    }
                }
                if prepared.videos
                else {}
            ),
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
    warnings = tuple(
        BodyError(
            "equation-tex",
            f"{'Display' if equation.display else 'Inline'} equation will be shown as TeX source: {reason}. {equation.tex.strip()[:80]!r}",
            equation.line,
        )
        for equation, reason in equation_problems(document)
    )
    return BodyDerivation(ok=True, body_ir=envelope, errors=(), warnings=warnings)


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
