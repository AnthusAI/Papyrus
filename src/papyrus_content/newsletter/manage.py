"""Managing a subscription with a manage token: preferences, unsubscribe, re-subscribe, deletion, and the admin operations.

A manage token proves control of the inbox it was mailed to, so ticking a list again re-subscribes with no new opt-in.
Every function takes the service (``handler.Newsletter``) and the event, and answers ``{"statusCode", "body"}``.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import addresses, records, tokens
from .pause import resume_site
from .store import Conflict, append_history, iso, membership_row

WRITE_ATTEMPTS = 3
RESUBSCRIBE_CLEARS = ("bounce", "complaint")


def respond(status_code: int, **body: Any) -> dict[str, Any]:
    return {"statusCode": status_code, "body": body}


def mask(address: str) -> str:
    """``reader@example.com`` -> ``r***@example.com``."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _manage_claims(svc: Any, token: Any) -> tokens.Claims | None:
    try:
        return tokens.verify(svc.keys.token, token, "manage", svc.clock())
    except tokens.InvalidToken:
        return None


def apply_unsubscribe(svc: Any, hid: str, list_ids: list[str] | None, label: str) -> list[str] | None:
    """Unsubscribe from the given lists (all when None). Idempotent. Returns the ids that changed, or None when there is no profile."""
    for _attempt in range(WRITE_ATTEMPTS):
        profile = svc.store.get_profile(hid)
        if profile is None:
            return None
        now = svc.clock()
        rows = svc.store.memberships(hid)
        targets = [
            list_id
            for list_id, row in rows.items()
            if (list_ids is None or list_id in list_ids) and row.get("status") != "unsubscribed"
        ]
        remaining = [list_id for list_id, row in rows.items() if row.get("status") == "subscribed" and list_id not in targets]
        became_unsubscribed = not remaining and profile.get("status") != "unsubscribed"
        if not targets and not became_unsubscribed:
            return []
        if not remaining:
            profile["status"] = "unsubscribed"
            profile.pop("confirmNonce", None)
        profile["updatedAt"] = iso(now)
        append_history(profile, now, label)
        put_rows = [membership_row(hid, list_id, "unsubscribed", now) for list_id in targets]
        try:
            svc.store.save(profile, int(profile.get("rev", 0)), put_rows)
        except Conflict:
            continue
        return targets
    return []


def preferences_state(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    claims = _manage_claims(svc, event.get("token"))
    profile = svc.store.get_profile(claims.hid) if claims else None
    if claims is None or profile is None:
        return respond(400, status="invalid")
    rows = svc.store.memberships(claims.hid)
    lists = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "description": entry.get("description", ""),
            "subscribed": rows.get(entry["id"], {}).get("status") == "subscribed",
        }
        for entry in svc.settings.lists
    ]
    return respond(200, status="ready", email=mask(str(profile.get("email", ""))), lists=lists)


def update_preferences(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    claims = _manage_claims(svc, event.get("token"))
    if claims is None:
        return respond(400, status="invalid")
    wanted = svc._requested_lists(event.get("lists"))
    for _attempt in range(WRITE_ATTEMPTS):
        profile = svc.store.get_profile(claims.hid)
        if profile is None:
            return respond(400, status="invalid")
        now = svc.clock()
        rows = svc.store.memberships(claims.hid)
        subscribing = [list_id for list_id in wanted if rows.get(list_id, {}).get("status") != "subscribed"]
        suppression = records.get_suppression(svc.store, claims.hid)
        if suppression and subscribing:
            if suppression.get("reason") in RESUBSCRIBE_CLEARS:
                records.delete_suppression(svc.store, claims.hid)
                try:
                    svc.mailer.delete_suppressed_destination(str(profile.get("email", "")))
                except Exception as error:  # noqa: BLE001 - the local row is already cleared; SES may still hold the address
                    print(json.dumps({"event": "ses_unsuppress_failed", "error": type(error).__name__}))
            else:
                wanted = [list_id for list_id in wanted if list_id not in subscribing]
                subscribing = []
        put_rows = []
        for entry in svc.settings.lists:
            list_id = entry["id"]
            is_subscribed = rows.get(list_id, {}).get("status") == "subscribed"
            if list_id in wanted and not is_subscribed:
                put_rows.append(membership_row(claims.hid, list_id, "subscribed", now, profile_confirmed=True))
                append_history(profile, now, f"resubscribed:{list_id}")
            elif list_id not in wanted and is_subscribed:
                put_rows.append(membership_row(claims.hid, list_id, "unsubscribed", now))
                append_history(profile, now, f"unsubscribed:{list_id}")
        if put_rows:
            profile["status"] = "confirmed" if wanted else "unsubscribed"
            profile.pop("confirmNonce", None)
            profile.pop("expiresAt", None)
            profile["updatedAt"] = iso(now)
            try:
                svc.store.save(profile, int(profile.get("rev", 0)), put_rows)
            except Conflict:
                continue
        subscribed = [entry["id"] for entry in svc.settings.lists if entry["id"] in wanted]
        return respond(200, status="saved", lists=subscribed)
    return respond(409, status="conflict")


def unsubscribe(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    claims = _manage_claims(svc, event.get("token"))
    if claims is None:
        return respond(400, status="invalid")
    list_id = event.get("list")
    known = svc.settings.list_named(list_id) if isinstance(list_id, str) and list_id else None
    if list_id and known is None:
        return respond(200, status="unsubscribed", scope="list", lists=[])
    changed = apply_unsubscribe(svc, claims.hid, [list_id] if known else None, f"unsubscribed:{list_id}" if known else "unsubscribed:all")
    named = [{"id": item, "name": svc.settings.list_named(item)["name"]} for item in (changed or []) if svc.settings.list_named(item)]
    if known and not named:
        named = [{"id": known["id"], "name": known["name"]}]
    return respond(200, status="unsubscribed", scope="list" if known else "all", lists=named)


def delete_subscriber(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Erase everything held about the subscriber the token names. Idempotent: a token for an erased subscriber still answers deleted."""
    claims = _manage_claims(svc, event.get("token"))
    if claims is None:
        return respond(400, status="invalid")
    records.erase_subscriber(svc.store, claims.hid)
    return respond(200, status="deleted")


def admin_erase(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Erase one subscriber by address, for the newsroom panel. Only a caller that may invoke the function can reach it."""
    raw = event.get("email")
    address = addresses.normalize(raw) if isinstance(raw, str) else ""
    if not addresses.is_valid(address):
        return respond(400, status="invalid_email")
    removed = records.erase_subscriber(svc.store, addresses.hid(svc.keys.hash, address))
    return respond(200, status="deleted", removed=removed)


def resume_sending(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    resume_site(svc.store, svc.mailer, svc.clock())
    return respond(200, status="resumed")


MANAGE_ACTIONS = {
    "preferences_state": preferences_state,
    "update_preferences": update_preferences,
    "unsubscribe": unsubscribe,
    "delete_subscriber": delete_subscriber,
    "admin_erase": admin_erase,
    "resume_sending": resume_sending,
}
