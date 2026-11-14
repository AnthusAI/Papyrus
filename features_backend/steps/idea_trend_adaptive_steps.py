"""The adaptive trend window and the evidence-based repeat rule (features_backend/idea-trend-windows.feature, idea-trend-evidence.feature)."""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from papyrus_content.ideas import trends  # noqa: E402
from papyrus_content.knowledge_snapshot.trends import TrendConfig, scan_window  # noqa: E402

FLAT = [10.0] * 26


def snapshot_of(as_of: str, **series: list[int]) -> dict:
    """Concepts (which need no notability) beside a steady filler entity, so the corpus volume is flat."""
    longest = max([26, *(len(values) for values in series.values())])
    entities = {"concept--steady": [10] * longest, **{f"concept--{name}": values for name, values in series.items()}}
    rows = [{"key": key, "kind": "concept", "name": key.split("--")[1], "series26": values[-26:], "seriesWeekly": values if len(values) > 26 else None, "series8": values[-8:], "itemCount": sum(values), "isNew": False} for key, values in entities.items()]
    return {"asOf": as_of, "siteBase": None, "clusters": [], "previous": None, "entityFile": lambda key: None, "index": {"entities": rows}}


def draft_row(key: str, filed: str, state: str, as_of: str | None = None) -> dict:
    row = {"id": f"prop-{key}", "kind": "story_draft", "state": state, "createdAt": f"{filed}T09:00:00Z", "targets": json.dumps([{"type": "entity", "id": key}])}
    return {**row, "snapshot": {"asOf": as_of}} if as_of else row


def trend_of(context) -> dict | None:
    return {row["key"]: row for row in trends.select_entities(context.adaptive_snapshot)["anchors"]}.get("concept--subject")


# --- windows -----------------------------------------------------------------------------------------------------------------


@given("a quiet concept that is mentioned {count:d} times in the latest week")
def step_spike(context, count):
    context.adaptive_series = [0] * 25 + [count]


@given("a concept that was quiet and then grew a little every week for 16 weeks")
def step_build(context):
    context.adaptive_series = [0] * 10 + [1] * 3 + [2] * 4 + [3] * 5 + [4] * 4


@given("a concept that is mentioned once a week and {count:d} times in the latest week")
def step_noise(context, count):
    context.adaptive_series = [1] * 25 + [count]


@given("a concept that keeps its share while the corpus doubles")
def step_share(context):
    context.adaptive_series = [1] * 22 + [2] * 4
    context.adaptive_volume = [10.0] * 22 + [20.0] * 4


@given("a concept that was quiet for 70 weeks, then grew steadily for 50 weeks")
def step_long_build(context):
    context.adaptive_series = [0] * 70 + [1] * 10 + [2] * 10 + [3] * 10 + [4] * 10 + [5] * 10
    context.adaptive_volume = [10.0] * 120


@given("the snapshot publishes only eight weeks")
def step_eight(context):
    context.adaptive_eight = True


@given("{count:d} concepts that are only noise around 2 mentions a week")
def step_many(context, count):
    generator = random.Random(7)

    def poisson(mean: float) -> int:
        limit, product, drawn = math.exp(-mean), generator.random(), 0
        while product > limit:
            drawn, product = drawn + 1, product * generator.random()
        return drawn

    context.adaptive_many = [[poisson(2.0) for _ in range(26)] for _ in range(count)]


@when("the trend windows are scanned over the last 26 weeks only")
def step_scan_26(context):
    series = context.adaptive_series[-26:]
    context.adaptive_snapshot = snapshot_of("2026-10-26", subject=series)
    context.adaptive_window = scan_window(series, [10.0] * 26)


@when("the trend windows are scanned")
def step_scan(context):
    series = context.adaptive_series
    context.adaptive_snapshot = snapshot_of("2026-10-26", subject=series)
    if getattr(context, "adaptive_eight", False):
        for row in context.adaptive_snapshot["index"]["entities"]:
            del row["series26"]
    volume = getattr(context, "adaptive_volume", FLAT)
    context.adaptive_window = scan_window(series, volume)


@when("the trend windows are scanned for each")
def step_scan_each(context):
    context.adaptive_trends = sum(1 for series in context.adaptive_many if scan_window(series, FLAT)["correctedPValue"] <= TrendConfig().significance)


