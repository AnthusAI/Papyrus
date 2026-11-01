"""The adaptive trend window and the evidence-based repeat rule (features_backend/idea-trend-windows.feature, idea-trend-evidence.feature)."""

from __future__ import annotations

import json

import pytest

from papyrus_content.ideas import commands, trends
from papyrus_content.knowledge_snapshot.trends import TrendConfig, binomial_upper_tail, exceeds_report, scan_window, window_lengths

FLAT = [10.0] * 26  # a corpus whose volume does not move, so only the entity's own counts matter


def draft_row(key: str, *, filed: str, asOf: str | None = None, state: str = "draft", windows: list[dict] | None = None) -> dict:
    row = {"id": f"prop-{key}-{filed}", "kind": "story_draft", "state": state, "createdAt": f"{filed}T09:00:00Z", "targets": json.dumps([{"type": "entity", "id": key}])}
    if asOf:
        row["snapshot"] = {"asOf": asOf}
    if windows is not None:
        row["evidence"] = json.dumps({"windows": windows})
    return row


def snapshot_of(as_of: str, **series: list[int]) -> dict:
    """A snapshot of concepts (which need no notability) with a steady filler entity, so the corpus volume is flat."""
    entities = {"concept--steady": [10] * 26, **{f"concept--{name}": values for name, values in series.items()}}
    rows = [{"key": key, "kind": "concept", "name": key.split("--")[1], "series26": values, "series8": values[-8:], "itemCount": sum(values), "isNew": False} for key, values in entities.items()]
    return {"asOf": as_of, "siteBase": None, "clusters": [], "previous": None, "entityFile": lambda key: None, "index": {"entities": rows}}


def anchors(snapshot: dict, earlier: list[dict] | None = None, config: TrendConfig | None = None) -> dict[str, dict]:
    return {row["key"]: row for row in trends.select_entities(snapshot, config, earlier)["anchors"]}


# --- the scan -------------------------------------------------------------------------------------------------------------


def test_window_lengths_double_while_enough_baseline_is_left():
    assert window_lengths(26) == [1, 2, 4, 8, 16]
    assert window_lengths(8) == [1, 2, 4]
    assert window_lengths(5) == [1]
    assert window_lengths(4) == []
    assert window_lengths(26, minimum_baseline=10) == [1, 2, 4, 8, 16]
    assert window_lengths(26, minimum_baseline=12) == [1, 2, 4, 8]


def test_the_binomial_upper_tail_matches_known_values():
    assert binomial_upper_tail(0, 10, 0.3) == 1.0
    assert binomial_upper_tail(11, 10, 0.3) == 0.0
    assert binomial_upper_tail(1, 3, 0.5) == pytest.approx(0.875)
    assert binomial_upper_tail(6, 13, 0.5) == pytest.approx(0.70947265625)
    assert binomial_upper_tail(10, 10, 0.5) == pytest.approx(0.5**10)
    assert 0 < binomial_upper_tail(300, 400, 0.5) < 1e-20  # a tiny tail keeps its precision


def test_a_spike_is_found_over_a_short_window():
    window = scan_window([0] * 25 + [9], FLAT)
    assert (window["windowWeeks"], window["count"], window["baselineWeeks"], window["baselineCount"]) == (1, 9, 25, 0)
    assert window["correctedPValue"] < 1e-6 and window["surprise"] > 4


DAILY_FLAT = [10.0] * 60


def test_a_burst_in_the_last_two_days_is_significant_against_a_flat_sixty_day_baseline():
    window = scan_window([1] * 58 + [8, 8], DAILY_FLAT, bucket_days=1)
    assert (window["windowBuckets"], window["windowDays"], window["count"], window["baselineBuckets"], window["baselineCount"]) == (2, 2, 16, 58, 58)
    assert window["correctedPValue"] <= TrendConfig().significance


def test_the_same_counts_spread_evenly_over_the_days_are_not_significant():
    window = scan_window([1] * 60, DAILY_FLAT, bucket_days=1)
    assert window["correctedPValue"] > TrendConfig().significance


def test_day_buckets_leave_the_configured_weeks_of_baseline_in_days():
    assert window_lengths(60, 28) == [1, 2, 4, 8, 16, 32]
    assert scan_window([0] * 60, DAILY_FLAT, bucket_days=1)["baselineDays"] >= 28


