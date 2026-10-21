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
    def __init__(self, settings: StandardSettings) -> None:
        self.settings = settings

    def item_key(self, section: SectionConfig | None, slug: str) -> str:
        base = f"{section.base}/" if section is not None and section.base else ""
        if self.settings.url_style == "directory":
            return f"{base}{slug}/index.html"
        return f"{base}{slug}.html"

    @staticmethod
    def listing_key(base: str, page: int = 1) -> str:
        """``base/index.html`` for page 1, ``base/page/N/index.html`` after it; ``base`` may be empty (the root)."""
        prefix = f"{base}/" if base else ""
        return f"{prefix}index.html" if page == 1 else f"{prefix}page/{page}/index.html"

    def tag_base(self, tag_slug: str | None = None) -> str:
        base = self.settings.listings.tag_base
        return f"{base}/{tag_slug}" if tag_slug else base

    @staticmethod
    def url_for_key(key: str) -> str:
        return request_paths_for_key(key)[0]

    def absolute(self, origin: str | None, key_or_path: str) -> str | None:
        if origin is None:
            return None
        path = key_or_path if key_or_path.startswith("/") else self.url_for_key(key_or_path)
        return origin.rstrip("/") + path
