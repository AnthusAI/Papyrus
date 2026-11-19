"""A list carries its cadence, time, time zone and rule as data (features_backend/list-cadence.feature).

A fake site (its API, its site store, its schedule group, its wake queue and its Announcement and Delivery records); no network, no AWS, nothing is sent. The
schedules are reconciled by the command a deploy runs (``papyrus agents schedules``), a tick is the message the entry sends, and the wake is handled by the
function a list's agent calls (``list_cadence.wake``)."""
from __future__ import annotations

import copy
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import parse
from behave import given, register_type, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import agent_wakes, automations as au  # noqa: E402
from papyrus_content.agent_definitions import cli as agents_cli, schedules  # noqa: E402
from papyrus_content.announcements.decisions import Announcements  # noqa: E402
from papyrus_content import run_outcomes, today  # noqa: E402
from papyrus_content.announcements.attempts import NotReleasable, Attempts  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries  # noqa: E402
from papyrus_content.announcements.records import json_list  # noqa: E402
from papyrus_content.announcements.links import StoryRef  # noqa: E402
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.list_cadence.announce import Candidate, IssueNoteError, PersonNote  # noqa: E402
from papyrus_content.list_cadence.settings import ListSettingsError  # noqa: E402
from papyrus_content.list_cadence.store import ListSettingsStore  # noqa: E402
from papyrus_content.list_cadence.wake import ListWakeError, run_list, run_story_change, scheduled_time, write_note  # noqa: E402
from schedule_fakes import MONITOR, FakeScheduler, FakeSqs, Reader, Site, WakeQueue  # noqa: E402

ACCOUNT = "mom-sending"
BY = "list-agent"
PEOPLE = {"ryan": Caller(kind="person", subject="ryan", is_admin=True), "ellie": Caller(kind="person", subject="ellie"), "an agent": Caller(kind="agent", subject="bot")}


@parse.with_pattern(r".*")
def parse_rest(text):
    return text


register_type(Rest=parse_rest)


def quoted(text):
    return re.findall(r'"([^"]*)"', text)


def attempt(context, action):
    context.error = None
    try:
        return action()
    except (ListSettingsError, ListWakeError, IssueNoteError) as error:
        context.error = error
        return None


def list_entry(cadence, *, agent="announce-lists", day=None, time=None, zone=None, stars=3, sections=(), reviewed=False, rung=None, empty=None):
    entry = {"name": "A list", "cadence": cadence, "rule": {"sections": list(sections), "types": [], "tags": [], "minStars": stars},
             "requireReviewedSource": reviewed, "workingDocument": "story" if cadence == "weekly" else "delivery", "template": "roundup", "agent": agent}
    if cadence != "each":
        entry["sendAt"] = {"time": time, **({"day": day} if day else {})}
        entry["timeZone"] = zone
    if rung:
        entry["rung"] = rung
    if empty:
        entry["emptyPeriod"] = empty
    return entry


def save(context, who, list_id, entry, reason="Because"):
    context.state = attempt(context, lambda: context.lists.set_list(context.site_id, PEOPLE[who], list_id, entry, reason=reason))


def candidate(lineage, stars, section="science", reviewed=False):
    return Candidate(StoryRef(lineage, f"{lineage}-v1", 1), section, "article", [], int(stars), reviewed)


def draft(lists, candidates, notes=()):
    return f"For {', '.join(list_id for list_id, _ in lists)}: " + ", ".join([c.story.lineage_id for c in candidates] + [f"{note.by} wrote: {note.text}" for note in notes])


def reconcile(context):
    buffer = io.StringIO()
    context.writes_mark = context.scheduler.writes
    code = agents_cli.schedules_command(["--site", context.site_id], buffer, client_factory=lambda: context.api, aws_factory=lambda: (context.sqs, context.scheduler),
                                        reader_factory=lambda: context.reader, site_store_factory=lambda client: context.api.site_store)
    context.deploy_output, context.deploy_ok = buffer.getvalue(), code == 0


def rows(context, model):
    return context.backend.rows(model)


# --- the site -------------------------------------------------------------------------------------------------------------------------------------


