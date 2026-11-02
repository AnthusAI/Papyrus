from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.ideas.items import file_idea_item  # noqa: E402
from papyrus_content.knowledge_cloud import undo as undo_commands  # noqa: E402
from papyrus_content.knowledge_snapshot import commands as snapshot_commands  # noqa: E402
from papyrus_content.knowledge_wiki import commands as wiki_commands  # noqa: E402
from papyrus_content.knowledge_wiki.sync import front_matter_of  # noqa: E402
from papyrus_content.machine_writes import RETIRED_STAGE, machine_write_of  # noqa: E402
from papyrus_content.publishing import ItemFields, published_item_id_for, save_item  # noqa: E402
from papyrus_content.wiki_stamp import WIKI_PAGE_ITEM_TYPE  # noqa: E402
from procedures.newsroom.tests.test_idea_items import draft  # noqa: E402
from procedures.newsroom.tests.test_knowledge_wiki import DAY, WikiClient, publish_article  # noqa: E402
from procedures.newsroom.tests.test_story_from_reference import NOW, backend, reader  # noqa: E402


def _scene(context):
    if not hasattr(context, "undo_scene"):
        directory = tempfile.TemporaryDirectory()
        context.add_cleanup(directory.cleanup)
        client = WikiClient()
        for module in (snapshot_commands, wiki_commands, undo_commands):
            patcher = mock.patch.object(module, "create_authoring_client", lambda *args, **kwargs: (client, {}))
            patcher.start()
            context.add_cleanup(patcher.stop)
        context.undo_scene = {"client": client, "dir": Path(directory.name), "out": "", "writes": 0, "writes_before": 0}
    return context.undo_scene


def _pages(scene):
    rows = scene["client"].tables.get("Item", {}).values()
    return {front_matter_of(row).get("title"): row for row in rows if row.get("type") == WIKI_PAGE_ITEM_TYPE}


def _live(scene, title):
    return scene["client"].get_record("PublishedItem", published_item_id_for(_pages(scene)[title]["lineageId"])) is not None


def _run(scene, function, *flags):
    scene["writes_before"] = len(scene["client"].write_calls())
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        function(list(flags))
    scene["out"] = buffer.getvalue()
    scene["writes"] = len(scene["client"].write_calls()) - scene["writes_before"]


def _sync(context, run_id):
    _run(_scene(context), wiki_commands.knowledge_wiki_sync, "--apply", "--run-id", run_id)


def _publish(context):
    _run(_scene(context), wiki_commands.knowledge_wiki_publish, "--all-drafts", "--actor", "ai", "--apply", "--no-trigger", "--on", DAY)


@given('a site whose published article names the entities "{a}" ({ak}) and "{b}" ({bk})')
def step_site(context, a, ak, b, bk):
    scene = _scene(context)
    publish_article(scene["client"], "alpha", entities=[(ak, a), (bk, b)])
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot_commands.knowledge_publish_run(["--apply"])


@given('the wiki sync applied as run "{run_id}" and every page was published')
def step_synced_published(context, run_id):
    _sync(context, run_id)
    _publish(context)


@when('the wiki sync applies as run "{run_id}"')
def step_sync(context, run_id):
    _sync(context, run_id)


@when('the wiki sync applies as run "{run_id}" and every draft is published')
def step_sync_publish(context, run_id):
    _sync(context, run_id)
    _publish(context)


@given('the entity "{name}" was described')
def step_described(context, name):
    key = "maker--acme-loom" if name == "Acme Loom" else "tool--beta-spool"
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot_commands.knowledge_entities_describe(["--key", key, "--text", f"{name} is described.", "--actor", "human", "--actor-name", "Ada Reader"])


@given('a later run "{run_id}" created the page for "{title}"')
def step_later_run(context, run_id, title):
    scene = _scene(context)
    publish_article(scene["client"], "beta", entities=[("maker", title)])
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot_commands.knowledge_publish_run(["--apply"])
    _sync(context, run_id)
    _publish(context)


@given("a person saved an article by hand")
def step_person(context):
    save_item(
        _scene(context)["client"],
        ItemFields(type="article", slug="by-hand", section="posts", front_matter_yaml=yaml.safe_dump({"title": "By hand"}), body_markus="Mine.\n", aliases=[], id="item-by-hand"),
        actor="a-person", now=NOW,
    )


