"""What editors and owners do with the announcement settings and X, as plain functions over ``Services``. The console routes, the ``papyrus announcements`` commands and the MCP tools
all call these through the one operation table (``handlers.py``); nothing here prints or reads arguments.

The Announcements a person looks at are read by ``where``, ``recent`` and ``explain`` (``lines.py``, ``list_handlers.py``): the old list and show of the X row shape are gone with it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from .deliveries import Deliveries
from .drafting import DraftRefused, draft_announcement
from .eligibility import refusal
from .post import tagged_link
from .rules import OFF, money
from .x_account import NOT_CONNECTED, AnnouncementError
from .x_runner import SpendControl, resume_blocked

if TYPE_CHECKING:   # the X part imports the review policy, which imports the operation table that imports this module's handlers
    from .x_announce import XServices


@dataclass
class Services:
    client: Any
    x: "XServices"
    control: SpendControl
    deliveries: Deliveries


def current(services: Services) -> dict[str, Any]:
    return services.control.current()


def _release(services: Services, by: str) -> list[dict[str, Any]]:
    """Put back the X Deliveries a pause or the budget held, once the guard has lifted. It writes only the Deliveries' own state: the worker that sends them is the deliver side's."""
    return resume_blocked(services.deliveries, services.control, by=by)


def update_settings(services: Services, changes: Mapping[str, Any], *, by: str) -> dict[str, Any]:
    """Apply flat changes to the settings document, which checks every rule (``settings.AnnouncementSettings.save``) and raises ``AnnouncementError`` with a plain
    sentence. Deliveries that waited on a guard are put back when the change lifts it (a bigger budget, a connected account, a billing cycle day)."""
    document = services.control.settings.read()
    proposed = {**document, "rules": dict(document["rules"])}
    for name in ("minStars", "storyTypes", "sections", "requireReviewedSource"):
        if name in changes:
            proposed["rules"][name] = changes[name]
    for name in ("mode", "billingCycleDay", "labelConfirmed", "prices", "editWindows"):
        if name in changes:
            proposed[name] = changes[name]
    if "spacing" in changes:
        # Each account named is set; a null takes its spacing away. Accounts not named keep theirs.
        merged = dict(document.get("spacing") or {})
        for account, minutes in (changes["spacing"] or {}).items():
            if minutes is None:
                merged.pop(account, None)
            else:
                merged[account] = minutes
        proposed["spacing"] = merged
    if "budget" in changes:
        amount = money(changes["budget"])
        if amount is None:
            raise AnnouncementError("budget_invalid", "The budget is an amount of money, zero or more, per X billing cycle.")
        proposed["budget"] = float(amount)
    services.control.settings.save(proposed, services.control.connection().get("connection") or NOT_CONNECTED)
    return {"settings": services.control.settings.read(), "released": _release(services, by)}


def pause_announcements(services: Services, *, by: str) -> dict[str, Any]:
    return services.control.settings.manual_pause(True, by)


def resume_announcements(services: Services, *, by: str) -> dict[str, Any]:
    document = services.control.settings.manual_pause(False, by)
    return {"released": _release(services, by), "settings": document}


def preview(services: Services, lineage_id: str) -> dict[str, Any]:
    """The exact post a Story would get, from the same drafting and checks, writing nothing and sending nothing. Spends one model call."""
    settings = current(services)
    story = services.x.story(lineage_id)
    stopped = refusal(story, {**settings, "mode": settings["mode"] if settings["mode"] != OFF else "dry_run"})
    eligible, reason = (True, "eligible") if stopped is None else (False, stopped[0])
    link = tagged_link(services.x.site_origin().rstrip("/") + story.path)
    try:
        draft = draft_announcement(story, link, guidelines=services.x.guidelines_for(story), llm=services.x.llm, judge=services.x.judge, rule_lane=services.x.rule_lane,
                                   model=services.x.model)
    except DraftRefused as refused:
        return {"lineageId": lineage_id, "eligible": eligible, "reason": reason, "text": "", "post": "", "link": link, "weight": 0, "checks": [], "passed": False,
                "failures": [str(refused)], "sent": False}
    return {"lineageId": lineage_id, "eligible": eligible, "reason": reason, "text": draft.text, "post": draft.post, "link": link,
            "weight": draft.weight, "checks": draft.checks, "passed": draft.passed, "failures": draft.failures, "sent": False}


def account_status(services: Services) -> dict[str, Any]:
    """Mode, pause, the cycle's spend against the budget, and the connected account."""
    settings = current(services)
    report: dict[str, Any] = {"mode": settings["mode"], "paused": settings["paused"], "pausedBy": settings["pausedBy"], "pausedAt": settings["pausedAt"],
                              "pauseReason": settings["pauseReason"], "accountId": settings["accountId"], "accountHandle": settings["accountHandle"],
                              "connection": settings["connectionStatus"], "pricesAsOf": (settings["prices"] or {}).get("asOf")}
    if settings["budget"] is not None and settings["billingCycleDay"] is not None:
        report["standing"] = services.control.standing(settings).sentence()
    return report


