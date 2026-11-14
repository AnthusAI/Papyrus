"""Machine-written Items record the run that wrote them, and one run can be undone (PPY-5b5a5d). Synthetic data only."""

from __future__ import annotations

import json

import pytest

from papyrus_content.ideas.items import ItemStore, file_idea_item
from papyrus_content.knowledge_cloud.config import CloudRunConfig
from papyrus_content.knowledge_cloud import undo as undo_commands
from papyrus_content.knowledge_snapshot import commands as snapshot_commands
from papyrus_content.knowledge_wiki import commands as wiki_commands
from papyrus_content.machine_writes import (
    MACHINE_WRITE_KEY,
    RETIRED_STAGE,
    knowledge_run_id,
    machine_write_of,
    plan_restore,
    plan_undo,
    run_id_from_environment,
)
from papyrus_content.publishing import ItemFields, published_item_id_for, save_item
from papyrus_content.wiki_stamp import WIKI_PAGE_ITEM_TYPE
from procedures.newsroom.tests.test_idea_items import draft
from procedures.newsroom.tests.test_knowledge_wiki import DAY, WikiClient, publish_article
from procedures.newsroom.tests.test_story_from_reference import NOW, backend, reader

FIRST = "knowledge-example-scheduled-1"
SECOND = "knowledge-example-scheduled-2"


@pytest.fixture
def client(monkeypatch):
    fake = WikiClient()
    publish_article(fake, "alpha", entities=[("maker", "Acme Loom"), ("tool", "Beta Spool")])
    for module in (snapshot_commands, wiki_commands, undo_commands):
        monkeypatch.setattr(module, "create_authoring_client", lambda *args, **kwargs: (fake, {}))
    snapshot_commands.knowledge_publish_run(["--apply"])
    return fake


def wiki_items(client):
    return {row["slug"]: row for row in client.tables.get("Item", {}).values() if row.get("type") == WIKI_PAGE_ITEM_TYPE}


def sync(*flags):
    wiki_commands.knowledge_wiki_sync(list(flags))


def publish_all():
    wiki_commands.knowledge_wiki_publish(["--all-drafts", "--actor", "ai", "--apply", "--no-trigger", "--on", DAY])


def live(client, row):
    return client.get_record("PublishedItem", published_item_id_for(row["lineageId"])) is not None


def test_the_run_id_of_a_cloud_execution_is_built_from_the_publication_and_the_execution_name():
    assert knowledge_run_id("Example Site", "Scheduled 2026-11-03T05:00") == "knowledge-example-site-scheduled-2026-11-03t05-00"
    assert run_id_from_environment({"KNOWLEDGE_PUBLICATION": "example", "KNOWLEDGE_EXECUTION_NAME": "manual-7"}) == "knowledge-example-manual-7"
    assert run_id_from_environment({"KNOWLEDGE_RUN_ID": "chosen", "KNOWLEDGE_PUBLICATION": "example", "KNOWLEDGE_EXECUTION_NAME": "x"}) == "chosen"
    assert run_id_from_environment({"KNOWLEDGE_PUBLICATION": "example"}) is None
    config = CloudRunConfig.from_environment(
        {"KNOWLEDGE_PUBLICATION": "example", "KNOWLEDGE_STATE_BUCKET": "b", "KNOWLEDGE_LEDGER_TABLE": "t", "KNOWLEDGE_SITE_REPO": "r", "PAPYRUS_SITE_BUCKET": "s", "KNOWLEDGE_EXECUTION_NAME": "manual-7"}
    )
    assert config.run_id == "knowledge-example-manual-7"


def test_every_wiki_page_a_run_writes_records_the_run_and_a_later_run_keeps_the_creator(client):
    sync("--apply", "--run-id", FIRST)
    pages = wiki_items(client)
    assert len(pages) == 2
    for row in pages.values():
        assert machine_write_of(row) == {"runId": FIRST, "createdByRunId": FIRST, "writer": "knowledge-wiki-sync", "at": machine_write_of(row)["at"]}
    wiki_commands.knowledge_wiki_publish(["--all-drafts", "--actor", "ai", "--apply", "--no-trigger", "--on", DAY])
    snapshot_commands.knowledge_entities_describe(["--key", "maker--acme-loom", "--text", "Acme Loom makes looms.", "--actor", "human", "--actor-name", "Ada Reader"])
    sync("--apply", "--run-id", SECOND)
    stamp = machine_write_of(wiki_items(client)["maker-acme-loom"])
    assert (stamp["runId"], stamp["createdByRunId"]) == (SECOND, FIRST)


def test_a_sync_without_a_run_id_still_records_a_generated_one_when_it_writes(client, capsys):
    sync("--apply")
    stamp = machine_write_of(wiki_items(client)["tool-beta-spool"])
    assert stamp["runId"].startswith("wiki-sync-") and stamp["createdByRunId"] == stamp["runId"]
    assert stamp["runId"] in capsys.readouterr().err


def test_a_dry_run_sync_writes_nothing(client):
    before = len(client.write_calls())
    sync("--run-id", FIRST)
    assert len(client.write_calls()) == before


