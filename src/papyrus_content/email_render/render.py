from __future__ import annotations

from dataclasses import dataclass
from html import escape

from papyrus_content.markus_renderer.build import render_fragment_text
from papyrus_content.markus_renderer.convert import convert_text_in_process

from . import text as text_mod
from .dom import parse_fragment
from .styles import serialize, style_map
from .theme import EmailTheme, readable_on
from .urls import absolute_url


class PostalAddressMissing(ValueError):
    """A marketing issue cannot be rendered without the sender's postal address."""


@dataclass(frozen=True)
class EmailFooter:
    site_name: str
    site_url: str
    reason: str
    manage_url: str
    unsubscribe_url: str
    postal_address: str | None


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _body(markus: str, theme: EmailTheme, site_url: str) -> tuple[str, str]:
    fragment = render_fragment_text(markus, convert=convert_text_in_process)
    tree = parse_fragment(fragment)
    html = serialize(tree, theme, site_url, style_map(theme))
    plain = "\n\n".join(b for b in text_mod.blocks(tree, site_url) if b.strip())
    return html, plain


_LEGACY_DARK = """@media (prefers-color-scheme: dark) {
  .em-bg { background-color: #111111 !important; }
  .em-card { background-color: #1c1c1c !important; }
  .em-card p, .em-card li, .em-card h1, .em-card h2, .em-card h3, .em-card h4, .em-card h5, .em-card h6, .em-card td, .em-card th { color: #eeeeee !important; }
  .em-muted, .em-muted a { color: #bbbbbb !important; }
  .em-card a { color: #9ec5ff !important; }
  .em-card pre, .em-card .em-callout { background-color: #2a2a2a !important; color: #eeeeee !important; }
}"""

#: Dark tokens for a branded theme: ink page and panels, paper text. The bands and the button keep the brand colours.
DARK_PAGE = "#1A1615"
DARK_SURFACE = "#26211F"
DARK_TEXT = "#F5F1EA"
DARK_MUTED = "#CFC8BF"
DARK_CODE = "#322B28"


@dataclass(frozen=True)
class FooterParts:
    """What the footer says, for the footer band (the plain footer is built by the caller)."""

    reason: str
    links: tuple[tuple[str, str], ...]
    address_lines: tuple[str, ...] = ()


def _button_colors(theme: EmailTheme) -> tuple[str, str, str | None]:
    fill = theme.button_fill or theme.accent
    return fill, theme.button_text or readable_on(fill), theme.button_border


def _branded_dark(theme: EmailTheme) -> str:
    rules = [
        f".em-bg {{ background-color: {DARK_PAGE} !important; }}",
        f".em-card {{ background-color: {DARK_SURFACE} !important; }}",
        ".em-card p, .em-card li, .em-card h1, .em-card h2, .em-card h3, .em-card h4, .em-card h5, .em-card h6, "
        f".em-card td, .em-card th {{ color: {DARK_TEXT} !important; }}",
        f".em-muted, .em-muted a {{ color: {DARK_MUTED} !important; }}",
        f".em-card a {{ color: {DARK_TEXT} !important; text-decoration: underline !important; }}",
        f".em-card pre, .em-card .em-callout {{ background-color: {DARK_CODE} !important; color: {DARK_TEXT} !important; }}",
    ]
    if theme.header_band:
        rules.append(f".em-hband {{ background-color: {theme.header_band} !important; }}")
        rules.append(f".em-hband, .em-hband a, .em-hband div, .em-hband span {{ color: {theme.header_ink} !important; }}")
    if theme.footer_band:
        rules.append(f".em-fband {{ background-color: {theme.footer_band} !important; }}")
        rules.append(
            f".em-fband, .em-fband a, .em-fband p, .em-fband div, .em-fband span {{ color: {theme.footer_ink} !important; }}"
        )
    fill, ink, _ = _button_colors(theme)
    rules.append(f".em-btn-cell {{ background-color: {fill} !important; }}")
    rules.append(f".em-card a.em-btn {{ color: {ink} !important; text-decoration: none !important; }}")
    return "@media (prefers-color-scheme: dark) {\n  " + "\n  ".join(rules) + "\n}"


def _head(subject: str, theme: EmailTheme) -> str:
    dark = _branded_dark(theme) if theme.is_branded else _LEGACY_DARK
    root = "\n:root { color-scheme: light dark; supported-color-schemes: light dark; }" if theme.is_branded else ""
    return f"""<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="light dark" />
<meta name="supported-color-schemes" content="light dark" />
<title>{escape(subject)}</title>
<style type="text/css">{root}
@media only screen and (max-width: 620px) {{
  .em-container {{ width: 100% !important; }}
  .em-pad {{ padding-left: 16px !important; padding-right: 16px !important; }}
}}
{dark}
</style>
</head>"""


