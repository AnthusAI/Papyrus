from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import boto3
from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import project_commands  # noqa: E402
from papyrus_content.knowledge_snapshot import commands as snapshot_commands  # noqa: E402
from papyrus_content.knowledge_snapshot.model import KnowledgeData  # noqa: E402
from papyrus_content.projection import lease as lease_module  # noqa: E402
from papyrus_content.projection.deploy_render import deploy_render  # noqa: E402
from papyrus_content.projection.engine import DeletionGuard, ProjectionContext, project_all, reconcile  # noqa: E402
from papyrus_content.projection.lease import ProjectionLease, ProjectionLeaseHeld, lease_from_environment  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from procedures.newsroom.tests.incremental_site import seeded_site  # noqa: E402
from procedures.newsroom.tests.projection_fixtures import tree_digests  # noqa: E402
from procedures.newsroom.tests.test_projection_deletion_guard import DroppingProjector  # noqa: E402

TABLE = "papyrus-projection-locks"
BUCKET = "site-bucket"
OTHER = "other-owner"
ENVIRONMENT = {"AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}


class FakeTime:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.sleeps: list[float] = []
        self.on_sleep = None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


class ObservingSource(PublishedContentSource):
    """Records whether the lease exists in the table each time the projection reads the published items."""

    def __init__(self, client, table, seen: list) -> None:
        super().__init__(client)
        self._table, self._seen = table, seen

    def all_published_items(self):
        self._seen.append((self._table.get_item(Key={"publication": BUCKET}).get("Item") or {}).get("owner"))
        return super().all_published_items()


class FailingProjector:
    def __init__(self, inner) -> None:
        self._inner = inner

    def item_pages(self, item, site):
        raise RuntimeError("renderer broke")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def lease_for(context, key=BUCKET, owner="projection-owner", **options) -> ProjectionLease:
    return ProjectionLease(
        context.locks, key, table_name=TABLE, owner=owner, clock=context.time.clock, sleep=context.time.sleep,
        jitter=lambda: 1.0, **options,
    )


def projection_context(context, *, lease=None, projector=None, guard=None, source=None) -> ProjectionContext:
    site = context.site
    return ProjectionContext(
        source=source or PublishedContentSource(site.client),
        projector=projector or site.projector,
        writer=site.store,
        redirect_store=site.redirects,
        deletion_guard=guard,
        lease=lease if lease is not None else lease_for(context),
    )


def stored_pages(context) -> dict[str, str]:
    return tree_digests(Path(context.work.name) / "incremental")


def attempt(context, action) -> None:
    context.before = stored_pages(context)
    context.failure = None
    context.result = None
    try:
        context.result = action()
    except Exception as failure:  # noqa: BLE001 - the scenarios assert on the failure
        context.failure = failure


def lease_item(context, key=BUCKET):
    return context.locks.get_item(Key={"publication": key}).get("Item")


@given("a lock table and a site of three published articles that has been projected")
def lock_table_and_site(context) -> None:
    patcher = mock.patch.dict("os.environ", ENVIRONMENT)
    patcher.start()
    context.add_cleanup(patcher.stop)
    lease_module._table_name_cache.clear()
    moto = mock_aws()
    moto.start()
    context.add_cleanup(moto.stop)
    resource = boto3.resource("dynamodb")
    context.locks = resource.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    context.time = FakeTime()
    context.work = tempfile.TemporaryDirectory()
    context.add_cleanup(context.work.cleanup)
    context.site = seeded_site("generic", Path(context.work.name))
    context.failure = None
    context.seen = []
    context.other = None


@given("the projector fails while rendering")
def projector_fails(context) -> None:
    context.failing_projector = FailingProjector(context.site.projector)


@given("another owner holds the lease")
def other_holds(context) -> None:
    context.other = lease_for(context, owner=OTHER, purpose="cloud-run projection")
    context.other.acquire()


@given("another owner holds a lease that expired")
def other_expired(context) -> None:
    other_holds(context)
    context.time.now += 3600


@given("another owner holds the lease of a different publication")
def other_publication(context) -> None:
    context.other = lease_for(context, key="other-bucket", owner=OTHER)
    context.other.acquire()


@when("the site is projected under the lease")
def project_everything(context) -> None:
    projector = getattr(context, "failing_projector", None)
    attempt(context, lambda: project_all(projection_context(context, projector=projector)))


@when("the site is projected under the lease with a wait limit of {seconds:d} seconds")
def project_with_limit(context, seconds: int) -> None:
    lease = lease_for(context, wait_seconds=seconds)
    attempt(context, lambda: project_all(projection_context(context, lease=lease)))


@when("the site is projected under the lease and the lease is observed while it runs")
def project_observed(context) -> None:
    source = ObservingSource(context.site.client, context.locks, context.seen)
    attempt(context, lambda: project_all(projection_context(context, source=source)))


@when("the site is projected under the lease and the other owner releases the lease after {count:d} retries")
def project_after_release(context, count: int) -> None:
    context.time.on_sleep = lambda retries: context.other.release() if retries == count else None
    project_everything(context)


@when('the site configuration stops placing the article "{slug}" and the site is projected under the lease with the deletion guard on')
def project_dropped(context, slug: str) -> None:
    projector = DroppingProjector(context.site.projector, {"item-" + slug.rsplit("-", 1)[1]})
    attempt(context, lambda: project_all(projection_context(context, projector=projector, guard=DeletionGuard())))


@when("two projections of the same publication start together")
def two_projections(context) -> None:
    intervals: list[tuple[float, float]] = []
    failures: list[Exception] = []

    def run(name: str) -> None:
        class SlowSource(PublishedContentSource):
            def all_published_items(self):
                time.sleep(0.15)  # long enough that an unlocked second projection would overlap
                return super().all_published_items()

        lease = ProjectionLease(
            context.locks, BUCKET, table_name=TABLE, owner=name, wait_seconds=30,
            sleep=lambda seconds: time.sleep(0.02), jitter=lambda: 0.0,
        )
        projection = projection_context(context, lease=lease, source=SlowSource(context.site.client))
        try:
            started = time.monotonic()
            with projection.leased():
                started = time.monotonic()
                project_all(projection)
                intervals.append((started, time.monotonic()))
        except Exception as failure:  # noqa: BLE001
            failures.append(failure)

    threads = [threading.Thread(target=run, args=(name,)) for name in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    context.intervals, context.failures = sorted(intervals), failures


@when("the site is reconciled as a dry run")
def dry_run(context) -> None:
    lease = lease_for(context, wait_seconds=0)
    attempt(context, lambda: reconcile(projection_context(context, lease=lease), dry_run=True))


@when("a projection context is built where no lock table is configured")
def no_table(context) -> None:
    environment = {"PAPYRUS_PUBLICATION_KIND": "s3-projection", "PAPYRUS_SITE_BUCKET": BUCKET}
    context.built_lease = lease_from_environment(environment, BUCKET)


@when("a context is built for projecting to a local directory while a lock table is configured")
def local_directory_context(context) -> None:
    out = Path(context.work.name) / "local-out"
    with mock.patch.dict("os.environ", {"PAPYRUS_PROJECTION_LOCK_TABLE": TABLE, "PAPYRUS_SITE_BUCKET": BUCKET}):
        context.built = project_commands._build_context(context.site.client, {"out": str(out)})
    context.built_lease = context.built.lease


@when("the deploy render runs and the lease is observed while it runs")
def deploy_observed(context) -> None:
    source = ObservingSource(context.site.client, context.locks, context.seen)
    attempt(context, lambda: deploy_render(projection_context(context, source=source)))


@when("a knowledge snapshot with re-projection runs and the lease is observed while it runs")
def snapshot_observed(context) -> None:
    source = ObservingSource(context.site.client, context.locks, context.seen)
    projection = projection_context(context, source=source)
    empty = KnowledgeData(items=(), nodes=(), links=(), relations=(), clusters=(), beats=())
    with mock.patch.object(snapshot_commands, "authoring_client", return_value=context.site.client), \
            mock.patch.object(snapshot_commands, "_context_for", return_value=projection), \
            mock.patch.object(snapshot_commands, "load_knowledge_data", return_value=empty):
        attempt(context, lambda: snapshot_commands.knowledge_snapshot(["--site-bucket", BUCKET, "--reproject", "--json"]))


@then("the lease for the site bucket was held by the projection while it ran")
def held_while_running(context) -> None:
    assert context.failure is None, repr(context.failure)
    assert context.seen and set(context.seen) == {"projection-owner"}, context.seen


@then("the lease no longer exists")
def lease_gone(context) -> None:
    assert lease_item(context) is None, lease_item(context)


@then('the leased projection failed with "{text}"')
def failed_with(context, text: str) -> None:
    assert context.failure is not None, "the projection did not fail"
    assert text in str(context.failure), str(context.failure)


@then("the failure tells the operator how to clear the lease")
def failure_remedy(context) -> None:
    assert isinstance(context.failure, ProjectionLeaseHeld), repr(context.failure)
    message = str(context.failure)
    assert f"aws dynamodb delete-item --table-name {TABLE}" in message and BUCKET in message, message
    assert "cloud-run projection" in message


@then("the site store is untouched by the leased projection")
def store_unchanged(context) -> None:
    assert stored_pages(context) == context.before


@then("the other owner still holds the lease")
def other_still_holds(context) -> None:
    assert lease_item(context)["owner"] == OTHER


@then("the other publication is still leased by the other owner")
def other_publication_held(context) -> None:
    assert lease_item(context, "other-bucket")["owner"] == OTHER


@then("the projection waited {first:d}, {second:d} and {third:d} seconds before it took the lease")
def waited(context, first: int, second: int, third: int) -> None:
    assert context.time.sleeps == [first, second, third], context.time.sleeps


@then("the leased projection finished")
def finished(context) -> None:
    assert context.failure is None, repr(context.failure)


@then("the leased projection finished without waiting")
def finished_without_waiting(context) -> None:
    finished(context)
    assert context.time.sleeps == []


@then("both projections finished")
def both_finished(context) -> None:
    assert not context.failures, context.failures
    assert len(context.intervals) == 2, context.intervals


@then("their runs did not overlap")
def no_overlap(context) -> None:
    (_, first_end), (second_start, _) = context.intervals
    assert second_start >= first_end, context.intervals


@then("the context has no lease")
def no_lease(context) -> None:
    assert context.built_lease is None


@then("the whole site can be projected with no lease")
def projectable(context) -> None:
    project_all(projection_context(context, lease=lease_for(context)))


@then("projecting the whole site with that context leaves the lock table empty")
def table_empty(context) -> None:
    project_all(context.built)
    assert context.locks.scan()["Items"] == []