@when("a draft that cites the concept is recorded")
def step_record(context):
    selection = trends.select_entities(context.adaptive_snapshot)
    signals = {signal["id"]: signal for signal in trends.build_signals(context.adaptive_snapshot, None, None, selection)}
    entity = signals["entity:concept--subject"]
    cited = [entity["id"]]
    draft = {
        "headline": {"text": "h", "signalIds": cited, "itemIds": []}, "dek": {"text": "d", "signalIds": cited, "itemIds": []}, "section": "Analysis", "paragraphs": [[]],
        "citedSignalIds": cited, "citedItemIds": [], "figureSignalIds": cited, "figureTitle": "t", "figureCaption": "c", "citationCheck": {"status": "passed", "sentences": 0},
    }
    context.adaptive_record = trends.draft_record(
        draft, run={"runId": "r", "publication": "p"}, signals=signals, snapshot={"source": "s", "asOf": "2026-10-26"}, now=datetime(2026, 10, 26, tzinfo=timezone.utc))


@then("the concept is a trend over a window of {weeks:d} week")
@then("the concept is a trend over a window of {weeks:d} weeks")
def step_trend(context, weeks):
    anchor = trend_of(context)
    assert anchor and anchor["window"]["windowWeeks"] == weeks, anchor


@then("the window is longer than 26 weeks")
def step_longer_than_26(context):
    anchor = trend_of(context)
    assert anchor and anchor["window"]["windowWeeks"] > 26, anchor


@then("the longest window it can try is 16 weeks, and the full history is more surprising")
def step_at_most_16(context):
    full = scan_window(context.adaptive_series, [10.0] * 120)
    assert context.adaptive_window["windowWeeks"] <= 16, context.adaptive_window
    assert full["surprise"] > context.adaptive_window["surprise"], (full, context.adaptive_window)


@then("the concept is not a trend")
def step_not_trend(context):
    assert trend_of(context) is None, trend_of(context)


@then("the signal says {count:d} items in the last week against {baseline:d} in the {weeks:d} weeks before")
def step_signal_says(context, count, baseline, weeks):
    selection = trends.select_entities(context.adaptive_snapshot)
    signal = next(s for s in trends.build_signals(context.adaptive_snapshot, None, None, selection) if s["id"] == "entity:concept--subject")
    assert f"{count} items in the last week against {baseline} in the {weeks} weeks before" in trends.describe_signal(signal), trends.describe_signal(signal)


@then("the model is shown the concept with a window of {weeks:d} weeks and its full weekly history")
def step_model_view(context, weeks):
    selection = trends.select_entities(context.adaptive_snapshot)
    signal = next(s for s in trends.build_signals(context.adaptive_snapshot, None, None, selection) if s["id"] == "entity:concept--subject")
    view = trends.signal_view("S1", signal, signal["asOf"])
    assert view["window_weeks"] == weeks and len(view["items_per_week"]) == 26, view


@then("that window alone would pass at 0.01 but the corrected p-value does not")
def step_corrected(context):
    window = context.adaptive_window
    assert window["pValue"] < 0.01 < window["correctedPValue"], window


@then("at most {limit:d} of them are trends")
def step_at_most(context, limit):
    assert context.adaptive_trends <= limit, context.adaptive_trends


@then("the draft's evidence holds a window of {weeks:d} week with {count:d} items against {baseline:d} in the {baseline_weeks:d} weeks before")
def step_evidence(context, weeks, count, baseline, baseline_weeks):
    [window] = context.adaptive_record["evidence"]["windows"]
    assert (window["windowWeeks"], window["count"], window["baselineCount"], window["baselineWeeks"]) == (weeks, count, baseline, baseline_weeks), window


@then("the baseline is the {weeks:d} weeks before the window")
def step_baseline(context, weeks):
    assert trend_of(context)["window"]["baselineWeeks"] == weeks


# --- evidence ----------------------------------------------------------------------------------------------------------------


@given('a concept surged to {count:d} mentions in the week of "{week}"')
def step_surged(context, count, week):
    context.surge_first = count
    context.surge_rows = []


@given("a story draft on the concept was filed on {filed}")
def step_filed(context, filed):
    context.surge_rows.append(draft_row("concept--subject", filed, "draft", "2026-10-19"))


@given("a declined story draft on the concept was filed on {filed}")
def step_filed_declined(context, filed):
    context.surge_rows.append(draft_row("concept--subject", filed, "declined", "2026-10-19"))


