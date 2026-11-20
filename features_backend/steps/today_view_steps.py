import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
from papyrus_content import automation_view, today  # noqa: E402

ZONE = "America/New_York"
DAY = "2026-11-16"
NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)   # Monday noon in New York
BASE = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)  # Monday 10:00 in New York


class RunIndexClient:
    """Answers only the two reads Today may make, and records every read, so a whole-table list is a failure."""

    tenant_id = "site"

    def __init__(self):
        self.runs, self.automations, self.reads = [], [], []

    def list_by_index(self, index, key, *, sort_condition=None, **_):
        self.reads.append(("index", index, key, sort_condition))
        if index != "procedureRunsByStatus":   # the day's email sends (delivery-counts.feature) read the announcement records: none are made here
            return []
        low, high = sort_condition["between"]
        return [dict(row) for row in self.runs if row["runStatus"] == key and low <= row["requestedAt"] <= high]

    def list_tenant_rows(self, model, fields, **_):
        self.reads.append(("tenant", model))
        return [dict(row) for row in self.automations]

    def list_records(self, model, **_):
        self.reads.append(("list", model))
        raise AssertionError(f"Today listed the whole {model} table")

    def graphql(self, query, variables):
        raise AssertionError("Today made a read this client does not offer")


def agent(title, enabled=True, kind="monitor"):
    return {"id": title.lower().replace(" ", "."), "title": title, "enabled": enabled, "procedureKey": f"proc.{title.lower().replace(' ', '-')}",
            "trigger": json.dumps({"kind": kind, "config": {"monitorId": "m", "publicationId": "p"}}), "inputTemplate": "{}", "limits": "{}"}


