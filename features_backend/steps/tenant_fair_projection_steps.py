from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import boto3
from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection import lease as lease_module  # noqa: E402
from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE  # noqa: E402
from papyrus_content.projection.lease import ProjectionLease, ProjectionTenantRequired, lease_from_environment, lease_key  # noqa: E402

TABLE = "papyrus-projection-locks"
BUCKET = "fair-site-bucket"
AWS = {"AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def start(context, mode: str) -> None:
    patcher = mock.patch.dict("os.environ", {**AWS, TENANCY_MODE_ENVIRONMENT_VARIABLE: mode, "PAPYRUS_PROJECTION_LOCK_TABLE": TABLE})
    patcher.start()
    context.add_cleanup(patcher.stop)
    lease_module._table_name_cache.clear()
    aws = mock_aws()
    aws.start()
    context.add_cleanup(aws.stop)
    resource = boto3.resource("dynamodb")
    resource.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    context.locks = resource.Table(TABLE)
    context.clock = Clock()
    context.built = {}


def lease_for_tenant(context, tenant: str, owner: str, **options) -> ProjectionLease:
    return ProjectionLease(
        context.locks, lease_key(BUCKET, tenant), table_name=TABLE, owner=owner,
        clock=context.clock, sleep=context.clock.sleep, jitter=lambda: 1.0, **options,
    )


@given("a shared stack with a lock table")
def shared_stack(context) -> None:
    start(context, "shared")


@given("a dedicated stack with a lock table")
def dedicated_stack(context) -> None:
    start(context, "dedicated")


@given("alpha holds its projection lease on the bucket")
def alpha_holds(context) -> None:
    context.alpha = lease_for_tenant(context, "alpha", "alpha-owner")
    context.alpha.acquire()


@when("beta starts a projection in the same bucket")
def beta_starts(context) -> None:
    context.beta = lease_for_tenant(context, "beta", "beta-owner", wait_seconds=0)
    context.beta.acquire()


@then("beta does not wait")
def beta_does_not_wait(context) -> None:
    assert context.beta.depth == 1 and context.clock.sleeps == []


@then("the lock table holds one lease for alpha and one for beta")
def one_each(context) -> None:
    assert {item["publication"] for item in context.locks.scan()["Items"]} == {f"{BUCKET}#alpha", f"{BUCKET}#beta"}


@when('a projection lease is built for a site that has the tenant id "{tenant}"')
def built_with_tenant(context, tenant: str) -> None:
    context.built["with"] = lease_from_environment({"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE}, BUCKET, tenant_id=tenant)


@when("a projection lease is built for a site that has no tenant id")
def built_without_tenant(context) -> None:
    context.built["without"] = lease_from_environment({"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE}, BUCKET)


@then("both leases are keyed by the bucket name alone")
def keyed_by_bucket(context) -> None:
    assert [lease.key for lease in context.built.values()] == [BUCKET, BUCKET]


@when("a projection lease is built with no tenant")
def built_with_no_tenant(context) -> None:
    context.refusal = None
    try:
        lease_from_environment({"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE}, BUCKET)
    except ProjectionTenantRequired as error:
        context.refusal = error


@then("the projection is refused because it needs a tenant")
def refused(context) -> None:
    assert context.refusal is not None and "needs a tenant" in str(context.refusal)


@then("the lock table holds no lease")
def no_lease(context) -> None:
    assert context.locks.scan()["Items"] == []
