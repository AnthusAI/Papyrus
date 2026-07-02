from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .env import load_dotenv
from .papyrus_config import resolve_reader_cache_revalidate_secret, resolve_reader_revalidation_base_url


def trigger_reader_cache_revalidation(
    *,
    edition_date: str,
    article_slugs: list[str] | None = None,
    item_slugs: list[str] | None = None,
) -> dict[str, Any] | None:
    load_dotenv()
    base_url = resolve_reader_revalidation_base_url()
    secret = resolve_reader_cache_revalidate_secret() or ""
    if not base_url or not secret:
        return None

    payload = {
        "editionDate": edition_date,
        "articleSlugs": article_slugs or [],
        "itemSlugs": item_slugs or article_slugs or [],
    }
    request = urllib.request.Request(
        f"{base_url}/api/revalidate",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-papyrus-revalidate-secret": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {"ok": True}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Reader cache revalidation failed ({error.code}): {detail}") from error
