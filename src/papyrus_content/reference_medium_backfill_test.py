"""``papyrus references backfill-medium``: safe by default, idempotent, and it touches only the medium fields."""
from __future__ import annotations

import copy
from typing import Any

from .reference_medium_backfill import backfill_medium, planned_fields

CORPUS = "knowledge-corpus-demo"
PLAYLIST = "PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"


def reference(identifier: str, address: str, status: str = "accepted", **extra: Any) -> dict[str, Any]:
    return {"id": identifier, "corpusId": CORPUS, "versionState": "current", "curationStatus": status, "sourceUri": address,
            "feedArrivalAt": "2026-11-01T00:00:00.000Z", **extra}


class Client:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = {row["id"]: copy.deepcopy(row) for row in rows}
        self.updates: list[dict[str, Any]] = []

    def list_by_index(self, index: str, key: str) -> list[dict[str, Any]]:
        assert index == "referencesByCurationStatusKey"
        status = key.rsplit("#", 1)[1]
        return [copy.deepcopy(row) for row in self.rows.values() if row["curationStatus"] == status]

    def update_record(self, model: str, row: dict[str, Any]) -> None:
        assert model == "Reference"
        self.updates.append(row)
        self.rows[row["id"]].update(row)


def corpus() -> list[dict[str, Any]]:
    return [
        reference("v-accepted", "https://youtu.be/dQw4w9WgXcQ"),
        reference("v-pending", "https://vimeo.com/123456789", "pending"),
        reference("v-list", f"https://www.youtube.com/watch?v=JDAPDpbXRXw&list={PLAYLIST}", "rejected"),
        reference("playlist", f"https://www.youtube.com/playlist?list={PLAYLIST}"),
        reference("article", "https://example.org/article"),
        reference("v-archived", "https://youtu.be/dQw4w9WgXcQ", "archived"),
        reference("superseded", "https://youtu.be/dQw4w9WgXcQ", versionState="superseded"),
    ]


def test_without_the_write_flag_it_reports_every_change_and_writes_nothing():
    client, lines = Client(corpus()), []
    results = [backfill_medium(client, corpus_id=CORPUS, progress=lines.append)]   # dry_run defaults to True
    assert client.updates == []
    assert results[0]["dryRun"] is True and results[0]["written"] == 0
    assert results[0]["scanned"] == 6 and results[0]["changed"] == 5 and results[0]["videos"] == 4
    assert results[0]["aggregations"] == 1 and results[0]["playlistsRecorded"] == 1 and results[0]["alreadyRight"] == 1
    assert len(lines) == 5 and all(line.startswith("would write\t") for line in lines)
    assert any("v-accepted" in line and "medium=video" in line and f"{CORPUS}#video#accepted" in line for line in lines)


def test_with_the_write_flag_it_writes_only_the_medium_fields():
    client = Client(corpus())
    result = backfill_medium(client, corpus_id=CORPUS, dry_run=False)
    assert result["written"] == 5
    medium_fields = {"medium", "playlistUrl", "evidenceLevel", "mediumFeedKey", "contentNeededKey"}
    assert all(set(update) - {"id"} <= medium_fields for update in client.updates)
    rows = client.rows
    assert rows["v-accepted"]["mediumFeedKey"] == f"{CORPUS}#video#accepted" and rows["v-accepted"]["medium"] == "video"
    assert rows["v-accepted"]["contentNeededKey"] == f"{CORPUS}#video#needs_content#accepted"   # no capture stored yet: the content is missing
    assert rows["v-list"]["contentNeededKey"] == f"{CORPUS}#video#needs_content#rejected"
    assert "contentNeededKey" not in rows["article"] and "contentNeededKey" not in rows["playlist"] and "contentNeededKey" not in rows["v-archived"]
    assert rows["v-pending"]["mediumFeedKey"] == f"{CORPUS}#video#pending"
    assert rows["v-list"]["mediumFeedKey"] == f"{CORPUS}#video#rejected"
    assert rows["v-list"]["playlistUrl"] == f"https://www.youtube.com/playlist?list={PLAYLIST}"
    assert rows["playlist"]["evidenceLevel"] == "aggregation" and "mediumFeedKey" not in rows["playlist"] and "medium" not in rows["playlist"]
    assert "medium" not in rows["article"] and not any(update["id"] in {"article", "superseded"} for update in client.updates)
    assert rows["v-archived"]["medium"] == "video" and "mediumFeedKey" not in rows["v-archived"]   # archived: tagged, but in no list
    assert rows["v-accepted"]["curationStatus"] == "accepted"   # no vote, no curation field is touched


