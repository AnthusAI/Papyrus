"""Plain-text alternative derived from the same parsed Markus fragment."""

from __future__ import annotations

import re
import textwrap

from .dom import Node
from .styles import BLOCK_TAGS
from .urls import absolute_url

WIDTH = 76
_WS = re.compile(r"[ \t\r\n\f]+")


def wrap(text: str, indent: str = "", first: str | None = None) -> str:
    first = indent if first is None else first
    lines: list[str] = []
    for i, raw in enumerate(text.split("\n")):
        lines.append(
            textwrap.fill(
                raw.strip(),
                WIDTH,
                initial_indent=first if i == 0 else indent,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or (first if i == 0 else indent).rstrip()
        )
    return "\n".join(lines)


def _inline(node: Node, site_url: str, links: list[str] | None = None) -> str:
    out: list[str] = []
    for c in node.children:
        if c.tag is None:
            out.append(_WS.sub(" ", c.text))
        elif c.tag == "br":
            out.append("\n")
        elif c.tag == "img":
            alt = c.attrs.get("alt", "").strip()
            if alt:
                out.append(f"[Image: {alt}]")
        elif c.tag == "a":
            label = _inline(c, site_url, links).strip()
            href = absolute_url(c.attrs.get("href", ""), site_url)
            if links is not None:
                out.append(label)
                if href is not None and not (href.startswith("mailto:") and label == href[7:]) and href != label:
                    links.append(href)
            elif href is None or label == href:
                out.append(label)
            elif href.startswith("mailto:") and label == href[7:]:
                out.append(label)
            else:
                out.append(f"{label} ({href})" if label else href)
        else:
            out.append(_inline(c, site_url, links))
    return "".join(out)


def _runs(node: Node):
    """Yield ('inline', [nodes]) and ('block', node) groups over children."""
    run: list[Node] = []
    for c in node.children:
        if c.tag is not None and c.tag in BLOCK_TAGS:
            if run:
                yield "inline", run
                run = []
            yield "block", c
        else:
            run.append(c)
    if run:
        yield "inline", run


def _inline_run(nodes: list[Node], site_url: str) -> str:
    text = _inline(Node("span", children=nodes), site_url)
    return re.sub(r" *\n *", "\n", text).strip()


def _heading(item: Node, site_url: str, indent: str, tag: str) -> str:
    """Heading text with any link URLs moved to their own `<url>` lines, never uppercased or wrapped."""
    links: list[str] = []
    title = re.sub(r" *\n *", "\n", _inline(Node("span", children=item.children), site_url, links)).strip()
    if not title:
        return ""
    if tag in ("h1", "h2", "h3"):
        title = title.upper()
    rule = {"h1": "=", "h2": "-"}.get(tag)
    out = wrap(title, indent)
    if rule:
        out += "\n" + indent + rule * min(len(title), WIDTH - len(indent))
    for url in dict.fromkeys(links):
        out += f"\n{indent}<{url}>"
    return out


def blocks(node: Node, site_url: str, indent: str = "") -> list[str]:
    out: list[str] = []
    for kind, item in _runs(node):
        if kind == "inline":
            text = _inline_run(item, site_url)
            if text:
                out.append(wrap(text, indent))
            continue
        tag = item.tag
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            heading = _heading(item, site_url, indent, tag)
            if heading:
                out.append(heading)
        elif tag in ("ul", "ol"):
            out.append(_list(item, site_url, indent))
        elif tag == "blockquote":
            inner = blocks(item, site_url, indent + "> ")
            out.append(("\n" + indent + ">\n").join(inner))
        elif tag == "pre":
            code = "".join(_raw(item)).rstrip("\n")
            out.append("\n".join(indent + "    " + line for line in code.split("\n")))
        elif tag == "table":
            out.append(_table(item, site_url, indent))
        elif tag == "hr":
            out.append(indent + "-" * 20)
        else:
            out.extend(blocks(item, site_url, indent))
    return out


def _raw(node: Node):
    for c in node.children:
        if c.tag is None:
            yield c.text
        else:
            yield from _raw(c)


def _list(node: Node, site_url: str, indent: str) -> str:
    items: list[str] = []
    n = int(node.attrs.get("start", "1") or 1) if node.attrs.get("start", "1").isdigit() else 1
    for li in (c for c in node.children if c.tag == "li"):
        marker = f"{n}. " if node.tag == "ol" else "- "
        n += 1
        hang = indent + " " * len(marker)
        parts = blocks(li, site_url, hang)
        if not parts:
            continue
        parts[0] = indent + marker + parts[0][len(hang) :]
        items.append("\n".join(parts[:1]) + "".join("\n" + p for p in parts[1:]))
    return "\n".join(items)


def _table(node: Node, site_url: str, indent: str) -> str:
    rows: list[str] = []
    for tr in _find(node, "tr"):
        cells = [
            _inline_run(c.children, site_url).replace("\n", " ")
            for c in tr.children
            if c.tag in ("td", "th")
        ]
        rows.append(wrap(" | ".join(cells), indent, indent))
    return "\n".join(rows)


def _find(node: Node, tag: str):
    for c in node.children:
        if c.tag == tag:
            yield c
        elif c.tag is not None:
            yield from _find(c, tag)
