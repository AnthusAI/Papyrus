"""What editors and owners do with announcements, as plain functions over ``Services``. The console routes, the ``papyrus announcements`` commands and the MCP tools
all call these through the one operation table (``handlers.py``); nothing here prints or reads arguments.
"""
from __future__ import annotations

from itertools import islice
from typing import Any, Mapping

from .drafting import DraftRefused, draft_announcement
from .eligibility import load_story, verdict
from .engine import SYSTEM_ACTOR, Services, current, release_blocked, standing, sync_row
from .post import tagged_link
from .rules import OFF, ON, money
from .x_account import NOT_CONNECTED, AnnouncementError
from .store import BLOCK_LABELS, POSTING, STATE_LABELS


def label_of(row: Mapping[str, Any]) -> str:
    if row.get("state") == "blocked":
        return BLOCK_LABELS.get(row.get("blockedReason"), "Blocked")
    return STATE_LABELS.get(row.get("state"), str(row.get("state")))


def describe(row: Mapping[str, Any]) -> dict[str, Any]:
    """A row as the list and the Story drawer show it: the plain label beside the raw state."""
    return {**row, "label": label_of(row)}


def _release(services: Services, by: str) -> list[dict[str, Any]]:
    """Announce the Stories that waited, where this lane can: a dry run needs no channel. With mode On only a lane that holds the X channel (the site's own function)
    can hand a post over, so the signed-in command line leaves the waiting Stories for it."""
    settings = current(services)
    if settings["mode"] == OFF or not settings["accountId"] or (settings["mode"] == ON and services.broadcaster is None):
        return []
    return release_blocked(services, by=by)


def update_settings(services: Services, changes: Mapping[str, Any], *, by: str) -> dict[str, Any]:
    """Apply flat changes to the settings document, which checks every rule (``settings.AnnouncementSettings.save``) and raises ``AnnouncementError`` with a plain
    sentence. Stories that waited on a guard are announced when the change lifts it (a bigger budget, a connected account, a billing cycle day)."""
    document = services.settings.read()
    proposed = {**document, "rules": dict(document["rules"])}
    for name in ("minStars", "storyTypes", "sections"):
        if name in changes:
            proposed["rules"][name] = changes[name]
    for name in ("mode", "billingCycleDay", "labelConfirmed", "prices"):
        if name in changes:
            proposed[name] = changes[name]
    if "budget" in changes:
        amount = money(changes["budget"])
        if amount is None:
            raise AnnouncementError("budget_invalid", "The budget is an amount of money, zero or more, per X billing cycle.")
        proposed["budget"] = float(amount)
    services.settings.save(proposed, services.connection().get("connection") or NOT_CONNECTED)
    settings = current(services)
    return {"settings": services.settings.read(), "released": _release(services, by)}


def pause_announcements(services: Services, *, by: str) -> dict[str, Any]:
    return services.settings.manual_pause(True, by)


def resume_announcements(services: Services, *, by: str) -> dict[str, Any]:
    document = services.settings.manual_pause(False, by)
    return {"released": _release(services, by), "settings": document}


def preview(services: Services, lineage_id: str) -> dict[str, Any]:
    """The exact post a Story would get, from the same drafting and checks, writing nothing and sending nothing. Spends one model call."""
    settings = current(services)
    story = load_story(services.client, lineage_id, item_url_style=services.item_url_style)
    decision = verdict(story, {**settings, "mode": settings["mode"] if settings["mode"] != OFF else "dry_run"})
    link = tagged_link(services.site_origin.rstrip("/") + story.path)
    try:
        draft = draft_announcement(story, link, guidelines=services.guidelines_for(story), llm=services.llm, judge=services.judge, rule_lane=services.rule_lane, model=services.model)
    except DraftRefused as refused:
        return {"lineageId": lineage_id, "eligible": decision.eligible, "reason": decision.reason, "text": "", "post": "", "link": link, "weight": 0, "checks": [], "passed": False,
                "failures": [str(refused)], "sent": False}
    return {"lineageId": lineage_id, "eligible": decision.eligible, "reason": decision.reason, "text": draft.text, "post": draft.post, "link": link,
            "weight": draft.weight, "checks": draft.checks, "passed": draft.passed, "failures": draft.failures, "sent": False}


def show(services: Services, announcement_id: str) -> dict[str, Any] | None:
    row = services.store.get_by_id(announcement_id)
    if row is None:
        return None
    if row["state"] == POSTING and services.broadcaster is not None:
        sync_row(services, row, by=SYSTEM_ACTOR)
        row = services.store.get_by_id(announcement_id)
    return {**describe(row), "document": services.store.document(announcement_id)}


def listing(services: Services, *, state: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """The account's announcements, newest first, optionally one state. Reads only as far as it needs to: never a table."""
    account = current(services)["accountId"]
    if not account:
        return []
    rows = (row for row in services.store.recent(account) if state is None or row.get("state") == state)
    return [describe(row) for row in islice(rows, limit)]


def account_status(services: Services) -> dict[str, Any]:
    """Mode, pause, the cycle's spend against the budget, and the connected account."""
    settings = current(services)
    report: dict[str, Any] = {"mode": settings["mode"], "paused": settings["paused"], "pausedBy": settings["pausedBy"], "pausedAt": settings["pausedAt"],
                              "pauseReason": settings["pauseReason"], "accountId": settings["accountId"], "accountHandle": settings["accountHandle"],
                              "connection": settings["connectionStatus"], "pricesAsOf": (settings["prices"] or {}).get("asOf")}
    if settings["budget"] is not None and settings["billingCycleDay"] is not None:
        report["standing"] = standing(services, settings).sentence()
    return report
