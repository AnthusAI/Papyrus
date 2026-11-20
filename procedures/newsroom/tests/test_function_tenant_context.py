"""Every moved Python function builds its one TenantContext from the event and refuses before any read (PPY-7dc463).

The list of functions is features_backend/fixtures/function-tenant-context/handlers.json, which scripts/test-function-tenant-context.ts checks
against the schema's function list, so a function cannot be added without a place in it. The TypeScript handlers are run by that script.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE
from papyrus_content.tenant_context import TenantContextRefusal

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = json.loads((ROOT / "features_backend/fixtures/function-tenant-context/handlers.json").read_text())
PYTHON_HANDLERS = [
    name for name in REGISTRY["moved"] if (ROOT / "amplify/functions" / name / "handler.py").exists()
]
IAM = {"accountId": "000000000000", "userArn": "arn:aws:iam::000000000000:role/operator"}


def user(**claims):
    return {"sub": "user-1", "issuer": "https://cognito", "username": "user-1", "claims": {"sub": "user-1", **claims}}


def load(name: str):
    specification = importlib.util.spec_from_file_location(f"{name.replace('-', '_')}_tenant_context", ROOT / "amplify/functions" / name / "handler.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def event(identity, field="saveItemDraft", **arguments):
    return {"fieldName": field, "arguments": {"input": json.dumps(arguments)}, "identity": identity}


@pytest.fixture
def untouched_backend():
    """Any read or write through either client fails the test: a refusal happens before the first one."""
    def fail(*args, **kwargs):
        raise AssertionError("the handler reached the backend before it had a tenant")

    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=fail), \
            mock.patch("papyrus_content.graphql_http.execute_graphql", side_effect=fail):
        yield


def run(name, identity, environment, monkeypatch, **arguments):
    for key in (TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    module = load(name)
    if hasattr(module, "create_authoring_client"):
        monkeypatch.setattr(module, "create_authoring_client", mock.Mock(side_effect=AssertionError("the handler reached the backend before it had a tenant")))
    with pytest.raises(TenantContextRefusal) as refused:
        module.handler(event(identity, **arguments), None)
    return refused.value.reason


SHARED = {TENANCY_MODE_ENVIRONMENT_VARIABLE: "shared"}


@pytest.mark.parametrize("name", PYTHON_HANDLERS)
def test_a_shared_stack_refuses_an_iam_call_that_names_no_tenant(name, untouched_backend, monkeypatch):
    assert run(name, IAM, SHARED, monkeypatch) == "iam_without_tenant"


@pytest.mark.parametrize("name", PYTHON_HANDLERS)
def test_a_shared_stack_refuses_a_token_with_no_tenant_claim(name, untouched_backend, monkeypatch):
    assert run(name, user(), SHARED, monkeypatch) == "no_tenant_claim"


@pytest.mark.parametrize("name", PYTHON_HANDLERS)
def test_a_shared_stack_refuses_claims_that_name_two_tenants(name, untouched_backend, monkeypatch):
    identity = user(papyrus_tenant_admin="alpha", papyrus_tenant_member="beta")
    assert run(name, identity, SHARED, monkeypatch) == "multiple_tenants"


@pytest.mark.parametrize("name", PYTHON_HANDLERS)
def test_a_dedicated_stack_refuses_a_claim_for_another_tenant_than_its_own(name, untouched_backend, monkeypatch):
    assert run(name, user(papyrus_tenant_editor="beta"), {TENANT_ID_ENVIRONMENT_VARIABLE: "alpha"}, monkeypatch) == "foreign_tenant"


def test_a_signed_in_callers_tenant_is_never_taken_from_the_body(monkeypatch):
    from papyrus_content.tenant_context import build_event_tenant_context

    monkeypatch.delenv(TENANT_ID_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, "shared")
    # The body names beta; the claims name alpha: the call acts for alpha.
    assert build_event_tenant_context(event(user(papyrus_tenant_editor="alpha"), tenantId="beta")).tenant_id == "alpha"


def test_an_iam_caller_names_its_tenant_in_the_input_and_is_the_operator(monkeypatch):
    from papyrus_content.tenant_context import build_event_tenant_context

    monkeypatch.delenv(TENANT_ID_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, "shared")
    context = build_event_tenant_context(event(IAM, tenantId="alpha"))
    assert (context.tenant_id, context.operator, context.mode) == ("alpha", True, "shared")
