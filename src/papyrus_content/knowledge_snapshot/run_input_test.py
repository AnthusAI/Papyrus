from __future__ import annotations

import json
from datetime import date

import pytest

from .run_input import load_run

WEEKS = [f"2026-W{week}" for week in range(36, 44)]


def identity(**overrides) -> dict:
    body = {
        "run_id": "run-1",
        "generated_at": "2026-10-19T06:00:00Z",
        "trends_snapshot_id": "snap-1",
        "series_iso_weeks": WEEKS,
        "clusters": [
            {"uid": "u1", "topic_id": 3, "event": "new", "label": "3_voice", "top_terms": [], "member_item_count": 2, "member_item_ids": ["a", "b"],
             "first_seen": "2026-10-19", "earliest_published_at": "2026-10-06T00:00:00Z", "weekly_series": [0, 0, 0, 0, 0, 0, 1, 1]}
        ],
    }
    body.update(overrides)
    return body


def trends(**overrides) -> dict:
    body = {
        "snapshot_id": "snap-1",
        "weekly_bins": {
            "as_of": "2026-10-19",
            "iso_weeks": [f"2026-W{week:02d}" for week in range(18, 44)],
            "discovered_topics": [{"topic_id": 3, "topic_uid": None, "label": "voice", "counts": list(range(26))}],
            "canonical_topics": [],
        },
    }
    body.update(overrides)
    return body


def write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_trend_series_of_the_cluster_topic_wins_and_the_run_date_is_the_trends_as_of(tmp_path):
    run = load_run(write(tmp_path, "i.json", identity()), write(tmp_path, "t.json", trends()), None)
    cluster = run.clusters[0]
    assert len(cluster.weekly_series) == 26 and cluster.weekly_series["2026-W43"] == 25
    assert (run.run_id, run.as_of, cluster.earliest_published_at, cluster.member_count, cluster.top_terms) == ("run-1", date(2026, 10, 19), "2026-10-06T00:00:00Z", 2, ["3_voice"])
    assert run.warnings == []


def test_without_a_trends_file_the_eight_weeks_of_the_identity_file_are_used(tmp_path):
    run = load_run(write(tmp_path, "i.json", identity()), None, None)
    assert list(run.clusters[0].weekly_series.values()) == [0, 0, 0, 0, 0, 0, 1, 1] and run.as_of == date(2026, 10, 19)


def test_a_trends_snapshot_other_than_the_one_the_identity_run_used_is_not_trusted(tmp_path):
    run = load_run(write(tmp_path, "i.json", identity()), write(tmp_path, "t.json", trends(snapshot_id="snap-2")), None)
    assert len(run.clusters[0].weekly_series) == 8 and "snap-2" in run.warnings[0]


def test_a_trends_file_without_weekly_bins_warns_and_falls_back(tmp_path):
    run = load_run(write(tmp_path, "i.json", identity()), write(tmp_path, "t.json", {"snapshot_id": "snap-1", "weekly_bins": None}), None)
    assert len(run.clusters[0].weekly_series) == 8 and "no weekly_bins" in run.warnings[0]


def test_a_cluster_matches_its_series_by_topic_uid_before_topic_id(tmp_path):
    body = trends()
    body["weekly_bins"]["canonical_topics"] = [{"topic_id": None, "topic_uid": "u1", "label": "x", "counts": [9] * 26}]
    run = load_run(write(tmp_path, "i.json", identity()), write(tmp_path, "t.json", body), None)
    assert set(run.clusters[0].weekly_series.values()) == {9}


def test_trends_alone_are_refused_and_so_is_a_file_that_is_not_biblicus_output(tmp_path):
    with pytest.raises(ValueError, match="--trends needs --identity"):
        load_run(None, write(tmp_path, "t.json", trends()), None)
    with pytest.raises(ValueError, match="not the expected Biblicus output"):
        load_run(write(tmp_path, "i.json", {"clusters": "no"}), None, None)
    with pytest.raises(ValueError, match="Cannot read"):
        load_run(tmp_path / "missing.json", None, None)
    assert load_run(None, None, None) is None


def test_typed_entities_alone_get_a_run_id_from_the_file_and_relation_endpoints_may_be_objects(tmp_path):
    body = {"schema_version": 1, "backend": {"id": "hybrid"}, "items": [{"item_id": "a", "entities": [{"id": "e1", "kind": "model", "text": "Tern"}], "relations": [{"type": "made_by", "subject": {"id": "e1"}, "object": "e2"}]}]}
    first = load_run(None, None, write(tmp_path, "e.json", body))
    again = load_run(None, None, write(tmp_path, "e.json", body))
    assert first.run_id == again.run_id and first.run_id.startswith("typed-entities-") and first.clusters == []
    assert first.entities[0].relations[0].subject == "e1" and first.entities[0].entities[0].state == "proposed" and first.backend.id == "hybrid"
