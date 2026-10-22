import datetime as dt

import pytest

from .wiki_stamp import Review, parse_review, review_mapping, stamp_problems, stamp_text


def test_an_ai_stamp_says_draft_and_edited_by_ai_and_a_human_stamp_says_reviewed():
    assert stamp_text(Review("ai", None, "2026-10-22")) == "Draft, not yet reviewed. Edited by AI on 2026-10-22"
    assert stamp_text(Review("human", "Ada Reader", "2026-10-22")) == "Reviewed by Ada Reader on 2026-10-22"
    assert stamp_text(Review("human", None, "2026-10-22")) == "Reviewed by an editor on 2026-10-22"


def test_no_stamp_says_draft_and_never_uses_the_word_desk():
    assert stamp_text(None) == "Draft, not yet reviewed"
    texts = [stamp_text(None), stamp_text(Review("ai", None, "2026-10-22")), stamp_text(Review("human", None, "2026-10-22"))]
    assert not any("desk" in text.lower() for text in texts)


def test_dates_follow_the_sites_date_format():
    assert stamp_text(Review("ai", None, "2026-10-22"), "%B %d, %Y") == "Draft, not yet reviewed. Edited by AI on October 22, 2026"


def test_yaml_dates_and_strings_both_parse():
    assert parse_review({"review": {"actor": "ai", "name": None, "on": dt.date(2026, 10, 22)}}) == Review("ai", None, "2026-10-22")
    assert parse_review({"review": {"actor": "human", "name": "  Ada   Reader ", "on": "2026-10-22"}}) == Review("human", "Ada Reader", "2026-10-22")


@pytest.mark.parametrize(
    "front",
    [
        {},
        {"review": None},
        {"review": "ai"},
        {"review": {"actor": "robot", "name": None, "on": "2026-10-22"}},
        {"review": {"actor": "human", "name": "ada@example.org", "on": "2026-10-22"}},
        {"review": {"actor": "human", "name": "", "on": "2026-10-22"}},
        {"review": {"actor": "ai", "name": None, "on": "last week"}},
        {"review": {"actor": "ai", "name": None, "on": "2026-10-22"}, "superseded_by": "wiki/relative"},
    ],
)
def test_the_checker_refuses_anything_but_a_complete_stamp(front):
    assert stamp_problems(front)
    assert parse_review(front) is None or "superseded_by" in front


def test_a_complete_stamp_passes_and_names_no_one_by_default():
    assert stamp_problems({"review": {"actor": "ai", "name": None, "on": "2026-10-22"}, "superseded_by": "/wiki/new/"}) == []
    assert review_mapping("ai", None, "2026-10-22") == {"actor": "ai", "name": None, "on": "2026-10-22"}
    with pytest.raises(ValueError):
        review_mapping("bot", None, "2026-10-22")
