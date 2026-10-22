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


def _head(subject: str, theme: EmailTheme) -> str:
    return f"""<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="light dark" />
<meta name="supported-color-schemes" content="light dark" />
<title>{escape(subject)}</title>
<style type="text/css">
@media only screen and (max-width: 620px) {{
  .em-container {{ width: 100% !important; }}
  .em-pad {{ padding-left: 16px !important; padding-right: 16px !important; }}
}}
@media (prefers-color-scheme: dark) {{
  .em-bg {{ background-color: #111111 !important; }}
  .em-card {{ background-color: #1c1c1c !important; }}
  .em-card p, .em-card li, .em-card h1, .em-card h2, .em-card h3, .em-card h4, .em-card h5, .em-card h6, .em-card td, .em-card th {{ color: #eeeeee !important; }}
  .em-muted, .em-muted a {{ color: #bbbbbb !important; }}
  .em-card a {{ color: #9ec5ff !important; }}
  .em-card pre, .em-card .em-callout {{ background-color: #2a2a2a !important; color: #eeeeee !important; }}
}}
</style>
</head>"""


def _shell(*, subject: str, preheader: str, theme: EmailTheme, site_url: str, site_name: str, content: str, footer: str) -> str:
    logo = absolute_url(theme.logo_url or "", site_url, schemes=frozenset({"http", "https"}))
    home = escape(site_url)
    if logo:
        brand = (
            f'<a href="{home}" style="text-decoration:none;"><img src="{escape(logo)}" alt="{escape(site_name)}" '
            f'style="display:block;max-width:100%;max-height:60px;height:auto;border:0;" /></a>'
        )
    else:
        brand = (
            f'<a href="{home}" style="font-family:{theme.font_family};font-size:22px;font-weight:bold;'
            f'color:{theme.accent};text-decoration:none;">{escape(site_name)}</a>'
        )
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
<tr><td class="em-pad" style="padding:0 32px 16px 32px;">{brand}</td></tr>
<tr><td class="em-card em-pad" bgcolor="{theme.surface}" style="background-color:{theme.surface};padding:24px 32px 12px 32px;">
{content}
</td></tr>
<tr><td class="em-pad em-muted" style="padding:20px 32px 0 32px;font-family:{theme.font_family};font-size:13px;line-height:1.5;color:{theme.muted};">
{footer}
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>
"""


def _button(url: str, label: str, theme: EmailTheme) -> str:
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


def render_issue(
    *,
    subject: str,
    markus: str,
    theme: EmailTheme,
    footer: EmailFooter,
    preheader: str = "",
    site_url: str,
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
    html = _shell(
        subject=subject, preheader=preheader, theme=theme, site_url=site_url,
        site_name=footer.site_name, content=html_body, footer=footer_html,
    )
    address_text = "\n".join(line.strip() for line in address.splitlines() if line.strip())
    plain = (
        f"{plain_body}\n\n--\n"
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
    html = _shell(
        subject=subject, preheader=preheader, theme=theme, site_url=site_url,
        site_name=site_name, content=html_body, footer=footer_html,
    )
    plain = f"{plain_body}\n\n--\n{text_mod.wrap(reason)}\n\n{site_name} - {site_url}\n"
    return RenderedEmail(subject=subject, html=html, text=plain)
