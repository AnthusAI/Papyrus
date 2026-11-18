"""Cadence families without a site: the list settings that name them and the period a periodic issue covers (behaviour: features_backend/cadence-family.feature)."""
from datetime import datetime, timezone

import pytest

from papyrus_content.list_cadence.family import conflicts, families, family_of, mover, next_period_start, period_start
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


def _utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def test_the_next_daily_period_start_is_the_next_scheduled_time_after_now():
    daily = entry("daily", sendAt={"time": "06:00"})
    assert next_period_start(daily, _utc(2026, 11, 4, 17, 0)) == _utc(2026, 11, 5, 11, 0)   # noon in New York: the next 06:00 is tomorrow's
    assert next_period_start(daily, _utc(2026, 11, 4, 9, 0)) == _utc(2026, 11, 4, 11, 0)    # 04:00 local: today's 06:00 is still ahead
    assert next_period_start(daily, _utc(2026, 11, 4, 11, 0)) == _utc(2026, 11, 5, 11, 0), "at the start itself the next one is the following day"


def test_the_next_weekly_period_start_is_the_next_named_weekday():
    weekly = entry("weekly", sendAt={"day": "monday", "time": "04:00"})
    assert next_period_start(weekly, _utc(2026, 11, 4, 17, 0)) == _utc(2026, 11, 9, 9, 0)   # Wednesday: Monday the 9th, 04:00 EST
    assert next_period_start(weekly, _utc(2026, 11, 9, 9, 0)) == _utc(2026, 11, 16, 9, 0)
    assert next_period_start(entry("weekly", sendAt={"day": "sunday", "time": "04:00"}), _utc(2026, 11, 4, 17, 0)) == _utc(2026, 11, 8, 9, 0)


def test_the_next_period_start_keeps_the_local_time_across_a_clock_change():
    daily = entry("daily", sendAt={"time": "06:00"})
    # The clocks go back on 2026-11-01: 06:00 on the 31st is EDT (10:00 UTC), 06:00 on the 1st is EST (11:00 UTC).
    assert next_period_start(daily, _utc(2026, 10, 31, 12, 0)) == _utc(2026, 11, 1, 11, 0)


def test_an_every_item_list_has_no_next_period_start():
    with pytest.raises(ValueError):
        next_period_start(entry("each"), _utc(2026, 11, 5))


def _lists(*entries):
    return [{"id": list_id, **value} for list_id, value in entries]


def test_a_move_in_a_family_waits_for_its_periodic_lists_next_period_start_and_other_families_move_at_once():
    move = mover(_lists(("each", entry("each", family="new-stories")), ("daily", entry("daily", family="new-stories", sendAt={"time": "06:00"})),
                        ("weekly", entry("weekly", sendAt={"day": "monday", "time": "04:00"}))))
    now = _utc(2026, 11, 4, 17, 0)
    assert move("new-stories", now) == _utc(2026, 11, 5, 11, 0)
    assert move("weekly", now) == _utc(2026, 11, 9, 9, 0), "a list alone in its family is its own family, and its period is its own"
    assert move("unknown", now) == now


def test_a_family_with_no_periodic_list_moves_at_once():
    move = mover(_lists(("a", entry("each", family="pair")), ("b", entry("each", family="pair"))))
    now = _utc(2026, 11, 4, 17, 0)
    assert move("pair", now) == now


def test_a_family_with_two_periodic_lists_is_refused_by_the_hook_and_by_the_settings():
    daily, weekly = entry("daily", family="new-stories"), entry("weekly", family="new-stories", sendAt={"day": "monday", "time": "04:00"})
    with pytest.raises(ValueError):
        mover(_lists(("daily", daily), ("weekly", weekly)))
    with pytest.raises(ListSettingsError) as refused:
        validate_document(document(daily=daily, weekly=weekly))
    assert "periodic lists of the family new-stories" in refused.value.message
