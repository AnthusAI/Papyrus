"""The language checklist (features_backend/translation/translation-language-checklist.feature). Runs on the in-memory fake backend of the translation procedure's steps
and the synthetic multilingual site of translation_publishing_steps.py; nothing calls AWS or a model."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_checklist as checklist  # noqa: E402
from papyrus_content.guidelines import GuidelineStore  # noqa: E402

LINEAGE = "story-waymo--es-419"
PERSON = {"kind": "person", "label": "An Editor"}


def _rows(context) -> dict:
    return {row["stepKey"]: row for row in checklist.read_steps(context.client, LINEAGE)}


def _row(context, key: str) -> dict:
    rows = _rows(context)
    assert key in rows, f"no checklist item {key!r}; have {sorted(rows)}"
    return rows[key]


@given("the site does not require a person's review of its translations")
def step_review_optional(context):
    from story_procedure_site_steps import MemoryFiles

    files = MemoryFiles(context.client)
    patcher = mock.patch("papyrus_content.guidelines.store.ModelAttachmentFiles", lambda _client: files)
    patcher.start()
    context.add_cleanup(patcher.stop)
    document = {"schemaVersion": 1, "steps": [{"key": "review_people", "optional": True}, {"key": "publish"}]}
    GuidelineStore(context.client, files).save("procedure", document, expected_current_version_id="none", actor="Ada Admin", reason="Readers' review is optional",
                                               now="2026-11-11T10:00:00Z")
    context.client._papyrus_story_procedure = None   # the procedure is read again, not kept from before the document


@given("the translation's checklist rows are removed, as for a translation saved before language checklists")
def step_rows_removed(context):
    items = context.client.tables["Item"]
    for key in [key for key, row in items.items() if row.get("type") == "sub-task" and row.get("parentLineageId") == LINEAGE]:
        del items[key]


@given('a person records the review of the translation with the note "{note}"')
@when('a person records the review of the translation with the note "{note}"')
def step_review(context, note):
    checklist.set_step(context.client, LINEAGE, "human_review", "done", actor=PERSON, note=note)


@when('a person marks the translation\'s step "{key}" done with the note "{note}"')
def step_mark(context, key, note):
    checklist.set_step(context.client, LINEAGE, key, "done", actor=PERSON, note=note)


@then('the translation\'s checklist item "{key}" is "{state}"')
def step_state(context, key, state):
    assert _row(context, key)["state"] == state, _row(context, key)


@then('the translation\'s checklist item "{key}" is "{state}" for version {version:d}')
def step_state_for_version(context, key, state, version):
    row = _row(context, key)
    assert (row["state"], row["storyVersion"]) == (state, version), row


@then('the translation\'s checklist item "{key}" was changed by the system "{label}"')
def step_system(context, key, label):
    row = _row(context, key)
    assert (row["actorKind"], row["actorLabel"]) == ("system", label), row


@then('the translation\'s checklist item "{key}" was changed by the person "{label}"')
def step_person(context, key, label):
    row = _row(context, key)
    assert (row["actorKind"], row["actorLabel"]) == ("person", label), row


@then('the translation\'s checklist item "{key}" has evidence naming "{text}"')
def step_evidence(context, key, text):
    assert text in str(_row(context, key).get("evidence")), _row(context, key)


@then('the translation\'s checklist has no item for "{first}" or "{second}"')
def step_no_items(context, first, second):
    rows = _rows(context)
    assert first not in rows and second not in rows and rows, sorted(rows)


@then('publishing is refused naming the command "{command}"')
def step_command(context, command):
    error = context.publish_error
    assert error is not None and command in error.message, error


@given("the copy has no picture, as the English page of this site has none")
def step_copy_without_picture(context):
    context.copy["blocks"] = [block for block in context.copy["blocks"] if not block.startswith("::image")]
