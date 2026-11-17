"""Accessible default components. Each is a pure function returning markup; a site restyles them with CSS or replaces one with a hook."""

from __future__ import annotations

import datetime as dt
import html

from babel import Locale
from babel.dates import format_date

from .config import FooterColumn, NavLink
from .entries import StandardEntry
from .editions import hreflang_value
from .interface_strings import SKIP_LINK_KEY


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


SKIP_LINK_DEFAULT = "Skip to main content"


def skip_link(target: str = "main", strings=None) -> str:
    """The link that jumps to the page's main content. Its words are the page's language's interface string ``skipToMain``; a site that writes no interface
    strings (one language) gets the engine's English."""
    label = (strings or {}).get(SKIP_LINK_KEY) or SKIP_LINK_DEFAULT
    return f'<a class="markus-skip-link" href="#{esc(target)}">{esc(label)}</a>'


def shown_date(date: str, date_format: str = "", locale: str = "") -> str:
    """The text of a date: ISO as stored; ``date_format`` (``site.dateFormat``) for a calendar date; or, on a language edition, the language's own long date
    format (``locale`` is its BCP 47 tag: ``15 de noviembre de 2026`` for ``es-419``, ``2026年11月15日`` for ``zh-Hans``), which takes the place of ``date_format``,
    whose month names are one language's."""
    if not date or not (date_format or locale):
        return date
    try:
        day = dt.date.fromisoformat(date[:10])
    except ValueError:
        return date
    return format_date(day, format="long", locale=Locale.parse(locale, sep="-")) if locale else day.strftime(date_format)


def time_tag(date: str, *, class_name: str = "markus-time", date_format: str = "", locale: str = "") -> str:
    return f'<time class="{esc(class_name)}" datetime="{esc(date)}">{esc(shown_date(date, date_format, locale))}</time>' if date else ""


def byline(entry: StandardEntry, date_format: str = "", text: str | None = None, locale: str = "") -> str:
    """The byline; ``text`` is a site hook's complete byline, shown instead of the linked author names (``None``: no hook; an empty string: no byline)."""
    parts = []
    if text is not None:   # a site hook's empty string says this item has no byline: the authors are not a fallback
        if text:
            parts.append(f'<span class="markus-byline-authors">{esc(text)}</span>')
    elif entry.author_details:
        names = ", ".join(
            f'<a href="{esc(author.url)}">{esc(author.name)}</a>' if author.url else esc(author.name) for author in entry.author_details
        )
        parts.append(f'<span class="markus-byline-authors">{names}</span>')
    if entry.date:
        parts.append(time_tag(entry.date, date_format=date_format, locale=locale))
    return f'<p class="markus-byline">{" · ".join(parts)}</p>' if parts else ""


def translation_notice(strings, original: dict) -> str:
    """The line under the byline of a translated page, in the page's language from its interface strings: who translated it and a link to the original.
    ``original`` is ``{tag, url, kind, writtenBy}``: the page it was translated from, the translation's kind and, for an ``imported`` one, the name of the
    person or agent who wrote the copy. A machine translation says an AI translated it (``translation.label``); an imported one says who wrote it
    (``translation.importedLabel``) and never claims AI. The line is data the page is given, never part of the Story's text."""
    from ...item_language import IMPORTED_TRANSLATION, MACHINE_TRANSLATION
    from .interface_strings import AUTHOR_PLACEHOLDER, ORIGINAL_PLACEHOLDER, TRANSLATION_IMPORTED_LABEL_KEY, TRANSLATION_LABEL_KEY, TRANSLATION_ORIGINAL_KEY

    kind = original.get("kind") or MACHINE_TRANSLATION
    if kind == IMPORTED_TRANSLATION:
        label_key, author = TRANSLATION_IMPORTED_LABEL_KEY, original.get("writtenBy")
        if not author:
            raise ValueError("An imported translation's notice needs the name of its writer.")
        if label_key not in strings or not strings[label_key].strip():
            raise ValueError(f"The language has no {label_key}: a page of an imported translation must say who wrote it, so its interface strings need it.")
        if AUTHOR_PLACEHOLDER not in strings[label_key]:
            raise ValueError(f"{label_key} must contain {AUTHOR_PLACEHOLDER}, where the writer's name goes.")
    elif kind == MACHINE_TRANSLATION:
        label_key, author = TRANSLATION_LABEL_KEY, None
    else:
        raise ValueError(f"A translation's kind is {MACHINE_TRANSLATION!r} or {IMPORTED_TRANSLATION!r}, not {kind!r}.")
    before, found, after = strings[label_key].partition(ORIGINAL_PLACEHOLDER)
    if not found:
        raise ValueError(f"{label_key} must contain {ORIGINAL_PLACEHOLDER}, where the link to the original goes.")
    if author is not None:
        before, after = (part.replace(AUTHOR_PLACEHOLDER, author) for part in (before, after))   # the name is text, escaped below with the rest
    link = f'<a href="{esc(original["url"])}" hreflang="{esc(hreflang_value(original["tag"]))}">{esc(strings[TRANSLATION_ORIGINAL_KEY])}</a>'
    return f'<p class="markus-translation">{esc(before)}{link}{esc(after)}</p>'


