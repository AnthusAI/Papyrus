"""A story based on a Reference (features_backend/story-from-reference.feature). The backend is the in-memory fake."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import items_commands  # noqa: E402
from papyrus_content.knowledge_snapshot.monitor_records import record_of  # noqa: E402
from papyrus_content.monitor_promotion import promote_record  # noqa: E402
from papyrus_content.story_from_reference import StoryCopiedFromReference, create_story_from_references, story_from_story_draft  # noqa: E402
from papyrus_content.story_reporting import link_reference_to_story, stories_based_on_reference, story_references  # noqa: E402
from procedures.newsroom.tests import test_story_from_reference as support  # noqa: E402
from procedures.newsroom.tests.test_monitor_promotion import delivered  # noqa: E402

NOW = support.NOW


def reader(path):
    return support.SOURCE_TEXT if path == "corpus/clef.txt" else ""


def state(context):
    if not hasattr(context, "sfr"):
        context.sfr = type("State", (), {"client": None, "result": None, "error": None, "item_id": None, "lineage": None, "lines": ""})()
    return context.sfr


def story_body(context) -> str:
    held = state(context)
    return held.client.get_record("Item", held.item_id)["bodyMarkus"]


@given('a Reference "{title}" from the site "{site}" with a preview image and captured text')
def step_reference(context, title, site):
    held = state(context)
    held.client = support.backend()
    held.reference = support.reference(title=title)
    assert site in held.reference["sourceUri"]


@given("the Reference is a delivered model record")
def step_record(context):
    held = state(context)
    held.client = delivered()
    [row] = held.client.list_records("Reference")
    held.reference = row
    held.client.tables["ReferenceAttachment"] = {"a-text": {"id": "a-text", "referenceId": row["id"], "referenceLineageId": row["lineageId"], "role": "extracted_text", "sortKey": "010", "storagePath": "corpus/clef.txt"}}


@when('an editor promotes the record to the section "{section}"')
def step_promote(context, section):
    held = state(context)
    [row] = held.client.list_records("Reference")
    record, _missing = record_of(row)
    held.result = promote_record(held.client, record, section=section, actor="papyrus-cli", now=NOW, source_text_reader=reader)
    held.item_id, held.lineage = held.result["itemId"], held.result["itemId"]


@given('an approved story draft that cites the Reference and says "{sentence}"')
def step_draft(context, sentence):
    held = state(context)
    held.draft = support.draft(body=f"{sentence} [1]\n\n## Source\n\n1. Clef {support.ARTICLE_URL}\n\nSection: articles. Drafted by AI.\n")


@when('the newsroom turns the story draft into a story in the section "{section}"')
def step_turn_draft(context, section):
    held = state(context)
    held.result = story_from_story_draft(held.client, held.draft, actor="papyrus-cli", section=section, source_text_reader=reader, now=NOW)
    held.item_id, held.lineage = held.result["itemId"], held.result["lineageId"]


@when("the newsroom starts an article from the Reference without a body")
def step_brief(context):
    start(context, "article", None)


@when('the newsroom starts a post from the Reference with its own body "{body}"')
def step_post(context, body):
    start(context, "post", body + "\n")


@when('the newsroom starts an article from the Reference with its own body "{body}"')
def step_article(context, body):
    start(context, "article", body + "\n")


@given('the newsroom started an article from the Reference with its own body "{body}"')
def step_started(context, body):
    start(context, "article", body + "\n")


def start(context, item_type, body):
    held = state(context)
    held.result = create_story_from_references(
        held.client, references=[held.reference], section="articles", slug="clef-" + item_type, title="Clef", actor="papyrus-cli", body_markus=body,
        item_type=item_type, source_text_reader=reader, now=NOW,
    )
    held.item_id, held.lineage = held.result["itemId"], held.result["lineageId"]


@when("the newsroom tries to start an article whose body repeats a sentence of the Reference's captured text")
def step_copy(context):
    held = state(context)
    try:
        create_story_from_references(held.client, references=[held.reference], section="articles", slug="copied", title="Clef", actor="papyrus-cli", body_markus="Our view. " + support.SOURCE_TEXT + "\n", source_text_reader=reader, now=NOW)
    except StoryCopiedFromReference as error:
        held.error = error


@when("the copywriter cites the Reference in the story")
def step_cite(context):
    held = state(context)
    link_reference_to_story(held.client, held.lineage, held.reference["id"], role="cited", actor="copywriter", citation_key="clef")


@then('the story is linked to the Reference as "{role}"')
def step_linked(context, role):
    held = state(context)
    [link] = story_references(held.client, held.lineage)
    assert (link["referenceLineageId"], link["role"]) == (held.reference["lineageId"], role), link


@then("the story is still linked to the Reference as \"{role}\"")
def step_still_linked(context, role):
    step_linked(context, role)


@then("the Reference lists that story among the stories based on it")
def step_listed(context):
    held = state(context)
    assert [row["storyLineageId"] for row in stories_based_on_reference(held.client, held.reference["lineageId"])] == [held.lineage]


@then("the story's body does not contain the Reference's captured text")
def step_not_copied(context):
    body = story_body(context)
    assert "cheapest model" not in body and "route every request" not in body, body


@then("the story is a draft at the copywriting stage")
def step_stage(context):
    item = state(context).client.get_record("Item", state(context).item_id)
    assert (item["status"], item["stage"]) == ("draft", "copywriting"), item


@then('the story\'s body starts with "{text}"')
def step_starts(context, text):
    assert story_body(context).startswith(text), story_body(context)


@then("the story's body is a brief for the copywriter that links the source")
def step_is_brief(context):
    body = story_body(context)
    assert body.startswith("Brief for the copywriter") and support.ARTICLE_URL in body, body


@then('the post\'s body starts with an image from the preview, credited to "{site}"')
def step_image(context, site):
    first = story_body(context).splitlines()[0]
    assert first.startswith('::image{src="https://blog.example.com/og/clef.png"') and f'credit="Image: {site}"' in first, first


@then("the image stays the remote preview address and is not copied into the site's media")
def step_remote(context):
    held = state(context)
    assert not held.client.tables.get("MediaAsset"), "no MediaAsset row is written"
    front = json.loads(held.client.get_record("Item", held.item_id)["metadata"])["frontMatterYaml"]
    assert "hosted: false" in front, front


@then("the story's body has no image")
def step_no_image(context):
    assert "::image" not in story_body(context)


@then("the save is refused because the body is copied from the Reference")
def step_refused(context):
    assert isinstance(state(context).error, StoryCopiedFromReference)


@then("no story and no link were written")
def step_nothing(context):
    held = state(context)
    assert not held.client.tables.get("Item") and not held.client.tables.get("SemanticRelation")


@then("the story is saved")
def step_saved(context):
    assert state(context).result["created"] is True


@given('an existing draft article "{title}" whose body links to the Reference\'s address with tracking parameters')
def step_existing(context, title):
    held = state(context)
    held.item_id = held.lineage = "item-articles-cloudflare-clef-decision-models"
    held.title = title
    support.existing_story(held.client, f"Cloudflare describes [decision models]({support.ARTICLE_URL}?utm_source=newsletter#intro) in a new post.\n")


def run_command(context, flags):
    held = state(context)
    original = items_commands.create_authoring_client
    items_commands.create_authoring_client = lambda: (held.client, {})
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            items_commands.items_link_references(flags)
    finally:
        items_commands.create_authoring_client = original
    held.lines = buffer.getvalue()


@when('the operator links references for the site "{site}" as a dry run')
def step_dry(context, site):
    run_command(context, ["--site", site, "--dry-run"])


@when('the operator links references for the site "{site}"')
def step_apply(context, site):
    run_command(context, ["--site", site])


@then('the dry run reports that "{title}" would be linked to the Reference as "{role}"')
def step_reports(context, title, role):
    held = state(context)
    assert held.title == title
    assert "would link" in held.lines and held.item_id in held.lines and f"\t{role}\t" in held.lines, held.lines


@then("the dry run wrote no link")
def step_none_written(context):
    assert not state(context).client.tables.get("SemanticRelation")


@then("running it again writes nothing new")
def step_idempotent(context):
    held = state(context)
    before = json.dumps(held.client.tables["SemanticRelation"], sort_keys=True)
    run_command(context, ["--site", "anth-us"])
    assert "0 written" in held.lines and json.dumps(held.client.tables["SemanticRelation"], sort_keys=True) == before, held.lines