@given('the site "{site}" with its wake queue, its schedule group, its list settings and its announcement records')
def background(context, site):
    names = schedules.names_for(site)
    context.site_id, context.names = site, names
    context.api, context.scheduler, context.sqs, context.queue = Site(site), FakeScheduler(names.group), FakeSqs(names.queue), WakeQueue()
    context.reader = Reader(site)
    context.lists = ListSettingsStore(context.api.site_store)
    context.backend = RecordsBackend()
    context.announcements = Announcements(context.backend, Deliveries(context.backend, MemoryDeliveryFiles(context.backend)))
    context.now = "2026-11-16T14:00:00Z"
    context.candidates, context.policy_rung, context.announcement = [], "prepare", None
    context.qualified, context.late_at, context.since_seen, context.notes = {}, None, [], []
    context.error, context.result, context.state, context.writes_mark, context.deploy_ok, context.deploy_output = None, None, None, 0, True, ""


@given('the agent "{agent}" runs the procedure "{procedure}", is switched on and is linked to the router publication of the site')
def agent_row(context, agent, procedure):
    record = au.build_record({"id": agent, "title": agent, "procedureKey": procedure, "enabled": True,
                              "trigger": {"kind": "schedule", "config": {"monitorId": MONITOR, "publicationId": context.site_id}}}, actor="person")
    context.api.rows[agent] = au.stored_payload(record)


@given('the agent "{agent}" is switched off')
@when('the agent "{agent}" is switched off')
def switch_off(context, agent):
    context.api.rows[agent] = {**context.api.rows[agent], "enabled": False}


@given('"{admin}" is an admin and "{editor}" is an editor')
def people(context, admin, editor):
    assert PEOPLE[admin].is_admin and not PEOPLE[editor].is_admin


@given('the site\'s agent policy has the lists at the rung "{rung}"')
def policy(context, rung):
    context.policy_rung = rung


@given('the stored settings of the list "{list_id}" are edited by hand to a minimum of {stars:d} star')
def edited_by_hand(context, list_id, stars):
    state = context.lists.read(context.site_id)
    document = copy.deepcopy(state.document)
    document["lists"][list_id]["rule"]["minStars"] = stars
    context.api.site_store.save(context.site_id, "lists", document, "someone", note="by hand", expected_version=state.version)


@given("these Stories are in the period")
def stories(context):
    context.candidates = [candidate(row["story"], row["stars"], row["section"], row["reviewed"] == "yes") for row in context.table]
    context.qualified = {row["story"]: row["qualified"] for row in context.table if "qualified" in context.table.headings}


def stories_since(context, scheduled, since):
    """The Stories a reader of the site would hand the run: those that qualified after the list's last sent issue and by the time of the tick. A table with no
    ``qualified`` column has no times, so every Story is read, and only when the list has never sent."""
    context.since_seen.append(since)
    if not context.qualified:
        assert since is None, "the Stories in this period have no qualified times, but the list has sent before"
        return list(context.candidates)
    return [c for c in context.candidates if (since is None or context.qualified[c.story.lineage_id] > since) and context.qualified[c.story.lineage_id] <= scheduled]


# --- saving and changing lists --------------------------------------------------------------------------------------------------------------------


@given('the weekly list "{list_id}" is sent on "{day}" at "{time}" in "{zone}"{rest:Rest}')
def given_weekly(context, list_id, day, time, zone, rest):
    own = re.search(r'with its own rung "([^"]*)"', rest)
    empty = re.search(r'its empty period is "([^"]*)"', rest)
    entry = list_entry("weekly", day=day, time=time, zone=zone, reviewed="requires a reviewed source" in rest, rung=None if own is None or own.group(1) == "-" else own.group(1),
                       empty=empty.group(1) if empty else None)
    save(context, "ryan", list_id, entry, "Set up in the scenario")
    assert context.error is None, context.error
    reconcile(context)
    assert context.deploy_ok, context.deploy_output


@given('the daily list "{list_id}" is sent at "{time}" in "{zone}"')
def given_daily(context, list_id, time, zone):
    save(context, "ryan", list_id, list_entry("daily", time=time, zone=zone), "Set up in the scenario")
    assert context.error is None, context.error
    reconcile(context)
    assert context.deploy_ok, context.deploy_output


@given('the every-item list "{list_id}" with a minimum of {stars:d} stars')
def given_each(context, list_id, stars):
    save(context, "ryan", list_id, list_entry("each", stars=stars), "Set up in the scenario")
    assert context.error is None, context.error


