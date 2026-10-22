"""Links the sender puts in every message: ``make_manage_token(hid)`` and ``manage_urls(hid, list_id=None)``.

Both read the site's key parameter (``KEY_PARAMETER``) and public origin (``SITE_ORIGIN``) from the Lambda environment
unless given ``keys`` and ``site_origin``. A manage token has no expiry and stops working when the subscriber is deleted.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from . import tokens
from .keys import Keys, load_keys

PREFERENCES_PATH = "/api/newsletter/preferences"
UNSUBSCRIBE_PATH = "/api/newsletter/unsubscribe"


def make_manage_token(hid: str, keys: Keys | None = None) -> str:
    keys = keys or load_keys(os.environ["KEY_PARAMETER"])
    return tokens.issue(keys.token, tokens.Claims(hid=hid, purpose="manage"))


def manage_urls(hid: str, list_id: str | None = None, keys: Keys | None = None, site_origin: str | None = None) -> dict[str, str]:
    """``{"manage_url": ..., "unsubscribe_url": ...}``; the unsubscribe URL names the list when ``list_id`` is given."""
    origin = (site_origin or os.environ["SITE_ORIGIN"]).rstrip("/")
    token = make_manage_token(hid, keys)
    unsubscribe = f"{origin}{UNSUBSCRIBE_PATH}?t={token}" + (f"&l={quote(list_id, safe='')}" if list_id else "")
    return {"manage_url": f"{origin}{PREFERENCES_PATH}?t={token}", "unsubscribe_url": unsubscribe}
