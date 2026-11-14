"""The editorial-checks Lambda is told the site's tenant (PPY-49303f)."""
import json
from pathlib import Path

import pytest

from papyrus_content.editorial_checks import GraphQLEditorialStore
from papyrus_content.editorial_context import _digest, build_context

ROOT = Path(__file__).resolve().parents[3]


def _store(context_tenant, **kwargs):
    pack = build_context({"key": "example", "tenantId": context_tenant}, {"sectionId": "a"},
                         [{"scope": "publication", "kind": "policy", "text": "RULE", "source": {"id": "p"}}], mode="cloud")
    pack["contextHash"] = _digest({k: v for k, v in pack.items() if k not in ("contextHash", "resolvedAt")})

    def execute(query, variables):
        if "CanonicalEditorialPublication" in query:
            return {"listKnowledgeCorporaByRoleAndName": {"items": [{"id": "knowledge-corpus-example", "name": "E", "role": "canonical"}], "nextToken": None}}
        return {"getEditorialContext": json.dumps(pack)}

    return GraphQLEditorialStore(execute, **kwargs)


def test_a_tenant_context_is_refused_by_a_function_without_the_tenant_variable(monkeypatch):
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    with pytest.raises(ValueError, match="Editorial context tenant mismatch"):
        _store("machines-on-machines").get_editorial_context("a")


def test_a_tenant_context_is_accepted_when_the_function_has_the_tenant_variable(monkeypatch):
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "machines-on-machines")
    assert _store("machines-on-machines").get_editorial_context("a")["publication"]["tenantId"] == "machines-on-machines"


def test_the_clients_tenant_wins_over_the_environment(monkeypatch):
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    assert _store("machines-on-machines", tenant_id="machines-on-machines").get_editorial_context("a")


def test_the_site_backend_gives_the_checks_function_the_tenant_variable():
    backend = (ROOT / "amplify/site-backend.ts").read_text()
    block = backend[backend.index("const backendTenantId"):]
    receivers = block[block.index("for (const tenantLambda of ["):]
    receivers = receivers[:receivers.index("]) {")]
    assert "backend.editorialChecks.resources.lambda" in receivers
