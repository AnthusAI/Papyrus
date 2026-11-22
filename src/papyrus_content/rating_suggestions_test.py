import json

import pytest

from papyrus_content import rating_suggestions as rs
from papyrus_content.item_stars import ITEM_PRIVATE_STAR_FIELDS, carry_item_stars


class Rows:
    def __init__(self):
        self.items, self.reviews = {}, {}

    def update_record(self, model, payload):
        (self.items if model == "Item" else self.reviews).setdefault(payload["id"], {}).update(payload)

    def get_record(self, model, record_id):
        return dict(self.reviews[record_id]) if record_id in self.reviews else None

    def create_record(self, model, payload):
        self.reviews[payload["id"]] = dict(payload)


def test_a_suggestion_is_pending_only_while_nobody_has_rated_the_story():
    row = {"starSuggestion": 4, "starSuggestedBy": "agent:rate"}
    assert rs.pending_suggestion(row)["stars"] == 4
    assert rs.pending_suggestion({**row, "starRating": 2}) is None
    assert rs.suggestion_of({"starSuggestion": 5})["candidate"] is True
    assert rs.suggestion_of({"starSuggestion": 2}) is None


def test_writing_a_suggestion_never_touches_the_rating_and_refuses_a_rated_story():
    rows = Rows()
    rs.write_suggestion(rows, {"id": "s-v1", "lineageId": "s"}, 3, by="agent:rate", run="run-1", now="2026-11-21T08:30:00.000Z")
    assert rows.items["s-v1"] == {"id": "s-v1", "starSuggestion": 3, "starSuggestedAt": "2026-11-21T08:30:00.000Z", "starSuggestedBy": "agent:rate", "starSuggestionRun": "run-1"}
    with pytest.raises(rs.SuggestionError, match="already has a rating"):
        rs.write_suggestion(rows, {"id": "t-v1", "lineageId": "t", "starRating": 4}, 3, by="agent:rate", run=None, now="x")
    with pytest.raises(rs.SuggestionError):
        rs.write_suggestion(rows, {"id": "u-v1"}, 2, by="agent:rate", run=None, now="x")


def test_the_days_review_is_raised_once_and_counts_every_story_it_links():
    rows = Rows()
    first = rs.raise_daily_review(rows, day="2026-11-21", entries=[{"story": "a", "title": "A", "stars": 3}], raised_by="agent:rate")
    assert first["id"] == "rr-ratings-2026-11-21" and first["reason"] == "1 rating suggested, 0 five-star candidates" and first["mode"] == "soft_review"
    again = rs.raise_daily_review(rows, day="2026-11-21", entries=[{"story": "a", "title": "A", "stars": 3}, {"story": "c", "title": "C", "stars": 5}], raised_by="agent:rate")
    assert again["reason"] == "1 rating suggested, 1 five-star candidate" and [link["id"] for link in again["links"]] == ["a", "c"]
    assert len(rows.reviews) == 1 and json.loads(rows.reviews["rr-ratings-2026-11-21"]["links"])[1]["label"] == "C: five-star candidate"


def test_a_new_version_keeps_the_suggestion_and_it_is_never_published():
    carried = carry_item_stars({"starSuggestion": 4, "starSuggestedBy": "agent:rate", "starSuggestedAt": "t", "starSuggestionRun": "r"}, {})
    assert carried == {"starSuggestion": 4, "starSuggestedBy": "agent:rate", "starSuggestedAt": "t", "starSuggestionRun": "r"}
    assert {"starSuggestion", "starSuggestedBy", "starSuggestedAt", "starSuggestionRun"} <= set(ITEM_PRIVATE_STAR_FIELDS)
