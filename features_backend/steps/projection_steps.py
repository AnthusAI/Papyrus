from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.markus_renderer import build as markus_build  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext, project, project_all, project_static  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item, unpublish_item  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.projection_fixtures import (  # noqa: E402
    ACTOR,
    NOW,
    WorkDirectory,
    copy_fixture_content,
    fixture_projector,
    full_build,
    item_fields_for,
    local_context,
    markdown_files,
    publish_content_tree,
    static_directory_for,
    tree_digests,
)


class FakeRedirectStore:
    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}

    def put_all(self, redirects: dict[str, str]) -> None:
        self.mapping.update(redirects)

    def delete_all(self, sources: list[str]) -> None:
        for source in sources:
            self.mapping.pop(source, None)


class FailingRenderProjector:
    def __init__(self, inner) -> None:
        self._inner = inner

    def item_pages(self, item, site):
        raise RuntimeError("the renderer failed")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def prepare_site(context, *, with_home_page: bool = True) -> None:
    context.work = WorkDirectory()
    context.add_cleanup(context.work.cleanup)
    context.content_root = copy_fixture_content(context.work.root, with_home_page=with_home_page)
    context.client = FakeAuthoringClient()
    context.static_directory = static_directory_for(context.content_root, context.work.root)
    context.projector = fixture_projector(context.static_directory)
    context.projection, context.writer = local_context(context.client, context.projector, context.work.root / "projected")
    context.redirect_store = None
    context.error = None


def item_id_for_article(slug: str) -> str:
    return f"item-articles-{slug}"


def article_path(context, slug: str) -> Path:
    return context.content_root / "articles" / f"{slug}.md"


@given("the projection fixture site is published")
def site_published(context) -> None:
    prepare_site(context)
    publish_content_tree(context.client, context.content_root)


@given("the projection fixture site is published without a hand-authored home page")
def site_published_without_home(context) -> None:
    prepare_site(context, with_home_page=False)
    publish_content_tree(context.client, context.content_root)


@given("the projection fixture site is published and projected")
def site_published_and_projected(context) -> None:
    site_published(context)
    project_all(context.projection)


@given("the projection fixture site is published and projected with a redirect store")
def site_published_and_projected_with_redirects(context) -> None:
    site_published(context)
    context.redirect_store = FakeRedirectStore()
    context.projection.redirect_store = context.redirect_store
    project_all(context.projection)


@given("the projection fixture items are saved as drafts")
def items_saved_as_drafts(context) -> None:
    prepare_site(context)
    context.draft_fields = [item_fields_for(context.content_root, path) for path in markdown_files(context.content_root)]
    for fields in context.draft_fields:
        save_item(context.client, fields, actor=ACTOR, now=NOW)


@when("I project everything to a local directory")
def project_everything(context) -> None:
    context.report = project_all(context.projection)


@when("the static files are projected")
def project_static_files(context) -> None:
    project_static(context.projection)


@when("each fixture item is published and projected in turn")
def publish_and_project_each(context) -> None:
    for fields in context.draft_fields:
        publish_item(context.client, fields.id, actor=ACTOR, now=NOW)
        project(context.projection, fields.id)