def at(minutes):
    return datetime.fromtimestamp(BASE.timestamp() + minutes * 60, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def add(context, responsibility, count, *, outcome="acted", reason=None, status="completed", cost=None, when=0, automation=None):
    for number in range(count):
        row = {"id": f"run-{len(context.client.runs)}", "procedureKey": f"proc.{responsibility}", "runStatus": status, "outcome": outcome,
               "outcomeReason": reason, "responsibility": responsibility, "automationId": automation, "requestedAt": at(when + number),
               "finishedAt": at(when + number + 1), "costUsd": cost}
        context.client.runs.append(row)


@given("a site whose day is Monday 16 November 2026 in New York")
def site_day(context):
    context.client = RunIndexClient()
    context.day = DAY


@given('the site has the agents "Weekly digest" (disabled), "Announce releases" (enabled, nothing woke it) and "Rate new references" (enabled)')
def agents(context):
    context.client.automations = [agent("Weekly digest", enabled=False), agent("Announce releases"), agent("Rate new references")]
    context.client.runs.append({"id": "run-rate-agent", "procedureKey": "proc.rate-new-references", "runStatus": "completed", "outcome": "acted",
                                "automationId": "rate.new.references", "responsibility": "intake", "requestedAt": at(-60), "costUsd": 0.0})


@given('the "{responsibility}" responsibility finished {done:d} runs that did the work, {nothing:d} that found nothing to do and {asked:d} that asked a person')
def rate_mix(context, responsibility, done, nothing, asked):
    add(context, responsibility, done)
    add(context, responsibility, nothing, outcome="nothing", reason="not_rated", when=30)
    add(context, responsibility, asked, outcome="asked", reason="needs_review", when=60)


@given('the "{responsibility}" responsibility finished {count:d} runs that did the work')
def did_work(context, responsibility, count):
    add(context, responsibility, count)


@given('the "{responsibility}" responsibility finished {first:d} runs that found nothing to do because "{one}" and {second:d} because "{two}"')
def nothing_reasons(context, responsibility, first, one, second, two):
    add(context, responsibility, first, outcome="nothing", reason=one)
    add(context, responsibility, second, outcome="nothing", reason=two, when=30)


@given('the "{responsibility}" responsibility finished {count:d} runs that found nothing to do because "{reason}"')
def nothing_one_reason(context, responsibility, count, reason):
    add(context, responsibility, count, outcome="nothing", reason=reason, cost=0.0)


@given('the "{responsibility}" responsibility finished 1 run that failed with "{reason}" and has 1 run whose outcome is unknown')
def failed_unknown(context, responsibility, reason):
    add(context, responsibility, 1, outcome="failed", reason=reason, status="failed")
    add(context, responsibility, 1, outcome="unknown", reason="no_result_recorded", status="failed", when=30)


@given('the "{responsibility}" responsibility has 1 run still running and 1 finished run recorded before outcomes existed')
def going_and_old(context, responsibility):
    add(context, responsibility, 1, outcome=None, status="running")
    add(context, responsibility, 1, outcome=None, status="completed", when=30)


@given('the "{responsibility}" responsibility finished 2 runs that cost 0.25 and 0.16 and 1 run that recorded no cost')
def costed(context, responsibility):
    add(context, responsibility, 1, cost=0.25)
    add(context, responsibility, 1, cost=0.16, when=10)
    add(context, responsibility, 1, cost=None, when=20)


@given('the "{responsibility}" responsibility finished 1 run at 23:30 on Sunday and 1 at 00:30 on Tuesday, New York time')
def outside_the_day(context, responsibility):
    add(context, responsibility, 1, when=-(10 * 60 + 30))
    add(context, responsibility, 1, when=14 * 60 + 30)


@given('the "{responsibility}" responsibility finished 2 runs on Monday')
def on_monday(context, responsibility):
    add(context, responsibility, 2, when=0)


@given('the "{responsibility}" responsibility finished 2 runs started by the automation "{automation}"')
def by_automation(context, responsibility, automation):
    add(context, responsibility, 2, automation=automation)


def read(context, day=DAY):
    context.error = None
    result = automation_view.handle({"fieldName": "todayOverview", "identity": {"groups": ["editor"]}, "arguments": {"day": day, "timeZone": ZONE}},
                                    env={}, client_factory=lambda: context.client, now=NOW.timestamp())
    context.result = result
    context.today = result if result.get("state") == "ready" else None


@when("Today is read for the day")
def read_today(context):
    read(context)


@when('Today is read for the day "{day}"')
def read_bad_day(context, day):
    read(context, day)


@when('a reader who is not on staff asks for Today')
def reader_asks(context):
    context.result = automation_view.handle({"fieldName": "todayOverview", "identity": {"groups": []}, "arguments": {}}, env={},
                                            client_factory=lambda: context.client, now=NOW.timestamp())


@when('an editor runs the command "papyrus today"')
def editor_runs(context):
    out = io.StringIO()
    context.exit = today.command({}, as_json=False, client=ServerClient(context), out=out, now=NOW)
    context.output = out.getvalue().splitlines()


class ServerClient:
    """The signed-in lane's client: its `graphql` goes to the same function the site serves, with an editor's identity."""

    def __init__(self, context):
        self.context = context

    def graphql(self, query, variables):
        result = automation_view.handle({"fieldName": "todayOverview", "identity": {"groups": ["editor"]}, "arguments": {**variables, "timeZone": ZONE, "day": DAY}},
                                        env={}, client_factory=lambda: self.context.client, now=NOW.timestamp())
        return {"todayOverview": json.dumps(result)}


def line(context, title):
    found = [row for row in context.today["rows"] if row["title"] == title]
    assert found, f"no line for {title}: {[row['title'] for row in context.today['rows']]}"
    return found[0]


@then('the "{title}" line says "{words}"')
def line_says(context, title, words):
    shown = today.counts_text(line(context, title)["counts"])
    assert shown == words, shown


@then('the "{title}" line counts {count:d} runs')
def line_counts(context, title, count):
    assert len(line(context, title)["runs"]) == count, line(context, title)["runs"]


@then("the day's total is {count:d} runs")
def total(context, count):
    others = [row for row in context.client.runs if row["id"] == "run-rate-agent"]
    assert context.today["totals"]["runs"] == count + len(others), context.today["totals"]


@then('the "{title}" line gives the nothing-to-do reasons "{reasons}"')
def nothing_reasons_shown(context, title, reasons, kind="nothing"):
    assert today.reasons_text(line(context, title)["reasons"]["nothing"]) == reasons


@then('the "{title}" line gives the failed reasons "{reasons}"')
def failed_reasons_shown(context, title, reasons):
    assert today.reasons_text(line(context, title)["reasons"]["failed"]) == reasons


@then("nothing-to-do runs are not counted as failures")
def not_failures(context):
    assert context.today["totals"]["counts"]["failed"] == 0


@then("every run of the day is in exactly one count")
def one_count(context):
    totals = context.today["totals"]
    assert sum(totals["counts"].values()) == totals["runs"], totals


def not_run(context, title):
    found = [entry for entry in context.today["didNotRun"] if entry["title"] == title]
    return found[0] if found else None


@then('"{title}" is listed as "Did not run" because it is disabled')
def disabled(context, title):
    entry = not_run(context, title)
    assert entry and entry["state"] == "Did not run" and entry["whyCode"] == "disabled", entry


@then('"{title}" is listed as "Did not run" because nothing woke it today')
def no_wake(context, title):
    entry = not_run(context, title)
    assert entry and entry["state"] == "Did not run" and entry["whyCode"] == "no_wake", entry


@then('"{title}" is not listed as one that did not run once it has a run today')
def ran(context, title):
    assert not_run(context, title) is None


@then('the "{title}" line says its cost is "{cost}"')
def line_cost(context, title, cost):
    assert today.cost_text(line(context, title)) == cost, today.cost_text(line(context, title))


@then('the day\'s total cost is "{cost}"')
def day_cost(context, cost):
    totals = context.today["totals"]
    assert today.cost_text(totals) == cost, today.cost_text(totals)


@then("each run status was read once, with a time range, from the run status index")
def indexed(context):
    reads = [read for read in context.client.reads if read[0] == "index" and read[1] == "procedureRunsByStatus"]
    assert [read[2] for read in reads] == list(today.RUN_STATUSES), reads
    assert all(read[1] == "procedureRunsByStatus" and read[3] and "between" in read[3] for read in reads), reads


@then("no whole-table list of runs or agents was made")
def no_scan(context):
    assert not [read for read in context.client.reads if read[0] == "list"]
    assert ("tenant", "Automation") in context.client.reads


@then('the "{title}" line gives the command "{command}"')
def line_command(context, title, command):
    assert command in today.render(context.today)[1:] or f"    runs: {command}" in today.render(context.today)


@then('the printed Today has the line "{text}"')
def output_line(context, text):
    assert any(shown.strip() == text for shown in context.output), context.output


@then("Today is refused")
def refused(context):
    assert context.result == {"error": "forbidden"}, context.result


@then("Today is refused with a message that says it is not a date")
def refused_date(context):
    assert context.result["error"] == "bad_request" and "not a date" in context.result["message"], context.result
