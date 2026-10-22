"""Stand-ins for what story PPY-b5a699 (unsubscribe, preferences, suppression) exports.

That story owns ``make_manage_token(hid)``, ``manage_urls(hid, list_id=None)``, ``is_suppressed(hid)`` and ``is_paused()``
(its modules ``links``, ``suppression`` and ``pause``). Until it merges, this thin class gives the sending code the same
four calls, bound to the store and keys the sending code already holds, and builds the same URLs: a list-less manage
token, with the list named by ``&l=`` on the unsubscribe URL. When it merges, delegate the bodies to those modules and
delete the duplicated logic. Reads the same ``STATE`` / ``SITE`` row (``paused``) and ``SUPP#<hid>`` row.
"""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import quote

from . import tokens
from .keys import Keys
from .store import Store, _ser

UNSUBSCRIBE_PATH = "/api/newsletter/unsubscribe"
PREFERENCES_PATH = "/api/newsletter/preferences"


class Compliance:
    def __init__(self, *, store: Store, keys: Keys, site_origin: str, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.keys = keys
        self.site_origin = site_origin.rstrip("/")
        self.clock = clock

    def make_manage_token(self, hid: str) -> str:
        return tokens.issue(self.keys.token, tokens.Claims(hid=hid, purpose="manage"))

    def manage_urls(self, hid: str, list_id: str | None = None) -> dict[str, str]:
        """``{"manage_url", "unsubscribe_url"}``; the unsubscribe URL names the list when ``list_id`` is given."""
        token = self.make_manage_token(hid)
        unsubscribe = f"{self.site_origin}{UNSUBSCRIBE_PATH}?t={token}" + (f"&l={quote(list_id, safe='')}" if list_id else "")
        return {"manage_url": f"{self.site_origin}{PREFERENCES_PATH}?t={token}", "unsubscribe_url": unsubscribe}

    def is_suppressed(self, hid: str) -> bool:
        return self.store.is_suppressed(hid)

    def is_paused(self) -> bool:
        response: Any = self.store.client.get_item(
            TableName=self.store.table_name, Key=_ser({"pk": "STATE", "sk": "SITE"}), ConsistentRead=True
        )
        item = response.get("Item")
        return bool(item and item.get("paused", {}).get("BOOL"))
