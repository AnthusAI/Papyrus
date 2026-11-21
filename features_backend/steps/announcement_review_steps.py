"""Per-publication announcement review (features_backend/announcement-review-*.feature, PPY-97c0f2).

The policy is the real agent policy store over in-memory storage (the ``announce`` rung and its overrides), the records are the Announcement and Delivery records over the
in-memory backend of the records specs, and every Announcement is made through ``intake.announce_story``. A person's and an agent's calls go through ``execute``, the one door.
"""
from __future__ import annotations

import sys
from pathlib import Path

import parse
from behave import given, register_type, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_checklist as checklist  # noqa: E402
from papyrus_content.agent_gate import GateRun  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.announcements import intake, review_handlers, review_policy  # noqa: E402
from papyrus_content.announcements.eligibility import StoryFacts  # noqa: E402
from papyrus_content.images.handlers import Caller, Outcome, execute  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

@parse.with_pattern(r'[^"]*')
def _quoted(text):
    return text


register_type(R=_quoted)

TENANT = "alpha"
ADMIN = Caller(kind="person", subject="ada", is_admin=True)
EDITOR = Caller(kind="person", subject="ellie", is_admin=False)
CREATED_BY = "announce agent"
SETTLED_BY = {"person": "a person", "machine": "a machine"}


class ChecklistClient:
    """Just the three calls the checklist makes to write and read one sub-task Item: the real stamp reader runs over it."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def create_record(self, model, record):
        self.rows[record["id"]] = record

    def update_record(self, model, record):
        self.rows[record["id"]].update(record)

    def list_by_index(self, index, partition, **_):
        assert index == checklist.INDEX
        return [row for row in self.rows.values() if row.get("parentLineageId") == partition]


class ChecklistStamps(intake.ChecklistReviewStamps):
    """PROVISIONAL human review stamp, read the way production reads it (``intake.ChecklistReviewStamps``): a Story's checklist step ``review_people`` done by a person
    against the Story's current version. Ryan has not confirmed this definition. ``mark`` is what a person or an agent does to the step."""

    def __init__(self) -> None:
        super().__init__(ChecklistClient())

    def mark(self, lineage_id: str, version: int, state: str, actor_kind: str) -> None:
        row = checklist._apply(checklist._new_row(lineage_id, intake.REVIEW_STEP), state, {"kind": actor_kind, "label": "Someone"}, "2026-11-16T10:00:00Z",
                               note="read it", story_version=version)
        checklist._write(self.client, row)


def _fresh_policy(context):
    context.s3, context.catalogue = FakeS3(), FakeTable()
    clock = iter(f"2026-11-16T00:{minute:02d}:00Z" for minute in range(60))
    context.policy = AgentPolicyStore(SiteStore(context.s3, "bucket", context.catalogue, now=lambda: next(clock)))
    context.require_reviewed = False
    context.stamps = ChecklistStamps()
    context.facts = {}
    context.intake = None
    context.writes = 0
    context.backend.tenant_id = TENANT


def _scope(dimension, value):
    return {dimension: value} if dimension else None


def _seed(context, approval, scope=None, reason="Seed"):
    """Write the rung straight into the policy document, as an admin's saved document would hold it, so every value (``none`` too) can be a site's data."""
    context.policy.set_rung(TENANT, ADMIN, review_policy.RESPONSIBILITY, review_policy.RUNG_OF[approval], reason=reason, scope=scope)


# --- the publication's policy -----------------------------------------------------------------------------------------------------------------------


@given('a publication whose announcement review is "{approval:R}"')
def publication_review(context, approval):
    _fresh_policy(context)
    _seed(context, approval)


@given("a publication with no announcement review set")
def publication_without_review(context):
    _fresh_policy(context)


@given('a publication whose announce agent is at the rung "{rung:R}"')
def publication_at_rung(context, rung):
    _fresh_policy(context)
    context.policy.set_rung(TENANT, ADMIN, review_policy.RESPONSIBILITY, rung, reason="Seed")


@given('the announcement review for the channel "{channel:R}" is "{approval:R}"')
def channel_review(context, channel, approval):
    _seed(context, approval, {"channel": channel})


@given('the announcement review for the kind "{kind:R}" is "{approval:R}"')
def kind_review(context, kind, approval):
    _seed(context, approval, {"kind": kind})