def test_weekly_buckets_are_the_default_and_report_their_days():
    window = scan_window([0] * 25 + [9], FLAT)
    assert (window["windowBuckets"], window["windowDays"], window["bucketDays"]) == (1, 7, 7)


def test_a_bucket_shorter_than_a_day_is_refused():
    with pytest.raises(ValueError):
        scan_window([0] * 30, [10.0] * 30, bucket_days=0)


def test_an_entity_is_scanned_over_its_full_history_when_the_snapshot_has_it():
    full = [0] * 70 + [1] * 30 + [3] * 20  # 120 weeks; a window of 26 weeks cannot see the whole build
    row = {"key": "concept--slow", "series26": full[-26:], "series8": full[-8:], "seriesWeekly": full}
    assert trends.history_of(row) == full
    assert trends.history_of({**row, "seriesWeekly": None}) == full[-26:]
    assert trends.history_of({"series8": [1, 2]}) == [1, 2]
    assert window_lengths(len(full), 4) == [1, 2, 4, 8, 16, 32, 64]
    assert window_lengths(26, 4) == [1, 2, 4, 8, 16]


def test_a_slow_build_is_found_over_a_long_window():
    window = scan_window([0] * 10 + [1] * 3 + [2] * 4 + [3] * 5 + [4] * 4, FLAT)
    assert window["windowWeeks"] == 16 and window["count"] == 3 + 8 + 15 + 16
    assert window["correctedPValue"] < 1e-6


def test_the_most_surprising_window_wins_and_the_shorter_one_on_a_tie():
    assert scan_window([0] * 24 + [5, 5], FLAT)["windowWeeks"] == 2
    assert scan_window([0] * 22 + [4, 4, 4, 4], FLAT)["windowWeeks"] == 4


def test_the_p_value_is_corrected_for_the_number_of_windows_tried():
    window = scan_window([1] * 25 + [6], FLAT)
    assert window["tested"] == 5
    assert window["correctedPValue"] == pytest.approx(min(1.0, window["pValue"] * 5), rel=0.01)
    assert window["surprise"] > 2.33  # within the 0.01 the default asks for


def test_a_burst_of_noise_that_one_window_would_flag_is_not_a_trend_after_the_correction():
    window = scan_window([1] * 25 + [5], FLAT)
    assert window["pValue"] < 0.01 < window["correctedPValue"]  # uncorrected it would pass; corrected it does not
    assert anchors(snapshot_of("2026-10-26", noisy=[1] * 25 + [5])) == {}


def test_plain_noise_rarely_becomes_a_signal_across_many_series():
    import math
    import random

    generator = random.Random(7)

    def poisson(mean: float) -> int:
        limit, product, count = math.exp(-mean), generator.random(), 0
        while product > limit:
            count, product = count + 1, product * generator.random()
        return count

    flagged = sum(1 for _ in range(500) if scan_window([poisson(2.0) for _ in range(26)], FLAT)["correctedPValue"] <= 0.01)
    assert flagged <= 5  # one in a hundred at most (five of 500): the correction keeps the false-alarm rate at the level asked for


def test_a_series_too_short_for_any_window_has_none():
    assert scan_window([1, 2, 3, 4], FLAT[:4]) is None


def test_the_corpus_growth_is_not_a_trend():
    volume = [10.0] * 22 + [20.0] * 4  # the whole corpus doubled
    assert scan_window([1] * 22 + [2] * 4, volume)["correctedPValue"] > 0.01


# --- selection --------------------------------------------------------------------------------------------------------------


def test_a_spike_and_a_slow_build_each_keep_their_own_window_in_the_signals():
    snapshot = snapshot_of("2026-10-26", spike=[0] * 25 + [9], build=[0] * 10 + [1] * 3 + [2] * 4 + [3] * 5 + [4] * 4)
    chosen = anchors(snapshot)
    assert chosen["concept--spike"]["window"]["windowWeeks"] == 1
    assert chosen["concept--build"]["window"]["windowWeeks"] == 16
    signals = {signal["id"]: signal for signal in trends.build_signals(snapshot, None, None, trends.select_entities(snapshot))}
    spike, build = signals["entity:concept--spike"], signals["entity:concept--build"]
    assert (spike["windowWeeks"], spike["windowCount"], spike["baselineWeeks"], spike["baselineCount"]) == (1, 9, 25, 0)
    assert build["windowWeeks"] == 16
    assert "9 items in the last week against 0 in the 25 weeks before" in trends.describe_signal(spike)
    assert "in the last 16 weeks" in trends.describe_signal(build)
    view = trends.signal_view("S1", build, build["asOf"])
    assert (view["window_weeks"], view["items_in_window"]) == (16, build["windowCount"]) and len(view["items_per_week"]) == 26


