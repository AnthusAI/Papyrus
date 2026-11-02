from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands as snapshot_commands  # noqa: E402
from papyrus_content.knowledge_snapshot.keys import slug  # noqa: E402
from papyrus_content.knowledge_wiki import commands as wiki_commands  # noqa: E402
from papyrus_content.knowledge_wiki.sync import front_matter_of  # noqa: E402
from papyrus_content.publishing import published_item_id_for  # noqa: E402
from papyrus_content.wiki_stamp import WIKI_PAGE_ITEM_TYPE  # noqa: E402
from procedures.newsroom.tests.test_knowledge_wiki import WikiClient, publish_article  # noqa: E402

DAY = "2026-10-22"
VOCABULARY = "version: 1\npublication: example\nentity_kinds:\n{kinds}relation_types:\n  - {{key: made_by, label: made by}}\n"


def _scene(context):
    if not hasattr(context, "scene"):
        directory = tempfile.TemporaryDirectory()
        context.add_cleanup(directory.cleanup)
        client = WikiClient()
        for module in (snapshot_commands, wiki_commands):
            patcher = mock.patch.object(module, "create_authoring_client", lambda *args, **kwargs: (client, {}))
            patcher.start()
            context.add_cleanup(patcher.stop)
        context.scene = {"client": client, "dir": Path(directory.name), "entities": [], "out": "", "error": None, "retired": None}
    return context.scene


def _add(context, entities):
    scene = _scene(context)
    scene["entities"].extend(entities)
    publish_article(scene["client"], f"story-{len(scene['entities'])}", entities=entities)
    snapshot_commands.knowledge_publish_run(["--apply"])


def _parse_list(text):
    return [part.strip() for part in text.split(",") if part.strip()]


def _vocabulary(scene, kinds):
    body = "".join(f"  - {{key: {kind}, label: {kind.lower()}}}\n" for kind in _parse_list(kinds))
    path = scene["dir"] / f"vocabulary-{abs(hash(kinds))}.yml"
    path.write_text(VOCABULARY.format(kinds=body), encoding="utf-8")
    return str(path)


def _pages(scene):
    rows = scene["client"].tables.get("Item", {}).values()
    return {row["slug"]: row for row in rows if row.get("type") == WIKI_PAGE_ITEM_TYPE and row.get("section") == "wiki"}


def _page_titled(scene, title):
    found = [row for row in _pages(scene).values() if front_matter_of(row).get("title") == title]
    assert len(found) == 1, f"no single page titled {title!r}: {sorted(front_matter_of(row).get('title') for row in _pages(scene).values())}"
    return found[0]


def _live(scene, title):
    page = _page_titled(scene, title)
    return scene["client"].get_record("PublishedItem", published_item_id_for(page["lineageId"])) is not None


def _sync(context, kinds, *flags, apply=True):
    scene = _scene(context)
    arguments = list(flags)
    if kinds is not None:
        arguments += ["--vocabulary", _vocabulary(scene, kinds)]
    if apply:
        arguments.append("--apply")
    import contextlib
    import io

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            wiki_commands.knowledge_wiki_sync(arguments)
    except ValueError as error:
        scene["error"] = str(error)
    scene["out"] = buffer.getvalue()


def _publish_all(scene):
    wiki_commands.knowledge_wiki_publish(["--all-drafts", "--actor", "ai", "--apply", "--no-trigger", "--on", DAY])


@given('a graph with accepted entities "{a}" ({ak}), "{b}" ({bk}), "{c}" ({ck}), "{d}" ({dk}) and "{e}" ({ek})')
def step_graph(context, a, ak, b, bk, c, ck, d, dk, e, ek):
    _add(context, [(ak, a), (bk, b), (ck, c), (dk, d), (ek, e)])


@given('an accepted entity "{name}" ({kind})')
def step_one_entity(context, name, kind):
    _add(context, [(kind, name), *_scene(context)["entities"]])


@when("the wiki sync runs with no vocabulary")
def step_no_vocabulary(context):
    _sync(context, None)


@when('the wiki sync runs with a vocabulary of the kinds "{kinds}"')
def step_vocabulary(context, kinds):
    _sync(context, kinds)


@given('the wiki was synced and published with a vocabulary of the kinds "{kinds}"')
def step_synced_and_published(context, kinds):
    _sync(context, kinds)
    _publish_all(_scene(context))


