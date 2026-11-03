import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
from papyrus_content import editorial_context  # noqa: E402
from papyrus_content.monitoring_router import validate_router_publications  # noqa: E402


@given('a section stamped with the tenant "{tenant}"')
def step_section(context, tenant):
    context.tenant = SimpleNamespace(section={"id": f"{tenant}#analysis", "tenantId": tenant}, outcome=None)


def check(context, tenant):
    client = SimpleNamespace(tenant_id=tenant)
    try:
        editorial_context._check_tenant(client, context.tenant.section)
        context.tenant.outcome = "accepted"
    except ValueError as error:
        context.tenant.outcome = str(error)


@when("the editorial check looks at the section with a client that has no tenant")
def step_no_tenant(context):
    check(context, None)


@when('the editorial check looks at the section with a client of the tenant "{tenant}"')
def step_with_tenant(context, tenant):
    check(context, tenant)


@then("it is refused with the message that the tenant does not match the configured authoring scope")
def step_refused(context):
    assert context.tenant.outcome == "Editorial record tenant does not match the configured authoring scope.", context.tenant.outcome


@then("it is accepted")
def step_accepted(context):
    assert context.tenant.outcome == "accepted", context.tenant.outcome


@given('a router with the publication "{first}" naming the tenant "{tenant}" and the publication "{second}" naming none')
def step_router(context, first, tenant, second):
    table, store = tms.router((first, second))
    config = table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    config["publications"][0]["tenantId"] = tenant
    table.put_item(config)
    context.tenant = SimpleNamespace(store=store, built={}, first=first, second=second)


@when("the router builds the clients of both")
def step_build(context):
    from papyrus_content.monitoring_router import Router, validate_router_config

    state = context.tenant
    raw = state.store.get_router_config("hn")
    config = validate_router_config(raw)

    def factory(endpoint, tenant=None):
        state.built[endpoint] = tenant
        return object()

    router = Router(state.store, config, monitor_id="hn", now=0, run_id="r", cyclotron=None, appsync=factory, deliver=tr.Delivery())
    for publication in config["publications"]:
        router.client(publication)
    state.endpoints = {publication["publicationId"]: publication["appsyncEndpoint"] for publication in config["publications"]}


@then('the client of "{publication}" was built with the tenant "{tenant}"')
def step_with(context, publication, tenant):
    state = context.tenant
    assert state.built[state.endpoints[publication]] == tenant, state.built


@then('the client of "{publication}" was built without a tenant')
def step_without(context, publication):
    state = context.tenant
    assert state.built[state.endpoints[publication]] is None, state.built


@when('a router configuration names the tenant "{tenant}"')
def step_bad(context, tenant):
    context.tenant = SimpleNamespace(raw={"publications": [{"publicationId": "example-site", "site": "x", "appsyncEndpoint": tr.ENDPOINT, "tenantId": tenant}]}, error=None)
    try:
        validate_router_publications(context.tenant.raw)
    except Exception as error:  # noqa: BLE001
        context.tenant.error = error


@then("the configuration is refused")
def step_refused_config(context):
    assert context.tenant.error is not None


@given("an index with no vectors and {count:d} note Messages")
def step_notes(context, count):
    context.tenant = SimpleNamespace(notes=[{"id": f"m{n}"} for n in range(count)], read=[], stats=None)


@when("the router's index sync runs over no References")
def step_sync(context):
    from papyrus_knowledge_query import vector_index
    from papyrus_knowledge_query.services import KnowledgeQueryServices

    state = context.tenant

    def note_list(graph):
        state.read.append("list")
        return state.notes

    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=[]), mock.patch.object(vector_index, "_list_note_messages", side_effect=note_list), \
            mock.patch.object(vector_index, "_prepare_note_messages", side_effect=lambda services, messages: state.read.append("prepare") or []), \
            mock.patch.object(vector_index, "_list_index_vectors", return_value=[]), mock.patch.object(vector_index, "_prepare_concept_card_vectors", return_value=[]), \
            mock.patch.object(vector_index, "_apply_status_reconciliation"):
        services = KnowledgeQueryServices(graph=mock.Mock(), corpus_text=object())
        state.stats = vector_index.index_reference_passages(services, vector_index.VectorIndexOptions(
            action="sync", worker_count=1, include_ontology_vectors=False, include_notes=False, skip_indexed=True))


@then("no note Message was read")
def step_none_read(context):
    assert context.tenant.read == [], context.tenant.read
