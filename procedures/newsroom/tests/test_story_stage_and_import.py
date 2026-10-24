"""Moving a story between board stages, saving a version with a stage, and the Markus import's bucket and summary."""
import json
import os
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest

from papyrus_content.story_reporting import advance_stage, latest_story_version, move_story_stage, save_story_version, story_versions
from procedures.newsroom.tests.test_story_reporting import LINEAGE, NOW, client_with_one_story


def test_move_updates_the_item_stage_and_records_it_in_the_trail():
    client = client_with_one_story()
    result = move_story_stage(client, LINEAGE, "copywriting", actor="agent", reason="draft is ready", now=NOW)
    assert result["changed"] and result["from"] == "reporting"
    assert client.tables["Item"][LINEAGE]["stage"] == "copywriting"
    message = next(iter(client.tables["Message"].values()))
    assert "reporting -> copywriting" in message["summary"] and "draft is ready" in message["summary"]


def test_move_keeps_who_when_and_why_on_the_version_and_keeps_its_other_metadata():
    client = client_with_one_story()
    move_story_stage(client, LINEAGE, "copywriting", actor="agent", reason="draft is ready", now=NOW)
    move_story_stage(client, LINEAGE, "typesetting", actor="other", now=NOW)
    metadata = json.loads(client.tables["Item"][LINEAGE]["metadata"])
    assert metadata["frontMatterYaml"]
    assert [(m["from"], m["to"], m["by"], m["reason"]) for m in metadata["stageMoves"]] == [
        ("reporting", "copywriting", "agent", "draft is ready"), ("copywriting", "typesetting", "other", None)]


def test_move_to_the_same_stage_changes_nothing():
    client = client_with_one_story()
    assert move_story_stage(client, LINEAGE, "reporting", actor="agent")["changed"] is False
    assert not client.tables.get("Message")


def test_move_rejects_a_stage_the_publication_does_not_have():
    client = client_with_one_story()
    with pytest.raises(ValueError, match="Unknown content item stage"):
        move_story_stage(client, LINEAGE, "nowhere", actor="agent")
    assert client.tables["Item"][LINEAGE]["stage"] == "reporting"


def test_save_version_keeps_the_stage_unless_asked():
    client = client_with_one_story()
    kept = save_story_version(client, LINEAGE, front_matter_yaml='title: "S"', body_markus="Two.\n", actor="a", change_reason="r", now=NOW)
    assert kept["stage"] == "reporting"
    moved = save_story_version(client, LINEAGE, front_matter_yaml='title: "S"', body_markus="Three.\n", actor="a", change_reason="r",
                               now=NOW, stage=advance_stage(latest_story_version(client, LINEAGE)["stage"]))
    assert moved["stage"] == "copywriting"
    assert latest_story_version(client, LINEAGE)["stage"] == "copywriting"


def test_advance_stops_before_publication():
    assert advance_stage("idea") == "assignment"
    with pytest.raises(ValueError):
        advance_stage("typesetting")


def test_media_bucket_comes_from_the_site_roots_amplify_outputs(tmp_path, monkeypatch):
    from papyrus_content.media_store import configured_media_bucket

    (tmp_path / "amplify_outputs.json").write_text(json.dumps({"storage": {"bucket_name": "site-bucket"}}))
    for name in ("PAPYRUS_MEDIA_BUCKET", "PAPYRUS_STORAGE_BUCKET", "PAPYRUS_SITE_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert configured_media_bucket() == "site-bucket"
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "amplify_outputs.json").write_text(json.dumps({"storage": {"bucket_name": "named-root-bucket"}}))
    monkeypatch.setenv("PAPYRUS_SITE_ROOT", str(other))
    assert configured_media_bucket() == "named-root-bucket"


def test_import_summary_labels_board_only_items(monkeypatch):
    from papyrus_content import markus_import_commands as commands

    class Report:
        ok = True

        def to_dict(self):
            return {"ok": True, "created": 0, "updated": 0, "unchanged": 1, "skippedEditedInCms": 0, "published": 0,
                    "mediaUploaded": 0, "mediaUnchanged": 0, "readerOwnedAssets": 0, "notInSource": 3, "errors": []}

    monkeypatch.setattr(commands, "create_authoring_client", lambda tenant=None: (object(), {}))
    monkeypatch.setattr(commands, "configured_media_bucket", lambda explicit=None: None)
    monkeypatch.setattr(commands, "plan_import", lambda *a: object())
    monkeypatch.setattr(commands, "run_import", lambda *a, **k: Report())
    out = StringIO()
    with redirect_stdout(out):
        commands.content_import_markus(["--content-dir", "content", "--dry-run"])
    assert "board-only items" in out.getvalue() and "left untouched): 3" in out.getvalue()
    assert "notInSource" not in out.getvalue()


def test_move_story_stage_mutation_is_in_both_schema_definitions_for_editors():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for file in ("schema.ts", "resource.ts"):
        source = (root / "amplify/data" / file).read_text()
        action = source.split("  moveStoryStage: a", 1)[1].split("  unpublishItem:", 1)[0]
        assert "allow.groups(contentWriteGroups)" in action and "contentActions" in action
    assert 'field == "moveStoryStage"' in (root / "amplify/functions/content-actions/handler.py").read_text()
