"""The parts of the list cadence that need no site: the clock expression, the local period, the floor and the rung (the behaviour is features_backend/list-cadence.feature)."""
import pytest

from papyrus_content.announcements.links import StoryRef
from papyrus_content.list_cadence import schedule
from papyrus_content.list_cadence.announce import Candidate, effective_rung, local_period, qualifies
from papyrus_content.list_cadence.settings import ListSettingsError, validate_list


def entry(cadence, **changes):
    base = {"name": "A list", "cadence": cadence, "rule": {"sections": [], "types": [], "tags": [], "minStars": 3}, "template": "roundup", "agent": "announce-lists",
            "workingDocument": "delivery"}
    if cadence != "each":
        base.update(sendAt={"time": "06:05"}, timeZone="America/New_York")
    return validate_list("mine", {**base, **changes})


@pytest.mark.parametrize("day, expression", [("sunday", "5 6 * * 0"), ("monday", "5 6 * * 1"), ("saturday", "5 6 * * 6")])
def test_a_weekly_list_is_one_weekday_at_its_local_time(day, expression):
    assert schedule.cron_of(entry("weekly", sendAt={"day": day, "time": "06:05"})) == expression


def test_a_daily_list_is_every_day_and_an_every_item_list_has_no_clock():
    document = {"lists": {"d": entry("daily"), "e": entry("each")}}
    assert schedule.wanted(document) == {"d": {"agent": "announce-lists", "cron": "5 6 * * *", "timeZone": "America/New_York"}}


@pytest.mark.parametrize("stars", [-1, 0, 1, 2])
def test_nothing_under_three_stars_is_saved(stars):
    with pytest.raises(ListSettingsError) as refused:
        entry("each", rule={"minStars": stars})
    assert refused.value.code == "below_quality_floor"


@pytest.mark.parametrize("stars", [True, "3", 3.5, None, 6])
def test_a_minimum_that_is_not_three_four_or_five_is_refused(stars):
    with pytest.raises(ListSettingsError):
        entry("each", rule={"minStars": stars})


def test_the_floor_is_held_again_where_a_list_is_read_for_a_story():
    story = Candidate(StoryRef("a", "a-v1", 1), "science", "article", [], 2, True)
    assert qualifies({"rule": {"minStars": 1, "sections": [], "types": [], "tags": []}}, story) == (False, "2 stars is under the list's bar of 3")


def test_a_period_is_the_lists_local_date_or_local_iso_week():
    daily, weekly = entry("daily"), entry("weekly", sendAt={"day": "monday", "time": "04:00"})
    assert local_period(daily, "2026-11-17T04:30:00Z") == "2026-11-16"   # 11:30 PM the day before in New York
    assert local_period(weekly, "2026-11-16T09:00:00Z") == "2026-W47"
    assert local_period(weekly, "2026-12-28T09:00:00Z") == "2026-W53"
    assert local_period(weekly, "2027-01-04T09:00:00Z") == "2027-W01"


@pytest.mark.parametrize("own, policy, expected", [(None, "prepare", "prepare"), ("publish_auto", "prepare", "prepare"), ("propose", "publish_soft", "propose"), ("off", "publish_auto", "off")])
def test_a_list_can_narrow_the_policys_rung_and_never_widen_it(own, policy, expected):
    assert effective_rung({"rung": own} if own else {}, policy) == expected


def test_an_announcement_with_a_sent_delivery_is_not_cancelled_as_unsent():
    from papyrus_content.announcements.decisions import Announcements
    from papyrus_content.announcements.deliveries import Deliveries, Plan
    from papyrus_content.announcements.records import RecordError
    from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend

    backend = RecordsBackend()
    announcements = Announcements(backend, Deliveries(backend, MemoryDeliveryFiles(backend)))
    plan = Plan(channel="email", account_id="acct", approval="none", approval_policy="rung publish_auto (list weekly)", text="words", audience=("weekly",))
    made = announcements.announce(dedupe_key="roundup:weekly:2026-W47", kind="roundup", stories=[StoryRef("a", "a-v1", 1)], plans=[plan], created_by="bot", trigger="schedule",
                                  release_at="2026-11-16T09:00:00Z", now="2026-11-16T09:00:00Z")
    announcements.deliveries.finish(made.deliveries[0], "sent", by="bot", note="sent", now="2026-11-16T09:05:00Z")
    with pytest.raises(RecordError, match="not unsent"):
        announcements.cancel_unsent(made.announcement, reason="r", by="bot", now="2026-11-23T09:00:00Z")
