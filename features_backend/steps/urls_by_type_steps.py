from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import section_migration  # noqa: E402
from papyrus_content.content_item_lifecycle import build_new_content_item_version  # noqa: E402
from papyrus_content.ideas.items import section_id_of  # noqa: E402
from papyrus_content.projection import url_compare  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site, item, settings  # noqa: E402

STYLE = {"style": "directory"}


def quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


def story(slug: str, section: str | None, **front):
    front.setdefault("date", "2026-03-01")
    return item(slug, section=section, **front)


def project(context) -> None:
    urls = {**STYLE, **context.urls}
    site = cms_site(settings(urls=urls, listings={"types": ["article", "post", "page"], **context.listings}, **context.extra), context.items)
    context.add_cleanup(site.cleanup)
    context.site = site


def sitemap_text(site) -> str:
    return site.text("sitemap-0.xml" if "sitemap-0.xml" in site.tree else "sitemap.xml")


def reset(context) -> None:
    context.urls, context.listings, context.extra, context.items = {}, {}, {}, []


@given('a site whose articles have the base "{base}" in the type settings')
def articles_type_base(context, base: str) -> None:
    reset(context)
    context.urls["types"] = {"article": {"base": base, "label": "Articles"}}


@given('a site with the type settings article "{articles}" and post "{posts}"')
def articles_and_posts(context, articles: str, posts: str) -> None:
    reset(context)
    context.urls["types"] = {"article": {"base": articles}, "post": {"base": posts}}


@given('a site whose articles have the base "{base}" and which declares the section "{section}" with the base "{section_base}"')
def type_and_section(context, base: str, section: str, section_base: str) -> None:
    reset(context)
    context.urls["types"] = {"article": {"base": base}}
    context.urls["sections"] = {section: {"base": section_base}}


@given('a site whose section "{section}" has the base "{base}" and answers to the stored value "{alias}"')
def section_with_alias(context, section: str, base: str, alias: str) -> None:
    reset(context)
    context.urls["sections"] = {section: {"base": base, "label": section.upper(), "aliases": [alias]}}


@given('a site that keys its articles on the section "{section}"')
def articles_on_section(context, section: str) -> None:
    reset(context)
    context.urls["sections"] = {section: {"base": section, "label": "Articles"}}


@given('a site whose tag pages cover only the type "{kind}"')
def tags_by_type(context, kind: str) -> None:
    reset(context)
    context.urls["types"] = {"article": {"base": "articles"}}
    context.urls["sections"] = {"platform": {"base": "platform"}}
    context.listings["tagSelect"] = {"types": [kind]}


@given('an article about "{first}", an article with no section and an article whose section is the old placeholder')
def three_articles(context, first: str) -> None:
    context.items = [story("topical", first), story("sectionless", None, date="2026-03-02"), story("placeholder", "unsectioned", date="2026-03-03")]


@given('an article about "{first}" and an article about "{second}"')
def two_articles(context, first: str, second: str) -> None:
    context.items = [story("first", first), story("second", second, date="2026-03-02")]


@given('an article and a post about "{section}"')
def article_and_post(context, section: str) -> None:
    context.items = [story("an-article", section), story("a-post", section, type="post", date="2026-03-02")]


@given('a collection that selects the section "{section}"')
def topic_collection(context, section: str) -> None:
    context.extra["collections"] = [{"id": "topic", "select": {"sections": [section]}}]


@given('two articles stored with the section "{section}"')
def two_stored(context, section: str) -> None:
    context.stored_section = section
    context.items = [story("first", section), story("second", section, date="2026-03-02")]


@given('one article stored with the section "{first}" and one with the section "{second}"')
def one_and_one(context, first: str, second: str) -> None:
    context.items = [story("by-title", first), story("by-id", second, date="2026-03-02")]


@given('an article tagged "{tag}" and a page tagged "{other}"')
def tagged(context, tag: str, other: str) -> None:
    context.items = [story("an-article", None, tags=[tag]), item("a-page", section="platform", type="page", tags=[other])]


@when("the URL layout is projected")
def projected(context) -> None:
    project(context)


@then('the three articles have pages under "/{base}/"')
def three_pages(context, base: str) -> None:
    keys = set(context.site.tree)
    for slug in ("topical", "sectionless", "placeholder"):
        assert f"{base}/{slug}/index.html" in keys, sorted(keys)


@then('no page is published under "/{base}/"')
def none_under(context, base: str) -> None:
    assert not [key for key in context.site.tree if key.startswith(f"{base}/")]


@then("the articles listing, the sitemap and the feed name the three addresses")
def listing_sitemap_feed(context) -> None:
    listing = context.site.text("articles/index.html")
    assert sorted(cards(listing)) == ["placeholder", "sectionless", "topical"]
    for slug in ("topical", "sectionless", "placeholder"):
        assert f"/articles/{slug}/" in sitemap_text(context.site) and f"/articles/{slug}/" in context.site.text("feed.xml")


