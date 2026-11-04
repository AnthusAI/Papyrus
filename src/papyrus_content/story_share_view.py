"""What a share link answers (docs/story-share-links.md): the page, and the pictures that page may load.

Both go through ``resolve_share`` first, so a stranger, a wrong token, an expired or revoked link, another Story and a non-editor on a signed-in link are all stopped in one place.
The page is drawn into the response; this module has no writer and never touches the live site's prefix or bucket.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Callable

from .projection.source import PublishedContentSource
from .story_share_render import (
    SharePage,
    ShareShell,
    is_safe_media_reference,
    public_origin_of,
    render_story_page,
    share_note,
    shape_share_page,
)
from .story_shares import (
    ANONYMOUS,
    ANYONE,
    OK,
    PUBLISHED_NOTICE,
    SIGN_IN,
    SIGNED_IN,
    UNAVAILABLE,
    ShareRefused,
    Viewer,
    record_open,
    resolve_share,
)

MEDIA_ROUTE = "/api/share/{token}/media"
# A warm Lambda keeps the pictures a rendered page asked for, so each picture is not a full render. Keyed by what the page was drawn from, so an edit is a miss.
_PAGE_CACHE: "OrderedDict[tuple, SharePage]" = OrderedDict()
_PAGE_CACHE_SIZE = 32


def shell_for(projector, share: dict, version: dict, token: str) -> ShareShell:
    follows = share.get("versionNumber") is None
    return ShareShell(
        token=token,
        public_origin=public_origin_of(projector),
        media_path=MEDIA_ROUTE.format(token=token),
        note=share_note(int(version.get("versionNumber") or 0) or None, follows, share.get("viewers") == SIGNED_IN),
    )


def _cache_key(version: dict, share: dict, projector) -> tuple:
    return (version.get("id"), version.get("contentHash"), version.get("updatedAt"), share.get("viewers"), share.get("versionNumber"), public_origin_of(projector))


def draw(projector, site, version: dict, share: dict, token: str, *, use_cache: bool = True) -> SharePage:
    key = _cache_key(version, share, projector)
    cached = _PAGE_CACHE.get((token, *key)) if use_cache else None
    if cached is not None:
        return cached
    page = shape_share_page(render_story_page(projector, version, site), shell_for(projector, share, version, token))
    if use_cache:
        _PAGE_CACHE[(token, *key)] = page
        while len(_PAGE_CACHE) > _PAGE_CACHE_SIZE:
            _PAGE_CACHE.popitem(last=False)
    return page


def published_address(projector, published: dict | None) -> str | None:
    """The public address of a published Story, for the notice an ended link shows. None when the Story has no page."""
    origin = public_origin_of(projector)
    if not origin or published is None:
        return None
    from .projection.source import projected_item_from_row

    keys = projector.item_page_paths(projected_item_from_row(published).summary)
    if not keys:
        return None
    path = keys[0]
    if path == "index.html":
        return f"{origin}/"
    return f"{origin}/{path[: -len('index.html')]}" if path.endswith("/index.html") else f"{origin}/{path}"


def view_share(
    client: Any, token: Any, viewer: Viewer, *, projector, now: str | None = None, site_index: Callable[[], Any] | None = None, count_open: bool = True
) -> dict[str, Any]:
    """The answer for a link: ``{"state": "ok", "html": ..., "title": ...}``, or ``unavailable``, ``sign-in`` or ``published`` (with ``address``). Nothing else is ever said."""
    resolution = resolve_share(client, token, viewer, now=now)
    if resolution.state == UNAVAILABLE:
        return {"state": UNAVAILABLE}
    if resolution.state == SIGN_IN:
        return {"state": SIGN_IN}
    if resolution.state == PUBLISHED_NOTICE:
        return {"state": PUBLISHED_NOTICE, "address": published_address(projector, resolution.published)}
    site = site_index() if site_index else PublishedContentSource(client).site_index()
    try:
        page = draw(projector, site, resolution.version, resolution.share, token)
    except ShareRefused:
        return {"state": UNAVAILABLE}
    if count_open:
        record_open(client, resolution.share, now=now)
    return {"state": OK, "html": page.html, "title": page.title}


def view_media(
    client: Any, token: Any, viewer: Viewer, reference: Any, *, projector, now: str | None = None, site_index: Callable[[], Any] | None = None
) -> dict[str, Any]:
    """Where one picture of a shared page is. Only a picture the link's own page asked for (exactly as written), of the version the link shows, is answered; anything else is ``unavailable``.

    ``{"state": "ok", "source": "site", "url": ...}`` is on the public site (a rendition), ``{"source": "media", "storagePath": ...}`` is an original in the media store."""
    gone = {"state": UNAVAILABLE}
    resolution = resolve_share(client, token, viewer, now=now)
    if resolution.state != OK or not isinstance(reference, str) or not _plausible_reference(reference, public_origin_of(projector)):
        return gone
    site = site_index() if site_index else PublishedContentSource(client).site_index()
    try:
        page = draw(projector, site, resolution.version, resolution.share, token)
    except ShareRefused:
        return gone
    if reference not in page.images:
        return gone
    origin = public_origin_of(projector)
    path = reference.split("#", 1)[0]
    if origin and path.startswith(origin + "/"):
        path = path[len(origin):]
    if path.startswith("/"):
        if not origin or ".." in path.split("?", 1)[0].split("/"):
            return gone
        return {"state": OK, "source": "site", "url": origin + path}
    return _original(client, resolution.version, path) or gone


def _plausible_reference(reference: str, origin: str | None) -> bool:
    """Before anything is drawn: a picture address that is a path, or an address on the site's own origin, with no parent segments or control characters."""
    if origin and reference.startswith(origin + "/"):
        reference = reference[len(origin):]
    return is_safe_media_reference(reference)


def _original(client: Any, version: dict, path: str) -> dict[str, Any] | None:
    """A picture the Story's own version uploaded (``assets/<story>/<file>``), found among that version's MediaAsset rows and no others."""
    wanted = path.split("?", 1)[0]
    for asset in client.list_by_index("mediaAssetsByItemAndSortKey", version["id"]):
        metadata = asset.get("metadata")
        metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
        stored = str(asset.get("storagePath") or "")
        if (metadata.get("srcPath") == wanted or stored == f"media/{wanted}") and stored.startswith("media/") and ".." not in stored.split("/"):
            return {"state": OK, "source": "media", "storagePath": stored}
    return None


def check_shareable(client: Any, lineage_id: str, version_number: int | None, *, projector, site_index: Callable[[], Any] | None = None) -> None:
    """Draws the page once without a link, so a Story the public site cannot show is refused when the link is made, with the reason, not when someone opens it."""
    from .story_shares import shown_version

    version = shown_version(client, lineage_id, version_number)
    if version is None:
        raise ShareRefused("That version was not found.")
    if not public_origin_of(projector):
        raise ShareRefused("This site has no public address set (PAPYRUS_SITE_PUBLIC_URL), so a shared page cannot point at its stylesheets and pictures.")
    site = site_index() if site_index else PublishedContentSource(client).site_index()
    draw(projector, site, version, {"viewers": ANYONE, "versionNumber": version_number}, "x" * 43, use_cache=False)


__all__ = ["ANONYMOUS", "check_shareable", "view_media", "view_share"]
