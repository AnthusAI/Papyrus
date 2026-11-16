"""`papyrus stories measure` and the measurements `stories save-version` prints and stores (features_backend/story-measurements.feature).

The authoring backend is the in-memory fake. Humanus is the real library: it computes every number.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import humanus  # noqa: E402

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.publishing import ItemFields, save_item  # noqa: E402
from papyrus_content.story_reporting import save_story_version  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402

NOW = "2026-11-16T12:00:00Z"
FRONT = "title: Hello\n"


def lineage(context) -> str:
    return f"story-{context.slug}"


@given('a story "{slug}" in English with a first version:')
def step_story(context, slug):
    context.slug = slug
    context.client = FakeAuthoringClient()
    context.client.endpoint = "https://example.test/graphql"
    context.tmp = tempfile.mkdtemp(prefix="story-measure-")
    context.tmp_dirs.append(context.tmp)
    context.first_body = context.text
    context.front_text = None
    context.draft_text = None
    save_item(
        context.client,
        ItemFields(type="article", slug=slug, section="articles", front_matter_yaml=FRONT, body_markus=context.text, aliases=[], id=f"{lineage(context)}-v1"),
        actor="t", now=NOW,
    )
    context.client.update_record("Item", {"id": f"{lineage(context)}-v1", "lineageId": lineage(context), "versionNumber": 1, "versionState": "current"})


@given("a draft text to measure:")
def step_draft(context):
    context.draft_text = context.text


@given("the draft has the front matter:")
def step_front(context):
    context.front_text = context.text


@given("the story has a second saved version with more words")
def step_second_version(context):
    save_story_version(context.client, lineage(context), front_matter_yaml=FRONT, body_markus=context.first_body + "\n\nAnd a good many more words follow here.\n",
                       actor="t", change_reason="more", now=NOW)


@given("the story's current version carries measurements")
def step_carries(context):
    from papyrus_content.story_measure import story_measurements

    save_story_version(context.client, lineage(context), front_matter_yaml=FRONT, body_markus="Second.\n", actor="t", change_reason="second", now=NOW,
                       measurements=story_measurements("Second.\n", FRONT, "en"))
    assert "measurements" in json.loads(current(context)["metadata"])


def current(context) -> dict:
    rows = [row for row in context.client.tables["Item"].values() if row.get("type") != "sub-task" and row.get("versionState") == "current"]
    return sorted(rows, key=lambda row: int(row["versionNumber"]))[-1]


def run(context, function, flags: list[str], files: dict[str, str] | None = None) -> None:
    patches = [
        mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}),
        mock.patch.object(story_commands, "create_authoring_client", lambda: (context.client, {})),
    ]
    output, error = io.StringIO(), None
    context.before_rows = json.dumps(context.client.tables, sort_keys=True, default=str)
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        with contextlib.redirect_stdout(output):
            try:
                function(flags)
            except ValueError as raised:
                error = str(raised)
    context.result = {"output": output.getvalue(), "error": error}


def draft_flags(context) -> list[str]:
    body = Path(context.tmp) / "draft.md"
    body.write_text(context.draft_text, encoding="utf-8")
    flags = ["--body-file", str(body)]
    if context.front_text is not None:
        front = Path(context.tmp) / "front.yml"
        front.write_text(context.front_text, encoding="utf-8")
        flags += ["--front-matter-file", str(front)]
    return flags


@when("the draft is measured for the story")
def step_measure_draft(context):
    run(context, story_commands.stories_measure, ["--story", lineage(context), *draft_flags(context)])


@when("the story is measured")
def step_measure_story(context):
    run(context, story_commands.stories_measure, ["--story", lineage(context)])


@when("the story is measured as JSON")
def step_measure_json(context):
    run(context, story_commands.stories_measure, ["--story", lineage(context), "--json"])


@when("the draft is measured without a story or a language")
def step_measure_no_language(context):
    run(context, story_commands.stories_measure, draft_flags(context))


@when('the draft is measured in "{tag}" without a story')
def step_measure_language(context, tag):
    run(context, story_commands.stories_measure, [*draft_flags(context), "--language", tag])


def save_flags(context, *extra: str) -> list[str]:
    return ["--story", lineage(context), *draft_flags(context), "--reason", "measure", "--author-label", "t", "--no-check", *extra]


@when("the draft is saved as the next version")
def step_save(context):
    run(context, story_commands.stories_save_version, save_flags(context))


@when("the draft is saved as the next version as a dry run")
def step_save_dry(context):
    run(context, story_commands.stories_save_version, save_flags(context, "--dry-run"))


@when("another version is saved by a path that records none")
def step_other_path(context):
    save_story_version(context.client, lineage(context), front_matter_yaml=FRONT, body_markus="Third.\n", actor="t", change_reason="third", now=NOW)


def rows(context, kind: str) -> list[list[str]]:
    assert context.result["error"] is None, context.result["error"]
    return [line.split("\t") for line in context.result["output"].splitlines() if f"\t{kind}\t" in line or line.split("\t")[3:4] == [kind]]


def row(context, kind: str) -> dict[str, str]:
    found = [r for r in rows(context, kind) if kind in r]
    assert found, context.result["output"]
    return dict(item.split("=", 1) for item in found[0] if "=" in item)


@then("the output shows the size in words")
def step_size_words(context):
    assert row(context, "size")["unit"] == "word"


@then("the output shows the size in characters")
def step_size_characters(context):
    size = row(context, "size")
    assert size["unit"] == "character" and size["units"] == "12", size


@then("the output shows {sections:d} section and {paragraphs:d} paragraphs")
def step_structure(context, sections, paragraphs):
    structure = row(context, "structure")
    assert (structure["sections"], structure["paragraphs"]) == (str(sections), str(paragraphs)), structure


@then("the output shows {links:d} link and no citations")
def step_sourcing(context, links):
    sourcing = row(context, "sourcing")
    assert (sourcing["links"], sourcing["citations"]) == (str(links), "0"), sourcing


@then("the output shows the change against version {number:d}")
def step_change(context, number):
    assert rows(context, "change"), context.result["output"]
    change = [r for r in rows(context, "change")][0]
    assert f"vs version {number}" in change, change
    assert float(row(context, "change")["shareChanged"]) > 0


@then("the output shows no change")
def step_no_change(context):
    assert not rows(context, "change"), context.result["output"]


@then("the measurement is refused asking for --language")
def step_refused(context):
    assert context.result["error"] and "--language" in context.result["error"], context.result


@then("the output shows the headline present, the dek present and the blurb absent")
def step_headline_dek_blurb(context):
    structure = row(context, "structure")
    assert structure["headline"].startswith("present") and structure["dek"].startswith("present") and structure["blurb"] == "absent", structure


@then("the JSON has the size, structure and sourcing measurements and the Humanus version")
def step_json(context):
    payload = json.loads(context.result["output"])
    assert set(payload["measure"]) >= {"size", "structure", "sourcing"}
    assert payload["humanusVersion"] == humanus.__version__


@then("the version is saved with its measurements")
def step_save_succeeds(context):
    assert context.result["error"] is None, context.result["error"]
    assert "\tsaved\t" in context.result["output"], context.result["output"]


@then("the new version record stores the same measurements and the change against version 1")
def step_stored(context):
    stored = json.loads(current(context)["metadata"])["measurements"]
    assert stored["measure"]["size"]["unit"] == "word"
    assert stored["changeFromPrevious"]["version"] == 1 and stored["changeFromPrevious"]["shareChanged"] > 0
    printed = row(context, "size")
    assert printed["units"] == str(stored["measure"]["size"]["units"])
    assert stored["humanusVersion"] == humanus.__version__


@then("the new version record stores no measurements")
def step_stored_none(context):
    assert "measurements" not in json.loads(current(context)["metadata"])


@then("the measuring wrote nothing to the backend")
def step_nothing_written(context):
    assert json.dumps(context.client.tables, sort_keys=True, default=str) == context.before_rows


@then("the output is the dry-run line only")
def step_dry_run_only(context):
    assert context.result["error"] is None, context.result["error"]
    assert context.result["output"].strip().endswith("dry run") and "\tsize\t" not in context.result["output"], context.result["output"]
