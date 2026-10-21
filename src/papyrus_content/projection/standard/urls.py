"""The URL policy: where a page lives for a given ``urls.style`` and section layout."""

from __future__ import annotations

from ..writers import request_paths_for_key
from .config import SectionConfig, StandardSettings

NOT_FOUND_KEY = "404.html"
HOME_KEY = "index.html"


def slugify_tag(tag: str) -> str:
    out = []
    for character in tag.casefold():
        out.append(character if character.isalnum() else "-")
    return "-".join(part for part in "".join(out).split("-") if part)


class UrlPolicy:
    """Keys and paths of the pages Papyrus generates. With ``urls.basePath`` every one of them lives under it.

    Bases (sections, tags, archives, custom pages) are site-relative; :meth:`key` and :meth:`path` add the base path.
    URLs derived from keys (:meth:`url_for_key`) carry it already. Paths an author writes are not passed through here.
    """

    def __init__(self, settings: StandardSettings) -> None:
        self.settings = settings
        self.root = f"{settings.base_path}/" if settings.base_path else ""

    def key(self, site_key: str) -> str:
        """The object key of a site-relative key: ``index.html`` -> ``posts/index.html``."""
        return self.root + site_key

    def path(self, site_path: str) -> str:
        """The request path of a site-relative path: ``/`` -> ``/posts/``, ``/tags/`` -> ``/posts/tags/``."""
        return "/" + self.root + site_path.lstrip("/")

    def relative_key(self, key: str) -> str | None:
        """The site-relative key of an object key under the base path; ``None`` for a key outside it."""
        return key[len(self.root):] if key.startswith(self.root) else None

    def item_key(self, section: SectionConfig | None, slug: str) -> str:
        base = f"{section.base}/" if section is not None and section.base else ""
        if self.settings.url_style == "directory":
            return self.key(f"{base}{slug}/index.html")
        return self.key(f"{base}{slug}.html")

    def listing_key(self, base: str, page: int = 1) -> str:
        """``base/index.html`` for page 1, ``base/page/N/index.html`` after it; ``base`` may be empty (the root)."""
        prefix = f"{base}/" if base else ""
        return self.key(f"{prefix}index.html" if page == 1 else f"{prefix}page/{page}/index.html")

    def tag_base(self, tag_slug: str | None = None) -> str:
        base = self.settings.listings.tag_base
        return f"{base}/{tag_slug}" if tag_slug else base

    def url_for_key(self, key: str) -> str:
        """The canonical path of a page key. With ``urls.style: clean`` a page ``x.html`` lives at ``/x``."""
        if self.settings.url_style == "clean" and key.endswith(".html") and not key.endswith("index.html"):
            return "/" + key[: -len(".html")]
        return request_paths_for_key(key)[0]

    def key_for_path(self, path: str) -> str:
        """The object key a canonical path is stored under (the inverse of ``url_for_key``)."""
        if path.endswith("/"):
            return path.lstrip("/") + "index.html"
        key = path.lstrip("/")
        return key + ".html" if self.settings.url_style == "clean" and not key.endswith(".html") else key

    def absolute(self, origin: str | None, key_or_path: str) -> str | None:
        if origin is None:
            return None
        path = key_or_path if key_or_path.startswith("/") else self.url_for_key(key_or_path)
        return origin.rstrip("/") + path
