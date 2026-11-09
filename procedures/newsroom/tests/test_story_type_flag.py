"""`papyrus stories create --type` and `stories set-type`: a story's type is chosen from the CLI, checked against the site's list when it is known."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papyrus_content import story_commands
from papyrus_content.story_reporting import create_story
from procedures.newsroom.tests.fake_client import FakeAuthoringClient


def site_directory(tmp_path: Path, types=("article", "post"), default="article") -> Path:
    (tmp_path / "projection.json").write_text(json.dumps({"storyTypes": {"default": default, "types": list(types)}}))
    return tmp_path


def test_create_story_takes_a_type_and_without_one_uses_the_default_or_untyped():
    client = FakeAuthoringClient()
    assert create_story(client, title="A post", section_key=None, actor="AI", item_type="post")["type"] == "post"
    assert create_story(client, title="No type", section_key=None, actor="AI")["type"] == "untyped"
    assert create_story(client, title="Typed", section_key=None, actor="AI", item_type="article")["typeStatus"] == "article#draft"


def test_chosen_type_is_checked_against_the_site_list_when_it_is_known(tmp_path):
    folder = site_directory(tmp_path)
    assert story_commands.chosen_story_type({"type": "post"}, static_directory=folder) == "post"
    with pytest.raises(ValueError, match="not one of this site's Story types"):
        story_commands.chosen_story_type({"type": "guide"}, static_directory=folder)


def test_chosen_type_refuses_system_and_untyped_and_badly_shaped_names(tmp_path):
    folder = site_directory(tmp_path)
    for bad in ("untyped", "wiki_page", "Post", "po st"):
        with pytest.raises(ValueError):
            story_commands.chosen_story_type({"type": bad}, static_directory=folder)


def test_chosen_type_with_no_site_list_is_accepted_with_a_note(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("PAPYRUS_SITE_STATIC_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert story_commands.chosen_story_type({"type": "post"}) == "post"
    assert "was not checked against the site's list" in capsys.readouterr().out
    assert story_commands.chosen_story_type({}) is None


def test_set_type_changes_an_unpublished_story_and_refuses_a_published_one(monkeypatch, tmp_path, capsys):
    client = FakeAuthoringClient()
    item = create_story(client, title="Switch me", section_key=None, actor="AI")
    lineage = item["lineageId"]
    monkeypatch.setattr(story_commands, "create_authoring_client", lambda: (client, {}))
    monkeypatch.setenv("PAPYRUS_SITE_STATIC_DIR", str(site_directory(tmp_path)))
    story_commands.stories_set_type(["--story", lineage, "--type", "post", "--dry-run"])
    assert client.get_record("Item", item["id"])["type"] == "untyped", "a dry run writes nothing"
    story_commands.stories_set_type(["--story", lineage, "--type", "post"])
    changed = client.get_record("Item", item["id"])
    assert changed["type"] == "post" and changed["typeStatus"] == "post#draft"
    story_commands.stories_set_type(["--story", lineage, "--type", "post"])
    assert "unchanged" in capsys.readouterr().out
    monkeypatch.setattr(story_commands, "published_story_version", lambda *_: {"id": "published"})
    with pytest.raises(ValueError, match="is published"):
        story_commands.stories_set_type(["--story", lineage, "--type", "article"])
