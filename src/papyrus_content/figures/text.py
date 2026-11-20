"""The words inside a figure's SVG source, found and replaced (PPY-74ef89; docs/figures.md, "Figures in other languages").

A figure is drawn once as ``figure.svg`` and rendered to pictures, so a reader of a translated Story sees the original language's labels unless a
language variant of the figure exists. This module is the pure part of both halves of that:

* :func:`text_segments` finds every piece of reader-facing text in the source (the content of each ``<text>`` element, one segment per run between tags,
  so a label drawn on two ``<tspan>`` lines is two segments). ``<title>`` and ``<desc>`` are not drawn on the picture and are not counted.
* :func:`replace_segments` returns the source with each segment replaced, leaving everything else (comments such as ``<!--primitives-->``, ``{role}``
  colour names, classes, geometry) byte for byte as it was, which is why this works on the text of the file and never re-serialises it.
"""
from __future__ import annotations

import html
import re
from collections.abc import Mapping

_TEXT_ELEMENT = re.compile(r"(<text\b[^>]*>)(.*?)(</text\s*>)", re.S | re.I)


def _runs(inner: str) -> list[tuple[int, int, str]]:
    """``(start, end, text)`` of each run of characters between tags inside one ``<text>`` element (``inner`` is what lies between its tags)."""
    wrapped = f">{inner}<"
    found = []
    for match in re.finditer(r">([^<>]*)<", wrapped):
        text = match.group(1)
        if text.strip():
            found.append((match.start(1) - 1, match.end(1) - 1, text))
    return found


def text_segments(svg: str) -> list[str]:
    """The distinct reader-facing strings of the figure, in the order they first appear, decoded from XML entities and with surrounding space cut."""
    seen: list[str] = []
    for element in _TEXT_ELEMENT.finditer(svg):
        for _, _, text in _runs(element.group(2)):
            decoded = " ".join(html.unescape(text).split())
            if decoded and decoded not in seen:
                seen.append(decoded)
    return seen


def has_embedded_text(svg: str) -> bool:
    return bool(text_segments(svg))


def replace_segments(svg: str, translations: Mapping[str, str]) -> str:
    """``svg`` with each segment named in ``translations`` (decoded source text -> new text) replaced, every other character untouched. A segment with no
    entry is left as it was; the caller decides whether that is allowed."""

    def element(match: re.Match) -> str:
        inner = match.group(2)
        out, cursor = [], 0
        for start, end, text in _runs(inner):
            decoded = " ".join(html.unescape(text).split())
            if decoded not in translations:
                continue
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            out.append(inner[cursor:start] + lead + html.escape(translations[decoded], quote=False) + trail)
            cursor = end
        out.append(inner[cursor:])
        return match.group(1) + "".join(out) + match.group(3)

    return _TEXT_ELEMENT.sub(element, svg)
