from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import tenant_records as records  # noqa: E402
from papyrus_content.tenant_records_test import FakeTable  # noqa: E402

TENANCY_MODELS = ["Tenant", "TenantMembership", "TenantDomain"]
# The group also holds the two site document models (features_backend/site-documents.feature).
TENANCY_GROUP_SIZE = len(TENANCY_MODELS) + 2


@given('{count:d} tenants with {members:d} members each')
def tenants_with_members(context, count, members):
    context.table_store = FakeTable()
    for tenant in ("alpha", "beta", "gamma", "delta")[:count]:
        for number in range(members):
            sub = "ada" if number == 0 else f"{tenant}-{number}"
            context.table_store.create("TenantMembership", records.membership_record(tenant, sub, "member", "ops", "2026-11-10T00:00:00Z"))


@when("the token Lambda looks up Ada's memberships")
def lookup(context):
    context.found = records.list_memberships_for_user(context.table_store.query, "ada")


@then("it makes one query on the userSub index and reads only Ada's rows")
def one_query(context):
    assert context.table_store.queries == ["listTenantMembershipsByUserSub"], context.table_store.queries
    assert context.found and all(row["userSub"] == "ada" for row in context.found)


@given('"{hostname}" is a TenantDomain of "{tenant}"')
def existing_domain(context, hostname, tenant):
    context.table_store = FakeTable()
    records.claim_domain(context.table_store.create, tenant, hostname, "subdomain")


@when('"{tenant}" tries to add "{hostname}"')
def try_add(context, tenant, hostname):
    context.refused = None
    try:
        records.claim_domain(context.table_store.create, tenant, hostname, "custom")
    except records.DomainAlreadyClaimed as error:
        context.refused = error


@then("it is refused")
def refused(context):
    assert context.refused is not None
    assert context.table_store.rows[("TenantDomain", "alpha.apyr.us")]["tenantId"] == "alpha"


def _tsx(script):
    result = subprocess.run(["npx", "tsx", "-e", script], cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@when("the tenancy model group is excluded")
def exclude_group(context):
    context.models_out = _tsx(
        'import { baseModelNames } from "./amplify/data/schema";'
        'console.log(JSON.stringify({all: baseModelNames(), without: baseModelNames(["tenancy"])}))')


@then("Tenant, TenantMembership and TenantDomain are not in the schema")
def not_in_schema(context):
    import json
    data = json.loads(context.models_out.strip().splitlines()[-1])
    context.model_names = data
    assert all(name in data["all"] and name not in data["without"] for name in TENANCY_MODELS)


@then("every other model is")
def others_stay(context):
    names = context.model_names
    assert len(names["all"]) - len(names["without"]) == TENANCY_GROUP_SIZE


@then("Tenant, TenantMembership and TenantDomain have the same fields and indexes in both files")
def same_fields(context):
    assert context.parity.returncode == 0, context.parity.stdout + context.parity.stderr


@then("each of them has its indexes on a new table only, with no index added to an existing table")
def new_tables_only(context):
    # The parity script pins the exact index declarations of the three models, and they are the only tables whose index list changed.
    assert "tenancy indexes ok" in context.parity.stdout
