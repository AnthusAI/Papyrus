"""Steps for features_backend/site/today-attention.feature: Today's top, what only a person can move, then what is due today."""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
from papyrus_content import automation_view, overdue, run_attention, today, today_attention  # noqa: E402
from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.review_requests import review_state_key  # noqa: E402

SITE_ZONE = "America/New_York"
NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)   # Monday noon in New York
NEW_YORK_OFFSET_HOURS = 5                                  # New York is UTC-5 in November


def new_york(clock: str, day: int = 16) -> str:
    """A New York wall-clock time on Monday 16 November 2026 (or another November day) as the UTC text the records hold."""
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime(2026, 11, day, hour + NEW_YORK_OFFSET_HOURS, minute, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if hour + NEW_YORK_OFFSET_HOURS < 24 \
        else datetime(2026, 11, day + 1, hour + NEW_YORK_OFFSET_HOURS - 24, minute, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SiteIndexes:
    """The site's records, answering only the index reads Today may make, and recording every read so a whole-table list is a failure."""

    tenant_id = None

    def __init__(self):
        self.runs, self.reviews, self.deliveries, self.scheduled, self.automations, self.reads, self.updates = [], [], [], [], [], [], []

    def list_by_index(self, index, key, *, sort_condition=None, **_):
        self.reads.append(("index", index, key, sort_condition))
        if index == "procedureRunsByStatus":
            low, high = sort_condition["between"]
            return [dict(row) for row in self.runs if row["runStatus"] == key and low <= row["requestedAt"] <= high]
        if index == run_attention.INDEX:
            return [dict(row) for row in self.runs if row.get("attentionKey") == key]
        if index == "reviewRequestsByState":
            return [dict(row) for row in self.reviews if row["reviewStateKey"] == key]
        if index == "deliveriesByDue":
            rows = [row for row in self.deliveries if row.get("dueKey") == key]
            if "le" in sort_condition:
                return [dict(row) for row in rows if row["dueAt"] <= sort_condition["le"]]
            return [dict(row) for row in rows if row["dueAt"] < sort_condition["lt"]]
        return []   # the day's email sends read the Announcement records: none are made here

    def list_schedule(self, state, start=None, end=None):
        self.reads.append(("schedule", state, start, end))
        return [dict(row) for row in self.scheduled if row["scheduleState"] == state and start <= row["scheduledPublishAt"] <= end]

    def list_tenant_rows(self, model, fields, **_):
        self.reads.append(("tenant", model))
        return [dict(row) for row in self.automations]

    def get_record(self, model, record_id):
        assert model == "ProcedureRun", model
        return next((dict(row) for row in self.runs if row["id"] == record_id), None)

    def update_record(self, model, payload):
        self.updates.append((model, dict(payload)))
        row = next(row for row in self.runs if row["id"] == payload["id"])
        row.update({key: value for key, value in payload.items() if value is not None})
        for key in [key for key, value in payload.items() if value is None]:
            row.pop(key, None)
        return dict(row)

    def list_records(self, model, **_):
        self.reads.append(("list", model))
        raise AssertionError(f"Today listed the whole {model} table")

    def graphql(self, query, variables):
        raise AssertionError("Today made a read this client does not offer")


def review(context, request_id, mode, reason, subject, *, deadline=None, raised_at="2026-11-16T13:00:00Z"):
    row = {"id": request_id, "mode": mode, "reason": reason, "ask": None, "raisedBy": "agent:announce", "raisedAt": raised_at, "deadline": deadline,
           "state": "open", "reviewStateKey": review_state_key("open"), "subject": json.dumps(subject), "updatedAt": raised_at}
    if mode == "soft_review" and deadline:
        row["dueAt"] = deadline
    context.client.reviews.append(row)
    return row


def delivery(context, delivery_id, *, release_at, lock_at=None, approved=False):
    row = {"id": delivery_id, "announcementId": delivery_id.split("#")[0], "channel": "x", "accountId": "machines", "state": "ready", "releaseAt": release_at,
           "lockAt": lock_at, "approvedVersion": 1 if approved else None, "history": "[]", "attempts": None}
    context.client.deliveries.append(records.with_due(row))


def run(context, responsibility, outcome, reason, status="failed"):
    finished = "2026-11-16T14:00:00Z"
    row = {"id": f"run-{responsibility}-{outcome}", "procedureKey": f"proc.{responsibility}", "runStatus": status, "outcome": outcome, "outcomeReason": reason,
           "responsibility": responsibility, "requestedAt": "2026-11-16T13:59:00.000Z", "finishedAt": finished, "errorSummary": "timed out after 840 s" if outcome == "failed" else None,
           **run_attention.attention_fields(outcome, finished)}
    context.client.runs.append(row)
    context.run_id = row["id"]


def read(context, *, site_zone=SITE_ZONE, requested_zone=None):
    environment = {today_attention.SITE_TIME_ZONE_ENV: site_zone} if site_zone else {}
    context.result = automation_view.handle({"fieldName": "todayOverview", "identity": {"groups": ["editor"]}, "arguments": {"timeZone": requested_zone}},
                                            env=environment, client_factory=lambda: context.client, now=NOW.timestamp())
    assert context.result.get("state") == "ready", context.result
    context.today = context.result


def acknowledge(context, groups, who="editor@example.test"):
    return automation_view.handle({"fieldName": "acknowledgeRun", "identity": {"groups": groups, "claims": {"email": who}}, "arguments": {"runId": context.run_id}},
                                  env={}, client_factory=lambda: context.client, now=NOW.timestamp())


def waiting(context, reason):
    found = [entry for entry in context.today["waiting"] if entry["reason"] == reason]
    assert found, [entry["reason"] for entry in context.today["waiting"]]
    return found[0]


def attention_run(context):
    return next((entry for entry in context.today["attention"] if entry["kind"] == "run" and entry["id"] == context.run_id), None)


def due_line(entry):
    return f"{entry['local']} {entry['words']}: {entry['title']}"


# --- given ---------------------------------------------------------------------------------------------------------


@given("a site in New York whose day is Monday 16 November 2026, and it is noon there")
def site(context):
    context.client = SiteIndexes()
    context.site_zone = SITE_ZONE


@given('an open hard gate "{reason}" about the story "{story}"')
def hard_gate(context, reason, story):
    review(context, "gate-publish", "hard_gate", reason, {"type": "story", "id": story}, raised_at="2026-11-16T15:00:00Z")


@given('an open soft review "{reason}" about the delivery "{delivery_id}" that goes on without review at {clock} New York time')
def soft_review(context, reason, delivery_id, clock):
    review(context, "announce-draft-review", "soft_review", reason, {"type": "delivery", "id": delivery_id}, deadline=new_york(clock))


@given('the day\'s rating review "{reason}" is open')
def rating_review(context, reason):
    review(context, "rr-ratings-2026-11-16", "soft_review", reason, {"type": "batch", "id": "ratings-2026-11-16"}, raised_at="2026-11-16T12:00:00Z")


@given('a Delivery for x "machines" that was due to go out at {clock} New York time and nothing ran')
def overdue_delivery(context, clock):
    context.overdue_id = "announcement-daily#x#machines#g1"
    delivery(context, context.overdue_id, release_at=new_york(clock), approved=True)


@given("the overdue check has raised its flag")
def overdue_flag(context):
    row = next(row for row in context.client.deliveries if row["id"] == context.overdue_id)
    context.overdue_flag = overdue.flag_id("Delivery", row["id"], row["dueAt"])
    review(context, context.overdue_flag, "flag", f"Overdue: Delivery {row['id']} was due {row['dueAt']} and no run started.", {"type": "delivery", "id": row["id"]})


@given('a "{responsibility}" run that was interrupted and recorded the outcome unknown')
def unknown_run(context, responsibility):
    run(context, responsibility, "unknown", "interrupted")


@given('a "{responsibility}" run that failed with "{reason}" and nobody has acknowledged it')
def failed_run(context, responsibility, reason):
    run(context, responsibility, "failed", reason)


@given('Today lists the failed run under Needs attention with the action "{words}"')
def listed_first(context, words):
    read(context)
    entry = attention_run(context)
    assert entry and entry["action"]["words"] == words, context.today["attention"]


@given('a Delivery for x "machines" that locks at {lock} and goes out at {release} New York time, not yet approved')
def due_delivery(context, lock, release):
    delivery(context, "announcement-2#x#machines#g1", release_at=new_york(release), lock_at=new_york(lock))


@given('a Delivery for x "machines" that goes out tomorrow at {clock} New York time')
def tomorrow_delivery(context, clock):
    context.tomorrow_id = "announcement-3#x#machines#g1"
    delivery(context, context.tomorrow_id, release_at=new_york(clock, day=17), approved=True)


@given('the story "{story}" is scheduled to publish at {clock} New York time')
def scheduled_story(context, story, clock):
    context.client.scheduled.append({"id": f"{story}-v2", "lineageId": story, "headline": story.replace("-", " ").title(), "scheduleState": "scheduled",
                                     "scheduledPublishAt": new_york(clock)})


@given('the agent "{title}" wakes on the schedule "{cron}" in "{zone}"')
def scheduled_agent(context, title, cron, zone):
    context.client.automations.append({
        "id": "newsletter.daily", "title": title, "enabled": True, "procedureKey": "newsletter_daily",
        "trigger": json.dumps({"kind": "schedule", "config": {"monitorId": "m", "publicationId": "p"}}),
        "definition": json.dumps({"wakes": {"schedule": {"cron": cron, "timeZone": zone}}}), "inputTemplate": "{}", "limits": "{}"})


@given("the site names no time zone")
def no_zone(context):
    context.site_zone = None


# --- when ----------------------------------------------------------------------------------------------------------


@when("Today is read")
def read_today(context):
    read(context, site_zone=context.site_zone)


@when("Today is read without naming a time zone")
def read_without_zone(context):
    read(context, site_zone=context.site_zone)


@when("an editor acknowledges the failed run from Today")
def editor_acknowledges(context):
    context.answer = acknowledge(context, ["editor"])
    assert context.answer["state"] == "acknowledged", context.answer


@when("an editor settles the run from Today")
def editor_settles(context):
    read(context)
    assert attention_run(context)["action"]["kind"] == "settle"
    context.answer = acknowledge(context, ["editor"])
    assert context.answer["state"] == "acknowledged", context.answer


@when("a reader who is not on staff acknowledges the failed run")
def reader_acknowledges(context):
    context.answer = acknowledge(context, [])


@when('an editor runs "papyrus today"')
def editor_runs(context):
    class ServerClient:   # the signed-in lane: its `graphql` goes to the function the site serves, with an editor's identity
        def graphql(self, query, variables):
            result = automation_view.handle({"fieldName": "todayOverview", "identity": {"groups": ["editor"]}, "arguments": variables},
                                            env={today_attention.SITE_TIME_ZONE_ENV: SITE_ZONE}, client_factory=lambda: context.client, now=NOW.timestamp())
            return {"todayOverview": json.dumps(result)}

    out = io.StringIO()
    assert today.command({}, as_json=False, client=ServerClient(), out=out, now=NOW) == 0
    context.output = out.getvalue().splitlines()


# --- then ----------------------------------------------------------------------------------------------------------


@then('Waiting for you lists "{reason}" as a hard gate with the action "{words}"')
def lists_gate(context, reason, words):
    entry = waiting(context, reason)
    assert entry["mode"] == "hard_gate" and entry["mark"] == "?" and entry["modeWords"].startswith("Hard gate"), entry
    assert entry["action"]["words"] == words, entry


@then('the Answer action opens the request "{reason}" in the Notification Center')
def opens_request(context, reason):
    entry = waiting(context, reason)
    assert entry["action"]["kind"] == "answer" and entry["action"]["requestId"] == entry["id"], entry


@then('Waiting for you lists, in order, "{first}", "{second}" and "{third}"')
def waiting_order(context, first, second, third):
    assert [entry["reason"] for entry in context.today["waiting"]] == [first, second, third], context.today["waiting"]


@then('Waiting for you lists "{reason}" as a soft review with the action "{words}"')
def lists_soft(context, reason, words):
    entry = waiting(context, reason)
    assert entry["mode"] == "soft_review" and entry["modeWords"] == "Soft review" and entry["action"]["words"] == words, entry


@then('the soft review "{reason}" says it goes on without review at "{local}"')
def soft_deadline(context, reason, local):
    assert waiting(context, reason)["deadlineLocal"] == local, waiting(context, reason)


@then('Needs attention lists the Delivery as "{word}" with the action "{words}"')
def overdue_listed(context, word, words):
    found = [entry for entry in context.today["attention"] if entry["kind"] == "overdue" and entry["id"] == context.overdue_id]
    assert found and word in found[0]["shown"] and found[0]["record"] == "Delivery" and found[0]["action"]["words"] == words, context.today["attention"]
    assert found[0]["action"]["note"], "Wake now says what does it until the operation is there"


@then('the Overdue Delivery was due at "{local}"')
def overdue_local(context, local):
    entry = next(entry for entry in context.today["attention"] if entry["kind"] == "overdue")
    assert entry["dueLocal"] == local, entry


@then("the overdue check's flag is not listed a second time")
def flag_once(context):
    ids = [entry["id"] for entry in context.today["attention"]]
    assert context.overdue_flag not in ids, ids
    assert [entry["kind"] for entry in context.today["attention"]] == ["overdue"], context.today["attention"]


@then("the Delivery's past release is not listed under Due today")
def not_due(context):
    assert not [entry for entry in context.today["due"] if entry["id"] == context.overdue_id], context.today["due"]


@then('Needs attention lists the run as "{shown}" with the action "{words}"')
def run_listed(context, shown, words):
    entry = attention_run(context)
    assert entry, context.today["attention"]
    assert f"{entry['mark']} {entry['words']}" == shown and entry["action"]["words"] == words, entry
    assert entry["action"]["kind"] == "settle" and entry["action"]["note"], entry


@then("Needs attention does not list the failed run")
@then("Needs attention does not list the run")
def run_gone(context):
    assert attention_run(context) is None, context.today["attention"]


@then("the run records that the editor acknowledged it")
def acknowledged_by(context):
    row = context.client.get_record("ProcedureRun", context.run_id)
    assert row["acknowledgedBy"] == "editor@example.test" and row["acknowledgedAt"] == "2026-11-16T17:00:00Z", row


@then("the failed run stays in the history, still failed")
def still_failed(context):
    row = context.client.get_record("ProcedureRun", context.run_id)
    assert row["outcome"] == "failed" and row["runStatus"] == "failed" and "attentionKey" not in row, row


@then("the settled run stays in the history as outcome unknown")
def still_unknown(context):
    row = context.client.get_record("ProcedureRun", context.run_id)
    assert row["outcome"] == "unknown" and "attentionKey" not in row and row["acknowledgedBy"], row


@then("the acknowledgement is refused")
def refused(context):
    assert context.answer == {"error": "forbidden"}, context.answer


@then("the failed run still needs a person")
def still_needs(context):
    assert run_attention.needs_attention(context.client.get_record("ProcedureRun", context.run_id))
    assert not context.client.updates


@then('the day is Monday 16 November 2026 in "{zone}", the site\'s own time zone')
def site_day(context, zone):
    assert (context.today["day"], context.today["timeZone"], context.today["timeZoneSource"]) == ("2026-11-16", zone, "site"), context.today


@then('Due today lists, in order, "{first}", "{second}", "{third}" and "{fourth}"')
def due_order(context, first, second, third, fourth):
    assert [due_line(entry) for entry in context.today["due"]] == [first, second, third, fourth], [due_line(entry) for entry in context.today["due"]]


@then("the lock says it is not yet approved")
def lock_detail(context):
    lock = next(entry for entry in context.today["due"] if entry["what"] == "lockAt")
    assert lock["detail"] == "not yet approved", lock


@then("Due today does not list the Delivery that goes out tomorrow")
def not_tomorrow(context):
    assert not [entry for entry in context.today["due"] if entry["id"] == context.tomorrow_id], context.today["due"]


@then('the day is in "{zone}" and Today says the site names no time zone')
def utc_day(context, zone):
    assert context.today["timeZone"] == zone and context.today["timeZoneSource"] == "none", context.today
    assert context.today["timeZoneNote"] == today.NO_SITE_ZONE


@then('Due today lists "{line}"')
def due_lists(context, line):
    assert line in [due_line(entry) for entry in context.today["due"]], [due_line(entry) for entry in context.today["due"]]


@then("the printed Today shows Waiting for you, then Needs attention, then Due today, then what ran")
def printed_order(context):
    headings = [line.split(" ")[0] for line in context.output if line and not line.startswith(" ")]
    positions = [next(index for index, line in enumerate(context.output) if line.startswith(heading)) for heading in ("WAITING FOR YOU", "NEEDS ATTENTION", "DUE TODAY", "WHAT RAN")]
    assert positions == sorted(positions), (headings, context.output)


@then('the printed Today has a line with "{first}" and "{second}"')
def printed_line(context, first, second):
    assert any(first in line and second in line for line in context.output), context.output


@then("the open review requests were read once, from the open partition of the review request state index")
def read_reviews(context):
    reads = [read for read in context.client.reads if read[1] == "reviewRequestsByState"]
    assert reads == [("index", "reviewRequestsByState", review_state_key("open"), None)], reads


@then("the runs that need a person were read from the attention index")
def read_attention(context):
    assert [read for read in context.client.reads if read[1] == run_attention.INDEX] == [("index", run_attention.INDEX, run_attention.attention_key(), None)]


@then("the Deliveries due were read from the due index up to the end of the day")
def read_due(context):
    reads = [read for read in context.client.reads if read[1] == "deliveriesByDue"]
    assert ("index", "deliveriesByDue", records.due_key(), {"lt": "2026-11-17T05:00:00Z"}) in reads, reads


@then("the Stories scheduled to publish were read from the schedule index for the day")
def read_schedule(context):
    assert [read for read in context.client.reads if read[0] == "schedule"] == [("schedule", "scheduled", "2026-11-16T05:00:00Z", "2026-11-17T05:00:00Z")]


@then("Today listed no whole table")
def no_table(context):
    assert not [read for read in context.client.reads if read[0] == "list"], context.client.reads
