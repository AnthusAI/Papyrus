from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import (  # noqa: E402
    DeletionGuard,
    DeletionRefused,
    ProjectionContext,
    project_all,
    reconcile,
)
from papyrus_content.projection.item_state import ItemState, read_item_state, write_item_state  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from papyrus_content.publishing import unpublish_item  # noqa: E402
from procedures.newsroom.tests.incremental_site import ACTOR, NOW, seeded_site  # noqa: E402
from procedures.newsroom.tests.projection_fixtures import tree_digests  # noqa: E402
from procedures.newsroom.tests.test_projection_deletion_guard import DroppingProjector  # noqa: E402


def item_id_of(slug: str) -> str:
    return "item-" + slug.rsplit("-", 1)[1]


def guarded_context(context, *, projector=None, guard=DeletionGuard()) -> ProjectionContext:
    site = context.site
    return ProjectionContext(
        source=PublishedContentSource(site.client),
        projector=projector or site.projector,
        writer=site.store,
        redirect_store=site.redirects,
        deletion_guard=guard,
    )


def stored_pages(context) -> dict[str, str]:
    return tree_digests(Path(context.work.name) / "incremental")


def attempt(context, action) -> None:
    context.before = stored_pages(context)
    context.refusal = None
    try:
        action()
    except DeletionRefused as refusal:
        context.refusal = refusal


@given("a guarded site of three published articles that has been projected")
def guarded_site(context) -> None:
    context.work = tempfile.TemporaryDirectory()
    context.add_cleanup(context.work.cleanup)
    context.site = seeded_site("generic", Path(context.work.name))


@given('the site remembers thirty more pages for the article "{slug}"')
def remember_more_pages(context, slug: str) -> None:
    state = read_item_state(context.site.store, item_id_of(slug))
    stray = tuple(f"articles/stray-{number}.html" for number in range(30))
    for key in stray:
        context.site.store.put(key, b"<html></html>")
    write_item_state(context.site.store, ItemState(summary=state.summary, page_keys=(*state.page_keys, *stray)))


@when('the site configuration stops placing the article "{slug}" and the whole site is projected')
def drop_and_project(context, slug: str) -> None:
    projector = DroppingProjector(context.site.projector, {item_id_of(slug)})
    attempt(context, lambda: project_all(guarded_context(context, projector=projector)))


@when('the site configuration stops placing the article "{slug}" and the whole site is projected with deletions allowed')
def drop_and_project_allowed(context, slug: str) -> None:
    projector = DroppingProjector(context.site.projector, {item_id_of(slug)})
    attempt(context, lambda: project_all(guarded_context(context, projector=projector, guard=None)))


@when('the site configuration stops placing the article "{slug}" and the site is reconciled')
def drop_and_reconcile(context, slug: str) -> None:
    projector = DroppingProjector(context.site.projector, {item_id_of(slug)})
    attempt(context, lambda: reconcile(guarded_context(context, projector=projector)))


@when("the whole site is projected")
def project_everything(context) -> None:
    attempt(context, lambda: project_all(guarded_context(context)))


@when('the article "{slug}" is renamed to "{new_slug}" and the whole site is projected')
def rename_and_project(context, slug: str, new_slug: str) -> None:
    item_id = item_id_of(slug)
    unpublish_item(context.site.client, item_id, actor=ACTOR, now=NOW)
    context.site.drafts[item_id].slug = new_slug
    context.site.publish(item_id)
    attempt(context, lambda: project_all(guarded_context(context)))


@when('the article "{slug}" is unpublished and the site is reconciled')
def unpublish_and_reconcile(context, slug: str) -> None:
    unpublish_item(context.site.client, item_id_of(slug), actor=ACTOR, now=NOW)
    attempt(context, lambda: reconcile(guarded_context(context)))


@then("the projection is refused")
def is_refused(context) -> None:
    assert context.refusal is not None, "the projection went ahead"


@then("the projection is not refused")
def is_not_refused(context) -> None:
    assert context.refusal is None, str(context.refusal)


@then('the refusal names the page "{key}" and the item "{item_id}"')
def refusal_names(context, key: str, item_id: str) -> None:
    message = str(context.refusal)
    assert key in message and item_id in message, message


@then("the refusal says to check that --static-dir is a current checkout or to pass --allow-deletions")
def refusal_remedy(context) -> None:
    message = str(context.refusal)
    assert "--static-dir is a current checkout" in message and "--allow-deletions" in message, message


@then('the refusal counts {count:d} pages under "{prefix}"')
def refusal_counts(context, count: int, prefix: str) -> None:
    assert f"{prefix} {count}" in str(context.refusal), str(context.refusal)


@then("the site store is exactly as it was")
def store_unchanged(context) -> None:
    assert stored_pages(context) == context.before


@then('the page "{key}" exists')
def page_exists(context, key: str) -> None:
    assert key in stored_pages(context), key
