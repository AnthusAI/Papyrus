"""Every cadence makes the same two records: an Announcement (model ``AnnouncementDecision``) and an email Delivery (slice N1, PPY-4d74d9).

* A periodic list (``daily``, ``weekly``) is woken by its schedule entry. The once-only key is ``roundup:<list>:<local period>`` (``records.roundup_key``): the
  local date for a daily list, the local ISO week for a weekly one, so a second tick for the same period finds the same Announcement, and a changed send time
  cannot make a second one for a period that has one. When a period's Announcement exists, the list's earlier issues that never went are cancelled and their items carry forward
  (``periods.py``).
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
from papyrus_content.announcements import edit_windows, records
from papyrus_content.announcements.decisions import Announcements, Outcome
from papyrus_content.announcements.deliveries import Plan
from papyrus_content.images.handlers import Caller
from papyrus_content.announcements.links import StoryRef
from papyrus_content.run_outcomes import OUTCOME_KEY, REASON_KEY

from .alert_text import rule_matches
from .periods import History, carry_forward
from .settings import QUALITY_FLOOR_STARS

CHANNEL = "email"
ROUNDUP, STORY_PUBLISHED = "roundup", "story_published"
APPROVAL_OF_RUNG = {"prepare": records.HARD, "publish_soft": records.SOFT, "publish_auto": records.NONE}
#: How restrictive an approval is, so one Delivery for several lists takes the most restrictive of them.
_STRICTNESS = {records.NONE: 0, records.SOFT: 1, records.HARD: 2}

NO_ITEMS = "no items reached the list's bar"
BELOW_PREPARE = "the rung is below prepare, so nothing is made"
DRAFT_WAITING = "no items reached the list's bar; a draft waits for a person to write it"
#: The reason codes a run that made nothing records (``run_outcomes.REASON_CODE``): Today shows them beside "Nothing to do".
NO_ITEMS_CODE, BELOW_PREPARE_CODE, ALREADY_DECIDED_CODE, NO_LIST_CODE = "no_items_reached_bar", "rung_below_prepare", "already_decided", "no_list_carries_story"


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
    translation: bool = False   # a translation is no new Story: the readers were told when the original published, so it is never announced


@dataclass(frozen=True)
class Result:
    """What a wake did. ``outcome`` is None when nothing was written, and ``reason`` says why in words."""

    outcome: Outcome | None
    reason: str
    list_ids: tuple[str, ...] = ()
    cancelled: tuple[str, ...] = ()   # the once-only keys of earlier issues that never went and were cancelled so their items carry forward
    code: str | None = None           # why nothing was made, as the run record's reason code; None when something was made
    added: tuple[str, ...] = ()       # the channels whose Delivery this call added to an Announcement that already existed (a later rating reached the X floor)
    notes: tuple[str, ...] = ()       # what the other channels did, in words (X: blocked, dry run, held and why)
    worked: bool = False              # a channel's Delivery was written or changed without a new Announcement (a blocked draft drafted again, a crash finished)

    def declaration(self) -> dict[str, str]:
        """What the run's output tells the runner (``run_outcomes.declared_outcome``): nothing when it made or cancelled something (it did its work), and otherwise
        ``nothing`` with the reason code, so Today shows the run as nothing to do and why."""
        if (self.outcome is not None and self.outcome.created) or self.cancelled or self.added or self.worked:
            return {}
        assert self.code, f"a run that made nothing says why: {self.reason!r}"
        return {OUTCOME_KEY: "nothing", REASON_KEY: self.code}


@dataclass(frozen=True)
class PersonNote:
    """Words a person wrote for a period's issue. Only a person's own content makes an otherwise empty period an issue: an agent's text is never one."""

    by: str
    text: str


class IssueNoteError(ValueError):
    """A note that cannot be written into an issue, in plain words."""


Drafter = Callable[[Sequence[tuple[str, Mapping[str, Any]]], Sequence[Candidate], Sequence[PersonNote]], str]


def settings_of(edit_settings: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None) -> Mapping[str, Any]:
    """The announcement settings document the edit windows are read from: given as it is, or as a reader that is called only when a Delivery is about to be made (a run
    that makes nothing reads nothing)."""
    if callable(edit_settings):
        return edit_settings()
    return edit_settings or {}


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


