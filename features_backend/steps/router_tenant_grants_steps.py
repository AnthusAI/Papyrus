import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_stories as task_tests  # noqa: E402
import test_router_tenant_grants as rt  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from test_idea_more_than_summary import wildcard_grants  # noqa: E402
from _pytest.monkeypatch import MonkeyPatch  # noqa: E402


def granted():
    return task_tests.granted_fields(rt.API) | wildcard_grants()


def run_with_sinks(function, *args, **kwargs):
    """The filing sink and the editorial gate are doubles in the router task tests; use the same ones here."""
    from papyrus_content.ideas import gate as gate_module
    from fake_idea_store import FakeIdeaStore
    from test_idea_items import FakeGate

    patches = MonkeyPatch()
    try:
        patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
        patches.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate")))
        patches.setattr("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate()))
        return function(*args, **kwargs)
    finally:
        patches.undo()


@given('a publication "{publication}" whose router entry names its tenant')
def step_publication(context, publication):
    context.grants = SimpleNamespace(tenant=publication, fields=None, plain=None, asked=None)


@when("one monitor-stories pass runs on the tenant client with context packs {packs}")
def step_pass(context, packs):
    context.grants.fields = run_with_sinks(rt.idea_path_fields, context.grants.tenant, packs=packs == "on")


@then("every field it asked for is granted to the router on that publication's API")
def step_granted(context):
    missing = sorted(context.grants.fields - granted())
    assert not missing, missing


@when("the fields of a pass on the tenant client are compared with those of a pass on a client with no tenant")
def step_compare(context):
    state = context.grants
    state.fields = run_with_sinks(rt.idea_path_fields, state.tenant, packs=True)
    state.plain = run_with_sinks(rt.idea_path_fields, None, packs=True)


@then("the tenant client asked additionally for the tenant slug lookup")
def step_added(context):
    state = context.grants
    assert ("Query", "itemByTenantSlug") in state.fields - state.plain, state.fields - state.plain


@then("every field the tenant client added is granted to the router")
def step_added_granted(context):
    state = context.grants
    missing = sorted((state.fields - state.plain) - granted())
    assert not missing, missing


@when("the editorial doctrine is looked up on the tenant client")
def step_doctrine(context):
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
    from papyrus_content.ideas.context import load_context

    asked = []
    client = PapyrusGraphQLAuthoringClient(endpoint=rt.tr.ENDPOINT, tenant_id=context.grants.tenant, header_factory=lambda body: {})

    def respond(query, variables=None):
        field = task_tests.GRAPHQL_ROOT.match(query).group(1)
        asked.append((field, dict(variables or {})))
        return {field: {"items": [], "nextToken": None}}

    client.graphql = respond
    load_context(client, now=NOW)
    context.grants.asked = asked


@then('every slug asked for begins with "{prefix}"')
def step_slugs(context, prefix):
    slugs = [variables.get("tenantSlug") for field, variables in context.grants.asked if field == "itemByTenantSlug"]
    assert slugs and all(str(slug).startswith(prefix) for slug in slugs), context.grants.asked
