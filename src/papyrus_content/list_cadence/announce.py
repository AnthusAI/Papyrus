"""Every cadence makes the same two records: an Announcement (model ``AnnouncementDecision``) and an email Delivery (slice N1, PPY-4d74d9).

* A periodic list (``daily``, ``weekly``) is woken by its schedule entry. The once-only key is ``roundup:<list>:<local period>`` (``records.roundup_key``): the
  local date for a daily list, the local ISO week for a weekly one, so a second tick for the same period finds the same Announcement, and a changed send time
  cannot make a second one for a period that has one.
* An every-item list is woken by a Story's page going live or its rating changing. The once-only key is ``story-published:<lineage>``: a republish finds the same
  Announcement. One Announcement has one email Delivery whose audience is every every-item list the Story qualifies for.

Both go through ``Announcements.announce`` with one ``Plan`` of the same shape (channel ``email``, the site's sending account, the list ids as the audience).
What a list wants is read from its settings (``settings.py``); nothing about a cadence is here. The words come from ``draft``, the agent's drafter: this module
decides, it does not write.

**The floor and the rung.** A Story qualifies for a list only at the list's minimum rating, and that is never under three: it is re-checked here, not trusted from
the document. A list's own rung can only narrow the site's policy: the effective rung is the lower of the two. Below ``prepare`` nothing is written (at ``observe``
the run lists what it would have done); ``prepare`` makes a Delivery that needs a hard approval, ``publish_soft`` one that a person may stop, ``publish_auto`` one
approved by policy at creation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from papyrus_content.agent_rungs import RUNGS
from papyrus_content.announcements import records
from papyrus_content.announcements.decisions import Announcements, Outcome
from papyrus_content.announcements.deliveries import Plan
from papyrus_content.announcements.links import StoryRef
from papyrus_content.newsletter.alerts import rule_matches

from .settings import QUALITY_FLOOR_STARS

CHANNEL = "email"
ROUNDUP, STORY_PUBLISHED = "roundup", "story_published"
APPROVAL_OF_RUNG = {"prepare": records.HARD, "publish_soft": records.SOFT, "publish_auto": records.NONE}
#: How restrictive an approval is, so one Delivery for several lists takes the most restrictive of them.
_STRICTNESS = {records.NONE: 0, records.SOFT: 1, records.HARD: 2}

NO_ITEMS = "no items reached the list's bar"
BELOW_PREPARE = "the rung is below prepare, so nothing is made"


@dataclass(frozen=True)
class Candidate:
    """A Story as a list's rule sees it: what the run read, nothing else. ``stars`` is the effective rating (a person's, or the rating agent's at a rung that writes);
    an unrated Story is 0 and a prediction is not a rating."""

    story: StoryRef
    section: str | None
    story_type: str | None
    tags: Sequence[str]
    stars: int
    reviewed_source: bool = False


@dataclass(frozen=True)
class Result:
    """What a wake did. ``outcome`` is None when nothing was written, and ``reason`` says why in words."""

    outcome: Outcome | None
    reason: str
    list_ids: tuple[str, ...] = ()


Drafter = Callable[[Sequence[tuple[str, Mapping[str, Any]]], Sequence[Candidate]], str]


def qualifies(entry: Mapping[str, Any], candidate: Candidate) -> tuple[bool, str]:
    """Whether the list carries the Story, and the word for why not. The floor is the code's own: a document that somehow names less is still held to three."""
    rule = entry["rule"]
    if candidate.stars < max(rule["minStars"], QUALITY_FLOOR_STARS):
        return False, f"{candidate.stars} stars is under the list's bar of {max(rule['minStars'], QUALITY_FLOOR_STARS)}"
    if not rule_matches(rule, section=candidate.section, tags=candidate.tags, item_type=candidate.story_type):
        return False, "the list's sections, types or tags do not match"
    if entry.get("requireReviewedSource") and not candidate.reviewed_source:
        return False, "no person has reviewed the source"
    return True, "qualifies"


def effective_rung(entry: Mapping[str, Any], policy_rung: str) -> str:
    """The lower of the site policy's rung for this list and the list's own. A list can narrow what the policy allows and never widen it."""
    own = entry.get("rung")
    return policy_rung if own is None else min(policy_rung, own, key=RUNGS.index)


