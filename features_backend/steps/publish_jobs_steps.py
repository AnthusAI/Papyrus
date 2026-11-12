from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures/newsroom/tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.publish_jobs import DONE, QUEUED  # noqa: E402
from procedures.newsroom.tests.test_publish_jobs import AsynchronousPublishTest, CliWaitsForTheJobTest, handler, published_story  # noqa: E402


def _harness(context) -> AsynchronousPublishTest:
    """The unit tests' harness: moto's lock table, the fake newsroom client, and a recorder in place of the page build."""
    case = AsynchronousPublishTest("test_the_publish_answers_with_a_job_and_builds_nothing_itself")
    case.setUp()
    context.add_cleanup(case.tearDown)
    return case


@given("a story ready to publish on a site that keeps build records")
def step_story(context) -> None:
    context.jobs_case = _harness(context)
    published_story(context.jobs_case.client, "story-9", publish=False)
    context.story = "story-9"
    context.answers = []


@given("two stories ready to publish on a site that keeps build records")
def step_two_stories(context) -> None:
    step_story(context)
    published_story(context.jobs_case.client, "story-10", publish=False)
    context.stories = ["story-9", "story-10"]


@when("the editor publishes it from the CLI")
def step_publish(context) -> None:
    context.answers.append(context.jobs_case.publish(context.story))


@when("publishes it again before the build has started")
def step_publish_again(context) -> None:
    context.answers.append(context.jobs_case.publish(context.story))


@when("the editor publishes both from the CLI")
def step_publish_both(context) -> None:
    context.answers = [context.jobs_case.publish(story) for story in context.stories]


@then("the answer says the page is being built, with a job id and the page's address")
def step_answer(context) -> None:
    answer = context.answers[0]
    assert answer["ok"] and answer["scheduled"], answer
    assert answer["projection"]["state"] == QUEUED and answer["projection"]["jobId"], answer
    assert answer["itemPaths"] == [f"{context.story}/index.html"], answer
    assert context.jobs_case.projected == [], "the publish itself built nothing"


@then("exactly one build is started")
def step_one_build(context) -> None:
    assert [task["task"] for task in context.jobs_case.scheduled] == ["item"], context.jobs_case.scheduled


@then("the second answer names the same job")
def step_same_job(context) -> None:
    first, second = context.answers
    assert second["projection"]["joined"] is True, second
    assert second["projection"]["jobId"] == first["projection"]["jobId"], (first, second)


@when("the build runs")
def step_build_runs(context) -> None:
    result = handler.run_projection_task(context.jobs_case.scheduled[0])
    assert result["ok"], result


@then("asking for the job's status says it is done and names the page it wrote")
def step_status_done(context) -> None:
    status = context.jobs_case.status(context.story)["projection"]
    assert status["state"] == DONE, status
    assert status["jobId"] == context.answers[0]["projection"]["jobId"], status
    assert status["itemPaths"] == [f"{context.story}/index.html"], status


@when("the second build starts while another projection holds the lease")
def step_busy(context) -> None:
    context.jobs_case.lease.held_by_other = True
    try:
        handler.run_projection_task(context.jobs_case.scheduled[1])
    except handler.ProjectionTaskFailed as failed:
        context.busy_failure = failed
    context.jobs_case.lease.held_by_other = False


@then("the second build waits a few seconds at most and leaves its story queued")
def step_left_queued(context) -> None:
    assert getattr(context, "busy_failure", None) is not None, "the busy build fails so that Lambda retries it"
    assert context.jobs_case.lease.wait_seconds <= handler.QUEUED_LEASE_WAIT_SECONDS
    assert context.jobs_case.jobs_status(context.stories[1])["state"] == QUEUED
    assert context.jobs_case.projected == []


@when("the first build runs")
def step_first_runs(context) -> None:
    handler.run_projection_task(context.jobs_case.scheduled[0])


@then("it builds the queued story too before letting go of the lease")
def step_drained(context) -> None:
    assert context.jobs_case.projected == context.stories, context.jobs_case.projected
    assert context.jobs_case.jobs_status(context.stories[1])["state"] == DONE


@then("the retry of the second build finds its page already built")
def step_retry_noop(context) -> None:
    retried = handler.run_projection_task(context.jobs_case.scheduled[1])
    assert retried.get("alreadyBuilt") is True, retried
    assert context.jobs_case.projected == context.stories


