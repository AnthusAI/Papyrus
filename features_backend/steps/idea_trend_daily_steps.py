"""Cited Trends can run daily or on demand (features_backend/idea-trend-daily.feature)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from papyrus_content.ideas import trends  # noqa: E402
from papyrus_content.knowledge_snapshot.trends import TrendConfig  # noqa: E402

_spec = importlib.util.spec_from_file_location("trend_drafts_job", REPO_ROOT / "infra" / "knowledge-run" / "trend_drafts.py")
trend_drafts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trend_drafts)

ENDPOINT = "https://imnmexcbrzcddk2g4vl6hsn7ie.appsync-api.us-east-1.amazonaws.com/graphql"
URL = "https://shipped.anth.us/_data/knowledge/index.json"


def environment(context) -> dict:
    return {
        "KNOWLEDGE_PUBLICATION": "shipped", "KNOWLEDGE_EXECUTION_START": context.run_started, "KNOWLEDGE_OPENAI_KEY_PARAMETER": "/papyrus/shipped/openai-api-key",
        "TREND_DRAFTS_ENDPOINT": ENDPOINT, "TREND_DRAFTS_SNAPSHOT_URL": URL, "TREND_DRAFTS_FRESH_WAIT_SECONDS": "0", **getattr(context, "step_environment", {}),
    }


def run_step(context) -> None:
    context.step_commands, context.step_skip = [], None
    try:
        context.step_outcome = trend_drafts.run(
            environment(context), fetch=lambda url: context.published_as_of, sleep=lambda seconds: None, read_key=lambda name: "k",
            execute=lambda args, env: context.step_commands.append(args) or 0,
        )
    except trend_drafts.Skip as skip:
        context.step_skip = str(skip)


@given('the run started at "{started}"')
def step_started(context, started):
    context.run_started = started
    context.step_environment = {}


@given('the published snapshot says it is as of "{as_of}"')
def step_published(context, as_of):
    context.published_as_of = as_of


@given("the allowed snapshot age is {days:d} days")
def step_age(context, days):
    context.step_environment["TREND_DRAFTS_MAX_AGE_DAYS"] = str(days)


@when("the trend-drafts step runs")
def step_run(context):
    run_step(context)


@when("the trend window is set to {days:d} days and the trend-drafts step runs")
def step_run_with_window(context, days):
    context.step_environment["TREND_DRAFTS_WINDOW_DAYS"] = str(days)
    run_step(context)


@then('the step drafts from the snapshot as of "{as_of}"')
def step_drafted(context, as_of):
    assert context.step_skip is None, context.step_skip
    assert len(context.step_commands) == 1
    assert as_of in context.step_outcome


@then("the step is skipped as stale and files nothing")
def step_stale(context):
    assert context.step_skip and "stale" in context.step_skip, context.step_skip
    assert context.step_commands == []


@then("the command uses the default trend window")
def step_default_window(context):
    assert "--window-days" not in context.step_commands[0]


@then("the command uses a trend window of {days:d} days")
def step_window(context, days):
    assert context.step_commands[-1][-2:] == ["--window-days", str(days)]


@when("the trend window is {days:d} days")
def step_window_days(context, days):
    context.window_error = None
    try:
        context.window_config = TrendConfig(window_days=days)
    except ValueError as error:
        context.window_error = str(error)
        return
    snapshot = getattr(context, "quality_snapshot", None)
    if snapshot is not None:
        selection = trends.select_entities(snapshot, TrendConfig(window_days=days, minimum_recent=1))
        context.window_signals = {signal["targetId"]: signal for signal in trends.build_signals(snapshot, None, context.window_config, selection)}


@then("NVIDIA is counted with {recent:d} mentions against {prior:d} before")
def step_counted(context, recent, prior):
    signal = context.window_signals["maker--nvidia"]
    assert (signal["last4"], signal["prior4"]) == (recent, prior), signal


@then("the operator is told the window must be 7, 14, 21 or 28 days")
def step_refused(context):
    assert context.window_error and "7, 14, 21 or 28 days" in context.window_error, context.window_error
