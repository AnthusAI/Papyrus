"""Retiring GROBID citation stubs and restoring a machine-archived one: only untouched stubs, archive never delete, no feed, idempotent."""
import copy

import pytest

from papyrus_content.reference_citation_stubs import (RETIRED_BY, RESTORED_BY, STUB_CHANGE_REASON, STUB_CREATED_BY, STUB_STATUS_REASON,
                                                      is_machine_retired, restored_fields, retire_citation_stubs, retired_fields, skip_reason)
from papyrus_content.reference_feed_keys import feed_keys

CORPUS = "knowledge-corpus-example"
NOW = "2026-11-03T12:00:00.000Z"


def stub(name, **extra):
    row = {"id": f"{name}-v1", "lineageId": name, "versionNumber": 1, "versionState": "current", "corpusId": CORPUS,
           "changeReason": STUB_CHANGE_REASON, "curationStatus": "pending", "curationStatusKey": f"{CORPUS}#pending",
           "curationStatusUpdatedBy": STUB_CREATED_BY, "curationStatusReason": STUB_STATUS_REASON, "curationStatusUpdatedAt": "2026-10-01T00:00:00Z",
           "createdAt": "2026-10-01T00:00:00Z", "sourceUri": f"https://example.org/{name}", "inboundCitationCount": 0,
           "newsroomFeedKey": "references", "reviewedFeedKey": None}
    row.update(extra)
    row.update({key: extra.get(key, value) for key, value in feed_keys(row).items()})
    return row


class Client:
    def __init__(self, rows):
        self.rows = {row["id"]: row for row in rows}
        self.writes = []

    def list_by_index(self, index, key):
        assert index == "referencesByCurationStatusKey"
        return [copy.deepcopy(row) for row in self.rows.values() if f"{row['corpusId']}#{row['curationStatus']}" == key]

    def update_record(self, model, payload):
        assert model == "Reference"
        self.writes.append(copy.deepcopy(payload))
        self.rows[payload["id"]].update(payload)


def test_an_untouched_stub_is_eligible_and_a_predicted_one_too():
    assert skip_reason(stub("plain")) is None
    assert skip_reason(stub("predicted", predictedAcceptProbability=0.2, predictionDecidedAt="2026-10-02T00:00:00Z")) is None


@pytest.mark.parametrize("extra, reason", [
    ({"versionState": "superseded"}, "notCurrent"),
    ({"curationStatus": "accepted"}, "notPending"),
    ({"changeReason": "reference-import"}, "notCitationGraph"),
    ({"curationStatusReason": "Looks relevant"}, "notCitationGraph"),
    ({"curationStatusUpdatedBy": "an editor"}, "notSystemActor"),
    ({"starRating": 4}, "starred"),
    ({"starFeedKey": f"{CORPUS}#stars#2"}, "starred"),
    ({"curationActorKind": "human"}, "voted"),
])
def test_anything_else_is_skipped_with_its_reason(extra, reason):
    assert skip_reason(stub("other", **extra)) == reason


def test_the_command_archives_only_eligible_rows_and_counts_the_facts():
    rows = [stub("a"), stub("b", sourceUri=None, inboundCitationCount=3), stub("c", predictionDecidedAt="2026-10-02T00:00:00Z", predictedAcceptProbability=0.9),
            stub("starred", starRating=5), stub("human", curationStatusUpdatedBy="an editor"), stub("old", versionState="superseded")]
    client = Client(rows)
    counts = retire_citation_stubs(client, corpus_id=CORPUS, now=NOW)
    assert (counts["scanned"], counts["eligible"], counts["withUrl"], counts["withoutUrl"], counts["written"]) == (6, 3, 2, 1, 3)
    assert counts["withInboundCitations"] == 1 and counts["withPrediction"] == 1
    assert (counts["skipped"], counts["skipped.starred"], counts["skipped.notSystemActor"], counts["skipped.notCurrent"]) == (3, 1, 1, 1)
    assert sorted(write["id"] for write in client.writes) == ["a-v1", "b-v1", "c-v1"]
    assert all(client.rows[name]["curationStatus"] == "pending" for name in ("starred-v1", "human-v1", "old-v1"))


def test_a_retired_stub_is_archived_in_place_out_of_every_feed_and_nothing_is_deleted():
    client = Client([stub("a", predictionDecidedAt="2026-10-02T00:00:00Z", predictedAcceptProbability=0.2)])
    retire_citation_stubs(client, corpus_id=CORPUS, now=NOW)
    row = client.rows["a-v1"]
    assert (row["curationStatus"], row["curationStatusKey"], row["curationStatusUpdatedBy"], row["curationStatusUpdatedAt"]) == (
        "archived", f"{CORPUS}#archived", RETIRED_BY, NOW)
    assert row["feedStateKey"] is None and row["reviewedFeedKey"] == "references#reviewed"
    assert row["predictedAcceptProbability"] == 0.2 and row["sourceUri"] == "https://example.org/a"   # the record and its prediction stay
    assert "curationActorKind" not in row   # a retirement is no vote
    assert set(client.writes[0]) <= {"id", "curationStatus", "curationStatusKey", "curationStatusUpdatedAt", "curationStatusUpdatedBy",
                                     "curationStatusReason", "reviewedFeedKey", "feedStateKey", "updatedAt"}


def test_a_dry_run_counts_and_writes_nothing():
    client = Client([stub("a"), stub("b")])
    counts = retire_citation_stubs(client, corpus_id=CORPUS, dry_run=True, now=NOW)
    assert counts["eligible"] == 2 and counts["written"] == 0 and client.writes == []


def test_running_it_again_is_a_no_op():
    client = Client([stub("a"), stub("b")])
    retire_citation_stubs(client, corpus_id=CORPUS, now=NOW)
    client.writes.clear()
    again = retire_citation_stubs(client, corpus_id=CORPUS, now=NOW)
    assert again["scanned"] == 0 and again["written"] == 0 and client.writes == []


def test_only_a_row_the_machine_archived_is_machine_retired():
    archived = {**stub("a"), **retired_fields(stub("a"), now=NOW)}
    assert is_machine_retired(archived)
    assert not is_machine_retired({**archived, "curationStatusUpdatedBy": "an editor"})
    assert not is_machine_retired({**archived, "curationStatus": "rejected"})
    assert not is_machine_retired({**archived, "versionState": "superseded"})
    assert not is_machine_retired(None)


def test_restoring_returns_it_to_pending_in_the_unrated_feed_and_keeps_its_prediction():
    retired = {**stub("a", predictionDecidedAt="2026-10-02T00:00:00Z", predictedAcceptProbability=0.7), "curationStatus": "archived"}
    retired.update(retired_fields(retired, now=NOW))
    fields = restored_fields(retired, now="2026-11-04T00:00:00Z")
    assert (fields["curationStatus"], fields["curationStatusKey"], fields["curationStatusUpdatedBy"]) == ("pending", f"{CORPUS}#pending", RESTORED_BY)
    assert fields["feedStateKey"] == f"{CORPUS}#unrated" and fields["reviewedFeedKey"] is None
    assert fields["predictionSortKey"].startswith("0.700000#")
    assert not is_machine_retired({**retired, **fields})
    # and a restored row is not a stub again: the next retire run leaves it alone
    assert skip_reason({**retired, **fields}) == "notCitationGraph"
