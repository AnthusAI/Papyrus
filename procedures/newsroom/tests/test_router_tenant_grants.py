"""A router publication that names its tenant reads and writes its backend with a tenant client (papyrus_content/tenancy.py). That client asks for some AppSync
fields an untenanted one does not (the slug lookup becomes ``itemByTenantSlug``), and the router role is allowed an explicit list of fields. Record every field the
whole idea path asks for on the real client with its transport replaced, once with a tenant and once without, and check the template grants each one on that
publication's API (features_backend/router-tenant-grants.feature)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as task_tests  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from papyrus_content.graphql_authoring import INDEX_DEFINITIONS, PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.monitoring_stories import run_publication  # noqa: E402
from papyrus_content.tenancy import TENANT_INDEX_REDIRECTS  # noqa: E402
from test_idea_more_than_summary import Model, PAGE, one_reference, wildcard_grants  # noqa: E402
from test_monitoring_stories import fake_idea_sink, quiet_gate  # noqa: E402,F401

TENANT = "machines-on-machines"
API = "MachinesOnMachinesApiId"


@pytest.fixture(autouse=True)
def iam_auth(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")


def idea_path_fields(tenant, *, packs):
    """Every (Query|Mutation, field) one monitor-stories pass asks of the publication API, on the real client (``tenant``) with a recording transport."""
    rows, fake = one_reference()
    recorded: set[tuple[str, str]] = set()

    def respond(query, variables=None):
        kind, field = ("Mutation" if query.lstrip().startswith("mutation") else "Query"), task_tests.GRAPHQL_ROOT.match(query).group(1)
        recorded.add((kind, field))
        variables = variables or {}
        if field == "listStoryDrafts":
            return {field: {"status": "ok", "drafts": []}}
        if field == "fileProposal":
            return {field: {"status": "ok", "id": "proposal-1"}}
        if kind == "Mutation":
            return {field: {"id": "x"}}
        if field.startswith("get"):
            return {field: None}
        for index, definition in INDEX_DEFINITIONS.items():
            if definition["field"] == field and index == "referencesByCurationStatusKey":
                return {field: {"items": [r for r in fake.references if variables.get("curationStatusKey", "").endswith("#accepted")], "nextToken": None}}
        return {field: {"items": [], "nextToken": None}}

    client = PapyrusGraphQLAuthoringClient(endpoint=tr.ENDPOINT, tenant_id=tenant, header_factory=lambda body: {})
    client.graphql = respond
    publication = {"publicationId": task_tests.PUBLICATION, "corpusKey": task_tests.PUBLICATION, "monitorStories": {"contextPacks": {"enabled": packs}}}
    run_publication(client, publication, transport=Model(), now=NOW, out_of_time=lambda: False, fetch=lambda url: PAGE, explorer=None)
    return recorded


@pytest.mark.parametrize("packs", [False, True])
def test_every_field_the_idea_path_asks_for_with_a_tenant_client_is_granted_on_that_publications_api(packs):
    tenant_fields = idea_path_fields(TENANT, packs=packs)
    granted = task_tests.granted_fields(API) | wildcard_grants()
    assert tenant_fields <= granted, sorted(tenant_fields - granted)


def test_the_fields_a_tenant_adds_are_the_tenant_redirects_and_each_is_granted():
    """What the tenant client asks for that the untenanted one does not: recorded, not listed by hand, and every redirect target of tenancy.py is covered."""
    added = idea_path_fields(TENANT, packs=True) - idea_path_fields(None, packs=True)
    granted = task_tests.granted_fields(API) | wildcard_grants()
    assert added <= granted, sorted(added - granted)
    for target in TENANT_INDEX_REDIRECTS.values():
        assert ("Query", INDEX_DEFINITIONS[target]["field"]) in granted, target


def test_the_doctrine_lookup_asks_the_tenant_slug_index_with_the_tenant_prefixed_slug():
    from papyrus_content.ideas.context import load_context

    asked = []
    client = PapyrusGraphQLAuthoringClient(endpoint=tr.ENDPOINT, tenant_id=TENANT, header_factory=lambda body: {})

    def respond(query, variables=None):
        asked.append((task_tests.GRAPHQL_ROOT.match(query).group(1), dict(variables or {})))
        return {task_tests.GRAPHQL_ROOT.match(query).group(1): {"items": [], "nextToken": None}}

    client.graphql = respond
    load_context(client, now=NOW)
    slugs = [variables.get("tenantSlug") for field, variables in asked if field == "itemByTenantSlug"]
    assert slugs and all(str(slug).startswith(f"{TENANT}#") for slug in slugs), asked