@when('a run named "{run_id}" files a generated idea')
def step_idea(context, run_id):
    context.idea_client = backend()
    context.idea = file_idea_item(context.idea_client, draft(), now=NOW, source_text_reader=reader, run_id=run_id)


@when('the run "{run_id}" is undone without applying')
def step_undo_dry(context, run_id):
    _run(_scene(context), undo_commands.knowledge_run_undo, "--run-id", run_id, "--json")


@when('the run "{run_id}" is undone and applied')
@given('the run "{run_id}" was undone and applied')
@when('the run "{run_id}" is undone and applied again')
def step_undo(context, run_id):
    scene = _scene(context)
    scene["live_out"] = scene["dir"] / "live.json"
    _run(scene, undo_commands.knowledge_run_undo, "--run-id", run_id, "--apply", "--live-out", str(scene["live_out"]))


@when('the run "{run_id}" is restored and applied')
def step_restore(context, run_id):
    _run(_scene(context), undo_commands.knowledge_run_restore, "--run-id", run_id, "--apply")


@when("all wiki drafts are published")
def step_publish(context):
    _publish(context)


@then('every wiki page records "{run_id}" as the run that wrote it and the run that created it')
def step_recorded(context, run_id):
    pages = _pages(_scene(context))
    assert len(pages) == 2
    for row in pages.values():
        stamp = machine_write_of(row)
        assert (stamp["runId"], stamp["createdByRunId"]) == (run_id, run_id), stamp


@then('the page for "{title}" records "{latest}" as the latest writer and "{creator}" as its creator')
def step_latest(context, title, latest, creator):
    stamp = machine_write_of(_pages(_scene(context))[title])
    assert (stamp["runId"], stamp["createdByRunId"]) == (latest, creator), stamp


@then('the idea records "{run_id}" as its creator')
def step_idea_run(context, run_id):
    assert machine_write_of(context.idea_client.get_record("Item", context.idea["itemId"]))["createdByRunId"] == run_id


@then("the idea is still labelled as written by AI")
def step_idea_label(context):
    assert context.idea_client.get_record("Item", context.idea["itemId"])["versionCreatedBy"] == "AI"


@then("that command wrote no record")
def step_nothing(context):
    assert _scene(context)["writes"] == 0


@then("the report says it is a dry run and counts {count:d} pages to retire, both live")
def step_report(context, count):
    report = json.loads(_scene(context)["out"])
    assert (report["mode"], report["toRetire"], report["live"]) == ("dry-run", count, count), report


@then("both pages are still live")
def step_both_live(context):
    scene = _scene(context)
    assert all(_live(scene, title) for title in ("Acme Loom", "Beta Spool"))


@then("both pages are retired, are drafts and are not live")
def step_retired(context):
    scene = _scene(context)
    for title in ("Acme Loom", "Beta Spool"):
        row = _pages(scene)[title]
        assert row["stage"] == RETIRED_STAGE and row["status"] == "draft" and not _live(scene, title), (title, row["stage"], row["status"])


@then("both pages still exist")
def step_exist(context):
    assert set(_pages(_scene(context))) >= {"Acme Loom", "Beta Spool"}


@then("the list of pages to remove from the site holds both")
def step_live_out(context):
    scene = _scene(context)
    ids = {row["id"] for title, row in _pages(scene).items() if title in ("Acme Loom", "Beta Spool")}
    assert set(json.loads(scene["live_out"].read_text())) == ids


@then('the page for "{title}" is retired')
def step_one_retired(context, title):
    assert _pages(_scene(context))[title]["stage"] == RETIRED_STAGE


@then('the earlier run\'s pages "{a}" and "{b}" are still live')
def step_two_live(context, a, b):
    scene = _scene(context)
    assert _live(scene, a) and _live(scene, b) and _pages(scene)[a]["stage"] != RETIRED_STAGE


@then("the article is not retired")
def step_article(context):
    assert _scene(context)["client"].get_record("Item", "item-by-hand").get("stage") != RETIRED_STAGE


@then("both pages are drafts that are no longer retired")
def step_restored(context):
    scene = _scene(context)
    for title in ("Acme Loom", "Beta Spool"):
        row = _pages(scene)[title]
        assert row["stage"] != RETIRED_STAGE and row["status"] == "draft" and "undone" not in machine_write_of(row)


@then("both pages are live")
def step_live_again(context):
    scene = _scene(context)
    assert all(_live(scene, title) for title in ("Acme Loom", "Beta Spool"))
