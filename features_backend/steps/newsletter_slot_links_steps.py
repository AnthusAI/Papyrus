"""The link rule for a slot's blurb (features_backend/newsletter-slot-links.feature)."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter.slot_links import link_problems  # noqa: E402

PAGE = "https://news.example.com/articles/a.html"
REPORT = "https://reports.example.org/x"


@given("a Story whose text links to a report")
def story(context) -> None:
    context.story_text = f"The [report]({REPORT}) says so."


@when("a blurb links to the Story's page and to that report")
def good(context) -> None:
    context.problems = link_problems(f"See {PAGE} and [the report]({REPORT}).", story_url=PAGE, story_text=context.story_text)


@when("a blurb links to an address that is neither the Story's page nor in the Story")
def bad(context) -> None:
    context.problems = link_problems("Buy at https://shop.example.net/deal today.", story_url=PAGE, story_text=context.story_text)


@then("the blurb has no link problems")
def none(context) -> None:
    assert context.problems == []


@then("the blurb is refused naming that link")
def refused(context) -> None:
    assert len(context.problems) == 1 and "https://shop.example.net/deal" in context.problems[0]
