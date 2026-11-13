"""`papyrus stories retire`: the plan, the writes, and what the projection does with a retired Story."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papyrus_content.content_item_lifecycle import RETIRED_INTO_KEY, RETIRED_STAGE
from papyrus_content.cross_story_boilerplate import latest_stories
from papyrus_content.projection.engine import project_all, reconcile
from papyrus_content.projection.retired import RETIRED_KEY, RetiredEntry, final_target, registry_redirects
from papyrus_content.publishing import unpublish_item
from papyrus_content.story_retire import RetireRefused, apply_retire, plan_retire
from procedures.newsroom.tests.incremental_site import Site, add_item

OLD = "item-old"
POST = "item-post"
NEW = "item-new"


@pytest.fixture
def site(tmp_path: Path) -> Site:
    site = Site("feed", tmp_path)
    add_item(site, OLD, "old-article", section="articles")
    add_item(site, POST, "old-post", section="notes")
    add_item(site, NEW, "merged", section="articles")
    for item_id in (OLD, POST, NEW):
        site.project_item(item_id)
    return site


def retire(site: Site, story: str, target: str) -> None:
    plan = plan_retire(site.client, story, target)
    apply_retire(site.client, plan, actor="tester")
    site.published.discard(story)
    site.project_item(story)


def test_retire_redirects_an_article_and_a_post_in_another_folder(site: Site) -> None:
    retire(site, OLD, NEW)
    retire(site, POST, NEW)
    redirects = site.redirects.mapping
    assert redirects["/articles/old-article.html"] == "/articles/merged.html"
    assert redirects["/notes/old-post.html"] == "/articles/merged.html"
    assert not (Path(site.work) / "incremental" / "articles/old-article.html").exists()
    assert not (Path(site.work) / "incremental" / "notes/old-post.html").exists()


def test_retired_story_leaves_listings_and_sitemap(site: Site) -> None:
    retire(site, OLD, NEW)
    for key in ("index.html", "articles/index.html", "sitemap.xml"):
        path = Path(site.work) / "incremental" / key
        if path.exists():
            assert "old-article" not in path.read_text()


def test_retire_records_stage_and_target_and_keeps_every_version(site: Site) -> None:
    before = len(site.client.list_by_index("itemsByLineageAndVersion", OLD))
    retire(site, OLD, NEW)
    rows = site.client.list_by_index("itemsByLineageAndVersion", OLD)
    assert len(rows) == before
    head = site.client.get_record("Item", OLD)
    assert head["stage"] == RETIRED_STAGE
    assert json.loads(head["metadata"])[RETIRED_INTO_KEY]["toLineageId"] == NEW


def test_alias_and_renamed_addresses_redirect(site: Site) -> None:
    site.drafts[OLD].aliases = ["old/first-address"]
    site.publish(OLD)
    site.project_item(OLD)
    unpublish_item(site.client, OLD, actor="tester")
    site.published.discard(OLD)
    site.project_item(OLD)
    site.drafts[OLD].slug = "old-article-renamed"
    site.publish(OLD)
    site.project_item(OLD)
    retire(site, OLD, NEW)
    redirects = site.redirects.mapping
    assert redirects["/old/first-address"] == "/articles/merged.html"
    assert redirects["/articles/old-article-renamed.html"] == "/articles/merged.html"
    assert redirects["/articles/old-article.html"] == "/articles/merged.html"


def test_redirect_follows_a_renamed_target_without_a_chain(site: Site) -> None:
    retire(site, OLD, NEW)
    unpublish_item(site.client, NEW, actor="tester")
    site.published.discard(NEW)
    site.project_item(NEW)
    site.drafts[NEW].slug = "merged-renamed"
    site.publish(NEW)
    site.project_item(NEW)
    redirects = site.redirects.mapping
    assert redirects["/articles/old-article.html"] == "/articles/merged-renamed.html"
    assert redirects["/articles/merged.html"] == "/articles/merged-renamed.html"
    assert all(target not in redirects for target in redirects.values())


def test_a_full_projection_and_a_reconcile_keep_the_redirects(site: Site) -> None:
    retire(site, OLD, NEW)
    site.redirects.mapping.clear()
    report = reconcile(site.context, dry_run=True)
    assert report.redirects_repaired >= 1
    project_all(site.context)
    assert site.redirects.mapping["/articles/old-article.html"] == "/articles/merged.html"


def test_undo_restores_the_page_and_removes_the_redirects(site: Site) -> None:
    retire(site, OLD, NEW)
    plan = plan_retire(site.client, OLD, None, undo=True)
    assert plan.republish
    apply_retire(site.client, plan, actor="tester")
    site.published.add(OLD)
    site.project_item(OLD)
    assert "/articles/old-article.html" not in site.redirects.mapping
    assert (Path(site.work) / "incremental" / "articles/old-article.html").exists()
    assert site.client.get_record("Item", OLD)["stage"] == "published"
    assert json.loads(site.store.get(RETIRED_KEY))["entries"] == []


def test_retire_refuses_a_missing_unpublished_self_or_retired_target(site: Site) -> None:
    with pytest.raises(RetireRefused, match="No story found"):
        plan_retire(site.client, OLD, "item-nowhere")
    with pytest.raises(RetireRefused, match="itself"):
        plan_retire(site.client, OLD, OLD)
    site.drafts["item-draft"] = site.drafts[NEW].__class__(slug="draft-only", section="articles", title="Draft", date="2026-03-01", description="d", body="b\n")
    site.save("item-draft")
    with pytest.raises(RetireRefused, match="not published"):
        plan_retire(site.client, OLD, "item-draft")
    retire(site, POST, NEW)
    with pytest.raises(RetireRefused, match="retired and redirects to"):
        plan_retire(site.client, OLD, POST)


def test_retiring_the_target_of_a_retired_story_follows_the_chain_to_the_end(site: Site) -> None:
    retire(site, OLD, POST)
    retire(site, POST, NEW)
    redirects = site.redirects.mapping
    assert redirects["/articles/old-article.html"] == "/articles/merged.html"
    assert redirects["/notes/old-post.html"] == "/articles/merged.html"


def test_the_same_target_again_changes_nothing(site: Site) -> None:
    retire(site, OLD, NEW)
    assert plan_retire(site.client, OLD, NEW).unchanged


def test_a_story_that_was_never_published_is_refused(site: Site) -> None:
    site.drafts["item-idea"] = site.drafts[NEW].__class__(slug="idea", section="articles", title="Idea", date="2026-03-01", description="d", body="b\n")
    site.save("item-idea")
    with pytest.raises(RetireRefused, match="never published"):
        plan_retire(site.client, "item-idea", NEW)


def test_boilerplate_check_ignores_a_retired_story() -> None:
    rows = [
        {"id": "a", "lineageId": "a", "versionState": "current", "versionNumber": 1, "slug": "a", "bodyMarkus": "text", "stage": "copywriting"},
        {"id": "b", "lineageId": "b", "versionState": "current", "versionNumber": 1, "slug": "b", "bodyMarkus": "text", "stage": RETIRED_STAGE},
    ]
    assert [story.lineage_id for story in latest_stories(rows)] == ["a"]


class _Projector:
    """Pages at <section>/<slug>.html with a Markdown twin at <section>/<slug>.md."""

    def item_page_paths(self, summary):
        base = f"{summary.section}/{summary.slug}"
        return (f"{base}.html", f"{base}.md")


def test_the_markdown_twin_redirects_to_the_targets_twin() -> None:
    from papyrus_content.projection.model import ItemSummary, SiteIndex

    target = ItemSummary("t", "article", "articles", "merged", "articles/merged.md", 1, "T", None, {}, (), None, lineage_id="lin-t")
    site = SiteIndex(items=(target,), load_item=lambda _id: None)
    entry = RetiredEntry("o", "lin-o", "lin-t", ("notes/old.html", "notes/old.md"), ("legacy/old",))
    found = registry_redirects(_Projector(), site, {"lin-o": entry})
    assert found["/notes/old.html"] == "/articles/merged.html"
    assert found["/notes/old.md"] == "/articles/merged.md"
    assert found["/legacy/old"] == "/articles/merged.html"


def test_a_retired_target_is_followed_and_a_loop_ends() -> None:
    from papyrus_content.projection.model import ItemSummary, SiteIndex

    final = ItemSummary("t", "article", "articles", "merged", "articles/merged.md", 1, "T", None, {}, (), None, lineage_id="lin-t")
    site = SiteIndex(items=(final,), load_item=lambda _id: None)
    registry = {
        "lin-a": RetiredEntry("a", "lin-a", "lin-b", ()),
        "lin-b": RetiredEntry("b", "lin-b", "lin-t", ()),
        "lin-x": RetiredEntry("x", "lin-x", "lin-y", ()),
        "lin-y": RetiredEntry("y", "lin-y", "lin-x", ()),
    }
    assert final_target(site, registry, "lin-a").lineage_id == "lin-t"
    assert final_target(site, registry, "lin-x") is None