def test_an_old_snapshot_with_only_eight_weeks_is_still_scanned():
    rows = snapshot_of("2026-10-26", spike=[0] * 25 + [9])
    for row in rows["index"]["entities"]:
        del row["series26"]
    assert "concept--spike" in anchors(rows)
    assert anchors(rows)["concept--spike"]["window"]["baselineWeeks"] == 7


# --- the repeat rule: evidence, not days -------------------------------------------------------------------------------------


def test_a_draft_is_reconstructed_from_the_data_as_of_the_week_it_was_made():
    history = [0] * 24 + [6, 0]  # the spike was in the week of 2026-10-19; a week later it has faded
    volume = [sum(column) for column in zip(*[history, [10] * 26])]
    config = TrendConfig()
    report = trends.previous_report("concept--x", [draft_row("concept--x", filed="2026-10-20", asOf="2026-10-19")], history, [float(v) for v in volume], "2026-10-26", config)
    assert (report["windowWeeks"], report["count"], report["filed"], report["state"]) == (1, 6, "2026-10-20", "draft")


def test_a_stored_draft_reports_the_window_it_recorded_and_a_broad_kind_reports_nothing():
    windows = [{"signal": "entity:concept--x", "windowWeeks": 4, "count": 12}]
    row = draft_row("concept--x", filed="2026-10-20", windows=windows)
    assert trends.previous_report("concept--x", [row], [0] * 26, FLAT, "2026-10-26", TrendConfig())["count"] == 12
    assert trends.previous_report("licence--mit", [draft_row("licence--mit", filed="2026-10-20")], [0] * 26, FLAT, "2026-10-26", TrendConfig()) is None


def test_the_strongest_earlier_report_is_the_one_new_evidence_must_beat():
    rows = [
        draft_row("concept--x", filed="2026-09-01", windows=[{"signal": "entity:concept--x", "windowWeeks": 1, "count": 3}]),
        draft_row("concept--x", filed="2026-10-01", windows=[{"signal": "entity:concept--x", "windowWeeks": 1, "count": 9}], state="declined"),
    ]
    assert trends.previous_report("concept--x", rows, [0] * 26, FLAT, "2026-10-26", TrendConfig())["count"] == 9


def test_new_evidence_means_significantly_more_than_the_draft_reported():
    config = TrendConfig()
    report = {"windowWeeks": 1, "count": 6}
    scan = lambda count, weeks: {"count": count, "windowWeeks": weeks, "tested": 5}  # noqa: E731
    assert exceeds_report(scan(7, 1), report, config)[0] is False  # about the same
    assert exceeds_report(scan(14, 2), report, config)[0] is False  # the same rate for longer is not new
    assert exceeds_report(scan(12, 1), report, config)[0] is False  # twice as many is still within chance at this size
    assert exceeds_report(scan(30, 1), report, config)[0] is True
    more, p_value = exceeds_report(scan(30, 2), report, config)
    assert more is False or p_value <= config.significance


def test_an_anchor_with_a_draft_is_not_drafted_again_while_its_evidence_has_not_grown():
    first = snapshot_of("2026-10-19", surge=[0] * 25 + [6])
    assert "concept--surge" in anchors(first)
    earlier = [draft_row("concept--surge", filed="2026-10-20", asOf="2026-10-19")]
    selection = trends.select_entities(first, None, earlier)
    assert not selection["anchors"]
    [reason] = [row["reason"] for row in selection["excluded"] if row["key"] == "concept--surge"]
    assert reason.startswith("no new evidence: the draft filed 2026-10-20 (draft) reported 6 in 1 week(s); now 6 in 1")
    [prior] = selection["priorDrafts"]
    assert prior["renewed"] is False and prior["reported"] == {"windowWeeks": 1, "count": 6}
    # days passing change nothing: the same evidence, a week later, with the surge continuing at the same level
    later = snapshot_of("2026-10-26", surge=[0] * 24 + [6, 7])  # the surge goes on at the same level
    assert "concept--surge" not in anchors(later, earlier)


