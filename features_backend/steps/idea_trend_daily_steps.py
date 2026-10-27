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

from papyrus_content.ideas import commands  # noqa: E402

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


@then('the step drafts from the snapshot as of "{as_of}"')
def step_drafted(context, as_of):
    assert context.step_skip is None, context.step_skip
    assert len(context.step_commands) == 1
    assert as_of in context.step_outcome


@then("the step is skipped as stale and files nothing")
def step_stale(context):
    assert context.step_skip and "stale" in context.step_skip, context.step_skip
    assert context.step_commands == []


@given("the old trend window and cooldown are still set in the environment")
def step_old_settings(context):
    context.step_environment.update(TREND_DRAFTS_WINDOW_DAYS="14", TREND_DRAFTS_COOLDOWN_DAYS="0")


@then("the command carries no trend window and no cooldown")
def step_no_window(context):
    assert not [flag for flag in context.step_commands[0] if flag in {"--window-days", "--cooldown-days"}], context.step_commands[0]


@when('the operator passes the retired option "{flag}"')
def step_retired(context, flag):
    context.retired_error = None
    try:
        commands._trend_config({flag.lstrip("-"): "14"})
    except ValueError as error:
        context.retired_error = str(error)


@then("the operator is told the window is chosen from the data")
def step_retired_told(context):
    assert context.retired_error and "retired" in context.retired_error and "chosen from the data" in context.retired_error, context.retired_error
