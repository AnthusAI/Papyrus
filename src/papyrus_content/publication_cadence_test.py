"""The publication's publishing rhythm and the time it suggests (PPY-92164e; docs/scheduled-publishing.md, "Suggest a time")."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from papyrus_content.publication_cadence import NO_HISTORY, CadenceStore, cadence_from_environment, hour_of_week, suggest_time
from papyrus_content.story_schedule import UNRATED_NOTE, Caller, run_operation
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.schedule_support import ZONE, Clock, FakeLockTable, FakeScheduler, new_story, service_for

NEW_YORK = ZoneInfo(ZONE)
SAM = Caller(actor="sam", person="sam-sub", groups=("editor",))


def at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def weekday_mornings(store: CadenceStore, weeks: int = 2) -> None:
    """Ten weekday mornings of the publication's history: 09:00 New York, Monday to Friday, ``weeks`` weeks running up to 9 November 2026."""
    for week in range(weeks):
        for day in range(5):
            store.record_first_publication(at("2026-10-26T14:00:00Z") + timedelta(days=7 * week + day))


def test_the_hour_of_the_week_is_counted_in_the_publication_zone() -> None:
    assert hour_of_week(at("2026-11-09T14:00:00Z"), NEW_YORK) == 9               # Monday 09:00 EST
    assert hour_of_week(at("2026-07-06T13:00:00Z"), NEW_YORK) == 9               # Monday 09:00 EDT: the same hour of the week through the clock change
    assert hour_of_week(at("2026-11-16T04:59:00Z"), NEW_YORK) == 6 * 24 + 23     # Sunday 23:59


def test_a_first_publication_adds_one_to_its_hour_and_to_the_total() -> None:
    table = FakeLockTable()
    store = CadenceStore(table, "site-bucket", ZONE)
    assert store.read() is None
    store.record_first_publication(at("2026-11-09T14:10:00Z"))
    store.record_first_publication(at("2026-11-10T14:50:00Z"))
    store.record_first_publication(at("2026-11-11T18:00:00Z"))
    cadence = store.read()
    assert cadence is not None
    assert cadence.total == 3 and cadence.first_at == at("2026-11-09T14:10:00Z")
    assert dict(cadence.hours) == {9: 1, 24 + 9: 1, 2 * 24 + 13: 1}
    assert table.updates == 3   # one write each, and nothing was read to make it


def test_each_zone_keeps_its_own_hours() -> None:
    table = FakeLockTable()
    CadenceStore(table, "site-bucket", "America/New_York").record_first_publication(at("2026-11-09T14:00:00Z"))
    assert CadenceStore(table, "site-bucket", "Europe/London").read() is None


def test_no_lock_table_or_no_zone_keeps_no_rhythm() -> None:
    assert cadence_from_environment(None, {"PAPYRUS_SITE_BUCKET": "site"}, table=FakeLockTable()) is None
    assert cadence_from_environment(ZONE, {}, table=FakeLockTable()) is None
    assert cadence_from_environment(ZONE, {"PAPYRUS_SITE_BUCKET": "site"}, table=FakeLockTable()) is not None


def test_weekday_mornings_suggest_the_next_weekday_morning() -> None:
    store = CadenceStore(FakeLockTable(), "site", ZONE)
    weekday_mornings(store)
    cadence = store.read()
    # Mean gap: 14 days over 10 publications, 1.4 days. The latest scheduled time is Tuesday 10 Nov 08:00 New York; plus 1.4 days is Wednesday 11 Nov 17:36.
    suggestion = suggest_time(cadence, now=at("2026-11-09T20:00:00Z"), latest_scheduled=at("2026-11-10T13:00:00Z"), zone_name=ZONE)
    assert suggestion.at == at("2026-11-12T14:00:00Z")   # Thursday 09:00 New York: the next hour of the week the publication has used, after that
    assert suggestion.publications == 10


def test_a_window_with_no_history_moves_on_to_the_next_day() -> None:
    store = CadenceStore(FakeLockTable(), "site", ZONE)
    weekday_mornings(store)
    cadence = store.read()
    friday_night = at("2026-11-14T03:00:00Z")   # Friday 22:00 New York, and nothing is scheduled
    suggestion = suggest_time(cadence, now=friday_night, latest_scheduled=None, zone_name=ZONE)
    assert suggestion.at == at("2026-11-16T14:00:00Z")   # Monday 09:00: the weekend holds no past publication


