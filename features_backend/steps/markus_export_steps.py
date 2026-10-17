from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.markus_export import EmptyExportError, export_content  # noqa: E402
from papyrus_content.markus_import import DirMediaStore  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

NOW = "2026-10-05T12:00:00Z"


def add_article(client, slug: str, *, publish: bool, aliases: list[str] | None = None) -> None:
    fields = ItemFields(
        type="article",
        slug=slug,
        section="articles",
        front_matter_yaml=f"title: {slug}\n",
        body_markus="Body.\n",
        aliases=aliases or [],
        id=f"item-articles-{slug}",
    )
    save_item(client, fields, actor="behave", now=NOW)
    if publish:
        publish_item(client, fields.id, actor="behave", now=NOW)


def prepare(context) -> None:
    context.workdir = Path(tempfile.mkdtemp(prefix="markus-export-"))
    context.add_cleanup(__import__("shutil").rmtree, context.workdir, True)
    context.out_dir = context.workdir / "out"
    context.store = DirMediaStore(context.workdir / "bucket")
    context.export_error = None


@given("a CMS with a published article and a draft article")
def cms_with_both(context) -> None:
    prepare(context)
    context.client = FakeAuthoringClient()
    add_article(context.client, "live", publish=True)
    add_article(context.client, "wip", publish=False)


@given("an empty CMS")
def empty_cms(context) -> None:
    prepare(context)
    context.client = FakeAuthoringClient()


@given('a CMS with a published article aliased from "{alias}"')
def cms_with_alias(context, alias: str) -> None:
    prepare(context)
    context.client = FakeAuthoringClient()
    add_article(context.client, "live", publish=True, aliases=[alias])


def run_export(context, drafts: bool) -> None:
    try:
        export_content(context.client, context.store, context.out_dir, drafts=drafts, now=NOW)
    except EmptyExportError as error:
        context.export_error = str(error)


@when("I export the published content")
def export_published(context) -> None:
    run_export(context, drafts=False)


@when("I export the drafts")
def export_drafts(context) -> None:
    run_export(context, drafts=True)


@then('the export contains "{path}"')
def export_contains(context, path: str) -> None:
    assert (context.out_dir / path).is_file(), path


@then('the export does not contain "{path}"')
def export_lacks(context, path: str) -> None:
    assert not (context.out_dir / path).exists(), path


@then('the export fails with "{message}"')
def export_fails(context, message: str) -> None:
    assert context.export_error and message in context.export_error, context.export_error


@then('the redirects map "{source}" to "{target}"')
def redirects_map(context, source: str, target: str) -> None:
    redirects = json.loads((context.out_dir / "_papyrus" / "redirects.json").read_text())
    assert {"from": source, "to": target, "status": 301} in redirects, redirects