@given('the announcement review for the list "{list_id:R}" is "{approval:R}"')
def list_review(context, list_id, approval):
    _seed(context, approval, {"list": list_id})


@given('the announcement review where the kind is "{kind:R}" and the channel is "{channel:R}" is "{approval:R}"')
def channel_kind_review(context, channel, kind, approval):
    _seed(context, approval, {"channel": channel, "kind": kind})


@given("the publication announces only Stories a person has reviewed")
def requires_review(context):
    context.require_reviewed = True


@given("the publication does not require a review before it announces")
def does_not_require_review(context):
    context.require_reviewed = False


@given("the publication starts from the settings of a new publication")
def new_publication(context):
    _fresh_policy(context)
    _seed(context, review_policy.APPROVAL_OF[review_policy.NEW_PUBLICATION["announce"]["rung"]])
    context.require_reviewed = review_policy.NEW_PUBLICATION["requireReviewedSource"]


@given("the publication starts from the settings of Machines on Machines")
def machines_on_machines(context):
    _fresh_policy(context)
    entry = review_policy.MACHINES_ON_MACHINES["announce"]
    _seed(context, review_policy.APPROVAL_OF[entry["rung"]])
    for override in entry["overrides"]:
        _seed(context, review_policy.APPROVAL_OF[override["rung"]], {key: value for key, value in override.items() if key != "rung"})
    context.require_reviewed = review_policy.MACHINES_ON_MACHINES["requireReviewedSource"]


# --- the Story --------------------------------------------------------------------------------------------------------------------------------------


def _story(context, lineage, version, stars, rated_by):
    context.facts[lineage] = StoryFacts(lineage_id=lineage, item_id=f"{lineage}-v{version}", version_number=version, story_type="article", section=None, published=True,
                                        retired=False, stars=stars, title=lineage, dek="", summary="", body="", path=f"/{lineage}", rated_by=rated_by)


@given('the Story "{lineage:R}" at version {version:d} has {stars:d} stars given by "{rated_by:R}"')
def story_rated(context, lineage, version, stars, rated_by):
    _story(context, lineage, version, stars, rated_by)


@given('the Story "{lineage:R}" at version {version:d} is unrated')
def story_unrated(context, lineage, version):
    _story(context, lineage, version, 0, "")


@given('a person has reviewed version {version:d} of the Story "{lineage:R}"')
def person_reviewed(context, version, lineage):
    context.stamps.mark(lineage, version, "done", "person")


@when('the Story "{lineage:R}" is edited to version {version:d}')
def story_edited(context, lineage, version):
    old = context.facts[lineage]
    _story(context, lineage, version, old.stars, old.rated_by)
    context.deliveries_back = intake.story_changed(context.announcements, context.announcement, context.facts[lineage], by=CREATED_BY, now=context.now)


@when('the Story "{lineage:R}" is edited to version {version:d} without an Announcement')
def story_edited_alone(context, lineage, version):
    old = context.facts[lineage]
    _story(context, lineage, version, old.stars, old.rated_by)


@when('a person reviews version {version:d} of the Story "{lineage:R}"')
def person_reviews(context, version, lineage):
    context.stamps.mark(lineage, version, "done", "person")


@given('an agent has marked the review step done on version {version:d} of the Story "{lineage:R}"')
def agent_reviewed(context, version, lineage):
    context.stamps.mark(lineage, version, "done", "agent")


@given('a person has opened the review step again on version {version:d} of the Story "{lineage:R}"')
def person_reopened(context, version, lineage):
    context.stamps.mark(lineage, version, "open", "person")


@then('the Story "{lineage:R}" at version {version:d} has a human review stamp')
def has_stamp(context, lineage, version):
    assert context.stamps.reviewed(lineage, version), f"{lineage} version {version} has no stamp"


@then('the Story "{lineage:R}" at version {version:d} has no human review stamp')
def has_no_stamp(context, lineage, version):
    assert not context.stamps.reviewed(lineage, version), f"{lineage} version {version} has a stamp"


@when("the words of the drafted Deliveries are made again")
def words_again(context):
    stories = list(context.facts.values())
    context.ready, context.held_again = intake.make_ready(context.announcements, context.stamps, context.announcement, stories, require_reviewed_source=context.require_reviewed,
                                                         by="drafter", now=context.now)


@then("{count:d} Deliveries are ready again")
def ready_again(context, count):
    assert len(context.ready) == count, [row["channel"] for row in context.ready]


