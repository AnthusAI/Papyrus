import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from papyrus_content import today

ROOT = Path(__file__).resolve().parents[2]


def test_every_run_status_the_runner_writes_is_read():
    """A status missing from RUN_STATUSES would drop its runs from Today without a word."""
    written = set()
    for path in (ROOT / "src/papyrus_content/procedure_runner.py", ROOT / "src/papyrus_content/run_outcomes.py"):
        written |= set(re.findall(r"""runStatus["']?\s*[:=]\s*"([a-zA-Z]+)\"""", path.read_text()))
    started = (ROOT / "amplify/functions/procedure-action/handler.ts").read_text()
    written |= set(re.findall(r'runStatus: isExternalCliRun \? "([a-zA-Z]+)" : "([a-zA-Z]+)"', started)[0])   # a run that starts as queued or started
    assert {"completed", "failed", "queued", "started", "notRunnable"} <= written, written
    assert written <= set(today.RUN_STATUSES), written - set(today.RUN_STATUSES)


def test_day_bounds_follow_the_time_zone_through_a_clock_change():
    # 1 November 2026 is the day New York's clocks go back: that day is 25 hours long.
    bounds = today.day_bounds("2026-11-01", "America/New_York", datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    assert bounds["start"] == "2026-11-01T04:00:00.000Z" and bounds["end"] == "2026-11-02T05:00:00.000Z"


def test_default_day_is_today_in_the_zone():
    late = datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc)   # Monday evening in New York
    assert today.day_bounds(None, "America/New_York", late)["day"] == "2026-11-16"
    assert today.day_bounds(None, None, late)["day"] == "2026-11-17"


@pytest.mark.parametrize("day, zone", [("16 Nov", "UTC"), ("2026-02-30", "UTC"), ("2026-11-16", "Nowhere/Land")])
def test_a_day_or_zone_that_does_not_exist_is_refused(day, zone):
    with pytest.raises(today.TodayError):
        today.day_bounds(day, zone, datetime(2026, 11, 16, tzinfo=timezone.utc))


# --- Today's top and Due today (today-attention.feature has the behaviour) ------------------------------------------

from papyrus_content import today_attention  # noqa: E402
from papyrus_content.cron_fires import CronError, fires_between  # noqa: E402

UTC = timezone.utc


def _day(day: str, zone: str):
    bounds = today.day_bounds(day, zone, datetime(2026, 11, 16, tzinfo=UTC))
    return datetime.fromisoformat(bounds["start"].replace("Z", "+00:00")), datetime.fromisoformat(bounds["end"].replace("Z", "+00:00"))


def test_a_daily_schedule_fires_once_at_its_local_time():
    start, end = _day("2026-11-16", "America/New_York")
    assert fires_between("0 6 * * *", "America/New_York", start, end) == [datetime(2026, 11, 16, 11, 0, tzinfo=UTC)]


def test_a_schedule_in_another_zone_fires_inside_the_sites_day():
    start, end = _day("2026-11-16", "America/New_York")
    assert fires_between("30 1 * * *", "Europe/London", start, end) == [datetime(2026, 11, 17, 1, 30, tzinfo=UTC)]


def test_a_schedule_keeps_its_local_time_through_a_clock_change():
    start, end = _day("2026-11-01", "America/New_York")   # New York's clocks go back that night
    assert fires_between("0 6 * * *", "America/New_York", start, end) == [datetime(2026, 11, 1, 11, 0, tzinfo=UTC)]
    spring_start, spring_end = _day("2026-03-08", "America/New_York")
    assert fires_between("30 2 * * *", "America/New_York", spring_start, spring_end) == [], "2:30 AM does not exist that night"


@pytest.mark.parametrize("cron, fires", [
    ("0 9 * * MON", True), ("0 9 * * 1", True), ("0 9 * * 2-5", False), ("0 9 * * 1#3", True), ("0 9 * * 1L", False),
    ("0 9 16 * ?", True), ("0 9 L * ?", False), ("0 9 16W * ?", True), ("0 9 * NOV *", True), ("0 9 * DEC *", False), ("*/30 9 * * *", True),
])
def test_day_and_month_forms(cron, fires):
    start, end = _day("2026-11-16", "America/New_York")   # Monday 16 November 2026, the third Monday
    assert bool(fires_between(cron, "America/New_York", start, end)) is fires


def test_steps_fire_on_every_step():
    start, end = _day("2026-11-16", "UTC")
    assert len(fires_between("*/15 * * * *", "UTC", start, end)) == 96


def test_a_schedule_the_scheduler_cannot_run_is_refused():
    start, end = _day("2026-11-16", "UTC")
    with pytest.raises(CronError):
        fires_between("0 9 16 * MON", "UTC", start, end)


def test_local_time_names_another_day():
    assert today_attention.local_time("2026-11-16T20:30:00Z", "America/New_York", "2026-11-16") == "3:30 PM"
    assert today_attention.local_time("2026-11-17T05:00:00Z", "America/New_York", "2026-11-16") == "Tuesday 17 November, 12:00 AM"
    assert today_attention.local_time(None, "UTC", "2026-11-16") is None


def test_the_site_time_zone_comes_from_its_publication_setting():
    assert today_attention.site_time_zone({today_attention.SITE_TIME_ZONE_ENV: " America/New_York "}) == "America/New_York"
    assert today_attention.site_time_zone({}) is None
