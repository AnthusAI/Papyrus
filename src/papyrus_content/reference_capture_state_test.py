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


# --- a video waiting for its transcript: the capture reason and the sparse content-needed key ------------------------------------------------


def _video(**extra):
    return {"id": "r", "lineageId": "l", "corpusId": "c", "versionState": "current", "curationStatus": "accepted", "medium": "video", **extra}


def _card(reason=None, edited=False):
    capture = {"status": "completed", "wordCount": 900, "textSortKey": "curation-text", **({"textReason": reason} if reason else {})}
    return {"kind": "reference-curation", "status": "degraded", "capture": capture, "signals": {"wordCount": 900}, "labels": [],
            "current": {"textSortKey": "curation-edit-0001-text" if edited else "curation-text"}}


def test_a_video_captured_from_its_page_is_thin_and_in_the_content_needed_list():
    client, reference = FakeClient(), _video()
    assert sync_capture_state(client, reference, _card("awaiting_transcript")) == "thin"
    assert client.updates == [("Reference", {"id": "r", "captureState": "thin", "contentNeededKey": "c#video#needs_content#accepted"})]


def test_the_transcript_a_person_or_the_worker_saved_makes_it_full_and_removes_the_key():
    client = FakeClient()
    reference = _video(captureState="thin", contentNeededKey="c#video#needs_content#accepted")
    assert sync_capture_state(client, reference, _card("awaiting_transcript", edited=True)) == "full"
    assert client.updates == [("Reference", {"id": "r", "captureState": "full", "contentNeededKey": None})]
    assert sync_capture_state(client, reference, _card("awaiting_transcript", edited=True)) is None   # nothing more to write


def test_a_settled_reason_keeps_the_video_thin_records_the_reason_and_takes_it_out_of_the_list():
    client = FakeClient()
    reference = _video(captureState="thin", contentNeededKey="c#video#needs_content#accepted")
    assert sync_capture_state(client, reference, _card("no_transcript")) is None   # the state itself did not change
    assert client.updates == [("Reference", {"id": "r", "captureReason": "no_transcript", "contentNeededKey": None})]
    assert reference["captureReason"] == "no_transcript"
    assert sync_capture_state(client, reference, _card("no_transcript")) is None and len(client.updates) == 1


def test_text_supplied_after_a_settled_reason_clears_the_reason():
    client = FakeClient()
    reference = _video(captureState="thin", captureReason="no_transcript")
    sync_capture_state(client, reference, _card("no_transcript", edited=True))
    assert client.updates == [("Reference", {"id": "r", "captureState": "full", "captureReason": None})]


def test_an_ordinary_page_never_gets_either_field():
    client = FakeClient()
    sync_capture_state(client, {"id": "r", "corpusId": "c", "curationStatus": "accepted", "sourceUri": "https://example.org/a"}, _card())
    assert client.updates == [("Reference", {"id": "r", "captureState": "full"})]
