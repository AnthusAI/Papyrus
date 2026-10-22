"""The four calls the sender needs from the unsubscribe and suppression story (PPY-b5a699), bound to one store and key set.

``links.make_manage_token`` / ``links.manage_urls``, ``suppression.is_suppressed`` and ``pause.is_paused`` read the environment
unless given a store or keys; the sending code holds both and passes them, which also keeps its tests free of the environment.
"""

from __future__ import annotations

from . import links, pause, suppression
from .keys import Keys
from .store import Store


class Compliance:
    def __init__(self, *, store: Store, keys: Keys, site_origin: str) -> None:
        self.store = store
        self.keys = keys
        self.site_origin = site_origin.rstrip("/")

    def make_manage_token(self, hid: str) -> str:
        return links.make_manage_token(hid, self.keys)

    def manage_urls(self, hid: str, list_id: str | None = None) -> dict[str, str]:
        """``{"manage_url", "unsubscribe_url"}``; the unsubscribe URL names the list when ``list_id`` is given."""
        return links.manage_urls(hid, list_id, self.keys, self.site_origin)

    def is_suppressed(self, hid: str) -> bool:
        return suppression.is_suppressed(hid, self.store)

    def is_paused(self) -> bool:
        return pause.is_paused(self.store)
