"""Steps for a story's summary, whichever front matter field holds it."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from behave import given, then, when

from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, fixture_settings


def _content(context) -> Path:
    if not hasattr(context, "summary_content"):
        context.summary_content = Path(tempfile.mkdtemp(prefix="story-summary-"))
        context.add_cleanup(shutil.rmtree, context.summary_content, ignore_errors=True)
    return context.summary_content


def _write(context, slug: str, fields: str) -> None:
    (_content(context) / f"{slug}.md").write_text(f"---\ntitle: {slug}\ndate: '2026-01-05'\n{fields}---\nBody of {slug}.\n", encoding="utf-8")


@given('a site with public data and a story "{slug}" whose front matter has only a deck "{deck}"')
def step_only_deck(context, slug, deck):
    _write(context, slug, f"deck: {deck}\n")


@given('a story "{slug}" with the description "{description}" and the deck "{deck}"')
def step_both(context, slug, description, deck):
    _write(context, slug, f"description: {description}\ndeck: {deck}\n")


@when("the site is projected")
def step_project(context):
    settings = {**fixture_settings("flat"), "publicData": {"latest": True, "latestCount": 6}}
    context.summary_site = ProjectedSite("flat", settings=settings, content=_content(context))
    context.add_cleanup(context.summary_site.cleanup)


@then('the meta description of "{slug}" is "{text}"')
def step_meta(context, slug, text):
    page = context.summary_site.text(f"{slug}.html")
    assert re.search(rf'<meta name="description" content="{re.escape(text)}"', page), page[:1500]


@then('the latest list gives "{slug}" the summary "{text}"')
def step_latest(context, slug, text):
    latest = json.loads(context.summary_site.text("_data/latest.json"))
    items = latest["items"] if isinstance(latest, dict) else latest
    entry = next(item for item in items if slug in item["url"])
    assert entry["summary"] == text, entry
