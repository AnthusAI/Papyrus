"""Accessible default components. Each is a pure function returning markup; a site restyles them with CSS or replaces one with a hook."""

from __future__ import annotations

import datetime as dt
import html

from .config import FooterColumn, NavLink
from .entries import StandardEntry


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def skip_link(target: str = "main", label: str = "Skip to main content") -> str:
    return f'<a class="markus-skip-link" href="#{esc(target)}">{esc(label)}</a>'


def shown_date(date: str, date_format: str = "") -> str:
    """The text of a date: ISO as stored, or ``date_format`` (``site.dateFormat``) for a calendar date."""
    if not (date and date_format):
        return date
    try:
        return dt.date.fromisoformat(date[:10]).strftime(date_format)
    except ValueError:
        return date


def time_tag(date: str, *, class_name: str = "markus-time", date_format: str = "") -> str:
    return f'<time class="{esc(class_name)}" datetime="{esc(date)}">{esc(shown_date(date, date_format))}</time>' if date else ""


def byline(entry: StandardEntry, date_format: str = "") -> str:
    parts = []
    if entry.authors:
        parts.append(f'<span class="markus-byline-authors">{esc(", ".join(entry.authors))}</span>')
    if entry.date:
        parts.append(time_tag(entry.date, date_format=date_format))
    return f'<p class="markus-byline">{" · ".join(parts)}</p>' if parts else ""


def _same_route(href: str, current: str) -> bool:
    return href.rstrip("/") == current.rstrip("/") or (href in ("/", "") and current in ("/", ""))


def noopener(link: NavLink) -> str:
    return ' rel="noopener"' if link.external else ""


def _nav_link(link: NavLink, current_path: str) -> str:
    current = ' aria-current="page"' if _same_route(link.href, current_path) else ""
    cta = ' class="markus-nav-cta"' if link.cta else ""
    return f'<a{cta} href="{esc(link.href)}"{noopener(link)}{current}>{esc(link.label)}</a>'


def nav(links: tuple[NavLink, ...], current_path: str, *, label: str = "Site", disclosure: bool = False) -> str:
    items = []
    for link in links:
        if link.children:
            children = "".join(_nav_link(child, current_path) for child in link.children)
            items.append(
                f'<details class="markus-nav-group"><summary>{esc(link.label)}</summary>'
                f'<div class="markus-nav-group-links">{children}</div></details>'
            )
        else:
            items.append(_nav_link(link, current_path))
    toggle = (
        '<button class="markus-nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>'
        if disclosure
        else ""
    )
    body = "\n      ".join(items)
    return f'{toggle}<nav class="markus-site-nav" id="site-nav" aria-label="{esc(label)}">\n      {body}\n    </nav>'


def masthead(
    site_name: str, links: tuple[NavLink, ...], current_path: str, *, tagline: str = "", disclosure: bool = False, brand_html: str = ""
) -> str:
    tag = f'\n    <p class="markus-site-tagline">{esc(tagline)}</p>' if tagline else ""
    brand = (
        f'<a href="/" aria-label="{esc(site_name)}, home">{brand_html}</a>' if brand_html else f'<a href="/">{esc(site_name)}</a>'
    )
    # A brand the site supplies may hold block elements (a lockup of paragraphs), which a <p> cannot contain.
    wordmark = "div" if brand_html else "p"
    return (
        '  <header class="markus-site-masthead">\n'
        f'    <{wordmark} class="markus-site-wordmark">{brand}</{wordmark}>{tag}\n'
        f"    {nav(links, current_path, disclosure=disclosure)}\n"
        "  </header>"
    )


def breadcrumbs(crumbs: tuple[tuple[str, str], ...]) -> str:
    """``crumbs`` is ``(label, path)``; the last one is the current page and is not a link."""
    if len(crumbs) < 2:
        return ""
    items = []
    for position, (label, path) in enumerate(crumbs):
        if position == len(crumbs) - 1:
            items.append(f'<li aria-current="page">{esc(label)}</li>')
        else:
            items.append(f'<li><a href="{esc(path)}">{esc(label)}</a></li>')
    return f'<nav class="markus-breadcrumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'


def pager(page: int, pages: int, url_for_page) -> str:
    if pages <= 1:
        return ""
    previous = (
        f'<a rel="prev" href="{esc(url_for_page(page - 1))}">Newer</a>' if page > 1 else '<span aria-hidden="true"></span>'
    )
    following = f'<a rel="next" href="{esc(url_for_page(page + 1))}">Older</a>' if page < pages else ""
    return (
        f'<nav class="markus-pager" aria-label="Pagination">{previous}'
        f'<span class="markus-pager-status">Page {page} of {pages}</span>{following}</nav>'
    )


def card(entry: StandardEntry, *, heading_level: int = 2, date_format: str = "") -> str:
    level = f"h{heading_level}"
    image = f'<img class="markus-card-image" src="{esc(entry.image)}" alt="" loading="lazy">' if entry.image else ""
    href = entry.url or entry.link or "#"
    summary = f'<p class="markus-card-summary">{esc(entry.summary_text)}</p>' if entry.summary_text else ""
    meta = byline(entry, date_format)
    return (
        '<article class="markus-card">'
        f"{image}"
        f'<{level} class="markus-card-title"><a href="{esc(href)}">{esc(entry.title)}</a></{level}>'
        f"{meta}{summary}</article>"
    )


def card_list(entries, render_card=None) -> str:
    render = render_card or card
    return '<div class="markus-card-grid">' + "\n".join(render(entry) for entry in entries) + "</div>"


def footer(columns: tuple[FooterColumn, ...], text: str = "") -> str:
    blocks = []
    for column in columns:
        links = "".join(
            f'<li><a href="{esc(link.href)}"{noopener(link)}>{esc(link.label)}</a></li>' for link in column.links
        )
        heading = f'<h2 class="markus-footer-heading">{esc(column.title)}</h2>' if column.title else ""
        blocks.append(f'<div class="markus-footer-column">{heading}<ul>{links}</ul></div>')
    note = f'<p class="markus-footer-text">{esc(text)}</p>' if text else ""
    return "".join(blocks) + note


def tag_list(tags, tag_url) -> str:
    if not tags:
        return ""
    links = "".join(f'<li><a rel="tag" href="{esc(tag_url(tag))}">{esc(tag)}</a></li>' for tag in tags)
    return f'<ul class="markus-tags" aria-label="Tags">{links}</ul>'
