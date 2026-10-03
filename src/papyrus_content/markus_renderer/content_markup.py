"""Papyrus-layer content markup: ``::image{}``, ``[@key]``, ``::citations{}``.

Why a Papyrus layer at all
--------------------------
Markus owns the Markdown vocabulary and validates it strictly: directive
attribute schemas are pydantic models with ``extra="forbid"`` and an unknown
directive name is a hard error. ``:::figure`` therefore cannot carry a layout
or a responsive-sizes hint, and Papyrus cannot register a new directive
because ``convert_fragment`` shells out to the pinned ``markus`` CLI (which is
also the security boundary -- the build never passes ``--allow-html``).

So Papyrus resolves its own small vocabulary *before* Markus runs, lowering
each construct to an opaque alphanumeric sentinel, and substitutes real HTML
back into the converted fragment afterwards. Consequences worth knowing:

* Markus never sees Papyrus markup, so Markus stays the single authority on
  the Markdown it does own.
* Author text can still never introduce HTML: the sentinel carries no content,
  and every substituted attribute is escaped here.
* The whole layer is opt-in. ``build_markus_site`` leaves fragments completely
  untouched unless the caller passes ``images=`` or ``citations=``.

Authoring syntax is specified in ``docs/markus-content-markup.md``; that doc
is the contract reader-site build scripts and content codemods are written
against.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .citations import CitationCollector, CitationRendering
from .images import ImageBuilder, ImagePipeline, ImageRequest

#: Deliberately alphanumeric: Markdown cannot style it, Markus's typography
#: pass cannot rewrite it, and HTML escaping cannot alter it.
_TOKEN = "PAPYRUSMARKUP{0:05d}END"
_TOKEN_RE = re.compile(r"PAPYRUSMARKUP(\d{5})END")

# The attribute block may wrap across lines -- a codemod lifting a multi-line
# JSX element produces that naturally, and a long alt text is more readable
# wrapped. The closing brace still has to end its line, so a brace inside an
# attribute value is not supported (quote-aware block scanning would be, but
# nothing in the corpus needs it).
_IMAGE_DIRECTIVE_RE = re.compile(r"^[ \t]*::image\{(?P<attrs>[^}]*)\}[ \t]*$", re.M)
_CITATIONS_DIRECTIVE_RE = re.compile(
    r"^[ \t]*::citations(?:\{(?P<attrs>[^}]*)\})?[ \t]*$", re.M
)
_CITE_REF_RE = re.compile(r"\[@(?P<body>[^\]\n]+)\]")
_ATTR_RE = re.compile(
    r"""(?P<key>[A-Za-z_][\w-]*)\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\s}]+))"""
)
_FENCE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})", re.M)
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)

_IMG_TAG_RE = re.compile(r"<img\b(?P<attrs>[^>]*?)/?>", re.I)
_LONE_IMG_PARAGRAPH_RE = re.compile(
    r"<p>\s*(?P<img><img\b[^>]*?/?>)\s*</p>", re.I
)


class ContentMarkupError(RuntimeError):
    """Raised for malformed Papyrus content markup."""


def parse_attrs(raw: str) -> dict[str, str]:
    """Parse ``key="value"`` / ``key='value'`` / ``key=value`` pairs."""
    out: dict[str, str] = {}
    for match in _ATTR_RE.finditer(raw or ""):
        value = match.group("dq")
        if value is None:
            value = match.group("sq")
        if value is None:
            value = match.group("bare") or ""
        out[match.group("key")] = value
    return out


# -- front matter ----------------------------------------------------------


def split_front_matter(text: str) -> tuple[str, str]:
    """Return ``(front_matter_yaml, body)``; empty YAML when there is none."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    newline = text.find("\n", end + 1)
    body = text[newline + 1 :] if newline != -1 else ""
    return text[3:end], body


def read_citation_entries(text: str) -> dict[str, dict[str, Any]]:
    """Read the page's front-matter ``citations:`` block as CSL-JSON."""
    front_matter, _ = split_front_matter(text)
    if "citations:" not in front_matter:
        return {}
    import yaml

    try:
        loaded = yaml.safe_load(front_matter) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - author error path
        raise ContentMarkupError(f"Front matter is not valid YAML: {exc}") from exc
    entries = loaded.get("citations") if isinstance(loaded, Mapping) else None
    if entries is None:
        return {}
    if not isinstance(entries, Mapping):
        raise ContentMarkupError(
            "Front-matter `citations:` must be a mapping of key -> CSL-JSON object"
        )
    out: dict[str, dict[str, Any]] = {}
    for key, value in entries.items():
        if not isinstance(value, Mapping):
            raise ContentMarkupError(
                f"Citation {key!r} must be a mapping of CSL-JSON fields, got {type(value).__name__}"
            )
        out[str(key)] = dict(value)
    return out


