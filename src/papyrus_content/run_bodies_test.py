"""A run's bodies as one attachment (the behaviour is in features_backend/agents/run-bodies-in-s3.feature)."""
import json

import pytest

from papyrus_content import run_bodies


class AttachmentStore:
    def __init__(self):
        self.attachments, self.files = [], {}

    def list_by_index(self, index, key, limit=100):
        assert index == run_bodies.ATTACHMENTS_BY_OWNER_INDEX
        return [attachment for attachment in self.attachments if attachment["ownerId"] == key]


@pytest.fixture
def store(monkeypatch):
    found = AttachmentStore()

    def upload(client, attachment, body):
        found.attachments = [row for row in found.attachments if row["id"] != attachment["id"]] + [attachment]
        found.files[attachment["id"]] = body
        return attachment

    monkeypatch.setattr(run_bodies, "upload_attachment_body", upload)
    monkeypatch.setattr(run_bodies, "download_attachment_buffer", lambda client, attachment: found.files[attachment["id"]])
    return found


def test_a_run_body_is_one_json_attachment_of_the_run_and_reads_back_whole(store):
    run_bodies.write_run_body(store, "run-1", {"input": {"story": "s"}, "output": {"title": "t"}}, now="2026-11-20T00:00:00Z")
    (attachment,) = store.attachments
    assert (attachment["ownerKind"], attachment["role"], attachment["ownerId"], attachment["mediaType"]) == ("procedureRun", "run_body", "run-1", "application/json")
    assert run_bodies.read_run_body(store, "run-1") == {"input": {"story": "s"}, "normalizedInput": None, "output": {"title": "t"}, "error": None}
    assert json.loads(store.files[attachment["id"]])["normalizedInput"] is None


def test_writing_again_replaces_the_runs_body_and_does_not_add_a_second(store):
    run_bodies.write_run_body(store, "run-1", {"output": {"n": 1}}, now="2026-11-20T00:00:00Z")
    run_bodies.write_run_body(store, "run-1", {"output": {"n": 2}}, now="2026-11-20T00:01:00Z")
    assert len(store.attachments) == 1 and run_bodies.read_run_body(store, "run-1")["output"] == {"n": 2}


def test_a_run_without_a_stored_body_says_which_run(store):
    with pytest.raises(run_bodies.RunBodyMissing, match="run-9"):
        run_bodies.read_run_body(store, "run-9")


def test_a_field_that_is_not_a_body_is_refused(store):
    with pytest.raises(ValueError, match="resultSummary"):
        run_bodies.write_run_body(store, "run-1", {"resultSummary": "short"}, now="2026-11-20T00:00:00Z")
