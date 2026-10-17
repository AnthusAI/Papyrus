from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import ProjectionContext, project, reconcile  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from papyrus_content.publishing import unpublish_item  # noqa: E402
from procedures.newsroom.tests.incremental_site import (  # noqa: E402
    ACTOR,
    NOW,
    Draft,
    FailingWriter,
    HookedSource,
    Site,
    add_item,
)

SLUGS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]


def item_id_for(slug: str) -> str:
    return f"item-{slug}"


def site_of(context) -> Site:
    return context.site


def project_item(context, slug: str) -> None:
    context.site.touched.clear()
    context.reports = [project(context.site.context, item_id_for(slug))]
    context.site.touched |= set(context.reports[0].written) | set(context.reports[0].deleted)


@given("a newest-first site of six published articles that has been projected")
def six_articles(context) -> None:
    context.work = tempfile.TemporaryDirectory()
    context.add_cleanup(context.work.cleanup)
    context.site = Site("feed", Path(context.work.name))
    for number, slug in enumerate(SLUGS):
        add_item(context.site, item_id_for(slug), slug, date=f"2026-01-{number + 1:02d}")
        context.site.project_item(item_id_for(slug))
    context.operations_before = len(context.site.store.operations)
    context.error = None


def change_and_project(context, slug: str, change) -> None:
    draft = context.site.drafts[item_id_for(slug)]
    change(draft)
    context.site.publish(item_id_for(slug))
    context.site.store.operations.clear()
    project_item(context, slug)


@when('the feed article "{slug}" is retitled and projected')
def retitle(context, slug: str) -> None:
    change_and_project(context, slug, lambda draft: setattr(draft, "title", "A Different Title"))


@when('the body of the feed article "{slug}" is edited and projected')
def edit_body(context, slug: str) -> None:
    change_and_project(context, slug, lambda draft: setattr(draft, "body", "A different body.\n"))


@when('the feed article "{slug}" is hidden from the feed and projected')
def hide(context, slug: str) -> None:
    change_and_project(context, slug, lambda draft: setattr(draft, "hidden", True))


@when('a new article "{slug}" is published and projected')
def publish_new(context, slug: str) -> None:
    add_item(context.site, item_id_for(slug), slug, date="2026-02-01")
    context.site.store.operations.clear()
    project_item(context, slug)


def unpublish(context, slug: str) -> None:
    unpublish_item(context.site.client, item_id_for(slug), actor=ACTOR, now=NOW)
    context.site.published.discard(item_id_for(slug))


@given('the feed article "{slug}" is unpublished and projected')
@when('the feed article "{slug}" is unpublished and projected')
def unpublish_and_project(context, slug: str) -> None:
    unpublish(context, slug)
    context.site.store.operations.clear()
    project_item(context, slug)


@when('the feed article "{slug}" is republished as "{new_slug}" and projected')
def republish_renamed(context, slug: str, new_slug: str) -> None:
    context.site.drafts[item_id_for(slug)].slug = new_slug
    context.site.publish(item_id_for(slug))
    context.site.store.operations.clear()
    project_item(context, slug)


@when('two new articles "{first}" and "{second}" are published at the same time')
def publish_two_at_once(context, first: str, second: str) -> None:
    site = context.site
    add_item(site, item_id_for(first), first, date="2026-02-01")

    def second_publish_completes() -> None:
        add_item(site, item_id_for(second), second, date="2026-02-02")
        project(site.context, item_id_for(second))

    racing = ProjectionContext(
        source=HookedSource(site.client, {1: second_publish_completes}),
        projector=site.projector,
        writer=site.store,
        redirect_store=site.redirects,
    )
    context.reports = [project(racing, item_id_for(first))]
    assert context.reports[0].rounds >= 2, "the first publish never noticed the second"


@when('the feed article "{slug}" is retitled and its projection fails after the first write')
def retitle_and_fail(context, slug: str) -> None:
    site = context.site
    site.drafts[item_id_for(slug)].title = "A Different Title"
    site.publish(item_id_for(slug))
    failing = ProjectionContext(
        source=PublishedContentSource(site.client),
        projector=site.projector,
        writer=FailingWriter(site.store, 2),
        redirect_store=site.redirects,
    )
    try:
        project(failing, item_id_for(slug))
    except RuntimeError as error:
        context.error = error
    assert context.error is not None


@when("the projection is run again")
def run_again(context) -> None:
    project_item(context, "bravo")


@when('the feed article "{slug}" is retitled but its projection never runs')
def retitle_without_projection(context, slug: str) -> None:
    context.site.drafts[item_id_for(slug)].title = "A Different Title"
    context.site.publish(item_id_for(slug))


@when('the feed article "{slug}" is unpublished but its projection never runs')
def unpublish_without_projection(context, slug: str) -> None:
    unpublish(context, slug)


@given('a stray page "{key}" in the site store')
def stray_page(context, key: str) -> None:
    context.site.store.put(key, b"<p>stale</p>", version=1)


@when("reconcile runs")
def run_reconcile(context) -> None:
    context.site.store.operations.clear()
    context.reconcile_report = reconcile(context.site.context)


@then('a dry run of reconcile reports the item "{slug}" as stale')
def dry_run_reports(context, slug: str) -> None:
    report = reconcile(context.site.context, dry_run=True)
    assert item_id_for(slug) in report.stale_items, report.to_dict()


@then("a dry run of reconcile finds no drift")
def dry_run_clean(context) -> None:
    report = reconcile(context.site.context, dry_run=True)
    assert not report.drift, report.to_dict()


@then('the pages written were exactly "{expected}"')
def written_exactly(context, expected: str) -> None:
    written = sorted(key for kind, key in context.site.store.operations if kind == "put")
    assert written == sorted(part.strip() for part in expected.split(",")), written


@then("a fresh projection of everything finds nothing to change")
def nothing_to_change(context) -> None:
    incremental_pages, incremental_redirects = context.site.incremental()
    full_pages, _ = context.site.full()
    assert incremental_pages == full_pages, sorted(
        key for key in set(incremental_pages) | set(full_pages) if incremental_pages.get(key) != full_pages.get(key)
    )
    assert incremental_redirects == context.site.full_with_remembered_moves(), incremental_redirects


def page_text(context, key: str) -> str | None:
    path = Path(context.work.name) / "incremental" / key
    return path.read_text(encoding="utf-8") if path.is_file() else None


@then('the page "{key}" does not mention "{text}"')
def page_lacks(context, key: str, text: str) -> None:
    assert text not in (page_text(context, key) or ""), key


@then('the page "{key}" mentions "{text}"')
def page_mentions(context, key: str, text: str) -> None:
    assert text in (page_text(context, key) or ""), key


@then('the page "{key}" no longer exists')
def page_gone(context, key: str) -> None:
    assert page_text(context, key) is None, key


@then('the site store wrote "{first}" before deleting "{second}"')
def written_before_deleted(context, first: str, second: str) -> None:
    operations = context.site.store.operations
    assert ("put", first) in operations and ("delete", second) in operations, operations
    assert operations.index(("put", first)) < operations.index(("delete", second)), operations


@then('the site redirect store maps "{source}" to "{target}"')
def redirect_maps(context, source: str, target: str) -> None:
    assert context.site.redirects.mapping.get(source) == target, context.site.redirects.mapping
