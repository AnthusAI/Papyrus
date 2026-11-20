from __future__ import annotations

from types import SimpleNamespace

from behave import then, when

from papyrus_content.authors import Author
from papyrus_content.projection.standard import components
from papyrus_content.projection.standard.markdown import item_markdown


def _entry():
    return SimpleNamespace(title="A post", author_details=(Author("Ryan Porter"),), date="2026-11-09", updated=None, key="posts/a-post", link=None, summary_text="A summary.")


def _draw(context, hook):
    context.twin = item_markdown(_entry(), "Words of the post.\n", None, (), None, hook)
    context.page = components.byline(_entry(), "", hook)


@when("the byline of an item is drawn with no hook")
def step_no_hook(context):
    _draw(context, None)


@when('the byline of an item is drawn with the hook text "{text}"')
def step_hook_text(context, text):
    _draw(context, text)


@when("the byline of an item is drawn with an empty hook text")
def step_empty_hook(context):
    _draw(context, "")


@then('the Markdown twin and the page show "{text}"')
def step_both_show(context, text):
    assert text in context.twin and text in context.page, (context.twin, context.page)


@then('neither the Markdown twin nor the page shows "{text}"')
def step_neither_shows(context, text):
    assert text not in context.twin and text not in context.page, (context.twin, context.page)


@then('the Markdown twin still says it was published on "{date}"')
def step_published(context, date):
    assert f"Published {date}" in context.twin, context.twin
