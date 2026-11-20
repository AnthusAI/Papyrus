"""features_backend/stories/item-deck.feature and deploy-item-decks.feature: the deck column is the dek of the front matter, and the backfill that repairs old rows."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.item_deck_backfill import DEPLOY_MARKER_KEY, ensure_item_decks, run_decks  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from papyrus_content.story_reporting import save_story_version  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

LINEAGE = "story-one"
OLD = "2026-10-01T00:00:00Z"
STALE = "Railway's October breach opens a series."


class Store:
    def __init__(self):
        self.objects = {}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, body):
        self.objects[key] = body


def _save(context, front):
    save_item(context.client, ItemFields(id=LINEAGE, type="article", slug="one", section="articles", front_matter_yaml=front, body_markus="Body.\n", aliases=[]),
              actor="a", now="2026-11-01T00:00:00Z")


def _newest(context):
    rows = [row for row in context.client.tables["Item"].values() if row.get("lineageId") == LINEAGE]
    return max(rows, key=lambda row: int(row.get("versionNumber") or 0))


@given('a deck Story saved with the dek "{dek}"')
def step_saved(context, dek):
    context.client = FakeAuthoringClient()
    _save(context, f"title: One\ndek: {dek}\n")


@when('a new deck version is saved with the dek "{dek}"')
def step_new_version(context, dek):
    save_story_version(context.client, LINEAGE, front_matter_yaml=f"title: One\ndek: {dek}\n", body_markus="Body.\n", actor="a", change_reason="edit", now="2026-11-02T00:00:00Z")


@when('a deck Story is saved whose front matter has the dek "{dek}" and the deck "{deck}"')
def step_both(context, dek, deck):
    context.client = FakeAuthoringClient()
    _save(context, f"title: One\ndek: {dek}\ndeck: {deck}\n")


@when("a deck Story is saved whose front matter has no dek")
def step_none(context):
    context.client = FakeAuthoringClient()
    _save(context, "title: One\n")


@when("the deck Story is published")
def step_publish(context):
    publish_item(context.client, LINEAGE, actor="p", now="2026-11-02T00:00:00Z")


@then('the newest deck version\'s deck is "{deck}"')
def step_deck(context, deck):
    assert _newest(context)["deck"] == deck, _newest(context)


@then("the newest deck version has no deck")
def step_no_deck(context):
    assert not _newest(context).get("deck")


@then('the published deck row is "{deck}"')
def step_published_deck(context, deck):
    assert next(iter(context.client.tables["PublishedItem"].values()))["deck"] == deck


@given("a site whose Story and its published row still carry an older deck than the dek in their front matter")
def step_old_site(context):
    context.client = FakeAuthoringClient()
    _save(context, "title: One\ndek: Current dek.\n")
    context.client.tables["Item"][LINEAGE].update({"deck": STALE, "updatedAt": OLD})
    publish_item(context.client, LINEAGE, actor="p", now="2026-11-02T00:00:00Z")
    next(iter(context.client.tables["PublishedItem"].values()))["deck"] = STALE
    context.store, context.lines = Store(), []
    context.before = {key: context.client.tables["Item"][LINEAGE][key] for key in ("metadata", "updatedAt")}
    context.client.updates.clear()


@given("the site also has a checklist step with no front matter")
def step_checklist(context):
    context.client.tables["Item"]["step-1"] = {"id": "step-1", "lineageId": "step-1", "versionNumber": 1, "versionState": "current", "type": "sub-task",
                                               "updatedAt": OLD, "deck": "A step."}


@given("the deck deploy step ran once")
def step_ran_once(context):
    ensure_item_decks(context.client, context.store, now=lambda: "t", echo=lambda line: None)
    context.client.updates.clear()


@when("the deck deploy step runs")
def step_deploy(context):
    ensure_item_decks(context.client, context.store, now=lambda: "t", echo=lambda line: None)


@when('the deck repair is run as a dry run, as "papyrus stories decks --dry-run" does')
def step_dry(context):
    run_decks(context.client, dry_run=True, rate=0, echo=context.lines.append)


@when('the deck repair is run, as "papyrus stories decks" does')
def step_run(context):
    context.second_start = len(context.client.updates)
    run_decks(context.client, rate=0, echo=context.lines.append)


@then('the Item deck and the published deck are "{deck}"')
def step_both_decks(context, deck):
    assert context.client.tables["Item"][LINEAGE]["deck"] == deck
    assert next(iter(context.client.tables["PublishedItem"].values()))["deck"] == deck


@then("only the deck column of two rows was written")
def step_only_deck(context):
    assert len(context.client.updates) == 2 and all(set(payload) <= {"id", "deck", "updatedAt"} for _model, payload in context.client.updates), context.client.updates


@then("the front matter and the update time of the Item are unchanged")
def step_unchanged(context):
    assert {key: context.client.tables["Item"][LINEAGE][key] for key in context.before} == context.before


@then("the site holds the deck migration marker")
def step_marker(context):
    assert context.store.get(DEPLOY_MARKER_KEY) is not None


@then("no deck row was written")
def step_none_written(context):
    assert context.client.updates == []


@then("no deck was changed")
def step_nothing(context):
    assert context.client.updates == [] and context.client.tables["Item"][LINEAGE]["deck"] == STALE


@then("the report counts rows read, rows to write and rows already right for the Items and the published rows")
def step_report(context):
    summaries = [line for line in context.lines if "rows read" in line]
    assert len(summaries) == 2 and all("rows to write" in line and "already right" in line for line in summaries), context.lines
    assert any("PublishedItem" in line for line in summaries) and any("\tItem\t" in line for line in summaries)


@then("the second run wrote no row")
def step_second(context):
    assert len(context.client.updates) == context.second_start


@then("the checklist step was not written")
def step_step_alone(context):
    assert all(payload["id"] != "step-1" for _model, payload in context.client.updates)