def untranslated_notice(strings, original: dict) -> str:
    """The line on a language's home or listing that has no Story yet: it says so in the page's language and links to the same listing in the original
    language. ``original`` is ``{tag, url}`` of that page. The page is not indexed (``noindex``) until it lists something."""
    from .interface_strings import ORIGINAL_PLACEHOLDER, UNTRANSLATED_LABEL_KEY, UNTRANSLATED_ORIGINAL_KEY

    before, found, after = strings[UNTRANSLATED_LABEL_KEY].partition(ORIGINAL_PLACEHOLDER)
    if not found:
        raise ValueError(f"{UNTRANSLATED_LABEL_KEY} must contain {ORIGINAL_PLACEHOLDER}, where the link to the original language's page goes.")
    link = f'<a href="{esc(original["url"])}" hreflang="{esc(hreflang_value(original["tag"]))}">{esc(strings[UNTRANSLATED_ORIGINAL_KEY])}</a>'
    return f'<p class="markus-untranslated" role="note">{esc(before)}{link}{esc(after)}</p>'


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
    site_name: str, links: tuple[NavLink, ...], current_path: str, *, tagline: str = "", disclosure: bool = False, brand_html: str = "", home: str = "/",
    switcher: str = "",
) -> str:
    tag = f'\n    <p class="markus-site-tagline">{esc(tagline)}</p>' if tagline else ""
    switcher = f"\n    {switcher}" if switcher else ""
    brand = (
        f'<a href="{esc(home)}" aria-label="{esc(site_name)}, home">{brand_html}</a>' if brand_html else f'<a href="{esc(home)}">{esc(site_name)}</a>'
    )
    # A brand the site supplies may hold block elements (a lockup of paragraphs), which a <p> cannot contain.
    wordmark = "div" if brand_html else "p"
    return (
        '  <header class="markus-site-masthead">\n'
        f'    <{wordmark} class="markus-site-wordmark">{brand}</{wordmark}>{tag}\n'
        f"    {nav(links, current_path, disclosure=disclosure)}{switcher}\n"
        "  </header>"
    )


# Lucide icons (lucide.dev, ISC licence) on the 24 px grid, drawn in currentColor.
_LUCIDE = (
    '<svg class="markus-language-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" data-icon="{name}">{body}</svg>'
)
LANGUAGES_ICON = _LUCIDE.format(
    name="languages",
    body='<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
)
CHEVRON_DOWN_ICON = _LUCIDE.format(name="chevron-down", body='<path d="m6 9 6 6 6-6"/>')
CHECK_ICON = _LUCIDE.format(name="check", body='<path d="M20 6 9 17l-5-5"/>')


