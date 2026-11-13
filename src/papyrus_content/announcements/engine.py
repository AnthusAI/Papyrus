"""The announcement pipeline: one Story, one account, at most one post, every step audited.

``process_story`` is the single entry. Publishing calls it when a Story first goes live and rating calls it when a rating changes (PPY-9f4d66); resuming
calls it again for every Story that was waiting on a guard. It is safe to call any number of times for the same Story:

1. Mode Off does nothing. A Story that is not eligible (``eligibility``) leaves no trace.
2. An existing row for this account and Story lineage decides: posted, dry run, failed and withdrawn rows are final (a new version never announces again); a row
   waiting on a guard is tried again; a row ``posting`` is read back from Caducus's delivery log.
3. The guards: paused, the account is usable, the budget allows one more post. Each turns the Story into a ``blocked`` row with its reason instead of dropping it.
   Passing the budget also pauses announcements, and says why.
4. The text is drafted and checked (``drafting``). A draft that fails is ``blocked: check failed`` and is never posted; no one is asked to approve a draft that passes.
5. Dry run records the exact post as ``dry_run`` at zero cost and sends nothing. On records the row as ``posting`` and hands one ``story.announce`` event to Caducus
   (``channel``), which posts it, handles unknown outcomes and rate limits, and records the post id and cost. ``sync_row`` copies the delivery's result onto the row:
   ``posted``, ``failed`` with X's message, ``blocked`` when Caducus's guard refused, or ``withdrawn``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from papyrus_content import fact_check

from . import budget as budget_module
from .channel import FAILED, QUEUED, REFUSED, SENT, WITHDRAWN, Broadcaster, ChannelNotAvailable, DeliveryView, event_id
from .drafting import Draft, DraftRefused, Llm, RuleLane, draft_announcement
from .eligibility import StoryFacts, load_story, verdict
from .post import tagged_link
from .rules import DRY_RUN, OFF, ON, PAUSE_BUDGET, SYSTEM, post_price, view
from .store import (ACCOUNT_NEEDS_RECONNECTING, BLOCKED, BUDGET_REACHED, CHECK_FAILED, DRY_RUN as DRY_RUN_STATE, FAILED as FAILED_STATE, PAUSED, POSTED, POSTING,
                    SETTINGS_INCOMPLETE, WITHDRAWN as WITHDRAWN_STATE, AlreadyAnnounced, AnnouncementStore, announcement_id)

SYSTEM_ACTOR = SYSTEM
BUDGET_PAUSE_REASON = "Budget reached for this cycle"
CHANNEL = "x"
#: Blocked rows the engine tries again on its own when a guard lifts. A row blocked by a failed check waits for an editor.
GUARD_REASONS = (PAUSED, BUDGET_REACHED, ACCOUNT_NEEDS_RECONNECTING, SETTINGS_INCOMPLETE)


@dataclass
class Services:
    client: Any
    store: AnnouncementStore
    site_origin: str
    item_url_style: str
    #: ``guidelines_for(story) -> text``: the writing guidelines and announcement rules the draft is written under.
    guidelines_for: Callable[[StoryFacts], str]
    llm: Llm | None = None
    judge: fact_check.Judge | None = None
    rule_lane: RuleLane | None = None
    broadcaster: Broadcaster | None = None
    #: The settings document (``settings.AnnouncementSettings``: ``read``, ``pause``, ``resume``, ``resume_if``) and the account connection's status
    #: (``x_account.XAccounts.status``): the two things this package reads and never keeps a copy of.
    settings: Any = None
    connection: Callable[[], Mapping[str, Any]] = lambda: {}
    #: ``(kind, facts)``: tells the editors (a Caducus operator-class event). None tells no one.
    notify: Callable[[str, Mapping[str, Any]], None] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    model: str = ""


def current(services: Services) -> dict[str, Any]:
    """The settings and the connection as one flat view (``rules.view``)."""
    return view(services.settings.read(), services.connection())


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def result(status: str, reason: str = "", row: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, "announcementId": (row or {}).get("id"), "state": (row or {}).get("state"), **extra}


def _tell(services: Services, kind: str, **facts: Any) -> None:
    if services.notify is not None:
        services.notify(kind, facts)


# --- guards ------------------------------------------------------------------------------------------------------------------------------------------

def standing(services: Services, settings: Mapping[str, Any]) -> budget_module.Standing:
    now = services.now()
    start = budget_module.cycle_start(now, int(settings["billingCycleDay"]))
    return budget_module.standing(settings, services.store.spent(settings["accountId"], start), now)


def lift_budget_pause(services: Services, settings: dict[str, Any]) -> dict[str, Any]:
    """A pause the budget caused ends by itself when the budget has room again (a new cycle, or the owner raised it). A pause a person made never does."""
    if not (settings["paused"] and settings["pauseKind"] == PAUSE_BUDGET and settings["pausedBy"] == SYSTEM):
        return settings
    if standing(services, settings).would_pass(post_price(settings)):
        return settings
    services.settings.resume_if(PAUSE_BUDGET)
    return current(services)


def guard(services: Services, settings: dict[str, Any]) -> tuple[str, str] | None:
    """The first guard that stops a post: ``(reason code, plain words)``, or None when the Story may go on."""
    if settings["paused"]:
        who = settings["pausedBy"] or "someone"
        return PAUSED, f"Paused by {who}" + (f", {settings['pausedAt']}" if settings["pausedAt"] else "") + (f": {settings['pauseReason']}" if settings["pauseReason"] else "")
    if not settings["connected"]:
        return ACCOUNT_NEEDS_RECONNECTING, "The X account needs connecting again" if settings["connectionStatus"] == "needs_reconnecting" else "No X account is connected"
    if settings["budget"] is None or settings["billingCycleDay"] is None:
        return SETTINGS_INCOMPLETE, "Enter a budget and the day your X billing cycle starts"
    if standing(services, settings).would_pass(post_price(settings)):
        return BUDGET_REACHED, BUDGET_PAUSE_REASON
    return None


def pause_for_budget(services: Services) -> dict[str, Any]:
    services.settings.pause(PAUSE_BUDGET, BUDGET_PAUSE_REASON, SYSTEM, _iso(services.now()))
    return current(services)


# --- the pipeline ------------------------------------------------------------------------------------------------------------------------------------

def process_story(services: Services, lineage_id: str, *, trigger: str, by: str = SYSTEM_ACTOR) -> dict[str, Any]:
    settings = current(services)
    if settings.get("mode", OFF) == OFF:
        return result("ignored", "off")
    if settings["mode"] == ON and services.broadcaster is None:
        raise ChannelNotAvailable("Announcements are On but this site has no X channel wired. The Caducus x channel (kanbus-ea2644) is not deployed here.")
    story = load_story(services.client, lineage_id, item_url_style=services.item_url_style)
    decision = verdict(story, settings)
    if not decision.eligible:
        return result("ignored", decision.reason)
    account = settings["accountId"]
    if not account:
        return result("ignored", "no_account")
    row = services.store.get(account, lineage_id)
    if row is not None and row["state"] == POSTING:
        return sync_row(services, row, by=by)
    if row is not None and (row["state"] != BLOCKED or row.get("blockedReason") == CHECK_FAILED):
        return result("exists", row["state"], row)
    settings = lift_budget_pause(services, settings)
    link = tagged_link(services.site_origin.rstrip("/") + story.path)
    stopped = guard(services, settings)
    if stopped is not None:
        return _block(services, settings, story, link, row, stopped, trigger, by)
    return _announce(services, settings, story, link, row, trigger, by)


def _row(settings: Mapping[str, Any], story: StoryFacts, link: str, trigger: str, now: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": announcement_id(settings["accountId"], story.lineage_id), "accountId": settings["accountId"], "accountHandle": settings.get("accountHandle"),
        "storyLineageId": story.lineage_id, "storyItemId": story.item_id, "storyVersionNumber": story.version_number, "channel": CHANNEL, "mode": settings["mode"],
        "trigger": trigger, "link": link, "attempts": 0, "round": 1, "history": [], "createdAt": now, "updatedAt": now, **fields,
    }


def _block(services: Services, settings: dict[str, Any], story: StoryFacts, link: str, row: dict[str, Any] | None, stopped: tuple[str, str], trigger: str, by: str) -> dict[str, Any]:
    code, words = stopped
    now = _iso(services.now())
    if code == BUDGET_REACHED:
        settings = pause_for_budget(services)
        _tell(services, "announcement.budget-reached", story=story.title, spent=standing(services, settings).sentence())
    if code == ACCOUNT_NEEDS_RECONNECTING:
        _tell(services, "announcement.account-needs-reconnecting", reason=words)
    if row is None:
        try:
            row = services.store.create(_row(settings, story, link, trigger, now, state=BLOCKED, blockedReason=code, history=[{"at": now, "by": by, "state": BLOCKED, "note": words}]))
        except AlreadyAnnounced as found:
            return result("exists", found.row["state"], found.row)
    elif row.get("blockedReason") != code:
        row = services.store.update(row, {"state": BLOCKED, "blockedReason": code}, note=words, by=by, now=now)
    return result("blocked", code, row, message=words)


def _announce(services: Services, settings: dict[str, Any], story: StoryFacts, link: str, row: dict[str, Any] | None, trigger: str, by: str) -> dict[str, Any]:
    now = _iso(services.now())
    document = services.store.document(row["id"]) if row is not None else None
    if document and document.get("post"):
        draft = None
    else:
        if services.llm is None or services.judge is None:
            raise RuntimeError("Drafting needs a model: the announcement engine was built without one.")
        try:
            draft = draft_announcement(story, link, guidelines=services.guidelines_for(story), llm=services.llm, judge=services.judge, rule_lane=services.rule_lane,
                                       model=services.model)
        except DraftRefused as refused:
            return _draft_failed(services, settings, story, link, row, trigger, by, now, [str(refused)], None)
        if not draft.passed:
            return _draft_failed(services, settings, story, link, row, trigger, by, now, draft.failures, draft)
        document = _document(draft, story)
    common = {"weight": document["weight"], "draftedBy": document["model"], "checks": [{"name": c["name"], "passed": c["passed"]} for c in document["checks"]]}
    dry = settings["mode"] == DRY_RUN
    state = DRY_RUN_STATE if dry else POSTING
    note = "Dry run: not sent" if dry else "Handed to the X channel"
    fields = {**common, "state": state, "blockedReason": None, "error": None, "cost": "0" if dry else row.get("cost") if row else None,
              "attempts": int((row or {}).get("attempts") or 0) + (0 if dry else 1)}
    if row is None:
        made = _created(services, _row(settings, story, link, trigger, now, history=[{"at": now, "by": by, "state": state, "note": note}], **{k: v for k, v in fields.items() if v is not None}), document, state)
        if made["status"] == "exists" or dry:
            return made
        row = services.store.get_by_id(made["announcementId"])
    else:
        row = services.store.update(row, fields, note=note, by=by, now=now, document=document if draft is not None else None)
        if dry:
            return result("dry_run", "", row)
    services.broadcaster.submit(account_id=settings["accountId"], event_id=event_id(settings["accountId"], row["storyLineageId"], int(row.get("round") or 1)),
                                text=document["post"], url=link)
    return sync_row(services, row, by=by)


def _created(services: Services, row: dict[str, Any], document: Mapping[str, Any], status: str) -> dict[str, Any]:
    try:
        services.store.create(row, document)
    except AlreadyAnnounced as found:
        return result("exists", found.row["state"], found.row)
    return result("created" if status == POSTING else status, "", row)


def _document(draft: Draft, story: StoryFacts) -> dict[str, Any]:
    return {"text": draft.text, "post": draft.post, "link": draft.link, "weight": draft.weight, "model": draft.model, "checks": draft.checks,
            "story": {"lineageId": story.lineage_id, "itemId": story.item_id, "versionNumber": story.version_number, "title": story.title}}


def _draft_failed(services: Services, settings: dict[str, Any], story: StoryFacts, link: str, row: dict[str, Any] | None, trigger: str, by: str, now: str,
                  failures: list[str], draft: Draft | None) -> dict[str, Any]:
    document = {"text": draft.text if draft else "", "link": link, "model": services.model, "checks": draft.checks if draft else [], "failures": failures,
                "story": {"lineageId": story.lineage_id, "itemId": story.item_id, "versionNumber": story.version_number, "title": story.title}}
    fields = {"state": BLOCKED, "blockedReason": CHECK_FAILED, "weight": draft.weight if draft else None, "draftedBy": services.model,
              "checks": [{"name": c["name"], "passed": c["passed"]} for c in (draft.checks if draft else [])], "error": "; ".join(failures)[:500]}
    if row is None:
        made = _created(services, _row(settings, story, link, trigger, now, history=[{"at": now, "by": by, "state": BLOCKED, "note": "Check failed"}],
                                       **{k: v for k, v in fields.items() if v is not None}), document, "blocked")
    else:
        row = services.store.update(row, fields, note="Check failed", by=by, now=now, document=document)
        made = result("blocked", CHECK_FAILED, row)
    if made["status"] == "blocked":
        made["reason"], made["failures"] = CHECK_FAILED, failures
        _tell(services, "announcement.check-failed", story=story.title, failures=failures)
    return made


# --- reading the delivery back -----------------------------------------------------------------------------------------------------------------------

def sync_row(services: Services, row: dict[str, Any], *, by: str = SYSTEM_ACTOR) -> dict[str, Any]:
    """Copy what Caducus recorded for a ``posting`` row onto it. Only the delivery log says whether X took the post; this is the only place a row becomes posted."""
    if row["state"] != POSTING:
        return result("exists", row["state"], row)
    view: DeliveryView | None = services.broadcaster.delivery(event_id(row["accountId"], row["storyLineageId"], int(row.get("round") or 1)))
    now = _iso(services.now())
    if view is None or view.status == QUEUED:
        return result("queued", "", row)
    cost = {"cost": view.cost, "attempts": view.attempts or row.get("attempts")}
    if view.status == SENT:
        row = services.store.update(row, {**cost, "state": POSTED, "postId": view.post_id, "postedAt": now, "error": None}, note="Posted", by=by, now=now)
        return result("posted", "", row, postId=view.post_id)
    if view.status == FAILED:
        row = services.store.update(row, {**cost, "state": FAILED_STATE, "error": view.reason}, note=f"X refused: {view.reason}", by=by, now=now)
        _tell(services, "announcement.failed", story=row["storyLineageId"], reason=view.reason)
        return result("failed", view.reason or "", row)
    if view.status == REFUSED:
        # Caducus's guard refused (a pause, or the budget). A refusal is final for that event id, so the next announcement is round + 1.
        code = BUDGET_REACHED if "udget" in (view.reason or "") else PAUSED
        row = services.store.update(row, {**cost, "state": BLOCKED, "blockedReason": code, "round": int(row.get("round") or 1) + 1}, note=view.reason or "Refused by the guard", by=by, now=now)
        return result("blocked", code, row, message=view.reason)
    if view.status == WITHDRAWN:
        row = services.store.update(row, {**cost, "state": WITHDRAWN_STATE, "withdrawnBy": view.withdrawn_by, "withdrawnAt": view.withdrawn_at or now}, note=f"Withdrawn by {view.withdrawn_by}", by=by, now=now)
        return result("withdrawn", "", row)
    raise ValueError(f"The X channel's delivery has the status {view.status!r}.")


# --- guards lifting ----------------------------------------------------------------------------------------------------------------------------------

def release_blocked(services: Services, *, by: str = SYSTEM_ACTOR) -> list[dict[str, Any]]:
    """Try again every Story that was waiting on a guard. Such rows are newer than the pause that blocked them, so the read stops at the pause."""
    settings = current(services)
    if settings.get("mode", OFF) == OFF or not settings.get("accountId"):
        return []
    settings = lift_budget_pause(services, settings)
    since = settings["pausedAt"] or "0000-00-00T00:00:00Z"
    waiting = [row for row in services.store.since(settings["accountId"], since) if row.get("state") == BLOCKED and row.get("blockedReason") in GUARD_REASONS]
    return [process_story(services, row["storyLineageId"], trigger="resume", by=by) for row in reversed(waiting)]


def resume(services: Services, *, by: str) -> list[dict[str, Any]]:
    services.settings.resume()
    return release_blocked(services, by=by)