def retitle(path: Path, title: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        text = re.sub(r"^title:.*$", f"title: {title}", text, count=1, flags=re.M)
    else:
        text = f"---\ntitle: {title}\n---\n\n{text}"
    path.write_text(text, encoding="utf-8")


def republish_changed_article(context, slug: str, *, aliases: list[str] | None = None) -> None:
    fields = item_fields_for(context.content_root, article_path(context, slug))
    if aliases is not None:
        fields.aliases = aliases
    save_item(context.client, fields, actor=ACTOR, now=NOW)
    publish_item(context.client, fields.id, actor=ACTOR, now=NOW)


@when('the article "{slug}" is retitled "{title}" and projected')
def retitle_and_project(context, slug: str, title: str) -> None:
    retitle(article_path(context, slug), title)
    republish_changed_article(context, slug)
    context.writer.operations.clear()
    project(context.projection, item_id_for_article(slug))


@when('the article "{slug}" is retitled "{title}" and projected with a projector that fails to render')
def retitle_and_project_with_failure(context, slug: str, title: str) -> None:
    retitle(article_path(context, slug), title)
    republish_changed_article(context, slug)
    context.writer.operations.clear()
    failing = ProjectionContext(
        source=context.projection.source,
        projector=FailingRenderProjector(context.projector),
        writer=context.writer,
    )
    try:
        project(failing, item_id_for_article(slug))
    except RuntimeError as error:
        context.error = error


@when('the article "{slug}" is unpublished and projected')
def unpublish_and_project(context, slug: str) -> None:
    unpublish_item(context.client, item_id_for_article(slug), actor=ACTOR, now=NOW)
    article_path(context, slug).unlink()
    context.writer.operations.clear()
    project(context.projection, item_id_for_article(slug), unpublished=True)


@when('the article "{slug}" gains the alias "{alias}" and is projected')
def gain_alias_and_project(context, slug: str, alias: str) -> None:
    republish_changed_article(context, slug, aliases=[alias])
    project(context.projection, item_id_for_article(slug))


@then("the projected directory is identical to the full build of the fixture content")
def projected_equals_full_build(context) -> None:
    expected = context.work.root / "expected"
    full_build(context.content_root, expected)
    actual_digests = tree_digests(context.work.root / "projected")
    expected_digests = tree_digests(expected)
    missing = sorted(set(expected_digests) - set(actual_digests))
    extra = sorted(set(actual_digests) - set(expected_digests))
    different = sorted(path for path in set(actual_digests) & set(expected_digests) if actual_digests[path] != expected_digests[path])
    assert not (missing or extra or different), f"missing={missing} extra={extra} different={different}"
    context.expected_directory = expected


@then("every projected page links its assets with the version token of the static files")
def pages_carry_version_token(context) -> None:
    expected = context.work.root / "expected"
    full_build(context.content_root, expected)
    full_build_token = markus_build._css_version(expected / "css", expected / "assets")
    assert context.projector.version == full_build_token, (context.projector.version, full_build_token)
    pages = sorted((context.work.root / "projected").rglob("*.html"))
    assert pages
    for page in pages:
        tokens = set(re.findall(r"\?v=([0-9a-f]{12})", page.read_text(encoding="utf-8")))
        assert tokens == {context.projector.version}, (page.name, tokens)


@then('the page "{key}" does not exist')
def page_does_not_exist(context, key: str) -> None:
    assert not (context.work.root / "projected" / key).exists(), key


@then('"{first}" is written before "{second}"')
def written_before(context, first: str, second: str) -> None:
    operations = context.writer.operations
    assert ("put", first) in operations and ("put", second) in operations, operations
    assert operations.index(("put", first)) < operations.index(("put", second)), operations


@then('"{first}" is written before "{second}" is deleted')
def written_before_deleted(context, first: str, second: str) -> None:
    operations = context.writer.operations
    assert ("put", first) in operations and ("delete", second) in operations, operations
    assert operations.index(("put", first)) < operations.index(("delete", second)), operations


@then('the page "{key}" was written with the published version of "{slug}"')
def page_written_with_version(context, key: str, slug: str) -> None:
    published = context.client.get_record("PublishedItem", f"published-{item_id_for_article(slug)}")
    assert published["versionNumber"] >= 2
    assert context.writer.versions[key] == published["versionNumber"], (context.writer.versions, published["versionNumber"])


@then("the projection raised an error")
def projection_raised(context) -> None:
    assert context.error is not None


@then("no page was written by that projection")
def nothing_written(context) -> None:
    assert context.writer.operations == []


@then('the redirect store maps "{source}" to "{target}"')
def redirect_maps(context, source: str, target: str) -> None:
    assert context.redirect_store.mapping.get(source) == target, context.redirect_store.mapping


@then('the redirect store no longer maps "{source}"')
def redirect_gone(context, source: str) -> None:
    assert source not in context.redirect_store.mapping, context.redirect_store.mapping