@given('the every-item list "{list_id}" with a minimum of {stars:d} stars for the section "{section}"')
def given_each_section(context, list_id, stars, section):
    save(context, "ryan", list_id, list_entry("each", stars=stars, sections=[section]), "Set up in the scenario")
    assert context.error is None, context.error


@when('{who} saves the list "{list_id}" as a weekly list sent on "{day}" at "{time}" in "{zone}" run by "{agent}" because "{reason}"')
def when_saves_weekly(context, who, list_id, day, time, zone, agent, reason):
    save(context, who, list_id, list_entry("weekly", agent=agent, day=day, time=time, zone=zone), reason)


@when('{who} saves the list "{list_id}" as a weekly list with a minimum of {stars:d} stars')
def when_saves_low(context, who, list_id, stars):
    save(context, who, list_id, list_entry("weekly", day="monday", time="04:00", zone="America/New_York", stars=stars))


@when("{who} saves a list with {fault}")
def when_saves_fault(context, who, fault):
    if "weekly cadence and no weekday" in fault:
        entry = list_entry("weekly", time="04:00", zone="America/New_York")
    elif "every-item cadence and a send time" in fault:
        entry = {**list_entry("each"), "sendAt": {"time": "06:00"}}
    elif "working document story" in fault:
        entry = {**list_entry("daily", time="06:00", zone="America/New_York"), "workingDocument": "story"}
    elif "time zone" in fault:
        entry = list_entry("daily", time="06:00", zone=quoted(fault)[0])
    elif "the time" in fault:
        entry = list_entry("daily", time=quoted(fault)[0], zone="America/New_York")
    elif "the empty period" in fault:
        base = list_entry("weekly", day="monday", time="04:00", zone="America/New_York") if "weekly cadence" in fault else list_entry("each")
        entry = {**base, "emptyPeriod": quoted(fault)[0]}
    elif "cadence of" in fault:
        entry = {**list_entry("daily", time="06:00", zone="America/New_York"), "cadence": quoted(fault)[0]}
    else:
        raise AssertionError(fault)
    save(context, who, "faulty", entry)


@when('ryan changes the time of the list "{list_id}" to "{day}" at "{time}" because "{reason}"')
def when_changes_time(context, list_id, day, time, reason):
    context.state = attempt(context, lambda: context.lists.set_value(context.site_id, PEOPLE["ryan"], list_id, "sendAt", {"day": day, "time": time}, reason=reason))
    assert context.error is None, context.error


@when('ryan changes the minimum rating of the list "{list_id}" to {stars:d}')
def when_changes_stars(context, list_id, stars):
    rule = {**context.lists.read(context.site_id).get(list_id)["rule"], "minStars": stars}
    context.state = attempt(context, lambda: context.lists.set_value(context.site_id, PEOPLE["ryan"], list_id, "rule", rule, reason="Lower the bar"))


@when('ryan removes the list "{list_id}" because "{reason}"')
@given('ryan removes the list "{list_id}" because "{reason}"')
def when_removes(context, list_id, reason):
    context.state = attempt(context, lambda: context.lists.remove_list(context.site_id, PEOPLE["ryan"], list_id, reason=reason))
    assert context.error is None, context.error


@then('the list settings are at version {version:d}')
def settings_version(context, version):
    assert context.lists.read(context.site_id).version == version


@then('the list settings are at version {version:d}, saved by "{who}" with the reason "{reason}"')
def settings_version_by(context, version, who, reason):
    assert context.error is None, context.error
    assert context.lists.read(context.site_id).version == version
    record = context.api.site_store.version_record(context.site_id, "lists", version)
    assert (record["createdBy"], record["note"]) == (who, reason), record


@then('the list settings are refused with "{text}"')
def settings_refused(context, text):
    assert isinstance(context.error, ListSettingsError), f"expected a refusal, got {context.error!r}"
    assert text in str(context.error), str(context.error)


@then('the list "{list_id}" still has a minimum of {stars:d} stars')
def still_stars(context, list_id, stars):
    assert context.lists.read(context.site_id).get(list_id)["rule"]["minStars"] == stars


# --- the schedule ---------------------------------------------------------------------------------------------------------------------------------


