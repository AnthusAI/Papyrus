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


class OneRecord:
    def __init__(self, rows):
        self.rows = rows

    def get_record(self, model, record_id):
        return self.rows.get((model, record_id))


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def timer_request(row):
    return {"wakeKey": f"deliver|{row['id']}|{row['dueAt']}|due", "trigger": {"kind": "follow-up", "summary": f"{row['id']} was waiting until {row['dueAt']}"}}


def test_wake_now_sends_the_timers_own_key_once_and_says_who_and_why():
    import pytest

    rows = {("Delivery", "d1"): {"id": "d1", "dueAt": "2026-11-19T09:00:00Z", "dueKey": "due", "releaseAt": "2026-11-19T09:00:00Z"}}
    sent = []
    result = overdue.wake_now(OneRecord(rows), kind="Delivery", record_id="d1", reason="The email did not go out", by="ada@example.test", person=True,
                              wake_requests={"Delivery": timer_request}, send=sent.append, now=NOW)
    (request,) = sent
    assert request["wakeKey"] == result["wakeKey"] == "deliver|d1|2026-11-19T09:00:00Z|due"
    assert request["trigger"]["poke"] == {"kind": "wake_overdue", "by": "ada@example.test", "reason": "The email did not go out", "at": "2026-11-19T12:00:00Z",
                                          "repeats": "deliver|d1|2026-11-19T09:00:00Z|due"}
    assert request["trigger"]["summary"].startswith("ada@example.test woke it now (The email did not go out); this repeats: d1 was waiting until")
    for kind, record_id, person, reason, code in (("Delivery", "d1", False, "r", "human_required"), ("Delivery", "d1", True, " ", "invalid_input"),
                                                  ("Item", "d1", True, "r", "invalid_input"), ("Delivery", "missing", True, "r", "not_found")):
        with pytest.raises(overdue.OverdueWakeError) as refused:
            overdue.wake_now(OneRecord(rows), kind=kind, record_id=record_id, reason=reason, by="x", person=person, wake_requests={"Delivery": timer_request},
                             send=sent.append, now=NOW)
        assert refused.value.code == code
    assert len(sent) == 1


def test_only_an_overdue_record_is_woken():
    assert overdue.is_overdue("Delivery", {"dueAt": "2026-11-19T11:28:00Z"}, NOW)
    assert not overdue.is_overdue("Delivery", {"dueAt": "2026-11-19T11:29:00Z"}, NOW)
    assert not overdue.is_overdue("Delivery", {"id": "d"}, NOW)
    assert overdue.is_overdue("ReviewRequest", {"state": "open", "dueAt": "2026-11-19T09:00:00Z"}, NOW)
    assert not overdue.is_overdue("ReviewRequest", {"state": "answered", "dueAt": "2026-11-19T09:00:00Z"}, NOW)


def test_a_site_that_names_no_timers_is_refused_when_a_wake_is_built():
    import pytest

    requests = overdue.site_timer_wake_requests({}, appsync_endpoint="https://example.test/graphql")
    with pytest.raises(overdue.OverdueWakeError) as refused:
        requests["Delivery"]({"id": "d1", "dueAt": "2026-11-19T09:00:00Z"})
    assert refused.value.code == "service_unavailable" and "PAPYRUS_AGENT_PUBLICATION_ID" in refused.value.message
