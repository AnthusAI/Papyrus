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


def close_required(context, *, except_keys=()):
    with evidence_patches(context):
        client = client_of(context)
        checklist.sync_checklist(client, LINEAGE, now=AT)
        for row in checklist.read_steps(client, LINEAGE):
            if row["state"] != "open" or row["stepKey"] not in checklist.required_keys() or row["stepKey"] in except_keys:
                continue
            if row["stepKey"].startswith("review_"):
                checklist.set_step(client, LINEAGE, row["stepKey"], "done", actor=EDITOR, note="Read it through.", now=AT)
            else:
                checklist.set_step(client, LINEAGE, row["stepKey"], "skipped", actor=EDITOR, reason="Covered elsewhere.", now=AT)


@given("every required step is closed")
def required_closed(context):
    close_required(context)


@given("every required step except Illustration is closed")
def required_closed_but_illustration(context):
    close_required(context, except_keys=("illustration",))


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


@then('the checklist item "{key}" has {count:d} note, the newest by the {kind} "{label}" saying "{text}"')
@then('the checklist item "{key}" has {count:d} notes, the newest by the {kind} "{label}" saying "{text}"')
def has_newest_note(context, key, count, kind, label, text):
    notes = item(context, key)["notes"]
    assert len(notes) == count and (notes[-1]["actorKind"], notes[-1]["actorLabel"], notes[-1]["text"]) == (kind, label, text), notes


@then('the checklist item "{key}" has {count:d} notes, the newest saying "{text}"')
def has_notes_newest(context, key, count, text):
    notes = item(context, key)["notes"]
    assert len(notes) == count and notes[-1]["text"] == text, notes


@then('the checklist item "{key}" has the notes in order "{first}" then "{second}"')
def notes_in_order(context, key, first, second):
    assert [note["text"] for note in item(context, key)["notes"]] == [first, second]


@when('an agent tries to add an empty note to the step "{key}"')
def agent_adds_note(context, key):
    try:
        checklist.add_note(client_of(context), lineage_of(context), key, "  ", actor={"kind": "agent", "label": "AI"})
        context.succeeded, context.error = True, None
    except Exception as error:
        context.succeeded, context.error = False, error


@given('a note "{text}" by the person "{label}" is on the step "{key}"')
def note_on_step(context, text, label, key):
    with evidence_patches(context):
        checklist.add_note(client_of(context), lineage_of(context), key, text, actor={"kind": "person", "label": label}, now=AT)


@then('the procedure output has a "note" line for "{key}" by "{who}" saying "{text}"')
def note_line(context, key, who, text):
    lines = [line.split("\t") for line in context.output.splitlines()]
    assert any(line[:3] == ["note", key, who] and line[-1] == text for line in lines), context.output


@then('the JSON checklist step "{key}" carries the note "{text}"')
def json_note(context, key, text):
    payload = json.loads(context.output)
    step = next(row for row in payload["checklist"] if row["stepKey"] == key)
    assert [note["text"] for note in step["notes"]] == [text], step


@when("the context pack layer of the procedure is read")
def read_layer(context):
    from papyrus_content.newsroom_context_pack import Situation, process_layer

    client = client_of(context)
    with evidence_patches(context):
        situation = Situation.__new__(Situation)
        situation.store, situation.lineage = client, lineage_of(context)
        entries, _problem = process_layer(situation)
    context.layer = "\n".join(entry["text"] for entry in entries)


@then('the layer says "{text}"')
def layer_says(context, text):
    assert text in context.layer, context.layer


# --- stories next: one answer (features_backend/stories-next-one-answer.feature) -------------------------------------------------

def output_lines(context) -> list[list[str]]:
    return [line.split("\t") for line in context.output.splitlines()]


def lines_of_kind(context, kind: str) -> list[list[str]]:
    return [line for line in output_lines(context) if line[:1] == [kind]]


@given("a new version of the Story is saved")
def new_version(context):
    client = client_of(context)
    previous = latest_story_version(client, LINEAGE)
    number = int(previous["versionNumber"]) + 1
    client.update_record("Item", {"id": previous["id"], "versionState": "superseded", "headStageKey": None})
    client.create_record("Item", {**previous, "id": f"{LINEAGE}-v{number}", "versionNumber": number, "versionState": "current",
                                  "headStageKey": previous["stage"], "versionCreatedAt": f"2026-11-04T09:0{number}:00Z"})   # the new row is the head
    context.world.version_number = number


@given('the step "{key}" has no recorded version')
def no_recorded_version(context, key):
    client = client_of(context)
    row = item(context, key)
    stored = client.get_record("Item", row["itemId"])
    meta = json.loads(stored["metadata"])
    meta["checklist"]["entry"].pop("storyVersion", None)
    client.update_record("Item", {"id": row["itemId"], "metadata": json.dumps(meta)})


