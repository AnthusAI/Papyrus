"""PPY-96ae60: tenant context survives the trusted automation-to-worker boundary."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from papyrus_content import procedure_runner as pr
from papyrus_content.localize import record
from test_automation_run_now import WritableTable, start

TENANT = "machines-on-machines"


def launched_request(tenant=TENANT):
    table = WritableTable()
    publication = table.rows[("MONITOR#ttab", "CONFIG#router")]["publications"][0]
    if tenant is not None:
        publication["tenantId"] = tenant
    _, _, requests = start(table=table)
    return requests[0]


def source_eligibility(tenant, group, lineage="story-1"):
    # Stop immediately after collect's actual source-eligibility gate, before any model/config work.
    class Eligible(Exception):
        pass
    client = SimpleNamespace(tenant_id=tenant, graphql=lambda *_: None)
    with patch("papyrus_content.story_reporting.published_story_version", return_value={"itemLineageId": lineage, "languageGroupId": group}), \
         patch("papyrus_content.editorial_checks.GraphQLEditorialStore", side_effect=Eligible):
        try:
            record.collect(client, story=lineage, language="es-419", judge=None, procedure_version="test")
        except Eligible:
            return True
        except ValueError as error:
            assert "is itself a translation" in str(error)
            return False


def test_router_publication_tenant_survives_request_and_child_environment(monkeypatch):
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "unrelated")
    request = pr.validate_request(launched_request())
    environment = pr.child_environment(request, None)
    assert request["tenantId"] == TENANT
    assert environment["PAPYRUS_TENANT_ID"] == TENANT
    assert source_eligibility(environment["PAPYRUS_TENANT_ID"], f"{TENANT}#story-1")


@pytest.mark.parametrize("tenant,group,lineage,eligible", [
    (TENANT, f"{TENANT}#story-1", "story-1", True),
    (None, f"{TENANT}#story-1", "story-1", False),
    ("other", f"{TENANT}#story-1", "story-1", False),
    (TENANT, f"{TENANT}#story-1", "story-es", False),
    (None, "story-1", "story-1", True),
])
def test_source_guard(tenant, group, lineage, eligible):
    assert source_eligibility(tenant, group, lineage) is eligible


def test_a_request_without_a_tenant_does_not_inherit_the_workers_or_the_inputs(monkeypatch):
    monkeypatch.setenv("PAPYRUS_TENANT_ID", TENANT)
    request = launched_request()
    request["input"]["tenantId"] = "caller-controlled"
    request.pop("tenantId")
    environment = pr.child_environment(pr.validate_request(request), None)
    assert "PAPYRUS_TENANT_ID" not in environment
    assert source_eligibility(environment.get("PAPYRUS_TENANT_ID"), "story-1")


@pytest.mark.parametrize("tenant", ["", "bad#tenant", 3, {}, False])
def test_invalid_explicit_tenant_is_not_runnable(tenant):
    request = launched_request(None)
    request["tenantId"] = tenant
    with pytest.raises(pr.ProcedureNotRunnable, match="tenantId"):
        pr.validate_request(request)


def wake_event(request):
    from papyrus_content import agent_wakes
    return {"Records": [{"eventSource": "aws:sqs", "messageId": "m-1", "body": agent_wakes.message_body(request)}]}


def test_handler_scopes_parent_and_child_and_clears_warm_tenant(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://unused.example/graphql")
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    monkeypatch.delenv("TRIGGER_TABLE_NAME", raising=False)
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "stale")
    observed = []
    def client():
        import os
        observed.append(os.environ.get("PAPYRUS_TENANT_ID"))
        return object()
    with patch("papyrus_content.graphql_authoring.PapyrusGraphQLAuthoringClient", side_effect=client), \
         patch.object(pr, "policy_for", return_value=None), \
         patch.object(pr, "run_procedure_request", return_value={"runStatus": "completed", "runId": "test", "outcome": "acted"}) as run:
        for tenant in (TENANT, None):
            request = launched_request(TENANT)
            request.pop("openaiKeyParameter", None)
            if tenant is None:
                request.pop("tenantId")
            pr.handler(wake_event(request), None)
            assert run.call_args.kwargs["environment"].get("PAPYRUS_TENANT_ID") == tenant
    assert observed == [TENANT, None]


def test_auto_localize_dispatch_uses_the_same_trusted_router_tenant():
    import automation_fixture as fx
    from papyrus_content import automations as au
    from papyrus_content.localize import dispatch
    table = WritableTable()
    table.rows[("MONITOR#ttab", "CONFIG#router")]["publications"][0]["tenantId"] = TENANT
    row = {"id": "wanted-es", "automationId": "distinctive.ttab", "languageGroupId": "story-1",
           "language": "es-419", "sourceVersionNumber": 1, "sourceContentHash": "hash"}
    client = SimpleNamespace(get_record=lambda *_: fx.automation_row(inputTemplate="{}"), update_record_if=lambda *_: True)
    requests = []
    with patch.object(dispatch.desired_state, "wanted", return_value=[row]):
        outcomes = dispatch.drain(client, reader=au.MonitoringReader(table), writer=au.MonitoringWriter(table),
                                  invoke=requests.append, site_endpoint=fx.SITE_ENDPOINT, now="2026-10-24T09:00:00Z")
    assert outcomes[0]["status"] == "started"
    assert requests[0]["tenantId"] == TENANT
    assert requests[0]["input"]["story"] == "story-1"
