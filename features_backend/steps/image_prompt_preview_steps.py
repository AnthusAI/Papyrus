"""The prompt preview (features_backend/image-prompt-preview.feature). An in-memory backend; no provider, no network."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.images.profile_fakes import FakeBackend  # noqa: E402
from papyrus_content.images.profile_handlers import with_client  # noqa: E402

PERSON = Caller(kind="person", subject="Edie Editor")
AGENT = Caller(kind="agent", subject="Edie Editor", delegated_by="Edie Editor")


def publication_of(context, name="ours"):
    return context.image_backends[name]


def preview(context, caller, arguments, name="ours"):
    backend = publication_of(context, name)
    context.writes_before = len(backend.writes)
    context.preview_answer = execute("image_prompt_preview", arguments, caller, with_client(backend))
    context.preview_publication = backend


def arguments_for(use, image_type, brief, *, story=None, section=None, count=None):
    arguments = {"use": use, "brief": brief}
    if image_type:
        arguments["imageType"] = image_type
    if story:
        arguments["target"] = {"kind": "story", "lineageId": story}
    if section:
        arguments["sectionId"] = section
    if count:
        arguments["count"] = count
    return arguments


def plans(context):
    assert context.preview_answer["ok"], context.preview_answer
    return context.preview_answer["result"]["plans"]


@when('a person previews a "{use}" prompt of type "{image_type}" for the Story "{story}" with the brief "{brief}"')
def step_story(context, use, image_type, story, brief):
    preview(context, PERSON, arguments_for(use, image_type, brief, story=story))


@when('a person previews a "{use}" prompt of type "{image_type}" for the section "{section}" with the brief "{brief}"')
def step_section(context, use, image_type, section, brief):
    preview(context, PERSON, arguments_for(use, image_type, brief, section=section))


@when('a person previews a "{use}" prompt of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_neither(context, use, image_type, brief):
    preview(context, PERSON, arguments_for(use, image_type, brief))


@when('a person previews a "{use}" prompt with no Story and no section with the brief "{brief}"')
def step_neither_untyped(context, use, brief):
    preview(context, PERSON, arguments_for(use, None, brief), name="plain")


@when('an agent previews a set of {count:d} "{use}" prompts of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_agent_set(context, count, use, image_type, brief):
    preview(context, AGENT, arguments_for(use, image_type, brief, count=count))


@when('a person previews a set of {count:d} "{use}" prompts of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_person_set(context, count, use, image_type, brief):
    preview(context, PERSON, arguments_for(use, image_type, brief, count=count))


@then("the preview succeeds with one plan")
def step_one_plan(context):
    assert len(plans(context)) == 1, context.preview_answer


@then("the preview succeeds with {count:d} plans")
def step_many_plans(context, count):
    assert len(plans(context)) == count, context.preview_answer


@then('the plan text starts with "{text}"')
def step_starts(context, text):
    assert plans(context)[0]["text"].startswith(text), plans(context)[0]["text"]


@then('the plan text holds "{text}"')
def step_holds(context, text):
    assert text in plans(context)[0]["text"], plans(context)[0]["text"]


@then('the plan text is only "{text}"')
def step_only(context, text):
    assert plans(context)[0]["text"] == text, plans(context)[0]["text"]


@then("the plan says the master prompt came from the publication and the subject from the request")
def step_sources(context):
    sources = {segment["slot"]: segment["source"] for segment in plans(context)[0]["segments"]}
    assert sources["style"] == "publication" and sources["subject"] == "request", sources


@then("the plan carries the field sources of the resolved guidelines")
def step_field_sources(context):
    assert plans(context)[0]["fieldSources"], plans(context)[0]


@then("the preview says the cost is not priced")
def step_unpriced(context):
    assert context.preview_answer["result"]["estimate"]["priced"] is False


@then("the preview made no records and called no provider")
def step_no_writes(context):
    assert len(context.preview_publication.writes) == context.writes_before
    assert "provider" not in context.preview_answer["result"]["capabilityCheck"]


@then("the plan is private with nothing to apply")
def step_private(context):
    assert plans(context)[0]["private"] is True


@then('the plan avoids "{item}"')
def step_avoids(context, item):
    assert item in plans(context)[0]["avoid"], plans(context)[0]["avoid"]


@then('the plan is for the image type "{image_type}"')
def step_type(context, image_type):
    assert plans(context)[0]["imageType"] == image_type


@then('the preview is refused with "{code}"')
def step_refused(context, code):
    assert context.preview_answer["ok"] is False and context.preview_answer["error"]["code"] == code, context.preview_answer


@then('the preview warns "{code}"')
def step_warns(context, code):
    assert code in [warning["code"] for warning in context.preview_answer["warnings"]], context.preview_answer["warnings"]


@then("the capability check says generation is not configured and spending is not approved")
def step_capability(context):
    check = context.preview_answer["result"]["capabilityCheck"]
    assert check["ok"] is False and check["reason"] == "generation_not_configured" and check["approvedForSpend"] is False, check
