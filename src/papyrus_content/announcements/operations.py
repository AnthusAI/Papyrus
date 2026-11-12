"""What editors and owners do with announcements, as plain functions over ``Services``. The console routes, the ``papyrus announcements`` commands and the MCP tools
all call these through the one operation table (``handlers.py``); nothing here prints or reads arguments.
"""
from __future__ import annotations

from itertools import islice
from typing import Any, Mapping

from . import settings as settings_module
from .drafting import draft_announcement
from .eligibility import load_story, verdict
from .engine import SYSTEM_ACTOR, Services, _iso, pause, release_blocked, resume, standing, sync_row
from .post import tagged_link
from .settings import OFF
from .store import BLOCK_LABELS, POSTING, STATE_LABELS


def label_of(row: Mapping[str, Any]) -> str:
    if row.get("state") == "blocked":
        return BLOCK_LABELS.get(row.get("blockedReason"), "Blocked")
    return STATE_LABELS.get(row.get("state"), str(row.get("state")))


def describe(row: Mapping[str, Any]) -> dict[str, Any]:
    """A row as the list and the Story drawer show it: the plain label beside the raw state."""
    return {**row, "label": label_of(row)}


def update_settings(services: Services, changes: Mapping[str, Any], *, by: str, quality_floor: int) -> dict[str, Any]:
    """Apply a settings change after checking every rule. A change that gives the budget room, or any change while Stories wait, lets the waiting Stories go."""
    current = services.store.settings()
    checked = settings_module.checked(current, changes, quality_floor=quality_floor)
    saved = services.store.save_settings(checked, actor=by, now=_iso(services.now()))
    released = release_blocked(services, by=by) if saved.get("mode", OFF) != OFF and saved.get("accountId") else []
    return {"settings": services.store.settings(), "released": released}


def pause_announcements(services: Services, *, by: str, reason: str | None) -> dict[str, Any]:
    return pause(services, services.store.settings(), by=by, reason=reason)


def resume_announcements(services: Services, *, by: str) -> dict[str, Any]:
    return {"released": resume(services, by=by), "settings": services.store.settings()}


def preview(services: Services, lineage_id: str) -> dict[str, Any]:
    """The exact post a Story would get, from the same drafting and checks, writing nothing and sending nothing. Spends one model call."""
    settings = services.store.settings()
    story = load_story(services.client, lineage_id, item_url_style=services.item_url_style)
    decision = verdict(story, {**settings, "mode": settings.get("mode") if settings.get("mode", OFF) != OFF else "dry_run"})
    link = tagged_link(services.site_origin.rstrip("/") + story.path)
    draft = draft_announcement(story, link, guidelines=services.guidelines_for(story), llm=services.llm, judge=services.judge, rule_lane=services.rule_lane, model=services.model)
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
    account = services.store.settings().get("accountId")
    if not account:
        return []
    rows = (row for row in services.store.recent(account) if state is None or row.get("state") == state)
    return [describe(row) for row in islice(rows, limit)]


def account_status(services: Services) -> dict[str, Any]:
    """Mode, pause, the cycle's spend against the budget, and a budget suggestion from the site's own pace."""
    settings = services.store.settings()
    report: dict[str, Any] = {"mode": settings.get("mode", OFF), "paused": bool(settings.get("paused")), "pausedBy": settings.get("pausedBy"), "pausedAt": settings.get("pausedAt"),
                              "pauseReason": settings.get("pauseReason"), "accountId": settings.get("accountId"), "accountHandle": settings.get("accountHandle"),
                              "pricesAsOf": settings.get("pricesAsOf")}
    if settings.get("accountId") and settings.get("budget") is not None and settings.get("billingCycleDay") is not None:
        report["standing"] = standing(services, settings).sentence()
    return report
