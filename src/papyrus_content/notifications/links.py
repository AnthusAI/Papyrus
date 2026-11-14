"""The site's own pages and its one-click endpoint, for Caducus's public audience.

People open pages under ``<base>/notifications/``; only the RFC 8058 one-click URL, in the ``List-Unsubscribe`` header, is a
machine address (``/api/notifications/unsubscribe`` at the host root, like the other machine routes). Links carry a token,
never an address.
"""

from __future__ import annotations

from urllib.parse import urlencode

from caducus.notify.audience import LinkBuilder

from .settings import Settings


class SiteLinks(LinkBuilder):
    def __init__(self, settings: Settings):
        self._origin = settings.site_origin.rstrip("/")
        self._base = f"/{settings.base_path.strip('/')}" if settings.base_path.strip("/") else ""

    def _page(self, page: str, **query: str | None) -> str:
        kept = {name: value for name, value in query.items() if value}
        return f"{self._origin}{self._base}/notifications/{page}/?{urlencode(kept)}"

    def confirm_page(self, token: str) -> str:
        return self._page("confirm", token=token)

    def preferences_page(self, token: str) -> str:
        return self._page("preferences", token=token)

    def unsubscribe_page(self, token: str, list_id: str | None) -> str:
        return self._page("unsubscribe", token=token, list=list_id)

    def one_click(self, token: str, list_id: str | None) -> str:
        query = {"t": token, **({"l": list_id} if list_id else {})}
        return f"{self._origin}/api/notifications/unsubscribe?{urlencode(query)}"
