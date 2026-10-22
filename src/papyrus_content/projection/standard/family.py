"""The Anthus family footer, rendered as static HTML in the structure of the npm package ``anthus-footer``.

The registry (``anthus_sites.json``) is data mirrored from the package's ``src/sites.js`` (and its default community
links); the package is the source of truth. Like the package the footer has three parts: the site's own band (name,
description and the site's link columns), the "Made by Anthus AI Solutions" band (the live sites shown in the footer,
grouped as Products, Open source we use and Research, each with its one-line description) and the community links.
Only sites that are ``live`` and shown in the footer appear, in the package's order, the current site included.
"""

from __future__ import annotations

import json
from pathlib import Path

from .components import esc, noopener
from .config import FamilyFooter, FooterColumn

REGISTRY = json.loads((Path(__file__).parent / "anthus_sites.json").read_text(encoding="utf-8"))
DEFAULT_DESCRIPTION = (
    "We build powerful, AI-native solutions backed by durable procedures, rigorous operational guardrails, "
    "and our suite of battle-tested, reusable platform components."
)
GLOBAL_TITLE = "Anthus AI Solutions"
GLOBAL_DESCRIPTION = "Products, the open-source building blocks behind them, and the public research that tests them."
GLOBAL_EYEBROW = "Made by"
DEFAULT_BYLINE = "© Anthus AI Solutions"
COMPANY_SITE = "anthus"


def brand_links() -> list[tuple[str, str]]:
    sites = REGISTRY["sites"]
    return [(sites[key]["label"], sites[key]["href"]) for key in REGISTRY["anthusLinkSiteIds"] if sites[key]["href"] and sites[key]["showInFooter"]]


def footer_groups() -> list[dict]:
    """``[{id, title, links: [{label, href, description}]}]`` for the groups that have live, shown sites."""
    sites = REGISTRY["sites"]
    shown = [
        sites[key] for key in REGISTRY["platformSiteIds"]
        if sites[key]["href"] and sites[key]["showInFooter"] and sites[key]["status"] == "live"
    ]
    groups = []
    for group in REGISTRY["footerGroups"]:
        links = [
            {"label": site["label"], "href": site["href"], "description": site.get("description", "")}
            for site in shown if site.get("footerGroup") == group["id"]
        ]
        if links:
            groups.append({"id": group["id"], "title": group["title"], "links": links})
    return groups


def platform_links() -> list[tuple[str, str]]:
    return [(link["label"], link["href"]) for group in footer_groups() for link in group["links"]]


def _link(label: str, href: str, *, external: bool) -> str:
    attributes = ' target="_blank" rel="noreferrer"' if external else ""
    return f'<a href="{esc(href)}"{attributes}>{esc(label)}</a>'


def _column(title: str, links: list[str]) -> str:
    items = "".join(f"<li>{link}</li>" for link in links)
    return f'<div><h3 class="papyrus-family-footer-column-title">{esc(title)}</h3><ul class="papyrus-family-footer-list">{items}</ul></div>'


def _item(label: str, href: str, description: str, *, external: bool) -> str:
    text = f"<p>{esc(description)}</p>" if description else ""
    return f'<div class="papyrus-family-footer-item">{_link(label, href, external=external)}{text}</div>'


def _community_href(link: dict, family: FamilyFooter) -> str:
    """The registry's contact link points at ``family.contact_url`` when the site sets one; every other link is unchanged."""
    if family.contact_url and link["href"] == REGISTRY["contactUrl"]:
        return family.contact_url
    return link["href"]


def family_footer(family: FamilyFooter, site_name: str, text: str, columns: tuple[FooterColumn, ...]) -> str:
    """The inside of the footer element. ``text`` (``footer.text``) is the description when the family sets none."""
    registered = REGISTRY["sites"].get(family.site_id) or {}
    is_company = family.site_id == COMPANY_SITE
    name = family.name or registered.get("label") or site_name
    own = [
        _column(column.title, [f'<a href="{esc(link.href)}"{noopener(link)}>{esc(link.label)}</a>' for link in column.links])
        for column in columns
    ]
    if is_company:
        own.insert(0, _column("Anthus", [_link(label, href, external=False) for label, href in brand_links()]))
    eyebrow = f'<span class="papyrus-family-footer-eyebrow">{esc(family.tagline)}</span>' if family.tagline else ""
    copy = (
        f'<h2 class="papyrus-family-footer-title">{esc(name)}</h2>'
        f'<p class="papyrus-family-footer-description">{esc(family.description or text or DEFAULT_DESCRIPTION)}</p>'
    )
    if family.logo:
        logo = f'<img class="papyrus-family-footer-logo" src="{esc(family.logo)}" alt="{esc(family.logo_alt)}" width="48" height="48">'
        copy = f'<div class="papyrus-family-footer-intro-row">{logo}<div>{copy}</div></div>'
    local = (
        '<div class="papyrus-family-footer-shell"><div class="papyrus-family-footer-local">'
        f'<div class="papyrus-family-footer-intro">{eyebrow}{copy}</div>'
        f'{"".join(own)}</div></div>'
    )
    groups = "".join(
        f'<div class="papyrus-family-footer-group"><h3 class="papyrus-family-footer-column-title">{esc(group["title"])}</h3>'
        + "".join(_item(link["label"], link["href"], link["description"], external=False) for link in group["links"])
        + "</div>"
        for group in footer_groups()
    )
    company_url = REGISTRY["companyUrl"]
    global_eyebrow = "" if is_company else f'<span class="papyrus-family-footer-eyebrow">{esc(GLOBAL_EYEBROW)}</span>'
    band = (
        '<div class="papyrus-family-footer-band"><div class="papyrus-family-footer-shell"><div class="papyrus-family-footer-section">'
        f'<div>{global_eyebrow}<h2 class="papyrus-family-footer-title"><a href="{esc(company_url)}">{esc(GLOBAL_TITLE)}</a></h2>'
        f'<p class="papyrus-family-footer-description">{esc(GLOBAL_DESCRIPTION)}</p></div>'
        f'<div class="papyrus-family-footer-groups">{groups}</div>'
        f'<div class="papyrus-family-footer-bottom"><a href="{esc(company_url)}">{esc(family.byline or DEFAULT_BYLINE)}</a></div>'
        "</div></div></div>"
    )
    community = "".join(
        _item(link["label"], _community_href(link, family), link.get("description", ""), external=True)
        for link in REGISTRY["communityLinks"]
    )
    return (
        '<div class="papyrus-family-footer">'
        f"{local}{band}"
        f'<div class="papyrus-family-footer-shell"><div class="papyrus-family-footer-community">{community}</div></div>'
        "</div>"
    )
