"""The trend window in days (default 28 against the 28 before): a shorter window for a daily cadence (features_backend/idea-trend-daily.feature)."""

from __future__ import annotations

import pytest

from ideas_fixtures import selection_snapshot
from papyrus_content.ideas import commands, trends
from papyrus_content.knowledge_snapshot.trends import DEFAULT_WINDOW_DAYS, TrendConfig, trend_score


def test_the_default_window_is_28_days_against_the_28_before_and_changes_nothing():
    assert DEFAULT_WINDOW_DAYS == 28 and TrendConfig().window_days == 28 and TrendConfig().window_weeks == 4
    snapshot = selection_snapshot()
    assert trends.select_entities(snapshot) == trends.select_entities(snapshot, TrendConfig(window_days=28))
    assert trends.build_signals(snapshot) == trends.build_signals(snapshot, None, TrendConfig(window_days=28))
    assert trends.select_entities(snapshot)["thresholds"]["windowDays"] == 28


def test_a_shorter_window_scores_the_last_weeks_against_the_same_number_before_them():
    series, volume = [0, 0, 1, 0, 0, 1, 1, 4], [10.0] * 8
    four = trend_score("maker", series, volume, TrendConfig())
    one = trend_score("maker", series, volume, TrendConfig(window_days=7))
    two = trend_score("maker", series, volume, TrendConfig(window_days=14))
    assert (four["last4"], four["prior4"]) == (6.0, 1.0)
    assert (two["last4"], two["prior4"]) == (5.0, 1.0)
    assert (one["last4"], one["prior4"]) == (4.0, 1.0)


def test_signals_of_a_shorter_window_carry_its_counts_and_the_model_sees_which_window():
    snapshot = selection_snapshot()
    config = TrendConfig(window_days=14, minimum_recent=1)
    selection = trends.select_entities(snapshot, config)
    signals = trends.build_signals(snapshot, None, config, selection)
    entities = [signal for signal in signals if signal["kind"] == "entity"]
    assert entities and all(signal["windowWeeks"] == 2 for signal in entities)
    nvidia = next(signal for signal in entities if signal["targetId"] == "maker--nvidia")
    assert (nvidia["last4"], nvidia["prior4"]) == (5, 1)  # the last two weeks of [0, 0, 1, 0, 0, 1, 1, 4] against the two before
    view = trends.signal_view("S1", nvidia, nvidia["asOf"])
    assert view["items_last_2_weeks"] == 5 and view["items_prior_2_weeks"] == 1 and "items_last_4_weeks" not in view
    assert "5 items in the last two weeks against 1 before" in trends.describe_signal(nvidia)


def test_the_default_window_keeps_the_published_four_week_names():
    snapshot = selection_snapshot()
    signal = next(signal for signal in trends.build_signals(snapshot) if signal["kind"] == "entity")
    view = trends.signal_view("S1", signal, signal["asOf"])
    assert "items_last_4_weeks" in view and "windowWeeks" not in signal


def test_a_shorter_window_narrows_the_items_behind_a_signal():
    related = [
        {"title": "Old", "url": "/old/", "publishedAt": "2026-10-06T00:00:00Z"},
        {"title": "New", "url": "/new/", "publishedAt": "2026-10-21T00:00:00Z"},
    ]
    assert [item["title"] for item in trends.window_items(related, "2026-10-26", None)] == ["New", "Old"]
    assert [item["title"] for item in trends.window_items(related, "2026-10-26", None, 1)] == []
    assert [item["title"] for item in trends.window_items(related, "2026-10-26", None, 2)] == ["New"]


@pytest.mark.parametrize("days", [0, 1, 6, 10, 29, 35, 56, -7])
def test_a_window_that_is_not_whole_weeks_up_to_four_is_refused(days):
    with pytest.raises(ValueError, match="7, 14, 21 or 28 days"):
        TrendConfig(window_days=days)


def test_the_command_reads_window_days_and_it_wins_over_the_config_file(tmp_path):
    assert commands._trend_config({}).window_days == 28
    assert commands._trend_config({"window-days": "14"}).window_days == 14
    file = tmp_path / "trend.json"
    file.write_text('{"window_days": 21, "minimum_likes": 50}')
    config = commands._trend_config({"trend-config": str(file)})
    assert (config.window_days, config.minimum_likes) == (21, 50)
    assert commands._trend_config({"trend-config": str(file), "window-days": "7"}).window_days == 7
    with pytest.raises(ValueError):
        commands._trend_config({"window-days": "10"})
