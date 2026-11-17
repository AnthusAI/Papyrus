"""Every automation carries its site's tenant, and rows written without one are stamped once (features_backend/automation-tenant-id.feature).

The site is the authoring client over an in-memory API whose `tenantId` index is sparse (a row without the field is not in it), so a row written
without a tenant is invisible to `list_tenant_rows`, as it is on a live site. Every request is kept to be validated against the real schema.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import automations as au  # noqa: E402
from papyrus_content.agent_definitions import release  # noqa: E402
from papyrus_content.graphql_authoring import LIST_DEFINITIONS  # noqa: E402
from papyrus_content.tenancy import TENANT_ID_ENVIRONMENT_VARIABLE  # noqa: E402
from papyrus_content.tenant_field_backfill import apply_tenant_id_backfill, plan_tenant_id_backfill  # noqa: E402
from papyrus_content.tenant_field_backfill_commands import backfill_tenant_from_options  # noqa: E402
from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, tenant_client  # noqa: E402

NOW = "2026-11-17T04:00:00Z"
LIST_FIELDS = {definition["field"]: model for model, definition in LIST_DEFINITIONS.items()}


class SiteApi(InMemoryGraphQLBackend):
    """The in-memory API with the whole-table list queries the backfill reads, and every request kept."""

    def __init__(self):
        super().__init__()
        self.requests, self.mutations = [], 0

    def __call__(self, query, variables=None):
        self.requests.append({"query": query, "variables": variables or {}})
        if "mutation " in query:
            self.mutations += 1
        return super().__call__(query, variables)

    def _read(self, field, variables):
        if field in LIST_FIELDS:
            rows = sorted(self.tables.get(LIST_FIELDS[field], {}).values(), key=lambda row: row["id"])
            return {"items": copy.deepcopy(rows), "nextToken": None}
        return super()._read(field, variables)


def stored_automation(automation_id, *, tenant=None, enabled=True):
    record = au.build_record({"id": automation_id, "title": automation_id, "enabled": enabled, "procedureKey": "rate_items",
                              "trigger": {"kind": "schedule", "config": {}}}, actor="seed", now=NOW)
    return {**au.stored_payload(record), **({"tenantId": tenant} if tenant else {})}


def table(context, model):
    return context.api.tables.get(model, {})


@given('a site backend whose tenant is "{tenant}"')
def site_backend(context, tenant):
    context.tenant, context.api = tenant, SiteApi()
    context.client = tenant_client(context.api, tenant)
    context.report, context.error, context.written = None, None, None
    context.before_rows = {}


@given('the site holds the automation "{automation_id}" written without a tenant')
def automation_without_tenant(context, automation_id):
    table_ = context.api.tables.setdefault("Automation", {})
    table_[automation_id] = stored_automation(automation_id)


@given('the site holds the automation "{automation_id}" owned by the tenant "{tenant}"')
def automation_of_tenant(context, automation_id, tenant):
    context.api.tables.setdefault("Automation", {})[automation_id] = stored_automation(automation_id, tenant=tenant)


@given('the site holds the message "{message_id}" written without a tenant')
def message_without_tenant(context, message_id):
    context.api.tables.setdefault("Message", {})[message_id] = {"id": message_id}


@when('an operator creates the automation "{automation_id}"')
def operator_creates(context, automation_id):
    au.create_automation(context.client, {"id": automation_id, "title": automation_id, "procedureKey": "rate_items", "enabled": True,
                                          "trigger": {"kind": "schedule", "config": {}}}, actor="operator", now=NOW)


@when('an operator switches off the automation "{automation_id}"')
def operator_disables(context, automation_id):
    au.update_automation(context.client, automation_id, {"enabled": False}, actor="operator", now=NOW)


@when('the build applies the definition "{definition_id}"')
def deploy_applies(context, definition_id):
    context.error, context.mutations_before = None, context.api.mutations
    try:
        results = release.apply_release(context.client, release.load(None), {"rate_items"}, apply=True, now=NOW)
        context.report = {entry["definitionId"]: entry["status"] for entry in results}
    except release.ReleaseError as error:
        context.error, context.report = error, {}


@when('the backfill runs for the tenant "{tenant}" as a dry run')
def backfill_dry_run(context, tenant):
    context.mutations_before = context.api.mutations
    context.plan = plan_tenant_id_backfill(tenant_client(context.api, None), tenant)


@when('the backfill runs for the tenant "{tenant}" with --apply')
def backfill_apply(context, tenant):
    context.before_rows = {model: copy.deepcopy(rows) for model, rows in context.api.tables.items()}
    context.mutations_before = context.api.mutations
    reader = tenant_client(context.api, None)   # the command reads every row: it names no site tenant of its own
    context.plan = plan_tenant_id_backfill(reader, tenant)
    context.written = apply_tenant_id_backfill(reader, context.plan)


@when("the backfill runs with no tenant")
def backfill_no_tenant(context):
    context.error = None
    try:
        backfill_tenant_from_options({})
    except ValueError as error:
        context.error = error


@when("the backfill runs with a tenant set in the environment")
def backfill_tenant_in_environment(context):
    context.error = None
    saved = os.environ.get(TENANT_ID_ENVIRONMENT_VARIABLE)
    os.environ[TENANT_ID_ENVIRONMENT_VARIABLE] = context.tenant
    try:
        backfill_tenant_from_options({"tenant": context.tenant})
    except ValueError as error:
        context.error = error
    finally:
        if saved is None:
            os.environ.pop(TENANT_ID_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[TENANT_ID_ENVIRONMENT_VARIABLE] = saved


@then('the stored automation "{automation_id}" carries the tenant "{tenant}"')
def stored_carries_tenant(context, automation_id, tenant):
    assert table(context, "Automation")[automation_id].get("tenantId") == tenant, table(context, "Automation")[automation_id]


@then('the tenant\'s automation listing holds "{automation_id}"')
def listing_holds(context, automation_id):
    assert automation_id in {row["id"] for row in context.client.list_tenant_rows("Automation", "id tenantId")}


@then('the build reports "{definition_id}" as {status} and sent no write')
def deploy_reports_and_wrote_nothing(context, definition_id, status):
    assert context.error is None, context.error
    assert context.report == {definition_id: status}, context.report
    assert context.api.mutations == context.mutations_before, "the deploy wrote"


@then('the build reports "{definition_id}" as {status}')
def deploy_reports(context, definition_id, status):
    assert context.error is None, context.error
    assert context.report.get(definition_id) == status, context.report


@then('the build changes "rate" once and creates no second automation')
def deploy_changed_once(context):
    assert context.error is None, context.error
    assert context.report == {"rate": "changed"}, context.report
    assert list(table(context, "Automation")) == ["rate"]
    assert not any("mutation CreateAutomation" in request["query"] for request in context.api.requests), "the deploy created the automation again"


@then('the build is refused naming "{name}" and "{command}"')
def deploy_refused(context, name, command):
    assert isinstance(context.error, release.ReleaseError), context.error
    assert name in str(context.error) and command in str(context.error), str(context.error)


@then("no write was sent")
def nothing_written(context):
    assert context.api.mutations == context.mutations_before, f"{context.api.mutations - context.mutations_before} write(s)"


@then("the backfill would stamp {automations:d} Automation row and {messages:d} Message row")
def would_stamp(context, automations, messages):
    counts = {model.model_name: len(model.stamp) for model in context.plan.models}
    assert (counts["Automation"], counts["Message"]) == (automations, messages), counts
    assert context.plan.pending_writes == automations + messages


@then("the backfill wrote {written:d} rows and left {other:d} row of another tenant")
def backfill_counts(context, written, other):
    assert sum(context.written.values()) == written, context.written
    assert sum(len(model.other_tenant) for model in context.plan.models) == other


@then("each stamped row's other fields are as they were")
def other_fields_unchanged(context):
    for model, rows in context.before_rows.items():
        for row_id, before in rows.items():
            after = {name: value for name, value in table(context, model)[row_id].items() if name != "tenantId"}
            assert after == {name: value for name, value in before.items() if name != "tenantId"}, (model, row_id)


@then("the backfill is refused because it requires a tenant")
def refused_requires_tenant(context):
    assert context.error is not None and "requires --tenant" in str(context.error), context.error


@then("the backfill is refused because it reads every row")
def refused_reads_every_row(context):
    assert context.error is not None and "reads every row" in str(context.error), context.error


@then("every request sent is accepted by the GraphQL schema Amplify generates from the data schema")
def requests_match_schema(context):
    assert context.api.requests, "the scenario sent no request"
    with tempfile.TemporaryDirectory() as folder:
        operations = Path(folder) / "operations.json"
        operations.write_text(json.dumps(context.api.requests))
        run = subprocess.run(["npx", "tsx", "scripts/graphql-operations-contract.mts", str(operations)], cwd=REPO_ROOT, capture_output=True, text=True)
    verdicts = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    assert len(verdicts) == len(context.api.requests), run.stderr[-2000:] or run.stdout[-2000:]
    rejected = [verdict for verdict in verdicts if verdict["problems"]]
    assert not rejected, "the schema refuses: " + json.dumps(rejected, indent=2)
    context.verdict_operations = {verdict["operation"] for verdict in verdicts}


@then("the requests include a create, an update and the tenant listing of Automation")
def requests_cover_kinds(context):
    assert {"CreateAutomation", "UpdateAutomation", "ListAutomationsByTenant"} <= context.verdict_operations, context.verdict_operations
