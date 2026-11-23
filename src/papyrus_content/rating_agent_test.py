"""What wakes the rating agent and which Stories a change wake judges (slice L3; the whole run is in features_backend/agents/rating-suggestion-triggers.feature)."""
from __future__ import annotations

import pytest

from papyrus_content import rating_agent
from papyrus_content.rating_agent import RatingError, RatingWake, Services, Tally, rating_wake, why_not_eligible, woken_stories


def test_the_schedule_names_nothing_a_publish_names_its_story_and_an_acceptance_its_reference():
    assert rating_wake({}) == RatingWake() and rating_wake({}).kind == "schedule"
    assert rating_wake({"story": "s-1", "change": "stage_entered", "stage": "published", "what": "stage_entered.published"}) == RatingWake(story="s-1")
    assert rating_wake({"change": "accepted", "subjectKind": "Reference", "subjectId": "r-1"}) == RatingWake(reference="r-1")


@pytest.mark.parametrize("given", [{"story": "s-1", "change": "stage_entered", "stage": "copywriting"}, {"story": "s-1", "change": "rated"},
                                   {"change": "accepted", "subjectKind": "Story", "subjectId": "s-1"}, {"change": "stage_entered", "stage": "published"}])
def test_a_wake_the_definition_does_not_listen_for_is_refused(given):
    with pytest.raises(RatingError):
        rating_wake(given)


def _row(**extra):
    return {"id": "s-1-v3", "lineageId": "s-1", "type": "article", "stage": "published", **extra}


def test_only_a_published_unrated_unsuggested_story_that_is_not_a_translation_waits_for_a_rating():
    assert why_not_eligible(_row()) is None
    assert why_not_eligible(_row(stage="copywriting")) == "not_published"
    assert why_not_eligible(_row(sourceLineageId="s-0")) == "translation"
    assert why_not_eligible(_row(starRating=4, starRatedBy="ada")) == "already_rated"
    assert why_not_eligible(_row(starSuggestion=3)) == "already_suggested"
    assert why_not_eligible(_row(type="page")) == "not_a_story"


def test_a_reference_wake_reads_each_story_based_on_it_once_and_lists_why_it_skips_one():
    rows = {"s-1": _row(), "s-2": _row(lineageId="s-2", starRating=3, starRatedBy="ada")}
    services = Services(stories=lambda: iter(()), judge=lambda row, text: {}, execute=lambda *args: {}, story=rows.get,
                        stories_based_on=lambda reference: ["s-1", "s-2", "s-1", "s-gone"])
    tally = Tally()
    judged = [row["lineageId"] for row in woken_stories(RatingWake(reference="r-1"), services, tally)]
    assert judged == ["s-1"]
    assert tally.skipped == [{"story": "s-2", "reason": "already_rated"}, {"story": "s-gone", "reason": "not_found"}]


def test_eligible_is_the_same_rule_the_daily_run_reads_the_index_with():
    assert rating_agent.eligible(_row()) and not rating_agent.eligible(_row(starSuggestion=5))