def local_period(entry: Mapping[str, Any], scheduled_time: str) -> str:
    """The list's period a tick belongs to, in the list's own time zone: ``2026-11-16`` for a daily list, ``2026-W47`` for a weekly one."""
    local = datetime.fromisoformat(records.utc(scheduled_time).replace("Z", "+00:00")).astimezone(ZoneInfo(entry["timeZone"]))
    if entry["cadence"] == "weekly":
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02d}"
    return local.strftime("%Y-%m-%d")


def email_plan(text: str, rung: str, list_ids: Sequence[str], *, account_id: str, drafted_by: str, approval: str | None = None) -> Plan:
    """The one shape of an email Delivery, for every cadence."""
    return Plan(channel=CHANNEL, account_id=account_id, approval=approval or APPROVAL_OF_RUNG[rung], approval_policy=f"rung {rung} (list {', '.join(list_ids)})",
                text=text, audience=tuple(list_ids), drafted_by=drafted_by)


def announce_period(announcements: Announcements, list_id: str, entry: Mapping[str, Any], scheduled_time: str, candidates: Sequence[Candidate], *,
                    draft: Drafter, policy_rung: str, account_id: str, by: str, now: str | None = None) -> Result:
    """One tick of a periodic list: the Announcement for the list's local period and its email Delivery, or nothing when no item reached the bar."""
    if entry["cadence"] == "each":
        raise ValueError(f"{list_id} is an every-item list; it is woken by a Story, not a clock (announce_story).")
    rung = effective_rung(entry, policy_rung)
    if rung not in APPROVAL_OF_RUNG:
        return Result(None, BELOW_PREPARE, (list_id,))
    chosen = [candidate for candidate in candidates if qualifies(entry, candidate)[0]]
    if not chosen:
        return Result(None, NO_ITEMS, (list_id,))
    key = records.roundup_key(list_id, local_period(entry, scheduled_time))
    text = draft([(list_id, entry)], chosen)
    outcome = announcements.announce(dedupe_key=key, kind=ROUNDUP, stories=[candidate.story for candidate in chosen],
                                     plans=[email_plan(text, rung, [list_id], account_id=account_id, drafted_by=by)], created_by=by, trigger="schedule",
                                     release_at=scheduled_time, now=now)
    return Result(outcome, "decided" if outcome and outcome.created else "already decided for this period", (list_id,))


def announce_story(announcements: Announcements, lists: Mapping[str, Mapping[str, Any]], candidate: Candidate, *, draft: Drafter,
                   policy_rung: Callable[[str], str], account_id: str, by: str, now: str | None = None, trigger: str = "change") -> Result:
    """A Story's page went live, or its rating changed: the Announcement for the Story and one email Delivery for every every-item list that carries it.

    ``policy_rung`` answers the site policy's rung for a list id. A reader on two of the lists gets one message because the audience is one Delivery."""
    carried: dict[str, tuple[Mapping[str, Any], str]] = {}
    for list_id, entry in sorted(lists.items()):
        if entry["cadence"] != "each" or not qualifies(entry, candidate)[0]:
            continue
        rung = effective_rung(entry, policy_rung(list_id))
        if rung in APPROVAL_OF_RUNG:
            carried[list_id] = (entry, rung)
    if not carried:
        return Result(None, "no every-item list carries this Story at a rung that writes")
    approval = max((APPROVAL_OF_RUNG[rung] for _, rung in carried.values()), key=_STRICTNESS.__getitem__)
    strictest = next(rung for _, rung in carried.values() if APPROVAL_OF_RUNG[rung] == approval)
    list_ids = tuple(carried)
    text = draft([(list_id, entry) for list_id, (entry, _) in carried.items()], [candidate])
    outcome = announcements.announce(dedupe_key=records.story_published_key(candidate.story.lineage_id), kind=STORY_PUBLISHED, stories=[candidate.story],
                                     plans=[email_plan(text, strictest, list_ids, account_id=account_id, drafted_by=by, approval=approval)], created_by=by,
                                     trigger=trigger, now=now)
    return Result(outcome, "decided" if outcome and outcome.created else "already decided for this Story", list_ids)
