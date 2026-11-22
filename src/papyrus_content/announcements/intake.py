"""The one path that decides to announce a Story: floors, the source rule, then the review policy of each channel (PPY-97c0f2).

``announce_story`` is what the announce agent runs (and what a person's command runs) after the channels have said which of them qualify and made the words. It makes the
Announcement and its Deliveries through ``Announcements.announce`` and decides three things before it writes anything:

1. **The floors, under every policy.** A Story with no rating, or under three stars, is never announced; a rating of five counts only when a person gave it (a machine never
   supplies a five). Neither is a setting: no review value, override or source rule lowers them.
2. **The source rule, ``requireReviewedSource``.** When the site turned it on, an Announcement is made only for a Story a person has reviewed on its current version
   (a human review stamp, ``ReviewStamps``). An unreviewed Story leaves no row at all; the same call after the review makes it, once.
3. **The review policy of each channel** (``review_policy.choose``): the rung of the ``announce`` responsibility, narrowed by list, kind and channel. Each Delivery is
   written with the ``approval`` it gives and the ``approvalPolicy`` that says where it came from. A channel whose rung prepares no Delivery gets none, and the result says why.

A Story edited after a review loses the stamp: ``story_changed`` returns every Delivery that has not gone to a draft, and ``make_ready`` puts a draft back to ready only
while the rule is off or the new version has been reviewed again. Until then it waits, whatever its approval says (a ``none`` Delivery must not go out unreviewed on a site that
requires review).

**The human review stamp** is read from the checklist of the lineage being announced (``story_checklist.review_stamp``): its review step (``review_people``; for a
translation, its own ``human_review``, never the original's) is done against that lineage's CURRENT version number, by a person or by an agent on a person's recorded
instruction (the person and their words; a delegated stamp names the person). An agent alone cannot close the step at all (``delegation-required``). A later version
carries no stamp until the step is done again, and a waiting Announcement returns to waiting (PPY-473f8f).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from papyrus_content.agent_policy.resolve import PolicyState

from .decisions import Announcements, Outcome
from .deliveries import Plan
from .eligibility import StoryFacts
from .links import StoryRef
from .records import DRAFTED
from .review_policy import ReviewChoice, choose

#: The checklist step a person marks done when they have reviewed an original Story for readers (a translation's is ``human_review``).
REVIEW_STEP = "review_people"
QUALITY_FLOOR_STARS = 3
MAX_STARS = 5

# Why nothing was announced, as short codes the list and the commands show.
BELOW_FLOOR, MACHINE_FIVE, NOT_REVIEWED, NO_DELIVERY = "below_floor", "machine_five", "story_not_reviewed", "no_delivery"


class ReviewStamps(Protocol):
    def reviewed(self, lineage_id: str, version_number: int) -> bool:
        """Whether a person has reviewed this version of the Story."""


class ChecklistReviewStamps:
    """The stamp read from the checklist of the lineage asked about (``story_checklist.lineage_review_stamp``): one index read by parent. A person's mark, or an
    agent's on a person's recorded instruction, counts only on the version it was made against; an agent's mark with no instruction never counts, and neither does
    a step that is open again."""

    def __init__(self, client: Any):
        self.client = client

    def reviewed(self, lineage_id: str, version_number: int) -> bool:
        from papyrus_content.story_checklist import lineage_review_stamp

        return lineage_review_stamp(self.client, lineage_id, version_number) is not None


@dataclass(frozen=True)
class Target:
    """One channel the Announcement may go to, with the words already made for it. The channel rules (does it qualify, how long may it be) are the channel's own."""

    channel: str
    account_id: str
    text: str
    list_id: str | None = None
    audience: Sequence[str] = ()
    image_key: str | None = None
    lock_at: str | None = None


@dataclass(frozen=True)
class Held:
    """Something that was not done, in plain words: ``code`` is the short form, ``channel`` is set when only one channel was left out."""

    code: str
    reason: str
    channel: str | None = None


@dataclass
class Intake:
    outcome: Outcome | None = None
    held: list[Held] = field(default_factory=list)
    choices: dict[str, ReviewChoice] = field(default_factory=dict)   # the review each prepared channel got, by channel

    @property
    def announced(self) -> bool:
        return self.outcome is not None


