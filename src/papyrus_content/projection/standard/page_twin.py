"""The Markdown twin of a page that is a template: an authored page file, the home item, a section front page.

An article's twin is its Markus source as written (``blocks.twin``). A page file is different: its directives are a
template for the HTML page, and a reader of the twin (a person following "View as Markdown", an agent) has no use for
``::band{size="bare"}`` or ``::include{kind="references" ...}``. This module turns such a source into what the page shows:

``::band`` and ``::column``  layout only; nothing is written.
``::button``                 a Markdown link, ``[label](href)``.
``::island``                 its ``summary`` text, when it has one.
``::include``                what the include places, as a Markdown list of titles and links (the caller renders it).
``::raw`` ... ``::endraw``   hand-written markup with no source text to read; nothing is written.

Every other line, including Markus directives such as ``::image`` and ``:::`` containers, is kept as written.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from html.parser import HTMLParser

from .blocks import _directives, substitute
from .markdown import FRONT_MATTER

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
SKIPPED = ("script", "style", "svg")   # their text is code or the labels of a drawing, not words
UNSAFE_HREF = re.compile(r"^\s*(javascript|data|vbscript):", re.I)


def render(
    text: str,
    values: Mapping[str, str],
    source: str,
    include_markdown: Callable[[dict], str],
    absolute: Callable[[str], str],
) -> str:
    """The twin source of a page file: tokens replaced, page directives rendered as Markdown, front matter kept as it is.

    ``include_markdown`` returns the Markdown of one ``::include`` (empty when it places nothing readable); ``absolute`` makes a
    site path an absolute URL. Includes are rendered in document order, so a ledger the callback keeps behaves as on the page."""
    text = substitute(text, values, source)
    front = FRONT_MATTER.match(text)
    head, body = (text[: front.end()], text[front.end():]) if front else ("", text)
    out: list[str] = []
    for line, name, attributes, _inside in _directives(body):
        if name is None:
            out.append(line)
        elif name == "button":
            link = _button_link(attributes, absolute)
            if link:
                out += ["", link, ""]
        elif name == "island":
            summary = attributes.get("summary", "").strip()
            if summary:
                out += ["", summary, ""]
        elif name == "include":
            markdown = include_markdown(attributes).strip("\n")
            if markdown:
                out += ["", markdown, ""]
        # band, column, raw, rawline and endraw write nothing
    return head + re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def _button_link(attributes: Mapping[str, str], absolute: Callable[[str], str]) -> str:
    label, href = attributes.get("label", "").strip(), attributes.get("href", "").strip()
    if not label or not href or UNSAFE_HREF.match(href):
        return ""
    return f"[{label}]({absolute(href) if href.startswith('/') else href})"


class _Outline(HTMLParser):
    """The headings, links and (when there are no links) paragraphs of a block of markup, in order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str, str]] = []   # (kind, text, href) in document order; kind is heading, link or text
        self._href: str | None = None
        self._buffer: list[str] = []
        self._heading: int | None = None
        self._skip = 0
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIPPED:
            self._skip += 1
        elif tag == "a":
            self._flush_text()
            self._href = dict(attrs).get("href") or ""
            self._buffer = []
        elif tag in HEADINGS:
            self._flush_text()
            self._heading = int(tag[1])
        elif tag in ("p", "li", "div", "section", "article", "br"):
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED:
            self._skip = max(self._skip - 1, 0)
        elif tag == "a":
            label = " ".join("".join(self._buffer).split())
            href = self._href or ""
            self._buffer, self._href = [], None
            if label and href and not href.startswith("#") and not UNSAFE_HREF.match(href) and href not in self._seen:
                self._seen.add(href)
                self.entries.append(("link", label, href))
        elif tag in HEADINGS and self._heading is not None:
            label = " ".join("".join(self._buffer).split())
            self._buffer, level = [], self._heading
            self._heading = None
            if label:
                self.entries.append(("heading", f"{'#' * min(max(level, 2), 6)} {label}", ""))
        elif tag in ("p", "li", "div", "section", "article"):
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buffer.append(data)

    def _flush_text(self) -> None:
        if self._href is not None or self._heading is not None:
            return
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if text:
            self.entries.append(("text", text, ""))

    def close(self) -> None:
        super().close()
        self._flush_text()


def markup_markdown(markup: str, absolute: Callable[[str], str]) -> str:
    """A block's markup as Markdown: its headings, then each distinct link as a list item. A block with no link is its headings and text.

    This is how an include the standard front end cannot name (a site's own ``block`` hook, a knowledge block) reaches the twin: the title
    and the link of what the block links to, not its card chrome."""
    outline = _Outline()
    outline.feed(markup)
    outline.close()
    has_links = any(kind == "link" for kind, _text, _href in outline.entries)
    lines: list[str] = []
    for kind, text, href in outline.entries:
        if kind == "text" and has_links:
            continue
        if kind == "link":
            lines.append(f"- [{text}]({absolute(href) if href.startswith('/') else href})")
        else:
            lines += ["", text, ""] if kind == "heading" else [text, ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
