"""At the budget, paid agent work waits and says so (features_backend/agents/spend-stop.feature, PPY-9376f8)."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = REPO_ROOT / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import agent_wakes, graphql_authoring, model_attachments, procedure_runner as pr, run_outcomes, spend_ledger, spend_stop  # noqa: E402
from papyrus_content.agent_definitions import cli as agents_cli  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore, PolicyGate  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402
from papyrus_content.spend_brake import SpendBrake  # noqa: E402
from papyrus_content.spend_brake_test import HaltableTable  # noqa: E402

TENANT, BUCKET, AGENT = "alpha", "site-bucket", "rate"
PEOPLE = {"admin": Caller(kind="person", subject="ada", is_admin=True), "agent": Caller(kind="agent", subject="rating-agent")}


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class BudgetSiteBackend(tpr.NewsroomClient):
    """One site's API as the runner and the budget command use it: run records (the id comes from the wake key, and each is stamped in the order it was
    requested), the automation with its registered definition, review requests, and the run status index."""

    tenant_id = TENANT

    def __init__(self):
        super().__init__()
        self.records, self.reviews, self.requested, self.spend_stop_requests = {}, {}, 0, []
        self.automation = {"id": AGENT, "responsibility": AGENT, "procedureKey": "papyrus.rate", "definition": json.dumps({"id": AGENT, "paid": True})}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id})}
            self.requested += 1
            self.records[run_id] = {"id": run_id, "tenantId": TENANT, "runStatus": "started", "wakeKey": variables["wakeKey"],
                                    "requestedAt": f"2026-11-18T15:00:{self.requested:02d}Z"}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        if "updateProcedureRun" in query:
            if "UpdateWaitingProcedureRun" in query:
                self.spend_stop_requests.append({"query": query, "variables": variables})
            self.records[variables["input"]["id"]].update(variables["input"])
            return {"updateProcedureRun": {"id": variables["input"]["id"]}}
        return super().graphql(query, variables)

    def get_record(self, model, record_id):
        if model == "Automation":
            return self.automation if record_id == AGENT else None
        if model == "ReviewRequest":
            return self.reviews.get(record_id)
        assert model == "ProcedureRun", model
        return self.records.get(record_id)

    def create_record(self, model, record):
        assert model == "ReviewRequest"
        self.reviews[record["id"]] = dict(record)
        return record

    def list_by_index(self, index_name, key_value, **options):
        if index_name != spend_stop.WAITING_INDEX:
            return super().list_by_index(index_name, key_value, **options)   # the procedure's own attachments
        assert key_value == spend_stop.WAITING, key_value
        rows = [dict(row) for row in self.records.values() if row.get("runStatus") == key_value]
        return list(reversed(rows))   # the order of the rows is the reader's to set


class CycleTimers:
    """The site's follow-up timers as far as the spend stop uses them: one entry per record, the latest message wins."""

    def __init__(self):
        self.entries = {}

    def wake_again_at(self, record_kind, record_id, request, *, due_at):
        self.entries[(record_kind, record_id)] = {"dueAt": due_at, "body": agent_wakes.message_body(dict(request))}
        return request["wakeKey"]


def wake_request(key):
    return {**tpr.REQUEST, "procedureKey": "papyrus.rate", "wakeKey": key, "tenantId": TENANT, "siteBucket": BUCKET, "publicationId": "alpha",
            "input": {}, "trigger": {"kind": "schedule", "automationId": AGENT, "summary": f"Scheduled run of {AGENT}", "serialBy": "agent"}}


def from_queue(body):
    """What the runner reads from one queue message: the message must be a well-formed wake (agent_wakes.request_from_event)."""
    return agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": body}]})


def deliver(context, request):
    def execute(*args, **kwargs):
        context.executed.append(request["wakeKey"])
        return {"success": True, "output": {"title": "rated"}, "seconds": 1}

    brake = SpendBrake(context.ledger, default_budget=Decimal("100"), clock=lambda: utc(context.clock))
    stop = spend_stop.SpendStop(timers=lambda _request: context.timers, send=context.send, now=lambda: context.clock)
    gate = PolicyGate(context.client, policy=context.policy, tenant_id=TENANT)
    context.result = pr.run_procedure_request(request, client=context.client, policy=gate, execute=execute, seconds_available=900, environment={},
                                              spend_brake=brake, spend_stop=stop)