@then('the collection lists only the article about "{section}"')
def collection_only(context, section: str) -> None:
    assert cards(context.site.text("topic/index.html")) == ["first"]


@then("the articles listing has both articles")
def both_articles(context) -> None:
    assert cards(context.site.text("articles/index.html")) == ["second", "first"]


@then('the article is published under "/{article_base}/" and the post under "/{post_base}/"')
def article_and_post_pages(context, article_base: str, post_base: str) -> None:
    keys = set(context.site.tree)
    assert f"{article_base}/an-article/index.html" in keys and f"{post_base}/a-post/index.html" in keys
    assert cards(context.site.text(f"{post_base}/index.html")) == ["a-post"]


@then("the same files are written as for a site that keys them on the type with no stored section")
def same_files(context) -> None:
    other = cms_site(
        settings(urls={**STYLE, "types": {"article": {"base": "articles", "label": "Articles"}}}, listings={"types": ["article", "post", "page"]}),
        [story("first", None), story("second", None, date="2026-03-02")],
    )
    context.add_cleanup(other.cleanup)
    assert sorted(context.site.tree) == sorted(other.tree)
    assert sitemap_text(context.site) == sitemap_text(other)


@then('the article about "{first}" is published under "/{first_base}/" and the other under "/{second_base}/"')
def declared_wins(context, first: str, first_base: str, second_base: str) -> None:
    keys = set(context.site.tree)
    assert f"{first_base}/first/index.html" in keys and f"{second_base}/second/index.html" in keys


@then('both articles are published under "/{base}/" and listed together')
def both_under_alias(context, base: str) -> None:
    keys = set(context.site.tree)
    assert f"{base}/by-title/index.html" in keys and f"{base}/by-id/index.html" in keys
    assert cards(context.site.text(f"{base}/index.html")) == ["by-id", "by-title"]


@then('there is a tag page for "{tag}" and none for "{other}"')
def tag_pages(context, tag: str, other: str) -> None:
    keys = set(context.site.tree)
    assert f"tags/{tag}/index.html" in keys and f"tags/{other}/index.html" not in keys


@when('a site\'s type settings give "{kind}" the base "{base}" while a section already has the base "{taken}"')
def clashing_bases(context, kind: str, base: str, taken: str) -> None:
    try:
        standard_settings_from_mapping(settings(urls={**STYLE, "types": {kind: {"base": base}}, "sections": {"opinion": {"base": taken}}}))
        context.refusal = None
    except ValueError as error:
        context.refusal = str(error)


@then("the settings are refused naming the type")
def refused_naming_type(context) -> None:
    assert context.refusal and "urls.types.article.base" in context.refusal, context.refusal


@when("a Story is created from an Assignment that names no section")
def new_story(context) -> None:
    context.version = build_new_content_item_version(lineage_id="content-item-x", title="A title", summary=None, section_key=None, stage="idea", actor_label="AI", now="2026-11-02T00:00:00Z")


@then("the Story's section is empty and its draft slug keeps its usual shape")
def empty_section(context) -> None:
    assert context.version["section"] is None and context.version["slug"].startswith("draft-unsectioned-")


@given('a site with the section "{section}" titled "{title}"')
def titled_section(context, section: str, title: str) -> None:
    class Client:
        def list_records(self, model):
            return [{"id": section, "title": title}]

    context.client = Client()


@when('an idea names the section "{title}"')
def idea_names(context, title: str) -> None:
    context.filed = section_id_of(context.client, title)


@then('the Story is filed under the section "{section}"')
def filed_under(context, section: str) -> None:
    assert context.filed == section


SECTION_ROWS = [{"id": "aws", "title": "AWS"}, {"id": "guides", "title": "Before You File"}]


def row(slug: str, section: str | None, item_type: str = "article") -> dict:
    return {"id": f"item-{slug}", "sourceItemId": f"item-{slug}", "type": item_type, "slug": slug, "section": section, "status": "published", "versionState": "current", "sectionStatus": f"{section or ''}#published"}


@given("the stored sections of a site: {values}")
def stored_sections(context, values: str) -> None:
    context.rows = [row(f"story-{index}", value) for index, value in enumerate(quoted(values.split("and a page folder")[0]))]
    if "page folder" in values:
        context.rows.append(row("platform-page", quoted(values.split("page folder")[1])[0], "page"))


def plan_against(context, urls: dict) -> None:
    settings_ = standard_settings_from_mapping(settings(urls={**STYLE, **urls}))
    context.plan = section_migration.plan_for(site="example", items=context.rows, published=[], sections=SECTION_ROWS, settings=settings_)
    context.written = False


