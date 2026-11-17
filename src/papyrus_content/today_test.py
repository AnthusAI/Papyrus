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
    written |= set(re.findall(r'runStatus: isExternalCliRun \? "([a-zA-Z]+)" : "([a-zA-Z]+)"', started)[0])   # a run that starts as queued or running
    assert {"completed", "failed", "queued", "running", "notRunnable"} <= written, written
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
