import json
from pathlib import Path

from .reference_capture_state import capture_state, is_captured, normalize_capture_state, sync_capture_state

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "capture-state-vectors.json").read_text())["vectors"]


def test_the_state_matches_the_vectors_the_typescript_twin_is_tested_against():
    for vector in VECTORS:
        assert capture_state(vector["attachments"]) == vector["expected"], vector["name"]


def test_the_stored_value_reads_empty_and_unknown_as_none_and_only_full_is_captured():
    for value in (None, "", "weird", 3):
        assert normalize_capture_state(value) == "none"
    for state in ("full", "thin", "none", "running"):
        assert normalize_capture_state(state) == state
    assert is_captured("full")
    assert not any(is_captured(value) for value in ("thin", "none", "running", "", None))


class FakeClient:
    def __init__(self, attachments=()):
        self.attachments = list(attachments)
        self.updates = []
        self.listed = 0

    def list_by_index(self, name, key):
        self.listed += 1
        return self.attachments

    def update_record(self, model, payload):
        self.updates.append((model, payload))


def _vector(name):
    return next(v for v in VECTORS if v["name"] == name)["attachments"]


def test_sync_writes_only_when_the_state_differs_and_never_writes_none():
    client = FakeClient(_vector("no attachments is none"))
    reference = {"id": "r", "lineageId": "l"}
    assert sync_capture_state(client, reference) is None and client.updates == []
    client = FakeClient(_vector("an old extracted text of many words is full"))
    assert sync_capture_state(client, reference) == "full"
    assert client.updates == [("Reference", {"id": "r", "captureState": "full"})]
    assert sync_capture_state(client, reference) is None   # idempotent
    stale = {"id": "r", "lineageId": "l", "captureState": "thin"}
    client = FakeClient([])
    assert sync_capture_state(client, stale) == "none" and client.updates == [("Reference", {"id": "r", "captureState": None})]


def test_sync_does_not_read_attachments_when_the_card_holds_text():
    card = next(row for row in _vector("a long captured text is full") if row["role"] == "curation")["metadata"]
    client = FakeClient()
    assert sync_capture_state(client, {"id": "r"}, card) == "full"
    assert client.listed == 0
