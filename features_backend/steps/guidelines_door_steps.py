"""The guidelines door and command line (features_backend/guidelines-door.feature, guidelines-cli.feature). An in-memory backend and files; no network."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines import operations_test as ops  # noqa: E402
from papyrus_content.guidelines.operations_test import (ADMIN, EDITOR, NAMES, READER, VIDEO, WRITING, COMMANDS, created, door, read, run, save, world)  # noqa: E402
from papyrus_content.guidelines.s3_files import PAYLOAD_PREFIX, S3DocumentFiles  # noqa: E402
from papyrus_content.images import generate, mcp  # noqa: E402
from papyrus_content.images.profile_fakes import FakeBackend as ImageBackend, profile_copy  # noqa: E402


# --- the door -----------------------------------------------------------------------------------------------------------------------------------

@given("a door onto a publication with no guidelines")
def step_no_guidelines(context):
    context.backend, context.files = world(saved=False)


@given("a door onto a publication with saved writing guidelines")
@given("a command line onto a publication with saved writing guidelines")
def step_saved(context):
    context.backend, context.files = world()


@when('an admin saves writing guidelines naming "none" as the version they replace, with the reason "{reason}"')
def step_first_save(context, reason):
    context.answer = save(context.backend, ADMIN, WRITING, reason=reason, guard="none", request="first")


@then("the door answers with version 1 of the writing guidelines")
def step_version_one(context):
    assert context.answer["ok"] and context.answer["result"]["versionNumber"] == 1 and context.answer["result"]["kind"] == "writing", context.answer


@then('the version records "{name}" as the person who saved it')
def step_recorded(context, name):
    assert context.backend.items[0]["versionCreatedBy"] == name


@then("the catalog row holds no text and the document is stored as one file")
def step_catalog(context):
    row = context.backend.items[0]
    assert row["bodyMarkus"] == "" and row["body"] == [] and len(context.backend.bodies) == 1 and len(context.backend.attachments) == 1
    assert row["slug"] == "editorial-doctrine-writing"


@then("an editor reading the writing guidelines gets the document that was saved")
def step_editor_reads_saved(context):
    assert read(context.backend)["result"]["document"] == WRITING


@when("an editor reads the writing guidelines through the door")
def step_editor_reads(context):
    context.answer = read(context.backend)


@then("the door answers with the saved document")
def step_saved_document(context):
    assert context.answer["ok"] and context.answer["result"]["document"] == WRITING


@when("an editor tries to save a change to the audience")
def step_editor_saves(context):
    context.before = created(context.backend)
    context.answer = save(context.backend, EDITOR, {**WRITING, "audience": "Engineers"}, request="editor")


@then("the door answers that the caller is not authorised and nothing new is stored")
def step_not_authorised(context):
    assert context.answer["error"]["code"] == "not_authorized" and created(context.backend) == context.before


@when("an editor sends a save that claims to come from an admin")
def step_spoof(context):
    context.answer = door(context.backend, "guidelinesWrite", EDITOR, "guidelines_save", requestId="spoof",
                          input={"kind": "writing", "document": WRITING, "reason": "x", "expectedCurrentVersionId": "none", "isAdmin": True})


@then("the door refuses the request because the input has no such property")
def step_no_such_property(context):
    assert context.answer["error"]["code"] == "invalid_input" and context.answer["error"]["details"]["path"] == "isAdmin"


@then("a signed-in reader is not admitted to either door")
def step_reader(context):
    assert door(context.backend, "guidelinesRead", READER, "guidelines_get", input={"kind": "writing"})["error"]["code"] == "not_authorized"
    assert door(context.backend, "guidelinesWrite", READER, "guidelines_save", requestId="r", input={})["error"]["code"] == "not_authorized"


@when("an agent in an admin's session asks to drop the writing binding constraint")
def step_agent_drops(context):
    context.before = created(context.backend)
    context.answer = save(context.backend, ADMIN, {**WRITING, "constraints": []}, request="agent-drop", actorKind="agent")


@then("the guidelines door answers that a person is required and nothing new is stored")
def step_person_required(context):
    assert context.answer["error"]["code"] == "human_required" and created(context.backend) == context.before


@when("that agent changes only the tone")
def step_agent_tone(context):
    context.answer = save(context.backend, ADMIN, {**WRITING, "tone": ["Plain."]}, request="agent-tone", actorKind="agent")


@then("the door saves version 2 and the history says an agent saved it")
def step_agent_saved(context):
    assert context.answer["ok"] and context.answer["result"]["versionNumber"] == 2
    history = door(context.backend, "guidelinesRead", EDITOR, "guidelines_history", input={"kind": "writing"})["result"]["versions"]
    assert history[0]["byKind"] == "agent"


@when("an admin who is a person drops the binding constraint")
def step_person_drops(context):
    context.answer = save(context.backend, ADMIN, {**WRITING, "tone": ["Plain."], "constraints": []}, request="person-drop")


@then("the door saves version 3")
def step_version_three(context):
    assert context.answer["ok"] and context.answer["result"]["versionNumber"] == 3


@when("an admin saves an audience change twice with the same request id")
def step_twice(context):
    context.guard = read(context.backend)["result"]["expectedCurrentVersionId"]
    context.change = {**WRITING, "audience": "Engineers"}
    context.first = save(context.backend, ADMIN, context.change, guard=context.guard, request="same")
    context.second = save(context.backend, ADMIN, context.change, guard=context.guard, request="same")


@then("both guideline answers name version 2 and only one new version was stored")
def step_both(context):
    assert context.first["result"]["versionNumber"] == 2 == context.second["result"]["versionNumber"] and created(context.backend) == 2


@then("the same guideline change with a different request id is refused as stale")
def step_stale_other(context):
    assert save(context.backend, ADMIN, context.change, guard=context.guard, request="other")["error"]["code"] == "stale_version"


@when("an editor tries to save guidelines through the read door")
def step_save_read_door(context):
    context.answer = door(context.backend, "guidelinesRead", EDITOR, "guidelines_save", input={})


@when("an admin tries to read guidelines through the write door")
def step_read_write_door(context):
    context.answer = door(context.backend, "guidelinesWrite", ADMIN, "guidelines_get", requestId="r", input={"kind": "writing"})


@when("an editor asks the image door for guidelines")
def step_image_door(context):
    context.answer = door(context.backend, "imageRead", EDITOR, "guidelines_get", input={"kind": "writing"})


@when("an editor asks the guidelines door for an image operation")
def step_guidelines_door_image(context):
    context.answer = door(context.backend, "guidelinesRead", EDITOR, "image_profile_get")


@then("the guidelines door says to use {name}")
def step_use(context, name):
    assert context.answer["error"]["code"] == "invalid_input" and name in context.answer["error"]["message"], context.answer


@when("an admin saves naming a version that is no longer current")
def step_stale(context):
    context.before = created(context.backend)
    context.answer = save(context.backend, ADMIN, {**WRITING, "audience": "X"}, guard="item-editorial-doctrine-writing-v0", request="stale")


@then("the door answers that the guidelines have changed and nothing new is stored")
def step_changed(context):
    assert context.answer["error"]["code"] == "stale_version" and created(context.backend) == context.before


@when('an admin saves a document with an empty tone sentence and an unknown field "{field}"')
def step_invalid(context, field):
    context.answer = save(context.backend, ADMIN, {"schemaVersion": 1, "tone": ["ok", ""], field: 1}, request="invalid")


@then('the door lists the problems on the fields "{first}" and "{second}" and nothing new is stored')
def step_problems(context, first, second):
    assert context.answer["error"]["code"] == "invalid_input"
    assert {p["path"] for p in context.answer["error"]["details"]["problems"]} == {first, second} and created(context.backend) == context.before


@when("an admin saves the document that is already current")
def step_unchanged(context):
    context.answer = save(context.backend, ADMIN, WRITING, request="unchanged")


@then("the door answers that nothing changed and the guidelines stay at version 1")
def step_unchanged_answer(context):
    assert context.answer["ok"] and context.answer["result"]["unchanged"] is True and context.answer["result"]["versionNumber"] == 1
    assert created(context.backend) == context.before


@when('an admin saves video guidelines naming "none" as the version they replace')
def step_video(context):
    context.answer = save(context.backend, ADMIN, VIDEO, kind="video", guard="none", request="video")
    assert context.answer["ok"], context.answer


@then("an editor reading the video guidelines gets the saved document")
def step_video_read(context):
    assert read(context.backend, kind="video")["result"]["document"] == VIDEO


@when('an editor reads guidelines of the kind "{kind}"')
def step_unknown_kind(context, kind):
    context.answer = read(context.backend, kind=kind)


@then('the door answers that the kind is unknown and the known kinds include "{a}", "{b}" and "{c}"')
def step_lists_kinds(context, a, b, c):
    assert context.answer["error"]["code"] == "unknown_kind" and {a, b, c} <= set(context.answer["error"]["details"]["kinds"])


@given('a section "{section}" with its own tone and audience')
def step_section(context, section):
    document = {"schemaVersion": 1, "tone": ["Dry."], "audience": "Specialists"}
    answer = save(context.backend, ADMIN, document, section=section, guard="none", request="section")
    assert answer["ok"], answer


@when('an editor resolves the writing guidelines for the section "{section}"')
def step_resolve_section(context, section):
    context.answer = door(context.backend, "guidelinesRead", EDITOR, "guidelines_resolve", input={"kind": "writing", "section": section})


@then("the tone has the publication's sentence and then the section's")
def step_tone(context):
    assert context.answer["result"]["document"]["tone"] == ["Warm and plain.", "Dry."]


@then("the field sources differ for the tone and the binding constraints")
def step_sources(context):
    sources = context.answer["result"]["fieldSources"]
    assert sources["tone"] != sources["constraints"], sources


@given("a guidelines door onto a publication with a saved style profile")
def step_profile(context):
    context.backend = ImageBackend("ours", profile=profile_copy())


@when("an editor reads the image guidelines through the guidelines door")
def step_image_read(context):
    context.answer = door(context.backend, "guidelinesRead", EDITOR, "guidelines_get", input={"kind": "image"})


@then("the door answers with the style profile as the document")
def step_profile_document(context):
    result = context.answer["result"]
    assert context.answer["ok"] and result["kind"] == "image" and result["document"]["schemaVersion"] == 2 and result["profile"] == result["document"]


@then("resolving image guidelines gives the layered profile")
def step_image_resolve(context):
    answer = door(context.backend, "guidelinesRead", EDITOR, "guidelines_resolve", input={"kind": "image"})
    assert answer["ok"] and answer["result"]["found"] and answer["result"]["kind"] == "image" and answer["result"]["document"]["schemaVersion"] == 2, answer


@given("the door's S3 files")
def step_s3(context):
    context.models, context.s3 = [], ops.FakeS3()
    backend = ops.FakeBackend(publication="ours")
    backend.create_record = lambda model, record: context.models.append((model, record["storagePath"]))
    context.s3_files = S3DocumentFiles(backend, bucket="bucket", s3=context.s3)
    context.attachment = {"id": "a", "storagePath": PAYLOAD_PREFIX + "item-x/doctrine-document/guidelines.json", "mediaType": "application/json"}


@when("a guideline file is written and read back")
def step_file(context):
    context.s3_files.put(context.attachment, b"{}")
    context.read_back = context.s3_files.get(context.attachment)


@then("the object and the attachment row are written under the item payload prefix")
def step_prefix(context):
    path = context.attachment["storagePath"]
    assert context.read_back == b"{}" and context.s3.calls[0] == ("put", path) and context.models == [("ModelAttachment", path)]
    assert path.startswith("newsroom/payloads/item/")


@then("a path outside that prefix is refused before S3 is asked")
def step_outside(context):
    before = list(context.s3.calls)
    for path in ("newsroom/payloads/reference/x.json", PAYLOAD_PREFIX + "../story/x.json"):
        try:
            context.s3_files.put({**context.attachment, "storagePath": path}, b"{}")
        except ValueError:
            continue
        raise AssertionError(path)
    assert context.s3.calls == before


# --- the command line ---------------------------------------------------------------------------------------------------------------------------

def write_document(context, document):
    import tempfile

    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    handle.write(json.dumps(document))
    handle.close()
    return handle.name


def guard(context):
    return read(context.backend)["result"]["expectedCurrentVersionId"]


def save_args(context, document, *, extra=()):
    return ["save", "--kind", "writing", "--file", write_document(context, document), "--reason", "Narrowed", "--expected-current-version-id", guard(context), *extra]


@when("an admin runs save with a changed audience and --dry-run")
def step_dry(context):
    context.before = created(context.backend)
    context.document = {**WRITING, "audience": "Engineers"}
    context.status, context.answer = run(context.backend, context.files, save_args(context, context.document, extra=["--dry-run"]))


@then("the answer is a dry run that previews the audience change and nothing new is stored")
def step_dry_answer(context):
    result = context.answer["result"]
    assert context.status == 0 and result["dryRun"] is True
    assert result["preview"]["changes"] == [{"path": "audience", "from": "General readers", "to": "Engineers"}]
    assert created(context.backend) == context.before


@when("the admin runs the same save without --dry-run")
def step_real(context):
    context.status, context.answer = run(context.backend, context.files, save_args(context, context.document))


@then('the saved writing guidelines are at version 2 with the audience "{audience}"')
def step_v2(context, audience):
    assert context.status == 0 and context.answer["result"]["versionNumber"] == 2
    assert read(context.backend)["result"]["document"]["audience"] == audience


@when("an admin runs diff with a changed tone and a removed binding constraint")
def step_diff(context):
    context.before, context.writes = created(context.backend), len(context.backend.writes)
    path = write_document(context, {**WRITING, "tone": ["Brisk."], "constraints": []})
    context.status, context.answer = run(context.backend, context.files, ["diff", "--kind", "writing", "--file", path])


@then("the answer lists the tone change and the removed constraint")
def step_diff_answer(context):
    result = context.answer["result"]
    assert {change["path"] for change in result["changes"]} == {"tone", "constraints"} and result["constraintChanges"][0]["change"] == "removed"


@then("no new guideline version is stored")
def step_nothing(context):
    assert created(context.backend) == context.before and len(context.backend.writes) == getattr(context, "writes", len(context.backend.writes))


@when('an admin runs resolve for the section "{section}"')
def step_cli_resolve(context, section):
    context.status, context.answer = run(context.backend, context.files, ["resolve", "--kind", "writing", "--section", section])


@then("every field in the answer names the layer it came from")
def step_every_field(context):
    result = context.answer["result"]
    assert set(result["fieldSources"]) == {name for name in result["document"]}, result


@then("the answer names both layers with their versions")
def step_layers(context):
    layers = context.answer["result"]["layers"]
    assert [(layer["scope"], layer["versionNumber"]) for layer in layers] == [("publication", 1), ("section", 1)]


@when("an admin runs show for the writing guidelines")
def step_show(context):
    context.status, context.answer = run(context.backend, context.files, ["show", "--kind", "writing"])


@then("the answer holds the document and the version id to pass as the version being replaced")
def step_show_answer(context):
    result = context.answer["result"]
    assert result["document"] == WRITING and result["expectedCurrentVersionId"] == result["itemId"]


@when("an admin runs show for the video guidelines")
def step_show_video(context):
    context.status, context.answer = run(context.backend, context.files, ["show", "--kind", "video"])


@then('the answer says there are none and that the first save passes "{value}"')
def step_none(context, value):
    assert context.status == 2 and context.answer["error"]["code"] == "not_found" and context.answer["error"]["details"]["expectedCurrentVersionId"] == value


@when("an editor runs save")
def step_cli_editor(context):
    context.status, context.answer = run(context.backend, context.files, save_args(context, {**WRITING, "audience": "Engineers"}), admin=False)


@then("the command fails because the caller is not authorised")
def step_cli_not_authorised(context):
    assert context.status == 2 and context.answer["error"]["code"] == "not_authorized"


@when("an agent in an admin's session runs save dropping the binding constraint")
def step_cli_agent(context):
    context.before = created(context.backend)
    context.status, context.answer = run(context.backend, context.files, save_args(context, {**WRITING, "constraints": []}), environ={"PAPYRUS_ACTOR_KIND": "agent"})


@then("the command fails because a person is required and nothing new is stored")
def step_cli_person(context):
    assert context.status == 2 and context.answer["error"]["code"] == "human_required" and created(context.backend) == context.before


@then("the guideline commands, the MCP tools and the TypeScript types list the same five operations in the same order")
def step_same_five(context):
    import re

    assert [entry["op"] for entry in COMMANDS] == NAMES and len(NAMES) == 5
    assert [name for name in mcp.image_tools() if name.startswith("guidelines_")] == NAMES
    assert re.findall(r"^  (guidelines_[a-z_]+): \{ input:", generate.TS_TYPES.read_text(encoding="utf-8"), re.M) == NAMES


@then("the generated files are current")
def step_generated_current(context):
    assert generate.stale() == []


@then("the CLI and the MCP tool print identical JSON for each guideline operation")
def step_identical(context):
    import pathlib
    import tempfile

    for item in ops.GUIDELINES:
        ops.test_every_example_fits_its_schemas_and_the_cli_and_the_mcp_tool_give_identical_json(item, pathlib.Path(tempfile.mkdtemp()))


@when('an agent runs "papyrus guidelines save --help" with no site and no sign-in')
def step_help(context):
    from papyrus import cli

    opened = []
    out, err = io.StringIO(), io.StringIO()
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("PAPYRUS_", "AWS_"))}
    with patch.dict(os.environ, environment, clear=True), patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=lambda *a, **k: opened.append(1)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            context.status = cli.main(["guidelines", "save", "--help"])
        except SystemExit as stop:
            context.status = int(stop.code or 0)
    context.help_output, context.opened = out.getvalue(), opened


@then('the printed usage shows "{flag}" and says the command writes by default')
def step_help_text(context, flag):
    assert context.status == 0 and flag in context.help_output and "yes, by default" in context.help_output, context.help_output


@then("no connection to a site was opened")
def step_no_connection(context):
    assert context.opened == []