def email_plan(text: str, rung: str, list_ids: Sequence[str], *, account_id: str, drafted_by: str, approval: str | None = None, state: str = records.READY) -> Plan:
    """The one shape of an email Delivery, for every cadence. A draft waiting for a person's words has none (``text`` is empty) and is not ready."""
    return Plan(channel=CHANNEL, account_id=account_id, approval=approval or APPROVAL_OF_RUNG[rung], approval_policy=f"rung {rung} (list {', '.join(list_ids)})",
                text=text, audience=tuple(list_ids), drafted_by=drafted_by, state=state)


def announce_period(announcements: Announcements, list_id: str, entry: Mapping[str, Any], scheduled_time: str, candidates: Sequence[Candidate], *,
                    history: History, notes: Sequence[PersonNote] = (), draft: Drafter, policy_rung: str, account_id: str, by: str, now: str | None = None,
                    edit_settings: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None) -> Result:
    """One tick of a periodic list: the Announcement for the list's local period and its email Delivery, or nothing when the period is empty.

    ``candidates`` are the Stories that qualified since the list's last sent issue (``history.last_sent_at``), so what an earlier issue did not send is in them, and
    ``notes`` are words a person wrote for the period. A period with neither is empty: by default nothing is made and the run says so; a list set to ``draft_only``
    makes the draft instead, with no words, for a person to write, and it goes only when one does (``add_note``). No placeholder issue is ever made. Once this
    period's Announcement exists (made now or by an earlier call), each earlier issue of the list that never went is cancelled and its items are eligible here again;
    a retry after a crash between the two finishes the cancelling."""
    if entry["cadence"] == "each":
        raise ValueError(f"{list_id} is an every-item list; it is woken by a Story, not a clock (announce_story).")
    rung = effective_rung(entry, policy_rung)
    if rung not in APPROVAL_OF_RUNG:
        return Result(None, BELOW_PREPARE, (list_id,), code=BELOW_PREPARE_CODE)
    chosen = [candidate for candidate in candidates if qualifies(entry, candidate)[0]]
    empty = not chosen and not notes
    if empty and entry["emptyPeriod"] != "draft_only":
        return Result(None, NO_ITEMS, (list_id,), code=NO_ITEMS_CODE)
    key = records.roundup_key(list_id, local_period(entry, scheduled_time))
    if empty:
        plan = email_plan("", rung, [list_id], account_id=account_id, drafted_by=by, state=records.DRAFTED)
    else:
        plan = email_plan(draft([(list_id, entry)], chosen, notes), rung, [list_id], account_id=account_id, drafted_by=by)
    now = now or records.now_iso()
    # The issue goes at the list's scheduled time; the edit window gives its lock time (the lead before it), as data from the announcement settings.
    release, plans = edit_windows.apply(settings_of(edit_settings), ROUNDUP, [plan], now=now, release_at=scheduled_time)
    outcome = announcements.announce(dedupe_key=key, kind=ROUNDUP, stories=[candidate.story for candidate in chosen], plans=plans, created_by=by, trigger="schedule",
                                     release_at=release, now=now, stories_optional=not chosen)
    cancelled = carry_forward(announcements, history, key, scheduled_time, by=by, now=now)
    if outcome and outcome.created:
        return Result(outcome, DRAFT_WAITING if empty else "decided", (list_id,), cancelled)
    return Result(outcome, "already decided for this period", (list_id,), cancelled, ALREADY_DECIDED_CODE)