# -- lowering --------------------------------------------------------------


@dataclass
class PreparedPage:
    """A page's Markdown with Papyrus markup lowered to sentinels."""

    markdown: str
    images: dict[str, ImageRequest] = field(default_factory=dict)
    citation_keys: dict[str, list[str]] = field(default_factory=dict)
    citation_lists: dict[str, str | None] = field(default_factory=dict)
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def block_tokens(self) -> set[str]:
        """Tokens that stood alone on their own line in the source."""
        return set(self.images) | set(self.citation_lists)

    @property
    def touched(self) -> bool:
        return bool(self.images or self.citation_keys or self.citation_lists)


def _mask_code(body: str) -> tuple[str, list[str]]:
    """Replace fenced blocks and inline code spans with sentinels.

    Papyrus markup inside a code span is documentation about the syntax, not
    an instance of it -- this doc's own examples would otherwise be rendered.
    """
    stash: list[str] = []

    def park(chunk: str) -> str:
        stash.append(chunk)
        return f"\x00CODE{len(stash) - 1}\x00"

    # Fenced blocks first, scanning line by line so an unterminated fence
    # swallows the rest of the document exactly as Markdown would.
    out: list[str] = []
    fence: str | None = None
    buffer: list[str] = []
    for line in body.splitlines(keepends=True):
        if fence is None:
            match = _FENCE_RE.match(line)
            if match:
                fence = match.group("fence")[0] * 3
                buffer = [line]
                continue
            out.append(line)
        else:
            buffer.append(line)
            if line.strip().startswith(fence):
                out.append(park("".join(buffer)))
                fence = None
                buffer = []
    if fence is not None:
        out.append(park("".join(buffer)))

    masked = "".join(out)
    masked = _INLINE_CODE_RE.sub(lambda m: park(m.group(0)), masked)
    return masked, stash


def _unmask_code(text: str, stash: list[str]) -> str:
    def restore(match: re.Match[str]) -> str:
        return stash[int(match.group(1))]

    return re.sub(r"\x00CODE(\d+)\x00", restore, text)


def prepare_page(
    text: str,
    *,
    images: ImagePipeline | None,
    citations: CitationRendering | None,
) -> PreparedPage:
    """Lower Papyrus markup in ``text`` to sentinels.

    Returns the page unchanged when neither capability is enabled.
    """
    if images is None and citations is None:
        return PreparedPage(markdown=text)

    front_matter, body = split_front_matter(text)
    prefix = f"---{front_matter}\n---\n" if front_matter else ""
    masked, stash = _mask_code(body)

    page = PreparedPage(markdown=text)
    page.entries = read_citation_entries(text) if citations is not None else {}
    counter = 0

    def next_token() -> str:
        nonlocal counter
        counter += 1
        return _TOKEN.format(counter)

    if images is not None:

        def lower_image(match: re.Match[str]) -> str:
            attrs = parse_attrs(match.group("attrs"))
            src = attrs.get("src")
            if not src:
                raise ContentMarkupError(
                    f"::image{{...}} needs a src attribute: {match.group(0).strip()!r}"
                )
            unknown = set(attrs) - {
                "src",
                "alt",
                "layout",
                "caption",
                "credit",
                "sizes",
                "loading",
            }
            if unknown:
                raise ContentMarkupError(
                    f"::image{{...}} got unknown attribute(s) {', '.join(sorted(unknown))}. "
                    "Allowed: src, alt, layout, caption, credit, sizes, loading."
                )
            token = next_token()
            page.images[token] = ImageRequest(
                src=src,
                alt=attrs.get("alt", ""),
                layout=attrs.get("layout"),
                caption=attrs.get("caption"),
                credit=attrs.get("credit"),
                sizes=attrs.get("sizes"),
                loading=attrs.get("loading"),
            )
            return token

        masked = _IMAGE_DIRECTIVE_RE.sub(lower_image, masked)

    if citations is not None:

        def lower_cite(match: re.Match[str]) -> str:
            keys = [part.strip().lstrip("@").strip() for part in match.group("body").split(";")]
            keys = [key for key in keys if key]
            if not keys:
                return match.group(0)
            token = next_token()
            page.citation_keys[token] = keys
            return token

        masked = _CITE_REF_RE.sub(lower_cite, masked)

        def lower_list(match: re.Match[str]) -> str:
            attrs = parse_attrs(match.group("attrs") or "")
            unknown = set(attrs) - {"format"}
            if unknown:
                raise ContentMarkupError(
                    f"::citations{{...}} got unknown attribute(s) {', '.join(sorted(unknown))}. "
                    "Allowed: format."
                )
            token = next_token()
            page.citation_lists[token] = attrs.get("format")
            return token

        masked = _CITATIONS_DIRECTIVE_RE.sub(lower_list, masked)

    page.markdown = prefix + _unmask_code(masked, stash)
    return page