def close_every_step(context, *, except_keys=()):
    if "illustration" not in except_keys:
        add_cover(context, "stock")   # the Illustration step closes only on a cover a person approved
    with evidence_patches(context):
        client = client_of(context)
        checklist.sync_checklist(client, LINEAGE, now=AT)
        for row in checklist.read_steps(client, LINEAGE):
            if row["state"] == "done" or row["stepKey"] in except_keys:
                continue
            checklist.set_step(client, LINEAGE, row["stepKey"], "done", actor=EDITOR, note="Done.", now=AT)


@given("every step of the Story is closed")
def every_step_closed(context):
    close_every_step(context)


@given("every step of the Story is closed except publishing")
def every_step_closed_but_publish(context):
    close_every_step(context, except_keys=("publish",))


@then('the procedure output has a "step" line for "{key}" showing "{state}"')
def step_line(context, key, state):
    assert any(line[1:3] == [key, state] for line in lines_of_kind(context, "step")), context.output


@then("every step line agrees with its item line")
def step_agrees_with_item(context):
    items = {line[1]: line[2] for line in lines_of_kind(context, "item")}
    wrong = [(line[1], line[2], items[line[1]]) for line in lines_of_kind(context, "step") if line[1] in items and line[2] != {"open": "not_done"}.get(items[line[1]], items[line[1]])]
    assert not wrong, f"{wrong}\n{context.output}"


@then('the procedure output has a "version" line for "{key}" saying "{text}"')
def version_line(context, key, text):
    assert any(line[1] == key and text in "\t".join(line[2:]) for line in lines_of_kind(context, "version")), context.output


def has_kind_line(context, kind, key):
    assert any(line[1] == key for line in lines_of_kind(context, kind)), context.output


@then('the procedure output has a "remaining" line for "{key}"')
def remaining_line(context, key):
    has_kind_line(context, "remaining", key)


@then('the procedure output has a "lens" line for "{key}"')
def lens_line(context, key):
    has_kind_line(context, "lens", key)


@then('the procedure output has a "hint" line for "{key}"')
def hint_line(context, key):
    has_kind_line(context, "hint", key)


@then('the procedure output has no "remaining" line for "{key}"')
def no_remaining_for(context, key):
    assert not any(line[1] == key for line in lines_of_kind(context, "remaining")), context.output


@then('the procedure output has no "remaining" line')
def no_remaining_line(context):
    assert not lines_of_kind(context, "remaining"), context.output


@then('the procedure output has no "lens" line')
def no_lens_line(context):
    assert not lines_of_kind(context, "lens"), context.output


@then('the procedure output has a "status" line reading "{status}"')
def status_line(context, status):
    assert [line[1] for line in lines_of_kind(context, "status")] == [status], context.output


@then('the "remaining" lines are in order "{keys}"')
def remaining_order(context, keys):
    assert [line[1] for line in lines_of_kind(context, "remaining")] == [key.strip() for key in keys.split(",")], context.output


@then('the "status" line counts as many as there are "remaining" lines')
def status_counts(context):
    assert int(lines_of_kind(context, "status")[0][2]) == len(lines_of_kind(context, "remaining")), context.output


@then('the JSON answer has the status "{status}" and lists "{key}" as stale')
def json_answer(context, status, key):
    answer = json.loads(context.output)
    assert answer["status"] == status, answer["status"]
    assert [row["key"] for row in answer["stale"]] == [key]
    assert key in [row["key"] for row in answer["remaining"]]
    row = next(row for row in answer["steps"] if row["key"] == key)
    assert row["state"] == "stale" and row["recordedVersion"] == 1 and row["freshness"].startswith("STALE"), row


@when("a finished check of the current version with no violation passes")
def check_passes(context):
    context.world.check_run = {"id": f"{LINEAGE}-v{context.world.version_number}", "lanes": {"humanus": {"status": "ran"}}, "findings": []}


# --- Illustration (features_backend/story-illustration.feature) -------------------------------------------------------------------

COVER = "assets/board/cover.png"
COVER_DARK = "assets/board/cover.dark.png"


def add_cover(context, kind: str, *, picked_by: str = "Ryan", dark: bool = False, stored: bool = True, remote: bool = False, approved: bool = True) -> None:
    """Gives the current version of the Story a cover the way the newsroom and the figures workflow do: front matter ``image``, the picture first in the body,
    and a ``MediaAsset`` row per stored picture. ``kind`` is ``stock`` (a picked stock picture: the ``coverImage`` record) or ``figure`` (a credit that says who
    approved it, and an optional dark picture)."""
    import yaml

    client = client_of(context)
    version_id = f"{LINEAGE}-v{context.world.version_number}"
    row = client.get_record("Item", version_id)
    metadata = json.loads(row["metadata"])
    front = {"title": "Board refuses", "image": ("https://example.test/cover.png" if remote else "/" + COVER)}
    attributes = f'src="{"https://example.test/cover.png" if remote else COVER}" alt="The board room"'
    if kind == "stock" and approved:
        front["coverImage"] = {"source": "wikimedia-commons", "creator": "A. Photographer", "licence": "CC BY 4.0", "srcPath": COVER,
                               "pickedAt": AT, "pickedBy": picked_by}
        attributes += ' credit="Image: A. Photographer, CC BY 4.0, via Wikimedia Commons"'
    if kind == "figure":
        attributes += f' credit="Drafted by AI. Approved by {picked_by}."' if approved else ' credit="Drafted by AI. Approved by <name>."'
        if dark:
            front["imageDark"] = "/" + COVER_DARK
            attributes += f' srcDark="{COVER_DARK}"'
    metadata["frontMatterYaml"] = yaml.safe_dump(front, sort_keys=False)
    client.update_record("Item", {"id": version_id, "metadata": json.dumps(metadata), "bodyMarkus": f"::image{{{attributes}}}\n\nFirst."})
    if stored and not remote:
        for path in [COVER, *([COVER_DARK] if dark else [])]:
            client.upsert("MediaAsset", {"id": f"media-{version_id}-{path}", "itemId": version_id, "type": "image", "role": "body", "sortKey": f"000#{path}",
                                         "alt": "The board room", "metadata": json.dumps({"srcPath": path})})


