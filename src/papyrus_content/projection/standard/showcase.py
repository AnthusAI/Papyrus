"""The showcase (logo wall): a list of sites rendered as an accessible, responsive logo grid.

The data is published content, not markup: each item of the configured section is one site, with front matter
``name`` (or the title), ``logo`` (an image path or URL; text is the fallback), ``logoAlt``, ``url`` (http or https),
``kind`` (one of ``showcase.kinds``) and ``order`` (lower first). Editors manage the collection in the CMS; the wall
re-renders when any item changes.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..model import ItemSummary
from .config import ShowcaseSettings


@dataclass(frozen=True)
class ShowcaseSite:
    name: str
    url: str
    kind: str
    order: int
    logo: str | None = None
    logo_alt: str = ""

    def fingerprint(self) -> list:
        return [self.name, self.url, self.kind, self.order, self.logo, self.logo_alt]


def _order(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1000


def _safe_url(value) -> str | None:
    text = str(value or "").strip()
    return text if urlsplit(text).scheme in ("http", "https") and urlsplit(text).netloc else None


def showcase_sites(summaries, settings: ShowcaseSettings) -> list[ShowcaseSite]:
    """The wall's sites, sorted by order then name; items without a usable name or http(s) URL are skipped."""
    sites = []
    for summary in summaries:
        if summary.section != settings.section:
            continue
        data = summary.front_matter
        name = str(data.get("name") or data.get("title") or "").strip()
        url = _safe_url(data.get("url"))
        if not name or url is None:
            continue
        logo = str(data.get("logo") or "").strip() or None
        sites.append(
            ShowcaseSite(
                name=name, url=url, kind=str(data.get("kind") or "").strip(), order=_order(data.get("order")),
                logo=logo, logo_alt=str(data.get("logoAlt") or "").strip(),
            )
        )
    return sorted(sites, key=lambda site: (site.order, site.name.casefold()))


def logo_wall(sites, settings: ShowcaseSettings) -> str:
    """One heading and one list per kind, in the configured kind order; kinds with no sites are omitted."""
    esc = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    groups = []
    known = {key for key, _label in settings.kinds}
    ordered = [(key, label, [site for site in sites if site.kind == key]) for key, label in settings.kinds]
    ordered.append(("", "More", [site for site in sites if site.kind not in known]))
    for key, label, members in ordered:
        if not members:
            continue
        items = []
        for site in members:
            if site.logo:
                face = f'<img class="markus-logo-image" src="{esc(site.logo)}" alt="{esc(site.logo_alt or site.name)}" loading="lazy">'
            else:
                face = f'<span class="markus-logo-text">{esc(site.name)}</span>'
            items.append(f'<li class="markus-logo"><a href="{esc(site.url)}" rel="noopener">{face}</a></li>')
        heading_id = f"showcase-{esc(key or 'more')}"
        groups.append(
            f'<section class="markus-showcase-group" aria-labelledby="{heading_id}">'
            f'<h2 id="{heading_id}">{esc(label)}</h2><ul class="markus-logo-grid">{"".join(items)}</ul></section>'
        )
    return f'<div class="markus-showcase">{"".join(groups)}</div>'