@when('the wiki sync runs with a vocabulary of the kinds "{kinds}" and retiring')
@given('the wiki sync ran with a vocabulary of the kinds "{kinds}" and retiring')
def step_retiring(context, kinds):
    scene = _scene(context)
    scene["retired_file"] = scene["dir"] / "retired.json"
    _sync(context, kinds, "--retire", "--retired-out", str(scene["retired_file"]))


@when('the wiki sync dry run is made with a vocabulary of the kinds "{kinds}" and retiring')
def step_dry_run(context, kinds):
    _sync(context, kinds, "--retire", apply=False)


@when("the wiki sync runs with a vocabulary that declares no kinds")
def step_empty_vocabulary(context):
    scene = _scene(context)
    path = scene["dir"] / "empty.yml"
    path.write_text("version: 1\npublication: example\n", encoding="utf-8")
    try:
        wiki_commands.knowledge_wiki_sync(["--vocabulary", str(path), "--apply"])
    except ValueError as error:
        scene["error"] = str(error)


@when("every draft is published")
def step_publish(context):
    _publish_all(_scene(context))


@when('the knowledge snapshot is built with a vocabulary of the kinds "{kinds}"')
def step_snapshot(context, kinds):
    scene = _scene(context)
    out = scene["dir"] / "snapshot"
    snapshot_commands.knowledge_snapshot(
        ["--out", str(out), "--as-of", "2026-10-19", "--entity-href", "/wiki/{slug}/", "--vocabulary", _vocabulary(scene, kinds)]
    )
    index = json.loads((out / "_data" / "knowledge" / "index.json").read_text())
    scene["snapshot"] = {entity["name"]: entity for entity in index["entities"]}


@then("the wiki has pages for {names} only")
def step_pages(context, names):
    wanted = sorted(part.strip().strip('"') for part in names.replace(" and ", ",").split(",") if part.strip())
    found = sorted(front_matter_of(row)["title"] for row in _pages(_scene(context)).values())
    assert found == wanted, (found, wanted)


@then('the page for "{title}" keeps the entity key "{key}"')
def step_key(context, title, key):
    assert front_matter_of(_page_titled(_scene(context), title))["entityKey"] == key


@then('"{name}" links to its wiki page')
def step_links(context, name):
    assert _scene(context)["snapshot"][name]["href"] == f"/wiki/{slug(_scene(context)['snapshot'][name]['key'])}/"


@then('"{name}" has no link')
def step_no_link(context, name):
    assert _scene(context)["snapshot"][name]["href"] is None


@then('the snapshot has no entity "{name}"')
def step_no_entity(context, name):
    assert name not in _scene(context)["snapshot"]


@then('the page for "{title}" is no longer live and is marked retired')
def step_down(context, title):
    page = _page_titled(_scene(context), title)
    assert not _live(_scene(context), title) and page["status"] == "draft" and front_matter_of(page)["retired"] is True


@then('the pages for "{a}" and "{b}" are still live')
def step_others_live(context, a, b):
    assert _live(_scene(context), a) and _live(_scene(context), b)


@then("the sync reports one page to remove from the site")
def step_reports(context):
    scene = _scene(context)
    page = _page_titled(scene, "Aaron Cohen")
    assert json.loads(scene["retired_file"].read_text()) == [page["id"]]


@then('the page for "{title}" is not live')
def step_not_live(context, title):
    assert not _live(_scene(context), title)


@then('the page for "{title}" is still live')
def step_still_live(context, title):
    assert _live(_scene(context), title)


@then('the sync warns that "{title}" is no longer generated')
def step_warns(context, title):
    slug_text = slug(f"personauthor--{title.replace(' ', '')}")
    assert f"warning\twiki/{slug_text}: no longer generated" in _scene(context)["out"], _scene(context)["out"]


@then('the dry run lists the page for "{title}" as live and to be taken down')
def step_dry_lists(context, title):
    out = _scene(context)["out"]
    assert "mode\tdry-run" in out and "retire\twiki/personauthor-aaroncohen\tlive: taken down" in out, out


@then('the page for "{title}" is live and not marked retired')
def step_back(context, title):
    assert _live(_scene(context), title) and "retired" not in front_matter_of(_page_titled(_scene(context), title))


@then("the sync is refused because the vocabulary declares no entity kinds")
def step_refused(context):
    assert "declares no entity kinds" in (_scene(context)["error"] or "")
