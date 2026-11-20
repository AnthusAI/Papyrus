"""The inserter's standing rules (``selection.py``), pure, and the roundup draft that applies them (``roundup.py``)."""

from __future__ import annotations

from papyrus_content.newsletter.issues_test import DAY, Rig, rig  # noqa: F401
from papyrus_content.newsletter.newsletter_test import START
from papyrus_content.newsletter.roundup import declared_types
from papyrus_content.newsletter.selection import (
    ALREADY_SENT, BELOW_FLOOR, DUPLICATE, EXCLUDED, RETIRED, WRONG_TYPE, Candidate, eligible_at, select,
)
import pytest

SINCE, UNTIL = 100.0, 200.0


def story(slug, *, stars=3, published=150.0, rated=None, type="article", section="tools", group=None, status="published", title=None):
    row = {"id": f"published-{slug}", "itemLineageId": slug, "slug": slug, "title": title or slug, "type": type, "section": section, "status": status}
    return Candidate(row, stars, published, eligible_at(published, rated, stars, 3), group)


def run(candidates, **overrides):
    options = {"types": ["article"], "floor": 3, "since": SINCE, "until": UNTIL} | overrides
    chosen = select(candidates, **options)
    return [c.id for slot in chosen.included.values() for c in slot], {left.candidate.id: left.reason for left in chosen.left_out}


def test_only_declared_types_qualify_and_wiki_pages_are_left_out():
    included, left = run([story("a"), story("wiki", type="wiki")])
    assert included == ["a"] and left == {"wiki": WRONG_TYPE}


def test_a_retired_story_is_left_out_as_retired():
    assert run([story("gone", status="retired")]) == ([], {"gone": RETIRED})


def test_unrated_and_below_the_floor_never_qualify():
    included, left = run([story("none", stars=0), story("two", stars=2), story("three", stars=3)])
    assert included == ["three"] and left == {"none": BELOW_FLOOR, "two": BELOW_FLOOR}


def test_no_floor_means_everything_of_a_declared_type_qualifies():
    assert run([story("none", stars=0)], floor=None)[0] == ["none"]


def test_a_late_rated_older_article_is_eligible_when_it_reaches_the_floor():
    old_rated_now = story("late", published=10.0, rated=160.0)
    assert old_rated_now.eligible_at == 160.0
    assert run([old_rated_now])[0] == ["late"]
    assert run([old_rated_now], since=160.0, until=300.0)[0] == []   # the next issue's window starts after it: never offered again


def test_an_item_outside_the_window_is_not_listed_at_all():
    assert run([story("before", published=50.0), story("after", published=250.0)]) == ([], {})


def test_already_sent_and_excluded_items_are_left_out_with_their_reason():
    included, left = run([story("sent"), story("cut"), story("fresh")], sent_ids={"sent"}, excluded={"cut"})
    assert included == ["fresh"] and left == {"sent": ALREADY_SENT, "cut": EXCLUDED}


def test_the_first_eligible_of_a_group_wins_and_later_ones_are_duplicates():
    included, left = run([story("second", published=160.0, group="g", title="Second"), story("first", published=120.0, group="g", title="First")])
    assert included == ["first"] and left == {"second": DUPLICATE.format(title="First")}


def test_a_group_an_earlier_issue_sent_is_not_offered_again():
    included, left = run([story("again", group="g")], sent_groups={"g"})
    assert included == [] and "duplicate" in left["again"]


def test_items_in_no_group_never_dedupe():
    assert sorted(run([story("a"), story("b")])[0]) == ["a", "b"]


def test_a_slot_follows_the_shared_quality_order_and_a_pin_wins():
    items = [story("three", stars=3, published=190.0), story("five", stars=5, published=110.0), story("four", stars=4, published=150.0)]
    assert run(items)[0] == ["five", "four", "three"]
    assert run(items, pinned={"three": 0})[0] == ["three", "five", "four"]


def test_slots_are_alphabetical_with_the_unsectioned_last():
    chosen = select([story("x", section=None), story("b", section="tools"), story("a", section="security")], types=["article"], floor=3, since=SINCE, until=UNTIL)
    assert list(chosen.included) == ["security", "tools", None]


def test_a_list_must_declare_its_types():
    assert declared_types({"id": "weekly", "types": ["article"]}) == ["article"]
    for entry in ({"id": "weekly"}, {"id": "weekly", "types": []}, {"id": "weekly", "types": [3]}):
        with pytest.raises(ValueError, match="must declare the Story types"):
            declared_types(entry)


# -- the draft ---------------------------------------------------------------------------------------------------------


def body_of(rig: Rig) -> tuple[dict, str]:
    created = rig.task("assemble-roundup", listId="weekly")
    return created, rig.content.items[created["itemId"]]["bodyMarkus"] if "itemId" in created else ""


def test_the_first_window_opens_at_the_start_of_the_period_and_no_fixed_days_apply(rig: Rig) -> None:
    rig.content.publish(slug="this-week", title="This week", section="tools", at=START - DAY)
    rig.content.publish(slug="last-week", title="Last week", section="tools", at=START - 8 * DAY)
    _created, body = body_of(rig)
    assert "[This week]" in body and "Last week" not in body


def test_wiki_pages_are_left_out_with_the_reason(rig: Rig) -> None:
    rig.content.publish(slug="story", title="Story", section="tools", at=START - DAY)
    rig.content.publish(slug="wiki-page", title="Wiki page", section="wiki", at=START - DAY, type="wiki")
    _created, body = body_of(rig)
    kept, left = body.split("## Left out")
    assert "[Story]" in kept and "[Wiki page]" in left and f"({WRONG_TYPE})" in left


def test_the_issue_remembers_the_entries_it_carries(rig: Rig) -> None:
    rig.content.publish(slug="carried", title="Carried", section="tools", at=START - 3 * DAY)
    first, _body = body_of(rig)
    assert rig.issue(first["issueId"])["entryIds"] == ["lineage-carried"]