def test_an_idea_filed_by_a_run_records_the_run_without_changing_who_it_says_wrote_it():
    client = backend()
    result = file_idea_item(client, draft(), now=NOW, source_text_reader=reader, run_id=FIRST)
    item = client.get_record("Item", result["itemId"])
    assert machine_write_of(item)["createdByRunId"] == FIRST and machine_write_of(item)["writer"] == "idea-pipeline"
    assert item["versionCreatedBy"] == "AI"  # the Idea column reads this to label a generated idea


def test_the_idea_store_passes_the_run_to_each_idea_it_files():
    client = backend()
    lineage = ItemStore(client, source_text_reader=reader, run_id=SECOND).file_story_draft(draft())
    assert machine_write_of(client.get_record("Item", f"{lineage}"))["createdByRunId"] == SECOND


def test_undo_is_a_dry_run_by_default_and_names_what_it_would_retire(client, capsys):
    sync("--apply", "--run-id", FIRST)
    publish_all()
    capsys.readouterr()
    before = len(client.write_calls())
    undo_commands.knowledge_run_undo(["--run-id", FIRST])
    out = capsys.readouterr().out
    assert len(client.write_calls()) == before
    assert "dry-run" in out and "pass --apply" in out and "to retire\t2\tlive\t2" in out
    assert all(live(client, row) for row in wiki_items(client).values())


def test_undo_unpublishes_and_retires_the_run_and_deletes_nothing(client, tmp_path):
    sync("--apply", "--run-id", FIRST)
    publish_all()
    ids = {row["id"] for row in wiki_items(client).values()}
    live_out = tmp_path / "live.json"
    undo_commands.knowledge_run_undo(["--run-id", FIRST, "--apply", "--live-out", str(live_out)])
    pages = wiki_items(client)
    assert {row["id"] for row in pages.values()} == ids  # nothing deleted
    for row in pages.values():
        assert row["stage"] == RETIRED_STAGE and row["status"] == "draft" and not live(client, row)
        assert machine_write_of(row)["undone"]["runId"] == FIRST and machine_write_of(row)["undone"]["previous"]["wasLive"] is True
    assert sorted(json.loads(live_out.read_text())) == sorted(ids)


def test_undo_touches_only_the_run_it_names(client):
    sync("--apply", "--run-id", FIRST)
    publish_article(client, "beta", entities=[("maker", "Cog Works")])
    snapshot_commands.knowledge_publish_run(["--apply"])
    sync("--apply", "--run-id", SECOND)
    publish_all()
    undo_commands.knowledge_run_undo(["--run-id", SECOND, "--apply"])
    pages = wiki_items(client)
    assert pages["maker-cog-works"]["stage"] == RETIRED_STAGE
    assert pages["maker-acme-loom"]["stage"] != RETIRED_STAGE and live(client, pages["maker-acme-loom"])


def test_a_retired_page_is_not_brought_back_by_the_next_sync_or_publish(client):
    sync("--apply", "--run-id", FIRST)
    publish_all()
    undo_commands.knowledge_run_undo(["--run-id", FIRST, "--apply"])
    sync("--apply", "--retire", "--run-id", SECOND)
    publish_all()
    for row in wiki_items(client).values():
        assert row["stage"] == RETIRED_STAGE and not live(client, row)
        assert machine_write_of(row)["runId"] == FIRST  # the later run did not write it


def test_undoing_twice_changes_nothing_the_second_time(client):
    sync("--apply", "--run-id", FIRST)
    undo_commands.knowledge_run_undo(["--run-id", FIRST, "--apply"])
    before = len(client.write_calls())
    undo_commands.knowledge_run_undo(["--run-id", FIRST, "--apply"])
    assert len(client.write_calls()) == before


def test_restore_puts_the_pages_back_as_drafts_and_the_next_publish_makes_them_live(client):
    sync("--apply", "--run-id", FIRST)
    publish_all()
    undo_commands.knowledge_run_undo(["--run-id", FIRST, "--apply"])
    plan = plan_restore(client.list_records("Item"), FIRST)
    assert len(plan.items) == 2 and plan.was_live == 2
    undo_commands.knowledge_run_restore(["--run-id", FIRST])  # dry run
    assert all(row["stage"] == RETIRED_STAGE for row in wiki_items(client).values())
    undo_commands.knowledge_run_restore(["--run-id", FIRST, "--apply"])
    for row in wiki_items(client).values():
        assert row["stage"] == "copywriting" and "undone" not in machine_write_of(row)
    publish_all()
    assert all(live(client, row) for row in wiki_items(client).values())


def test_an_item_a_person_made_is_never_selected(client):
    save_item(
        client,
        ItemFields(type="article", slug="by-hand", section="posts", front_matter_yaml="title: By hand\n", body_markus="Mine.\n", aliases=[], id="item-by-hand"),
        actor="a-person", now=NOW,
    )
    assert MACHINE_WRITE_KEY not in json.loads(client.get_record("Item", "item-by-hand")["metadata"])
    plan = plan_undo(client.list_records("Item"), FIRST, lambda lineage: None)
    assert plan.items == ()


def test_undo_requires_a_run_id(client):
    with pytest.raises(ValueError, match="--run-id"):
        undo_commands.knowledge_run_undo(["--apply"])