def test_a_second_run_writes_nothing():
    client = Client(corpus())
    backfill_medium(client, corpus_id=CORPUS, dry_run=False)
    client.updates.clear()
    again = backfill_medium(client, corpus_id=CORPUS, dry_run=False)
    assert client.updates == [] and again["changed"] == 0 and again["alreadyRight"] == 6


def test_an_archived_video_that_holds_a_key_loses_it_and_a_changed_status_moves_it():
    held = reference("v-archived", "https://youtu.be/dQw4w9WgXcQ", "archived", medium="video", mediumFeedKey=f"{CORPUS}#video#accepted")
    assert planned_fields(held) == {"mediumFeedKey": None}
    moved = reference("v-moved", "https://youtu.be/dQw4w9WgXcQ", "rejected", medium="video", mediumFeedKey=f"{CORPUS}#video#accepted",
                      captureState="full")
    assert planned_fields(moved) == {"mediumFeedKey": f"{CORPUS}#video#rejected"}
    held_content = reference("v-held", "https://youtu.be/dQw4w9WgXcQ", "accepted", medium="video", mediumFeedKey=f"{CORPUS}#video#accepted",
                             captureState="full", contentNeededKey=f"{CORPUS}#video#needs_content#accepted")
    assert planned_fields(held_content) == {"contentNeededKey": None}   # captured since: the key leaves


def test_the_content_key_follows_the_stored_capture_state_and_a_settled_reason():
    base = {"medium": "video", "mediumFeedKey": f"{CORPUS}#video#accepted"}
    waiting = f"{CORPUS}#video#needs_content#accepted"
    for extra, wanted in (({}, waiting), ({"captureState": "none"}, waiting), ({"captureState": "thin"}, waiting), ({"captureState": "full"}, None),
                          ({"captureState": "running"}, None), ({"captureState": "thin", "captureReason": "no_transcript"}, None),
                          ({"captureReason": "unavailable"}, None), ({"captureReason": "unsupported_platform"}, None)):
        fields = planned_fields(reference("v", "https://youtu.be/dQw4w9WgXcQ", **base, **extra))
        assert fields.get("contentNeededKey") == wanted, extra
        assert ("contentNeededKey" in fields) is (wanted is not None), extra   # nothing to clear on a row that holds no key
    done = reference("v", "https://youtu.be/dQw4w9WgXcQ", **base, captureState="thin", captureReason="no_transcript")
    assert planned_fields(done) == {}   # a second run does not put a settled video back in the worker's list


def test_the_counts_say_how_many_content_keys_were_set():
    result = backfill_medium(Client(corpus()), corpus_id=CORPUS, dry_run=True)
    assert result["contentKeysSet"] == 3 and result["contentKeysCleared"] == 0


def test_an_evidence_level_a_person_or_model_wrote_is_never_replaced():
    playlist = reference("p", f"https://www.youtube.com/playlist?list={PLAYLIST}", evidenceLevel="primary")
    assert planned_fields(playlist) == {}


def test_the_command_is_safe_by_default_and_writes_only_with_the_write_flag(capsys):
    from unittest import mock

    from .references_commands import references_backfill_medium

    for flags, writes in ((["--site", "demo"], 0), (["--site", "demo", "--dry-run"], 0), (["--site", "demo", "--write"], 5), (["--site", "demo", "--write", "--dry-run"], 0)):
        client = Client(corpus())
        with mock.patch("papyrus_content.references_commands.create_authoring_client", return_value=(client, None)), \
                mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=False):
            references_backfill_medium(flags)
        assert len(client.updates) == writes, flags
        output = capsys.readouterr().out
        assert ("mode\twrite" in output) is (writes > 0)
        assert ("preview (nothing is written; add --write)" in output) is (writes == 0)