@given("a story draft on another concept was filed on {filed}")
def step_filed_other(context, filed):
    context.surge_rows.append(draft_row("concept--other", filed, "draft", "2026-10-19"))


@given("a story draft on the concept that recorded a window of {weeks:d} weeks with {count:d} items")
def step_recorded(context, weeks, count):
    row = draft_row("concept--subject", "2026-10-20", "draft")
    row["evidence"] = json.dumps({"windows": [{"signal": "entity:concept--subject", "windowWeeks": weeks, "count": count}]})
    context.surge_rows = [row]


@when('the surge continues at {count:d} mentions in the week of "{week}"')
@when('the surge grows to {count:d} mentions in the week of "{week}"')
def step_second_week(context, count, week):
    context.surge_series = [0] * 24 + [context.surge_first, count]


@when('the trends are selected for the week of "{week}"')
def step_select(context, week):
    series = getattr(context, "surge_series", None) or [0] * 25 + [context.surge_first]
    context.adaptive_snapshot = snapshot_of(week, subject=series)
    context.surge_selection = trends.select_entities(context.adaptive_snapshot, None, context.surge_rows)


@when("the earlier draft's report is read")
def step_report(context):
    context.surge_report = trends.previous_report("concept--subject", context.surge_rows, [0] * 26, FLAT, "2026-10-26", TrendConfig())


@then("the concept is not an anchor and the run says there is no new evidence")
def step_no_new(context):
    selection = context.surge_selection
    assert "concept--subject" not in {row["key"] for row in selection["anchors"]}, selection["anchors"]
    assert any(row["key"] == "concept--subject" and row["reason"].startswith("no new evidence") for row in selection["excluded"]), selection["excluded"]


@then("the concept is an anchor again")
@then("the concept is an anchor")
def step_anchor(context):
    assert "concept--subject" in {row["key"] for row in context.surge_selection["anchors"]}, context.surge_selection


@then("the run record shows the draft reported {count:d} in {weeks:d} week")
def step_reported(context, count, weeks):
    [prior] = context.surge_selection["priorDrafts"]
    assert prior["reported"] == {"windowWeeks": weeks, "count": count} and prior["renewed"] is False, prior


@then("the run record shows the new evidence renewed the earlier draft")
def step_renewed(context):
    [prior] = context.surge_selection["priorDrafts"]
    assert prior["renewed"] is True and prior["pValue"] <= TrendConfig().significance, prior


@then("it reports {count:d} items in {weeks:d} weeks")
def step_reports(context, count, weeks):
    assert (context.surge_report["count"], context.surge_report["windowWeeks"]) == (count, weeks), context.surge_report


@then("the retired seven-day cooldown is not in the run record")
def step_no_cooldown(context):
    assert "cooldown" not in context.surge_selection and "cooldownDays" not in context.surge_selection["thresholds"]


# --- day buckets -------------------------------------------------------------------------------------------------------------


@given("a daily series that is mentioned once a day for {days:d} days and {burst:d} times on each of the last {burst_days:d} days")
def step_daily_burst(context, days, burst, burst_days):
    context.daily_series = [1] * days + [burst] * burst_days


@given("a daily series that is mentioned once a day for {days:d} days")
def step_daily_even(context, days):
    context.daily_series = [1] * days


@when("the trend windows are scanned in day buckets")
def step_scan_days(context):
    context.daily_window = scan_window(context.daily_series, [10.0] * len(context.daily_series), bucket_days=1)


@then("the window is {days:d} days, which is {buckets:d} buckets")
def step_daily_window(context, days, buckets):
    assert (context.daily_window["windowDays"], context.daily_window["windowBuckets"]) == (days, buckets), context.daily_window


@then("the corrected p-value is within 0.01")
def step_daily_significant(context):
    assert context.daily_window["correctedPValue"] <= TrendConfig().significance, context.daily_window


@then("the corrected p-value is not within 0.01")
def step_daily_not_significant(context):
    assert context.daily_window["correctedPValue"] > TrendConfig().significance, context.daily_window


@then("the window is {buckets:d} bucket of {days:d} days")
def step_weekly_default(context, buckets, days):
    window = scan_window(context.adaptive_series, [10.0] * len(context.adaptive_series))
    assert (window["windowBuckets"], window["windowDays"]) == (buckets, days), window