@when("the schedules are reconciled")
@given("the schedules are reconciled")
def when_reconciled(context):
    reconcile(context)


def list_entry_of(context, list_id):
    return context.scheduler.entries[schedules.entry_name(f"{schedules.LIST_ENTRY_PREFIX}{list_id}")]


@then('the schedule group holds the one-shot entry "{name}" and no entry for the list "{list_id}"')
def only_one_shot(context, name, list_id):
    assert context.deploy_ok, context.deploy_output
    assert sorted(context.scheduler.entries) == [name], sorted(context.scheduler.entries)


@then('the entry for the list "{list_id}" says "{expression}" in the time zone "{zone}"')
def entry_says(context, list_id, expression, zone):
    entry = list_entry_of(context, list_id)
    assert (entry["ScheduleExpression"], entry["ScheduleExpressionTimezone"]) == (expression, zone), entry


@then('the entry for the list "{list_id}" wakes "{agent}" with the list "{named}" and no offset from UTC in its time')
def entry_wakes(context, list_id, agent, named):
    entry = list_entry_of(context, list_id)
    body = json.loads(entry["Target"]["Input"])
    assert body["wake"]["key"] == f"{agent}:list:{named}|schedule|{schedules.SCHEDULED_TIME}", body["wake"]
    assert body["request"]["input"]["listId"] == named and body["request"]["trigger"]["automationId"] == agent, body["request"]
    assert "UTC" not in entry["ScheduleExpression"] and "+" not in entry["ScheduleExpression"] and entry["ScheduleExpressionTimezone"] == "America/New_York"


@then("the scheduler was asked to create, update or delete nothing more")
def nothing_more(context):
    assert context.scheduler.writes == context.writes_mark, (context.scheduler.writes, context.writes_mark)


@then('the deploy step stops with a message that says the list "{list_id}" names the agent "{agent}", which is {why}')
def deploy_stops(context, list_id, agent, why):
    assert not context.deploy_ok, context.deploy_output
    assert f"The list {list_id} names the agent {agent}, which is {why}" in json.loads(context.deploy_output)["error"]["message"], context.deploy_output


# --- ticks and wakes ------------------------------------------------------------------------------------------------------------------------------


@given('the scheduler fires the entry for the list "{list_id}" for the time "{when}"')
@when('the scheduler fires the entry for the list "{list_id}" for the time "{when}"')
@when('the scheduler fires the entry for the list "{list_id}" for the time "{when}" again')
def fires(context, list_id, when):
    entry = list_entry_of(context, list_id)
    context.queue.send(entry["Target"]["Input"].replace(schedules.SCHEDULED_TIME, when), entry["Target"]["SqsParameters"]["MessageGroupId"])


@then('the message says in words that it is for the list "{list_id}"')
def says_why(context, list_id):
    assert f"for the list {list_id}" in json.loads(context.queue.messages[0].body)["wake"]["why"]


def handle(context, message):
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "messageId": "m", "body": message.body}]})

    def run():
        state = context.lists.read(context.site_id)
        return run_list(request, state, context.announcements, candidates_for=lambda _list, _entry, scheduled, since: stories_since(context, scheduled, since),
                        notes_for=lambda _list, _entry, scheduled, since: [note for written, note in context.notes if (since is None or written > since) and written <= scheduled], draft=draft,
                        policy_rung=lambda _: context.policy_rung, account_id=ACCOUNT, by=BY, now=context.late_at or scheduled_time(request),
                        edit_settings=getattr(context, "edit_settings", None))

    context.result = attempt(context, run)
    context.queue.delete(message)


@when("the runner handles the next scheduled message")
def handles_next(context):
    handle(context, context.queue.receive())


@when('the runner is delayed until "{time}"')
def delayed(context, time):
    context.late_at = time


@when("the runner handles every scheduled message")
def handles_all(context):
    while context.queue.messages:
        handle(context, context.queue.receive())
        assert context.error is None, context.error


@when('the Story "{lineage}" goes live at {stars:d} stars in the section "{section}"')
@when('the Story "{lineage}" is republished')
def story_live(context, lineage, stars=None, section=None):
    if stars is None:
        stars, section = context.last_story[1:]
    context.last_story = (lineage, stars, section)

    def run():
        state = context.lists.read(context.site_id)
        return run_story_change(candidate(lineage, stars, section, True), state, context.announcements, draft=draft, policy_rung=lambda _: context.policy_rung,
                                account_id=ACCOUNT, by=BY, now=context.now)

    context.result = attempt(context, run)


