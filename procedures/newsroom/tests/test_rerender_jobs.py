"""A page re-render is a job (PPY-4611d5): ``rerender`` and the re-render after ``link-story`` start it, ask about it, and report how it really ended.

The server half runs the content-actions handler over moto's lock table with a fake page-refresh service; the client half runs the CLI over a fake
newsroom whose answers are scripted, or which is too slow for the client.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_publish_jobs import LockTableCase, handler  # noqa: E402

from papyrus_content import story_rerender  # noqa: E402
from papyrus_content.operator_errors import GraphQLTimeoutError  # noqa: E402
from papyrus_content.page_refresh import cli as refresh_cli  # noqa: E402
from papyrus_content.projection.publish_jobs import DONE, FAILED, QUEUED  # noqa: E402

LINEAGE = "item-big"
PLANNED = {"ok": True, "operation": "site_rerender_pages", "dryRun": True, "rendered": {"ok": True, "dryRun": True, "wouldWrite": ["big/index.html"], "count": 1, "errors": []},
           "invalidation": {"ok": True, "status": "not-requested", "paths": [], "count": 0, "cost": {}}}
WROTE = {"ok": True, "operation": "site_rerender_pages", "rendered": {"ok": True, "written": ["big/index.html"], "count": 1, "errors": []},
         "invalidation": {"ok": True, "status": "not-requested", "paths": [], "count": 0}}
BROKEN = {"ok": False, "operation": "site_rerender_pages", "rendered": {"ok": False, "written": [], "count": 0, "errors": ["the hook raised"]},
          "invalidation": {"ok": False, "status": "skipped", "paths": [], "count": 0}}


class FakeService:
    def __init__(self, outcome: dict) -> None:
        self.outcome, self.calls = outcome, []

    def rerender(self, scope, *, lineage=None, invalidate=True, dry_run=False, confirm=False, force_paths=None, under=None):
        self.calls.append({"scope": scope, "lineage": lineage, "dry_run": dry_run})
        return PLANNED if dry_run else self.outcome


def request(**extra) -> dict:
    return {"operation": "site_rerender_pages", "scope": "story", "storyLineageId": LINEAGE, "invalidate": False, **extra}


class ServerJobTest(LockTableCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = FakeService(WROTE)
        self.scheduled: list[dict] = []
        self.patches = [
            mock.patch.object(handler, "create_authoring_client", return_value=(object(), {})),
            mock.patch.object(handler, "refresh_service", return_value=self.service),
            mock.patch.object(handler, "schedule_projection_task", side_effect=lambda task, reason: self.scheduled.append(task) or True),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        super().tearDown()

    def ask(self, **arguments) -> dict:
        return handler.refresh_site_pages_action(arguments)

    def test_an_async_story_rerender_answers_with_a_job_and_renders_nothing_itself(self) -> None:
        answer = self.ask(**request(**{"async": True}))
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["scheduled"])
        self.assertEqual(answer["job"]["state"], QUEUED)
        self.assertEqual([call["dry_run"] for call in self.service.calls], [True])   # only the guard's preview ran in the call
        self.assertEqual(self.scheduled[0]["jobKey"], answer["jobKey"])
        self.assertEqual(self.scheduled[0]["jobId"], answer["job"]["jobId"])
        self.assertEqual(self.scheduled[0]["storyLineageId"], LINEAGE)

    def test_without_async_a_story_rerender_still_runs_inside_the_call(self) -> None:
        answer = self.ask(**request())
        self.assertTrue(answer["ok"])
        self.assertNotIn("scheduled", answer)
        self.assertEqual(self.scheduled, [])

    def test_the_same_request_while_one_is_queued_joins_it(self) -> None:
        first = self.ask(**request(**{"async": True}))
        second = self.ask(**request(**{"async": True}))
        self.assertTrue(second["job"]["joined"])
        self.assertEqual(second["job"]["jobId"], first["job"]["jobId"])
        self.assertEqual(len(self.scheduled), 1)

    def test_a_different_request_has_its_own_job(self) -> None:
        first = self.ask(**request(**{"async": True}))
        other = self.ask(**request(**{"async": True, "invalidate": True}))
        self.assertNotEqual(other["jobKey"], first["jobKey"])
        self.assertEqual(len(self.scheduled), 2)

    def test_the_status_follows_the_job_to_done_with_what_it_wrote(self) -> None:
        answer = self.ask(**request(**{"async": True}))
        self.assertEqual(self.ask(operation="site_rerender_pages", jobStatus=True, jobKey=answer["jobKey"])["job"]["state"], QUEUED)
        handler.run_projection_task(self.scheduled[0])
        status = self.ask(operation="site_rerender_pages", jobStatus=True, jobKey=answer["jobKey"])["job"]
        self.assertEqual(status["state"], DONE)
        self.assertEqual(status["rendered"]["count"], 1)
        self.assertEqual(status["invalidation"]["status"], "not-requested")

    def test_the_status_can_be_asked_with_the_request_instead_of_the_key(self) -> None:
        answer = self.ask(**request(**{"async": True}))
        again = self.ask(**request(jobStatus=True))
        self.assertEqual(again["jobKey"], answer["jobKey"])
        self.assertEqual(again["job"]["jobId"], answer["job"]["jobId"])

    def test_a_render_that_fails_ends_the_job_failed_with_the_reason_and_the_task_still_fails_for_retry(self) -> None:
        self.service.outcome = BROKEN
        answer = self.ask(**request(**{"async": True}))
        with self.assertRaises(handler.ProjectionTaskFailed):
            handler.run_projection_task(self.scheduled[0])
        status = self.ask(operation="site_rerender_pages", jobStatus=True, jobKey=answer["jobKey"])["job"]
        self.assertEqual(status["state"], FAILED)
        self.assertEqual(status["error"], "the hook raised")

    def test_a_render_that_raises_ends_the_job_failed(self) -> None:
        answer = self.ask(**request(**{"async": True}))
        with mock.patch.object(self.service, "rerender", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
            handler.run_projection_task(self.scheduled[0])
        status = self.ask(operation="site_rerender_pages", jobStatus=True, jobKey=answer["jobKey"])["job"]
        self.assertEqual((status["state"], status["error"]), (FAILED, "RuntimeError: boom"))

    def test_a_retry_of_a_task_whose_job_is_done_does_nothing(self) -> None:
        self.ask(**request(**{"async": True}))
        handler.run_projection_task(self.scheduled[0])
        calls = len(self.service.calls)
        self.assertTrue(handler.run_projection_task(self.scheduled[0])["alreadyBuilt"])
        self.assertEqual(len(self.service.calls), calls)

    def test_a_status_with_neither_key_nor_scope_is_refused(self) -> None:
        answer = self.ask(operation="site_rerender_pages", jobStatus=True)
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["error"]["code"], "invalid_input")

    def test_a_job_that_cannot_be_scheduled_ends_failed(self) -> None:
        with mock.patch.object(handler, "schedule_projection_task", return_value=False):
            answer = self.ask(**request(**{"async": True}))
        self.assertEqual(answer["error"]["code"], "not_scheduled")
        key = handler.rerender_job_key(request())
        self.assertEqual(self.ask(operation="site_rerender_pages", jobStatus=True, jobKey=key)["job"]["state"], FAILED)


class Newsroom:
    """The signed-in lane's far end: ``refreshSitePages`` answers come from ``script`` (called with the decoded input), or the call is too slow for the client."""

    def __init__(self, script) -> None:
        self.script, self.inputs = script, []

    def graphql(self, query, variables=None):
        payload = json.loads(variables["input"])
        self.inputs.append(payload)
        answer = self.script(payload)
        if isinstance(answer, Exception):
            raise answer
        return {"refreshSitePages": json.dumps(answer)}