# -- resolution ------------------------------------------------------------


def _img_attrs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in re.finditer(
        r"""([A-Za-z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", raw
    ):
        out[match.group(1).lower()] = html.unescape(
            match.group(2) if match.group(2) is not None else (match.group(3) or "")
        )
    return out


def upgrade_plain_images(fragment: str, builder: ImageBuilder, *, depth: int) -> str:
    """Give Markus's own ``<img>`` output responsive sources and dimensions.

    Covers plain Markdown images and ``:::figure{src=...}`` alike. An image
    that stands alone in its own paragraph is promoted to a ``<figure>``; one
    inside a sentence, or already inside Markus's ``<figure>``, is replaced in
    place so the surrounding structure is preserved.
    """

    # Generated markup contains <img> tags of its own, whose src already
    # carries the page-depth prefix. Park each result behind a sentinel so the
    # second pass cannot re-process what the first pass just produced.
    stash: list[str] = []

    def render(attrs: dict[str, str], *, bare: bool) -> str | None:
        src = attrs.get("src", "")
        if not src:
            return None
        request = ImageRequest(src=src, alt=attrs.get("alt", ""), bare=bare)
        try:
            rendered = builder.render(request, depth=depth)
        except Exception:
            if builder.pipeline.strict:
                raise
            return None
        if not rendered:
            return None
        stash.append(rendered)
        return f"\x00IMG{len(stash) - 1}\x00"

    def lone(match: re.Match[str]) -> str:
        return render(_img_attrs(match.group("img")), bare=False) or match.group(0)

    fragment = _LONE_IMG_PARAGRAPH_RE.sub(lone, fragment)

    def inline(match: re.Match[str]) -> str:
        return render(_img_attrs(match.group("attrs")), bare=True) or match.group(0)

    fragment = _IMG_TAG_RE.sub(inline, fragment)
    return re.sub(r"\x00IMG(\d+)\x00", lambda m: stash[int(m.group(1))], fragment)


def resolve_fragment(
    fragment: str,
    page: PreparedPage,
    *,
    depth: int = 0,
    image_builder: ImageBuilder | None = None,
    citations: CitationRendering | None = None,
) -> str:
    """Substitute real HTML for the sentinels in a converted fragment."""
    if image_builder is not None and image_builder.pipeline.upgrade_plain_images:
        fragment = upgrade_plain_images(fragment, image_builder, depth=depth)

    if not page.touched:
        return fragment

    # Markus wraps a lone sentinel in its own paragraph; block constructs
    # replace that paragraph rather than nesting a <figure> inside a <p>.
    block = page.block_tokens
    if block:
        fragment = re.sub(
            r"<p>\s*(" + "|".join(re.escape(token) for token in sorted(block)) + r")\s*</p>",
            lambda m: m.group(1),
            fragment,
        )

    collector = (
        CitationCollector(page.entries, citations) if citations is not None else None
    )
    list_placeholders: dict[str, str] = {}

    def substitute(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in page.images:
            if image_builder is None:
                raise ContentMarkupError(
                    "::image{} used but no image pipeline is configured "
                    "(pass images=ImagePipeline(...) to build_markus_site)"
                )
            return image_builder.render(page.images[token], depth=depth)
        if collector is not None and token in page.citation_keys:
            rendered = [collector.marker_html(key) for key in page.citation_keys[token]]
            return "".join(bit for bit in rendered if bit)
        if collector is not None and token in page.citation_lists:
            list_placeholders[token] = page.citation_lists[token] or collector.config.default_format
            return token
        return token

    # ``re.sub`` scans left to right, so citation numbers follow the order the
    # markers appear in the rendered page.
    fragment = _TOKEN_RE.sub(substitute, fragment)

    for token, fmt in list_placeholders.items():
        fragment = fragment.replace(token, collector.list_html(fmt=fmt))  # type: ignore[union-attr]

    return fragment
