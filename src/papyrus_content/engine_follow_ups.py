"""The engine's own follow-ups: wakes the runner starts with no adopted agent (PPY-9b8e59; owner decision, Ryan, 2026-11-22).

A follow-up timer the engine itself sets (a soft review's deadline) wakes the engine, not an agent: no Automation governs it and no responsibility or rung applies
to it, so the run gate would skip it as ``not_adopted``. ``engine_follow_up_of`` names the ones the gate starts anyway, and only those: the wake's trigger is a
follow-up (``follow_up_timers.KIND``), it names no automation, the owner in its wake key is on ``ENGINE_FOLLOW_UPS`` and its procedure is that owner's own registered
procedure. Any other wake, follow-up or not, goes through the policy as before.

What still applies: the site's pause (``site.paused`` in the agent policy, the "pause every agent on a site" switch). A paused site starts no engine follow-up either; the
request keeps its due time and is shown as Overdue until the site resumes. A per-agent pause and a rung do not apply: there is no agent.

The list: a soft review's deadline (``review-deadline`` -> ``review_deadline``, review_deadline_timers.py) and a Delivery's due time, the scheduled send (``deliver`` ->
``deliver_due``, announcements/delivery_timers.py and announcements/deliver_due.py, PPY-e2829f).
"""
from __future__ import annotations

from typing import Any, Mapping

from . import follow_up_timers, wake_keys
from .announcements.delivery_timers import OWNER as DELIVER_OWNER, PROCEDURE_KEY as DELIVER_PROCEDURE
from .review_deadline_timers import OWNER as REVIEW_DEADLINE_OWNER, PROCEDURE_KEY as REVIEW_DEADLINE_PROCEDURE

#: Owner in the wake key -> the one procedure that handles its wakes.
ENGINE_FOLLOW_UPS: Mapping[str, str] = {REVIEW_DEADLINE_OWNER: REVIEW_DEADLINE_PROCEDURE, DELIVER_OWNER: DELIVER_PROCEDURE}


def engine_follow_up_of(request: Mapping[str, Any]) -> str | None:
    """The engine owner this wake is for, or None when it is not one of the engine's own follow-ups."""
    trigger = request.get("trigger") if isinstance(request.get("trigger"), dict) else {}
    if trigger.get("kind") != follow_up_timers.KIND or trigger.get("automationId"):
        return None
    try:
        owner = wake_keys.checked(request.get("wakeKey")).split(wake_keys.SEPARATOR)[0]
        follow_up_timers.due_time_of(str(request.get("wakeKey")))
    except (wake_keys.InvalidWakeKey, follow_up_timers.FollowUpError):
        return None
    return owner if ENGINE_FOLLOW_UPS.get(owner) == request.get("procedureKey") else None
