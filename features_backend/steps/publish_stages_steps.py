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

from papyrus_content.operator_errors import GraphQLRequestError, GraphQLTimeoutError  # noqa: E402
from papyrus_content.publish_commands import content_publish  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.test_publish_stages import ITEM, SlowOrFakeFunction, publish, saved, written  # noqa: E402

TIMEOUT = "GraphQL request failed: The read operation timed out"


def prepare(context, **function) -> None:
    context.function = saved(SlowOrFakeFunction(**function))
    context.version_served = 1
    context.runs = []


@given("a saved story and a page-building function that answers with the pages it wrote")
def answers(context) -> None:
    prepare(context, response=written())


@given("a saved story and a page-building function whose cache purge was refused")
def purge_refused(context) -> None:
    prepare(context, response={**written(), "invalidation": {"status": "failed", "reason": "the purge was refused", "paths": []}})


@given("a saved story and a page-building function that skipped the purge because the site leaves it off")
def purge_off(context) -> None:
    prepare(context, response={**written(), "invalidation": {"status": "skipped", "reason": "off", "paths": []}})


@given("a saved story and a page-building function that is too slow for the client")
def too_slow(context) -> None:
    prepare(context, error=GraphQLTimeoutError(TIMEOUT))


@given("a saved story and a page-building function that is too slow for the client the first time")
def too_slow_once(context) -> None:
    prepare(context, response=written(), errors=[GraphQLTimeoutError(TIMEOUT)])


@given("a saved story and a page-building function that runs out of time")
def runs_out(context) -> None:
    prepare(context, error=GraphQLRequestError("GraphQL request failed: Lambda:ExecutionTimeout Task timed out after 75.00 seconds"))


@given("the public address still serves an older version")
def old_version(context) -> None:
    context.version_served = None


def run(context, flags: list[str]) -> None:
    code, out, err = publish(context.function, flags, version=context.version_served)
    context.runs.append((code, out, err))
    context.exit_code, context.stdout, context.stderr = code, out, err
    try:
        context.payload = json.loads(out)
    except ValueError:
        context.payload = None


@when("the operator runs the publish command and asks to verify it")
def publishes_verified(context) -> None:
    run(context, ["--json", "--verify", "--verify-seconds", "0"])


@when("the operator runs the publish command and asks to verify it without waiting")
def publishes_verified_now(context) -> None:
    run(context, ["--json", "--verify", "--verify-seconds", "0"])


@when("the operator runs the publish command")
def publishes(context) -> None:
    if hasattr(context, "function"):
        run(context, ["--json"])
    else:
        run_checklist(context, [])


@when("the operator runs the publish command again")
def publishes_again(context) -> None:
    run(context, ["--json"])


@then("the second run exits with code {code:d}")
def second_exits(context, code: int) -> None:
    assert context.runs[1][0] == code, context.runs[1]


@then("the second run lists the pages written")
def second_pages(context) -> None:
    assert json.loads(context.runs[1][1])["stages"]["projected"]["pages"] == written()["paths"]


@then("the result lists the pages written")
def lists_pages(context) -> None:
    assert context.payload["stages"]["projected"]["pages"] == written()["paths"], context.payload


@then("the result lists the paths purged at the edge")
def lists_paths(context) -> None:
    assert "/articles/hello/index.html" in context.payload["stages"]["invalidated"]["paths"], context.payload


@then("the public page shows the published version")
def public_current(context) -> None:
    assert context.payload["stages"]["verified"]["status"] == "current", context.payload


@then("the cache invalidation stage is reported as skipped")
def invalidation_skipped(context) -> None:
    assert context.payload["stages"]["invalidated"]["status"] == "skipped", context.payload


@then("the verdict says no purge was made")
def verdict_no_purge(context) -> None:
    assert "NOT PURGED" in context.payload["verdict"], context.payload["verdict"]


@then("the verdict does not say the page was purged")
def verdict_not_purged(context) -> None:
    assert not context.payload["verdict"].startswith("PURGED"), context.payload["verdict"]


@then("the page is reported as written")
def page_written(context) -> None:
    assert context.payload["stages"]["projected"]["status"] == "ok" and context.payload["pagePublished"], context.payload


@then("the result says the failure was in the cache purge, not in the write")
def purge_not_write(context) -> None:
    assert context.payload["failedStage"] == "invalidation-failed" and "Not a write failure" in context.payload["message"], context.payload


@then("the result says the page is still running")
def still_running(context) -> None:
    assert context.payload["stages"]["projected"]["status"] == "still-running" and "STILL RUNNING" in context.payload["message"], context.payload


@then("the result does not say the publish failed")
def not_failed(context) -> None:
    assert "FAILED" not in context.payload["message"], context.payload


@then("the story's data stays published")
def story_published(context) -> None:
    assert context.function.get_record("Item", ITEM)["status"] == "published"


@then("the result says that running the command again is safe")
def retry_safe(context) -> None:
    assert "safe" in context.payload["stages"]["projected"]["error"], context.payload


@then("the call to the function was allowed to take {seconds:d} seconds")
def waited(context, seconds: int) -> None:
    assert context.function.waited == [float(seconds)], context.function.waited


# ---- the checklist rule (D)

@given("a story whose review steps are open")
def story_with_open_steps(context) -> None:
    from papyrus_content.story_reporting import create_story

    context.client = FakeAuthoringClient()
    story = create_story(context.client, title="A Story", section_key=None, actor="AI")
    context.client.tables["Item"][story["id"]]["type"] = "article"
    context.item_id = story["id"]


@given("a story that does not exist")
def no_story(context) -> None:
    context.client = FakeAuthoringClient()
    context.item_id = "item-missing"


def run_checklist(context, flags: list[str]) -> None:
    out, err = io.StringIO(), io.StringIO()
    context.exit_code = 0
    with mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(context.client, {})), \
            mock.patch("papyrus_content.publish_commands.refuse_placeholder_slug"), \
            mock.patch("papyrus_content.projection.runtime.render_preflight"), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            content_publish(["--id", context.item_id, *flags])
        except SystemExit as exit_:
            context.exit_code = exit_.code
    context.stdout, context.stderr = out.getvalue(), err.getvalue()
    try:
        context.payload = json.loads(context.stdout)
    except ValueError:
        context.payload = None


@when("the operator runs the publish command asking for a machine-readable result")
def publishes_json(context) -> None:
    run_checklist(context, ["--json"])


@then('the result names the code "{code}"')
def names_code(context, code: str) -> None:
    assert context.payload["code"] == code, context.payload


@then('the result lists the open step "{key}" labelled "{label}"')
def lists_step(context, key: str, label: str) -> None:
    assert {"key": key, "label": label} in context.payload["openSteps"], context.payload


@then('the output lists the open step "{key}"')
def output_lists_step(context, key: str) -> None:
    assert f"open step: {key}:" in context.stdout, context.stdout


@then("no published record exists for the story")
def nothing_published(context) -> None:
    assert context.client.tables.get("PublishedItem", {}) == {}
