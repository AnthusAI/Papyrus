"""One explicitly requested X search using the dedicated site's existing OAuth connection."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .. import spend_ledger
from ..opportunities import NoRedirects
from ..tenant_context import TenantContextRefusal, build_tenant_context
from . import budget
from .x_account import CONNECTED, AnnouncementError


def authorize(identity: Mapping[str, Any], person: bool) -> None:
    if not person or not identity.get("sub") or identity.get("userArn"):
        raise AnnouncementError("person_only", "An editor or admin must request this search in the newsroom.")
    try:
        tenant = build_tenant_context(identity)
    except TenantContextRefusal:
        raise AnnouncementError("forbidden", "This credential cannot search for this site.") from None
    if tenant.mode != "dedicated" or not tenant.tenant_id:
        raise AnnouncementError("not_configured", "Search needs a dedicated site with a configured tenant and spend ledger.")


def amount(value: Any, label: str) -> Decimal:
    try:
        if not isinstance(value, (int, float, str, Decimal)) or isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or result >= Decimal(10**12) or result.as_tuple().exponent < -6:
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise AnnouncementError("search_price_invalid", f"{label} must be a positive dollar amount with at most six decimal places.") from None


def validated_settings(value: Any) -> dict:
    if value is None:
        return {"enabled": False, "budget": None, "postPrice": None, "userPrice": None}
    if not isinstance(value, dict) or set(value) - {"enabled", "budget", "postPrice", "userPrice"} or not isinstance(value.get("enabled"), bool):
        raise AnnouncementError("search_settings_invalid", "Search settings must specify whether search is enabled.")
    normalized = {"enabled": value["enabled"], "budget": None, "postPrice": None, "userPrice": None}
    for field, label in (("budget", "The search budget"), ("postPrice", "The X post-read price"), ("userPrice", "The X user-read price")):
        if value.get(field) is not None or value["enabled"]:
            normalized[field] = str(amount(value.get(field), label))
    return normalized


def x_page(query: str, count: int, token: str) -> Any:
    params = urlencode({"query": query, "max_results": count, "expansions": "author_id",
                        "user.fields": "protected,withheld", "post.fields": "author_id,conversation_id,created_at,entities,withheld"})
    request = Request(f"https://api.x.com/2/tweets/search/recent?{params}", method="GET",
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with build_opener(NoRedirects()).open(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        error.close()
        raise AnnouncementError("search_refused", f"X returned HTTP {error.code}. No retry was sent.") from None
    except (URLError, OSError, ValueError):
        raise AnnouncementError("search_unreachable", "X search did not return a usable response. No retry was sent.") from None


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9]{1,20}", value))


def public_page(page: Any, count: int) -> tuple[dict, int, int]:
    if not isinstance(page, dict) or page.get("errors"):
        raise AnnouncementError("search_bad_response", "X search returned an error. No retry was sent.")
    posts = page.get("data", [])
    includes = page.get("includes", {})
    users = includes.get("users", []) if isinstance(includes, dict) else None
    if not isinstance(posts, list) or not isinstance(users, list) or len(posts) > count or len(users) > count:
        raise AnnouncementError("search_bad_response", "X search returned an unexpected page. No retry was sent.")
    public = {u["id"] for u in users if isinstance(u, dict) and _id(u.get("id")) and u.get("protected") is False and not u.get("withheld")}
    blocked = {u["id"] for u in users if isinstance(u, dict) and _id(u.get("id")) and (u.get("protected") is not False or u.get("withheld"))}
    public -= blocked
    allowed = []
    for post in posts:
        if not isinstance(post, dict) or not _id(post.get("id")) or post.get("withheld") or not isinstance(post.get("text"), str):
            continue
        author = post.get("author_id")
        if not _id(author) or author not in public:
            continue
        # Do not return full post/author records or expansions, only the matcher input.
        row = {key: post[key] for key in ("id", "text") }
        if _id(post.get("conversation_id")):
            row["conversation_id"] = post["conversation_id"]
        if isinstance(post.get("created_at"), str):
            row["created_at"] = post["created_at"]
        entities = post.get("entities")
        urls = entities.get("urls") if isinstance(entities, dict) else None
        if isinstance(urls, list):
            row["entities"] = {"urls": [
                {key: url[key] for key in ("expanded_url", "unwound_url") if isinstance(url.get(key), str)}
                for url in urls if isinstance(url, dict)
            ]}
        allowed.append(row)
    meta = page.get("meta")
    # Never send an opaque provider cursor through the frontend or keep post/user text server-side.
    return {"data": allowed, "meta": {"result_count": len(allowed), "more_available": bool(meta.get("next_token")) if isinstance(meta, dict) else False}}, len(posts), len(users)


def search(payload: dict, accounts: Any, settings: Any, ledger_factory: Any, *, fetch=x_page,
           clock=lambda: datetime.now(timezone.utc)) -> dict:
    if set(payload) != {"query", "maxResults"}:
        raise AnnouncementError("search_invalid_input", "Search input is only a query and maxResults.")
    query, count = payload["query"], payload["maxResults"]
    if not isinstance(query, str) or not query.strip() or len(query) > 4096 or type(count) is not int or not 10 <= count <= 100:
        raise AnnouncementError("search_invalid_input", "Enter an X query and a result limit between 10 and 100.")
    document = settings.read()
    options = validated_settings(document.get("opportunities"))
    if not options["enabled"]:
        raise AnnouncementError("search_disabled", "X opportunity searches are off until an admin enables them.")
    start_day = document.get("billingCycleDay")
    if ledger_factory is None or type(start_day) is not int or not 1 <= start_day <= 31:
        raise AnnouncementError("search_not_configured", "An X billing cycle and site spend ledger are required before searching.")
    post_price = amount(options["postPrice"], "The X post-read price")
    user_price = amount(options["userPrice"], "The X user-read price")
    cap = amount(options["budget"], "The search budget")
    worst_case = (post_price + user_price) * count
    status = accounts.status()
    account = status.get("accountId")
    if status.get("connection") != CONNECTED or not _id(account) or not {"tweet.read", "users.read"}.issubset(status.get("scopes", [])):
        raise AnnouncementError("search_connection_unavailable", "This site needs a connected X account with post and user read permissions.")
    moment = clock()
    try:
        reserved = ledger_factory().reserve_search(account, budget.cycle_start(moment, start_day), worst_case, cap, moment)
    except spend_ledger.SpendError:
        raise AnnouncementError("search_ledger_unavailable", "The site could not reserve the X search budget. Nothing was searched.") from None
    if reserved is None:
        raise AnnouncementError("search_budget_exhausted", "This search would exceed the site's X read budget. Nothing was searched.")
    try:
        token = accounts.access_token(expected_account_id=account)
    except AnnouncementError as error:
        raise AnnouncementError(error.code, "The existing X connection could not authorize the search.") from None
    page, posts, users = public_page(fetch(query.strip(), count, token), count)
    return {"capture": {query.strip(): page}, "receipt": {
        "postsReturnedByX": posts, "usersReturnedByX": users, "publicPosts": len(page["data"]),
        "reservedUsd": str(worst_case), "reservedThisCycleUsd": reserved,
        "estimatedUsd": str(posts * post_price + users * user_price),
    }}
