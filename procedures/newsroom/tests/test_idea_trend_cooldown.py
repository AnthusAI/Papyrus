"""The anchor cooldown: an entity that anchored a story draft (not declined) in the last N days (default 7) cannot anchor another
(features_backend/idea-trend-cooldown.feature)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ideas_fixtures import NOW, selection_snapshot
from papyrus_content.ideas import commands, trends
from papyrus_content.knowledge_snapshot.trends import TrendConfig


def draft(targets, *, days_ago: float, state: str = "draft", as_text: bool = True) -> dict:
    filed = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    cited = [{"type": kind, "id": key} for kind, key in targets]
    return {"id": f"prop-{days_ago}", "kind": "story_draft", "title": "t", "summary": "s", "state": state, "createdAt": filed, "targets": json.dumps(cited) if as_text else cited}


def test_the_default_cooldown_is_seven_days_and_zero_turns_it_off():
    assert TrendConfig().cooldown_days == 7
    assert trends.cooldown_anchors([draft([("entity", "maker--nvidia")], days_ago=1)], NOW, TrendConfig(cooldown_days=0)) == {}


def test_an_entity_cited_by_a_recent_draft_cools_down_until_the_cooldown_has_passed():
    config = TrendConfig()
    recent = draft([("entity", "maker--nvidia"), ("cluster", "cl-1")], days_ago=2)
    assert trends.cooldown_anchors([recent], NOW, config) == {"maker--nvidia": (NOW - timedelta(days=2)).date().isoformat()}
    assert trends.cooldown_anchors([draft([("entity", "maker--nvidia")], days_ago=6.9)], NOW, config) != {}
    assert trends.cooldown_anchors([draft([("entity", "maker--nvidia")], days_ago=7.1)], NOW, config) == {}
    assert trends.cooldown_anchors([draft([("entity", "maker--nvidia")], days_ago=7.1)], NOW, TrendConfig(cooldown_days=14)) != {}


def test_a_declined_draft_does_not_cool_anything_down_and_clusters_never_do():
    rows = [draft([("entity", "maker--nvidia")], days_ago=1, state="declined"), draft([("cluster", "cl-1")], days_ago=1)]
    assert trends.cooldown_anchors(rows, NOW, TrendConfig()) == {}


def test_broad_kinds_cited_as_context_never_cool_down_because_they_never_anchor():
    rows = [draft([("entity", "maker--nvidia"), ("entity", "licence--mit"), ("entity", "task--text-generation"), ("entity", "platform--hugging-face")], days_ago=1)]
    assert set(trends.cooldown_anchors(rows, NOW, TrendConfig())) == {"maker--nvidia"}


def test_the_newest_filing_date_is_kept_and_targets_may_be_text_or_a_list():
    rows = [draft([("entity", "maker--nvidia")], days_ago=5), draft([("entity", "maker--nvidia")], days_ago=2, as_text=False)]
    assert trends.cooldown_anchors(rows, NOW, TrendConfig()) == {"maker--nvidia": (NOW - timedelta(days=2)).date().isoformat()}


def test_a_row_without_a_readable_date_is_ignored():
    row = {**draft([("entity", "maker--nvidia")], days_ago=1), "createdAt": "yesterday"}
    assert trends.cooldown_anchors([row], NOW, TrendConfig()) == {}


def test_a_cooled_entity_is_passed_over_with_the_date_and_the_rest_still_anchor():
    snapshot = selection_snapshot()
    before = trends.select_entities(snapshot)
    assert "maker--nvidia" in {row["key"] for row in before["anchors"]}
    after = trends.select_entities(snapshot, TrendConfig(), {"maker--nvidia": "2026-10-20"})
    assert "maker--nvidia" not in {row["key"] for row in after["anchors"]}
    reason = next(row["reason"] for row in after["excluded"] if row["key"] == "maker--nvidia")
    assert reason == "cooldown: anchored a story draft filed 2026-10-20"
    assert {row["key"] for row in before["anchors"]} - {"maker--nvidia"} == {row["key"] for row in after["anchors"]}
    assert after["thresholds"]["cooldownDays"] == 7


def test_selection_without_a_cooldown_is_what_it_was():
    snapshot = selection_snapshot()
    assert trends.select_entities(snapshot, TrendConfig(), {}) == trends.select_entities(snapshot)


@pytest.mark.parametrize("days", [-1, 366])
def test_a_cooldown_outside_zero_to_365_days_is_refused(days):
    with pytest.raises(ValueError, match="0 to 365"):
        TrendConfig(cooldown_days=days)


def test_the_command_reads_cooldown_days_and_it_wins_over_the_config_file(tmp_path):
    assert commands._trend_config({}).cooldown_days == 7
    assert commands._trend_config({"cooldown-days": "0"}).cooldown_days == 0
    file = tmp_path / "trend.json"
    file.write_text('{"cooldown_days": 3}')
    assert commands._trend_config({"trend-config": str(file)}).cooldown_days == 3
    assert commands._trend_config({"trend-config": str(file), "cooldown-days": "14"}).cooldown_days == 14
    with pytest.raises(ValueError, match="whole number of days"):
        commands._trend_config({"cooldown-days": "soon"})
