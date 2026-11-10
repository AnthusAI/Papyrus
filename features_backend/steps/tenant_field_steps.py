from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import graphql_authoring  # noqa: E402
from papyrus_content.tenancy import TENANT_FIELD_MODELS  # noqa: E402
from papyrus_content.tenant_field_test import IntrospectableBackend  # noqa: E402
from procedures.newsroom.tests.test_tenancy import tenant_client  # noqa: E402

MODELS = ("Message", "Assignment", "Reference")


def make_client(context, tenant, with_field=True):
    import os

    if with_field:
        os.environ[graphql_authoring.TENANT_FIELD_ENVIRONMENT_VARIABLE] = "1"
    else:
        os.environ.pop(graphql_authoring.TENANT_FIELD_ENVIRONMENT_VARIABLE, None)
    context.field_backend = IntrospectableBackend(with_tenant_field=with_field)
    context.field_client = tenant_client(context.field_backend, tenant)


@given('a client for tenant "{tenant}"')
def client_for_tenant(context, tenant):
    make_client(context, tenant)


@given('a client for tenant "{tenant}" on a site whose deploy has not set the tenantId flag')
def client_without_field(context, tenant):
    make_client(context, tenant, with_field=False)


@given("a dedicated backend with no tenant configured")
def dedicated_backend(context):
    make_client(context, None)


@when("it creates a Message, an Assignment and a Reference")
def create_three(context):
    for model in MODELS:
        context.field_client.create_record(model, {"id": f"{model}-1"})


@when("an editor creates a Message")
def editor_creates_message(context):
    context.field_client.create_record("Message", {"id": "Message-1"})


@then('each row has tenantId "{tenant}"')
def rows_have_tenant(context, tenant):
    for model in MODELS:
        assert context.field_backend.tables[model][f"{model}-1"]["tenantId"] == tenant


@then("the row has no tenantId and the call succeeds")
def row_has_no_tenant(context):
    assert "tenantId" not in context.field_backend.tables["Message"]["Message-1"]


@then("no row has a tenantId and every call succeeds")
def no_row_has_tenant(context):
    for model in MODELS:
        assert "tenantId" not in context.field_backend.tables[model][f"{model}-1"]


@when("the schema parity check runs")
def run_parity(context):
    context.parity = subprocess.run(["npx", "tsx", "scripts/test-schema-parity.ts"], cwd=REPO_ROOT, capture_output=True, text=True)


@then("each of the 52 tenant-owned models has tenantId in the deployed and the typed schema")
def parity_passes(context):
    assert context.parity.returncode == 0, context.parity.stderr


@then("the global identity models UserProfile, UserIdentity and PublicHandleClaim do not")
def global_models_untouched(context):
    assert "tenantId: a.string()" not in context.parity.stderr
    assert not TENANT_FIELD_MODELS & {"UserProfile", "UserIdentity", "PublicHandleClaim"}
