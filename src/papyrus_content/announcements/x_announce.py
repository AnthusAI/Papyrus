"""X on the Announcement and Delivery records: which Stories qualify, the draft and its checks, a dry run, and a blocked draft that asks once (PPY-efd06c).

X is one channel of an Announcement, not a row shape of its own. When a Story's page goes live or its rating changes, the announce agent asks this module whether the Story qualifies on X
and, if it does, for the one X Delivery to write beside the Story's other Deliveries (``list_cadence/story_wake.py``): the Announcement is made together with its first Delivery, and a later
rating that reaches the floor adds the X Delivery to the Announcement that already exists.

**What decides whether X gets a Delivery, in this order** (the answer is a short code and plain words, never a row):

1. the site's mode (``off`` is the default and makes nothing; X is off everywhere until the owner turns it on);
2. the channel's own rules: published, not retired, a Story, its type and section, and the bar (``eligibility.refusal``; the bar is never under three stars, and an unrated Story or a
   model's prediction never qualifies, because only the effective human rating counts);
3. the floors under every policy: nothing under three stars, and a five only when a person gave it (``intake.floor_refusal``);
4. the account: a Delivery names its account, so a site with no connected X account gets none;
5. the source rule (``requireReviewedSource``) and the review policy of the channel (``review_policy.choose``): below ``prepare`` prepares nothing.

**The draft.** One model call from the Story's title, dek and summary under the site's writing guidelines, then every check (``drafting.check_draft``). The post exactly as it will go is the
Delivery's words. A draft that fails a check is a Delivery that is **blocked: check failed** and raises **one** review request for the Announcement (``blocked_drafts.block_and_flag``), and
it is not drafted again until an input changes: the Story's version or the guidelines (``revisit``). The inputs a draft was written under are recorded with its checks.

**A dry run** builds the Delivery, runs every check and sends nothing: its state is ``dry_run`` and its cost is 0. It never reaches a channel.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from papyrus_content import fact_check
from papyrus_content.agent_policy.resolve import PolicyState

from . import blocked_drafts
from .decisions import Outcome
from .deliveries import Deliveries, Plan
from .delivery_versions import Versions
from .drafting import Draft, DraftRefused, Llm, RuleLane, draft_announcement
from .eligibility import StoryFacts, refusal
from .learned_examples import Read
from .intake import NOT_REVIEWED, NO_DELIVERY, PROVISIONAL_NOTE, Held, ReviewStamps, floor_refusal
from .post import tagged_link
from .records import BLOCKED, DRAFTED, READY, json_list
from .review_policy import choose
from .rules import DRY_RUN, OFF, view

CHANNEL = "x"
STORY_PUBLISHED = "story_published"
NO_ACCOUNT = "no_account"
#: The name of the line among a Delivery's checks that records what the draft was written under. It is not a check of the words: it is always ``passed``.
INPUTS = "inputs"


@dataclass
class XServices:
    """What the X part of a wake reaches outside itself for. A test replaces each one."""

    #: ``() -> settings document`` (``settings.AnnouncementSettings.read``) and ``() -> the X connection's status`` (``x_account.XAccounts.status``).
    settings: Callable[[], Mapping[str, Any]]
    connection: Callable[[], Mapping[str, Any]]
    #: ``lineage -> the Story's facts as they are now``.
    story: Callable[[str], StoryFacts]
    #: ``() -> the site's public address``; asked only when a link is built, so a site that never drafts needs none.
    site_origin: Callable[[], str]
    #: ``story -> the writing guidelines and announcement rules the draft is written under``.
    guidelines_for: Callable[[StoryFacts], str]
    llm: Llm | None = None
    judge: fact_check.Judge | None = None
    rule_lane: RuleLane | None = None
    model: str = ""
    #: ``() -> what people's edits taught for X`` (``learned_examples.load``): the active examples, newest first within the budget. None for a site that has none to read.
    learned: Callable[[], Read] | None = None
    #: ``story -> the guideline layers the draft was written under`` (``{scope, itemId, versionNumber, contentHash}``), recorded so the draft is explainable. None when unknown.
    guideline_layers: Callable[[StoryFacts], list[dict[str, Any]]] | None = None


@dataclass
class Prepared:
    """What the X part decided for one Story: the Delivery to write (``plan``), or why there is none (``held``). ``problems`` are the failed checks of a draft that is to be blocked."""

    plan: Plan | None = None
    held: Held | None = None
    problems: list[str] | None = None
    dry_run: bool = False

    @property
    def writes(self) -> bool:
        return self.plan is not None


def settings_view(services: XServices) -> dict[str, Any]:
    return view(services.settings(), services.connection())


def inputs_of(story: StoryFacts, guidelines: str, model: str, *, layers: list[dict[str, Any]] | None = None, learned: Read | None = None) -> dict[str, Any]:
    """What a draft is written under: the Story's version, a fingerprint of the guidelines, the guideline layers it read (id, version and hash of each) and the examples it read (the
    Delivery of each). When the Story, the guidelines or the examples change, a blocked draft is drafted again; otherwise it never is. ``papyrus announcements explain --delivery`` prints this."""
    return {"name": INPUTS, "passed": True, "storyVersion": story.version_number, "guidelines": hashlib.sha256(guidelines.encode("utf-8")).hexdigest()[:16], "model": model,
            "guidelineLayers": list(layers or []), "examples": learned.ids if learned else []}


def _read(services: XServices) -> Read:
    return services.learned() if services.learned is not None else Read()


def _layers(services: XServices, story: StoryFacts) -> list[dict[str, Any]]:
    return services.guideline_layers(story) if services.guideline_layers is not None else []


def recorded_inputs(row: Mapping[str, Any]) -> dict[str, Any] | None:
    return next((check for check in json_list(row.get("checks")) if check.get("name") == INPUTS), None)


def failed_problems(row: Mapping[str, Any]) -> list[str]:
    """The problems of the checks that failed, in the words they were recorded in."""
    return [problem for check in json_list(row.get("checks")) if check.get("passed") is False for problem in check.get("problems") or []]


def _checks(draft: Draft | None, inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [*([{"name": check["name"], "passed": check["passed"], "problems": list(check.get("problems") or [])} for check in draft.checks] if draft else []), dict(inputs)]


def _draft(services: XServices, story: StoryFacts, link: str, guidelines: str, learned: Read) -> tuple[Draft | None, list[str]]:
    """One model call and every check. A site that cannot even try (no writing guidelines) has no draft and says why."""
    if services.llm is None or services.judge is None:
        raise RuntimeError("Drafting needs a model: the X part of the announce agent was built without one.")
    try:
        draft = draft_announcement(story, link, guidelines=guidelines, llm=services.llm, judge=services.judge, rule_lane=services.rule_lane, model=services.model, learned=learned.prompt)
    except DraftRefused as refused:
        return None, [str(refused)]
    return draft, ([] if draft.passed else draft.failures)


def prepare(services: XServices, story: StoryFacts, policy: PolicyState, stamps: ReviewStamps) -> Prepared:
    """Decide whether X gets a Delivery for this Story now, and if so build it (the one model call is here). Writes nothing."""
    settings = settings_view(services)
    if settings["mode"] == OFF:
        return Prepared(held=Held("off", "Announcements are off for this publication, so nothing is announced on X.", CHANNEL))
    stopped = refusal(story, settings)
    if stopped:
        return Prepared(held=Held(stopped[0], stopped[1], CHANNEL))
    floor = floor_refusal(story)
    if floor:
        return Prepared(held=Held(floor.code, floor.reason, CHANNEL))
    if not settings["accountId"]:
        return Prepared(held=Held(NO_ACCOUNT, "No X account is connected to this site, so there is no account to post from.", CHANNEL))
    if settings["requireReviewedSource"] and not stamps.reviewed(story.lineage_id, story.version_number):
        return Prepared(held=Held(NOT_REVIEWED, f"{story.lineage_id} version {story.version_number} has not been reviewed by a person, and this publication announces only reviewed Stories. {PROVISIONAL_NOTE}", CHANNEL))
    choice = choose(policy, channel=CHANNEL, kind=STORY_PUBLISHED)
    if not choice.prepares:
        return Prepared(held=Held(NO_DELIVERY, str(choice.reason), CHANNEL))
    link = tagged_link(services.site_origin().rstrip("/") + story.path)
    guidelines = services.guidelines_for(story)
    learned = _read(services)
    draft, problems = _draft(services, story, link, guidelines, learned)
    checks = _checks(draft, inputs_of(story, guidelines, services.model, layers=_layers(services, story), learned=learned))
    text = draft.post if draft is not None and draft.text else ""
    plan = Plan(channel=CHANNEL, account_id=str(settings["accountId"]), approval=str(choice.approval), approval_policy=choice.policy, text=text, drafted_by="machine", checks=checks,
                state=READY if not problems else DRAFTED)
    return Prepared(plan=plan, problems=problems or None, dry_run=settings["mode"] == DRY_RUN)


def after_announce(deliveries: Deliveries, prepared: Prepared, outcome: Outcome, *, by: str, now: str | None = None) -> dict[str, Any] | None:
    """The Delivery was written with the Announcement: a draft that failed its checks is blocked and asks once, and a dry run is finished as one. Returns the X Delivery as it stands.

    Safe to call again after a crash: a Delivery that is already blocked or already a dry run is left as it is, and the Announcement's flag is raised once."""
    plan = prepared.plan
    row = next((delivery for delivery in outcome.deliveries if (delivery["channel"], delivery["accountId"]) == (plan.channel, plan.account_id)), None) if plan else None
    if row is None:
        return None
    if prepared.problems and row.get("state") in (DRAFTED, READY):
        row, _ = blocked_drafts.block_and_flag(deliveries, row, problems=prepared.problems, by=by, now=now)
    elif prepared.dry_run and row.get("state") == READY:
        row = deliveries.mark_dry_run(row, by=by, now=now)
    return row