def _wordmark(theme: EmailTheme, home: str, site_name: str, *, size: int = 22, color: str | None = None) -> str:
    """The brand mark: the wordmark image when set, else the site name as text."""
    if theme.wordmark_image_url:
        return (
            f'<a href="{home}" style="text-decoration:none;"><img src="{escape(theme.wordmark_image_url)}" '
            f'alt="{escape(theme.wordmark_text or site_name)}" width="{theme.wordmark_width}" height="{theme.wordmark_height}" '
            f'style="display:block;border:0;outline:none;max-width:100%;height:auto;" /></a>'
        )
    return (
        f'<a href="{home}" style="font-family:{theme.font_family};font-size:{size}px;font-weight:bold;'
        f'color:{color or theme.accent};text-decoration:none;">{escape(site_name)}</a>'
    )


def _label_style(theme: EmailTheme, color: str, size: int = 11) -> str:
    return (
        f"font-family:{theme.mono};font-size:{size}px;font-weight:bold;letter-spacing:1.2px;text-transform:uppercase;"
        f"color:{color};"
    )


def _header_rows(theme: EmailTheme, site_url: str, site_name: str, label: str) -> str:
    """The row above the card: a band when the theme has one, else the plain brand line."""
    home = escape(site_url)
    if theme.header_band:
        ink = theme.header_ink
        label_html = (
            f'<div style="{_label_style(theme, ink)}margin:12px 0 0 0;line-height:1.4;">{escape(label)}</div>' if label else ""
        )
        return (
            f'<tr><td class="em-hband em-pad" bgcolor="{theme.header_band}" '
            f'style="background-color:{theme.header_band};padding:26px 32px 20px 32px;color:{ink};">'
            f"{_wordmark(theme, home, site_name, size=28, color=ink)}{label_html}</td></tr>"
        )
    logo = absolute_url(theme.logo_url or "", site_url, schemes=frozenset({"http", "https"}))
    if theme.wordmark_image_url:
        brand = _wordmark(theme, home, site_name)
    elif logo:
        brand = (
            f'<a href="{home}" style="text-decoration:none;"><img src="{escape(logo)}" alt="{escape(site_name)}" '
            f'style="display:block;max-width:100%;max-height:60px;height:auto;border:0;" /></a>'
        )
    else:
        brand = _wordmark(theme, home, site_name)
    return f'<tr><td class="em-pad" style="padding:0 32px 16px 32px;">{brand}</td></tr>'


def _footer_row(theme: EmailTheme, site_url: str, site_name: str, legacy: str, parts: FooterParts | None) -> str:
    home = escape(site_url)
    if theme.footer_band and parts is not None:
        ink = theme.footer_ink
        font = f"font-family:{theme.font_family};color:{ink};"
        links = f' <span style="{_label_style(theme, ink, 12)}">&middot;</span> '.join(
            f'<a href="{escape(url)}" style="color:{ink};text-decoration:underline;">{escape(label)}</a>'
            for label, url in parts.links
        )
        address = "<br />".join(escape(line) for line in parts.address_lines)
        address_html = (
            f'<p style="{_label_style(theme, ink, 11)}font-weight:normal;margin:0;line-height:1.6;">{address}</p>' if address else ""
        )
        return (
            f'<tr><td class="em-fband em-pad" bgcolor="{theme.footer_band}" '
            f'style="background-color:{theme.footer_band};padding:22px 32px 26px 32px;{font}">'
            f'<div style="margin:0 0 14px 0;">{_wordmark(theme, home, site_name, size=26, color=ink)}</div>'
            f'<p style="{_label_style(theme, ink, 12)}margin:0 0 12px 0;line-height:1.8;">{links}</p>'
            f'<p style="{font}font-size:13px;line-height:1.5;margin:0 0 10px 0;">{escape(parts.reason)}</p>'
            f"{address_html}</td></tr>"
        )
    return (
        f'<tr><td class="em-pad em-muted" style="padding:20px 32px 0 32px;font-family:{theme.font_family};'
        f'font-size:13px;line-height:1.5;color:{theme.muted};">\n{legacy}\n</td></tr>'
    )