def add_note(announcements: Announcements, list_id: str, entry: Mapping[str, Any], scheduled_time: str, caller: Caller, text: str, *, draft: Drafter, policy_rung: str,
             account_id: str, now: str | None = None) -> Result:
    """A person writes into the period's draft: the draft gets its words, as an edit of the same Delivery (ready), and from then on it is an
    issue like any other: the list's rung decides whether it needs approval. Only a person's own words count, and only a draft that has none yet is written into; an
    issue that has words is changed like any other."""
    if caller.kind != "person":
        raise IssueNoteError("Only a person's own words make an empty period an issue; an agent's are not content.")
    if not isinstance(text, str) or not text.strip():
        raise IssueNoteError("A note needs words.")
    rung = effective_rung(entry, policy_rung)
    if rung not in APPROVAL_OF_RUNG:
        raise IssueNoteError(BELOW_PREPARE.capitalize() + ".")
    key = records.roundup_key(list_id, local_period(entry, scheduled_time))
    announcement = announcements.by_dedupe_key(key)
    if announcement is None or announcement["state"] not in (records.PLANNED, records.RELEASED):
        raise IssueNoteError(f"There is no open issue {key} to write into: an empty period makes a draft only on a list set to draft_only.")
    (delivery,) = [row for row in announcements.deliveries.live_for_announcement(announcement["id"]) if row["channel"] == CHANNEL and row["accountId"] == account_id]
    if delivery.get("textKey") or delivery["state"] != records.DRAFTED:
        raise IssueNoteError(f"{key} already has its words; a change to it is an edit of its words, or a correction once it was sent.")
    words = draft([(list_id, entry)], [], [PersonNote(caller.subject, text.strip())])
    written = announcements.deliveries.write_words(delivery, email_plan(words, rung, [list_id], account_id=account_id, drafted_by=caller.subject), by=caller.subject, now=now)
    return Result(Outcome(announcement, [written], False), "a person wrote the issue", (list_id,))


def announce_story(announcements: Announcements, lists: Mapping[str, Mapping[str, Any]], candidate: Candidate, *, draft: Drafter,
                   policy_rung: Callable[[str], str], account_id: str, by: str, now: str | None = None, trigger: str = "change",
                   extra_plans: Sequence[Plan] = (), edit_settings: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None) -> Result:
    """A Story's page went live, or its rating changed: the Announcement for the Story, one email Delivery for every every-item list that carries it, and the Deliveries other channels
    qualified for (``extra_plans``: X, ``x_announce``).

    ``policy_rung`` answers the site policy's rung for a list id. A reader on two of the lists gets one message because the audience is one Delivery. Each channel's plan gets its release
    and lock times from the site's edit windows (``edit_settings`` is the announcement settings document; ``edit_windows.apply``). The same once-only key finds the Announcement a
    wake made earlier, so a channel that qualifies later (a rating that reached X's floor) adds its Delivery to it."""
    carried: dict[str, tuple[Mapping[str, Any], str]] = {}
    for list_id, entry in sorted(lists.items()):
        if entry["cadence"] != "each" or not qualifies(entry, candidate)[0]:
            continue
        rung = effective_rung(entry, policy_rung(list_id))
        if rung in APPROVAL_OF_RUNG:
            carried[list_id] = (entry, rung)
    if not carried and not extra_plans:
        return Result(None, "no every-item list carries this Story at a rung that writes", code=NO_LIST_CODE)
    plans: list[Plan] = list(extra_plans)
    list_ids: tuple[str, ...] = ()
    if carried:
        approval = max((APPROVAL_OF_RUNG[rung] for _, rung in carried.values()), key=_STRICTNESS.__getitem__)
        strictest = next(rung for _, rung in carried.values() if APPROVAL_OF_RUNG[rung] == approval)
        list_ids = tuple(carried)
        text = draft([(list_id, entry) for list_id, (entry, _) in carried.items()], [candidate], ())
        plans.insert(0, email_plan(text, strictest, list_ids, account_id=account_id, drafted_by=by, approval=approval))
    now = now or records.now_iso()
    key = records.story_published_key(candidate.story.lineage_id)
    before = {row["id"] for row in announcements.deliveries.for_announcement(records.announcement_id(key))}
    release, plans = edit_windows.apply(settings_of(edit_settings), STORY_PUBLISHED, plans, now=now)
    outcome = announcements.announce(dedupe_key=key, kind=STORY_PUBLISHED, stories=[candidate.story], plans=plans, created_by=by, trigger=trigger, release_at=release, now=now)
    if outcome and outcome.created:
        return Result(outcome, "decided", list_ids)
    added = tuple(sorted(row["channel"] for row in (outcome.deliveries if outcome else []) if row["id"] not in before))
    if added:
        return Result(outcome, "added " + ", ".join(added) + " to the Announcement that already exists", list_ids, added=added)
    return Result(outcome, "already decided for this Story", list_ids, code=ALREADY_DECIDED_CODE)