@then('"{channel:R}" waits because "{reason:R}"')
def waits_because(context, channel, reason):
    found = [held for held in context.held_again if held.channel == channel]
    assert found and reason in found[0].reason, [held.reason for held in context.held_again]


# --- announcing -------------------------------------------------------------------------------------------------------------------------------------


def _targets(table):
    headings = list(table.headings)
    return [intake.Target(channel=row["channel"], account_id=row["account"], text=f"Words for {row['channel']}", list_id=(row["list"] if "list" in headings and row["list"] else None),
                          lock_at=(row["lock at"] if "lock at" in headings and row["lock at"] else None)) for row in table]


def _announce(context, lineages, kind, key, release=None):
    stories = [context.facts[name.strip()] for name in lineages.split(",")]
    context.intake = intake.announce_story(context.announcements, context.policy.read(TENANT), context.stamps, stories, dedupe_key=key, kind=kind, targets=_targets(context.table),
                                           require_reviewed_source=context.require_reviewed, created_by=CREATED_BY, trigger="publish", release_at=release, now=context.now)
    context.outcome = context.intake.outcome
    context.outcomes.append(context.outcome)
    if context.outcome:
        context.announcement = context.outcome.announcement


@step('the announce agent announces the Story "{lineage:R}" as "{kind:R}" on these channels')
def announce_story(context, lineage, kind):
    _announce(context, lineage, kind, f"{'story-published' if kind == 'story_published' else kind}:{lineage}")


@step('the announce agent announces the Story "{lineage:R}" as "{kind:R}" with a release time "{release:R}" on these channels')
def announce_story_at(context, lineage, kind, release):
    _announce(context, lineage, kind, f"{'story-published' if kind == 'story_published' else kind}:{lineage}", release)


@step('the announce agent announces the Stories "{lineages:R}" as "{kind:R}" under the key "{key:R}" on these channels')
def announce_stories(context, lineages, kind, key):
    _announce(context, lineages, kind, key)


@then('an Announcement was made with {count:d} Deliveries')
def announcement_made(context, count):
    assert context.outcome is not None, [held.reason for held in context.intake.held]
    assert len(context.outcome.deliveries) == count, [row["channel"] for row in context.outcome.deliveries]


@then('nothing was announced because "{reason:R}"')
def nothing_because(context, reason):
    assert context.outcome is None and context.backend.rows("AnnouncementDecision") == []
    assert any(reason in held.reason for held in context.intake.held), [held.reason for held in context.intake.held]


@then('no Delivery was prepared for "{channel:R}" because "{reason:R}"')
def no_delivery_because(context, channel, reason):
    found = [held for held in context.intake.held if held.channel == channel]
    assert found and reason in found[0].reason, [(held.channel, held.reason) for held in context.intake.held]
    assert not [row for row in context.backend.rows("Delivery") if row["channel"] == channel]


def _row(context, channel, account):
    rows = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account]
    assert rows, f"no Delivery for {channel} {account}"
    return dict(max(rows, key=lambda row: int(row["generation"])))


@then('the Delivery "{channel:R}" "{account:R}" has the review "{approval:R}" from "{source:R}"')
def delivery_review(context, channel, account, approval, source):
    row = _row(context, channel, account)
    assert row["approval"] == approval, row["approval"]
    assert row["approvalPolicy"].startswith(source), row["approvalPolicy"]
    assert "agent policy version" in row["approvalPolicy"] or source.startswith("set for this Delivery"), row["approvalPolicy"]


@then('the Delivery "{channel:R}" "{account:R}" records the version of the policy it was made under')
def delivery_records_version(context, channel, account):
    assert f"agent policy version {context.policy.read(TENANT).version}" in _row(context, channel, account)["approvalPolicy"]


@then('the Delivery "{channel:R}" "{account:R}" reads "{words:R}" with the mark "{mark:R}"')
def delivery_reads(context, channel, account, words, mark):
    label = review_policy.approval_label(_row(context, channel, account))
    assert label["words"].startswith(words) and label["mark"] == mark, label


@then('the Delivery "{channel:R}" "{account:R}" is waiting in the state "{state:R}"')
def delivery_state(context, channel, account, state):
    assert _row(context, channel, account)["state"] == state


# --- policy changes by a person ---------------------------------------------------------------------------------------------------------------------


