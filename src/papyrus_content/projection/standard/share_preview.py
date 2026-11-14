"""The head inputs of a Story's page, resolved in one place: what the page says about itself in search and in a share card.

The projector builds an item page's ``PageHead`` here, and the lens checks (``lens_evidence.py``) call the same function, so the preview the
checks judge is the one Papyrus emits. Nothing is rendered: the caller gives the opening paragraph and the first body picture it found.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import StandardSettings
from .entries import StandardEntry, first_text
from .head import PageHead
from .urls import UrlPolicy

#: Front matter field for the description of the Story's own picture (``og:image:alt``, ``twitter:image:alt``).
IMAGE_ALT_FIELD = "imageAlt"

#: Where the description came from: the Story's summary, the first paragraph, or (the weakest) the site-wide description.
DESCRIPTION_SOURCES = ("summary", "opening", "site", "none")
#: Where the picture came from: the Story's front matter, its first body picture, or the site's default picture.
IMAGE_SOURCES = ("front_matter", "body", "site_default", "none")


@dataclass(frozen=True)
class SharePreview:
    head: PageHead
    description_source: str
    image_source: str


def json_ld_type_of(standard: StandardSettings, entry: StandardEntry) -> str:
    mapping = dict(standard.seo.json_ld_types)
    return mapping.get(entry.topic) or mapping.get(entry.type) or standard.seo.default_json_ld


def breadcrumbs_of(standard: StandardSettings, policy: UrlPolicy, entry: StandardEntry) -> tuple[tuple[str, str], ...]:
    if not standard.breadcrumbs:
        return ()
    crumbs = [(standard.home_link_label, policy.path("/"))]
    if entry.section is not None and entry.section.listing and entry.section.listing_page:
        crumbs.append((entry.section.label, policy.path(f"/{entry.section.base}/")))
    crumbs.append((entry.title, entry.url))
    return tuple(crumbs) if len(crumbs) > 1 else ()


def based_on_of(standard: StandardSettings, entry: StandardEntry) -> str:
    """The original the page is based on: the URL in ``seo.isBasedOnField``, only when it is an absolute http(s) URL."""
    field = standard.seo.based_on_field
    value = entry.data.get(field) if field else None
    return value.strip() if isinstance(value, str) and value.strip().startswith(("http://", "https://")) else ""


def item_share_preview(entry: StandardEntry, standard: StandardSettings, policy: UrlPolicy, *, opening: str = "", body_image: str | None = None) -> SharePreview:
    """The ``PageHead`` of a Story's page. ``opening`` is the first paragraph's text and ``body_image`` the first picture of the body."""
    if entry.summary_text:
        description, description_source = entry.summary_text, "summary"
    elif opening:
        description, description_source = opening, "opening"
    elif standard.identity.description:
        description, description_source = standard.identity.description, "site"
    else:
        description, description_source = "", "none"
    image = entry.image or body_image
    image_source = "front_matter" if entry.image else "body" if body_image else "site_default" if standard.seo.default_image else "none"
    article = entry.type in standard.listings.types or entry.type in standard.seo.article_types
    head = PageHead(
        title=entry.title,
        path=entry.url,
        description=description,
        og_type="article" if article else "website",
        image=image,
        image_alt=first_text(entry.data, (IMAGE_ALT_FIELD,)) if image else "",
        canonical=entry.canonical,
        published=entry.date,
        modified=entry.updated,
        authors=entry.author_details,
        tags=entry.tags,
        noindex=entry.noindex,
        based_on=based_on_of(standard, entry),
        json_ld_type=json_ld_type_of(standard, entry) if article else None,
        breadcrumbs=breadcrumbs_of(standard, policy, entry),
    )
    return SharePreview(head, description_source, image_source)
