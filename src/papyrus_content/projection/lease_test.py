import boto3
import pytest
from moto import mock_aws

from papyrus_content.projection import lease as lease_module
from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE
from papyrus_content.projection.lease import (
    ProjectionLease,
    ProjectionLeaseHeld,
    ProjectionLeaseLost,
    ProjectionTenantRequired,
    backoff_seconds,
    lease_key,
    lease_from_environment,
)

TABLE = "papyrus-projection-locks"
KEY = "site-bucket"
TENANCY_MODE = TENANCY_MODE_ENVIRONMENT_VARIABLE


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    lease_module._table_name_cache.clear()
    with mock_aws():
        resource = boto3.resource("dynamodb")
        resource.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield resource.Table(TABLE)


def make(table, clock, owner, **options):
    return ProjectionLease(table, KEY, table_name=TABLE, owner=owner, clock=clock, sleep=clock.sleep, jitter=lambda: 1.0, **options)


def stored(table):
    return table.get_item(Key={"publication": KEY}).get("Item")


def test_acquire_writes_the_item_and_release_removes_it(table):
    clock = Clock()
    lease = make(table, clock, "a", purpose="cloud-run projection")
    lease.acquire()
    item = stored(table)
    assert item["owner"] == "a" and item["purpose"] == "cloud-run projection"
    assert int(item["expiresAt"]) == int(clock.now + 1800)
    assert item["acquiredAt"].endswith("Z")
    lease.release()
    assert stored(table) is None


def test_release_never_deletes_someone_elses_lease(table):
    clock = Clock()
    first, second = make(table, clock, "a"), make(table, clock, "b")
    first.acquire()
    clock.now += 2000  # a's lease expires, b takes over
    second.acquire()
    first.release()
    assert stored(table)["owner"] == "b"


def test_nested_acquire_shares_one_hold(table):
    lease = make(table, Clock(), "a")
    lease.acquire()
    lease.acquire()
    lease.release()
    assert stored(table) is not None
    lease.release()
    assert stored(table) is None


def test_stale_lease_is_taken_over(table):
    clock = Clock()
    make(table, clock, "crashed").acquire()
    clock.now += 1801
    make(table, clock, "b").acquire()
    assert stored(table)["owner"] == "b"
    assert clock.sleeps == []


def test_held_lease_waits_with_backoff_then_proceeds_when_released(table):
    clock = Clock()
    holder = make(table, clock, "a")
    holder.acquire()
    waiter = make(table, clock, "b", wait_seconds=120)
    original_sleep = clock.sleep

    def sleep_and_release(seconds):
        original_sleep(seconds)
        if len(clock.sleeps) == 3:
            holder.release()

    waiter.sleep = sleep_and_release
    waiter.acquire()
    assert clock.sleeps == [1.0, 2.0, 4.0]
    assert stored(table)["owner"] == "b"


def test_held_beyond_the_wait_limit_raises_with_the_holder(table):
    clock = Clock()
    make(table, clock, "a", purpose="cloud-run projection").acquire()
    waiter = make(table, clock, "b", wait_seconds=10)
    with pytest.raises(ProjectionLeaseHeld) as raised:
        waiter.acquire()
    error = raised.value
    assert error.owner == "a" and error.purpose == "cloud-run projection"
    assert "aws dynamodb delete-item" in str(error) and TABLE in str(error) and KEY in str(error)
    assert sum(clock.sleeps) == 10  # never sleeps past the limit
    assert stored(table)["owner"] == "a"


def test_backoff_schedule_doubles_to_a_cap_and_jitters_downward():
    assert [backoff_seconds(n) for n in range(6)] == [1, 2, 4, 8, 15, 15]
    assert backoff_seconds(3, 0.0) == 4.0


def test_renew_extends_only_after_half_the_ttl_and_only_for_the_owner(table):
    clock = Clock()
    lease = make(table, clock, "a", ttl_seconds=100)
    lease.acquire()
    first_expiry = int(stored(table)["expiresAt"])
    clock.now += 10
    lease.renew()
    assert int(stored(table)["expiresAt"]) == first_expiry  # too soon: no write
    clock.now += 50
    lease.renew()
    assert int(stored(table)["expiresAt"]) == int(clock.now + 100)
    clock.now += 200  # expired; another owner takes over
    make(table, clock, "b", ttl_seconds=100).acquire()
    clock.now += 60
    with pytest.raises(ProjectionLeaseLost):
        lease.renew()
    assert stored(table)["owner"] == "b"


