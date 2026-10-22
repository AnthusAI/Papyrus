"""Fixed tag -> inline style map and the HTML serializer for the Markus fragment."""

from __future__ import annotations

from html import escape

from .dom import VOID_TAGS, Node
from .theme import EmailTheme
from .urls import absolute_url

MONO = "Menlo, Consolas, 'Courier New', monospace"
KEEP_ATTRS = {
    "a": ("href", "title"),
    "img": ("src", "alt", "title", "width", "height"),
    "td": ("colspan", "rowspan", "align"),
    "th": ("colspan", "rowspan", "align"),
    "ol": ("start",),
}
BLOCK_TAGS = frozenset(
    "article section div aside figure figcaption details summary p h1 h2 h3 h4 h5 h6 ul ol li "
    "blockquote pre table thead tbody tfoot tr td th hr dl dt dd".split()
)


def style_map(t: EmailTheme) -> dict[str, str]:
    base = f"font-family:{t.font_family};color:{t.text};"
    heading = base + "font-weight:bold;line-height:1.25;margin:28px 0 12px 0;"
    cell = f"border:1px solid {t.muted};padding:8px 10px;text-align:left;vertical-align:top;"
    return {
        "p": base + "font-size:17px;line-height:1.6;margin:0 0 16px 0;",
        "h1": heading + "font-size:28px;",
        "h2": heading + "font-size:23px;",
        "h3": heading + "font-size:19px;",
        "h4": heading + "font-size:17px;",
        "h5": heading + "font-size:16px;",
        "h6": heading + "font-size:15px;",
        "a": f"color:{t.accent};text-decoration:underline;",
        "ul": base + "font-size:17px;line-height:1.6;margin:0 0 16px 0;padding:0 0 0 24px;",
        "ol": base + "font-size:17px;line-height:1.6;margin:0 0 16px 0;padding:0 0 0 24px;",
        "li": base + "font-size:17px;line-height:1.6;margin:0 0 6px 0;",
        "blockquote": f"font-family:{t.font_family};color:{t.muted};font-style:italic;margin:0 0 16px 0;"
        f"padding:4px 0 4px 16px;border-left:4px solid {t.accent};",
        "pre": f"font-family:{MONO};font-size:14px;line-height:1.5;color:{t.text};background-color:#f4f4f4;"
        "margin:0 0 16px 0;padding:12px;white-space:pre-wrap;word-wrap:break-word;",
        "code": f"font-family:{MONO};font-size:15px;",
        "img": "display:block;max-width:100%;height:auto;border:0;margin:0 0 16px 0;",
        "hr": f"border:0;border-top:1px solid {t.muted};margin:24px 0;height:0;",
        "table": f"border-collapse:collapse;width:100%;margin:0 0 16px 0;font-family:{t.font_family};"
        f"font-size:15px;color:{t.text};",
        "th": cell + "font-weight:bold;",
        "td": cell,
        "figcaption": f"font-family:{t.font_family};font-size:14px;color:{t.muted};margin:0 0 16px 0;",
        "strong": "font-weight:bold;",
        "em": "font-style:italic;",
        "sup": "font-size:12px;line-height:0;",
    }


def _callout_style(t: EmailTheme) -> str:
    return f"border-left:4px solid {t.accent};background-color:#f4f4f4;padding:8px 14px;margin:0 0 16px 0;"


def _classes(node: Node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def serialize(node: Node, theme: EmailTheme, site_url: str, styles: dict[str, str] | None = None) -> str:
    styles = styles or style_map(theme)
    return "".join(_emit(c, theme, site_url, styles) for c in node.children)


def _emit(node: Node, theme: EmailTheme, site_url: str, styles: dict[str, str]) -> str:
    if node.tag is None:
        return escape(node.text, quote=False)
    tag = node.tag
    classes = _classes(node)
    inner = "".join(_emit(c, theme, site_url, styles) for c in node.children)

    if tag == "a":
        href = absolute_url(node.attrs.get("href", ""), site_url)
        if href is None:
            return inner
        title = node.attrs.get("title")
        title_attr = f' title="{escape(title)}"' if title else ""
        return f'<a href="{escape(href)}"{title_attr} style="{styles["a"]}">{inner}</a>'
    if tag == "img":
        src = absolute_url(node.attrs.get("src", ""), site_url, schemes=frozenset({"http", "https"}))
        if src is None:
            return ""
        parts = [f'src="{escape(src)}"', f'alt="{escape(node.attrs.get("alt", ""))}"']
        for key in ("title", "width", "height"):
            if node.attrs.get(key):
                parts.append(f'{key}="{escape(node.attrs[key])}"')
        return f'<img {" ".join(parts)} style="{styles["img"]}" />'
    if tag == "br":
        return "<br />"
    if tag == "hr":
        return f'<hr style="{styles["hr"]}" />'

    if tag in ("article", "section", "div", "figure", "details", "summary", "aside", "span", "dl", "dt", "dd"):
        if tag == "aside" and any(c.startswith("markus-callout") for c in classes):
            return f'<div class="em-callout" style="{_callout_style(theme)}">{inner}</div>'
        if "markus-table-wrap" in classes:
            return f'<div style="overflow-x:auto;">{inner}</div>'
        return inner if tag in ("span", "article", "section") else f"<div>{inner}</div>"
    if tag == "p" and "markus-callout-title" in classes:
        style = styles["p"] + "font-weight:bold;margin-bottom:6px;"
        return f'<p style="{style}">{inner}</p>'

    style = styles.get(tag)
    kept = ""
    for attr in KEEP_ATTRS.get(tag, ()):
        if node.attrs.get(attr):
            kept += f' {attr}="{escape(node.attrs[attr])}"'
    if tag in ("table",):
        kept += ' cellpadding="0" cellspacing="0" border="0"'
    style_attr = f' style="{style}"' if style else ""
    if tag in VOID_TAGS:
        return f"<{tag}{kept}{style_attr} />"
    return f"<{tag}{kept}{style_attr}>{inner}</{tag}>"