def test_the_busiest_hour_of_the_following_day_wins() -> None:
    store = CadenceStore(FakeLockTable(), "site", ZONE)
    store.record_first_publication(at("2026-10-12T13:00:00Z"))   # a Monday at 09:00 New York
    for week in range(3):
        store.record_first_publication(at("2026-10-12T14:00:00Z") + timedelta(days=7 * week))   # three Mondays at 10:00
    sunday_evening = at("2026-11-09T01:00:00Z")   # Sunday 8 November 20:00 New York
    suggestion = suggest_time(store.read(), now=sunday_evening, latest_scheduled=None, zone_name=ZONE)
    assert suggestion.at == at("2026-11-09T15:00:00Z")   # Monday 10:00, which three past Mondays used, not 09:00, which one did


def test_an_hourly_publication_gets_hourly_slots() -> None:
    store = CadenceStore(FakeLockTable(), "site", ZONE)
    start = at("2026-11-09T00:00:00Z")
    for hour in range(24 * 7):
        store.record_first_publication(start + timedelta(hours=hour))   # a publication that publishes every hour of the week
    now = at("2026-11-16T00:30:00Z")
    first = suggest_time(store.read(), now=now, latest_scheduled=None, zone_name=ZONE)
    assert first.at == at("2026-11-16T01:00:00Z")   # the next whole hour: nothing in the history asks for more spacing
    assert first.mean_gap_hours == pytest.approx(1.0, abs=0.01)


# --- the operation ------------------------------------------------------------------------------------------------------------------------------------


def suggesting(table: FakeLockTable | None = None, zone: str = ZONE, now: str = "2026-11-09T20:00:00Z") -> tuple:
    client = FakeAuthoringClient()
    clock = Clock(now)
    store = CadenceStore(table or FakeLockTable(), "site", zone)
    return client, clock, store, service_for(client, FakeScheduler(), clock, zone, cadence=store)


def test_a_publication_with_no_history_has_no_suggestion_and_says_why() -> None:
    _client, _clock, _store, service = suggesting()
    answer = run_operation("schedule_suggest", {}, service, SAM)
    assert answer == {"ok": True, "suggestion": None, "reason": NO_HISTORY, "timeZone": ZONE}
    assert NO_HISTORY == "No suggestion yet: this publication has no publishing history."


def test_a_site_with_no_cadence_store_has_no_history_either() -> None:
    client = FakeAuthoringClient()
    service = service_for(client, FakeScheduler(), Clock("2026-11-09T20:00:00Z"))
    assert run_operation("schedule_suggest", {}, service, SAM)["suggestion"] is None


def test_the_suggestion_comes_after_the_latest_scheduled_story() -> None:
    client, clock, store, service = suggesting()
    weekday_mornings(store)
    new_story(client, first_published="2026-11-01T15:00:00Z", versions=1)
    scheduled = run_operation("schedule", {"itemId": "item-articles-robots", "at": "2026-11-10 08:00"}, service, SAM)
    assert scheduled["ok"] is True, scheduled
    answer = run_operation("schedule_suggest", {}, service, SAM)
    assert answer["suggestion"]["at"] == "2026-11-12T14:00:00Z"
    assert answer["suggestion"]["latestScheduledAt"] == "2026-11-10T13:00:00Z"
    assert answer["suggestion"]["label"] == "Thu 12 Nov 2026, 09:00 EST"
    own = run_operation("schedule_suggest", {"storyLineageId": "item-articles-robots"}, service, SAM)
    assert own["suggestion"]["latestScheduledAt"] is None   # the Story being moved does not push its own slot away
    assert own["suggestion"]["at"] == "2026-11-10T14:00:00Z"


def test_suggesting_needs_a_time_zone() -> None:
    client = FakeAuthoringClient()
    service = service_for(client, FakeScheduler(), Clock("2026-11-09T20:00:00Z"), zone=None)
    assert run_operation("schedule_suggest", {}, service, SAM)["errors"][0]["code"] == "scheduling-off"


# --- what the drawer reads for one Story -------------------------------------------------------------------------------------------------------------


def test_one_story_listing_says_when_a_newer_version_exists_and_what_an_unrated_story_gets() -> None:
    client, clock, _store, service = suggesting(now="2026-11-10T15:00:00Z")
    new_story(client, versions=3)
    version_three = next(row for row in client.tables["Item"].values() if row.get("versionNumber") == 3)["id"]
    assert run_operation("schedule", {"itemId": version_three, "at": "2026-11-13 09:00"}, service, SAM)["ok"] is True
    from papyrus_content.story_reporting import save_story_version

    save_story_version(client, "item-articles-robots", front_matter_yaml="title: Robots in the warehouse\n", body_markus="Version four.\n", actor="Alex", change_reason="edit", now="2026-11-10T16:00:00Z")
    entry = run_operation("schedule_list", {"storyLineageId": "item-articles-robots"}, service, SAM)["schedules"][0]
    assert entry["newerVersionExists"] is True and entry["state"] == "scheduled"
    assert entry["notes"] == [UNRATED_NOTE]