# --- what the records hold ------------------------------------------------------------------------------------------------------------------------


@given("the announcement settings give a roundup issue on the email channel a window of {window:d} minutes with a lock lead of {lead:d} minutes")
def roundup_window(context, window, lead):
    context.edit_settings = {"editWindows": [{"kind": "roundup", "channel": "email", "windowMinutes": window, "lockLeadMinutes": lead}]}


@then('that Announcement\'s email Delivery goes at "{release}" and locks at "{lock}"')
def roundup_delivery_times(context, release, lock):
    (row,) = [delivery for delivery in rows(context, "Delivery") if delivery["channel"] == "email"]
    assert (row["releaseAt"], row["lockAt"]) == (release, lock), (row["releaseAt"], row["lockAt"])


@then("the catalog holds no Announcement")
def holds_none(context):
    assert not rows(context, "AnnouncementDecision") and not rows(context, "Delivery")


@then("the catalog holds the Announcements {keys} and no others")
def holds_keys(context, keys):
    found = sorted(row["dedupeKey"] for row in rows(context, "AnnouncementDecision"))
    assert found == sorted(quoted(keys)), found


@then("the catalog holds {announcements:d} Announcements and {deliveries:d} Deliveries")
def holds_counts(context, announcements, deliveries):
    assert (len(rows(context, "AnnouncementDecision")), len(rows(context, "Delivery"))) == (announcements, deliveries)


@then('the run says "{reason}"')
def run_says(context, reason):
    assert context.result is not None and context.result.reason == reason, (context.result, context.error)


@then('the run is refused with "{text}"')
def run_refused(context, text):
    assert isinstance(context.error, (ListWakeError, ListSettingsError, IssueNoteError)) and text in str(context.error), context.error


@then('the Announcement "{key}" is planned for "{when}"')
@then('the Announcement "{key}" is still planned for "{when}"')
def planned(context, key, when):
    assert context.error is None, context.error
    row = context.announcements.by_dedupe_key(key)
    assert row, f"no Announcement for {key}: {[r['dedupeKey'] for r in rows(context, 'AnnouncementDecision')]}"
    assert (row["state"], row["releaseAt"]) == ("planned", when), row
    context.announcement = row


@then("that Announcement is about the Stories {stories}")
def about(context, stories):
    context.announcement = context.announcement or the_announcement(context)
    found = sorted(link["objectLineageId"] for link in context.announcements.stories(context.announcement["id"]))
    assert found == sorted(quoted(stories)), found


def the_announcement(context):
    (row,) = rows(context, "AnnouncementDecision")
    return row


def one_email_delivery(context):
    found = context.announcements.deliveries.for_announcement(context.announcement["id"])
    assert len(found) == 1 and found[0]["channel"] == "email", found
    return found[0]


@then("that Announcement has one email Delivery for the list {list_id}")
@then("that Announcement has one email Delivery for the lists {list_id}")
def one_delivery(context, list_id):
    context.announcement = the_announcement(context)
    assert one_email_delivery(context)["audience"] == quoted(list_id), one_email_delivery(context)


@then('the Delivery of the list "{list_id}" needs "{approval}" approval, decided by "{rung}"')
def approval_of(context, list_id, approval, rung):
    assert context.error is None, context.error
    (delivery,) = rows(context, "Delivery")
    assert delivery["audience"] == [list_id] and delivery["approval"] == approval, delivery
    assert delivery["approvalPolicy"] == f"rung {rung} (list {list_id})", delivery


@then('each Delivery is an email Delivery on the sending account "{account}" for exactly one list, drafted and ready, with its words in a file')
def each_delivery(context, account):
    for delivery in rows(context, "Delivery"):
        assert (delivery["channel"], delivery["accountId"], delivery["state"]) == ("email", account, "ready"), delivery
        assert len(delivery["audience"]) == 1 and delivery["draftedBy"] == BY and delivery["textKey"] and not delivery.get("text"), delivery


@then("every Delivery has the same fields as the others")
def same_delivery_fields(context):
    shapes = {frozenset(delivery) for delivery in rows(context, "Delivery")}
    assert len(shapes) == 1, shapes


