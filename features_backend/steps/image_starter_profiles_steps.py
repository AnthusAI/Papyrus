"""The draft starter profiles (features_backend/image-starter-profiles.feature). A fake backend; reads files only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.images.profile_handlers import with_client  # noqa: E402
from papyrus_content.images.visual_style import validate_profile  # noqa: E402

FOLDER = REPO_ROOT / "docs" / "examples" / "image-profiles"


@given("the draft starter profiles in the examples folder")
def step_load_drafts(context):
    context.drafts = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(FOLDER.glob("*.json"))}


@then('there is a draft for "{a}", "{b}" and "{c}"')
def step_three(context, a, b, c):
    assert sorted(context.drafts) == sorted([a, b, c])


@then("each draft says it is a draft for Ryan to correct, lists at least three open questions before anything else, and is set to review pictures after the fact")
def step_labelled(context):
    for name, draft in context.drafts.items():
        assert draft["DRAFT"].startswith("DRAFT for Ryan to correct"), name
        assert len(draft["openQuestions"]) >= 3 and list(draft)[:2] == ["DRAFT", "openQuestions"], name
        assert draft["profile"]["imageReview"] == "after_the_fact", name


@then("the profile in each draft passes the profile validator")
def step_valid(context):
    for name, draft in context.drafts.items():
        assert validate_profile(draft["profile"]) == [], name


@then("no draft has any example picture attached, only slots listed by name and note")
def step_no_pictures(context):
    for name, draft in context.drafts.items():
        assert all(definition.get("examples") == [] for definition in draft["profile"]["imageTypes"].values()), name
        assert draft["exampleSlots"] and all(item["name"] and item["note"] for slot in draft["exampleSlots"] for kind in ("exemplar", "negative") for item in slot.get(kind, [])), name


@then("the \"{name}\" draft has the image types cover-diagram, inline-diagram, cover-photo, cover-illustration, inline-illustration and social-card")
def step_types(context, name):
    assert set(context.drafts[name]["profile"]["imageTypes"]) == {"cover-diagram", "inline-diagram", "cover-photo", "cover-illustration", "inline-illustration", "social-card"}


@then("its diagram types are drawn with the figure tools and never generated, and its photograph type is stock only")
def step_sources(context):
    types = context.drafts["machines-on-machines"]["profile"]["imageTypes"]
    assert types["cover-diagram"]["sources"] == ["figure-system"] and types["inline-diagram"]["sources"] == ["figure-system"] and types["cover-photo"]["sources"] == ["stock"]


@then("its binding rule bans generated pictures that look like photographs and leaves stock photographs alone")
def step_rule(context):
    rule = context.drafts["machines-on-machines"]["profile"]["constraints"][0]
    assert rule["appliesTo"] == {"origins": ["generated"]} and "photo" in rule["prohibits"]["treatments"] and "Authentic photographs from other sources are not affected" in rule["text"]


def save_as(context, name, caller):
    return execute("image_profile_save", {"document": context.drafts[name]["profile"], "reason": "First profile", "expectedCurrentVersionId": "none"}, caller,
                   with_client(context.image_backends['ours']))


@when('an editor who is not an admin tries to save the "{name}" profile')
def step_editor_save(context, name):
    context.starter_answer = save_as(context, name, Caller(kind="person", subject="Edie Editor"))


@then("the save is refused as not authorised and nothing is stored")
def step_refused(context):
    assert context.starter_answer["error"]["code"] == "not_authorized" and context.image_backends['ours'].writes == []


@when('an admin saves the "{name}" profile')
def step_admin_save(context, name):
    context.starter_answer = save_as(context, name, Caller(kind="person", subject="Ada Admin", is_admin=True))


@then("the starter profile is saved as version {number:d}")
def step_version(context, number):
    assert context.starter_answer["ok"] and context.starter_answer["result"]["versionNumber"] == number