def remove_cover(context) -> None:
    client = client_of(context)
    version_id = f"{LINEAGE}-v{context.world.version_number}"
    metadata = json.loads(client.get_record("Item", version_id)["metadata"])
    metadata["frontMatterYaml"] = 'title: "Board refuses"'
    client.update_record("Item", {"id": version_id, "metadata": json.dumps(metadata), "bodyMarkus": "First."})


@given('the Story has a stock cover picked by "{name}"')
def stock_cover(context, name):
    add_cover(context, "stock", picked_by=name)


@given('the Story has a figure cover approved by "{name}"')
def figure_cover(context, name):
    add_cover(context, "figure", picked_by=name)


@given('the Story has a figure cover approved by "{name}" with a dark picture')
def figure_cover_dark(context, name):
    add_cover(context, "figure", picked_by=name, dark=True)


@given("the Story has a cover that nobody approved")
def unapproved_cover(context):
    add_cover(context, "figure", approved=False)


@given("the Story has a cover that is not a stored asset")
def unstored_cover(context):
    add_cover(context, "stock", stored=False)


@given("the Story has a remote cover address")
def remote_cover(context):
    add_cover(context, "stock", remote=True)


@given("the cover is taken off the Story in a new version")
def cover_removed_in_new_version(context):
    new_version(context)
    remove_cover(context)


@given("the site requires dark figures")
def site_requires_dark(context):
    use_policy(context, requireDark=True)


@given('the site requires a cover for "{item_type}" Stories')
def site_requires_type(context, item_type):
    use_policy(context, requiredTypes=[item_type])


def use_policy(context, **changes) -> None:
    from papyrus_content import story_illustration

    policy = {"requiredTypes": ["article"], "requireDark": False, "unreadable": False, **getattr(context, "policy", {}), **changes}
    first = not hasattr(context, "policy")
    context.policy = policy
    if first:
        patcher = patch.object(story_illustration, "read_policy", lambda _client: dict(context.policy))
        patcher.start()
        context.add_cleanup(patcher.stop)


@given('a revision of the published Story is saved at the "{stage}" stage')
def revision_of_published(context, stage):
    new_version(context)
    client_of(context).update_record("Item", {"id": f"{LINEAGE}-v{context.world.version_number}", "stage": stage, "headStageKey": stage, "status": "draft", "bodyMarkus": "Revised."})


@when('a person marks the step "{key}" done')
def person_marks_done(context, key):
    mark(context, key, "done", EDITOR)


@when('an agent marks the step "{key}" skipped with the reason "{reason}"')
def agent_marks_skipped(context, key, reason):
    mark(context, key, "skipped", {"kind": "agent", "label": "AI"}, reason=reason)


@when('a person marks the step "{key}" skipped with the reason "{reason}"')
def person_marks_skipped(context, key, reason):
    mark(context, key, "skipped", EDITOR, reason=reason)


def mark(context, key, state, actor, **fields) -> None:
    context.succeeded, context.error = True, None
    with evidence_patches(context):
        try:
            checklist.set_step(client_of(context), lineage_of(context), key, state, actor=actor, now=AT, **fields)
        except Exception as error:
            context.succeeded, context.error = False, error


@then('the stored step "{key}" is a sub-task the newsroom lists as "{title}" in position {position:d} of {total:d}')
def ui_reads_the_stored_step(context, key, title, position, total):
    """What the newsroom panel reads (lib/story-checklist.ts, storyStepsFromItems): the sub-task Item's title, state, sort order and metadata.checklist."""
    rows = [row for row in client_of(context).tables["Item"].values() if row.get("type") == "sub-task" and row.get("parentLineageId") == lineage_of(context)]
    assert len(rows) == total, len(rows)
    ordered = sorted(rows, key=lambda row: row["sortTitle"])
    keys = [json.loads(row["metadata"])["checklist"]["stepKey"] for row in ordered]
    stored = ordered[keys.index(key)]
    assert stored["title"] == title and stored["status"] in checklist.STATES, stored
    assert keys.index(key) + 1 == position, keys