def floor_refusal(story: StoryFacts) -> Held | None:
    """The two floors no setting lowers. None when the Story clears both."""
    if story.stars < QUALITY_FLOOR_STARS:
        word = "is unrated" if story.stars == 0 else f"has {story.stars} stars"
        return Held(BELOW_FLOOR, f"{story.lineage_id} {word}; nothing under three stars is announced, under any review policy.")
    if story.stars == MAX_STARS:
        from papyrus_content.priming_export import machine_story_actor

        if machine_story_actor(story.rated_by):
            return Held(MACHINE_FIVE, f"{story.lineage_id} has five stars that a person did not give; a machine never supplies a five, so it is not announced.")
    return None


def story_ref(story: StoryFacts) -> StoryRef:
    return StoryRef(story.lineage_id, story.item_id, story.version_number)


def announce_story(
    announcements: Announcements, policy: PolicyState, stamps: ReviewStamps, stories: Sequence[StoryFacts], *, dedupe_key: str, kind: str, targets: Sequence[Target],
    require_reviewed_source: bool, created_by: str, trigger: str, release_at: str | None = None, now: str | None = None,
) -> Intake:
    """Decide to announce ``stories`` on ``targets``. Writes nothing when a floor or the source rule says no, or when no channel's rung prepares a Delivery."""
    result = Intake()
    for story in stories:
        refused = floor_refusal(story)
        if refused:
            result.held.append(refused)
    if result.held:
        return result
    if require_reviewed_source:
        unreviewed = [story for story in stories if not stamps.reviewed(story.lineage_id, story.version_number)]
        if unreviewed:
            names = ", ".join(f"{story.lineage_id} version {story.version_number}" for story in unreviewed)
            result.held.append(Held(NOT_REVIEWED, f"{names} has not been reviewed by a person, and this publication announces only reviewed Stories."))
            return result
    plans: list[Plan] = []
    for target in targets:
        choice = choose(policy, channel=target.channel, kind=kind, list_id=target.list_id)
        if not choice.prepares:
            result.held.append(Held(NO_DELIVERY, str(choice.reason), target.channel))
            continue
        result.choices[target.channel] = choice
        plans.append(Plan(channel=target.channel, account_id=target.account_id, approval=str(choice.approval), approval_policy=choice.policy, text=target.text,
                          audience=target.audience, image_key=target.image_key, lock_at=target.lock_at))
    result.outcome = announcements.announce(dedupe_key=dedupe_key, kind=kind, stories=[story_ref(story) for story in stories], plans=plans, created_by=created_by, trigger=trigger,
                                            release_at=release_at, now=now)
    return result


def story_changed(announcements: Announcements, announcement: Mapping[str, Any], story: StoryFacts, *, by: str, now: str | None = None) -> list[dict[str, Any]]:
    """A newer version of a Story the Announcement is about: every Delivery that has not gone returns to a draft and waits again, with the policy it was created under."""
    return announcements.story_changed(announcement, story_ref(story), by=by, now=now)


def make_ready(announcements: Announcements, stamps: ReviewStamps, announcement: Mapping[str, Any], stories: Sequence[StoryFacts], *, require_reviewed_source: bool, by: str,
               now: str | None = None) -> tuple[list[dict[str, Any]], list[Held]]:
    """The words of each drafted Delivery are made and checked again: it goes back to ready, unless the site requires review and a Story has no stamp on its current version.
    Returns the Deliveries now ready and what still waits, in words."""
    waiting = [story for story in stories if require_reviewed_source and not stamps.reviewed(story.lineage_id, story.version_number)]
    ready: list[dict[str, Any]] = []
    held: list[Held] = []
    for row in announcements.deliveries.live_for_announcement(announcement["id"]):
        if row.get("state") != DRAFTED:
            continue
        if waiting:
            held.append(Held(NOT_REVIEWED, f"{row['channel']} waits: {', '.join(story.lineage_id for story in waiting)} was changed after its review and has not been reviewed again.", row["channel"]))
            continue
        ready.append(announcements.deliveries.mark_ready(row, by=by, now=now))
    return ready, held
