import re
from datetime import datetime, timezone
from pathlib import Path

from papyrus_content import overdue

WAKE_QUEUE = Path(__file__).resolve().parents[2] / "amplify" / "agents" / "wake-queue.ts"
RUNNER = Path(__file__).resolve().parent / "procedure_runner.py"


def test_the_flag_id_is_one_per_record_and_due_time():
    first = overdue.flag_id("Delivery", "d1", "2026-11-19T09:00:00Z")
    assert first == overdue.flag_id("Delivery", "d1", "2026-11-19T09:00:00Z")
    assert first != overdue.flag_id("Delivery", "d1", "2026-11-19T10:00:00Z")
    assert first != overdue.flag_id("Delivery", "d2", "2026-11-19T09:00:00Z")
    assert re.match(r"^[a-z0-9][a-z0-9._-]{0,127}$", first)


def test_the_limits_are_the_wake_queues():
    text = WAKE_QUEUE.read_text(encoding="utf-8")
    number = lambda name: int(re.search(rf"export const {name} = (\d+);", text).group(1))  # noqa: E731
    assert number("RUNNER_TIMEOUT_SECONDS") == overdue.RUNNER_TIMEOUT_SECONDS
    assert number("RUNNER_RECORDING_MARGIN_SECONDS") == overdue.RECORDING_MARGIN_SECONDS
    assert number("WAKE_MAXIMUM_RECEIVES") == overdue.MAXIMUM_RECEIVES
    assert f"SECONDS_KEPT_FOR_RECORDING = {overdue.RECORDING_MARGIN_SECONDS}" in RUNNER.read_text(encoding="utf-8")


def test_settled_before_is_the_queue_limits_earlier():
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    assert overdue.settled_before(now) == "2026-11-19T11:28:00Z"
