from __future__ import annotations

import json
import tempfile
from pathlib import Path

from behave import given, then, when

from papyrus_content import story_commands
from papyrus_content.story_reporting import create_story
from procedures.newsroom.tests.fake_client import FakeAuthoringClient


@given('a site that offers the types "{first}" and "{second}"')
def step_site(context, first, second):
    context.client = FakeAuthoringClient()
    context.folder = Path(tempfile.mkdtemp())
    (context.folder / "projection.json").write_text(json.dumps({"storyTypes": {"default": first, "types": [first, second]}}))
    context.item = None
    context.error = None


@given('a story "{title}" with no type')
def step_untyped_story(context, title):
    context.item = create_story(context.client, title=title, section_key=None, actor="AI")


@when('an editor creates a story "{title}" with type "{story_type}"')
def step_create_typed(context, title, story_type):
    name = story_commands.chosen_story_type({"type": story_type}, static_directory=context.folder)
    context.item = create_story(context.client, title=title, section_key=None, actor="AI", item_type=name)


@when('an editor creates a story "{title}" with no type')
def step_create_untyped(context, title):
    name = story_commands.chosen_story_type({}, static_directory=context.folder)
    context.item = create_story(context.client, title=title, section_key=None, actor="AI", item_type=name)


@when('an editor asks for the type "{story_type}"')
def step_ask_type(context, story_type):
    try:
        story_commands.chosen_story_type({"type": story_type}, static_directory=context.folder)
    except ValueError as error:
        context.error = str(error)


def set_type(context, story_type):
    import os

    story_commands.create_authoring_client = lambda: (context.client, {})
    os.environ["PAPYRUS_SITE_STATIC_DIR"] = str(context.folder)
    try:
        story_commands.stories_set_type(["--story", context.item["lineageId"], "--type", story_type])
    except ValueError as error:
        context.error = str(error)


@when('an editor sets its type to "{story_type}"')
def step_set_type(context, story_type):
    set_type(context, story_type)


@when('the story is published and an editor sets its type to "{story_type}"')
def step_set_type_published(context, story_type):
    story_commands.published_story_version = lambda *_: {"id": "published"}
    set_type(context, story_type)


@then('the story is stored as a "{story_type}" with the type status "{status}"')
def step_stored(context, story_type, status):
    stored = context.client.get_record("Item", context.item["id"])
    assert stored["type"] == story_type and stored["typeStatus"] == status, stored


@then('the story is stored as an "{story_type}"')
def step_stored_untyped(context, story_type):
    assert context.client.get_record("Item", context.item["id"])["type"] == story_type


@then('the command refuses it, naming the types "{types}"')
def step_refused(context, types):
    assert context.error and types in context.error and "not one of this site's Story types" in context.error, context.error


@then("the command refuses because the story is published")
def step_refused_published(context):
    assert context.error and "is published" in context.error, context.error