SCHEDULED = {"ok": True, "operation": "site_rerender_pages", "dryRun": False, "scheduled": True, "jobKey": "rerender#story#item-big#no-purge#", "job": {"jobId": "job-1", "state": "queued"},
             "rendered": {"ok": None, "scheduled": True, "requested": 1, "errors": []},
             "invalidation": {"ok": True, "status": "not-requested", "paths": [], "count": 0, "requests": [], "cost": {}}}


def scripted(*states):
    """The start answer, then one status answer per state; the last state repeats."""
    queue = list(states)

    def script(payload):
        if not payload.get("jobStatus"):
            return SCHEDULED
        state = queue.pop(0) if len(queue) > 1 else queue[0]
        return {"ok": True, "operation": "site_rerender_pages", "jobKey": SCHEDULED["jobKey"], "job": {"jobId": "job-1", **state}}

    return script


RUNNING = {"state": "running"}
DONE_JOB = {"state": "done", "rendered": {"ok": True, "count": 1, "errors": []}, "invalidation": {"ok": True, "status": "not-requested", "count": 0}}
FAILED_JOB = {"state": "failed", "rendered": {"ok": False, "count": 0, "errors": ["the hook raised"]}, "error": "the hook raised"}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def lane_of(newsroom: Newsroom):
    return lambda name, arguments: refresh_cli.run_signed_in(newsroom, name, arguments)


