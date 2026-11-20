"""The roundup inserter's standing rules (features_backend/readers/newsletter-roundup-inserter.feature): the pure selection and the draft that applies it."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter.issues_test import DAY, rig_context  # noqa: E402
from papyrus_content.newsletter.newsletter_test import START  # noqa: E402
from papyrus_content.newsletter.roundup import declared_types  # noqa: E402
from papyrus_content.newsletter.selection import (  # noqa: E402
    ALREADY_SENT, BELOW_FLOOR, DUPLICATE, EXCLUDED, RETIRED, WRONG_TYPE, Candidate, eligible_at, select,
)

SINCE, UNTIL, FLOOR = 100.0, 200.0, 3


def candidate(slug, *, stars=3, published=150.0, rated=None, type="article", section="tools", group=None, status="published") -> Candidate:
    row = {"id": f"published-{slug}", "itemLineageId": slug, "slug": slug, "title": slug.title(), "type": type, "section": section, "status": status}
    return Candidate(row, stars, published, eligible_at(published, rated, stars, FLOOR), group)


@given("a roundup list that declares the article type")
def declares(context) -> None:
    context.candidates, context.options, context.pinned = [], {"types": declared_types({"id": "weekly", "types": ["article"]})}, {}


@given("a published article and a published post")
def article_and_post(context) -> None:
    context.candidates += [candidate("article"), candidate("post", type="post")]


@given("a published wiki page in the window")
def wiki(context) -> None:
    context.candidates.append(candidate("wiki-page", type="wiki"))


@given("a Story retired after it qualified")
def retired(context) -> None:
    context.candidates.append(candidate("story", status="retired"))


@given("a published article nobody rated")
def unrated(context) -> None:
    context.candidates.append(candidate("article", stars=0))


@given("an article published a month ago and rated three stars today")
def late_rated(context) -> None:
    context.candidates.append(candidate("late", published=10.0, rated=160.0))


@given("an article that was in last week's issue")
def sent(context) -> None:
    context.candidates.append(candidate("article"))
    context.options["sent_ids"] = {"article"}


@given("two articles of the same story group, the second eligible later")
def duplicates(context) -> None:
    context.candidates += [candidate("second", published=160.0, group="story"), candidate("first", published=120.0, group="story")]


@given("an article an editor excluded from this issue")
def excluded(context) -> None:
    context.candidates.append(candidate("article"))
    context.options["excluded"] = {"article"}


@given("three articles in one section rated five, four and three stars")
def three(context) -> None:
    context.candidates += [candidate("three", stars=3, published=190.0), candidate("five", stars=5, published=110.0), candidate("four", stars=4, published=150.0)]


@when("an editor pinned the three-star article to the first place")
def pin(context) -> None:
    context.pinned = {"three": 0}


@when("the inserter chooses")
def choose(context) -> None:
    context.selection = select(context.candidates, floor=FLOOR, since=SINCE, until=UNTIL, pinned=context.pinned, **context.options)
    context.included = [c.id for slot in context.selection.included.values() for c in slot]
    context.left_out = {left.candidate.id: left.reason for left in context.selection.left_out}


@then("only the article is in the issue")
def only_article(context) -> None:
    assert context.included == ["article"], context.included


@then("the post is left out as not a type the list carries")
def post_left(context) -> None:
    assert context.left_out == {"post": WRONG_TYPE}


@then("the wiki page is left out as not a type the list carries")
def wiki_left(context) -> None:
    assert context.left_out == {"wiki-page": WRONG_TYPE}


@then("the issue is empty")
def empty(context) -> None:
    assert context.included == []


@then("the Story is left out as retired")
def retired_left(context) -> None:
    assert context.left_out == {"story": RETIRED}


@then("the article is left out as below the floor")
def below(context) -> None:
    assert context.left_out == {"article": BELOW_FLOOR}


@then("the article is in this week's issue")
def in_week(context) -> None:
    assert context.included == ["late"]


@then("the next issue's window starts after the article became eligible, so it is not offered again")
def not_again(context) -> None:
    again = select(context.candidates, floor=FLOOR, since=UNTIL, until=UNTIL + 100, **context.options)
    assert again.count == 0 and not again.left_out


@then("the article is left out as already sent")
def already(context) -> None:
    assert context.left_out == {"article": ALREADY_SENT}


@then("only the first eligible article is in the issue")
def first_only(context) -> None:
    assert context.included == ["first"]


@then("the other is left out as a duplicate of the first")
def duplicate_left(context) -> None:
    assert context.left_out == {"second": DUPLICATE.format(title="First")}


@then("the article is left out as removed by a person")
def removed(context) -> None:
    assert context.left_out == {"article": EXCLUDED}


@then("they appear in the shared quality order")
def quality_order(context) -> None:
    assert context.included == ["five", "four", "three"]


@then("the three-star article comes first and the others follow in quality order")
def pinned_order(context) -> None:
    assert context.included == ["three", "five", "four"]


@given("a roundup list that declares no types")
def no_types(context) -> None:
    context.entry = {"id": "weekly"}


@when("the roundup is assembled")
def assemble(context) -> None:
    context.refusal = None
    try:
        declared_types(context.entry)
    except ValueError as error:
        context.refusal = str(error)
    if context.refusal is None:
        context.assembled = context.rig.task("assemble-roundup", listId="weekly")


@then("it is refused because the list must declare the Story types it carries")
def refused(context) -> None:
    assert context.refusal and "must declare the Story types" in context.refusal


@given("a weekly list that never sent an issue and an article from the week before")
def never_sent(context) -> None:
    context.rig_manager = rig_context()
    context.rig = context.rig_manager.__enter__()
    context.add_cleanup(lambda: context.rig_manager.__exit__(None, None, None))
    context.entry = {"id": "weekly", "types": ["article"]}
    context.rig.content.publish(slug="this-week", title="This week", section="tools", at=START - DAY)
    context.rig.content.publish(slug="last-week", title="Last week", section="tools", at=START - 8 * DAY)


@then("the window opens at the start of the current period and the older article is not in it")
def period_window(context) -> None:
    body = context.rig.content.items[context.assembled["itemId"]]["bodyMarkus"]
    assert "[This week]" in body and "Last week" not in body


@then("no number of days is configured anywhere")
def no_days(context) -> None:
    import papyrus_content.newsletter.roundup as roundup

    assert not hasattr(roundup, "DEFAULT_WINDOW_SECONDS")