def _handlers(context):
    review_handlers._publication = lambda client: "publication"   # the publication's key is read from the site's own record, which these specs do not build
    return review_handlers.signed_in_handlers(client_factory=lambda: context.backend, policy_factory=lambda client: context.policy)


def _call(context, name, arguments, caller):
    context.envelope = execute(name, arguments, caller, _handlers(context))
    return context.envelope


@when('an admin changes the publication\'s announcement review to "{approval:R}" because "{reason:R}"')
def admin_changes_publication(context, approval, reason):
    _call(context, "announcements_review_set", {"approval": approval, "reason": reason}, ADMIN)
    assert context.envelope["ok"], context.envelope


@when('an admin changes the announcement review for the kind "{kind:R}" to "{approval:R}" because "{reason:R}"')
def admin_changes_kind(context, kind, approval, reason):
    _call(context, "announcements_review_set", {"approval": approval, "kind": kind, "reason": reason}, ADMIN)
    assert context.envelope["ok"], context.envelope


@when('an admin takes away the announcement review override for the channel "{channel:R}" because "{reason:R}"')
def admin_removes_channel(context, channel, reason):
    _call(context, "announcements_review_set", {"approval": "inherit", "channel": channel, "reason": reason}, ADMIN)
    assert context.envelope["ok"], context.envelope


@when('an editor tries to change the publication\'s announcement review to "{approval:R}" because "{reason:R}"')
def editor_changes(context, approval, reason):
    _call(context, "announcements_review_set", {"approval": approval, "reason": reason}, EDITOR)


@when('an admin tries to change the publication\'s announcement review to "{approval:R}" because "{reason:R}"')
def admin_tries(context, approval, reason):
    _call(context, "announcements_review_set", {"approval": approval, "reason": reason}, ADMIN)


@then('the announcement review shows "{approval:R}" for the publication and "{kind_approval:R}" for the kind "{kind:R}"')
def review_shows(context, approval, kind_approval, kind):
    _call(context, "announcements_review_show", {}, EDITOR)
    result = context.envelope["result"]
    assert result["approval"] == approval, result
    assert [item["approval"] for item in result["overrides"] if item["scope"] == {"kind": kind}] == [kind_approval], result


@then('the announcement review for the channel "{channel:R}" and the kind "{kind:R}" would be "{approval:R}" from "{source:R}"')
def review_would_be(context, channel, kind, approval, source):
    _call(context, "announcements_review_show", {"channel": channel, "kind": kind}, EDITOR)
    chosen = context.envelope["result"]["chosen"]
    assert chosen["approval"] == approval and chosen["policy"].startswith(source), chosen


@then('the change is refused as "{code:R}"')
def change_refused(context, code):
    assert context.envelope["ok"] is False and context.envelope["error"]["code"] == code, context.envelope


@then('the refusal says "{text:R}"')
def refusal_says(context, text):
    assert text in context.envelope["error"]["message"], context.envelope["error"]["message"]


@then("the policy has {count:d} versions")
def policy_versions(context, count):
    assert context.policy.read(TENANT).version == count


@then('the Delivery "{channel:R}" "{account:R}" still has the review "{approval:R}" from "{source:R}"')
def still_has(context, channel, account, approval, source):
    delivery_review(context, channel, account, approval, source)


# --- one Announcement's review, changed by an editor -----------------------------------------------------------------------------------------------------


@when('an editor changes the review of the Delivery "{channel:R}" "{account:R}" to "{approval:R}"')
def editor_changes_delivery(context, channel, account, approval):
    _call(context, "announcements_delivery_review_set", {"delivery": _row(context, channel, account)["id"], "approval": approval}, EDITOR)
    assert context.envelope["ok"], context.envelope


@then('the Delivery "{channel:R}" "{account:R}" is approved by "{who:R}"')
def delivery_approved_by(context, channel, account, who):
    row = _row(context, channel, account)
    assert context.deliveries.is_approved(row) and row["approvedBy"] == who, (row.get("approvedBy"), row.get("approvedVersion"))


@when("the Announcement is stopped by a person before the lock time")
def person_stops(context):
    context.announcements.cancel(context.announcement, by="ellie", now=context.now)


@then('the Delivery "{channel:R}" "{account:R}" is withdrawn and cannot go at "{when:R}"')
def withdrawn_cannot_go(context, channel, account, when):
    row = _row(context, channel, account)
    ok, _ = context.deliveries.releasable(row, when)
    assert row["state"] == "withdrawn" and not ok


