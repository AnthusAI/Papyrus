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

from papyrus_content.publish_commands import content_publish, content_unpublish  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from papyrus_content.story_commands import stories_move  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

ITEM_ID = "item-articles-hello"
NOW = "2026-10-05T12:00:00Z"
BASE_ENVIRONMENT = {"PAPYRUS_PUBLICATION_KIND": "s3-projection", "PAPYRUS_CONTENT_ACTIONS_FUNCTION": "content-actions-fn", "PAPYRUS_GRAPHQL_AUTH": "iam"}


class Client(FakeAuthoringClient):
    def __init__(self, response: dict) -> None:
        super().__init__()
        self.mutations: list[tuple[str, dict]] = []
        self.response = response

    def graphql(self, query, variables=None):
        name = "unpublishItem" if "unpublishItem" in query else "publishItem"
        self.mutations.append((name, json.loads(variables["input"])))
        return {name: json.dumps(self.response)}


def save(context, slug: str) -> None:
    save_item(context.client, ItemFields(
        type="article", slug=slug, section="articles", front_matter_yaml="title: Hello\n",
        body_markus="Hello.\n", aliases=[], id=ITEM_ID,
    ), actor="behave", now=NOW)


def invoke(context, command, flags) -> None:
    out, err = io.StringIO(), io.StringIO()
    context.exit_code = 0
    context.client.calls.clear()
    with mock.patch.dict("os.environ", context.environment), \
            mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(context.client, {})), \
            mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(context.client, {})), \
            mock.patch("papyrus_content.story_triggers.deliver_from_environment"), \
            mock.patch("papyrus_content.projection_trigger._invoke_lambda", side_effect=context.lambda_error) as lambda_call, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            command(flags)
        except SystemExit as exit_:
            context.exit_code = exit_.code
    context.lambda_call = lambda_call
    context.stdout, context.stderr = out.getvalue(), err.getvalue()


@given("a site that projects its pages")
def projecting_site(context) -> None:
    context.environment = dict(BASE_ENVIRONMENT)
    context.client = Client({"ok": True, "changed": False, "projected": True, "live": True})
    context.lambda_error = None


@given('a saved draft story with the slug "{slug}"')
def saved_story(context, slug: str) -> None:
    save(context, slug)


@given("the story is published")
def story_published(context) -> None:
    publish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@given("the CLI is signed in as a newsroom user with no AWS credentials")
def signed_in(context) -> None:
    context.environment["PAPYRUS_GRAPHQL_AUTH"] = "user"
    context.lambda_error = RuntimeError("Unable to locate credentials")


@given("the projection trigger fails")
def trigger_fails(context) -> None:
    context.lambda_error = RuntimeError("denied")


@given("the newsroom's publish mutation reports that the projection failed")
def mutation_reports_failure(context) -> None:
    context.client.response = {"ok": True, "projected": False, "error": "bucket denied"}


@when("the operator publishes the story")
def operator_publishes(context) -> None:
    invoke(context, content_publish, ["--id", ITEM_ID])


@when("the operator publishes the story asking for JSON")
def operator_publishes_json(context) -> None:
    invoke(context, content_publish, ["--id", ITEM_ID, "--json"])


@when("the operator publishes the story without triggers")
def operator_publishes_quietly(context) -> None:
    invoke(context, content_publish, ["--id", ITEM_ID, "--no-trigger"])


@when("the operator previews publishing the story")
def operator_previews(context) -> None:
    invoke(context, content_publish, ["--id", ITEM_ID, "--dry-run"])


@when("the operator unpublishes the story")
def operator_unpublishes(context) -> None:
    invoke(context, content_unpublish, ["--id", ITEM_ID])


@then("the published records are written")
def records_written(context) -> None:
    assert context.client.get_record("Item", ITEM_ID)["status"] == "published"


@then('the projection was requested through the "{mutation}" mutation for the story')
def mutation_requested(context, mutation: str) -> None:
    # A publish asks for a background build (async) and waits on its job; an unpublish is one call (PPY-3acc8d).
    expected = {"id": ITEM_ID, "async": True} if mutation == "publishItem" else {"id": ITEM_ID}
    assert context.client.mutations[:1] == [(mutation, expected)], context.client.mutations
    assert all(name == mutation and payload == {"id": ITEM_ID, "jobStatus": True} for name, payload in context.client.mutations[1:]), context.client.mutations


@then("no AWS function was invoked")
def no_function(context) -> None:
    context.lambda_call.assert_not_called()


@then("no projection was requested for the story")
def no_projection(context) -> None:
    context.lambda_call.assert_not_called()
    assert context.client.mutations == []


@then("the command exits successfully")
def exits_ok(context) -> None:
    assert context.exit_code == 0, (context.exit_code, context.stdout, context.stderr)


@then("the command exits with an error")
def exits_error(context) -> None:
    assert context.exit_code not in (0, None), (context.exit_code, context.stdout, context.stderr)


@then("the output says the data is published but the page is not")
def says_page_missing(context) -> None:
    assert "the data is published but the page is not live" in context.stderr, context.stderr


@then('the output names the command "{command}" to retry')
def names_retry(context, command: str) -> None:
    assert f"Retry with: {command} {ITEM_ID}" in context.stderr, context.stderr


@then('the output names "{text}"')
def output_names(context, text: str) -> None:
    assert text in context.stdout + context.stderr


@then("the publish wrote nothing")
def nothing_written(context) -> None:
    assert context.client.write_calls() == []


@then("the JSON reports the data as published and the page as not published, with a retry command")
def json_facts(context) -> None:
    payload = json.loads(context.stdout)
    assert (payload["ok"], payload["dataPublished"], payload["pagePublished"]) == (False, True, False)
    assert payload["retry"] == f"papyrus ops content publish --id {ITEM_ID}"


# -- stories move --


@given("a story on the board")
def story_on_board(context) -> None:
    context.environment = dict(BASE_ENVIRONMENT)
    context.client = FakeAuthoringClient()
    context.lambda_error = None
    save(context, "hello")


def move(context, stage: str, *extra: str) -> None:
    invoke(context, stories_move, ["--story", ITEM_ID, "--stage", stage, *extra])


@when('the operator moves the story to the "{stage}" stage')
def operator_moves(context, stage: str) -> None:
    move(context, stage)


@when('the operator previews moving the story to the "{stage}" stage')
def operator_previews_move(context, stage: str) -> None:
    move(context, stage, "--dry-run")


@then('the warning says no page is published and names "{command}"')
def move_warning(context, command: str) -> None:
    assert "No page is published" in context.stderr and command in context.stderr, context.stderr
    assert "warning" not in context.stdout


@then('the story\'s stage is "{stage}"')
def stage_is(context, stage: str) -> None:
    assert context.client.get_record("Item", ITEM_ID)["stage"] == stage


@then("the story's stage is unchanged")
def stage_unchanged(context) -> None:
    assert context.client.get_record("Item", ITEM_ID)["stage"] != "published"


@then("no publish warning is printed")
def no_warning(context) -> None:
    assert context.stderr == ""


@then("the command exits with code {code:d}")
def exits_with_code(context, code: int) -> None:
    assert context.exit_code == code, (context.exit_code, context.stdout, context.stderr)