def _shell(
    *, subject: str, preheader: str, theme: EmailTheme, site_url: str, site_name: str, content: str, footer: str,
    label: str = "", parts: FooterParts | None = None,
) -> str:
    pre = (
        f'<span style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;'
        f'overflow:hidden;mso-hide:all;visibility:hidden;color:{theme.background};">{escape(preheader)}'
        f"{'&#8199;&#847;' * 20 if preheader else ''}</span>"
    )
    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
{_head(subject, theme)}
<body class="em-bg" style="margin:0;padding:0;background-color:{theme.background};">
{pre}
<table role="presentation" class="em-bg" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{theme.background}" style="background-color:{theme.background};">
<tr><td align="center" style="padding:24px 12px;">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" class="em-container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;">
{_header_rows(theme, site_url, site_name, label)}
<tr><td class="em-card em-pad" bgcolor="{theme.surface}" style="background-color:{theme.surface};padding:24px 32px 12px 32px;">
{content}
</td></tr>
{_footer_row(theme, site_url, site_name, footer, parts)}
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>
"""


def _button(url: str, label: str, theme: EmailTheme) -> str:
    if theme.button_fill or theme.button_border:
        fill, fg, border = _button_colors(theme)
        edge = f"border:1.5px solid {border};" if border else ""
        return (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px 0;">'
            f'<tr><td class="em-btn-cell" align="center" bgcolor="{fill}" style="background-color:{fill};{edge}">'
            f'<a class="em-btn" href="{escape(url)}" style="display:inline-block;padding:11px 18px;font-family:{theme.font_family};'
            f'font-size:15px;font-weight:bold;color:{fg};text-decoration:none;">{escape(label)}</a>'
            "</td></tr></table>"
        )
    fg = readable_on(theme.accent)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px 0;">'
        f'<tr><td align="center" bgcolor="{theme.accent}" style="background-color:{theme.accent};border-radius:4px;">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:12px 24px;font-family:{theme.font_family};'
        f'font-size:16px;font-weight:bold;color:{fg};text-decoration:none;">{escape(label)}</a>'
        "</td></tr></table>"
    )


def _link_style(theme: EmailTheme) -> str:
    return f'style="color:{theme.muted};text-decoration:underline;"'


def _plain_header(theme: EmailTheme, site_name: str, label: str) -> str:
    """Plain-text counterpart of the header: the wordmark's alt text (or the site name) and the label."""
    if not (theme.header_band or theme.wordmark_image_url):
        return ""
    lines = [theme.wordmark_text or site_name]
    if theme.header_band and label:
        lines.append(label.upper())
    return "\n".join(lines) + "\n\n"


def render_issue(
    *,
    subject: str,
    markus: str,
    theme: EmailTheme,
    footer: EmailFooter,
    preheader: str = "",
    site_url: str,
    list_name: str = "",
) -> RenderedEmail:
    address = (footer.postal_address or "").strip()
    if not address:
        raise PostalAddressMissing("A postal address is required to render a newsletter issue")
    subject = _one_line(subject)
    html_body, plain_body = _body(markus, theme, site_url)
    ls = _link_style(theme)
    address_html = "<br />".join(escape(line.strip()) for line in address.splitlines() if line.strip())
    footer_html = (
        f'<p style="margin:0 0 10px 0;">{escape(footer.reason)}</p>'
        f'<p style="margin:0 0 10px 0;"><a href="{escape(footer.manage_url)}" {ls}>Manage your subscription</a>'
        f' &nbsp;|&nbsp; <a href="{escape(footer.unsubscribe_url)}" {ls}>Unsubscribe</a></p>'
        f'<p style="margin:0 0 10px 0;"><a href="{escape(footer.site_url)}" {ls}>{escape(footer.site_name)}</a><br />'
        f"{address_html}</p>"
    )
    address_lines = tuple(line.strip() for line in address.splitlines() if line.strip())
    label = _one_line(list_name) or subject
    parts = FooterParts(
        reason=footer.reason,
        links=((footer.site_name, footer.site_url), ("Unsubscribe", footer.unsubscribe_url), ("Email preferences", footer.manage_url)),
        address_lines=address_lines,
    )
    html = _shell(
        subject=subject, preheader=preheader, theme=theme, site_url=site_url,
        site_name=footer.site_name, content=html_body, footer=footer_html, label=label, parts=parts,
    )
    address_text = "\n".join(address_lines)
    plain = (
        f"{_plain_header(theme, footer.site_name, label)}{plain_body}\n\n--\n"
        f"{text_mod.wrap(footer.reason)}\n\n"
        f"Manage your subscription: {footer.manage_url}\n"
        f"Unsubscribe: {footer.unsubscribe_url}\n\n"
        f"{footer.site_name} - {footer.site_url}\n{address_text}\n"
    )
    return RenderedEmail(subject=subject, html=html, text=plain)


def render_transactional(
    *,
    subject: str,
    markus: str,
    theme: EmailTheme,
    site_name: str,
    site_url: str,
    preheader: str = "",
    action_url: str | None = None,
    action_label: str | None = None,
) -> RenderedEmail:
    subject = _one_line(subject)
    html_body, plain_body = _body(markus, theme, site_url)
    if action_url:
        label = action_label or "Continue"
        html_body += _button(action_url, label, theme)
        plain_body += f"\n\n{label}: {action_url}"
    ls = _link_style(theme)
    reason = f"You received this because someone entered this address on {site_name}. If it was not you, ignore this email."
    footer_html = (
        f'<p style="margin:0 0 10px 0;">{escape(reason)}</p>'
        f'<p style="margin:0 0 10px 0;"><a href="{escape(site_url)}" {ls}>{escape(site_name)}</a></p>'
    )
    parts = FooterParts(reason=reason, links=((site_name, site_url),))
    html = _shell(
        subject=subject, preheader=preheader, theme=theme, site_url=site_url,
        site_name=site_name, content=html_body, footer=footer_html, parts=parts,
    )
    plain = f"{_plain_header(theme, site_name, '')}{plain_body}\n\n--\n{text_mod.wrap(reason)}\n\n{site_name} - {site_url}\n"
    return RenderedEmail(subject=subject, html=html, text=plain)
