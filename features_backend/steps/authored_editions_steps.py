"""Authored companions, local in-memory backend only."""

import json
from copy import deepcopy
from unittest.mock import patch
from behave import given, when, then
from papyrus_content.authored_editions import import_edition
from papyrus_content.localize.desired_state import want
from fake_client import FakeAuthoringClient


@given("an original article and independently authored Spanish copy")
def setup(context):
    context.ed_client = FakeAuthoringClient()
    context.ed_primary = {
        "id": "original-v1",
        "lineageId": "original",
        "versionNumber": 1,
        "type": "article",
        "title": "The original",
        "slug": "the-original",
        "section": "news",
        "language": "en",
        "languageGroupId": "original",
        "bodyMarkus": "English source.",
        "contentHash": "source-hash",
        "metadata": "{}",
        "versionState": "current",
        "status": "published",
    }
    context.ed_client.tables.setdefault("Item", {})["original-v1"] = deepcopy(context.ed_primary)
    context.ed_body = "Una apertura diferente.\n\n## Otra voz\n\n[Entrevista](https://example.test/es-interview)\n"
    context.ed_before = deepcopy(context.ed_client.tables)
    context.ed_settings = {
        "primary": "en",
        "enabled": ["en", "es-419"],
        "public": ["en", "es-419"],
        "prefixes": {"en": "", "es-419": "es"},
        "slugs": {"en": "translated", "es-419": "translated"},
    }


@given("that language already has a translation")
def existing(context):
    row = {**context.ed_primary, "id": "original--es-419-v1", "lineageId": "original--es-419", "language": "es-419"}
    context.ed_client.tables["Item"][row["id"]] = row
    context.ed_before = deepcopy(context.ed_client.tables)


@when("the editor imports the independently authored edition")
def imported(context):
    from types import SimpleNamespace

    try:
        with (
            patch("papyrus_content.story_reporting.published_story_version", return_value=context.ed_primary),
            patch("papyrus_content.editorial_checks.settings_from", return_value={}),
            patch(
                "papyrus_content.language_serving.serving_languages",
                return_value=SimpleNamespace(primary="en", enabled=("en", "es-419"), slugs={"es-419": "translated"}),
            ),
            patch("papyrus_content.editorial_languages.site_language", return_value="es-419"),
            patch("papyrus_content.story_checklist.sync_checklist"),
            patch("papyrus_content.story_reporting._carry_media_forward"),
        ):
            context.ed_result = import_edition(
                context.ed_client,
                story="original",
                language="es-419",
                body=context.ed_body,
                front_matter="title: Otra voz\ndrafting:\n  by: AI\n",
                written_by="AI",
                author_kind="agent",
                applied_by="editor-session",
                reason="Own reporting",
                apply=not getattr(context, "ed_dry_run", False),
            )
        context.ed_error = None
    except ValueError as error:
        context.ed_error = str(error)


@then("the companion preserves its own copy and sources without translation alignment")
def preserved(context):
    assert not context.ed_error, context.ed_error
    row = context.ed_result["record"]
    assert row["bodyMarkus"] == context.ed_body
    meta = json.loads(row["metadata"])
    assert meta["authoredEdition"]["authorKind"] == "agent"
    assert "alignment" not in meta and "localization" not in meta
    assert row["languageGroupId"] == "original" and row["language"] == "es-419"


@then("the original article is unchanged and the companion is unpublished")
def draft(context):
    assert context.ed_client.tables["Item"]["original-v1"] == context.ed_primary
    assert context.ed_result["record"]["status"] == "draft"
    assert not context.ed_client.tables.get("PublishedItem")
    assert not context.ed_client.tables.get("LocalizationRequest")


@then("the authored import is refused without a write")
def refused(context):
    assert context.ed_error and "already" in context.ed_error
    assert {k: v for k, v in context.ed_client.tables.items() if v} == {k: v for k, v in context.ed_before.items() if v}


@then("a translation request for that language is refused")
def protected(context):
    before = deepcopy(context.ed_client.tables)
    try:
        want(context.ed_client, source=context.ed_primary, language="es-419", requested_by="test")
    except ValueError as error:
        assert "authored" in str(error)
    else:
        raise AssertionError("translation was allowed")
    assert context.ed_client.tables == before


@given("a translation for that language is queued")
def queued(context):
    context.ed_client.tables.setdefault("LocalizationRequest", {})["original#es-419"] = {"id": "original#es-419", "state": "wanted"}
    context.ed_before = deepcopy(context.ed_client.tables)


@then("the queued translation conflict saves nothing")
def queue_refused(context):
    assert "queued" in context.ed_error
    assert context.ed_client.tables["Item"] == context.ed_before["Item"]


@then("only one unpublished authored version exists")
def idempotent(context):
    assert not context.ed_error and context.ed_result["unchanged"]
    assert len(context.ed_client.tables["Item"]) == 2


@given("the original belongs to a different tenant")
def foreign(context):
    context.ed_client.tenant_id = "current-site"
    context.ed_primary["tenantId"] = "other-site"


@then("the cross-tenant import is refused")
def foreign_refused(context):
    assert "another tenant" in context.ed_error
    assert len(context.ed_client.tables["Item"]) == 1


@given("the import is only a dry run")
def dry_run(context):
    context.ed_dry_run = True


@then("no companion or translation request is written")
def no_write(context):
    assert not context.ed_error and context.ed_result["record"] is None
    assert len(context.ed_client.tables["Item"]) == 1
    assert not context.ed_client.tables.get("LocalizationRequest")


@then("publishing the companion refuses an open editorial checklist")
def gate(context):
    from papyrus_content.publishing import publish_item, PublishError
    from papyrus_content.story_checklist import ChecklistError

    with (
        patch("papyrus_content.localization_publish.require_publishable"),
        patch("papyrus_content.story_checklist.require_checklist_closed", side_effect=ChecklistError("reviews open")),
    ):
        try:
            publish_item(context.ed_client, context.ed_result["record"]["id"], actor="editor")
        except PublishError as error:
            assert "reviews open" in str(error)
        else:
            raise AssertionError("authored copy bypassed editorial checks")
    assert not context.ed_client.tables.get("PublishedItem")


@then("the reader metadata identifies independent authorship without a translator notice")
def notice(context):
    from papyrus_content.projection.source import summary_from_row
    from papyrus_content.projection.standard.components import translation_notice

    summary = summary_from_row(context.ed_result["record"])
    assert summary.translation_kind == "authored"
    assert translation_notice({}, {"kind": "authored", "url": "/original/", "tag": "en"}) == ""
