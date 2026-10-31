from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.standard_frontend_content_support import (  # noqa: E402
    DirectorySite,
    cards,
    cms_site,
    html_written,
    item,
    settings,
)
from procedures.newsroom.tests.standard_frontend_support import edit_item, written_keys  # noqa: E402

BAND = '::band{size="bare"}\n'
SECTIONS = {"sections": {"posts": {"base": "posts"}}}


def _page_entry(name: str) -> dict:
    return {"id": name, "path": name, "title": name, "source": f"{name}.md"}


@given('a site that lists the types "{first}" and "{second}"')
def site_types(context, first: str, second: str) -> None:
    context.story_types = [first, second]


@given("a post published after the newest article")
def post_after_article(context) -> None:
    context.typed_items = [
        item("a1", date="2026-02-01", type="article"),
        item("a2", date="2026-02-03", type="article"),
        item("p1", date="2026-02-05", type="post"),
    ]


def _project_page(context, line: str) -> None:
    site = cms_site(
        settings(urls=SECTIONS, listings={"types": context.story_types}, pages=[_page_entry("page")]),
        context.typed_items,
        {"page.md": f"---\ntitle: Page\n---\n{BAND}{line}\n"},
    )
    context.add_cleanup(site.cleanup)
    context.typed_site = site
    context.block = cards(site.text("page/index.html"))


@when('a page includes a listing with types "{types}" and count {count:d}')
def listing_types_count(context, types: str, count: int) -> None:
    _project_page(context, f'::include{{kind="listing" types="{types}" count="{count}" layout="bare"}}')


@when('a page includes a listing with notTypes "{types}"')
def listing_not_types(context, types: str) -> None:
    _project_page(context, f'::include{{kind="listing" notTypes="{types}" layout="bare"}}')


@then("the block shows the newest article and no post")
def shows_newest_article(context) -> None:
    assert context.block == ["a2"], context.block


@then("the block shows every article and no post")
def shows_every_article(context) -> None:
    assert context.block == ["a2", "a1"], context.block


@when('a page includes a listing with the attribute "{attribute}"')
def listing_unknown_attribute(context, attribute: str) -> None:
    site = DirectorySite(
        settings(pages=[_page_entry("page")]),
        [item("x", section="posts")],
        {"page.md": f'{BAND}::include{{kind="listing" {attribute}="post"}}\n'},
    )
    context.add_cleanup(site.cleanup)
    try:
        site.project_all()
    except ValueError as error:
        context.projection_error = str(error)
    else:
        context.projection_error = None


@then('the projection fails naming the unknown attribute "{attribute}"')
def fails_naming_attribute(context, attribute: str) -> None:
    assert context.projection_error and f"unknown attributes: {attribute}" in context.projection_error, context.projection_error


@given("a page whose listing shows the newest article")
def page_with_newest_article(context) -> None:
    _project_page(context, '::include{kind="listing" sections="posts" types="article" count="1" layout="bare"}')
    assert context.block == ["a2"], context.block
    written_keys(context.typed_site)  # start counting writes from here


@when("a post is edited")
def edit_post(context) -> None:
    edit_item(context.typed_site, "item-posts-p1", title="P1 renamed")
    context.rewritten = html_written(written_keys(context.typed_site))


@then("only the post is rewritten")
def only_post_rewritten(context) -> None:
    assert "page/index.html" not in context.rewritten, context.rewritten


@when("the newest article is edited")
def edit_newest_article(context) -> None:
    edit_item(context.typed_site, "item-posts-a2", title="A2 renamed")
    context.rewritten = html_written(written_keys(context.typed_site))


@then("the article and the page are rewritten")
def article_and_page_rewritten(context) -> None:
    assert {"posts/a2.html", "page/index.html"} <= context.rewritten, context.rewritten
