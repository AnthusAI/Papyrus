"""The pure rules of the Announcement and Delivery records (features_backend/announcement-*.feature and delivery-*.feature hold the behaviour)."""
from __future__ import annotations

import pytest

from papyrus_content.announcements import records


def test_utc_converts_an_offset_and_refuses_a_local_time():
    assert records.utc("2026-11-17T09:00:00-05:00") == "2026-11-17T14:00:00Z"
    assert records.utc("2026-11-17T14:00:00Z") == "2026-11-17T14:00:00Z"
    assert records.utc(None) is None and records.utc("") is None
    with pytest.raises(records.RecordError, match="needs its offset"):
        records.utc("2026-11-17T09:00:00")


def test_ids_are_permanent_functions_of_their_keys():
    assert records.announcement_id("story-published:a") == records.announcement_id("story-published:a")
    assert records.announcement_id("story-published:a") != records.announcement_id("story-published:b")
    assert records.delivery_id("announcement-1", "x", "handle", 2) == "announcement-1#x#handle#g2"


def test_due_is_the_earliest_pending_time():
    row = {"state": "ready", "releaseAt": "2026-11-17T09:00:00Z", "lockAt": "2026-11-17T08:00:00Z", "nextAttemptAt": "2026-11-17T07:00:00Z"}
    assert records.due_at(row) == "2026-11-17T07:00:00Z"
    assert records.due_at({**row, "nextAttemptAt": None}) == "2026-11-17T08:00:00Z"
    assert records.due_at({**row, "nextAttemptAt": None, "lockedAt": "2026-11-16T00:00:00Z"}) == "2026-11-17T09:00:00Z"


@pytest.mark.parametrize("state", ["sent", "failed", "dry_run", "withdrawn", "superseded"])
def test_a_final_delivery_waits_for_nothing(state):
    row = {"state": state, "releaseAt": "2026-11-17T09:00:00Z", "lockAt": "2026-11-17T09:00:00Z", "nextAttemptAt": "2026-11-17T10:00:00Z"}
    assert records.due_at(row) is None
    assert "dueAt" not in records.with_due({**row, "dueAt": "2026-11-17T09:00:00Z", "dueKey": "due"})


def test_a_sending_delivery_waits_only_for_its_next_attempt():
    row = {"state": "sending", "releaseAt": "2026-11-17T09:00:00Z", "lockAt": "2026-11-17T09:00:00Z"}
    assert records.due_at(row) is None
    assert records.due_at({**row, "nextAttemptAt": "2026-11-17T10:00:00Z"}) == "2026-11-17T10:00:00Z"


def test_the_catalog_refuses_text():
    records.require_catalog_only({"id": "d", "textKey": "newsroom/payloads/delivery/d/delivery-text/delivery.md"})
    for field in records.TEXT_FIELDS:
        with pytest.raises(records.RecordError, match="holds no text"):
            records.require_catalog_only({"id": "d", field: "words"})


def test_stored_leaves_out_empty_values_on_create_and_sends_null_on_update():
    row = {"id": "d", "history": [{"at": "t"}], "dueAt": None}
    assert records.stored(row) == {"id": "d", "history": '[{"at": "t"}]'}
    assert records.stored(row, clearing=True) == {"id": "d", "history": '[{"at": "t"}]', "dueAt": None}


def test_the_history_only_grows():
    first = records.history_with({}, at="t1", by="a", state="planned", note="decided")
    second = records.history_with({"history": first}, at="t2", by="b", state="released", note="released")
    assert second[:1] == first and len(second) == 2