def test_held_context_releases_on_error(table):
    lease = make(table, Clock(), "a")
    with pytest.raises(RuntimeError):
        with lease.held():
            raise RuntimeError("boom")
    assert stored(table) is None


def test_no_table_configured_means_no_lease(table):
    class Missing:
        class exceptions:
            ParameterNotFound = Exception

        def get_parameter(self, Name):
            error = Exception("missing")
            error.response = {"Error": {"Code": "ParameterNotFound"}}
            raise error

    assert lease_from_environment({}, KEY, ssm_client=Missing()) is None


def test_environment_variable_names_the_table_and_sets_the_wait(table):
    lease = lease_from_environment(
        {"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE, "PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS": "1800"}, KEY
    )
    assert lease.table_name == TABLE and lease.wait_seconds == 1800 and lease.key == KEY


def test_ssm_parameter_names_the_table_and_access_denied_is_loud(table):
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/papyrus/projection-lock/table-name", Value=TABLE, Type="String")
    assert lease_from_environment({}, KEY).table_name == TABLE

    class Denied:
        def get_parameter(self, Name):
            error = Exception("denied")
            error.response = {"Error": {"Code": "AccessDeniedException"}}
            raise error

    lease_module._table_name_cache.clear()
    with pytest.raises(Exception, match="denied"):
        lease_from_environment({}, KEY, ssm_client=Denied())


def test_a_dedicated_stack_keeps_the_bucket_key_with_or_without_a_tenant(monkeypatch):
    monkeypatch.delenv(TENANCY_MODE, raising=False)
    assert lease_key(KEY) == KEY
    assert lease_key(KEY, "alpha") == KEY


def test_a_shared_stack_keys_the_lease_per_tenant(monkeypatch):
    monkeypatch.setenv(TENANCY_MODE, "shared")
    assert lease_key(KEY, "alpha") == f"{KEY}#alpha"
    assert lease_key(KEY, "beta") == f"{KEY}#beta"


def test_a_shared_stack_refuses_a_projection_without_a_tenant_before_taking_a_lease(monkeypatch, table):
    monkeypatch.setenv(TENANCY_MODE, "shared")
    with pytest.raises(ProjectionTenantRequired, match="needs a tenant"):
        lease_from_environment({"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE}, KEY)
    assert table.scan()["Items"] == []


def test_the_lease_from_the_environment_is_keyed_by_the_tenancy_mode(monkeypatch, table):
    environment = {"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE}
    monkeypatch.delenv(TENANCY_MODE, raising=False)
    assert lease_from_environment(environment, KEY, tenant_id="alpha").key == KEY
    assert lease_from_environment(environment, KEY).key == KEY
    monkeypatch.setenv(TENANCY_MODE, "shared")
    assert lease_from_environment(environment, KEY, tenant_id="alpha").key == f"{KEY}#alpha"


def test_two_tenants_on_one_bucket_hold_their_leases_at_once(monkeypatch, table):
    monkeypatch.setenv(TENANCY_MODE, "shared")
    clock = Clock()
    alpha = ProjectionLease(table, lease_key(KEY, "alpha"), table_name=TABLE, owner="alpha", clock=clock, sleep=clock.sleep, jitter=lambda: 1.0)
    beta = ProjectionLease(table, lease_key(KEY, "beta"), table_name=TABLE, owner="beta", clock=clock, sleep=clock.sleep, jitter=lambda: 1.0, wait_seconds=0)
    alpha.acquire()
    beta.acquire()
    assert clock.sleeps == []
    assert {item["publication"] for item in table.scan()["Items"]} == {f"{KEY}#alpha", f"{KEY}#beta"}
    same_tenant = ProjectionLease(table, lease_key(KEY, "alpha"), table_name=TABLE, owner="other", clock=clock, sleep=clock.sleep, jitter=lambda: 1.0, wait_seconds=0)
    with pytest.raises(ProjectionLeaseHeld):
        same_tenant.acquire()
