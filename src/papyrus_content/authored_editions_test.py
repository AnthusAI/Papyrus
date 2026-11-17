"""Boundary regressions for authored editions; no service or model calls."""

import json
from unittest.mock import patch
import pytest
from papyrus_content.authored_editions import is_authored
from papyrus_content.localize.record import previous_alignment, save
from papyrus_content.publishing import publish_item, PublishError
from papyrus_content.story_checklist import ChecklistError
from papyrus_content.projection.source import summary_from_row
from papyrus_content.projection.standard.components import translation_notice

ROW = {
    "id": "source--es-419-v1",
    "lineageId": "source--es-419",
    "language": "es-419",
    "languageGroupId": "source",
    "type": "article",
    "section": "news",
    "slug": "voz",
    "bodyMarkus": "Own sources.",
    "versionState": "current",
    "contentHash": "hash",
    "metadata": json.dumps({"authoredEdition": {"kind": "independent", "authorKind": "agent"}, "frontMatterYaml": "title: Voz"}),
}


def test_previous_alignment_refuses_before_looking_for_translation_provenance():
    with patch("papyrus_content.story_reporting.story_versions", return_value=[ROW]):
        with pytest.raises(ValueError, match="independently authored"):
            previous_alignment(object(), "source--es-419")


def test_late_translation_save_refuses_before_writing():
    from types import SimpleNamespace

    request = SimpleNamespace(source=SimpleNamespace(version_id="source-v1"), localization_lineage="source--es-419")
    client = SimpleNamespace(get_record=lambda *_: {"id": "source-v1"})
    with patch("papyrus_content.story_reporting.story_versions", return_value=[ROW]):
        with pytest.raises(ValueError, match="saves nothing"):
            save(client, request, {})


def test_projection_never_labels_authored_copy_as_translated():
    row = {**ROW, "outputPath": "articles/voz.md"}
    summary = summary_from_row(row)
    assert summary.translation_kind == "authored"
    assert translation_notice({}, {"kind": "authored", "url": "/original/", "tag": "en"}) == ""


def test_authored_flag_requires_explicit_kind():
    assert is_authored(ROW)
    assert not is_authored({"metadata": json.dumps({"localization": {"translation": "imported"}})})


def test_authored_companion_keeps_normal_publication_gate():
    from fake_client import FakeAuthoringClient

    client = FakeAuthoringClient({"Item": [ROW]})
    with (
        patch("papyrus_content.localization_publish.require_publishable"),
        patch("papyrus_content.story_checklist.require_checklist_closed", side_effect=ChecklistError("review still open")) as gate,
    ):
        with pytest.raises(PublishError, match="review still open"):
            publish_item(client, ROW["id"], actor="editor")
        gate.assert_called_once()
    assert not client.tables.get("PublishedItem")


def test_authored_companion_can_publish_after_ordinary_gates():
    from fake_client import FakeAuthoringClient

    client = FakeAuthoringClient({"Item": [ROW]})
    with (
        patch("papyrus_content.localization_publish.require_publishable"),
        patch("papyrus_content.story_checklist.require_checklist_closed") as gate,
        patch("papyrus_content.publish_gate.ensure_publish_approval"),
        patch("papyrus_content.entity_labels.wanted.record_wanted_for_translation"),
    ):
        result = publish_item(client, ROW["id"], actor="editor")
    gate.assert_called_once()
    published = client.tables["PublishedItem"][result.published_item_id]
    assert published["language"] == "es-419"
    assert published["languageGroupId"] == "source"
    assert published["bodyMarkus"] == ROW["bodyMarkus"]


def test_auto_publish_skips_authored_draft_without_request():
    from types import SimpleNamespace
    from fake_client import FakeAuthoringClient
    from papyrus_content.localize.auto import request_translations

    primary = {
        "id": "source-v2",
        "lineageId": "source",
        "language": "en",
        "languageGroupId": "source",
        "type": "article",
        "contentHash": "new-source",
    }
    client = FakeAuthoringClient({"Item": [primary, ROW]})
    serving = SimpleNamespace(primary="en", enabled=("en", "es-419"), auto=SimpleNamespace(automation="localizer", publish=True))
    with (
        patch("papyrus_content.localize.auto.serving_languages", return_value=serving),
        patch("papyrus_content.localize.auto.published_story_version", return_value=primary),
    ):
        result = request_translations(client, primary["id"], settings={"configured": True})
    assert result["requested"] == []
    assert not client.tables.get("LocalizationRequest")
