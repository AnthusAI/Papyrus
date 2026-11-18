"""What a list's wake does: read the request the queue delivered, read the list's settings as they are now, and make the period's Announcement (slice N1).

The request is the one the schedule entry sent (``agent_definitions/schedules.py``): its ``input.listId`` names the list and its wake key
(``<agent>:list:<list>|schedule|<scheduled time>``) names the time the tick was scheduled for. The settings are read again at every tick, so a changed time or rule
takes effect at the next tick and nothing already decided is touched.
"""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

from papyrus_content import wake_keys
from papyrus_content.announcements.decisions import Announcements

from .periods import read_history
from .announce import Candidate, Drafter, Result, announce_period, announce_story
from .store import ListState


class ListWakeError(ValueError):
    """A wake that is not a tick of a periodic list that exists."""


def scheduled_time(request: Mapping) -> str:
    parts = wake_keys.checked(request.get("wakeKey")).split(wake_keys.SEPARATOR)
    if len(parts) != 3 or parts[1] != wake_keys.SCHEDULE:
        raise ListWakeError(f"{request.get('wakeKey')!r} is not a schedule tick: a periodic list is woken by its clock.")
    return parts[2]


def run_list(request: Mapping, state: ListState, announcements: Announcements, *, candidates_for: Callable[[str, Mapping, str, str | None], Sequence[Candidate]], draft: Drafter,
             policy_rung: Callable[[str], str], account_id: str, by: str, now: str | None = None) -> Result:
    """One tick. ``candidates_for(list id, settings, scheduled time, since)`` is the Stories that qualified since ``since`` (when the list's last issue was sent, or None
    when it never sent one) that the run read; ``policy_rung(list id)`` the site policy's rung."""
    list_id = (request.get("input") or {}).get("listId")
    entry = state.get(list_id) if list_id else None
    if entry is None:
        raise ListWakeError(f"The wake names the list {list_id!r}, which is not a list of this site: nothing is made.")
    if entry["cadence"] == "each":
        raise ListWakeError(f"{list_id} is an every-item list: a clock does not wake it.")
    time = scheduled_time(request)
    history = read_history(announcements.deliveries, account_id, list_id)
    return announce_period(announcements, list_id, entry, time, candidates_for(list_id, entry, time, history.last_sent_at), history=history, draft=draft, policy_rung=policy_rung(list_id),
                           account_id=account_id, by=by, now=now)


def run_story_change(candidate: Candidate, state: ListState, announcements: Announcements, *, draft: Drafter, policy_rung: Callable[[str], str], account_id: str, by: str,
                     now: str | None = None, trigger: str = "change") -> Result:
    """A Story's page went live, or its rating changed (the change feed wakes the agent): the settings are read as they are now, and every every-item list that
    carries the Story shares one Announcement and one email Delivery."""
    return announce_story(announcements, state.document["lists"], candidate, draft=draft, policy_rung=policy_rung, account_id=account_id, by=by, now=now, trigger=trigger)