@given('a site whose "{agent}" agent is at the rung "{rung}" with a budget of {amount:d} dollars a week')
def site(context, agent, rung, amount):
    context.client, context.ledger, context.timers = BudgetSiteBackend(), HaltableTable(), CycleTimers()
    context.policy = AgentPolicyStore(SiteStore(FakeS3(), BUCKET, FakeTable(), now=lambda: "2026-11-16T00:00:00Z"))
    context.policy.set_rung(TENANT, PEOPLE["admin"], agent, rung, reason="Seed")
    context.policy.set_value(TENANT, PEOPLE["admin"], "budget", {"amountUsd": amount, "period": "week"}, reason="Seed")
    context.executed, context.queue, context.envelope, context.exit_code = [], [], None, None
    context.send = lambda request, deduplication=None: context.queue.append({"body": agent_wakes.message_body(request), "deduplication": deduplication})
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)


@given("the ledger holds {amount:d} dollars of spend for the week of {start}")
def spent(context, amount, start):
    spend_ledger.record_run(context.ledger, tenant_id=TENANT, responsibility=AGENT, run_id="earlier-run", period="week", cost_usd=amount, calls=1,
                            unpriced_calls=0, moment=utc(f"{start}T12:00:00Z"))


@given('the runner\'s clock reads "{moment}"')
def clock(context, moment):
    context.clock = moment


@given('the "{agent}" agent\'s registered definition says it is free')
def free(context, agent):
    context.client.automation["definition"] = json.dumps({"id": agent, "paid": False})


@when('the paid wake "{key}" arrives')
@when('the wake "{key}" arrives')
def arrives(context, key):
    deliver(context, from_queue(agent_wakes.message_body(wake_request(key))))


@given('the paid wake "{key}" arrived and waited')
def arrived_and_waited(context, key):
    arrives(context, key)
    assert context.result.get("waiting") is True, context.result


@when('the runner\'s clock reads "{moment}" and the cycle\'s timer fires')
def timer_fires(context, moment):
    context.clock = moment
    (entry,) = context.timers.entries.values()
    deliver(context, from_queue(entry["body"]))


@when("the cycle's timer message is delivered again")
def timer_again(context):
    (entry,) = context.timers.entries.values()
    deliver(context, from_queue(entry["body"]))


@when("the wake queue delivers every released wake")
def deliver_released(context):
    while context.queue:
        deliver(context, from_queue(context.queue.pop(0)["body"]))


def budget_command(context, who, amount, reason, apply):
    argv = ["--amount", str(amount), "--period", "week", "--reason", reason] + (["--apply"] if apply else [])
    out = io.StringIO()
    context.exit_code = agents_cli.set_budget_command(argv, out, client_factory=lambda: context.client, policy_factory=lambda client: context.policy,
                                                      caller_factory=lambda client, caller: PEOPLE[who], sender_factory=lambda: context.send)
    context.envelope = json.loads(out.getvalue())


@when('an admin raises the site\'s budget to {amount:d} dollars a week because "{reason}" and applies it')
def admin_raises(context, amount, reason):
    budget_command(context, "admin", amount, reason, True)
    assert context.exit_code == 0, context.envelope


@when('an agent raises the site\'s budget to {amount:d} dollars a week because "{reason}" and applies it')
def agent_raises(context, amount, reason):
    budget_command(context, "agent", amount, reason, True)


@when('an admin raises the site\'s budget to {amount:d} dollars a week because "{reason}" as a dry run')
def admin_dry_run(context, amount, reason):
    budget_command(context, "admin", amount, reason, False)
    assert context.exit_code == 0, context.envelope


def run_of(context, key):
    return context.client.records["run-for-" + key]


def keys(text):
    return [part.strip() for part in text.split(",")]


@then("the rate procedure ran {count:d} time")
@then("the rate procedure ran {count:d} times")
def ran(context, count):
    assert len(context.executed) == count, context.executed


@then('the rate procedure ran for "{wakes}" in that order')
def ran_in_order(context, wakes):
    assert context.executed == keys(wakes), context.executed


@then('the run record of "{key}" is waiting for "{waiting_for}" until "{due}"')
def is_waiting(context, key, waiting_for, due):
    run = run_of(context, key)
    assert (run["runStatus"], run["waitingFor"], run["dueAt"], run.get("outcome")) == ("waiting", waiting_for, due, None), run


@then('that run record keeps the wake "{key}" so it can run again')
def keeps_wake(context, key):
    wake = json.loads(run_of(context, key)["wake"])
    assert wake["wakeKey"] == key and wake["procedureKey"] == "papyrus.rate" and wake["trigger"]["automationId"] == AGENT, wake
    assert spend_stop.RELEASED_FROM not in wake["trigger"], "the kept wake is the wake as it first came"


@then('its line in the run list reads "{text}"')
def line(context, text):
    (run,) = context.client.records.values()
    assert run_outcomes.outcome_shown(run) == text, run_outcomes.outcome_shown(run)


