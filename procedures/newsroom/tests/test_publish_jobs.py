"""Builds of a publish as jobs (PPY-3acc8d): answered at once, joined by a retry of the same story, queued when the site is busy and built
by whoever holds the lease, and asked about later. The lock table is moto's DynamoDB; the projection itself is replaced by a recorder."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import boto3
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_client import FakeAuthoringClient  # noqa: E402

from papyrus_content.projection.lease import ProjectionLeaseHeld  # noqa: E402
from papyrus_content.projection.model import ProjectionReport  # noqa: E402
from papyrus_content.projection.publish_jobs import DONE, QUEUED, RUNNING, STALE_SECONDS, PublishJobs  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler_jobs", HANDLER_PATH)
handler = importlib.util.module_from_spec(specification)
specification.loader.exec_module(handler)

TABLE = "papyrus-projection-locks"
BUCKET = "site-bucket"
ENVIRONMENT = {
    "AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
    "PAPYRUS_PUBLICATION_KIND": "s3-projection", "PAPYRUS_SITE_BUCKET": BUCKET, "PAPYRUS_PROJECTION_LOCK_TABLE": TABLE,
}


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class LockTableCase(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = mock.patch.dict("os.environ", ENVIRONMENT)
        self.environment.start()
        self.moto = mock_aws()
        self.moto.start()
        self.table = boto3.resource("dynamodb").create_table(
            TableName=TABLE, KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST",
        )
        self.clock = Clock()
        self.ids = iter(f"job-{number}" for number in range(1, 100))
        self.jobs = PublishJobs(self.table, BUCKET, clock=self.clock, new_id=lambda: next(self.ids))

    def tearDown(self) -> None:
        self.moto.stop()
        self.environment.stop()


class PublishJobsTest(LockTableCase):
    def test_a_request_queues_a_job_and_a_second_request_joins_it(self) -> None:
        job, joined = self.jobs.request("story-1", 3)
        self.assertFalse(joined)
        self.assertEqual((job["jobId"], job["state"]), ("job-1", QUEUED))
        again, joined = self.jobs.request("story-1", 4)
        self.assertTrue(joined)   # still queued: that build reads the data when it starts, so it builds version 4
        self.assertEqual(again["jobId"], "job-1")
        self.assertEqual(self.jobs.queued_items(), {"story-1"})

    def test_a_running_build_is_joined_for_its_own_version_and_a_new_version_gets_a_new_job(self) -> None:
        self.jobs.request("story-1", 3)
        self.jobs.take("story-1")
        self.jobs.start("story-1", "job-1")
        same, joined = self.jobs.request("story-1", 3)
        self.assertTrue(joined)
        self.assertEqual(same["state"], RUNNING)
        newer, joined = self.jobs.request("story-1", 4)
        self.assertFalse(joined)
        self.assertEqual(newer["jobId"], "job-2")
        self.jobs.finish("story-1", "job-1", ok=True, outcome={"paths": ["a"]})   # the older build ends: the newer job is not overwritten
        self.assertEqual(self.jobs.status("story-1")["jobId"], "job-2")
        self.assertEqual(self.jobs.status("story-1")["state"], QUEUED)

    def test_a_job_nobody_touched_for_longer_than_a_function_may_run_is_not_joined(self) -> None:
        self.jobs.request("story-1", 3)
        self.clock.now += STALE_SECONDS + 1
        self.assertTrue(self.jobs.status("story-1")["stale"])
        fresh, joined = self.jobs.request("story-1", 3)
        self.assertFalse(joined)
        self.assertEqual(fresh["jobId"], "job-2")

    def test_a_finished_job_reports_its_outcome(self) -> None:
        self.jobs.request("story-1", 3, announce={"publishedItemId": "published-story-1"})
        self.jobs.start("story-1", "job-1")
        self.jobs.finish("story-1", "job-1", ok=True, outcome={"paths": ["posts/story-1/index.html"], "url": "https://example.org/posts/story-1/"})
        status = self.jobs.status("story-1")
        self.assertEqual(status["state"], DONE)
        self.assertEqual(status["outcome"]["url"], "https://example.org/posts/story-1/")
        self.assertEqual(self.jobs.announcement("story-1"), {"publishedItemId": "published-story-1"})


def published_story(client, item_id: str = "story-1", *, publish: bool = True) -> None:
    fields = ItemFields(type="page", slug=item_id, section=None, front_matter_yaml="title: A story\n", body_markus="Some text.\n", aliases=[], id=item_id)
    save_item(client, fields, actor="editor", now="2026-11-08T00:00:00Z")
    if publish:
        publish_item(client, item_id, actor="editor", now="2026-11-08T00:00:00Z")


class FakeLease:
    """The projection lease, held by nobody or by someone else."""

    def __init__(self, held_by_other: bool = False) -> None:
        self.held_by_other = held_by_other
        self.wait_seconds = 120.0
        self.depth = 0

    @contextmanager
    def held(self):
        if self.held_by_other:
            raise ProjectionLeaseHeld(BUCKET, TABLE, {"owner": "deploy", "purpose": "deploy render", "expiresAt": 1}, self.wait_seconds)
        self.depth += 1
        try:
            yield self
        finally:
            self.depth -= 1


def fake_context(client, lease: FakeLease):
    from papyrus_content.projection.source import PublishedContentSource

    context = SimpleNamespace(source=PublishedContentSource(client), projector=SimpleNamespace(item_page_paths=lambda summary: [f"{summary.slug}/index.html"]), lease=lease, invalidate=None)

    @contextmanager
    def leased():
        with lease.held():
            yield

    context.leased = leased
    return context


class AsynchronousPublishTest(LockTableCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = FakeAuthoringClient()
        published_story(self.client)
        self.lease = FakeLease()
        self.scheduled: list[dict] = []
        self.projected: list[str] = []
        self.patches = [
            mock.patch.object(handler, "create_authoring_client", return_value=(self.client, {})),
            mock.patch.object(handler, "render_preflight"),
            mock.patch.object(handler, "projection_context", side_effect=lambda client: fake_context(client, self.lease)),
            mock.patch.object(handler, "schedule_projection_task", side_effect=lambda task, reason: self.scheduled.append(task) or True),
            mock.patch.object(handler, "project", side_effect=self.project),
            mock.patch.object(handler, "announce_published"),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        super().tearDown()

    def project(self, context, item_id, unpublished=False):
        self.projected.append(item_id)
        report = ProjectionReport()
        report.written = [f"{item_id}/index.html"]
        report.item_paths = [f"{item_id}/index.html"]
        return report

    def publish(self, item_id: str = "story-1") -> dict:
        return handler.handler({"fieldName": "publishItem", "arguments": {"input": json.dumps({"id": item_id, "async": True})}, "identity": {"username": "editor", "claims": {}}})

    def unpublish(self, item_id: str = "story-1", **arguments) -> dict:
        return handler.handler({"fieldName": "unpublishItem", "arguments": {"input": json.dumps({"id": item_id, **arguments})}, "identity": {"username": "editor", "claims": {}}})

    def status(self, item_id: str = "story-1") -> dict:
        return handler.handler({"fieldName": "publishItem", "arguments": {"input": json.dumps({"id": item_id, "jobStatus": True})}, "identity": {"username": "editor", "claims": {}}})

    def test_the_publish_answers_with_a_job_and_builds_nothing_itself(self) -> None:
        answer = self.publish()
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["scheduled"])
        self.assertEqual(answer["projection"]["state"], QUEUED)
        self.assertFalse(answer["projection"]["joined"])
        self.assertEqual(answer["itemPaths"], ["story-1/index.html"])
        self.assertEqual(self.projected, [])
        self.assertEqual([task["task"] for task in self.scheduled], ["item"])
        self.assertEqual(self.scheduled[0]["jobId"], answer["projection"]["jobId"])

    def test_an_async_unpublish_answers_with_a_job_and_the_job_takes_the_page_down(self) -> None:
        answer = self.unpublish(**{"async": True})
        self.assertTrue(answer["ok"] and answer["changed"])
        self.assertEqual(answer["projection"]["state"], QUEUED)
        self.assertEqual(self.projected, [])   # AppSync's 30 seconds never wait for the page work (PPY-f171b4)
        self.assertEqual([(task["task"], task["unpublished"]) for task in self.scheduled], [("item", True)])
        self.assertEqual(self.client.get_record("PublishedItem", "published-story-1"), None)
        self.assertEqual(self.status()["projection"]["state"], QUEUED)
        self.assertTrue(handler.handler({"projectionTask": self.scheduled[0]}, None)["ok"])
        status = self.status()["projection"]
        self.assertEqual((status["state"], status["jobId"]), (DONE, answer["projection"]["jobId"]))
        self.assertEqual(status["paths"], ["story-1/index.html"])

    def test_an_unpublish_without_async_still_builds_while_the_call_waits(self) -> None:
        answer = self.unpublish()
        self.assertTrue(answer["projected"])
        self.assertEqual(self.projected, ["story-1"])
        self.assertEqual(self.scheduled, [])

    def test_publishing_the_same_story_again_joins_the_build_instead_of_starting_another(self) -> None:
        first = self.publish()
        second = self.publish()
        self.assertTrue(second["projection"]["joined"])
        self.assertEqual(second["projection"]["jobId"], first["projection"]["jobId"])
        self.assertEqual(len(self.scheduled), 1)

    def test_the_status_follows_the_build_to_its_end(self) -> None:
        published_story(self.client, "story-3", publish=False)   # a first publish: the newsletter hears of it once the page is live
        answer = self.publish("story-3")
        self.assertEqual(self.status("story-3")["projection"]["state"], QUEUED)
        result = handler.handler({"projectionTask": self.scheduled[0]}, None)
        self.assertTrue(result["ok"])
        status = self.status("story-3")["projection"]
        self.assertEqual(status["state"], DONE)
        self.assertEqual(status["jobId"], answer["projection"]["jobId"])
        self.assertEqual(status["itemPaths"], ["story-3/index.html"])
        handler.announce_published.assert_called_once()

    def test_a_build_that_finds_the_site_busy_leaves_the_story_queued_and_fails_for_a_retry(self) -> None:
        self.publish()
        self.lease.held_by_other = True
        with self.assertRaises(handler.ProjectionTaskFailed):
            handler.handler({"projectionTask": self.scheduled[0]}, None)
        self.assertEqual(self.lease.wait_seconds, handler.QUEUED_LEASE_WAIT_SECONDS)   # a few seconds, not two minutes
        self.assertEqual(self.projected, [])
        self.assertEqual(self.jobs_status()["state"], QUEUED)

    def test_the_lease_holder_builds_what_was_queued_and_the_queued_build_retry_then_does_nothing(self) -> None:
        published_story(self.client, "story-2")
        self.publish("story-1")
        self.publish("story-2")
        story_1_task, story_2_task = self.scheduled[0], self.scheduled[1]
        self.lease.held_by_other = True
        with self.assertRaises(handler.ProjectionTaskFailed):
            handler.handler({"projectionTask": story_2_task}, None)   # busy: story-2 stays queued
        self.lease.held_by_other = False
        handler.handler({"projectionTask": story_1_task}, None)       # builds story-1, then story-2 from the queue, before letting go
        self.assertEqual(self.projected, ["story-1", "story-2"])
        self.assertEqual(self.jobs_status("story-2")["state"], DONE)
        retried = handler.handler({"projectionTask": story_2_task}, None)   # Lambda's retry of the busy build
        self.assertTrue(retried["alreadyBuilt"])
        self.assertEqual(self.projected, ["story-1", "story-2"])

    def test_one_queued_item_pages_run_covers_every_publish_before_it(self) -> None:
        handler.schedule_item_pages("story-1")
        handler.schedule_item_pages("story-2")
        self.assertEqual([task["task"] for task in self.scheduled], ["item-pages"])

    def test_every_invocation_is_one_metered_run_named_after_what_it_does(self) -> None:
        self.assertEqual(handler.metered_caller({"fieldName": "publishItem"}), ("lambda:content-actions:publishItem", False))
        self.assertEqual(handler.metered_caller({"projectionTask": {"task": "item"}}), ("lambda:content-actions:item", False))
        self.assertEqual(handler.metered_caller({"projectionTask": {"task": "deploy-render"}}), ("lambda:content-actions:deploy-render", True))

    def jobs_status(self, item_id: str = "story-1") -> dict:
        return PublishJobs(self.table, BUCKET).status(item_id)


if __name__ == "__main__":
    unittest.main()


class ScriptedClient:
    """Answers ``publishItem`` from a script: the first answer is the publish, the rest are the status questions."""

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.inputs: list[dict] = []

    def graphql(self, query: str, variables: dict) -> dict:
        self.inputs.append(json.loads(variables["input"]))
        answer = json.dumps(self.answers.pop(0) if len(self.answers) > 1 else self.answers[0])
        return {"publishItem": answer, "unpublishItem": answer}


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class CliWaitsForTheJobTest(unittest.TestCase):
    """The signed-in CLI asks for a background build and then asks about it, in short calls, so AppSync's 30 seconds never cut it off."""

    def trigger(self, answers: list[dict], timeout: str = "60", *, unpublished: bool = False):
        from papyrus_content.projection_trigger import item_task, trigger_projection_as_user

        client, clock = ScriptedClient(answers), FakeTime()
        with mock.patch.dict("os.environ", {"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": timeout}):
            outcome = trigger_projection_as_user(client, item_task("story-1", unpublished=unpublished), sleep=clock.sleep, clock=clock.clock)
        return outcome, client

    def test_a_build_that_ends_is_reported_as_projected_with_its_pages(self) -> None:
        outcome, client = self.trigger([
            {"ok": True, "scheduled": True, "itemPaths": ["story-1/index.html"], "url": "https://example.org/story-1/", "projection": {"jobId": "job-1", "state": "queued", "joined": False}},
            {"ok": True, "projection": {"jobId": "job-1", "state": "running"}},
            {"ok": True, "projection": {"jobId": "job-1", "state": "done", "paths": ["story-1/index.html", "index.html"], "itemPaths": ["story-1/index.html"], "invalidation": {"status": "ok", "paths": ["/story-1/"]}}},
        ])
        self.assertEqual(client.inputs[0], {"id": "story-1", "async": True})
        self.assertEqual(client.inputs[1], {"id": "story-1", "jobStatus": True})
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["status"], "projected")
        self.assertEqual(outcome["paths"], ["story-1/index.html", "index.html"])
        self.assertEqual(outcome["url"], "https://example.org/story-1/")

    def test_an_unpublish_is_asked_for_in_the_background_and_followed_by_its_job(self) -> None:
        outcome, client = self.trigger([
            {"ok": True, "changed": True, "scheduled": True, "itemPaths": [], "projection": {"jobId": "job-1", "state": "queued", "joined": False}},
            {"ok": True, "projection": {"jobId": "job-1", "state": "running"}},
            {"ok": True, "projection": {"jobId": "job-1", "state": "done", "paths": ["story-1/index.html", "_papyrus/retired.json"]}},
        ], unpublished=True)
        self.assertEqual(client.inputs[0], {"id": "story-1", "async": True})
        self.assertEqual(client.inputs[1], {"id": "story-1", "jobStatus": True})
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["paths"], ["story-1/index.html", "_papyrus/retired.json"])

    def test_an_unpublish_still_going_when_the_wait_ends_is_still_running_not_failed(self) -> None:
        outcome, _client = self.trigger([{"ok": True, "projection": {"jobId": "job-1", "state": "running"}}], timeout="10", unpublished=True)
        self.assertIsNone(outcome["ok"])
        self.assertEqual(outcome["status"], "still-running")
        self.assertIn("papyrus ops content unpublish --id story-1", outcome["retry"])

    def test_a_build_still_going_when_the_wait_ends_is_still_running_not_failed(self) -> None:
        from papyrus_content.publish_stages import projected_stage

        outcome, _client = self.trigger([
            {"ok": True, "scheduled": True, "itemPaths": ["story-1/index.html"], "projection": {"jobId": "job-1", "state": "queued", "joined": True}},
            {"ok": True, "projection": {"jobId": "job-1", "state": "queued"}},
        ], timeout="10")
        self.assertIsNone(outcome["ok"])
        self.assertEqual(outcome["status"], "still-running")
        self.assertTrue(outcome["joined"])
        self.assertIn("job-1", outcome["error"])
        self.assertEqual(projected_stage(outcome)["status"], "still-running")

    def test_a_failed_build_is_failed_with_its_reason(self) -> None:
        outcome, _client = self.trigger([
            {"ok": True, "projection": {"jobId": "job-1", "state": "queued"}},
            {"ok": True, "projection": {"jobId": "job-1", "state": "failed", "error": "the page cannot be rendered"}},
        ])
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["error"], "the page cannot be rendered")

    def test_a_backend_that_predates_background_builds_is_refused_with_what_to_deploy(self) -> None:
        for unpublished in (False, True):
            outcome, client = self.trigger([{"ok": True, "projected": True, "paths": ["story-1/index.html"], "itemPaths": ["story-1/index.html"]}], unpublished=unpublished)
            self.assertEqual(len(client.inputs), 1)   # no waiting inside the call, no second try
            self.assertFalse(outcome["ok"])
            self.assertEqual(outcome["status"], "failed")
            self.assertIn("Deploy a backend that includes PPY-f171b4", outcome["error"])
