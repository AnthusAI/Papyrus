"""Steps for features_backend/stories-list-board-parity.feature. The client is an in-memory fake; nothing leaves the process."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_cli_reads as support  # noqa: E402
from papyrus_content import story_commands  # noqa: E402


def row(lineage, version, state, stage, updated):
    made = support.story(lineage, stage, updated=updated, type="article")
    made.update(id=f"{lineage}-v{version}", versionNumber=version, versionState=state, title=f"Title {lineage} v{version}")
    return made


def _use(context, *rows):
    context.client = support.Client({"Item": list(rows), "NewsroomSection": [{"id": "news", "title": "News Desk"}]})


def _list(context, *flags):
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, {})):
        context.lines = [line.split("\t") for line in support.run(story_commands.stories_list, list(flags)).splitlines()]


@given("a newsroom with a draft Story in the idea stage and a published Story")
def _(context):
    _use(context, row("fresh", 1, "draft", "idea", "2026-11-10"), row("old", 1, "current", "published", "2026-11-01"))


@given("a newsroom with a Story whose first version was replaced by a second in the reporting stage")
def _(context):
    _use(context, row("a", 1, "superseded", "reporting", "2026-11-01"), row("a", 2, "draft", "reporting", "2026-11-02"))


@given("a newsroom with a Story that has a published version and a newer draft in the same stage")
def _(context):
    _use(context, row("a", 1, "current", "copywriting", "2026-11-01"), row("a", 2, "draft", "copywriting", "2026-11-02"))


@given("a newsroom with three draft Stories in the idea stage")
def _(context):
    _use(context, *[row(name, 1, "draft", "idea", f"2026-11-0{index + 1}") for index, name in enumerate("abc")])


@when("an agent lists the Stories in the idea stage")
def _(context):
    _list(context, "--stage", "idea")


@when("an agent lists the Stories in the reporting stage")
def _(context):
    _list(context, "--stage", "reporting")


@when("an agent lists the Stories in that stage")
def _(context):
    _list(context, "--stage", "copywriting")


@when("an agent lists the Stories in the idea stage with a limit of two")
def _(context):
    _list(context, "--stage", "idea", "--limit", "2")


def _stories(context):
    return [line for line in context.lines if len(line) > 3]


@then("the draft Story is listed once")
def _(context):
    assert [line[2] for line in _stories(context)] == ["fresh"], context.lines


@then("the total says one of one")
def _(context):
    assert context.lines[-1] == ["stories", "list", "1 of 1"], context.lines


@then("the Story is listed once, as its second version")
def _(context):
    assert [(line[2], line[5]) for line in _stories(context)] == [("a", "Title a v2")], context.lines


@then("its first version is not listed")
def _(context):
    assert all(line[5] != "Title a v1" for line in _stories(context))


@then("the Story is listed once, as the newer draft")
def _(context):
    assert [(line[2], line[5]) for line in _stories(context)] == [("a", "Title a v2")], context.lines


@then("two Stories are listed and the total says two of three")
def _(context):
    assert len(_stories(context)) == 2 and context.lines[-1] == ["stories", "list", "2 of 3"], context.lines
