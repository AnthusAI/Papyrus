"""The reviewer on the published record (features_backend/stories/published-reviewer.feature). The Story world is story_procedure_steps.py's and the translation
world is translation_publishing_steps.py's; nothing calls AWS or a model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.source import summary_from_row  # noqa: E402
from papyrus_content.published_reviewer import REVIEWED_BY_KEY  # noqa: E402
from papyrus_content.publishing import PublishError, publish_item, published_item_id_for  # noqa: E402
from papyrus_content.story_reporting import latest_story_version  # noqa: E402
from story_checklist_steps import evidence_patches  # noqa: E402


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
