"""Page blocks: line-level directives Markus does not own, handled before Markus runs.

``::band{id tone size eyebrow columns}`` starts a full-width section, ``::column{panel}`` the next column of the band,
``::button{href label size variant}`` a call to action (consecutive lines share a row) and ``::island{name height ...}``
a mount point for a site script. Each directive sits alone on its line.

``::include{kind=... }`` places generated markup (a listing of entries chosen by tag or section, a showcase, a form, a
block of the site's ``block`` hook) and ``::raw`` ... ``::endraw`` places the lines between them as they are. See
``includes.py``; ``::raw`` is for pages that live in the site's static directory, never for items edited in a CMS. Text between directives is converted by Markus
as usual, one segment at a time. ``::island`` and ``::button`` also work inside a Markus ``:::`` container (a card, a
column): there they are swapped in after the container is converted. ``{{name}}`` tokens are replaced from the ``values`` object of ``projection.json``
before anything else. A file with no ``::band`` line is not touched (apart from tokens).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping

from .markdown import FRONT_MATTER

DIRECTIVE = re.compile(r"^::(band|column|island|button|include)(?:\{(.*)\})?[ \t]*$")
RAW_OPEN = re.compile(r"^::raw[ \t]*$")
RAW_CLOSE = re.compile(r"^::endraw[ \t]*$")
ATTRIBUTE = re.compile(r'([\w-]+)="([^"]*)"')
TOKEN = re.compile(r"\{\{(\w+)\}\}")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
CONTAINER_OPEN = re.compile(r"^:::[\w-]+")
CONTAINER_CLOSE = re.compile(r"^:::[ \t]*$")
INLINE_BLOCKS = ("island", "button", "include", "raw")

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
    """``(line, name, attributes, inside)`` for every line; ``name`` is ``None`` for text. Lines inside code fences are text.

    A fence closes at a line of the same character, at least as long as the opening one, with nothing after it, so a
    longer fence can hold shorter ones. ``inside`` is true for a line within a Markus ``:::`` container, where only
    islands, buttons, includes and raw markup are directives (``::band`` and ``::column`` there are text).

    ``::raw`` opens a region that ends at ``::endraw``: its lines come out as ``"rawline"`` (nothing in them is a
    directive, a fence or a container), the opening and closing lines as ``"raw"`` and ``"endraw"``.
    """
    fence = None
    depth = 0
    raw = False
    for line in text.split("\n"):
        if raw:
            if RAW_CLOSE.match(line):
                raw = False
                yield line, "endraw", {}, depth > 0
            else:
                yield line, "rawline", {}, depth > 0
            continue
        marker = FENCE.match(line)
        if marker is not None:
            ticks, rest = marker.group(1), marker.group(2)
            if fence is None:
                fence = ticks
            elif ticks[0] == fence[0] and len(ticks) >= len(fence) and not rest.strip():
                fence = None
        if fence is None and marker is None and RAW_OPEN.match(line):
            raw = True
            yield line, "raw", {}, depth > 0
            continue
        if fence is None and marker is None:
            if CONTAINER_CLOSE.match(line):
                depth = max(depth - 1, 0)
            elif CONTAINER_OPEN.match(line):
                depth += 1
        match = DIRECTIVE.match(line) if fence is None else None
        if match is not None and depth and match.group(1) not in INLINE_BLOCKS:
            match = None
        if match is None:
            yield line, None, {}, depth > 0
        else:
            yield line, match.group(1), dict(ATTRIBUTE.findall(match.group(2) or "")), depth > 0
    if raw:
        raise ValueError("::raw without a closing ::endraw")


def uses_bands(text: str) -> bool:
    return any(name == "band" for _line, name, _attributes, _inside in _directives(text))


def uses_blocks(text: str) -> bool:
    """True when the text holds anything this module handles: a band, an include or raw markup."""
    return any(name in ("band", "include", "raw") for _line, name, _attributes, _inside in _directives(text))


def includes_in(text: str) -> list[dict]:
    """The attributes of every ``::include`` of a text, in order (the page's declared dependencies)."""
    return [attributes for _line, name, attributes, _inside in _directives(text) if name == "include"]


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


def render(
    text: str, source: str, convert: Callable[[str], str], include: Callable[[dict], str] | None = None, *, trusted: bool = False,
) -> str:
    """The HTML of a page that uses bands. ``text`` has no front matter; ``convert`` turns one Markdown segment into HTML.

    ``include`` turns the attributes of one ``::include`` into markup; ``trusted`` allows ``::raw`` (a page file of the
    site's repository, not an item an editor wrote).
    """
    bands: list[dict] = []
    lines: list[str] = []
    buttons: list[dict] = []
    inline: dict[str, str] = {}      # placeholder token -> HTML, for blocks inside a Markus container
    inline_buttons: list[dict] = []

    def parts() -> list[str]:
        if not bands:
            raise ValueError(f"{source}: content before the first ::band")
        return bands[-1]["columns"][-1]["parts"]

    def flush_buttons() -> None:
        if buttons:
            parts().append(_buttons_html(buttons))
            buttons.clear()

    def place(html_text: str) -> None:
        token = f"PAPYRUSBLOCK{len(inline)}X"
        inline[token] = html_text
        lines.extend(("", token, ""))

    def flush_inline_buttons() -> None:
        if inline_buttons:
            place(_buttons_html(inline_buttons))
            inline_buttons.clear()

    def flush_text() -> None:
        flush_inline_buttons()
        markdown = "\n".join(lines).strip()
        lines.clear()
        if markdown:
            converted = convert(markdown)
            for token, replacement in inline.items():
                converted = converted.replace(f"<p>{token}</p>", replacement).replace(token, replacement)
            parts().append(converted)

    raw_lines: list[str] = []
    raw_inside = False
    for line, name, attributes, inside in _directives(text):
        if name == "raw":
            if not trusted:
                raise ValueError(f"{source}: ::raw is only allowed in a page file of the site's static directory")
            raw_lines, raw_inside = [], inside
            continue
        if name == "rawline":
            raw_lines.append(line)
            continue
        if name in ("endraw", "include"):
            if name == "include":
                if include is None:
                    raise ValueError(f"{source}: ::include is not available here")
                markup, raw_inside = include(attributes), inside
            else:
                markup = "\n".join(raw_lines)
            if raw_inside:
                flush_inline_buttons()
                place(markup)
            else:
                flush_text()
                flush_buttons()
                parts().append(markup)
            continue
        if inside and name == "island":
            flush_inline_buttons()
            place(_island_html(source, attributes))
            continue
        if inside and name == "button":
            inline_buttons.append(_button(source, attributes))
            continue
        if name is None:
            if line.strip() and buttons:
                flush_buttons()
            if line.strip():
                flush_inline_buttons()
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
    if not uses_blocks(text):
        return text
    front = FRONT_MATTER.match(text)
    head, body = (text[: front.end()], text[front.end():]) if front else ("", text)
    out: list[str] = []
    buttons: list[str] = []

    def flush_buttons() -> None:
        if buttons:
            out.extend(["", " · ".join(buttons), ""])
            buttons.clear()

    for line, name, attributes, _inside in _directives(body):
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


ISLAND_MOUNT = re.compile(r'<(?P<tag>div|span)(?P<attributes>(?=[^>]*\bclass="papyrus-island")[^>]*\bdata-island="(?P<name>[^"]+)"[^>]*)></(?P=tag)>')
ISLAND_PROPS = re.compile(r"\bdata-props='([^']*)'")


def parse_prerendered(data: bytes) -> dict[str, list[tuple[dict, str]]]:
    """``islands.prerender`` is a JSON list of ``{"name", "props", "html"}``; the result maps a name to its ``(props, html)`` pairs."""
    entries = json.loads(data.decode("utf-8"))
    if not isinstance(entries, list):
        raise ValueError("islands.prerender must be a JSON list of {name, props, html}")
    by_name: dict[str, list[tuple[dict, str]]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not isinstance(entry.get("html"), str):
            raise ValueError("islands.prerender entries need a name and html")
        by_name.setdefault(entry["name"], []).append((dict(entry.get("props") or {}), entry["html"]))
    return by_name


def fill_islands(body: str, prerendered: Mapping[str, list[tuple[dict, str]]]) -> str:
    """Put the server-rendered HTML inside every empty mount point that has an entry for its name and props.

    A mount point with no entry stays empty (the site script mounts it in the browser). The HTML is the site's own build
    output and is inserted as written; the site script hydrates it."""

    def fill(match: re.Match) -> str:
        props_text = ISLAND_PROPS.search(match.group("attributes"))
        try:
            props = json.loads(html.unescape(props_text.group(1))) if props_text else {}
        except ValueError:
            return match.group(0)
        for candidate, rendered in prerendered.get(match.group("name"), ()):
            if candidate == props:
                tag = match.group("tag")
                return f"<{tag}{match.group('attributes')}>{rendered}</{tag}>"
        return match.group(0)

    return ISLAND_MOUNT.sub(fill, body)
