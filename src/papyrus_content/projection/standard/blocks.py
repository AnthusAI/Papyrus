"""Page blocks: line-level directives Markus does not own, handled before Markus runs.

``::band{id tone size eyebrow columns}`` starts a full-width section, ``::column{panel}`` the next column of the band,
``::button{href label size variant}`` a call to action (consecutive lines share a row) and ``::island{name height ...}``
a mount point for a site script. Each directive sits alone on its line. Text between directives is converted by Markus
as usual, one segment at a time. ``{{name}}`` tokens are replaced from the ``values`` object of ``projection.json``
before anything else. A file with no ``::band`` line is not touched (apart from tokens).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping

from .markdown import FRONT_MATTER

DIRECTIVE = re.compile(r"^::(band|column|island|button)(?:\{(.*)\})?[ \t]*$")
ATTRIBUTE = re.compile(r'([\w-]+)="([^"]*)"')
TOKEN = re.compile(r"\{\{(\w+)\}\}")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")

TONES = ("background", "card", "muted")
SIZES = ("standard", "hero", "bare")
BUTTON_SIZES = ("default", "lg")
BUTTON_VARIANTS = ("default", "secondary")
PANELS = ("card",)
ATTRIBUTES = {
    "band": {"id", "tone", "size", "eyebrow", "columns"},
    "column": {"panel"},
    "button": {"href", "label", "size", "variant"},
}
ISLAND_NAME = re.compile(r"^[A-Za-z][\w.-]*$")
ISLAND_HEIGHT = re.compile(r"^\d+(\.\d+)?(px|rem|em|vh|%)$")
SAFE_HREF = re.compile(r"^(https?://|mailto:|/(?!/)|#)", re.I)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def substitute(text: str, values: Mapping[str, str], source: str) -> str:
    """Replace ``{{name}}`` tokens; a name that ``values`` does not define is an error. No values: the text is untouched."""
    if not values:
        return text

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError(f"{source}: no value named {{{{{name}}}}} in projection.json values")
        return values[name]

    return TOKEN.sub(replace, text)


def _directives(text: str):
    """``(line, name, attributes)`` for every line; ``name`` is ``None`` for text. Lines inside code fences are text.

    A fence closes at a line of the same character, at least as long as the opening one, with nothing after it, so a
    longer fence can hold shorter ones.
    """
    fence = None
    for line in text.split("\n"):
        marker = FENCE.match(line)
        if marker is not None:
            ticks, rest = marker.group(1), marker.group(2)
            if fence is None:
                fence = ticks
            elif ticks[0] == fence[0] and len(ticks) >= len(fence) and not rest.strip():
                fence = None
        match = DIRECTIVE.match(line) if fence is None else None
        if match is None:
            yield line, None, {}
        else:
            yield line, match.group(1), dict(ATTRIBUTE.findall(match.group(2) or ""))


def uses_bands(text: str) -> bool:
    return any(name == "band" for _line, name, _attributes in _directives(text))


def _choice(source: str, label: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"{source}: {label} {value!r} must be one of {', '.join(allowed)}")
    return value


def _checked(source: str, name: str, attributes: dict) -> dict:
    unknown = set(attributes) - ATTRIBUTES[name]
    if unknown:
        raise ValueError(f"{source}: ::{name} has unknown attributes: {', '.join(sorted(unknown))}")
    return attributes


def _button(source: str, attributes: dict) -> dict:
    _checked(source, "button", attributes)
    href, label = attributes.get("href", ""), attributes.get("label", "")
    if not label or not SAFE_HREF.match(href):
        raise ValueError(f"{source}: ::button needs a label and an http(s), mailto, site-absolute or #fragment href, got {href!r}")
    return {
        "href": href,
        "label": label,
        "size": _choice(source, "button size", attributes.get("size", "default"), BUTTON_SIZES),
        "variant": _choice(source, "button variant", attributes.get("variant", "default"), BUTTON_VARIANTS),
    }


def _buttons_html(buttons: list[dict]) -> str:
    links = "".join(
        f'<a class="markus-button" data-size="{esc(b["size"])}" data-variant="{esc(b["variant"])}" href="{esc(b["href"])}">{esc(b["label"])}</a>'
        for b in buttons
    )
    return f'<p class="markus-actions">{links}</p>'


def _island_html(source: str, attributes: dict) -> str:
    name = attributes.pop("name", "")
    if not ISLAND_NAME.match(name):
        raise ValueError(f"{source}: ::island needs a name such as name=\"Chart\", got {name!r}")
    height = attributes.pop("height", "")
    if height and not ISLAND_HEIGHT.match(height):
        raise ValueError(f"{source}: ::island height {height!r} must be a number with px, rem, em, vh or %")
    style = f' style="min-height:{esc(height)}"' if height else ""
    props = json.dumps(attributes, ensure_ascii=False, separators=(",", ":"))
    props = html.escape(props, quote=False).replace("'", "&#x27;")
    return f'<div class="papyrus-island" data-island="{esc(name)}"{style} data-props=\'{props}\'></div>'


def render(text: str, source: str, convert: Callable[[str], str]) -> str:
    """The HTML of a page that uses bands. ``text`` has no front matter; ``convert`` turns one Markdown segment into HTML."""
    bands: list[dict] = []
    lines: list[str] = []
    buttons: list[dict] = []

    def parts() -> list[str]:
        if not bands:
            raise ValueError(f"{source}: content before the first ::band")
        return bands[-1]["columns"][-1]["parts"]

    def flush_buttons() -> None:
        if buttons:
            parts().append(_buttons_html(buttons))
            buttons.clear()

    def flush_text() -> None:
        markdown = "\n".join(lines).strip()
        lines.clear()
        if markdown:
            parts().append(convert(markdown))

    for line, name, attributes in _directives(text):
        if name is None:
            if line.strip() and buttons:
                flush_buttons()
            lines.append(line)
            continue
        flush_text()
        if name != "button":
            flush_buttons()
        if name == "band":
            _checked(source, name, attributes)
            bands.append({
                "id": attributes.get("id", ""),
                "tone": _choice(source, "band tone", attributes.get("tone", "background"), TONES),
                "size": _choice(source, "band size", attributes.get("size", "standard"), SIZES),
                "eyebrow": attributes.get("eyebrow", ""),
                "layout": attributes.get("columns", ""),
                "columns": [{"panel": "", "parts": []}],
            })
        elif name == "column":
            if not bands:
                raise ValueError(f"{source}: content before the first ::band")
            _checked(source, name, attributes)
            panel = attributes.get("panel", "")
            if panel:
                _choice(source, "column panel", panel, PANELS)
            bands[-1]["columns"].append({"panel": panel, "parts": []})
        elif name == "island":
            parts().append(_island_html(source, attributes))
        else:
            parts()
            buttons.append(_button(source, attributes))
    flush_text()
    flush_buttons()
    return "\n".join(_band_html(band) for band in bands)


def _band_html(band: dict) -> str:
    if band["size"] == "bare":
        return "\n".join(part for column in band["columns"] for part in column["parts"])
    columns = "".join(
        f'<div class="markus-column"{f" data-panel={chr(34)}{esc(column["panel"])}{chr(34)}" if column["panel"] else ""}>' + "\n".join(column["parts"]) + "</div>"
        for column in band["columns"]
    )
    identifier = f' id="{esc(band["id"])}"' if band["id"] else ""
    layout = f' data-layout="{esc(band["layout"])}"' if band["layout"] else ""
    eyebrow = f'<p class="markus-band-eyebrow">{esc(band["eyebrow"])}</p>' if band["eyebrow"] else ""
    return (
        f'<section class="markus-band"{identifier} data-tone="{esc(band["tone"])}" data-size="{esc(band["size"])}"{layout}>'
        f'<div class="markus-band-inner">{eyebrow}<div class="markus-columns" data-count="{len(band["columns"])}">{columns}</div></div></section>'
    )


def twin(text: str, values: Mapping[str, str], source: str) -> str:
    """The Markdown twin's source: tokens replaced, and for a page with bands the markers dropped, buttons turned into links and islands omitted."""
    text = substitute(text, values, source)
    if not uses_bands(text):
        return text
    front = FRONT_MATTER.match(text)
    head, body = (text[: front.end()], text[front.end():]) if front else ("", text)
    out: list[str] = []
    buttons: list[str] = []

    def flush_buttons() -> None:
        if buttons:
            out.extend(["", " · ".join(buttons), ""])
            buttons.clear()

    for line, name, attributes in _directives(body):
        if name == "button":
            attributes = _button(source, attributes)
            buttons.append(f"[{attributes['label']}]({attributes['href']})")
            continue
        if name is None and not line.strip() and buttons:
            continue
        flush_buttons()
        if name is None:
            out.append(line)
        elif name in ("band", "column"):
            out.append("")
    flush_buttons()
    return head + re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
