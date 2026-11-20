from pathlib import Path
import sys

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_monitoring_intake as intake_tests  # noqa: E402
from papyrus_content.monitoring import Monitor, SourceItem  # noqa: E402
from papyrus_content.monitoring_intake import ReferenceIntake  # noqa: E402


def _bind(context, publication_tenant, client_tenant, endpoint=None):
    context.client = intake_tests.TenantClient(client_tenant)
    context.publication_tenant = publication_tenant
    context.monitor = Monitor("hn", "publication", "knowledge-corpus-publication", endpoint or context.client.endpoint, Path("/tmp/monitor-state-unused"))
    context.saved, context.refusal = [], None


def _intake(context):
    return ReferenceIntake(context.client, context.monitor, auth_mode="iam", tenant_id=context.publication_tenant,
                           persist=lambda rows: context.saved.extend(rows))


@given('a publication in the tenant "{tenant}" and a client for that tenant')
def tenant_and_client(context, tenant):
    _bind(context, tenant, tenant)


@given('a publication in the tenant "{tenant}" and a client for the tenant "{other}"')
def tenant_and_other_client(context, tenant, other):
    _bind(context, tenant, other)


@given('a publication with no tenant and a client for the tenant "{tenant}"')
def no_tenant_tenant_client(context, tenant):
    _bind(context, None, tenant)


@given('a publication in the tenant "{tenant}" and a client for that tenant on another endpoint')
def tenant_other_endpoint(context, tenant):
    _bind(context, tenant, tenant, endpoint="https://other.example.org/graphql")


@given("a publication with no tenant and a client with no tenant")
def no_tenant(context):
    _bind(context, None, None)


@when("a monitor delivers an item to it")
def deliver(context):
    item = SourceItem("1", "A paper", "https://example.org/paper", "https://news.ycombinator.com/item?id=1", None)
    context.receipt = _intake(context)(item, {**context.monitor.binding, "sourceId": item.source_id, "sourceItemUrl": item.source_item_url,
                                             "fingerprint": item.fingerprint, "observedAt": "2026-11-07T00:00:00Z", "revision": 1})


@when("a monitor is bound to it")
def bind(context):
    try:
        _intake(context)
    except ValueError as error:
        context.refusal = error


@then("the delivery creates a pending Reference")
def creates(context):
    assert len(context.client.references) == 1 and context.client.references[0]["curationStatus"] == "pending"


@then("the Reference carries no tenant field")
def no_tenant_field(context):
    assert "tenantId" not in context.client.references[0]


@then("the binding is refused and nothing is written")
def refused(context):
    assert context.refusal is not None and "endpoint/tenant binding" in str(context.refusal)
    assert context.client.writes == [] and context.saved == []
