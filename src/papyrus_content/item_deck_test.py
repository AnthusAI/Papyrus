"""An Item's ``deck`` column is the dek of its front matter, by one rule, on every save path (features_backend/stories/item-deck.feature, deploy-item-decks.feature)."""
from __future__ import annotations

import json

from papyrus_content.item_deck_backfill import DEPLOY_MARKER_KEY, ensure_item_decks, plan_decks, run_decks
from papyrus_content.item_front_matter import DEK_KEYS, dek_from_front_matter
from papyrus_content.publishing import ItemFields, columns_from_front_matter, project_item_to_published, publish_item, save_item
from papyrus_content.story_reporting import save_story_version
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

LINEAGE = "story-one"


def test_dek_is_the_canonical_key_and_wins_over_the_older_spellings():
    assert DEK_KEYS == ("dek", "deck", "standfirst", "description")
    fm = {"dek": "New dek.", "deck": "Old deck.", "standfirst": "S.", "description": "D."}
    assert dek_from_front_matter(fm) == "New dek."
    assert dek_from_front_matter({"dek": "  ", "deck": "Old deck."}) == "Old deck."
    assert dek_from_front_matter({"standfirst": "S.", "description": "D."}) == "S."
    assert dek_from_front_matter({"title": "T"}) is None
    assert columns_from_front_matter({"title": "T", "dek": "New dek."})["deck"] == "New dek."


def _story(client: FakeAuthoringClient, front: str) -> dict:
    save_item(client, ItemFields(id=LINEAGE, type="article", slug="one", section="articles", front_matter_yaml=front, body_markus="Body.\n", aliases=[]), actor="a", now="2026-11-01T00:00:00Z")
    return client.tables["Item"][LINEAGE]


def test_creating_and_saving_a_version_keep_the_deck_equal_to_the_dek():
    client = FakeAuthoringClient()
    assert _story(client, "title: One\ndek: First dek.\n")["deck"] == "First dek."
    second = save_story_version(client, LINEAGE, front_matter_yaml="title: One\ndek: Second dek.\n", body_markus="Body.\n", actor="a", change_reason="edit", now="2026-11-02T00:00:00Z")
    assert second["deck"] == "Second dek."
    third = save_story_version(client, LINEAGE, front_matter_yaml="title: One\ndek: Third dek.\ndeck: Stale.\n", body_markus="Body.\n", actor="a", change_reason="edit", now="2026-11-03T00:00:00Z")
    assert third["deck"] == "Third dek."


def test_the_published_row_copies_the_items_deck():
    client = FakeAuthoringClient()
    _story(client, "title: One\ndek: Served dek.\n")
    publish_item(client, LINEAGE, actor="p", now="2026-11-02T00:00:00Z")
    published = next(iter(client.tables["PublishedItem"].values()))
    assert published["deck"] == "Served dek."


def _row(row_id: str, front: str | None, deck, **extra):
    metadata = {"frontMatterYaml": front} if front is not None else {}
    return {"id": row_id, "lineageId": row_id.split("-v")[0], "versionNumber": 1, "versionState": "current", "type": "article", "updatedAt": "2026-10-01T00:00:00Z",
            "metadata": json.dumps(metadata), "deck": deck, **extra}


def test_the_plan_writes_only_rows_whose_deck_differs_and_leaves_rows_without_front_matter():
    plan = plan_decks([
        _row("a-v1", "title: A\ndek: New.\n", "Old."),        # stale
        _row("b-v1", "title: B\ndek: Same.\n", "Same."),      # right
        _row("c-v1", "title: C\ndek: Only dek.\n", None),     # missing
        _row("d-v1", "title: D\n", "Left from before."),      # no dek key at all: cleared to match
        _row("e-step", None, "A checklist step."),            # nothing to derive from
    ])
    assert [(w["id"], w["deck"]) for w in plan.writes] == [("a-v1", "New."), ("c-v1", "Only dek."), ("d-v1", None)]
    assert (plan.rows, plan.already_right, plan.no_front_matter) == (5, 1, 1)


def _old_site() -> FakeAuthoringClient:
    client = FakeAuthoringClient()
    row = _story(client, "title: One\ndek: Current dek.\n")
    row["updatedAt"] = "2026-10-01T00:00:00Z"
    row["deck"] = "Railway's October breach opens a series."   # what an older writer left
    publish_item(client, LINEAGE, actor="p", now="2026-11-02T00:00:00Z")
    published = next(iter(client.tables["PublishedItem"].values()))
    published["deck"] = "Railway's October breach opens a series."
    client.tables["Item"]["step-1"] = {"id": "step-1", "lineageId": "step-1", "versionNumber": 1, "versionState": "current", "type": "sub-task", "updatedAt": "x"}
    client.updates.clear()
    return client


def test_the_backfill_rederives_item_and_published_decks_writes_only_the_column_and_is_idempotent():
    client = _old_site()
    before = {key: client.tables["Item"][LINEAGE][key] for key in ("metadata", "updatedAt", "bodyMarkus")}
    lines: list[str] = []
    first = run_decks(client, rate=0, echo=lines.append)
    assert client.tables["Item"][LINEAGE]["deck"] == "Current dek."
    assert next(iter(client.tables["PublishedItem"].values()))["deck"] == "Current dek."
    assert {key: client.tables["Item"][LINEAGE][key] for key in before} == before
    assert all(set(payload) <= {"id", "deck", "updatedAt"} for _model, payload in client.updates)
    assert (len(first.writes), len(first.published.writes)) == (1, 1)
    assert any("rows read" in line and "rows to write" in line and "already right" in line for line in lines)
    client.updates.clear()
    second = run_decks(client, rate=0, echo=lambda line: None)
    assert client.updates == [] and not second.writes and not second.published.writes


def test_a_dry_run_writes_nothing():
    client = _old_site()
    run_decks(client, dry_run=True, rate=0, echo=lambda line: None)
    assert client.updates == [] and client.tables["Item"][LINEAGE]["deck"].startswith("Railway")


class Store:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, body):
        self.objects[key] = body


def test_the_deploy_step_runs_once_per_site_and_leaves_a_marker():
    client, store = _old_site(), Store()
    assert ensure_item_decks(client, store, now=lambda: "t", echo=lambda line: None)["itemDecks"] == "written"
    assert DEPLOY_MARKER_KEY in store.objects and client.tables["Item"][LINEAGE]["deck"] == "Current dek."
    client.calls.clear()
    assert ensure_item_decks(client, store, now=lambda: "t", echo=lambda line: None) == {"itemDecks": "already written"}
    assert client.calls == []
