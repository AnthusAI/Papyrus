"""Manual mode (PPY-4410fc): the address of a post a person made by hand, and the guard that keeps a manual Delivery from every automatic path."""
import pytest

from papyrus_content.announcements.attempts import AccountWorker, Attempts, ManualDelivery, manual_address
from papyrus_content.announcements.attempts_fakes import FakeChannel
from papyrus_content.announcements.deliveries import Deliveries, Plan
from papyrus_content.announcements.records import RecordError, attempt_log
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend

NOW = "2026-11-17T09:00:00Z"
URL = "https://example.org/status/1"


def make(mode="manual", state="ready", text="Words a person will post"):
    backend = RecordsBackend()
    deliveries = Deliveries(backend, MemoryDeliveryFiles(backend))
    plan = Plan(channel="x", account_id="ryan", approval="none", approval_policy="test", text=text, mode=mode, state=state)
    row = deliveries.create("announcement-1", plan, release_at=NOW, by="announce", now=NOW)
    return deliveries, Attempts(deliveries), row["id"]


@pytest.mark.parametrize("address", ["https://example.org/a", "http://example.org/a?b=1#c"])
def test_a_web_address_is_accepted(address):
    assert manual_address(f"  {address}  ") == address


@pytest.mark.parametrize("address", ["", "   ", "example.org/a", "ftp://example.org/a", "javascript:alert(1)", "https://", "https:///a", "https://example.org/a b", None])
def test_anything_else_is_refused(address):
    with pytest.raises(RecordError, match="http:// or https://"):
        manual_address(address)


def test_recording_writes_the_attempt_the_state_and_the_address_in_one_change():
    deliveries, attempts, row_id = make()
    row = attempts.record_manual(row_id, URL, by="ryan", now=NOW)
    assert (row["state"], row["resultUrl"]) == ("sent", URL)
    assert attempt_log(row) == [{"number": 1, "at": NOW, "outcome": "sent", "closedAt": NOW, "by": "ryan", "url": URL}]
    assert deliveries.get(row_id)["revision"] == 2
    assert "dueAt" not in deliveries.get(row_id)


def test_the_person_must_be_named():
    _, attempts, row_id = make()
    with pytest.raises(RecordError, match="say who posted it"):
        attempts.record_manual(row_id, URL, by=" ", now=NOW)


def test_recording_twice_is_refused_and_changes_nothing():
    deliveries, attempts, row_id = make()
    attempts.record_manual(row_id, URL, by="ryan", now=NOW)
    with pytest.raises(RecordError, match="already sent"):
        attempts.record_manual(row_id, "https://example.org/other", by="ellie", now=NOW)
    assert deliveries.get(row_id)["resultUrl"] == URL
    assert len(attempt_log(deliveries.get(row_id))) == 1


@pytest.mark.parametrize("state", ["drafted"])
def test_only_a_ready_delivery_is_recorded(state):
    _, attempts, row_id = make(state=state)
    with pytest.raises(RecordError, match="only a ready Delivery"):
        attempts.record_manual(row_id, URL, by="ryan", now=NOW)


def test_an_automatic_delivery_is_not_recorded_by_hand():
    _, attempts, row_id = make(mode="automatic")
    with pytest.raises(RecordError, match="automatic Delivery"):
        attempts.record_manual(row_id, URL, by="ryan", now=NOW)


def test_a_missing_delivery_is_refused():
    _, attempts, _ = make()
    with pytest.raises(RecordError, match="There is no Delivery"):
        attempts.record_manual("nowhere", URL, by="ryan", now=NOW)


def test_a_words_file_that_is_gone_is_refused():
    deliveries, attempts, row_id = make()
    deliveries.files.texts.pop(row_id)
    with pytest.raises(RecordError, match="its words file is missing"):
        attempts.record_manual(row_id, URL, by="ryan", now=NOW)


def test_a_manual_delivery_is_never_releasable():
    deliveries, _, row_id = make()
    assert deliveries.releasable(deliveries.get(row_id), "2030-01-01T00:00:00Z") == (False, "a person posts it by hand and records the address")


def test_no_attempt_opens_and_no_worker_sends_a_manual_delivery():
    deliveries, attempts, row_id = make()
    channel = FakeChannel(deliveries)
    with pytest.raises(ManualDelivery):
        attempts.open(row_id, by="worker", now="2030-01-01T00:00:00Z")
    with pytest.raises(ManualDelivery):
        AccountWorker(deliveries, channel, "x", "ryan").send(row_id, by="worker", now="2030-01-01T00:00:00Z")
    with pytest.raises(ManualDelivery):
        attempts.hand_over(deliveries.get(row_id), {"eventId": "e"}, channel, by="worker", now=NOW)
    assert channel.submissions == [] and not attempt_log(deliveries.get(row_id))