@when("the section migration is planned against a configuration that keys articles on their type")
def plan_new(context) -> None:
    plan_against(context, {"types": {"article": {"base": "articles"}}, "sections": {"aws": {"base": "aws", "aliases": ["AWS"]}, "platform": {"base": "platform"}}})


@when('the section migration is planned against a configuration that keys articles on the section "{section}"')
def plan_old(context, section: str) -> None:
    plan_against(context, {"sections": {section: {"base": "articles"}}})


def action_of(context, value: str) -> dict:
    return next(entry for entry in context.plan["values"] if entry["section"] == value and entry["model"] == "Item")


@then('"{first}" and "{second}" would be cleared and "{third}" would become "{target}"')
def cleared_and_mapped(context, first: str, second: str, third: str, target: str) -> None:
    assert action_of(context, first)["action"] == "clear" and action_of(context, second)["action"] == "clear"
    assert (action_of(context, third)["action"], action_of(context, third)["to"]) == ("map", target)


@then('"{first}" and the page folder "{folder}" are left alone')
def left_alone(context, first: str, folder: str) -> None:
    assert action_of(context, first)["action"] == "keep" and action_of(context, folder)["action"] == "keep"


@then('"{value}" is listed as needing a decision and nothing about it changes')
def needs_decision(context, value: str) -> None:
    assert [entry["section"] for entry in context.plan["decisions"]] == [value]
    assert all(change["from"] != value for change in context.plan["changes"])


@then("nothing has been written")
def nothing_written(context) -> None:
    assert context.plan["changes"] and "dry run: nothing is written" in section_migration.render(context.plan)


@then("the plan is blocked and applying it is refused")
def blocked_and_refused(context) -> None:
    assert context.plan["blocked"] >= 1 and not context.plan["ok"]
    try:
        section_migration.apply_plan(context.plan, object())
    except SystemExit as stop:
        assert "blocked" in str(stop)
    else:
        raise AssertionError("a blocked plan was applied")


def published_row(slug: str, section: str | None) -> dict:
    return {
        "id": f"published-item-{slug}", "sourceItemId": f"item-{slug}", "itemLineageId": f"item-{slug}", "versionNumber": 1, "type": "article", "status": "published", "language": "en", "languageGroupId": f"item-{slug}",
        "slug": slug, "section": section, "title": slug.title(), "bodyMarkus": "Body.\n", "aliases": [], "publishedAt": "2026-03-01T00:00:00Z",
        "metadata": {"frontMatterYaml": f"title: {slug.title()}\ndate: 2026-03-01\n"},
    }


@given('a snapshot of published articles stored with the section "{section}"')
def snapshot(context, section: str) -> None:
    context.work = Path(tempfile.mkdtemp(prefix="compare-steps-"))
    context.add_cleanup(lambda: __import__("shutil").rmtree(context.work, ignore_errors=True))
    rows = [published_row("one", section), published_row("two", section)]
    context.snapshot = context.work / "rows.json"
    context.snapshot.write_text(json.dumps(rows))
    context.plan_file = context.work / "plan.json"
    context.plan_file.write_text(json.dumps({"published": [{"id": row["id"], "from": section, "to": None} for row in rows]}))


def web(context, name: str, urls: dict) -> Path:
    directory = context.work / name
    directory.mkdir()
    (directory / "projection.json").write_text(json.dumps({"site": {"name": "Example", "productionUrl": "https://example.org"}, "urls": {**STYLE, **urls}}))
    return directory


def compare(context, new_urls: dict) -> None:
    old = web(context, "old", {"sections": {"articles": {"base": "articles"}}})
    new = web(context, "new", new_urls)
    context.result_file = context.work / "result.json"
    context.status = url_compare.main(["compare", "--snapshot", str(context.snapshot), "--old-static", str(old), "--new-static", str(new), "--plan", str(context.plan_file), "--work", str(context.work / "projections"), "--json", str(context.result_file)])
    context.result = json.loads(context.result_file.read_text())


@when("the snapshot is projected with the section key and again with the type key and the cleared sections")
def compare_same(context) -> None:
    compare(context, {"types": {"article": {"base": "articles"}}})


@when('the snapshot is projected with the section key and again with a type base of "{base}"')
def compare_moved(context, base: str) -> None:
    compare(context, {"types": {"article": {"base": base}}})


@then("the two projections have the same paths, sitemap, feeds and redirects")
def nothing_moved(context) -> None:
    assert context.status == 0 and context.result["moved"] is False and context.result["paths"]["new"] > 0


@then("the comparison reports the removed and the added addresses and fails")
def reports_moved(context) -> None:
    assert context.status == 1 and "articles/one/index.html" in context.result["paths"]["removed"] and "stories/one/index.html" in context.result["paths"]["added"]