@then('the cycle\'s one timer is due at "{due}"')
def timer_due(context, due):
    (entry,) = context.timers.entries.values()
    assert entry["dueAt"] == due, entry


@then('the cycle\'s one timer carries the wake "{key}" and is due at "{due}"')
def timer_carries(context, key, due):
    (entry,) = context.timers.entries.values()
    assert entry["dueAt"] == due and json.loads(entry["body"])["wake"]["key"] == key, entry


@then('the run record of "{key}" is completed with the outcome "{outcome}"')
def completed(context, key, outcome):
    run = run_of(context, key)
    assert (run["runStatus"], run["outcome"]) == ("completed", outcome), run


@then('every one of those run records is completed with the outcome "{outcome}"')
def all_completed(context, outcome):
    for key in context.executed:
        completed(context, key, outcome)
        run = run_of(context, key)
        assert not run.get("waitingFor") and not run.get("dueAt") and not run.get("wake"), run


@then("the admins were sent no budget flag")
def no_flag(context):
    assert not context.client.reviews, context.client.reviews


@then('the admins have exactly one budget flag, "{request_id}", saying the waiting work runs at "{due}"')
def one_flag(context, request_id, due):
    assert list(context.client.reviews) == [request_id], context.client.reviews
    flag = context.client.reviews[request_id]
    assert flag["mode"] == "flag" and flag["state"] == "open" and due in flag["ask"] and "set-budget" in flag["ask"], flag
    assert "budget for this week is reached" in flag["reason"] and "Free checks" in flag["reason"], flag


@then('{count:d} run records are waiting for "{waiting_for}"')
def count_waiting(context, count, waiting_for):
    assert [run["waitingFor"] for run in context.client.records.values() if run["runStatus"] == "waiting"] == [waiting_for] * count, context.client.records


@then('the wake queue was given the released wakes "{wakes}" in that order')
def released_in_order(context, wakes):
    bodies = [json.loads(message["body"]) for message in context.queue]
    assert [body["wake"]["key"] for body in bodies] == keys(wakes), bodies
    assert all(body["request"]["trigger"][spend_stop.RELEASED_FROM] == spend_stop.WAITING_FOR for body in bodies), bodies
    assert len({message["deduplication"] for message in context.queue}) == len(bodies), "each released wake is its own message on the queue"


@then("the wake queue was given no released wake")
def none_released(context):
    assert context.queue == [], context.queue


@then("no run record is waiting")
def none_waiting(context):
    assert not [run for run in context.client.records.values() if run["runStatus"] == "waiting"], context.client.records


@then("the site keeps {count:d} run record in all")
@then("the site keeps {count:d} run records in all")
def run_records(context, count):
    assert len(context.client.records) == count, context.client.records


@then("the agent policy holds a budget of {amount:d} dollars a week")
def policy_budget(context, amount):
    assert context.policy.read(TENANT).document["site"]["budget"] == {"amountUsd": amount, "period": "week"}


@then('the budget command is refused as "{code}"')
def refused(context, code):
    assert context.exit_code != 0 and context.envelope["ok"] is False and context.envelope["error"]["code"] == code, context.envelope


@then('the dry run names the waiting wake "{key}"')
def dry_run_names(context, key):
    result = context.envelope["result"]
    assert result["action"] == "dry-run" and not result["applied"] and result["waiting"] == [key], result
    assert result["budget"] == {"before": {"amountUsd": 5, "period": "week"}, "after": {"amountUsd": 20, "period": "week"}}, result


@then("the spend stop's writes and its read of the waiting runs are accepted by the GraphQL schema Amplify generates from the data schema")
def schema_accepts(context):
    definition = graphql_authoring.INDEX_DEFINITIONS[spend_stop.WAITING_INDEX]
    read = {"query": graphql_authoring._index_query(definition["field"], definition["partitionKey"], definition["fields"]),
            "variables": {"runStatus": spend_stop.WAITING, "limit": 100, "nextToken": None}}
    requests = [*context.client.spend_stop_requests, read]
    assert {request["variables"].get("input", {}).get("runStatus") for request in requests[:-1]} == {"waiting", "started"}, requests
    with tempfile.TemporaryDirectory() as folder:
        operations = Path(folder) / "operations.json"
        operations.write_text(json.dumps(requests))
        run = subprocess.run(["npx", "tsx", "scripts/graphql-operations-contract.mts", str(operations)], cwd=REPO_ROOT, capture_output=True, text=True)
    verdicts = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    assert len(verdicts) == len(requests), run.stderr[-2000:] or run.stdout[-2000:]
    rejected = [verdict for verdict in verdicts if verdict["problems"]]
    assert not rejected, "the schema refuses: " + json.dumps(rejected, indent=2)