@then("every Announcement has the fields of the others, differing only in key, kind and trigger")
def same_announcement_fields(context):
    announcements = rows(context, "AnnouncementDecision")
    assert len({frozenset(row) for row in announcements}) == 1
    assert sorted(row["kind"] for row in announcements) == ["roundup", "roundup", "story_published"]


# --- period keys and what carries forward (features_backend/period-keys.feature) -------------------------------------------------------------------


@given('the Delivery of the list "{list_id}" is approved and sent at "{time}"')
@when('the Delivery of the list "{list_id}" is approved and sent at "{time}"')
def approved_and_sent(context, list_id, time):
    deliveries = context.announcements.deliveries
    ready = sorted((row for row in rows(context, "Delivery") if row["audience"] == [list_id] and row["state"] == "ready"), key=lambda row: row["createdAt"])
    assert ready, "the list has no Delivery waiting to go"
    approved = deliveries.approve(ready[-1], version=1, by="ryan", now=time)
    attempts = Attempts(deliveries)
    _, entry = attempts.open(approved["id"], by="sender", now=time)
    attempts.close(approved["id"], entry["number"], "sent", by="sender", now=time)


@given('the due Announcements are released at "{time}"')
@when('the due Announcements are released at "{time}"')
def release_due(context, time):
    assert context.announcements.release_due(time), "no Announcement was due"


def the_announcement_of(context, key):
    row = context.announcements.by_dedupe_key(key)
    assert row, f"no Announcement for {key}: {[r['dedupeKey'] for r in rows(context, 'AnnouncementDecision')]}"
    return row


@then('the Announcement "{key}" is cancelled because "{reason}"')
def cancelled_because(context, key, reason):
    row = the_announcement_of(context, key)
    assert row["state"] == "cancelled", row["state"]
    assert json_list(row["history"])[-1]["note"] == reason, row["history"]


@then('the Announcement "{key}" was decided for "{when}", the first of the two ticks')
def decided_for(context, key, when):
    assert the_announcement_of(context, key)["releaseAt"] == when


@then('the Announcement "{key}" is not cancelled')
def not_cancelled(context, key):
    assert the_announcement_of(context, key)["state"] != "cancelled"


@then('the Announcement "{key}" is about the Stories {stories}')
def announcement_about(context, key, stories):
    found = sorted(link["objectLineageId"] for link in context.announcements.stories(the_announcement_of(context, key)["id"]))
    assert found == sorted(quoted(stories)), found


@then('the Delivery of the Announcement "{key}" is {state}')
def delivery_of(context, key, state):
    (delivery,) = context.announcements.deliveries.for_announcement(the_announcement_of(context, key)["id"])
    assert delivery["state"] == state, delivery["state"]


@then('the run looked for Stories since "{time}"')
def looked_since(context, time):
    assert context.since_seen[-1] == time, context.since_seen


@then("the run looked for Stories since the list's first issue")
def looked_since_start(context):
    assert context.since_seen[-1] is None, context.since_seen


@then("no email was sent")
def nothing_sent(context):
    assert all(row["state"] not in ("sending", "sent") and not json_list(row.get("attempts")) for row in rows(context, "Delivery"))


# --- an empty period (features_backend/empty-period.feature) --------------------------------------------------------------------------------------


@given('a person {who} wrote the note "{text}" for the period at "{time}"')
def person_note_before(context, who, text, time):
    context.notes.append((time, PersonNote(who, text)))


@when('{who} writes "{text}" into the draft of the list "{list_id}" for the period of "{time}"')
def writes_into_draft(context, who, text, list_id, time):
    caller = PEOPLE[who]
    context.result = attempt(context, lambda: write_note(list_id, time, caller, text, context.lists.read(context.site_id), context.announcements, draft=draft,
                                                         policy_rung=lambda _: context.policy_rung, account_id=ACCOUNT, now=context.late_at or time))


@then('the Announcement "{key}" is about no Story')
def about_no_story(context, key):
    assert not context.announcements.stories(the_announcement_of(context, key)["id"])


def live_delivery(context, key):
    (delivery,) = context.announcements.deliveries.live_for_announcement(the_announcement_of(context, key)["id"])
    return delivery


