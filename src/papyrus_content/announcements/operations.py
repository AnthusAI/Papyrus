"""What editors and owners do with the announcement settings and X, as plain functions over ``Services``. The console routes, the ``papyrus announcements`` commands and the MCP tools
all call these through the one operation table (``handlers.py``); nothing here prints or reads arguments.

The Announcements a person looks at are read by ``where``, ``recent`` and ``explain`` (``lines.py``, ``list_handlers.py``): the old list and show of the X row shape are gone with it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping

from papyrus_content import console_links

from . import budget as budget_module, link_reads
from .deliveries import Deliveries
from .drafting import DraftRefused, draft_announcement
from .eligibility import refusal
from .post import tagged_link
from .records import ATTEMPT_SENT, BLOCKED, attempt_log
from .rules import OFF, SettingsIncomplete, money
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
    learned = services.x.learned() if services.x.learned is not None else None
    try:
        draft = draft_announcement(story, link, guidelines=services.x.guidelines_for(story), llm=services.x.llm, judge=services.x.judge, rule_lane=services.x.rule_lane,
                                   model=services.x.model, learned=learned.prompt if learned else "",
                                   hashtags=services.x.hashtags(story.lineage_id) if services.x.hashtags else None)
    except DraftRefused as refused:
        return {"lineageId": lineage_id, "eligible": eligible, "reason": reason, "text": "", "post": "", "link": link, "weight": 0, "checks": [], "passed": False,
                "failures": [str(refused)], "sent": False}
    return {"lineageId": lineage_id, "eligible": eligible, "reason": reason, "text": draft.text, "post": draft.post, "link": link,
            "weight": draft.weight, "checks": draft.checks, "passed": draft.passed, "failures": draft.failures, "sent": False, "hashtags": draft.hashtags}


#: The window the budget suggestion reads: the site's own pace over the last two months (the design's "last two months").
SUGGESTION_WINDOW_DAYS = 60


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pace_and_posts(services: Services, settings: Mapping[str, Any]) -> dict[str, Any]:
    """From the account's own Deliveries, newest first, stopping at the edge of the window (never the whole table): how many Announcements the account has had in the window (one
    for each eligibility event, however many generations or states they went through) and how many posts it sent this billing cycle (every attempt that was sent, a post
    later deleted included, because X charged for it). ``postCount`` is our count; X's own daily usage count is read beside it by the page, not here."""
    now = services.control.now()
    window_start = _iso(now - timedelta(days=SUGGESTION_WINDOW_DAYS))
    cycle = budget_module.cycle_start(now, int(settings["billingCycleDay"])) if settings.get("billingCycleDay") is not None else None
    cycle_start = f"{cycle.isoformat()}T00:00:00Z" if cycle else None
    eligible: set[str] = set()
    posts = 0
    for row in services.deliveries.for_account("x", settings["accountId"]):
        if str(row.get("createdAt") or "") < window_start:
            break
        eligible.add(str(row["announcementId"]))
        posts += sum(1 for entry in attempt_log(row) if entry.get("outcome") == ATTEMPT_SENT and cycle_start and str(entry.get("at") or "") >= cycle_start)
    return {"eligibleCount": len(eligible), "postCount": posts if cycle_start else None}


def account_status(services: Services) -> dict[str, Any]:
    """Mode, pause, the cycle's spend against the budget, our post count this cycle, the budget suggestion from the site's own pace, and the connected account."""
    settings = current(services)
    report: dict[str, Any] = {"mode": settings["mode"], "paused": settings["paused"], "pausedBy": settings["pausedBy"], "pausedAt": settings["pausedAt"],
                              "pauseReason": settings["pauseReason"], "accountId": settings["accountId"], "accountHandle": settings["accountHandle"],
                              "connection": settings["connectionStatus"], "pricesAsOf": (settings["prices"] or {}).get("asOf")}
    if settings["budget"] is not None and settings["billingCycleDay"] is not None:
        report["standing"] = services.control.standing(settings).sentence()
    if settings["accountId"]:
        counted = pace_and_posts(services, settings)
        if counted["postCount"] is not None:
            report["postCount"] = counted["postCount"]
        try:
            report["suggestion"] = budget_module.suggestion(counted["eligibleCount"], SUGGESTION_WINDOW_DAYS, settings)
        except SettingsIncomplete:
            pass   # no price entered yet: there is nothing to suggest, and the page already asks for the prices
    return report


def blocked_stories(services: Services) -> list[dict[str, Any]]:
    """The Stories that qualified and are waiting, with the reason in the Delivery's own words (paused, budget reached, account needs reconnecting, a failed check): one entry for
    each blocked X Delivery of the connected account, newest first. Nothing that never qualified is listed; why a Story did not qualify is ``explain``."""
    settings = current(services)
    if not settings["accountId"]:
        return []
    waiting = []
    for row in services.deliveries.for_account("x", settings["accountId"]):
        if row.get("state") != BLOCKED:
            continue
        stories = [{"lineageId": link["objectLineageId"]} for link in link_reads.stories_of_announcement(services.client, row["announcementId"])]
        waiting.append({"delivery": row["id"], "announcementId": row["announcementId"], "stories": stories, "reason": row.get("blockedReason") or "", "words": f"Blocked: {row.get('blockedReason') or 'waiting'}",
                        "since": row.get("updatedAt")})
    return waiting


def account_connect_link(base: str) -> dict[str, str]:
    """Connecting the X account is a browser step (OAuth); the command line only says where."""
    return {"url": console_links.announcements_url(base), "words": "Open this page in the newsroom and choose Connect X account. Connecting needs the browser; no secret is ever typed here."}


def retry_delivery(services: Services, delivery: str, *, by: str) -> dict[str, Any]:
    """A person decided a failed Delivery should be tried again: it goes back to ready, and the next try is the next attempt. The attempts so far stay in its log."""
    row = services.deliveries.get(delivery)
    if row is None:
        raise ValueError(f"There is no Delivery {delivery}.")
    return services.deliveries.retry(row, by=by)