def settled(newsroom: Newsroom, **env) -> dict:
    clock = Clock()
    with mock.patch.dict("os.environ", {"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": "30", **env}):
        return refresh_cli.rerender_with_job(lane_of(newsroom), "site_rerender_pages", {"scope": "story", "storyLineageId": LINEAGE, "invalidate": False, "dryRun": False},
                                             check="papyrus ops content rerender --story item-big --no-invalidate --status", sleep=clock.sleep, clock=clock)


class ClientWaitTest(unittest.TestCase):
    def test_a_rerender_that_outlasts_the_first_call_is_asked_about_until_done(self) -> None:
        newsroom = Newsroom(scripted(RUNNING, RUNNING, DONE_JOB))
        result = settled(newsroom)
        self.assertTrue(result["ok"])
        self.assertEqual(result["job"]["state"], "done")
        self.assertEqual(result["rendered"]["count"], 1)
        self.assertNotIn("scheduled", result)
        self.assertTrue(newsroom.inputs[0]["async"])
        self.assertEqual([entry.get("jobKey") for entry in newsroom.inputs[1:]], [SCHEDULED["jobKey"]] * 3)

    def test_a_job_still_running_when_the_wait_is_over_is_reported_as_still_running_not_failed(self) -> None:
        result = settled(Newsroom(scripted(RUNNING)), PAPYRUS_PROJECTION_TIMEOUT_SECONDS="10")
        self.assertIsNone(result["ok"])
        self.assertEqual(result["status"], "still-running")
        self.assertIn("not a failure", result["error"])
        self.assertIn("--status", result["check"])

    def test_a_server_failure_is_reported_as_failed_with_the_reason(self) -> None:
        result = settled(Newsroom(scripted(RUNNING, FAILED_JOB)))
        self.assertFalse(result["ok"])
        self.assertNotIn("status", result)
        self.assertEqual(result["rendered"]["errors"], ["the hook raised"])
        self.assertIn("the hook raised", refresh_cli.render_text(result))

    def test_a_request_that_gets_no_answer_is_unknown_not_failed(self) -> None:
        for error in (GraphQLTimeoutError("The read operation timed out"), RuntimeError("Execution timed out")):
            result = settled(Newsroom(lambda payload, error=error: error))
            self.assertEqual((result["ok"], result["status"]), (None, "unknown"), error)

    def test_another_error_is_not_swallowed(self) -> None:
        with self.assertRaises(RuntimeError):
            settled(Newsroom(lambda payload: RuntimeError("Not Authorized")))

    def test_a_dry_run_is_asked_once_with_no_job(self) -> None:
        newsroom = Newsroom(lambda payload: {"ok": True, "operation": "site_rerender_pages", "dryRun": True, "rendered": {"ok": True, "dryRun": True, "wouldWrite": [], "count": 0, "errors": []}})
        result = refresh_cli.rerender_with_job(lane_of(newsroom), "site_rerender_pages", {"scope": "story", "dryRun": True}, check="x")
        self.assertTrue(result["dryRun"])
        self.assertNotIn("async", newsroom.inputs[0])

    def test_a_site_without_job_records_answers_scheduled_and_is_not_polled(self) -> None:
        bare = {**SCHEDULED}
        bare.pop("job")
        bare.pop("jobKey")
        newsroom = Newsroom(lambda payload: bare)
        self.assertTrue(settled(newsroom)["scheduled"])
        self.assertEqual(len(newsroom.inputs), 1)


