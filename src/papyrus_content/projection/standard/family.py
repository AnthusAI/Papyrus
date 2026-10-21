"""The Anthus family footer, rendered as static HTML in the structure of the npm package ``anthus-footer``.

The registry (``anthus_sites.json``) is the package's ``src/sites.js``; the package is its other consumer. Like the
package, the Anthus column lists the company links and the platform column lists every ``live`` site that is shown in
the footer, current site included.
"""

from __future__ import annotations

import json
from pathlib import Path

from .components import esc
from .config import FamilyFooter, FooterColumn

REGISTRY = json.loads((Path(__file__).parent / "anthus_sites.json").read_text(encoding="utf-8"))
DEFAULT_TAGLINE = "Part of the Anthus Platform"
DEFAULT_DESCRIPTION = "Anthus builds AI-native systems with durable procedures, operational guardrails, and reusable platform components."
DEFAULT_BYLINE = "Built by Anthus AI Solutions"
OPEN_SOURCE_NOTE = "Free and open-source Anthus platform components where applicable"


def brand_links() -> list[tuple[str, str]]:
    sites = REGISTRY["sites"]
    return [(sites[key]["label"], sites[key]["href"]) for key in REGISTRY["anthusLinkSiteIds"] if sites[key]["href"] and sites[key]["showInFooter"]]


def platform_links() -> list[tuple[str, str]]:
    sites = REGISTRY["sites"]
    return [
        (sites[key]["label"], sites[key]["href"]) for key in REGISTRY["platformSiteIds"]
        if sites[key]["href"] and sites[key]["showInFooter"] and sites[key]["status"] == "live"
    ]


def _link(label: str, href: str, *, external: bool) -> str:
    attributes = ' target="_blank" rel="noreferrer"' if external else ""
    return f'<a href="{esc(href)}"{attributes}>{esc(label)}</a>'


def _column(title: str, links: list[str]) -> str:
    items = "".join(f"<li>{link}</li>" for link in links)
    return f'<div class="papyrus-family-footer-column"><h3 class="papyrus-family-footer-heading">{esc(title)}</h3><ul>{items}</ul></div>'


def family_footer(family: FamilyFooter, site_name: str, text: str, columns: tuple[FooterColumn, ...]) -> str:
    """The inside of the footer element. ``text`` (``footer.text``) is the description when the family sets none."""
    registered = REGISTRY["sites"].get(family.site_id) or {}
    name = family.name or registered.get("label") or site_name
    community = '<span aria-hidden="true">·</span>'.join(_link(link["label"], link["href"], external=True) for link in REGISTRY["communityLinks"])
    own = [
        _column(column.title, [_link(link.label, link.href, external=link.external) for link in column.links])
        for column in columns
    ]
    anthus = _column("Anthus", [_link(label, href, external=False) for label, href in brand_links()])
    platform = _column("Anthus Platform", [_link(label, href, external=False) for label, href in platform_links()])
    return (
        '<div class="papyrus-family-footer"><div class="papyrus-family-footer-shell">'
        f'<div class="papyrus-family-footer-community">{community}</div>'
        '<div class="papyrus-family-footer-grid">'
        '<div class="papyrus-family-footer-brand">'
        f'<span class="papyrus-family-footer-eyebrow">{esc(family.tagline or DEFAULT_TAGLINE)}</span>'
        f'<h2 class="papyrus-family-footer-heading">{esc(name)}</h2>'
        f'<p>{esc(family.description or text or DEFAULT_DESCRIPTION)}</p></div>'
        f"{anthus}{platform}{''.join(own)}</div>"
        f'<div class="papyrus-family-footer-bottom"><span>{esc(family.byline or DEFAULT_BYLINE)}</span><span>{esc(OPEN_SOURCE_NOTE)}</span></div>'
        "</div></div>"
    )
