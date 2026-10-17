from __future__ import annotations

import contextlib
import io

from behave import given, then, when

from papyrus_content.edge_invalidation import invalidate_revalidated_paths


class FakeCloudFront:
    def __init__(self) -> None:
        self.invalidations: list[dict] = []
        self.rejecting: set[str] = set()

    def create_invalidation(self, **arguments) -> None:
        if arguments["DistributionId"] in self.rejecting:
            raise RuntimeError("AccessDenied")
        self.invalidations.append(arguments)

    def paths_for(self, distribution_id: str) -> list[str]:
        return [
            path
            for call in self.invalidations
            if call["DistributionId"] == distribution_id
            for path in call["InvalidationBatch"]["Paths"]["Items"]
        ]


@given('a Pretext reader that revalidated "{first}" and "{second}"')
def reader_revalidated_two(context, first: str, second: str) -> None:
    context.revalidated = {"ok": True, "revalidatedPaths": [first, second]}
    context.cloudfront = FakeCloudFront()


@given('a Pretext reader that revalidated "{path}"')
def reader_revalidated_one(context, path: str) -> None:
    context.revalidated = {"ok": True, "revalidatedPaths": [path]}
    context.cloudfront = FakeCloudFront()


@given("a Pretext reader that revalidated nothing")
def reader_revalidated_nothing(context) -> None:
    context.revalidated = {"ok": True, "revalidatedPaths": []}
    context.cloudfront = FakeCloudFront()


@given('the site names the distributions "{first}" and "{second}"')
def site_names_two(context, first: str, second: str) -> None:
    context.distribution_ids = [first, second]


@given('the site names the distributions "{only}"')
def site_names_one(context, only: str) -> None:
    context.distribution_ids = [only]


@given('distribution "{distribution_id}" rejects invalidations')
def distribution_rejects(context, distribution_id: str) -> None:
    context.cloudfront.rejecting.add(distribution_id)


@when("the publish purges the edge")
def publish_purges(context) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        context.purge = invalidate_revalidated_paths(
            context.distribution_ids, context.revalidated, context.cloudfront, sleep=lambda _seconds: None
        )


@then('distribution "{distribution_id}" was invalidated for "{first}" and "{second}"')
def invalidated_for_two(context, distribution_id: str, first: str, second: str) -> None:
    assert context.cloudfront.paths_for(distribution_id) == [first, second], context.cloudfront.invalidations


@then('distribution "{distribution_id}" was invalidated for "{path}"')
def invalidated_for_one(context, distribution_id: str, path: str) -> None:
    assert context.cloudfront.paths_for(distribution_id) == [path], context.cloudfront.invalidations


@then("no invalidation was requested")
def nothing_requested(context) -> None:
    assert context.cloudfront.invalidations == [], context.cloudfront.invalidations


@then("the purge succeeded")
def purge_succeeded(context) -> None:
    assert context.purge["ok"] is True, context.purge


@then('the purge reported a failure for "{distribution_id}"')
def purge_failed_for(context, distribution_id: str) -> None:
    assert context.purge["ok"] is False and context.purge["distributions"][distribution_id]["ok"] is False, context.purge
