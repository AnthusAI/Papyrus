from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.content_item_lifecycle import RETIRED_STAGE  # noqa: E402
from papyrus_content.cross_story_boilerplate import latest_stories  # noqa: E402
from papyrus_content.projection.model import ItemSummary, SiteIndex  # noqa: E402
from papyrus_content.projection.retired import RetiredEntry, registry_redirects  # noqa: E402
from papyrus_content.publishing import unpublish_item  # noqa: E402
from papyrus_content.story_retire import RetireRefused, apply_retire, plan_retire  # noqa: E402
from procedures.newsroom.tests.incremental_site import Draft, Site, add_item  # noqa: E402


def item_id_for(slug: str) -> str:
    return f"item-{slug}"


def retire(context, slug: str, target: str) -> None:
    plan = plan_retire(context.site.client, item_id_for(slug), item_id_for(target))
    apply_retire(context.site.client, plan, actor="tester")
    context.site.published.discard(item_id_for(slug))
    context.site.project_item(item_id_for(slug))


def snapshot(context) -> dict:
    return copy.deepcopy(context.site.client.tables)


@given('a site with the published stories "{first}" and "{second}" in articles and "{third}" in notes')
def stories_site(context, first: str, second: str, third: str) -> None:
    context.work = tempfile.TemporaryDirectory()
    context.add_cleanup(context.work.cleanup)
    context.site = Site("feed", Path(context.work.name))
    for slug, section in ((first, "articles"), (second, "articles"), (third, "notes")):
        add_item(context.site, item_id_for(slug), slug, section=section)
        context.site.project_item(item_id_for(slug))
    context.site.drafts[item_id_for("draft-only")] = Draft(
        slug="draft-only", section="articles", title="Draft", date="2026-03-01", description="Not yet", body="Not yet.\n"
    )
    context.site.save(item_id_for("draft-only"))
    context.refusal = None


@given('the story "{slug}" was served at an alias "{alias}" and then renamed to "{new_slug}"')
def aliased_and_renamed(context, slug: str, alias: str, new_slug: str) -> None:
    site, item_id = context.site, item_id_for(slug)
    site.drafts[item_id].aliases = [alias]
    site.publish(item_id)
    site.project_item(item_id)
    unpublish_item(site.client, item_id, actor="tester")
    site.published.discard(item_id)
    site.project_item(item_id)
    site.drafts[item_id].slug = new_slug
    site.publish(item_id)
    site.project_item(item_id)


@given('the story "{slug}" is retired into "{target}"')
@when('the story "{slug}" is retired into "{target}"')
def story_retired(context, slug: str, target: str) -> None:
    retire(context, slug, target)


@when('the story "{slug}" is renamed to "{new_slug}" and projected')
def target_renamed(context, slug: str, new_slug: str) -> None:
    site, item_id = context.site, item_id_for(slug)
    unpublish_item(site.client, item_id, actor="tester")
    site.published.discard(item_id)
    site.project_item(item_id)
    site.drafts[item_id].slug = new_slug
    site.publish(item_id)
    site.project_item(item_id)


@then('the story "{slug}" is in the retired stage and still has its versions')
def retired_with_versions(context, slug: str) -> None:
    client = context.site.client
    rows = client.list_by_index("itemsByLineageAndVersion", item_id_for(slug))
    assert rows, "the story's versions are gone"
    assert client.get_record("Item", item_id_for(slug))["stage"] == RETIRED_STAGE


@then('the story "{slug}" is in the published stage')
def published_stage(context, slug: str) -> None:
    assert context.site.client.get_record("Item", item_id_for(slug))["stage"] == "published"


@then('the stored pages "{first}" and "{second}" and "{third}" do not mention "{text}"')
def pages_lack(context, first: str, second: str, third: str, text: str) -> None:
    for key in (first, second, third):
        path = Path(context.work.name) / "incremental" / key
        assert path.is_file(), f"{key} was never written"
        assert text not in path.read_text(encoding="utf-8"), key


