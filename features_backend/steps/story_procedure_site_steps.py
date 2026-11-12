"""A site's own Story procedure (features_backend/story-procedure-site.feature). The backend and the documents' files are in memory; nothing calls AWS."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines import GuidelineError, GuidelineStore  # noqa: E402

STEP_ROW_HEAD = "ModelAttachment"


class MemoryFiles:
    """The S3 side of the guideline store: the document bodies are kept here and their attachment rows in the fake backend."""

    def __init__(self, client):
        self.client = client
        self.bodies = {}

    def put(self, attachment, body):
        self.client.create_record("ModelAttachment", copy.deepcopy(attachment))
        self.bodies[attachment["storagePath"]] = bytes(body)
        return attachment

    def get(self, attachment):
        return self.bodies.get(attachment["storagePath"])


def own_step(key="label_check", stage="copywriting", **extra):
    return {"key": key, "stage": stage, "title": "Check the satire label", "role": "Editor", "note": "Confirm the satire label is on the page.", **extra}


def client_of(context):
    world = context.world
    return world.client or world.build()


def use_procedure(context, steps):
    """Saves the site's procedure document through the real store and makes the store read the same in-memory files."""
    client = client_of(context)
    files = MemoryFiles(client)
    patcher = mock.patch("papyrus_content.guidelines.store.ModelAttachmentFiles", lambda _client: files)
    patcher.start()
    context.add_cleanup(patcher.stop)
    if steps is not None:
        GuidelineStore(client, files).save("procedure", {"schemaVersion": 1, "steps": steps}, expected_current_version_id="none", actor="Ada Admin", reason="Our procedure",
                                           now="2026-11-11T10:00:00Z")
    context.site_files = files


@given("a site that saved no procedure")
def step_none(context):
    use_procedure(context, None)


@given('a site whose procedure is choose, draft, a step of its own "{key}" at the "{stage}" stage, and publish')
def step_site_procedure(context, key, stage):
    use_procedure(context, [{"key": "choose"}, {"key": "draft"}, own_step(key, stage), {"key": "publish"}])


@given('a site whose procedure makes its own step "{key}" optional')
def step_optional(context, key):
    use_procedure(context, [{"key": "choose"}, {"key": "draft"}, own_step(key, optional=True), {"key": "publish"}])


def attempt_save(context, document):
    use_procedure(context, None)
    try:
        GuidelineStore(client_of(context), context.site_files).save(
            "procedure", {"schemaVersion": 1, **document}, expected_current_version_id="none", actor="Ada Admin", reason="Try", now="2026-11-11T10:00:00Z")
        context.refusal = None
    except GuidelineError as error:
        context.refusal = str(error)


@when("an admin saves a procedure of choose and draft")
def step_no_publish(context):
    attempt_save(context, {"steps": [{"key": "choose"}, {"key": "draft"}]})


@when('an admin saves a procedure that gives the built-in step "draft" a stage')
def step_built_in_stage(context):
    attempt_save(context, {"steps": [{"key": "choose"}, {"key": "draft", "stage": "idea"}, {"key": "publish"}]})


@when("an admin saves a procedure with a step of its own that has no title")
def step_no_title(context):
    attempt_save(context, {"steps": [{"key": "choose"}, {"key": "label_check", "stage": "copywriting"}, {"key": "publish"}]})


@then('the procedure save is refused saying "{text}"')
def step_refused(context, text):
    assert context.refusal and text in context.refusal, context.refusal


@given("the Story's checklist was made by a role that could not read the site's documents")
def step_made_blind(context):
    from papyrus_content import story_checklist as checklist

    client = client_of(context)
    with mock.patch("papyrus_content.editorial_commands.read_item_check_run", lambda _item_id: None):
        checklist.sync_checklist(client, "story-1", now="2026-11-07T10:00:00.000000Z", read_procedure=False)
    names = {row["stepKey"] for row in checklist.read_steps(client, "story-1")}
    assert "review_people" in names and "label_check" not in names, names