@given("a page-building function that answers with a job and later reports it done")
def step_function_done(context) -> None:
    context.cli_answers = [
        {"ok": True, "scheduled": True, "itemPaths": ["story-1/index.html"], "url": "https://example.org/story-1/", "projection": {"jobId": "job-1", "state": "queued"}},
        {"ok": True, "projection": {"jobId": "job-1", "state": "running"}},
        {"ok": True, "projection": {"jobId": "job-1", "state": "done", "paths": ["story-1/index.html", "index.html"], "itemPaths": ["story-1/index.html"]}},
    ]
    context.cli_timeout = "60"


@given("a page-building function that answers with a job that stays queued")
def step_function_queued(context) -> None:
    context.cli_answers = [
        {"ok": True, "scheduled": True, "itemPaths": ["story-1/index.html"], "projection": {"jobId": "job-1", "state": "queued"}},
        {"ok": True, "projection": {"jobId": "job-1", "state": "queued"}},
    ]
    context.cli_timeout = "10"


@when("the operator's CLI publishes the story")
def step_cli(context) -> None:
    case = CliWaitsForTheJobTest("test_a_build_that_ends_is_reported_as_projected_with_its_pages")
    context.cli_outcome, context.cli_client = case.trigger(context.cli_answers, timeout=context.cli_timeout)


@then("it reports the page as built, with the pages written")
def step_cli_built(context) -> None:
    outcome = context.cli_outcome
    assert outcome["ok"] is True and outcome["status"] == "projected", outcome
    assert outcome["paths"] == ["story-1/index.html", "index.html"], outcome


@then("no call it made had to wait for the build")
def step_cli_short_calls(context) -> None:
    inputs = context.cli_client.inputs
    assert inputs[0] == {"id": "story-1", "async": True}, inputs
    assert all(entry == {"id": "story-1", "jobStatus": True} for entry in inputs[1:]), inputs


@then("it reports the page as still being built, which is not a failure, and names the job")
def step_cli_still(context) -> None:
    from papyrus_content.publish_stages import projected_stage

    outcome = context.cli_outcome
    assert outcome["ok"] is None and outcome["status"] == "still-running", outcome
    assert "job-1" in outcome["error"] and "not a failure" in outcome["error"], outcome
    assert projected_stage(outcome)["status"] == "still-running"


@given("a published story on a site that keeps build records")
def step_published_story(context) -> None:
    context.jobs_case = _harness(context)
    context.story = "story-1"
    context.answers = []


@when("the editor unpublishes it from the CLI")
def step_unpublish(context) -> None:
    context.answers.append(context.jobs_case.unpublish(context.story, **{"async": True}))


@then("the answer says the page is being taken down, with a job id")
def step_unpublish_answer(context) -> None:
    answer = context.answers[0]
    assert answer["ok"] and answer["scheduled"] and answer["changed"], answer
    assert answer["projection"]["state"] == QUEUED and answer["projection"]["jobId"], answer
    assert context.jobs_case.scheduled[0]["unpublished"] is True
    assert context.jobs_case.projected == [], "the unpublish itself built nothing"


@given("a page-building function that answers an unpublish with a job and later reports it done")
def step_unpublish_function(context) -> None:
    context.cli_answers = [
        {"ok": True, "changed": True, "scheduled": True, "itemPaths": [], "projection": {"jobId": "job-1", "state": "queued", "joined": False}},
        {"ok": True, "projection": {"jobId": "job-1", "state": "running"}},
        {"ok": True, "projection": {"jobId": "job-1", "state": "done", "paths": ["story-1/index.html", "index.html"]}},
    ]
    context.cli_timeout = "60"


@when("the operator's CLI unpublishes the story")
def step_cli_unpublish(context) -> None:
    case = CliWaitsForTheJobTest("test_a_build_that_ends_is_reported_as_projected_with_its_pages")
    context.cli_outcome, context.cli_client = case.trigger(context.cli_answers, timeout=context.cli_timeout, unpublished=True)


@then("it reports the page as taken down, with the pages written")
def step_cli_taken_down(context) -> None:
    outcome = context.cli_outcome
    assert outcome["ok"] is True and outcome["status"] == "projected", outcome
    assert outcome["paths"] == ["story-1/index.html", "index.html"], outcome


@given("a page-building function that builds the pages inside the call, as backends before this change do")
def step_old_backend(context) -> None:
    context.cli_answers = [{"ok": True, "projected": True, "paths": ["story-1/index.html"], "itemPaths": ["story-1/index.html"]}]
    context.cli_timeout = "60"


@then("it fails and says which backend to deploy, without asking again")
def step_refused(context) -> None:
    outcome = context.cli_outcome
    assert outcome["ok"] is False and "Deploy a backend that includes PPY-f171b4" in outcome["error"], outcome
    assert len(context.cli_client.inputs) == 1, context.cli_client.inputs
