from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures/newsroom/tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.operator_errors import GraphQLTimeoutError  # noqa: E402
from papyrus_content.page_refresh import cli as refresh_cli  # noqa: E402
from papyrus_content.projection.publish_jobs import DONE, FAILED, QUEUED  # noqa: E402
from procedures.newsroom.tests import test_rerender_jobs as support  # noqa: E402

FLAGS = ["--story", support.LINEAGE, "--no-invalidate"]


def run_command(context, flags: list[str]) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True), \
            mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(context.newsroom, {})), \
            mock.patch("papyrus_content.projection_trigger.JOB_POLL_SECONDS", 0.001), \
            mock.patch.dict("os.environ", {"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": "0.01"}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            refresh_cli.content_rerender(flags)
        except SystemExit as stop:
            code = stop.code
    context.exit_code, context.out, context.err = code, out.getvalue(), err.getvalue()


# ------------------------------------------------------------------ the command


@given("a re-render that is still running when the command first asks and done a moment later")
def step_slow_then_done(context) -> None:
    context.newsroom = support.Newsroom(support.scripted(support.RUNNING, support.RUNNING, support.DONE_JOB))


@given("a re-render that keeps running past the command's wait")
def step_never_done(context) -> None:
    context.newsroom = support.Newsroom(support.scripted(support.RUNNING))


@given("a re-render that has finished")
def step_finished(context) -> None:
    context.newsroom = support.Newsroom(support.scripted(support.DONE_JOB))


@given('a re-render whose job fails with the reason "{reason}"')
def step_failed(context, reason: str) -> None:
    job = {"state": "failed", "rendered": {"ok": False, "count": 0, "errors": [reason]}, "error": reason}
    context.newsroom = support.Newsroom(support.scripted(support.RUNNING, job))


@given("a newsroom that does not answer the request to start the re-render")
def step_no_answer(context) -> None:
    context.newsroom = support.Newsroom(lambda payload: GraphQLTimeoutError("The read operation timed out"))


@when("the editor re-renders the Story with no purge")
def step_rerender(context) -> None:
    run_command(context, FLAGS)


@when("the editor asks how the re-render of the Story stands")
def step_status(context) -> None:
    run_command(context, [*FLAGS, "--status"])


@then("the re-render command exits with code {code:d}")
def step_exit(context, code: int) -> None:
    assert context.exit_code == code, (context.exit_code, context.out, context.err)


@then("the command says the re-render wrote {count:d} pages")
def step_wrote(context, count: int) -> None:
    assert f"re-render: ok, wrote {count} pages" in context.out, context.out


@then("the command asked about the job until it was done")
def step_polled(context) -> None:
    asked = [entry for entry in context.newsroom.inputs if entry.get("jobStatus")]
    assert len(asked) == 3 and not any(entry.get("async") for entry in asked), context.newsroom.inputs
    assert context.newsroom.inputs[0]["async"] is True, context.newsroom.inputs


@then("the command says the re-render is still running and not failed")
def step_running(context) -> None:
    assert "STILL RUNNING, not failed" in context.out and "did not finish" not in context.err, (context.out, context.err)


@then("the command names the command that checks on it")
def step_check(context) -> None:
    assert "papyrus ops content rerender --story item-big --no-invalidate --status" in context.out, context.out


@then('the command says the re-render failed with the reason "{reason}"')
def step_failed_reason(context, reason: str) -> None:
    assert "FAILED" in context.out and f"error: {reason}" in context.out, context.out


@then("the command says the outcome is not known and not failed")
def step_unknown(context) -> None:
    assert "OUTCOME NOT KNOWN, not failed" in context.out, context.out


# ------------------------------------------------------------------ the server


def server(context):
    if getattr(context, "server_case", None) is None:
        case = support.ServerJobTest("test_an_async_story_rerender_answers_with_a_job_and_renders_nothing_itself")
        case.setUp()
        context.add_cleanup(case.tearDown)
        context.server_case = case
    return context.server_case


@given("a site that keeps job records")
def step_site(context) -> None:
    server(context)


@when("the editor asks the newsroom to re-render the Story in the background")
@given("the editor asked the newsroom to re-render the Story in the background")
def step_background(context) -> None:
    context.answer = server(context).ask(**support.request(**{"async": True}))


@then("the answer names a job that is queued")
def step_queued(context) -> None:
    assert context.answer["job"]["jobId"] and context.answer["job"]["state"] == QUEUED, context.answer


@then("nothing was rendered inside the call")
def step_nothing_rendered(context) -> None:
    assert [call["dry_run"] for call in server(context).service.calls] == [True], server(context).service.calls


@then("the same request again joins that job")
def step_joins(context) -> None:
    again = server(context).ask(**support.request(**{"async": True}))
    assert again["job"]["joined"] and again["job"]["jobId"] == context.answer["job"]["jobId"], again


@when("the scheduled re-render runs")
def step_runs(context) -> None:
    support.handler.run_projection_task(server(context).scheduled[0])


@when('the scheduled re-render runs and the render fails with "{reason}"')
def step_runs_failing(context, reason: str) -> None:
    case = server(context)
    case.service.outcome = {**support.BROKEN, "rendered": {**support.BROKEN["rendered"], "errors": [reason]}}
    try:
        support.handler.run_projection_task(case.scheduled[0])
    except support.handler.ProjectionTaskFailed:
        pass   # the task fails so that Lambda retries it; the job already says how it ended


def job_status(context) -> dict:
    return server(context).ask(operation="site_rerender_pages", jobStatus=True, jobKey=context.answer["jobKey"])["job"]


@then("asking for the job's status says it is done and that it wrote {count:d} pages")
def step_status_done(context, count: int) -> None:
    status = job_status(context)
    assert status["state"] == DONE and status["rendered"]["count"] == count, status


@then('asking for the job\'s status says it failed with the reason "{reason}"')
def step_status_failed(context, reason: str) -> None:
    status = job_status(context)
    assert status["state"] == FAILED and status["error"] == reason, status


# ------------------------------------------------------------------ the link command's re-render


@when("a link between two Stories is saved and their pages are re-rendered")
def step_link(context) -> None:
    from procedures.newsroom.tests.test_link_rerender import link
    from procedures.newsroom.tests.test_story_links import site as link_site

    client = link_site()
    context.link_client = client
    clock = support.Clock()
    original = refresh_cli.rerender_with_job
    with mock.patch.object(refresh_cli, "run_signed_in", side_effect=lambda _client, name, arguments: support._signed(context.newsroom, name, arguments)), \
            mock.patch.object(refresh_cli, "rerender_with_job", side_effect=lambda *a, **k: original(*a, sleep=clock.sleep, clock=clock, **k)), \
            mock.patch.dict("os.environ", {"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": "10"}):
        context.link_out, context.link_err, context.link_failure = link(client, "--story", "item-big", "--to", "item-post-1")


@then("the link stays saved")
def step_link_saved(context) -> None:
    assert context.link_failure is None, context.link_err
    assert len(context.link_client.tables["SemanticRelation"]) == 1


@then("the warning says the re-render is not confirmed and is not a failure")
def step_link_warning(context) -> None:
    assert "has not been confirmed" in context.link_err and "not a failure" in context.link_err, context.link_err
    assert "\trunning" in context.link_out, context.link_out


@then("the warning names the command that checks on it")
def step_link_check(context) -> None:
    assert "papyrus ops content rerender --story item-big --no-invalidate --status" in context.link_err, context.link_err
