"""The Story checklist (features_backend/story-checklist.feature). Builds on the Story procedure steps: the same in-memory backend, nothing calls AWS or a model."""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_checklist as checklist  # noqa: E402
from papyrus_content.publishing import PublishError, publish_item  # noqa: E402
from papyrus_content.story_reporting import latest_story_version  # noqa: E402

LINEAGE = "story-1"
AT = "2026-11-07T10:00:00.000000Z"
EDITOR = {"kind": "person", "label": "Editor"}


def client_of(context):
    world = context.world
    return world.client or world.build()


def lineage_of(context) -> str:
    """The Story under test: story-1, or the one lineage a `stories create` just made."""
    rows = client_of(context).tables.get("Item", {}).values()
    lineages = {row["lineageId"] for row in rows}
    return LINEAGE if LINEAGE in lineages or not lineages else sorted(lineages)[0]


def evidence_patches(context) -> ExitStack:
    """What `stories next` reads outside the Items: the stored check and the research packets."""
    world = context.world
    stack = ExitStack()
    stack.enter_context(patch("papyrus_content.editorial_commands.read_item_check_run", lambda _item_id: world.check_run))
    stack.enter_context(patch("papyrus_content.assignments_workflow.load_assignment_research_packet_entries",
                              lambda _client, assignment_id: [{}] if assignment_id in world.packets else []))
    return stack


def item(context, key: str) -> dict:
    rows = {row["stepKey"]: row for row in checklist.read_steps(client_of(context), lineage_of(context))}
    assert key in rows, f"no checklist item {key!r}; have {sorted(rows)}"
    return rows[key]


@given("the Story's checklist exists")
def checklist_exists(context):
    with evidence_patches(context):
        checklist.sync_checklist(client_of(context), lineage_of(context), now=AT)
    client_of(context).calls.clear()   # the setup is not what a scenario measures


@given('the Story\'s checklist was made before the step "{key}" existed')
def checklist_without_step(context, key):
    with evidence_patches(context):
        checklist.sync_checklist(client_of(context), lineage_of(context), now=AT)
    client_of(context).delete_record("Item", f"{checklist.step_id(LINEAGE, key)}-v1")


@given('the checklist item "{key}" is marked "{state}" by the person "{label}" with the reason "{reason}"')
def item_marked(context, key, state, label, reason):
    with evidence_patches(context):
        checklist.set_step(client_of(context), lineage_of(context), key, state, actor={"kind": "person", "label": label}, reason=reason, now=AT)


@given('the review step "{key}" is done with the note "{note}"')
def review_done(context, key, note):
    with evidence_patches(context):
        checklist.set_step(client_of(context), lineage_of(context), key, "done", actor=EDITOR, note=note, now=AT)


@given('the checklist item "{key}" is reopened by a person')
def item_reopened(context, key):
    with evidence_patches(context):
        checklist.set_step(client_of(context), lineage_of(context), key, "open", actor=EDITOR, now=AT)


@given("every required step is closed")
def required_closed(context):
    with evidence_patches(context):
        client = client_of(context)
        checklist.sync_checklist(client, LINEAGE, now=AT)
        for row in checklist.read_steps(client, LINEAGE):
            if row["state"] != "open" or row["stepKey"] not in checklist.required_keys():
                continue
            if row["stepKey"].startswith("review_"):
                checklist.set_step(client, LINEAGE, row["stepKey"], "done", actor=EDITOR, note="Read it through.", now=AT)
            else:
                checklist.set_step(client, LINEAGE, row["stepKey"], "skipped", actor=EDITOR, reason="Covered elsewhere.", now=AT)


@given('the Story has the type "{item_type}"')
def story_type(context, item_type):
    client_of(context).update_record("Item", {"id": f"{LINEAGE}-v{context.world.version_number}", "type": item_type})


@when('an agent tries to reopen the step "{key}"')
def agent_reopens(context, key):
    try:
        checklist.set_step(client_of(context), lineage_of(context), key, "open", actor={"kind": "agent", "label": "AI"})
        context.succeeded, context.error = True, None
    except Exception as error:
        context.succeeded, context.error = False, error


@when("the Story is published by an editor")
def publish(context):
    client = client_of(context)
    context.publish_error = None
    with evidence_patches(context):
        try:
            publish_item(client, f"{LINEAGE}-v{context.world.version_number}", actor="editor", approved_by="editor-sub")
        except PublishError as error:
            context.publish_error = error


@when("the checklist is brought up to date after a change")
def sync_after_change(context):
    with evidence_patches(context):
        checklist.sync_checklist(client_of(context), lineage_of(context), now=AT)


@then("the Story has {count:d} checklist items")
def item_count(context, count):
    assert len(checklist.read_steps(client_of(context), lineage_of(context))) == count


@then('the checklist item "{key}" is "{state}"')
def item_state(context, key, state):
    assert item(context, key)["state"] == state, item(context, key)


@then('the checklist has no item for "{key}"')
def no_item(context, key):
    assert key not in {row["stepKey"] for row in checklist.read_steps(client_of(context), lineage_of(context))}


