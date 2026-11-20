"""The conversion of kept alert rows: one Announcement for each Story, a finished Delivery, and the same answer when it runs again."""
from __future__ import annotations

from papyrus_content.announcements import alert_conversion as conversion, records
from papyrus_content.announcements.decisions import Announcements
from papyrus_content.announcements.deliveries import Deliveries
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend

NOW = "2026-11-17T09:00:00Z"


def kept(list_id: str, lineage: str, issue: str) -> conversion.KeptRow:
    return conversion.KeptRow(list_id, lineage, issue, "2026-11-10T09:00:00Z")


def world():
    backend = RecordsBackend()
    return backend, Announcements(backend, Deliveries(backend, MemoryDeliveryFiles(backend)))


ISSUES = {"a1": {"issueId": "a1", "status": "sent", "sourceItemId": "s-v2", "bodyMarkus": "## [S](https://x.test/s)\n"}, "a2": {"issueId": "a2", "status": "awaiting_approval"}}
ITEMS = {"s-v2": {"id": "s-v2", "versionNumber": 2}}


def run(announcements, rows):
    return conversion.convert(conversion.plan(rows), announcements, read_issue=ISSUES.get, read_item=ITEMS.get, account_id="site-send", now=NOW)


def test_rows_of_one_story_become_one_conversion_with_every_list() -> None:
    (found,) = conversion.plan([kept("b", "s", "a1"), kept("a", "s", "a1")])
    assert found.lineage == "s" and found.lists == ("a", "b")


def test_a_sent_alert_becomes_a_sent_delivery_with_its_words_and_runs_once() -> None:
    backend, announcements = world()
    rows = [kept("a", "s", "a1"), kept("b", "s", "a1")]
    first = run(announcements, rows)
    assert (first.announcements, first.deliveries_sent, first.unchanged) == (1, 1, 0)
    (delivery,) = backend.rows("Delivery")
    assert delivery["state"] == records.SENT and sorted(delivery["audience"]) == ["a", "b"] and len(records.attempt_log(delivery)) == 1
    assert announcements.by_dedupe_key(records.story_published_key("s"))["state"] == records.RELEASED
    again = run(announcements, rows)
    assert (again.announcements, again.deliveries_sent, again.unchanged) == (0, 0, 1)
    assert len(backend.rows("Delivery")) == 1 and len(records.attempt_log(backend.rows("Delivery")[0])) == 1


def test_an_alert_that_never_went_is_withdrawn() -> None:
    backend, announcements = world()
    result = run(announcements, [kept("a", "t", "a2")])
    assert (result.deliveries_withdrawn, result.deliveries_sent) == (1, 0)
    assert backend.rows("Delivery")[0]["state"] == records.DELIVERY_WITHDRAWN
