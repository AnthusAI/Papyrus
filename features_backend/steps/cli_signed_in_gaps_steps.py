"""Save-version author, the assignment direction, and the root guard message, through the real commands. No network or AWS."""
import contextlib
import io
import json
import pathlib
import sys
from unittest import mock

from behave import given, then, when

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))

from fake_client import FakeAuthoringClient  # noqa: E402

from papyrus import cli as papyrus_cli  # noqa: E402
from papyrus_content import assignments_commands, story_commands  # noqa: E402
from papyrus_content.operator_errors import OperatorError  # noqa: E402

LINEAGE = "story-gap"


class Client(FakeAuthoringClient):
    endpoint = "https://example.test/graphql"
    tenant_id = None


def _story_client():
    client = Client({"Item": [{"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "headline": "A story",
                               "title": "A story", "stage": "idea", "slug": "a-story", "type": "untyped", "section": "news"}]})
    return client


@given("a Story with one version")
def story(context):
    context.client = _story_client()
    context.signed_in, context.label, context.failure, context.stderr = False, None, None, ""


@given('the CLI is signed in as "{label}"')
def signed_in(context, label):
    context.signed_in, context.label = True, label


@given("the CLI is signed in but its session names no one")
def signed_in_nobody(context):
    context.signed_in, context.label = True, None


@given("the CLI uses the IAM lane for a save")
def iam(context):
    context.signed_in, context.label = False, None


def _save(context, *extra):
    out, err = io.StringIO(), io.StringIO()
    context.failure = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, {})), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=context.signed_in), \
            mock.patch("papyrus_content.cli_user_auth.signed_in_label", return_value=context.label), \
            mock.patch("papyrus_content.story_triggers.deliver_from_environment"), \
            mock.patch.object(story_commands, "print_reminder"), \
            mock.patch.object(story_commands, "reminder_assessment", return_value=None):
        try:
            story_commands.stories_save_version(["--story", LINEAGE, "--body", "New text", "--reason", "test", "--no-check", *extra])
        except BaseException as error:  # noqa: BLE001
            context.failure = error
    context.stdout, context.stderr = out.getvalue(), err.getvalue()


@when("the person saves a new version without an author label")
def save_without(context):
    _save(context)


@when('the person saves a new version with the author label "{label}"')
def save_with(context, label):
    _save(context, "--author-label", label)


@then('the new version is recorded as written by "{who}"')
def written_by(context, who):
    assert context.failure is None, context.failure
    newest = max(context.client.tables["Item"].values(), key=lambda row: int(row["versionNumber"]))
    assert int(newest["versionNumber"]) == 2 and newest.get("versionCreatedBy") == who, newest


@then("a warning says the author label is ignored")
def warns(context):
    assert "is ignored" in context.stderr, context.stderr


@then("nothing is saved and the person is told to check whoami")
def nothing_saved(context):
    assert isinstance(context.failure, OperatorError) and "whoami" in str(context.failure), context.failure
    assert len(context.client.tables["Item"]) == 1


@then("the save is refused because the author label is required")
def refused(context):
    assert isinstance(context.failure, ValueError) and "--author-label is required" in str(context.failure), context.failure
    assert len(context.client.tables["Item"]) == 1


def _assignment(context, metadata=None, attachment_text=None):
    row = {"id": "as-1", "status": "open", "assignmentTypeKey": "research.multi", "title": "Look", "queueKey": "q", "sectionKey": "news"}
    if metadata is not None:
        row["metadata"] = json.dumps(metadata)
    tables = {"Assignment": [row]}
    if attachment_text is not None:
        tables["ModelAttachment"] = [{"id": "att-1", "ownerId": "as-1", "role": "metadata", "sortKey": "metadata", "status": "ready"}]
    context.client = Client(tables)
    context.attachment_text = attachment_text


@given('an Assignment whose direction is "{text}"')
def direction_single(context, text):
    _assignment(context, {"direction": text})
    context.expected = [text]


@given("an Assignment whose direction has three lines with a blank line between the first two")
def direction_multi(context):
    _assignment(context, {"direction": "Find the vendors.\n\nCompare their claims.\nName what is unverified."})
    context.expected = ["Find the vendors.", "", "Compare their claims.", "Name what is unverified."]


@given("an Assignment whose direction is only in its metadata attachment")
def direction_attachment(context):
    _assignment(context, None, json.dumps({"direction": "Compare the two vendors' claims."}))


@given("an Assignment with no direction")
def direction_none(context):
    _assignment(context, {"kind": "research.assignment.created"})


@when("a person shows the Assignment")
def show(context):
    out = io.StringIO()
    patches = [mock.patch.object(assignments_commands, "create_authoring_client", return_value=(context.client, {}))]
    if context.attachment_text is not None:
        patches.append(mock.patch("papyrus_content.assignments.download_attachment_buffer", lambda client, attachment: context.attachment_text.encode()))
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(out):
        for patch in patches:
            stack.enter_context(patch)
        assignments_commands.assignments_show(["--assignment", "as-1"])
    context.rows = [line.split("\t") for line in out.getvalue().splitlines()]


def _direction_rows(context):
    return [row for row in context.rows if row[:2] == ["assignments", "show"] and row[3:4] == ["direction"]]


@then('one direction row holds "{text}"')
def one_row(context, text):
    rows = _direction_rows(context)
    assert len(rows) == 1 and rows[0][4] == text, rows


@then("the direction prints as one row per line, in order, the blank line as an empty value")
def per_line(context):
    assert [row[4] for row in _direction_rows(context)] == context.expected, _direction_rows(context)


@then("every row still has the same tab-separated columns")
def same_columns(context):
    assert {len(row) for row in _direction_rows(context)} == {5}


@then("no direction row is printed")
def no_row(context):
    assert _direction_rows(context) == []


def _guard(context, operator_root, module_root):
    context.guard_error = None
    with mock.patch.object(papyrus_cli, "PAPYRUS_ROOT", module_root), mock.patch.object(papyrus_cli, "_find_operator_repo_root", return_value=operator_root):
        try:
            papyrus_cli._enforce_root_guard(["stories", "show"], cwd=operator_root)
        except ValueError as error:
            context.guard_error = str(error)


@given("an install whose root differs from the Papyrus checkout the person is inside")
def differing_root(context):
    context.roots = (pathlib.Path("/tmp/operator-root").resolve(), pathlib.Path("/tmp/module-root").resolve())


@given("an install whose root is the Papyrus checkout the person is inside")
def matching_root(context):
    context.roots = (pathlib.Path("/tmp/module-root").resolve(),) * 2


@when("the person runs a command")
def run_command(context):
    _guard(context, *context.roots)


@then("the command is still blocked")
def blocked(context):
    assert context.guard_error and "papyrus-root-guard\tblocked" in context.guard_error


@then("the message tells the person to run it from another folder")
def another_folder(context):
    assert "Run it from another folder" in context.guard_error, context.guard_error


@then("the message says the cross-root flag is an explicit choice")
def explicit_choice(context):
    assert "--allow-cross-root" in context.guard_error and "explicit choice" in context.guard_error, context.guard_error


@then("the command is not blocked")
def not_blocked(context):
    assert context.guard_error is None
