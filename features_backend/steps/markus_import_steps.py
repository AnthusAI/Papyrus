from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.markus_import import DirMediaStore, ImportOptions, plan_import, run_import  # noqa: E402
from papyrus_content.publishing import ItemFields, save_item  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

FIXTURE = REPO_ROOT / "procedures" / "newsroom" / "tests" / "fixtures" / "markus-content"


def run(context, **option_changes):
    options = ImportOptions(content_dir=context.content, draft_dirs={"drafts": "articles"}, **option_changes)
    plan = plan_import(options, context.client, context.store)
    context.report = run_import(plan, context.client, context.store, apply=True)


@given("the fixture content directory")
def fixture_directory(context) -> None:
    context.temp = Path(tempfile.mkdtemp())
    context.add_cleanup(shutil.rmtree, context.temp, True)
    context.content = context.temp / "content"
    shutil.copytree(FIXTURE, context.content)
    context.store = DirMediaStore(context.temp / "bucket")
    context.client = FakeAuthoringClient()


@given("a file using the directive \"{name}\"")
def bad_file(context, name: str) -> None:
    (context.content / "articles" / "bad.md").write_text(f"---\ntitle: Bad\n---\n::{name}{{x=1}}\n")


@given("I import it")
@when("I import it")
def import_it(context) -> None:
    run(context)


@when("I import it again")
def import_again(context) -> None:
    context.client.calls.clear()
    run(context)


@given("the article \"{item_id}\" was edited in the CMS")
def edited_in_cms(context, item_id: str) -> None:
    import json

    metadata = json.loads(context.client.get_record("Item", item_id)["metadata"])
    save_item(
        context.client,
        ItemFields(
            type="article",
            slug="hello",
            section="articles",
            front_matter_yaml=metadata["frontMatterYaml"],
            body_markus="Edited in the CMS.\n",
            aliases=["/blog/hello-old"],
            id=item_id,
        ),
        actor="behave",
    )


@when("I import it again after changing its source")
def import_after_source_change(context) -> None:
    path = context.content / "articles" / "hello.md"
    path.write_text(path.read_text().replace("A first paragraph", "A source change"))
    run(context)


@then("{items:d} items are created and {media:d} media file is uploaded")
def counts(context, items: int, media: int) -> None:
    assert context.report.ok, context.report.errors
    assert context.report.created == items, context.report.created
    assert context.report.media_uploaded == media, context.report.media_uploaded


@then("the article \"{item_id}\" is published with the alias \"{alias}\"")
def published_with_alias(context, item_id: str, alias: str) -> None:
    item = context.client.get_record("Item", item_id)
    assert item["status"] == "published"
    assert context.client.get_record("PublishedItem", "published-" + item_id) is not None
    assert item["aliases"] == [alias], item["aliases"]


@then("everything is unchanged")
def everything_unchanged(context) -> None:
    assert (context.report.created, context.report.updated) == (0, 0)
    assert context.report.unchanged == 5
    assert context.report.media_uploaded == 0


@then("the article \"{item_id}\" is reported as edited in the CMS")
def reported_edited(context, item_id: str) -> None:
    assert context.report.skipped_edited_in_cms == [item_id], context.report.skipped_edited_in_cms


@then("its body is still the CMS edit")
def body_still_edited(context) -> None:
    assert context.client.get_record("Item", "item-articles-hello")["bodyMarkus"] == "Edited in the CMS.\n"


@then("the import fails naming \"{name}\"")
def import_fails(context, name: str) -> None:
    assert not context.report.ok
    assert any(name in message for message in context.report.errors), context.report.errors
