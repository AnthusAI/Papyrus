"""Story CLI edges (features_backend/story-cli-edges.feature). The backend is a fake."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.operator_errors import OperatorError  # noqa: E402
from test_story_cli_live_test_edges import LINEAGE, REFERENCE, ShowMessagesTests, fresh_client, relation_metadata, run  # noqa: E402


def _go(context, command, *flags, **kwargs):
    context.out, context.err, context.failure = run(command, context.client, *flags, **kwargs)


@given("a Story with one saved version and one Reference for the story edge checks")
def _background(context):
    context.client = fresh_client()
    context.out = context.err = ""
    context.failure = None
    context.helper = ShowMessagesTests()
    context.thread = context.helper.thread_with(context.client)
    context.messages = 0


@when('the story edge checks create a Story titled "{title}"')
def _create(context, title):
    _go(context, story_commands.stories_create, "--title", title)


@when("the story edge checks create a Story and the save fails")
def _create_fails(context):
    with mock.patch.object(story_commands, "create_story", side_effect=RuntimeError("boom")):
        _go(context, story_commands.stories_create, "--title", "x")


@when('the story edge checks move the Story to "{stage}"')
def _move(context, stage):
    _go(context, story_commands.stories_move, "--story", LINEAGE, "--stage", stage)


@when('the story edge checks move the Story to "{stage}" and the save fails')
def _move_fails(context, stage):
    with mock.patch.object(story_commands, "move_story_stage", side_effect=RuntimeError("Not Authorized")):
        _go(context, story_commands.stories_move, "--story", LINEAGE, "--stage", stage)


@when('the story edge checks move the Story to "{stage}" as a dry run')
def _move_dry(context, stage):
    _go(context, story_commands.stories_move, "--story", LINEAGE, "--stage", stage, "--dry-run")


def _link_flags(label=None):
    return ["--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", *(["--author-label", label] if label else [])]


@when('the story edge checks link the Reference with the label "{label}" and the save fails')
def _link_fails(context, label):
    with mock.patch.object(story_commands, "link_reference_to_story", side_effect=RuntimeError("Not Authorized")):
        _go(context, story_commands.stories_link_reference, *_link_flags(label))


@when('a signed-in person "{name}" links the Reference with no label')
def _link_person(context, name):
    _go(context, story_commands.stories_link_reference, *_link_flags(), signed_in=True, label=name)


@when('a signed-in person "{name}" links the Reference with the label "{label}"')
def _link_person_label(context, name, label):
    _go(context, story_commands.stories_link_reference, *_link_flags(label), signed_in=True, label=name)


@when("a signed-in session that names no one links the Reference")
def _link_nobody(context):
    _go(context, story_commands.stories_link_reference, *_link_flags(), signed_in=True, label=None)


@when("an operator on the IAM lane links the Reference with no label")
def _link_iam(context):
    _go(context, story_commands.stories_link_reference, *_link_flags())


@when('an operator on the IAM lane links the Reference with the label "{label}"')
def _link_iam_label(context, label):
    _go(context, story_commands.stories_link_reference, *_link_flags(label))


@given('a person\'s note "{summary}" was saved on the Story')
def _note(context, summary):
    context.messages += 1
    context.helper.message(context.client, context.thread, context.messages, summary=summary)


@given("a deleted note was saved on the Story")
def _deleted(context):
    context.messages += 1
    context.helper.message(context.client, context.thread, context.messages, summary="Gone", deletedAt="2026-11-09T00:00:00Z")


@when("the story edge checks show the Story")
def _show(context):
    _go(context, story_commands.stories_show, "--story", LINEAGE)


def _lines(context):
    return [line.split("\t") for line in context.out.splitlines()]


@then('the output keeps its "created" line with the version record id')
def _created(context):
    assert context.failure is None, context.failure
    created = [line for line in _lines(context) if line[2:3] == ["created"]]
    assert len(created) == 1 and len(created[0]) == 4, created
    context.created = created[0][3]


@then("the output has a \"lineage\" line with the Story's lineage id")
def _lineage(context):
    lineage = [line for line in _lines(context) if line[2:3] == ["lineage"]]
    assert len(lineage) == 1 and lineage[0][:3] == ["stories", "create", "lineage"], lineage
    context.lineage = lineage[0][3]


@then('the version record id is the lineage id followed by "-v1"')
def _suffix(context):
    assert context.created == f"{context.lineage}-v1", (context.created, context.lineage)


@then("the story edge command prints no write line")
def _no_write(context):
    assert "write" not in context.out.split(), context.out
    assert all(line[-1] != "write" for line in _lines(context) if line != [""]), context.out


@then("the story edge command fails")
def _fails(context):
    assert context.failure is not None


@then("the first output line is the move's write line")
def _first_write(context):
    assert context.failure is None, context.failure
    assert context.out.splitlines()[0] == f"stories\tmove\t{LINEAGE}\treporting\twrite"


@then("the output is only the move's dry run line")
def _dry_line(context):
    assert context.out.strip() == f"stories\tmove\t{LINEAGE}\tpublished\tdry run", context.out


@then("the warning that publishing is a separate step is printed on stderr")
def _warning(context):
    assert "nothing goes live" in context.err


@then("no record is written for the story edge checks")
def _nothing_written(context):
    assert context.client.write_calls() == []


@then('the link records "{name}" as who added it')
def _added_by(context, name):
    assert context.failure is None, context.failure
    assert relation_metadata(context.client)["addedBy"] == name


@then("the story edge command printed its write line after the link was saved")
def _link_write(context):
    assert context.out.splitlines()[0] == f"stories\tlink-reference\t{LINEAGE}\t{REFERENCE}\tconsulted\twrite", context.out
    assert "SemanticRelation" in context.client.tables


@then("the command warns on stderr that the label is ignored")
def _ignored(context):
    assert "is ignored" in context.err


@then("no relation is written for the story edge checks")
def _no_relation(context):
    assert "SemanticRelation" not in context.client.tables
    assert isinstance(context.failure, OperatorError)


@then('the overview has a "message" line by "{author}" with the summary "{summary}"')
def _message_line(context, author, summary):
    rows = [line for line in _lines(context) if line[2:3] == ["message"]]
    assert any(row[4] == author and row[5] == summary for row in rows), rows


@then('the overview lists the "message" summaries "{first}", "{second}" in that order')
def _message_order(context, first, second):
    rows = [line[5] for line in _lines(context) if line[2:3] == ["message"]]
    assert rows == [first, second], rows
