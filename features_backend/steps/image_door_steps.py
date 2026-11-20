"""The image-service door (features_backend/image-door.feature). A fake backend; no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.image_service import handle  # noqa: E402
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy  # noqa: E402

READER = {"claims": {"name": "Rae Reader"}, "groups": []}
EDITOR = {"claims": {"name": "Edie Editor"}, "groups": ["editor"]}
ADMIN = {"claims": {"name": "Ada Admin"}, "groups": ["admin"]}


def knock(context, door, identity, **arguments):
    if "input" in arguments:
        arguments["input"] = json.dumps(arguments["input"])
    context.door_answer = handle({"fieldName": door, "identity": identity, "arguments": arguments}, client_factory=lambda: context.door_backend, files_factory=lambda built: built.document_files)
    return context.door_answer


def guard(context):
    return knock(context, "imageRead", EDITOR, op="image_profile_get")["result"]["itemId"]


def created(context):
    return len([write for write in context.door_backend.writes if write[0] == "create"])


@given("a door onto a publication with a saved style profile")
def step_door(context):
    context.door_backend = FakeBackend("ours", profile=profile_copy())
    context.door_backend.add_story("story-1", section="security")


@when("a signed-in reader reads the profile through the door")
def step_reader(context):
    knock(context, "imageRead", READER, op="image_profile_get")


@then("the door answers that the caller is not authorised")
def step_not_authorised(context):
    assert context.door_answer["error"]["code"] == "not_authorized", context.door_answer


@when("an editor reads the profile through the door")
def step_editor_reads(context):
    knock(context, "imageRead", EDITOR, op="image_profile_get")


@then("the door answers with the profile")
def step_profile(context):
    assert context.door_answer["ok"] and context.door_answer["result"]["profile"]["schemaVersion"] == 2 and context.door_answer["publication"] == "ours"


@when("an editor tries to save through the read door")
def step_save_read(context):
    knock(context, "imageRead", EDITOR, op="image_profile_save", input={})


@then("the door says to use imageWrite")
def step_use_write(context):
    assert context.door_answer["error"]["code"] == "invalid_input" and "imageWrite" in context.door_answer["error"]["message"]


@when("an editor tries to read through the write door")
def step_read_write(context):
    knock(context, "imageWrite", EDITOR, op="image_profile_get", requestId="r1")


@then("the door says to use imageRead")
def step_use_read(context):
    assert context.door_answer["error"]["code"] == "invalid_input" and "imageRead" in context.door_answer["error"]["message"]


def drop_constraint(context, identity, **extra):
    knock(context, "imageWrite", identity, op="image_profile_save", requestId=f"drop-{identity['claims']['name']}",
          input={"document": {"constraints": []}, "reason": "Drop the rule", "expectedCurrentVersionId": guard(context)}, **extra)


@when("an editor asks to drop the binding constraint through the write door")
def step_editor_drops(context):
    drop_constraint(context, EDITOR)


@then("the door answers that the caller is not authorised and nothing is stored")
def step_not_authorised_nothing(context):
    assert context.door_answer["error"]["code"] == "not_authorized" and created(context) == 1


@when("an admin asks to drop the binding constraint through the write door")
def step_admin_drops(context):
    drop_constraint(context, ADMIN)


@then("the profile behind the door is at version 2 with no constraints")
def step_version_two(context):
    result = knock(context, "imageRead", EDITOR, op="image_profile_get")["result"]
    assert result["versionNumber"] == 2 and result["profile"]["constraints"] == []


@then("the new version records the admin's name")
def step_admin_name(context):
    assert knock(context, "imageRead", EDITOR, op="image_profile_history")["result"]["versions"][0]["by"] == "Ada Admin"


@when("an admin who declares themselves an agent asks to drop the binding constraint")
def step_agent_admin(context):
    drop_constraint(context, ADMIN, actorKind="agent")


@then("the door answers that a person is required and nothing is stored")
def step_person_required(context):
    assert context.door_answer["error"]["code"] == "human_required" and created(context) == 1


@when("an editor saves a mood change twice with the same request id")
def step_twice(context):
    body = {"document": {"identity": {"mood": ["calm", "dry"]}}, "reason": "Mood", "expectedCurrentVersionId": guard(context)}
    context.first = knock(context, "imageWrite", EDITOR, op="image_profile_save", requestId="same", input=body)
    context.second = knock(context, "imageWrite", EDITOR, op="image_profile_save", requestId="same", input=body)
    context.body = body


@then("both answers name version 2 and only one new version was stored")
def step_both(context):
    assert context.first["result"]["versionNumber"] == 2 == context.second["result"]["versionNumber"] and created(context) == 2


@then("the same change with a different request id is refused as stale")
def step_stale(context):
    answer = knock(context, "imageWrite", EDITOR, op="image_profile_save", requestId="another", input=context.body)
    assert answer["error"]["code"] == "stale_version"


@given('the section "{section}" avoids "{item}" in its own style')
def step_section(context, section, item):
    context.door_backend.add_section(section, visualStyle=json.dumps({"avoid": [item]}))


@when('an editor resolves a cover for a Story in the section "{section}" through the door')
def step_resolve(context, section):
    knock(context, "imageRead", EDITOR, op="image_profile_resolve",
          input={"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "imageType": "cover-illustration"})


@then('the answer through the door avoids "{item}"')
def step_avoid(context, item):
    assert item in context.door_answer["result"]["effective"]["avoid"], context.door_answer
