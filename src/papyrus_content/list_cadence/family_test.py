"""Cadence families without a site: the list settings that name them and the period a periodic issue covers (behaviour: features_backend/cadence-family.feature)."""
from datetime import datetime, timezone

import pytest

from papyrus_content.list_cadence.family import conflicts, families, family_of, period_start
from papyrus_content.list_cadence.settings import ListSettingsError, validate_document, validate_list

from .list_cadence_test import entry


def test_a_list_that_names_no_family_is_its_own():
    assert family_of("weekly", entry("weekly", sendAt={"day": "monday", "time": "04:00"})) == "weekly"
    assert family_of("daily", entry("daily", family="new-stories")) == "new-stories"


def test_the_family_is_stored_with_the_list():
    assert validate_list("daily", {**entry("daily"), "family": "new-stories"})["family"] == "new-stories"


@pytest.mark.parametrize("family", ["", "Upper", 3, "has space", "-x"])
def test_a_family_that_is_not_a_name_is_refused(family):
    with pytest.raises(ListSettingsError):
        validate_list("daily", {**entry("daily"), "family": family})


def document(**lists):
    return {"schemaVersion": 1, "lists": lists}


def test_a_family_has_one_list_for_each_cadence():
    one = entry("daily", family="new-stories")
    with pytest.raises(ListSettingsError) as refused:
        validate_document(document(first=one, second=one))
    assert "family new-stories" in refused.value.message


def test_every_item_and_daily_share_a_family_and_the_weekly_is_alone():
    checked = validate_document(document(each=entry("each", family="new-stories"), daily=entry("daily", family="new-stories"),
                                         weekly=entry("weekly", sendAt={"day": "monday", "time": "04:00"})))
    assert families(checked["lists"]) == {"each": "new-stories", "daily": "new-stories", "weekly": "weekly"}


def test_two_lists_alone_in_their_own_families_may_share_a_cadence():
    validate_document(document(a=entry("daily"), b=entry("daily")))


def test_conflicts_names_each_family_held_twice_once():
    by_list = {"each": "new-stories", "daily": "new-stories", "weekly": "weekly"}
    assert conflicts(["each", "daily", "weekly"], by_list) == ["new-stories"]
    assert conflicts(["daily", "weekly"], by_list) == []
    assert conflicts(["unknown", "unknown"], by_list) == ["unknown"]


def test_a_daily_period_starts_one_day_before_in_the_lists_own_calendar():
    scheduled = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)   # 06:00 in New York
    assert period_start(entry("daily"), scheduled) == datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)


def test_a_clock_change_does_not_move_the_local_start():
    # The clocks go back on 2026-11-01: the day before 06:00 EST on the 1st is 06:00 EDT, an hour earlier in UTC than 24 hours before.
    scheduled = datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)
    assert period_start(entry("daily"), scheduled) == datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)


def test_a_weekly_period_starts_one_week_before():
    scheduled = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)   # Monday 04:00 in New York
    assert period_start(entry("weekly", sendAt={"day": "monday", "time": "04:00"}), scheduled) == datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def test_an_every_item_list_has_no_period():
    with pytest.raises(ValueError):
        period_start(entry("each"), datetime(2026, 11, 5, tzinfo=timezone.utc))