@then('the checklist item "{key}" was changed by the {kind} "{label}"')
def changed_by(context, key, kind, label):
    row = item(context, key)
    assert (row["actorKind"], row["actorLabel"]) == (kind, label), row


@then('the checklist item "{key}" has the reason "{reason}"')
def has_reason(context, key, reason):
    assert item(context, key)["reason"] == reason, item(context, key)


@then('the checklist item "{key}" has the note "{note}"')
def has_note(context, key, note):
    assert item(context, key)["note"] == note, item(context, key)


@then('the checklist item "{key}" has evidence naming "{text}"')
def has_evidence(context, key, text):
    assert text in (item(context, key).get("evidence") or ""), item(context, key)


@then('the checklist item "{key}" has {count:d} history entries')
def history_count(context, key, count):
    assert len(item(context, key)["history"]) == count, item(context, key)["history"]


@then('the checklist item "{key}" records a change time')
def has_time(context, key):
    assert item(context, key).get("changedAt"), item(context, key)


@then("every checklist item records template version {version:d}")
def template_version(context, version):
    rows = checklist.read_steps(client_of(context), lineage_of(context))
    assert rows and all(row["templateVersion"] == version for row in rows), rows


@then('the Story card progress reads "{text}"')
def card_progress(context, text):
    metadata = json.loads(latest_story_version(client_of(context), lineage_of(context))["metadata"])
    assert checklist.progress_text(metadata["checklist"]) == text, metadata["checklist"]


@then('the Story summary lists "{key}" among the required steps still open')
def summary_lists_open(context, key):
    metadata = json.loads(latest_story_version(client_of(context), lineage_of(context))["metadata"])
    assert key in metadata["checklist"]["requiredOpen"], metadata["checklist"]


@then('the procedure command was refused saying "{text}"')
def refused(context, text):
    assert not context.succeeded and text in str(context.error), repr(context.error)


@then('publishing was refused saying "{text}"')
def publishing_refused(context, text):
    assert context.publish_error is not None and text in str(context.publish_error), repr(context.publish_error)
    assert context.publish_error.code in ("checklist-open", "sub-task-not-publishable")


@then("publishing succeeded")
def publishing_succeeded(context):
    assert context.publish_error is None, repr(context.publish_error)
    assert client_of(context).get_record("Item", f"{LINEAGE}-v{context.world.version_number}")["status"] == "published"


@then('the procedure output has a line "{first}" "{second}" reading "{text}"')
def line_reading(context, first, second, text):
    lines = [line.split("\t") for line in context.output.splitlines()]
    assert any(line[:3] == [first, second, text] for line in lines), context.output


@then('the procedure output has an "item" line for "{key}" showing "{state}"')
def item_line(context, key, state):
    lines = [line.split("\t") for line in context.output.splitlines()]
    assert any(line[:3] == ["item", key, state] for line in lines), context.output


@then('the procedure output mentions "{text}"')
def output_mentions(context, text):
    assert text in context.output, context.output


@when('the Story is imported from "{source}"')
def imported(context, source):
    with evidence_patches(context):
        checklist.mark_imported(client_of(context), lineage_of(context), source, now=AT)


@when('the checklist step "{key}" is published as an Item')
def publish_step(context, key):
    context.publish_error = None
    try:
        publish_item(client_of(context), f"{checklist.step_id(lineage_of(context), key)}-v{len(item(context, key)['history'])}", actor="editor", approved_by="editor-sub")
    except PublishError as error:
        context.publish_error = error


@then('the checklist step "{key}" is an Item of type "{item_type}" with the parent "{parent}"')
def step_is_item(context, key, item_type, parent):
    row = client_of(context).tables["Item"][f"{checklist.step_id(lineage_of(context), key)}-v{len(item(context, key)['history'])}"]
    assert (row["type"], row["parentLineageId"]) == (item_type, parent), row


@then('the checklist step "{key}" has {count:d} versions, the newest by "{label}"')
def step_versions(context, key, count, label):
    step_lineage = checklist.step_id(lineage_of(context), key)
    versions = sorted((row for row in client_of(context).tables["Item"].values() if row.get("lineageId") == step_lineage), key=lambda row: row["versionNumber"])
    assert len(versions) == count and versions[-1]["versionCreatedBy"] == label, versions


@then("the sub-task Items have no stage, no section and no body")
def sub_tasks_plain(context):
    rows = [row for row in client_of(context).tables["Item"].values() if row.get("type") == "sub-task"]
    assert rows and all(not row.get("stage") and not row.get("section") and not row.get("sectionStatus") and not row.get("bodyMarkus") for row in rows), rows


@then("no page was published")
def nothing_published(context):
    assert not client_of(context).tables.get("PublishedItem")


@then("the Story board lists only the Story, not its sub-tasks")
def board_lists_story_only(context):
    from papyrus_content.content_item_lifecycle import CONTENT_ITEM_STAGES

    client = client_of(context)
    listed = [row for stage in CONTENT_ITEM_STAGES for row in client.list_by_index("itemsByStage", stage)]
    assert {row["lineageId"] for row in listed} == {LINEAGE} and all(row["type"] != "sub-task" for row in listed), listed