def command(*flags: str, newsroom: Newsroom, **env):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True), \
            mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(newsroom, {})), \
            mock.patch("papyrus_content.projection_trigger.JOB_POLL_SECONDS", 0.001), \
            mock.patch.dict("os.environ", {"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": "0.01", **env}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            refresh_cli.content_rerender(list(flags))
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class CommandTest(unittest.TestCase):
    FLAGS = ("--story", LINEAGE, "--no-invalidate")

    def test_done_exits_zero_and_says_what_was_written(self) -> None:
        code, out, _err = command(*self.FLAGS, newsroom=Newsroom(scripted(DONE_JOB)))
        self.assertEqual(code, 0, out)
        self.assertIn("re-render: ok, wrote 1 pages", out)

    def test_still_running_exits_five_and_says_how_to_check(self) -> None:
        code, out, err = command(*self.FLAGS, newsroom=Newsroom(scripted(RUNNING)))
        self.assertEqual(code, 5)
        self.assertIn("STILL RUNNING, not failed", out)
        self.assertIn("papyrus ops content rerender --story item-big --no-invalidate --status", out)
        self.assertNotIn("did not finish", err)

    def test_failed_exits_one_with_the_reason(self) -> None:
        code, out, _err = command(*self.FLAGS, newsroom=Newsroom(scripted(FAILED_JOB)))
        self.assertEqual(code, 1)
        self.assertIn("error: the hook raised", out)

    def test_a_timeout_starting_it_exits_five_as_unknown(self) -> None:
        code, out, _err = command(*self.FLAGS, newsroom=Newsroom(lambda payload: GraphQLTimeoutError("The read operation timed out")))
        self.assertEqual(code, 5)
        self.assertIn("OUTCOME NOT KNOWN, not failed", out)

    def test_status_asks_once_and_reports_the_end(self) -> None:
        newsroom = Newsroom(scripted(DONE_JOB))
        code, out, _err = command(*self.FLAGS, "--status", newsroom=newsroom)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(newsroom.inputs), 1)
        self.assertTrue(newsroom.inputs[0]["jobStatus"])
        self.assertIn("re-render: ok", out)

    def test_status_of_a_job_still_running_exits_five(self) -> None:
        code, out, _err = command(*self.FLAGS, "--status", newsroom=Newsroom(scripted(RUNNING)))
        self.assertEqual(code, 5)
        self.assertIn("STILL RUNNING", out)

    def test_status_with_no_record_is_unknown(self) -> None:
        code, out, _err = command(*self.FLAGS, "--status", newsroom=Newsroom(lambda payload: {"ok": True, "jobKey": "k", "job": {"state": "unknown"}}))
        self.assertEqual(code, 5)
        self.assertIn("OUTCOME NOT KNOWN", out)


class LinkStoryRerenderOutcomeTest(unittest.TestCase):
    """The re-render after ``stories link-story`` reports the same three outcomes."""

    def run_with(self, result: dict) -> dict:
        client = mock.Mock()
        client.get_record.return_value = {"id": "published"}
        return story_rerender.rerender_stories(client, [LINEAGE], request=lambda client, lineage: result)

    def test_a_job_still_running_is_a_running_row_and_a_warning_that_says_it_is_not_a_failure(self) -> None:
        done = self.run_with({"ok": None, "status": "still-running", "error": "the pages are still being built after 120 s, which is not a failure", "check": "x"})
        self.assertEqual(done["rerendered"][0]["status"], "running")
        self.assertIn("not a failure", done["warnings"][0])
        self.assertIn("rerender --story item-big --no-invalidate --status", done["warnings"][0])
        self.assertNotIn("failed", done["warnings"][0])

    def test_an_unanswered_request_is_an_unknown_row(self) -> None:
        done = self.run_with({"ok": None, "status": "unknown", "error": "timed out", "check": "x"})
        self.assertEqual(done["rerendered"][0]["status"], "unknown")

    def test_a_failed_job_is_a_failed_row_with_the_reason(self) -> None:
        done = self.run_with({"ok": False, "operation": "site_rerender_pages", "rendered": {"ok": False, "errors": ["the hook raised"]}})
        self.assertEqual(done["rerendered"][0]["status"], "failed")
        self.assertIn("the hook raised", done["warnings"][0])

    def test_the_real_request_waits_for_the_job_and_reports_done(self) -> None:
        newsroom = Newsroom(scripted(RUNNING, DONE_JOB))
        client = mock.Mock()
        client.get_record.return_value = {"id": "published"}
        clock = Clock()
        original = refresh_cli.rerender_with_job
        with mock.patch.object(refresh_cli, "run_signed_in", side_effect=lambda _client, name, arguments: _signed(newsroom, name, arguments)), \
                mock.patch.object(refresh_cli, "rerender_with_job", side_effect=lambda *a, **k: original(*a, sleep=clock.sleep, clock=clock, **k)):
            done = story_rerender.rerender_stories(client, [LINEAGE], request=story_rerender.signed_in_request)
        self.assertEqual(done["rerendered"][0]["status"], "ok")
        self.assertEqual(done["warnings"], [])


def _signed(newsroom, name, arguments):
    data = newsroom.graphql("mutation Refresh", {"input": json.dumps({"operation": name, **arguments})})
    return json.loads(data["refreshSitePages"])
