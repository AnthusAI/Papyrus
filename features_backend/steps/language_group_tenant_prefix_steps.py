"""On a tenant backend a stored language group carries the tenant prefix (features_backend/language-group-tenant-prefix.feature). Stand-in clients; no network."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

ORIGINAL, TRANSLATION = "story-rivers", "story-rivers--es-419"


class Content:
    """The slice of the authoring client the roundup, the announce agent and the publish rule read."""

    def __init__(self, tenant_id, rows):
        self.tenant_id, self.rows = tenant_id, rows

    def list_published_item_summaries(self):
        return [dict(row) for row in self.rows.values()]

    def get_record(self, model, record_id):
        return next((dict(row) for row in self.rows.values() if row["id"] == record_id), None)

    def list_by_index(self, index, lineage):
        row = self.rows[lineage]
        return [{"id": f"{lineage}-v1", "versionState": "current", "stage": "published", **row}]


@given('the tenant backend "{tenant}" has the published Story "{original}" and its Spanish translation "{translation}", each stored with a prefixed language group')
def _backend(context, tenant, original, translation):
    assert (original, translation) == (ORIGINAL, TRANSLATION)
    from papyrus_content.publishing import published_item_id_for

    def row(lineage, language):
        return {"id": published_item_id_for(lineage), "itemLineageId": lineage, "lineageId": lineage, "type": "article", "status": "published", "slug": lineage, "title": lineage,
                "section": "news", "publishedAt": "2026-11-18T12:00:00Z", "versionNumber": 1, "language": language,
                "languageGroupId": f"{tenant}#{original}", "metadata": "{}"}

    context.tenant = tenant
    context.content = Content(tenant, {ORIGINAL: row(ORIGINAL, "en"), TRANSLATION: row(TRANSLATION, "es-419")})


@then('the original "{lineage}" is not a translation of anything')
def _original(context, lineage):
    from papyrus_content.item_language import localization_original, translation_original

    row = context.content.rows[lineage]
    assert translation_original(row, context.tenant) is None and localization_original(row, context.tenant) is None


@then('the translation "{lineage}" is a translation of "{original}"')
def _translation(context, lineage, original):
    from papyrus_content.item_language import localization_original, translation_original

    row = context.content.rows[lineage]
    assert translation_original(row, context.tenant) == original and localization_original(row, context.tenant) == original


@when("the roundup lists the Stories it may include")
def _roundup(context):
    from papyrus_content.newsletter.roundup import candidates

    service = SimpleNamespace(content=context.content, settings=SimpleNamespace(lists=[], floor_stars=None))
    context.listed = [candidate.row["itemLineageId"] for candidate in candidates(service)]


@then('the roundup lists "{included}" and not "{left_out}"')
def _roundup_lists(context, included, left_out):
    assert context.listed == [included], context.listed


@when('the announce agent reads the Story "{first}" and the Story "{second}"')
def _announce(context, first, second):
    from papyrus_content.list_cadence.story_wake import read_candidate

    class NoStamps:
        def __init__(self, client):
            pass

        def reviewed(self, lineage, version):
            return False

    with mock.patch("papyrus_content.announcements.intake.ChecklistReviewStamps", NoStamps):
        context.read = {lineage: read_candidate(context.content, lineage) for lineage in (first, second)}


@then("the original is not marked as a translation")
def _not_marked(context):
    assert context.read[ORIGINAL] is not None and context.read[ORIGINAL].translation is False


@then("the translation is marked as a translation")
def _marked(context):
    assert context.read[TRANSLATION] is not None and context.read[TRANSLATION].translation is True


@then('publishing "{lineage}" by an automation is refused as a translation')
def _refused(context, lineage):
    from papyrus_content.publish_by_person import TRANSLATION as KIND, story_kind

    assert story_kind(context.content, context.content.rows[lineage]) == KIND


@then('publishing "{lineage}" by an automation is not refused as a translation')
def _not_refused(context, lineage):
    from papyrus_content.publish_by_person import TRANSLATION as KIND, story_kind

    with mock.patch("papyrus_content.story_checklist.read_steps", return_value=[]):
        assert story_kind(context.content, context.content.rows[lineage]) != KIND