@then('the email of the Announcement "{key}" is a draft with no words')
def draft_no_words(context, key):
    delivery = live_delivery(context, key)
    assert delivery["state"] == "drafted" and not delivery.get("textKey") and not delivery.get("contentHash"), delivery
    assert context.announcements.deliveries.text(delivery) is None


@then('the email of the Announcement "{key}" is ready with the words "{words}"')
def delivery_words(context, key, words):
    delivery = live_delivery(context, key)
    assert delivery["state"] == "ready", delivery["state"]
    assert context.announcements.deliveries.text(delivery) == words, context.announcements.deliveries.text(delivery)


@then('the Delivery of the list "{list_id}" may not go at "{time}" because "{reason}"')
def may_not_go(context, list_id, time, reason):
    (delivery,) = [row for row in context.announcements.deliveries.for_account("email", ACCOUNT) if row["audience"] == [list_id] and row["state"] in ("drafted", "ready")]
    ok, why = context.announcements.deliveries.releasable(delivery, time)
    assert (ok, why) == (False, reason), (ok, why)


@then('the Delivery of the list "{list_id}" may go at "{time}"')
def may_go(context, list_id, time):
    (delivery,) = [row for row in context.announcements.deliveries.for_account("email", ACCOUNT) if row["audience"] == [list_id] and row["state"] in ("drafted", "ready")]
    assert context.announcements.deliveries.releasable(delivery, time) == (True, None)


@then('opening an attempt for the Delivery of the list "{list_id}" at "{time}" is refused because "{reason}"')
def attempt_refused(context, list_id, time, reason):
    (delivery,) = [row for row in context.announcements.deliveries.for_account("email", ACCOUNT) if row["audience"] == [list_id] and row["state"] in ("drafted", "ready")]
    try:
        Attempts(context.announcements.deliveries).open(delivery["id"], by="sender", now=time)
    except NotReleasable as refused:
        assert refused.reason == reason, refused.reason
    else:
        raise AssertionError("an attempt opened for a Delivery that may not go")


@then('the run tells the runner it found nothing to do because "{code}"')
def declares_nothing(context, code):
    assert context.result.declaration() == {run_outcomes.OUTCOME_KEY: "nothing", run_outcomes.REASON_KEY: code}, context.result.declaration()
    assert run_outcomes.declared_outcome(context.result.declaration()) == ("nothing", code)


@then("the run tells the runner it did its work")
def declares_acted(context):
    assert context.result.declaration() == {} and run_outcomes.declared_outcome(context.result.declaration()) == ("acted", None)


class TodayClient:
    """Answers only the reads Today may make."""

    tenant_id = "site"

    def __init__(self, runs):
        self.runs = runs

    def list_by_index(self, index, key, *, sort_condition=None, **_):
        low, high = sort_condition["between"]
        return [dict(row) for row in self.runs if row["runStatus"] == key and low <= row["requestedAt"] <= high]

    def list_tenant_rows(self, model, fields, **_):
        return []


@then('Today for "{day}" in "{zone}" shows the run of "{time}" as "{shown}" with the reason "{reasons}"')
def today_shows(context, day, zone, time, shown, reasons):
    finished = run_outcomes.finished_outcome(True, context.result.declaration(), None)
    run = {"id": "run-1", "procedureKey": "announce_list", "runStatus": finished["runStatus"], "outcome": finished["outcome"], "outcomeReason": finished["outcomeReason"],
           "responsibility": "announce", "automationId": "announce-lists", "requestedAt": time.replace("Z", ".000Z"), "finishedAt": time.replace("Z", ".000Z"), "costUsd": 0.0}
    overview = today.today_overview(TodayClient([run]), day=day, time_zone=zone, now=datetime.fromisoformat("2026-11-16T17:00:00+00:00"))
    (line,) = overview["rows"]
    assert today.counts_text(line["counts"]) == shown, today.counts_text(line["counts"])
    assert today.reasons_text(line["reasons"]["nothing"]) == reasons, line["reasons"]
    assert any(f"Nothing to do: {reasons}" in text for text in today.render(overview)), today.render(overview)


@then('the list "{list_id}" sends nothing in an empty period')
def sends_nothing_by_default(context, list_id):
    assert context.lists.read(context.site_id).get(list_id)["emptyPeriod"] == "nothing"
