"""The reviewer on the published record (features_backend/stories/published-reviewer.feature). The Story world is story_procedure_steps.py's and the translation
world is translation_publishing_steps.py's; nothing calls AWS or a model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.source import summary_from_row  # noqa: E402
from papyrus_content.published_reviewer import REVIEWED_BY_KEY  # noqa: E402
from papyrus_content.publishing import PublishError, publish_item, published_item_id_for  # noqa: E402
from papyrus_content.story_reporting import latest_story_version  # noqa: E402
from story_checklist_steps import evidence_patches  # noqa: E402

SIGNED_IN_SUB = "4a1b2c3d-0000-4000-8000-000000000001"


def _content_actions_handler():
    import importlib.util

    spec = importlib.util.spec_from_file_location("content_actions_handler", REPO_ROOT / "amplify" / "functions" / "content-actions" / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@given('the signed-in editor\'s newsroom profile is named "{name}"')
def signed_in_profile(context, name):
    client = _client(context)
    client.upsert("UserProfile", {"id": "profile-signed-in", "displayName": name})
    client.upsert("UserIdentity", {"id": "identity-signed-in", "userProfileId": "profile-signed-in", "cognitoSub": SIGNED_IN_SUB, "status": "active"})


@when('the signed-in editor marks the review of readers done in the console, the request naming "{claimed}"')
def console_review(context, claimed):
    from unittest.mock import patch

    from tenant_support import dedicated_call

    handler, client = _content_actions_handler(), _client(context)
    event = {"identity": {"sub": SIGNED_IN_SUB, "issuer": "https://cognito.example.test", "username": SIGNED_IN_SUB}}
    with dedicated_call(), patch.object(handler, "create_authoring_client", lambda *_args, **_kwargs: (client, None)):
        result = handler.set_story_step_action({"lineageId": "story-1", "stepKey": "review_people", "state": "done", "note": "Read it as a reader",
                                                "actorLabel": claimed}, event)
    assert result["ok"], result


@then('the checklist\'s review of readers is recorded under "{name}"')
def review_recorded_under(context, name):
    from papyrus_content import story_checklist as checklist

    row = {row["stepKey"]: row for row in checklist.read_steps(_client(context), "story-1")}["review_people"]
    assert (row["actorKind"], row["actorLabel"], row["actorSub"]) == ("person", name, SIGNED_IN_SUB), row


def _client(context):
    world = getattr(context, "world", None)
    if world is not None:
        return world.client or world.build()
    return context.client


def _published_row(context, lineage: str) -> dict:
    row = _client(context).get_record("PublishedItem", published_item_id_for(lineage))
    assert row is not None, f"{lineage} is not published: {getattr(context, 'publish_error', None)!r}"
    return row


def _recorded_reviewer(context, lineage: str):
    return json.loads(_published_row(context, lineage)["metadata"]).get(REVIEWED_BY_KEY)


@when("the Story's newest version is published by an editor")
def publish_newest_version(context):
    client = _client(context)
    context.publish_error = None
    with evidence_patches(context):
        try:
            publish_item(client, latest_story_version(client, "story-1")["id"], actor="editor", approved_by="editor-sub")
        except PublishError as error:
            context.publish_error = error


@then('the published record of "{lineage}" names the reviewer "{name}"')
def record_names_reviewer(context, lineage, name):
    recorded = _recorded_reviewer(context, lineage)
    assert recorded is not None and recorded["name"] == name and recorded.get("at"), recorded


@then('the published record of "{lineage}" names no reviewer')
def record_names_no_reviewer(context, lineage):
    assert _recorded_reviewer(context, lineage) is None, _recorded_reviewer(context, lineage)


@then('the page data of "{lineage}" names the reviewer "{name}"')
def page_data_names_reviewer(context, lineage, name):
    data = summary_from_row(_published_row(context, lineage)).front_matter
    assert (data.get(REVIEWED_BY_KEY) or {}).get("name") == name, data


@then('the page data of "{lineage}" names no reviewer')
def page_data_names_no_reviewer(context, lineage):
    data = summary_from_row(_published_row(context, lineage)).front_matter
    assert REVIEWED_BY_KEY not in data, data


@then('the published record of "{lineage}" is published version {number:d}')
def record_is_version(context, lineage, number):
    assert _published_row(context, lineage)["versionNumber"] == number, _published_row(context, lineage)
