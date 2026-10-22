"""Links the sender puts in every message: ``make_manage_token(hid)`` and ``manage_urls(hid, list_id=None)``.

People only ever get clean site URLs (``<origin><base>/newsletter/preferences/?token=...``); ``/api/newsletter/*`` is for machines. The one
machine URL in a message is ``one_click_url``, which goes in the List-Unsubscribe header for RFC 8058 one-click unsubscribe and never in a
body. ``base`` is the site's ``urls.basePath`` (empty at the root).

Both read the site's key parameter (``KEY_PARAMETER``), public origin (``SITE_ORIGIN``) and base path (``SITE_BASE_PATH``) from the Lambda
environment unless given ``keys``, ``site_origin`` and ``base_path``. A manage token has no expiry and stops working when the subscriber
is deleted.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from . import tokens
from .keys import Keys, load_keys

PAGE_PATH = "/newsletter/{page}/"
ONE_CLICK_PATH = "/api/newsletter/unsubscribe"


def _base(base_path: str) -> str:
    return f"/{base_path.strip('/')}" if base_path.strip("/") else ""


def home_url(site_origin: str, base_path: str = "") -> str:
    """The site's home, under its base path: ``https://example.com/posts/``."""
    return f"{site_origin.rstrip('/')}{_base(base_path)}/"


def page_url(site_origin: str, base_path: str, page: str, query: str = "") -> str:
    """The clean URL of one of the plugin's pages, such as ``https://example.com/posts/newsletter/confirm/?token=...``."""
    return f"{site_origin.rstrip('/')}{_base(base_path)}{PAGE_PATH.format(page=page)}" + (f"?{query}" if query else "")


def make_manage_token(hid: str, keys: Keys | None = None) -> str:
    keys = keys or load_keys(os.environ["KEY_PARAMETER"])
    return tokens.issue(keys.token, tokens.Claims(hid=hid, purpose="manage"))


def manage_urls(
    hid: str, list_id: str | None = None, keys: Keys | None = None, site_origin: str | None = None, base_path: str | None = None
) -> dict[str, str]:
    """``{"manage_url", "unsubscribe_url", "one_click_url"}``; the unsubscribe URLs name the list when ``list_id`` is given.

    ``manage_url`` and ``unsubscribe_url`` are pages for people. ``one_click_url`` is the POST target of the List-Unsubscribe header.
    """
    origin = (site_origin or os.environ["SITE_ORIGIN"]).rstrip("/")
    base = os.environ.get("SITE_BASE_PATH", "") if base_path is None else base_path
    token = make_manage_token(hid, keys)
    listed = f"&list={quote(list_id, safe='')}" if list_id else ""
    return {
        "manage_url": page_url(origin, base, "preferences", f"token={token}"),
        "unsubscribe_url": page_url(origin, base, "unsubscribe", f"token={token}{listed}"),
        "one_click_url": f"{origin}{ONE_CLICK_PATH}?t={token}" + (f"&l={quote(list_id, safe='')}" if list_id else ""),
    }
