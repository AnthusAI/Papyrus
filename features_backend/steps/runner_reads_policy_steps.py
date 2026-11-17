from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import model_attachments, procedure_runner as pr, run_outcomes  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore, PersonStart  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

TENANT, BUCKET = "alpha", "site-bucket"   # the same tenant the policy steps of agent-policy.feature use
ADMIN = Caller(kind="person", subject="ada", is_admin=True)


class CountingS3(FakeS3):
    def __init__(self):
        super().__init__()
        self.reads = []

    def get_object(self, Bucket, Key):
        self.reads.append(Key)
        return super().get_object(Bucket, Key)


class SiteBackend(tpr.NewsroomClient):
    """One site's API: the run records (the id comes from the wake key), the automations, and the site-document catalogue."""

    def __init__(self, table):
        super().__init__()
        self.table, self.records, self.automations, self.queries, self.reviews = table, {}, {}, [], {}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        for field, model in (("getSiteDocumentVersion", "SiteDocumentVersion"), ("getSiteDocument", "SiteDocument")):
            if field in query:
                self.queries.append(field)
                return {field: self.table.get(model, variables["id"])}
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
        return result

    def get_record(self, model, record_id):
        assert model in ("Automation", "ReviewRequest")
        return (self.automations if model == "Automation" else self.reviews).get(record_id)

    def create_record(self, model, record):
        assert model == "ReviewRequest"
        self.reviews[record["id"]] = record
        return record


@given('a site backend with the published procedure "{key}"')
def backend(context, key):
    context.site_table, context.s3 = FakeTable(), CountingS3()
    context.client = SiteBackend(context.site_table)
    context.policy = AgentPolicyStore(SiteStore(context.s3, BUCKET, context.site_table, now=lambda: "2026-11-16T00:00:00Z"))
    context.procedure_key, context.executed, context.result, context.refusal = key, [], None, None
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)


@given('the automation "{automation_id}" runs that procedure')
def automation(context, automation_id):
    context.automation_id = automation_id
    context.client.automations[automation_id] = {"id": automation_id, "title": "TTAB analysis", "enabled": True, "procedureKey": context.procedure_key}


@given('the automation is adopted as "{responsibility}"')
def adopted(context, responsibility):
    context.client.automations[context.automation_id]["responsibility"] = responsibility


@given('the policy sets "{responsibility}" to "{rung}"')
def sets_rung(context, responsibility, rung):
    context.policy.set_rung(TENANT, ADMIN, responsibility, rung, reason="Seed")


@given('an admin paused the site because "{why}"')
def site_paused(context, why):
    context.policy.pause(TENANT, ADMIN, reason=why)


@given("the site has never saved an agent policy")
def never_saved(context):
    assert context.site_table.rows == {}


@given("the policy document cannot be read")
def unreadable(context):
    context.s3.objects.clear()


def request_for(context, trigger):
    return {**tpr.REQUEST, "procedureKey": context.procedure_key, "wakeKey": f"{context.automation_id}|manual|{len(context.client.records)}",
            "tenantId": TENANT, "siteBucket": BUCKET, "trigger": trigger}


def start(context, request, policy=None):
    def execute(*args, **kwargs):
        context.executed.append(request["wakeKey"])
        return {"success": True, "output": {"title": "x"}, "seconds": 1}

    context.s3.reads.clear(), context.client.queries.clear()
    try:
        policy = policy or pr.policy_for(request, context.client, lambda: context.s3)
        context.result = pr.run_procedure_request(request, policy=policy, client=context.client, execute=execute, seconds_available=900, environment={})
    except pr.ProcedureNotRunnable as error:
        context.refusal = error


def record(context):
    (stored,) = context.client.records.values()
    return stored


@when("a wake arrives for the automation")
def wake(context):
    start(context, request_for(context, {"kind": "manual", "automationId": context.automation_id}))
    assert context.refusal is None, context.refusal


@when("a wake arrives for the automation and is refused")
def wake_refused(context):
    start(context, request_for(context, {"kind": "manual", "automationId": context.automation_id}))
    assert context.refusal is not None


@when("a wake arrives that names no automation")
def wake_without_automation(context):
    start(context, request_for(context, {"kind": "manual"}))


@when("a person starts the procedure from their own session")
def person(context):
    start(context, request_for(context, {"kind": "cli"}), policy=PersonStart())


@when("a wake arrives with no tenant and no site bucket")
def wake_without_location(context):
    request = {key: value for key, value in request_for(context, {"kind": "manual", "automationId": context.automation_id}).items()
               if key not in ("tenantId", "siteBucket")}
    start(context, request)


@then("no procedure ran")
def none_ran(context):
    assert context.executed == []


@then("the procedure ran once")
def ran_once(context):
    assert len(context.executed) == 1


@then('the run record says nothing to do with the reason "{reason}"')
def nothing_to_do(context, reason):
    stored = record(context)
    assert (stored["runStatus"], stored["outcome"], stored["outcomeReason"]) == ("completed", "nothing", reason), stored
    assert context.result["skipped"] is True and context.result["outcomeReason"] == reason


@then('the run record says "{words}"')
def says(context, words):
    assert record(context)["resultSummary"] == words, record(context)


@then('the run record names policy version {version:d} and the rung "{rung}"')
def names_version_and_rung(context, version, rung):
    stored = record(context)
    assert (stored["policyVersion"], stored["rung"]) == (version, rung), stored


@then('the run record names the responsibility "{responsibility}", policy version {version:d} and the rung "{rung}"')
def names_everything(context, responsibility, version, rung):
    stored = record(context)
    assert (stored["responsibility"], stored["policyVersion"], stored["rung"]) == (responsibility, version, rung), stored
    assert (context.result["responsibility"], context.result["policyVersion"], context.result["rung"]) == (responsibility, version, rung)


@then("the run record names no responsibility and no rung")
def names_none(context):
    stored = record(context)
    assert not any(stored.get(key) for key in ("responsibility", "rung", "policyVersion")), stored


@then('the run record is failed with the reason "{reason}"')
def failed(context, reason):
    stored = record(context)
    assert (stored["runStatus"], stored["outcome"], stored["outcomeReason"]) == ("failed", "failed", reason), stored
    assert context.refusal.run_id == stored["id"]


@then('the run list shows "{words}"')
def listed(context, words):
    assert run_outcomes.outcome_shown(record(context)) == words, run_outcomes.outcome_shown(record(context))


@then("the runner read the policy document row, the live version's row and the live version's body, and nothing else")
def read_by_key(context):
    assert context.client.queries == ["getSiteDocument", "getSiteDocumentVersion"], context.client.queries
    assert context.s3.reads == [f"tenants/{TENANT}/site/agents/2.json"], context.s3.reads


@then("the request is refused because it names no site policy")
def refused_no_location(context):
    assert context.refusal is not None and "names no site policy" in str(context.refusal)
    assert context.executed == [] and len(context.client.records) == 1, "the refusal is recorded on the wake's one run record"


@then("the run record belongs to the automation")
def belongs_to_automation(context):
    assert record(context)["automationId"] == context.automation_id, record(context)
