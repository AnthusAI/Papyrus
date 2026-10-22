from __future__ import annotations

import json
import uuid

import yaml

from . import commands
from .corpus_export import biblicus_item_id, export_items, render_item, write_export
from .run_input import load_run, translate_item_ids


def row(name: str, *, published_at="2026-10-13T08:00:00Z", item_type="article", entities=(), tags=(), deck="A deck.", body="Body text."):
    front_matter = {"entities": [{"kind": kind, "name": entity} for kind, entity in entities], "tags": list(tags)}
    return {
        "id": f"published-{name}",
        "sourceItemId": f"item-{name}",
        "versionNumber": 1,
        "type": item_type,
        "status": "published",
        "slug": name,
        "section": "posts",
        "title": name.title(),
        "deck": deck,
        "bodyMarkus": body,
        "aliases": [],
        "publishedAt": published_at,
        "metadata": json.dumps({"projection": {"frontMatter": front_matter, "pageTitle": f"{name.title()} page"}}),
    }


def url_for(summary):
    return f"/{summary.section}/{summary.slug}/"


def front_matter_of(text: str) -> dict:
    assert text.startswith("---\n")
    head, _, body = text[4:].partition("\n---\n")
    return yaml.safe_load(head), body


def test_a_file_carries_what_biblicus_reads_and_the_words_a_reader_reads():
    item = render_item(row("alpha", entities=[("task", "Voice cloning")], tags=["decision-models"]), url_for)
    meta, body = front_matter_of(item.text)
    assert meta["biblicus"] == {"id": biblicus_item_id("item-alpha")}
    assert str(uuid.UUID(meta["biblicus"]["id"])) == meta["biblicus"]["id"]
    assert meta["papyrus_item_id"] == "item-alpha"
    assert meta["dates"] == {"published_at": "2026-10-13T08:00:00Z"}
    assert meta["tags"] == ["decision-models"]
    assert meta["entities"] == [{"kind": "task", "name": "Voice cloning"}]
    assert (meta["slug"], meta["url"], meta["title"]) == ("alpha", "/posts/alpha/", "Alpha page")
    assert body == "# Alpha page\n\nA deck.\n\nBody text.\n"
    assert item.file == "item-alpha.md"


def test_an_item_without_a_publication_date_has_no_dates_block():
    meta, _ = front_matter_of(render_item(row("beta", published_at=None), url_for).text)
    assert "dates" not in meta and "date_provenance" not in meta


def test_only_published_items_of_the_chosen_types_are_exported_in_item_id_order():
    rows = [row("gamma"), row("alpha"), row("entity", item_type="wiki_page"), {**row("hidden"), "status": "draft"}]
    assert [item.item_id for item in export_items(rows, url_for)] == ["item-alpha", "item-gamma"]
    assert [item.item_id for item in export_items(rows, url_for, ("wiki_page",))] == ["item-entity"]


def test_the_export_is_the_same_on_every_run_and_drops_files_of_items_no_longer_published(tmp_path):
    items = export_items([row("alpha"), row("beta")], url_for)
    (tmp_path / "notes.md").write_text("mine\n", encoding="utf-8")
    assert write_export(items, tmp_path) == {"items": 2, "removed": 0, "undated": 0}
    first = (tmp_path / "item-alpha.md").read_text(encoding="utf-8")
    assert write_export(export_items([row("alpha")], url_for), tmp_path) == {"items": 1, "removed": 1, "undated": 0}
    assert (tmp_path / "item-alpha.md").read_text(encoding="utf-8") == first
    assert not (tmp_path / "item-beta.md").exists()
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "mine\n"


class Client:
    def __init__(self, rows):
        self.rows = rows

    def list_records(self, model):
        assert model == "PublishedItem"
        return self.rows


def test_the_command_writes_the_files_and_says_how_many(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(commands, "create_authoring_client", lambda *args, **kwargs: (Client([row("alpha"), row("beta", published_at=None)]), {}))
    commands.knowledge_corpus_export(["--out", str(tmp_path / "raw" / "papyrus")])
    assert "2 items\t1 undated\t0 removed" in capsys.readouterr().out
    assert sorted(path.name for path in (tmp_path / "raw" / "papyrus").iterdir()) == ["item-alpha.md", "item-beta.md"]


def test_the_command_needs_an_output_folder():
    try:
        commands.knowledge_corpus_export([])
    except ValueError as error:
        assert "--out" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_biblicus_ids_in_a_run_become_item_ids(tmp_path):
    alpha, beta = biblicus_item_id("item-alpha"), biblicus_item_id("item-beta")
    identity = {
        "run_id": "run-1",
        "generated_at": "2026-10-19T06:00:00Z",
        "clusters": [{"uid": "u1", "topic_id": 0, "member_item_count": 2, "member_item_ids": [alpha, beta, "item-other"]}],
    }
    entities = {"items": [{"item_id": alpha, "entities": [], "relations": []}]}
    (tmp_path / "i.json").write_text(json.dumps(identity), encoding="utf-8")
    (tmp_path / "e.json").write_text(json.dumps(entities), encoding="utf-8")
    run = load_run(tmp_path / "i.json", None, tmp_path / "e.json")
    translated = translate_item_ids(run, {alpha: "item-alpha", beta: "item-beta"})
    assert translated.clusters[0].member_item_ids == ["item-alpha", "item-beta", "item-other"]
    assert [item.item_id for item in translated.entities] == ["item-alpha"]
