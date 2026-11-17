"""The Announcement and Delivery records (features_backend/announcement-*.feature, delivery-*.feature).

A fake backend that answers only gets and index queries (it has no call that lists a table) and a fake store for the Deliveries' words. No network, no AWS.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import parse
from behave import register_type, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.announcements import links, records  # noqa: E402
from papyrus_content.announcements.decisions import Announcements  # noqa: E402
from papyrus_content.announcements.deliveries import ROLE, AttachmentFiles, Conflict, Deliveries, Plan  # noqa: E402
from papyrus_content.announcements.links import StoryRef  # noqa: E402
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend  # noqa: E402
from papyrus_content.graphql_authoring import INDEX_DEFINITIONS  # noqa: E402
from papyrus_content.relation_types import load_semantic_relation_type_seeds  # noqa: E402
from papyrus_content.upload_rules_fake import allowed_roles  # noqa: E402

MODELS = {"Announcement": "AnnouncementDecision", "Delivery": "Delivery", "link": "SemanticRelation"}
STATES = ("planned", "released", "cancelled", "withdrawn")
DEFAULT_POLICY = "publication default"
CREATED_BY = "pipeline"


@parse.with_pattern(r'[^"]*')
def parse_quoted(text):
    return text


register_type(Q=parse_quoted)


# --- helpers --------------------------------------------------------------------------------------------------------------------------------------


def attempt(context, action):
    """Run an action and keep what it raised, so a later step can say the call failed or was refused."""
    context.error = None
    try:
        return action()
    except Exception as error:   # noqa: BLE001 - the specs ask what the call said
        context.error = error
        return None


def noun_model(noun):
    key = "Delivery" if noun.startswith("Deliver") else "link" if noun.startswith("link") else "Announcement"
    return MODELS[key]


def story(context, lineage):
    return context.stories[lineage]


def decision_row(context, key):
    row = context.announcements.by_dedupe_key(key)
    assert row, f"no Announcement for {key}"
    return row


def delivery_row(context, channel, account, generation=None):
    rows = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account]
    assert rows, f"no Delivery for {channel} {account}"
    if generation is not None:
        found = [row for row in rows if int(row["generation"]) == generation]
        assert found, f"no generation {generation} of {channel} {account}"
        return dict(found[0])
    return dict(max(rows, key=lambda row: int(row["generation"])))


def plans_from(context, table):
    plans = []
    headings = list(table.headings)
    for row in table:
        values = {name: row[name] for name in headings}
        policy = values["policy"] if "policy" in headings else DEFAULT_POLICY
        plans.append(Plan(
            channel=values["channel"], account_id=values["account"], approval=values["approval"], approval_policy=policy,
            text=values.get("text") or f"Words for {values['channel']}", image_key=values.get("image") or None, lock_at=values.get("lock at") or None,
        ))
    return plans


def decide(context, key, kind, lineages, plans, release=None):
    refs = [story(context, lineage.strip()) for lineage in lineages.split(",")]
    context.last_call = (key, kind, refs, plans, release)
    outcome = attempt(context, lambda: context.announcements.announce(
        dedupe_key=key, kind=kind, stories=refs, plans=plans, created_by=CREATED_BY, trigger="publish", release_at=release, now=context.now))
    context.outcome = outcome
    context.outcomes.append(outcome)
    if outcome:
        context.announcement = outcome.announcement


def check_error(context, text):
    assert isinstance(context.error, records.RecordError), f"expected a refusal, got {context.error!r}"
    assert text in str(context.error), f"{text!r} is not in {str(context.error)!r}"


# --- setup ----------------------------------------------------------------------------------------------------------------------------------------


@step("an empty announcement catalog")
def empty_catalog(context):
    context.backend = RecordsBackend()
    context.files = MemoryDeliveryFiles(context.backend)
    context.deliveries = Deliveries(context.backend, context.files)
    context.announcements = Announcements(context.backend, context.deliveries)
    context.stories = {}
    context.outcomes = []
    context.outcome = None
    context.announcement = None
    context.error = None
    context.now = "2026-11-16T14:00:00Z"
    context.answer = None
    context.read_mark = 0


@step('the clock reads "{when:Q}"')
def set_clock(context, when):
    context.now = when


@step('the Story "{lineage:Q}" is at version {version:d}')
def story_at_version(context, lineage, version):
    context.stories[lineage] = StoryRef(lineage, f"{lineage}-v{version}", version)


# --- deciding -------------------------------------------------------------------------------------------------------------------------------------


@step('the decision "{key:Q}" of kind "{kind:Q}" is made for the Story "{lineage:Q}" with these Deliveries')
def decision_for_story(context, key, kind, lineage):
    decide(context, key, kind, lineage, plans_from(context, context.table))


@step('the decision "{key:Q}" of kind "{kind:Q}" is made for the Story "{lineage:Q}" with a release time "{release:Q}" and these Deliveries')
def decision_for_story_at(context, key, kind, lineage, release):
    decide(context, key, kind, lineage, plans_from(context, context.table), release)


@step('the decision "{key:Q}" of kind "{kind:Q}" is made for the Stories "{lineages:Q}" with these Deliveries')
def decision_for_stories(context, key, kind, lineages):
    decide(context, key, kind, lineages, plans_from(context, context.table))


@step('the same decision is made again for the Story "{lineage:Q}" with those Deliveries')
def decision_again(context, lineage):
    key, kind, refs, plans, release = context.last_call
    decide(context, key, kind, lineage, plans, release)


@step("the next write of a Delivery fails as if the connection dropped")
def fail_next_delivery_write(context):
    context.backend.fail_next("create", "Delivery")


@step("the next update of a Delivery fails as if the connection dropped")
def fail_next_delivery_update(context):
    context.backend.fail_next("update", "Delivery")


@step("the next upload of a Delivery's words fails as if the connection dropped")
def fail_next_upload(context):
    original = context.files.put
    state = {"failed": False}

    def put(delivery, text, *, now):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("connection dropped")
        original(delivery, text, now=now)

    context.files.put = put


@then("the call fails")
def call_fails(context):
    assert context.error is not None, "the call went through"


@then('the call is refused saying "{text:Q}"')
def call_refused(context, text):
    check_error(context, text)


@then("no Announcement was made")
def no_announcement(context):
    assert context.outcome is None and context.error is None


@then("the catalog holds {count:d} {noun:w}")
def catalog_holds(context, count, noun):
    rows = context.backend.rows(noun_model(noun))
    assert len(rows) == count, f"{noun}: {len(rows)} rows, expected {count}"


@then("the second call found the Announcement that already existed")
def second_found(context):
    assert context.outcomes[-1].created is False and context.outcomes[0].created is True


@then('the Announcement for the key "{key:Q}" is found through the key index')
def found_by_key(context, key):
    assert decision_row(context, key)
    assert ("announcementDecisionsByDedupeKey", key) in context.backend.reads


@then('the Announcement is linked to the Story "{lineage:Q}" at version {version:d}')
def announcement_linked(context, lineage, version):
    rows = context.announcements.stories(context.announcement["id"])
    found = [row for row in rows if row["objectLineageId"] == lineage]
    assert found and int(found[0]["objectVersionNumber"]) == version, f"links: {[(r['objectLineageId'], r['objectVersionNumber']) for r in rows]}"


@then("both Deliveries belong to that Announcement")
def both_belong(context):
    assert {row["announcementId"] for row in context.backend.rows("Delivery")} == {context.announcement["id"]}


@then("the Announcement row has none of these fields")
def row_has_none(context):
    row = context.backend.rows("AnnouncementDecision")[0]
    for entry in context.table:
        assert entry["field"] not in row, f"the Announcement holds {entry['field']}"


@then('the Announcement\'s release time is "{when:Q}"')
def release_is(context, when):
    assert context.announcement["releaseAt"] == when, context.announcement["releaseAt"]


@then('the Announcement for "{key:Q}" has the release time "{when:Q}"')
def release_of(context, key, when):
    assert decision_row(context, key)["releaseAt"] == when


# --- Deliveries -----------------------------------------------------------------------------------------------------------------------------------


@then('the Delivery row "{channel:Q}" "{account:Q}" holds')
def delivery_holds(context, channel, account):
    row = delivery_row(context, channel, account)
    for entry in context.table:
        assert str(row.get(entry["field"])) == entry["value"], f"{entry['field']}: {row.get(entry['field'])!r} is not {entry['value']!r}"


@then('the Delivery row "{channel:Q}" "{account:Q}" has no field "{field:Q}"')
def delivery_lacks(context, channel, account, field):
    assert field not in delivery_row(context, channel, account)


@then('the Delivery "{channel:Q}" "{account:Q}" was approved by "{who:Q}" under "{policy:Q}"')
def approved_under(context, channel, account, who, policy):
    row = delivery_row(context, channel, account)
    assert row["approvedBy"] == who and row["approvalPolicy"] == policy, (row["approvedBy"], row["approvalPolicy"])


@then('the Delivery "{channel:Q}" "{account:Q}" was approved by "{who:Q}"')
def approved_by(context, channel, account, who):
    assert delivery_row(context, channel, account)["approvedBy"] == who


@then('the Delivery "{channel:Q}" "{account:Q}" is not approved')
def not_approved(context, channel, account):
    assert not context.deliveries.is_approved(delivery_row(context, channel, account))


@then('the Delivery "{channel:Q}" "{account:Q}" may go at "{when:Q}"')
def may_go(context, channel, account, when):
    ok, reason = context.deliveries.releasable(delivery_row(context, channel, account), when)
    assert ok, f"not releasable: {reason}"


@then('the Delivery "{channel:Q}" "{account:Q}" may not go at "{when:Q}" because "{reason:Q}"')
def may_not_go(context, channel, account, when, reason):
    ok, why = context.deliveries.releasable(delivery_row(context, channel, account), when)
    assert not ok and why == reason, f"{ok}: {why!r}"


@step('the person "{who:Q}" approves version {version:d} of the Delivery "{channel:Q}" "{account:Q}"')
def person_approves(context, who, version, channel, account):
    attempt(context, lambda: context.deliveries.approve(delivery_row(context, channel, account), version=version, by=who, now=context.now))


@when('the Story "{lineage:Q}" changes to version {version:d}')
def story_changes(context, lineage, version):
    ref = StoryRef(lineage, f"{lineage}-v{version}", version)
    context.stories[lineage] = ref
    attempt(context, lambda: context.announcements.story_changed(context.announcement, ref, by=CREATED_BY, now=context.now))


@when('the Delivery "{channel:Q}" "{account:Q}" is drafted again and ready')
def drafted_again(context, channel, account):
    context.deliveries.mark_ready(delivery_row(context, channel, account), by="drafter", now=context.now)


@then('the Delivery "{channel:Q}" "{account:Q}" is at version {version:d} and is a draft')
def at_version_draft(context, channel, account, version):
    row = delivery_row(context, channel, account)
    assert int(row["version"]) == version and row["state"] == "drafted", (row["version"], row["state"])


@then('the Delivery "{channel:Q}" "{account:Q}" is at version {version:d} and is ready')
def at_version_ready(context, channel, account, version):
    row = delivery_row(context, channel, account)
    assert int(row["version"]) == version and row["state"] == "ready", (row["version"], row["state"])


@then('the Delivery "{channel:Q}" "{account:Q}" is withdrawn')
def delivery_withdrawn(context, channel, account):
    assert delivery_row(context, channel, account)["state"] == "withdrawn"


@when('two people read the Delivery "{channel:Q}" "{account:Q}" and both approve version {version:d}')
def two_approve(context, channel, account, version):
    first_read, second_read = delivery_row(context, channel, account), delivery_row(context, channel, account)
    context.deliveries.approve(first_read, version=version, by="ellie", now=context.now)
    context.error = None
    try:
        context.deliveries.approve(second_read, version=version, by="sam", now=context.now)
    except Conflict as error:
        context.error = error


@then("exactly one approval is saved and the other is told the Delivery changed")
def one_approval(context):
    assert isinstance(context.error, Conflict)
    row = context.backend.rows("Delivery")[0]
    assert row["approvedBy"] == "ellie"


# --- the schedule, release and cancel -------------------------------------------------------------------------------------------------------------


@step('the schedule releases what is due at "{when:Q}"')
def schedule_releases(context, when):
    context.announcements.release_due(when)


@then('the Announcement "{key:Q}" is {state:w}')
def announcement_state(context, key, state):
    assert state in STATES, f"{state} is not a state"
    assert decision_row(context, key)["state"] == state


@then("the schedule found it through the planned-by-release-time index")
def found_through_state_index(context):
    assert ("announcementDecisionsByState", "planned") in context.backend.reads


@when('the person "{who:Q}" cancels the Announcement "{key:Q}"')
def person_cancels(context, who, key):
    attempt(context, lambda: context.announcements.cancel(decision_row(context, key), by=who, now=context.now))


@then('the Announcement "{key:Q}" history reads')
def history_reads(context, key):
    history = records.json_list(decision_row(context, key)["history"])
    assert len(history) == len(context.table.rows), history
    for entry, line in zip(history, context.table):
        assert (entry["by"], entry["state"], entry["note"]) == (line["by"], line["state"], line["note"]), entry


# --- no text in the catalog -----------------------------------------------------------------------------------------------------------------------


@then('the Delivery row "{channel:Q}" "{account:Q}" has a text key and a content hash')
def has_key_and_hash(context, channel, account):
    row = delivery_row(context, channel, account)
    assert row["textKey"].startswith("newsroom/payloads/delivery/") and len(row["contentHash"]) == 64


@then('the Delivery row "{channel:Q}" "{account:Q}" contains none of "{words:Q}" anywhere')
def row_contains_none(context, channel, account, words):
    assert words not in json.dumps(delivery_row(context, channel, account))


@then('the Announcement row contains none of "{words:Q}" anywhere')
def announcement_contains_none(context, words):
    assert words not in json.dumps(context.backend.rows("AnnouncementDecision"))


@then('the Delivery "{channel:Q}" "{account:Q}" has these words in S3 "{words:Q}"')
def has_words(context, channel, account, words):
    assert context.files.texts[delivery_row(context, channel, account)["id"]] == words


@then('generation {generation:d} of "{channel:Q}" "{account:Q}" has these words in S3 "{words:Q}"')
def generation_has_words(context, generation, channel, account, words):
    assert context.files.texts[delivery_row(context, channel, account, generation)["id"]] == words


@then('the Delivery "{channel:Q}" "{account:Q}" has no words yet')
def has_no_words(context, channel, account):
    assert delivery_row(context, channel, account)["id"] not in context.files.texts


@then('the Delivery "{channel:Q}" "{account:Q}" has its words in S3')
def has_its_words(context, channel, account):
    assert delivery_row(context, channel, account)["id"] in context.files.texts


@then('the content hashes of "{first:Q}", "{second:Q}" and "{third:Q}" are all different')
def hashes_differ(context, first, second, third):
    hashes = {delivery_row(context, "x", account)["contentHash"] for account in (first, second, third)}
    assert len(hashes) == 3


@when('a catalog row carrying the field "{field:Q}" is checked')
def row_checked(context, field):
    attempt(context, lambda: records.require_catalog_only({"id": "row", field: "some words"}))


@then('the words of a Delivery are uploaded as role "{role:Q}" for owner kind "{kind:Q}"')
def upload_shape(context, role, kind):
    entry = AttachmentFiles(None)._entry("delivery-1", "words", "2026-11-16T14:00:00Z")["attachment"]
    assert entry["role"] == role == ROLE and entry["ownerKind"] == kind and entry["mediaType"] == "text/markdown"
    assert role in allowed_roles()
    handler = (REPO_ROOT / "amplify/functions/model-attachment-upload/handler.ts").read_text()
    owners = re.search(r"ALLOWED_OWNER_KINDS = new Set\(\[(.*?)\]\)", handler, re.DOTALL).group(1)
    assert f'"{kind}"' in owners, "the upload function does not accept this owner kind"
    assert f'ownerKind === "{kind}") return "Delivery"' in handler


# --- one live Delivery, corrections ---------------------------------------------------------------------------------------------------------------


@when('a second Delivery for "{channel:Q}" "{account:Q}" is made on that Announcement without naming one to replace')
def second_delivery(context, channel, account):
    old = delivery_row(context, channel, account)
    plan = Plan(channel=channel, account_id=account, approval="none", approval_policy=DEFAULT_POLICY, text="Another version")
    attempt(context, lambda: context.deliveries.add(old["announcementId"], plan, release_at=old["releaseAt"], by="ellie", now=context.now))


def correct(context, who, channel, account, words, generation=None, plan_account=None):
    old = delivery_row(context, channel, account, generation)
    plan = Plan(channel=channel, account_id=plan_account or account, approval=old["approval"], approval_policy=old["approvalPolicy"], text=words)
    attempt(context, lambda: context.deliveries.supersede(old, plan, by=who, now=context.now))


@step('the person "{who:Q}" corrects the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}"')
def person_corrects(context, who, channel, account, words):
    correct(context, who, channel, account, words)


@step('the person "{who:Q}" corrects generation {generation:d} of "{channel:Q}" "{account:Q}" with the words "{words:Q}"')
def person_corrects_generation(context, who, generation, channel, account, words):
    correct(context, who, channel, account, words, generation)


@step('the person "{who:Q}" corrects the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}" on the account "{other:Q}"')
def person_corrects_other_account(context, who, channel, account, words, other):
    correct(context, who, channel, account, words, plan_account=other)


@then('the Delivery "{channel:Q}" "{account:Q}" generation {generation:d} is superseded by generation {newer:d}')
def superseded_by(context, channel, account, generation, newer):
    old, new = delivery_row(context, channel, account, generation), delivery_row(context, channel, account, newer)
    assert old["state"] == "superseded" and old["supersededBy"] == new["id"], (old["state"], old.get("supersededBy"))


@then('the Delivery "{channel:Q}" "{account:Q}" generation {generation:d} supersedes generation {older:d}')
def supersedes_generation(context, channel, account, generation, older):
    new, old = delivery_row(context, channel, account, generation), delivery_row(context, channel, account, older)
    assert new["supersedes"] == old["id"]


@then('generation {generation:d} of "{channel:Q}" "{account:Q}" is linked to generation {older:d} by a supersedes relation')
def supersedes_relation(context, generation, channel, account, older):
    new, old = delivery_row(context, channel, account, generation), delivery_row(context, channel, account, older)
    found = context.backend.list_by_index("semanticRelationsBySubjectState", f"delivery#{new['id']}#current")
    assert [(row["predicate"], row["objectId"]) for row in found] == [("supersedes", old["id"])], found


@then('the live Delivery of "{channel:Q}" "{account:Q}" is generation {generation:d}')
def live_is(context, channel, account, generation):
    announcement = delivery_row(context, channel, account)["announcementId"]
    live = [row for row in context.deliveries.live_for_announcement(announcement) if row["channel"] == channel and row["accountId"] == account]
    assert [int(row["generation"]) for row in live] == [generation], live


@then("the Announcement has {count:d} live Deliveries")
def live_count(context, count):
    assert len(context.deliveries.live_for_announcement(context.announcement["id"])) == count


@then('the Delivery "{channel:Q}" "{account:Q}" generation {generation:d} has no due time')
def generation_no_due(context, channel, account, generation):
    row = delivery_row(context, channel, account, generation)
    assert "dueAt" not in row and "dueKey" not in row, row


@then('the Delivery "{channel:Q}" "{account:Q}" generation {generation:d} is not in the due index')
def generation_not_in_due_index(context, channel, account, generation):
    row = delivery_row(context, channel, account, generation)
    assert row["id"] not in {found["id"] for found in context.backend.list_by_index("deliveriesByDue", records.due_key())}


# --- due times ------------------------------------------------------------------------------------------------------------------------------------


@then('the Delivery "{channel:Q}" "{account:Q}" is due at "{when:Q}"')
def is_due_at(context, channel, account, when):
    row = delivery_row(context, channel, account)
    assert row.get("dueAt") == when and row.get("dueKey") == records.due_key(), (row.get("dueAt"), row.get("dueKey"))
    assert row["id"] in {found["id"] for found in context.backend.list_by_index("deliveriesByDue", records.due_key(), sort_condition={"le": when})}


@then('the Delivery "{channel:Q}" "{account:Q}" has no due time')
def has_no_due(context, channel, account):
    row = delivery_row(context, channel, account)
    assert "dueAt" not in row and "dueKey" not in row, row


@then('the Delivery "{channel:Q}" "{account:Q}" is not in the due index')
def not_in_due_index(context, channel, account):
    row = delivery_row(context, channel, account)
    assert row["id"] not in {found["id"] for found in context.backend.list_by_index("deliveriesByDue", records.due_key())}


@when('the Delivery "{channel:Q}" "{account:Q}" will be tried again at "{when:Q}" waiting for "{reason:Q}"')
def tried_again(context, channel, account, when, reason):
    attempt(context, lambda: context.deliveries.wait_until(delivery_row(context, channel, account), when, reason, by="sender", now=context.now))


@when('the Delivery "{channel:Q}" "{account:Q}" stops waiting')
def stops_waiting(context, channel, account):
    context.deliveries.stop_waiting(delivery_row(context, channel, account), by="sender", now=context.now)


@when('the Delivery "{channel:Q}" "{account:Q}" is locked')
def is_locked(context, channel, account):
    attempt(context, lambda: context.deliveries.lock(delivery_row(context, channel, account), by="send job", now=context.now))


@when('the release of the Delivery "{channel:Q}" "{account:Q}" moves to "{when:Q}"')
def release_moves(context, channel, account, when):
    context.deliveries.move_release(delivery_row(context, channel, account), when, by="ellie", now=context.now)


@step('the Delivery "{channel:Q}" "{account:Q}" is finished as "{state:Q}"')
def finished_as(context, channel, account, state):
    context.deliveries.finish(delivery_row(context, channel, account), state, by="sender", note=state, now=context.now)


@when('the schedule asks what is due at "{when:Q}"')
def asks_due(context, when):
    context.answer = context.deliveries.due(when)


@then("it is told about exactly these Deliveries")
def told_exactly(context):
    assert sorted((row["channel"], row["accountId"]) for row in context.answer) == sorted((entry["channel"], entry["account"]) for entry in context.table)


@then("the due index holds {count:d} Deliveries")
def due_index_holds(context, count):
    assert len(context.backend.list_by_index("deliveriesByDue", records.due_key())) == count


# --- a Story shows where it was announced ---------------------------------------------------------------------------------------------------------


@when('the Story "{lineage:Q}" is asked where it was announced')
def asked_where(context, lineage):
    context.answer = context.announcements.for_story(lineage)


@then("it answers with 0 Announcements")
def answers_none(context):
    assert context.answer == []


@then('it answers with 1 Announcement of kind "{kind:Q}" with these lines')
def answers_lines(context, kind):
    assert len(context.answer) == 1 and context.answer[0]["announcement"]["kind"] == kind
    lines = sorted((row["channel"], row["accountId"]) for row in context.answer[0]["deliveries"])
    assert lines == sorted((entry["channel"], entry["account"]) for entry in context.table), lines


@then('the line for "{channel:Q}" "{account:Q}" is generation {generation:d}')
def line_generation(context, channel, account, generation):
    line = [row for row in context.answer[0]["deliveries"] if row["channel"] == channel and row["accountId"] == account]
    assert [int(row["generation"]) for row in line] == [generation]


@then("every read was an index query or a get by id")
def only_indexed(context):
    assert context.backend.reads and all(index in INDEX_DEFINITIONS for index, _ in context.backend.reads), context.backend.reads


@when('the Deliveries of the account "{channel:Q}" "{account:Q}" are read newest first')
def account_newest_first(context, channel, account):
    context.answer = list(context.deliveries.for_account(channel, account))


@then("they come in this order of creation")
def order_of_creation(context):
    assert [row["createdAt"] for row in context.answer] == [entry["created"] for entry in context.table]


@when('the calendar asks for the planned Announcements from "{start:Q}" to "{end:Q}"')
def calendar_asks(context, start, end):
    context.answer = context.announcements.planned_between(start, end)


@then('it is told about the Announcement "{key:Q}" only')
def told_only(context, key):
    assert [row["id"] for row in context.answer] == [decision_row(context, key)["id"]]


# --- the relation types ---------------------------------------------------------------------------------------------------------------------------


@then('the relation type "{key:Q}" runs from "{subject:Q}" to "{object_:Q}"')
def relation_runs(context, key, subject, object_):
    seed = {entry["key"]: entry for entry in load_semantic_relation_type_seeds()}[key]
    assert seed["allowedSubjectKinds"] == [subject] and seed["allowedObjectKinds"] == [object_] and seed["isDirectional"]


@then("neither relation type is symmetric")
def neither_symmetric(context):
    seeds = {entry["key"]: entry for entry in load_semantic_relation_type_seeds()}
    assert not seeds["announces"]["isSymmetric"] and not seeds["supersedes"]["isSymmetric"]


@when('the Announcement "{announcement:Q}" is linked to the Story "{lineage:Q}" at version {version:d} twice')
def linked_twice(context, announcement, lineage, version):
    ref = StoryRef(lineage, f"{lineage}-v{version}", version)
    for _ in range(2):
        links.announces(context.backend, announcement, ref, now=context.now)


@when('the Announcement "{announcement:Q}" is linked to the Story "{lineage:Q}" at version {version:d}')
def linked_once(context, announcement, lineage, version):
    links.announces(context.backend, announcement, StoryRef(lineage, f"{lineage}-v{version}", version), now=context.now)


@then('the link of "{announcement:Q}" to "{lineage:Q}" names version {version:d}')
def link_names_version(context, announcement, lineage, version):
    rows = links.stories_of_announcement(context.backend, announcement)
    assert [int(row["objectVersionNumber"]) for row in rows if row["objectLineageId"] == lineage] == [version]


@when('the Announcements of the Story "{lineage:Q}" are read through the relation')
def read_through_relation(context, lineage):
    context.read_mark = len(context.backend.reads)
    context.answer = links.announcements_of_story(context.backend, lineage)


@then('{count:d} query was made, on the index "{index:Q}"')
def one_query(context, count, index):
    made = context.backend.reads[context.read_mark:]
    assert made == [(index, made[0][1])] and len(made) == count, made