def language_switcher(alternates, current_tag: str, label: str, *, prominence: str = "normal") -> str:
    """The language switcher: the Languages icon and the current language's own name open the list of the page's languages (``page.alternates``), each in
    its own name with its own ``lang``. A ``details`` element, so it opens and closes from the keyboard with no script (Enter or Space on the control; a
    link is a Tab stop); ``papyrus-language-switcher.js`` adds Escape and a click outside to close it. The current language is marked by a check mark,
    ``aria-current`` and its place as the control's text, never by colour alone. ``label`` is the word "Language" in the page's language; the control's accessible
    name is "<label>: <current name>". ``prominence`` is ``normal`` (a filled control) or ``quiet`` (the icon and the name in muted text). Nothing is drawn for a
    page that exists in one language."""
    current = next((alternate for alternate in alternates if alternate["tag"] == current_tag), None)
    if current is None or len(alternates) < 2:
        return ""
    options = "".join(
        f'<li><a class="markus-language-option" href="{esc(alternate["url"])}" lang="{esc(alternate["tag"])}" hreflang="{esc(alternate["hreflang"])}" '
        f'data-language="{esc(alternate["tag"])}"{" aria-current=\"true\"" if alternate["tag"] == current_tag else ""}>'
        f'<span class="markus-language-name">{esc(alternate["name"])}</span>{CHECK_ICON if alternate["tag"] == current_tag else ""}</a></li>'
        for alternate in alternates
    )
    quiet = " markus-language-switcher-quiet" if prominence == "quiet" else ""
    return (
        f'<div class="markus-language-switcher{quiet}" data-language-switcher><details class="markus-language-details">'
        f'<summary class="markus-language-trigger" aria-label="{esc(label)}: {esc(current["name"])}">{LANGUAGES_ICON}'
        f'<span class="markus-language-current">{esc(current["name"])}</span>{CHEVRON_DOWN_ICON}</summary>'
        f'<ul class="markus-language-list">{options}</ul></details></div>'
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


def card_image(entry: StandardEntry) -> str:
    """The card's picture. With a Night version it is a Day and a Night ``<img>``, each in a ``display:contents`` span (the site's own rules for ``.markus-card-image`` still apply); ``markus-components.css`` shows one by theme (the hidden span is ``display:none``, so a browser does not fetch its image)."""
    if not entry.image:
        return ""
    if not entry.image_dark:
        return f'<img class="markus-card-image" src="{esc(entry.image)}" alt="" loading="lazy">'

    def picture(source: str, theme: str) -> str:
        return f'<span class="markus-card-image-{theme}"><img class="markus-card-image" src="{esc(source)}" alt="" loading="lazy"></span>'

    return picture(entry.image, "day") + picture(entry.image_dark, "night")


def card(entry: StandardEntry, *, heading_level: int = 2, date_format: str = "", locale: str = "") -> str:
    level = f"h{heading_level}"
    image = card_image(entry)
    href = entry.url or entry.link or "#"
    summary = f'<p class="markus-card-summary">{esc(entry.summary_text)}</p>' if entry.summary_text else ""
    meta = byline(entry, date_format, locale=locale)
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


ARROW_RIGHT_ICON = (
    '<svg class="markus-section-icon" data-icon="arrow-right" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>'
)


def section_tabs_html(tabs) -> str:
    """The links between a site's section front pages. The current one is marked for assistive technology and drawn bold and filled, not by colour alone."""
    if len(tabs) < 2:
        return ""
    items = "".join(
        f'<li><a href="{esc(tab.href)}"' + (' aria-current="page" data-current="true"' if tab.current else "") + f">{esc(tab.label)}</a></li>"
        for tab in tabs
    )
    return f'<nav class="markus-section-tabs" aria-label="Sections"><ul>{items}</ul></nav>'


def _more_link(href: str, text: str, relation: str = "") -> str:
    rel = f' rel="{relation}"' if relation else ""
    return f'<p class="markus-section-more"><a{rel} href="{esc(href)}">{esc(text)} {ARROW_RIGHT_ICON}</a></p>'


def section_index_html(view, render_card) -> str:
    """A section's front page: tabs, label, description, a lead Story, the latest entries, an optional Reference grid, then the link to older pages."""
    section = view.section
    description = f'<p class="markus-section-description">{esc(section.description)}</p>' if section.description else ""
    lead = f'<div class="markus-section-lead">{render_card(view.lead)}</div>' if view.lead is not None else ""
    latest = "\n".join(render_card(entry) for entry in view.latest)
    grid = (
        f'<div class="markus-card-grid">{latest}</div>'
        if latest
        else ("" if view.lead is not None else '<p class="markus-section-empty">Nothing is published in this section yet.</p>')
    )
    listing = view.listing
    pager_html = pager(listing.page, listing.pages, listing.url_for_page)
    return (
        f'<div class="markus-document markus-section-index" data-section="{esc(section.name)}">'
        f"{section_tabs_html(view.tabs)}<h1>{esc(section.label)}</h1>{description}{lead}{grid}{view.references_html}{pager_html}</div>"
    )


def home_heading(name: str, description: str, quiet: bool) -> tuple[str, str]:
    """The home page's heading and intro. A quiet home (layout.column single) says the site's name only to assistive technology and has no intro:
    the masthead already says it."""
    if quiet:
        return f'<h1 class="papyrus-visually-hidden">{esc(name)}</h1>', ""
    return f"<h1>{esc(name)}</h1>", (f"<p>{esc(description)}</p>" if description else "")


def home_sections_html(name: str, description: str, blocks, render_card, *, lead: bool, quiet: bool = False) -> str:
    """The home of sections: one block per section with its label, description, newest entries and a link to its index page."""
    heading_html, intro = home_heading(name, description, quiet)
    rendered = []
    for block in blocks:
        section = block.section
        heading = f"section-block-{section.name}"
        about = f'<p class="markus-section-description">{esc(section.description)}</p>' if section.description else ""
        cards = []
        for position, entry in enumerate(block.entries):
            card_html = render_card(entry)
            cards.append(f'<div class="markus-section-lead">{card_html}</div>' if lead and position == 0 else card_html)
        grid = f'<div class="markus-card-grid">{chr(10).join(cards)}</div>' if cards else '<p class="markus-section-empty">Nothing is published in this section yet.</p>'
        rendered.append(
            f'<section class="markus-section-block" data-section="{esc(section.name)}" aria-labelledby="{esc(heading)}">'
            f'<h2 id="{esc(heading)}"><a href="{esc(block.href)}">{esc(section.label)}</a></h2>{about}{grid}'
            f'{_more_link(block.href, "More " + section.label)}</section>'
        )
    return f'<div class="markus-document markus-home-sections">{heading_html}{intro}{"".join(rendered)}</div>'