def test_a_declined_draft_is_not_proposed_again_without_new_evidence_and_is_with_it():
    earlier = [draft_row("concept--surge", filed="2026-10-20", asOf="2026-10-19", state="declined")]
    same = snapshot_of("2026-10-19", surge=[0] * 25 + [6])
    assert "concept--surge" not in anchors(same, earlier)
    much_more = snapshot_of("2026-10-26", surge=[0] * 24 + [6, 40])
    chosen = anchors(much_more, earlier)
    assert "concept--surge" in chosen
    assert chosen["concept--surge"]["renewal"]["renewed"] is True and chosen["concept--surge"]["renewal"]["state"] == "declined"


def test_an_anchor_with_no_earlier_draft_is_unaffected_and_so_are_other_entities():
    snapshot = snapshot_of("2026-10-26", surge=[0] * 24 + [6, 9], other=[0] * 25 + [8])
    earlier = [draft_row("concept--surge", filed="2026-10-20", asOf="2026-10-19")]
    assert "concept--other" in anchors(snapshot, earlier)  # it has no draft
    assert "concept--surge" not in anchors(snapshot, earlier)  # 9 against the 6 that its draft reported is not materially more


def test_a_draft_older_than_the_history_counts_for_nothing():
    old = draft_row("concept--surge", filed="2025-01-06", asOf="2025-01-06")
    assert "concept--surge" in anchors(snapshot_of("2026-10-26", surge=[0] * 25 + [9]), [old])


def test_a_renewed_anchor_is_not_dropped_as_the_same_targets():
    drafts = [{"title": "t", "ideaId": "idea-1", "targets": [{"type": "entity", "id": "concept--surge"}]}]
    existing = [("proposal", "prop-1", frozenset({("entity", "concept--surge")}))]
    assert trends.split_same_targets(drafts, existing)[0] == []
    assert trends.split_same_targets(drafts, existing, frozenset({"concept--surge"}))[0] == drafts


def test_a_draft_record_keeps_the_window_each_cited_entity_reported():
    snapshot = snapshot_of("2026-10-26", spike=[0] * 25 + [9])
    selection = trends.select_entities(snapshot)
    signals = {signal["id"]: signal for signal in trends.build_signals(snapshot, None, None, selection)}
    entity = signals["entity:concept--spike"]
    assert entity["window"]["windowWeeks"] == 1
    figure_draft = {
        "headline": {"text": "h", "signalIds": [entity["id"]], "itemIds": []}, "dek": {"text": "d", "signalIds": [entity["id"]], "itemIds": []}, "section": "Analysis",
        "paragraphs": [[]], "citedSignalIds": [entity["id"]], "citedItemIds": [], "figureSignalIds": [entity["id"]], "figureTitle": "t", "figureCaption": "c",
        "citationCheck": {"status": "passed", "sentences": 0},
    }
    from datetime import datetime, timezone

    record = trends.draft_record(figure_draft, run={"runId": "r", "publication": "p"}, signals=signals, snapshot={"source": "s", "asOf": "2026-10-26"}, now=datetime(2026, 10, 26, tzinfo=timezone.utc))
    [kept] = record["evidence"]["windows"]
    assert (kept["signal"], kept["windowWeeks"], kept["count"], kept["baselineWeeks"]) == ("entity:concept--spike", 1, 9, 25)
    # and the next run reads it back as what the draft reported
    assert trends.previous_report("concept--spike", [record], [0] * 26, FLAT, "2026-10-26", TrendConfig())["count"] == 9


# --- configuration -------------------------------------------------------------------------------------------------------------


def test_the_fixed_spans_are_gone_from_the_configuration():
    for retired in ("window_days", "cooldown_days"):
        with pytest.raises(ValueError, match="Unknown trend config"):
            TrendConfig.from_mapping({retired: 7})
    assert TrendConfig().significance == 0.01 and TrendConfig().minimum_baseline_weeks == 4
    assert TrendConfig.from_mapping({"significance": 0.001, "minimum_baseline_weeks": 6}).minimum_baseline_weeks == 6
    for bad in ({"significance": 0}, {"significance": 1}, {"minimum_baseline_weeks": 0}):
        with pytest.raises(ValueError):
            TrendConfig.from_mapping(bad)


@pytest.mark.parametrize("flag", ["window-days", "cooldown-days"])
def test_the_retired_command_flags_are_refused_with_the_reason(flag):
    with pytest.raises(ValueError, match="retired"):
        commands._trend_config({flag: "7"})
    assert commands._trend_config({}) == TrendConfig()
