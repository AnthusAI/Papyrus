"""An editor creates a Story from any Reference in one tap (features_backend/create-story-from-reference.feature). The backend is a fake."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.ideas.monitor_stories import has_based_on_story  # noqa: E402
from papyrus_content.story_from_reference import create_story_from_reference, story_rows  # noqa: E402
from papyrus_content.story_reporting import stories_based_on_reference, story_references  # noqa: E402
from test_create_story_from_reference import SOURCE_TEXT, SUMMARY, URL, backend  # noqa: E402


def held(context) -> SimpleNamespace:
    if not hasattr(context, "cs"):
        context.cs = SimpleNamespace(error=None, client=None, summary=SUMMARY, result=None, first=None, sections=(), preview=True, status="pending")
    return context.cs


def build(state):
    state.client = backend(status=state.status, preview=state.preview, sections=state.sections)


def run(state, **options):
    options = {"actor": "editor@example.test", "summary_of": lambda lineage: state.summary, "source_text_reader": lambda path: SOURCE_TEXT, "now": "2026-11-02T12:00:00Z", **options}
    return create_story_from_reference(state.client, "reference-clef-v1", **options)


def story(state):
    return state.client.get_record("Item", state.result["itemId"])


def front_of(state):
    return yaml.safe_load(json.loads(story(state)["metadata"])["frontMatterYaml"])


@given('a pending Reference "Clef decision models" from "blog.example.com" with a preview image, captured text and a generated summary')
def _background(context):
    held(context)


@given("the Reference has no generated summary")
def _no_summary(context):
    held(context).summary = ""


@given("the Reference has no preview image")
def _no_preview(context):
    held(context).preview = False


@given("the Reference is rejected")
def _rejected(context):
    held(context).status = "rejected"


@given("the Reference is accepted")
def _accepted(context):
    held(context).status = "accepted"


@given("the Reference's generated summary repeats the source's own words")
def _copies(context):
    held(context).summary = SOURCE_TEXT


@given('the site has one section "analysis"')
def _section(context):
    held(context).sections = ("analysis",)


@when("an editor creates a Story from the Reference")
def _create(context):
    state = held(context)
    build(state)
    state.result = run(state)


@given("an editor created a Story from the Reference")
def _created_before(context):
    state = held(context)
    build(state)
    state.first = run(state)


@when('an editor asks for a Story of the type "{item_type}"')
def _asks_for_type(context, item_type):
    state = held(context)
    build(state)
    try:
        run(state, item_type=item_type)
    except ValueError as error:
        state.error = str(error)


@then("no Story is made and the editor is told that type is not a Story")
def _not_a_story(context):
    state = held(context)
    assert "not a Story" in state.error and not state.client.tables.get("Item"), state.error


@when("the editor creates a Story from the Reference again")
def _again(context):
    state = held(context)
    state.result = run(state)


@when("the editor chooses to create another Story from the Reference")
def _another(context):
    state = held(context)
    state.result = run(state, again=True)


@then('a draft Story exists at the copywriting stage titled "{title}"')
def _article(context, title):
    item = story(held(context))
    assert (item["type"], item["stage"], item["title"]) == ("untyped", "copywriting", title)


@then('its body starts with the preview image credited to "{site}"')
def _image(context, site):
    body = story(held(context))["bodyMarkus"]
    assert body.startswith('::image{src="https://blog.example.com/og/clef.png"') and f'credit="Image: {site}"' in body


@then("its body then has the Reference's generated summary and a source line linking the Reference")
def _summary_and_source(context):
    body = story(held(context))["bodyMarkus"]
    assert SUMMARY in body and body.rstrip().endswith(f"Source: [Clef decision models]({URL}), Example Blog.")


@then('the Story is linked to the Reference as "based_on"')
def _linked(context):
    [link] = story_references(held(context).client, held(context).result["lineageId"])
    assert (link["referenceLineageId"], link["role"]) == ("reference-clef", "based_on")


@then("the Reference lists the Story among the stories based on it")
def _listed(context):
    assert [row["storyLineageId"] for row in stories_based_on_reference(held(context).client, "reference-clef")] == [held(context).result["lineageId"]]


@then("the Story's front matter says it was started from the Reference with its summary included")
def _front(context):
    assert front_of(held(context))["seededFrom"]["summary"] == "included" and front_of(held(context))["seededFrom"]["kind"] == "reference"


@then("the Story's front matter records the image address, its credit and the page it came from")
def _front_image(context):
    image = front_of(held(context))["seededImage"]
    assert (image["url"], image["credit"], image["page"], image["hosted"]) == ("https://blog.example.com/og/clef.png", "Image: Example Blog", URL, False)


@then("the Story's body has the source line and no other text beyond the image")
def _source_only(context):
    assert story(held(context))["bodyMarkus"].split("\n\n", 1)[1].strip() == f"Source: [Clef decision models]({URL}), Example Blog."


@then("the Story's body has no image")
def _no_image(context):
    assert "::image" not in story(held(context))["bodyMarkus"]


@then("the Story is untyped")
def _is_untyped(context):
    assert story(held(context))["type"] == "untyped"


@then("the Story is a {item_type}")
@then("the Story is an {item_type}")
def _is_type(context, item_type):
    assert story(held(context))["type"] == item_type


@then("the Reference's status is still {status}")
def _status(context, status):
    assert held(context).client.get_record("Reference", "reference-clef-v1")["curationStatus"] == status


@then("no second Story is made")
def _no_second(context):
    assert held(context).result["created"] is False and len([row for row in held(context).client.tables["Item"].values() if row.get("type") != "sub-task"]) == 1


@then("the existing Story is offered")
def _offered(context):
    assert [row["itemId"] for row in held(context).result["existing"]] == [held(context).first["itemId"]]


@then("a second Story is made with its own address")
def _second(context):
    state = held(context)
    assert state.result["created"] and state.result["itemId"] != state.first["itemId"] and len(story_rows(state.client, "reference-clef")) == 2


@then("the Story's body has no part of the source text")
def _no_source_text(context):
    assert "decision models that route" not in story(held(context))["bodyMarkus"]


@then("the Story's front matter says the summary was withheld")
def _withheld(context):
    assert front_of(held(context))["seededFrom"]["summary"] == "withheld"


@then('the Story is in the section "{section}"')
def _in_section(context, section):
    assert story(held(context))["section"] == section


@then("the idea pipeline no longer offers the Reference as a single-item idea")
def _not_offered(context):
    assert has_based_on_story(held(context).client.list_semantic_relations_by_object_state("reference#reference-clef#current"))