@then('no redirect points at another redirect')
def no_chain(context) -> None:
    mapping = context.site.redirects.mapping
    assert not [target for target in mapping.values() if target in mapping], mapping


@when('retiring "{slug}" into "{target}" is attempted')
def retire_attempted(context, slug: str, target: str) -> None:
    if target == "retired-one":
        add_item(context.site, item_id_for("retired-one"), "retired-one", section="notes")
        context.site.project_item(item_id_for("retired-one"))
        retire(context, "retired-one", "merged")
    context.before = snapshot(context)
    try:
        plan_retire(context.site.client, item_id_for(slug), item_id_for(target))
        context.refusal = None
    except RetireRefused as error:
        context.refusal = str(error)


@then('the retirement is refused saying "{reason}"')
def refused_saying(context, reason: str) -> None:
    assert context.refusal is not None and reason in context.refusal, context.refusal


@then("no record changed")
def nothing_changed(context) -> None:
    assert snapshot(context) == context.before


@then('the cross-story boilerplate check does not compare "{slug}"')
def boilerplate_skips(context, slug: str) -> None:
    rows = [row for row in context.site.client.list_by_index("itemsByLineageAndVersion", item_id_for(slug))]
    rows += context.site.client.list_by_index("itemsByLineageAndVersion", item_id_for("merged"))
    lineages = [story.lineage_id for story in latest_stories(rows)]
    assert item_id_for(slug) not in lineages and item_id_for("merged") in lineages, lineages


@when('the command "{command}" is run')
def command_run(context, command: str) -> None:
    from papyrus_content import graphql_authoring
    from papyrus_content.story_retire import stories_retire

    context.before = snapshot(context)
    original = graphql_authoring.create_authoring_client
    graphql_authoring.create_authoring_client = lambda *args, **kwargs: (context.site.client, {"sub": "tester"})
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            stories_retire(command.split()[2:])
    finally:
        graphql_authoring.create_authoring_client = original
    context.printed = output.getvalue().splitlines()


@then('the command printed a line containing "{text}"')
def printed_line(context, text: str) -> None:
    assert any(text in line for line in context.printed), context.printed


@when('the retirement of "{slug}" is undone')
def retirement_undone(context, slug: str) -> None:
    plan = plan_retire(context.site.client, item_id_for(slug), None, undo=True)
    apply_retire(context.site.client, plan, actor="tester")
    context.site.published.add(item_id_for(slug))
    context.site.project_item(item_id_for(slug))


@then('the page "{key}" is served again')
def page_exists(context, key: str) -> None:
    assert (Path(context.work.name) / "incremental" / key).is_file(), key


@then('the site redirect store has no redirect from "{source}"')
def no_redirect_from(context, source: str) -> None:
    assert source not in context.site.redirects.mapping, context.site.redirects.mapping


@then('retiring "{slug}" into "{target}" again plans no change')
def plans_no_change(context, slug: str, target: str) -> None:
    assert plan_retire(context.site.client, item_id_for(slug), item_id_for(target)).unchanged


class TwinProjector:
    """Pages at <section>/<slug>.html with a Markdown twin at <section>/<slug>.md, as the standard projector writes them."""

    def item_page_paths(self, summary):
        base = f"{summary.section}/{summary.slug}"
        return (f"{base}.html", f"{base}.md")


@given("a site whose pages have Markdown twins")
def twin_site(context) -> None:
    target = ItemSummary("merged", "article", "articles", "merged", "articles/merged.md", 1, "Merged", None, {}, (), None, lineage_id="lineage-merged")
    site = SiteIndex(items=(target,), load_item=lambda _item_id: None)
    entry = RetiredEntry("old", "lineage-old", "lineage-merged", ("notes/old.html", "notes/old.md"))
    context.twin_redirects = registry_redirects(TwinProjector(), site, {"lineage-old": entry})


@then('the retired story\'s "{key}" redirects to "{target}"')
def twin_redirects(context, key: str, target: str) -> None:
    assert context.twin_redirects.get("/" + key) == target, context.twin_redirects