def finish(deliveries: Deliveries, row: Mapping[str, Any], settings: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
    """What a crash may have left of an X Delivery that exists: a draft whose failed checks never blocked it (it blocks and asks once now), or a ready Delivery of a site in dry run
    (it is finished as one). Anything else is returned as it is."""
    problems = failed_problems(row)
    if row.get("state") == DRAFTED and problems:
        blocked, _ = blocked_drafts.block_and_flag(deliveries, row, problems=problems, by=by, now=now)
        return blocked
    if row.get("state") == READY and settings["mode"] == DRY_RUN and not row.get("attempts"):
        return deliveries.mark_dry_run(row, by=by, now=now)
    return dict(row)


def revisit(services: XServices, deliveries: Deliveries, row: Mapping[str, Any], story: StoryFacts, *, by: str, now: str | None = None) -> tuple[dict[str, Any], str]:
    """An X Delivery that was blocked because its checks failed, and the Story woke the agent again. It is drafted again only when an input changed: the Story's version, or the
    guidelines. Otherwise nothing is done (no model call, no second flag). Returns the Delivery as it stands and what was done: ``unchanged``, ``redrafted`` or ``still blocked``."""
    if not blocked_drafts.blocked_for_check(row):
        return dict(row), "not blocked"
    link = tagged_link(services.site_origin().rstrip("/") + story.path)
    guidelines = services.guidelines_for(story)
    learned = _read(services)
    inputs = inputs_of(story, guidelines, services.model, layers=_layers(services, story), learned=learned)
    earlier = recorded_inputs(row) or {}
    if (earlier.get("storyVersion"), earlier.get("guidelines"), earlier.get("examples") or []) == (inputs["storyVersion"], inputs["guidelines"], inputs["examples"]):
        return dict(row), "unchanged"
    draft, problems = _draft(services, story, link, guidelines, learned)
    checks = _checks(draft, inputs)
    if problems:
        # Drafted again, and still failing: the new problems and the inputs are recorded so this is not tried again until they change. The Announcement's one flag stands.
        return deliveries._change(row, {"checks": checks}, by=by, note="drafted again after its inputs changed; the checks still fail: " + "; ".join(problems), now=now), "still blocked"
    plan = Plan(channel=CHANNEL, account_id=row["accountId"], approval=row["approval"], approval_policy=row["approvalPolicy"], text=draft.post, drafted_by="machine", checks=checks)
    if row.get("textKey"):
        saved = Versions(deliveries).redraft(row["id"], replaces=int(row["version"]), text=draft.post, by=by, checks=checks, now=now)
        if saved.dropped:
            return saved.row, "still blocked"
        written = saved.row
    else:
        written = deliveries.write_words(row, plan, by=by, now=now)
    if written.get("state") == BLOCKED:
        written = deliveries.resume(written, by=by, now=now)
    if settings_view(services)["mode"] == DRY_RUN and written.get("state") == READY:
        written = deliveries.mark_dry_run(written, by=by, now=now)
    return written, "redrafted"


@dataclass
class Considered:
    """What the announce agent decided about X for one Story in one wake: a new Delivery to write (``prepared``), or the Delivery X already has (``existing``), or why there is none."""

    lineage: str
    prepared: Prepared | None = None
    existing: Mapping[str, Any] | None = None

    @property
    def plans(self) -> list[Plan]:
        return [self.prepared.plan] if self.prepared is not None and self.prepared.plan is not None else []


class XAnnouncer:
    """The X part of one announce wake. A Delivery is drafted once, when its channel first qualifies: a Story whose Announcement already has an X Delivery is never drafted for again
    here, whatever woke the agent (a blocked draft is drafted again only by ``revisit``, when an input changed)."""

    def __init__(self, services: XServices, announcements: Any, policy: PolicyState, stamps: ReviewStamps, *, by: str = "announce"):
        self.services, self.announcements, self.policy, self.stamps, self.by = services, announcements, policy, stamps, by

    @property
    def deliveries(self) -> Deliveries:
        return self.announcements.deliveries

    def consider(self, lineage: str) -> Considered:
        from .records import announcement_id, story_published_key

        key = story_published_key(lineage)
        if self.announcements.by_dedupe_key(key) is not None:
            rows = [row for row in self.deliveries.for_announcement(announcement_id(key)) if row["channel"] == CHANNEL]
            if rows:
                return Considered(lineage, existing=max(rows, key=lambda row: int(row["generation"])))
        return Considered(lineage, prepared=prepare(self.services, self.services.story(lineage), self.policy, self.stamps))

    def finished(self, considered: Considered, outcome: Outcome | None, *, now: str | None = None) -> tuple[list[str], bool]:
        """After the Announcement was written: block and flag a draft that failed, finish a dry run, or look again at what exists. Returns what was done, in words, and whether
        anything was written."""
        said: list[str] = []
        worked = False
        prepared = considered.prepared
        if prepared is not None and prepared.writes and outcome is not None:
            row = after_announce(self.deliveries, prepared, outcome, by=self.by, now=now)
            if row is not None:
                worked = True
                said.append(f"x: {row['state']}" + (f" ({row['blockedReason']})" if row.get("blockedReason") else ""))
        elif prepared is not None and prepared.held is not None:
            said.append(f"x: not announced ({prepared.held.code}): {prepared.held.reason}")
        if considered.existing is not None:
            row = finish(self.deliveries, considered.existing, settings_view(self.services), by=self.by, now=now)
            if blocked_drafts.blocked_for_check(row):
                row, did = revisit(self.services, self.deliveries, row, self.services.story(considered.lineage), by=self.by, now=now)
                worked = worked or did in ("redrafted", "still blocked")
                said.append(f"x: blocked draft, {did}")
            elif row.get("state") != considered.existing.get("state"):
                worked = True
                said.append(f"x: {row['state']}")
        return said, worked