# --- what an agent may do (the operation table's rows, through the one gate) -------------------------------------------------------------------------------

STUB_ARGUMENTS = {
    "announcements_release": {"delivery": "d1"}, "announcements_unlock": {"delivery": "d1"}, "announcements_withdraw": {"delivery": "d1"}, "announcements_correct": {"delivery": "d1", "text": "Corrected words"},
    "announcements_draft": {"delivery": "d1"}, "announcements_pinned_change": {"delivery": "d1", "replaces": 1, "block": 1}, "announcements_settings_set": {"budget": "10.00"},
    "announcements_review_set": {"approval": "none", "reason": "Why"}, "announcements_delivery_review_set": {"delivery": "d1", "approval": "none"},
}


@given('an announce agent working on the channel "{channel:R}" for the kind "{kind:R}"')
def agent_working(context, channel, kind):
    context.run = GateRun(context.policy.read(TENANT), review_policy.RESPONSIBILITY, "run-1", {"channel": channel, "kind": kind})
    context.agent = Caller(kind="agent", subject="announce", gate_run=context.run)
    context.writes = 0


@when('the announce agent asks to "{name:R}"')
def agent_asks(context, name):
    def handler(arguments, caller):
        context.writes += 1
        return Outcome({}, "publication")

    context.envelope = execute(name, dict(STUB_ARGUMENTS.get(name, {})), context.agent, {name: handler})
    context.answer = context.run.answers[-1]


@when('a person asks to "{name:R}"')
def person_asks(context, name):
    def handler(arguments, caller):
        context.writes += 1
        return Outcome({}, "publication")

    context.run = None
    context.envelope = execute(name, dict(STUB_ARGUMENTS.get(name, {})), EDITOR if name != "announcements_review_set" else ADMIN, {name: handler})


@then('the announcement gate answers "{word:R}"')
def gate_answers(context, word):
    if context.run is None:
        assert word == "allowed" and context.envelope["ok"], context.envelope
        return
    assert context.answer.answer == word, (context.answer, context.envelope)
    assert (context.envelope["ok"] is True) == (word == "allowed")
    if word != "allowed":
        assert context.envelope["error"]["code"] == word


@then("the agent's call did not write")
def agent_did_not_write(context):
    assert context.writes == 0


@then("the call wrote once")
def wrote_once(context):
    assert context.writes == 1


@step('the table names "{name:R}" as needing "{rung:R}" from an agent')
def table_needs(context, name, rung):
    from papyrus_content.images.operations import operation

    assert operation(name).agent_rung == rung, operation(name).agent_rung


# --- an agent in a person's own admin session, on that person's instruction (agent_policy/delegation.py) -----------------------------------------------------

SESSION_AGENT = Caller(kind="agent", subject="ada", is_admin=True)   # what identify() makes of an agent in ada's admin session
EDITOR_SESSION_AGENT = Caller(kind="agent", subject="ellie", is_admin=False)


def _delegated(context, caller, approval, person, quote):
    _call(context, "announcements_review_set", {"approval": approval, "reason": "Test", "onInstructionOf": person, "quote": quote, "agent": "Claude"}, caller)


@when('an agent in ada\'s session sets the publication\'s announcement review to "{approval:R}" on the instruction of "{person:R}" who said "{quote:R}"')
def delegated_ada(context, approval, person, quote):
    _delegated(context, SESSION_AGENT, approval, person, quote)


@when('an agent in ellie\'s session sets the publication\'s announcement review to "{approval:R}" on the instruction of "{person:R}" who said "{quote:R}"')
def delegated_ellie(context, approval, person, quote):
    _delegated(context, EDITOR_SESSION_AGENT, approval, person, quote)


@when('an agent in ada\'s session sets the publication\'s announcement review to "{approval:R}" naming no one')
def delegated_nobody(context, approval):
    _call(context, "announcements_review_set", {"approval": approval, "reason": "Test"}, SESSION_AGENT)


@then('the policy was saved by "{by}" with a reason holding "{words:R}"')
def saved_by_with_reason(context, by, words):
    state = context.policy.read(TENANT)
    record = context.policy.version_record(TENANT, state.version)
    assert record["by"] == by and words in record["reason"], record


@then('the policy still has no announce rung')
def no_rung(context):
    assert context.policy.read(TENANT).document["agents"].get(review_policy.RESPONSIBILITY) is None
