"""The suggestion-index backfill: in-memory fakes, no network (features_backend/reference-link-suggestion-index.feature)."""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", pathlib.Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.reference_links import NO_SCORE_SORT_VALUE, OPEN_SUGGESTION_KEY, decide, link_concept, link_references  # noqa: E402
from papyrus_content.reference_suggestion_backfill import backfill_suggestion_index, planned_fields  # noqa: E402
from test_reference_links import NODE, FakeClient  # noqa: E402

NOW = "2026-11-01T12:00:00Z"


def legacy_client():
    """Three suggestions written before the index existed (no key), one rejected, one accepted by an editor."""
    client = FakeClient()
    link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.8, now=NOW)
    link_references(client, "reference-a", "reference-c", "related_to", "suggested", actor="auto:vector", score=None, now=NOW)
    link_concept(client, "reference-b", NODE, "suggested", actor="auto:vector", score=0.6, now=NOW)
    rejected = link_references(client, "reference-b", "reference-c", "related_to", "suggested", actor="auto:vector", score=0.9, now=NOW)["relationId"]
    decide(client, rejected, "rejected", None, None, "sub-1", now=NOW)
    link_references(client, "reference-a", "reference-c", "cites", "human", actor="sub-1", now=NOW)
    for row in client.tables["SemanticRelation"].values():
        if row["relationState"] == "suggested":
            row.pop("openSuggestionKey"), row.pop("openSuggestionScore")
    return client


def test_every_open_suggestion_gets_the_key_and_a_sort_value_and_nothing_else_changes():
    client = legacy_client()
    before = {key: dict(row) for key, row in client.tables["SemanticRelation"].items()}
    result = backfill_suggestion_index(client)
    assert (result["scanned"], result["openSuggestions"], result["keyed"], result["unscored"], result["written"]) == (5, 3, 3, 1, 3)
    for key, row in client.tables["SemanticRelation"].items():
        if row["relationState"] == "suggested":
            assert row["openSuggestionKey"] == OPEN_SUGGESTION_KEY
            assert row["openSuggestionScore"] == (row["score"] if row["score"] is not None else NO_SCORE_SORT_VALUE)
        else:
            assert row.get("openSuggestionKey") is None
        assert {name: value for name, value in row.items() if not name.startswith("openSuggestion")} == {name: value for name, value in before[key].items() if not name.startswith("openSuggestion")}
    assert [row["openSuggestionScore"] for row in client.open_suggestion_index()] == [0.8, 0.6, NO_SCORE_SORT_VALUE]


def test_a_dry_run_counts_and_writes_nothing():
    client = legacy_client()
    result = backfill_suggestion_index(client, dry_run=True)
    assert (result["keyed"], result["written"], result["dryRun"]) == (3, 0, True)
    assert client.open_suggestion_index() == []


def test_a_second_run_writes_nothing():
    client = legacy_client()
    backfill_suggestion_index(client)
    again = backfill_suggestion_index(client)
    assert (again["keyed"], again["keysCleared"], again["written"], again["alreadyRight"]) == (0, 0, 0, 5)


def test_a_decided_row_that_somehow_has_a_key_loses_it_and_a_decision_is_never_undone():
    client = legacy_client()
    rejected = next(row for row in client.tables["SemanticRelation"].values() if row["relationState"] == "rejected")
    rejected.update({"openSuggestionKey": OPEN_SUGGESTION_KEY, "openSuggestionScore": 0.9})
    result = backfill_suggestion_index(client)
    assert result["keysCleared"] == 1
    assert (rejected["relationState"], rejected["openSuggestionKey"], rejected["openSuggestionScore"]) == ("rejected", None, None)
    assert all(row["relationState"] != "suggested" or row["openSuggestionKey"] for row in client.tables["SemanticRelation"].values())


def test_a_row_with_a_wrong_sort_value_is_corrected():
    client = legacy_client()
    backfill_suggestion_index(client)
    row = next(row for row in client.tables["SemanticRelation"].values() if row["score"] == 0.8)
    row["openSuggestionScore"] = 0.1
    assert planned_fields(row) == {"openSuggestionKey": OPEN_SUGGESTION_KEY, "openSuggestionScore": 0.8}
    assert backfill_suggestion_index(client)["keyed"] == 1
