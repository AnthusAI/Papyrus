"""Corrections of a Delivery (``Deliveries.supersede``) and the first words of a draft (``write_words``); the Gherkin is delivery-corrections-hardening.feature."""
from __future__ import annotations

import pytest

from papyrus_content.announcements.deliveries import AlreadySuperseded, CorrectedDifferently, Conflict, Deliveries, NotSent, OpenAttempt, Plan
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend

NOW = "2026-11-17T09:00:00Z"
RELEASE = "2026-11-17T09:00:00Z"


def make():
    backend = RecordsBackend()
    files = MemoryDeliveryFiles(backend)
    return backend, files, Deliveries(backend, files)


def plan(text, **kwargs):
    return Plan(channel="x", account_id="handle-1", approval="none", approval_policy="test policy", text=text, **kwargs)


def sent_delivery(deliveries, text="First words"):
    row = deliveries.create("announcement-1", plan(text), release_at=RELEASE, by="test", now=NOW)
    return deliveries.finish(row, "sent", by="worker", note="sent", now=NOW)


def test_an_unsent_delivery_is_not_corrected():
    backend, _, deliveries = make()
    row = deliveries.create("announcement-1", plan("First words"), release_at=RELEASE, by="test", now=NOW)
    with pytest.raises(NotSent, match="edited, not corrected"):
        deliveries.supersede(row, plan("Other words"), by="ellie", now=NOW)
    assert len(backend.rows("Delivery")) == 1


def test_an_open_attempt_is_settled_before_a_correction():
    backend, _, deliveries = make()
    row = sent_delivery(deliveries)
    open_row = {**deliveries.get(row["id"]), "attempts": [{"number": 1, "outcome": "started"}]}
    backend.records["Delivery"][row["id"]]["attempts"] = open_row["attempts"]
    with pytest.raises(OpenAttempt):
        deliveries.supersede(row, plan("Other words"), by="ellie", now=NOW)


def test_a_retry_with_a_fresh_read_that_already_points_forward_writes_the_relation():
    backend, _, deliveries = make()
    old = sent_delivery(deliveries)
    backend.fail_next("create", "SemanticRelation")
    with pytest.raises(RuntimeError):
        deliveries.supersede(old, plan("Corrected"), by="ellie", now=NOW)
    fresh = deliveries.get(old["id"])
    assert fresh["supersededBy"]
    successor = deliveries.supersede(fresh, plan("Corrected"), by="ellie", now=NOW)
    assert successor["supersedes"] == old["id"]
    assert [row["predicate"] for row in backend.rows("SemanticRelation")] == ["supersedes"]


def test_a_retry_from_a_stale_copy_finishes_the_same_way():
    backend, _, deliveries = make()
    old = sent_delivery(deliveries)
    backend.fail_next("update", "Delivery")
    with pytest.raises(RuntimeError):
        deliveries.supersede(old, plan("Corrected"), by="ellie", now=NOW)
    deliveries.supersede(old, plan("Corrected"), by="ellie", now=NOW)
    assert deliveries.get(old["id"])["state"] == "superseded"
    assert len(backend.rows("SemanticRelation")) == 1


def test_a_different_correction_is_a_conflict_and_writes_nothing_of_its_own():
    backend, files, deliveries = make()
    old = sent_delivery(deliveries)
    backend.fail_next("update", "Delivery")
    first = plan("First correction")
    with pytest.raises(RuntimeError):
        deliveries.supersede(old, first, by="ellie", now=NOW)
    successor_id = old["id"].replace("#g1", "#g2")
    files.texts.pop(files.file_key(successor_id), None)   # the first caller's words file was lost with its crash
    with pytest.raises(CorrectedDifferently, match="already corrected") as raised:
        deliveries.supersede(old, plan("Second correction"), by="sierra", now=NOW)
    assert isinstance(raised.value, Conflict) and raised.value.successor == successor_id
    assert files.file_key(successor_id) not in files.texts
    deliveries.supersede(old, first, by="ellie", now=NOW)
    assert files.texts[files.file_key(successor_id)] == "First correction"


def test_a_delivery_that_points_at_another_successor_is_refused():
    backend, _, deliveries = make()
    old = sent_delivery(deliveries)
    backend.records["Delivery"][old["id"]]["supersededBy"] = "announcement-1#x#handle-1#g9"
    with pytest.raises(AlreadySuperseded):
        deliveries.supersede(old, plan("Second"), by="ellie", now=NOW)


def test_write_words_edits_a_draft_in_place():
    backend, files, deliveries = make()
    draft = deliveries.create("announcement-1", plan("", state="drafted"), release_at=RELEASE, by="test", now=NOW)
    written = deliveries.write_words(draft, plan("Hello", drafted_by="ellie"), by="ellie", now=NOW)
    assert written["state"] == "ready" and written["generation"] == 1 and written["textKey"]
    assert files.texts[files.file_key(draft["id"], "v1")] == "Hello" and len(backend.rows("Delivery")) == 1
    with pytest.raises(Exception, match="already has its words"):
        deliveries.write_words(written, plan("Again"), by="ellie", now=NOW)
