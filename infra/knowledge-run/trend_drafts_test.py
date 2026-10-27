"""Tests for the trend-drafts job step (infra/knowledge-run/trend_drafts.py)."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("trend_drafts", Path(__file__).with_name("trend_drafts.py"))
trend_drafts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trend_drafts)

ENDPOINT = "https://imnmexcbrzcddk2g4vl6hsn7ie.appsync-api.us-east-1.amazonaws.com/graphql"
URL = "https://shipped.anth.us/_data/knowledge/index.json"
BASE = {
    "KNOWLEDGE_PUBLICATION": "shipped",
    "KNOWLEDGE_EXECUTION_START": "2026-10-26T05:00:12.345Z",  # a Monday
    "KNOWLEDGE_OPENAI_KEY_PARAMETER": "/papyrus/shipped/openai-api-key",
    "TREND_DRAFTS_ENDPOINT": ENDPOINT,
    "TREND_DRAFTS_SNAPSHOT_URL": URL,
    "TREND_DRAFTS_FRESH_WAIT_SECONDS": "0",
}


def test_run_week_is_the_monday_on_or_before_the_start():
    assert trend_drafts.monday_of_start("2026-10-28T10:00:00Z") == dt.date(2026, 10, 26)
    assert trend_drafts.monday_of_start("2026-10-26T05:00:00+00:00") == dt.date(2026, 10, 26)


def test_the_start_date_is_the_utc_date_of_the_execution():
    assert trend_drafts.start_date("2026-10-28T10:00:00Z") == dt.date(2026, 10, 28)
    assert trend_drafts.start_date("2026-10-28T23:30:00-05:00") == dt.date(2026, 10, 29)


def test_fresh_dates_are_the_start_date_its_max_age_and_the_monday_the_snapshot_stage_writes():
    assert trend_drafts.fresh_dates("2026-10-28T10:00:00Z", 1) == [dt.date(2026, 10, 28), dt.date(2026, 10, 27), dt.date(2026, 10, 26)]
    assert trend_drafts.fresh_dates("2026-10-26T05:00:00Z", 1) == [dt.date(2026, 10, 26), dt.date(2026, 10, 25)]
    assert trend_drafts.fresh_dates("2026-10-30T10:00:00Z", 0) == [dt.date(2026, 10, 30), dt.date(2026, 10, 26)]


@pytest.mark.parametrize("started, as_of", [
    ("2026-10-26T05:00:12Z", "2026-10-26"),  # the scheduled Monday run
    ("2026-10-28T10:00:00Z", "2026-10-28"),  # a snapshot dated the start day
    ("2026-10-28T10:00:00Z", "2026-10-27"),  # one day old: within the default max age
    ("2026-10-29T10:00:00Z", "2026-10-26"),  # a daily or manual run midweek: the snapshot stage stamps the Monday
    ("2026-11-01T22:00:00Z", "2026-10-26"),  # Sunday
])
def test_daily_and_manual_runs_draft_from_their_own_snapshot(started, as_of):
    calls = []
    trend_drafts.run({**BASE, "KNOWLEDGE_EXECUTION_START": started}, fetch=lambda url: as_of, read_key=lambda n: "k", execute=lambda a, e: calls.append(a) or 0)
    assert len(calls) == 1


@pytest.mark.parametrize("started, as_of", [
    ("2026-10-28T10:00:00Z", "2026-10-19"),  # last week's snapshot
    ("2026-10-28T10:00:00Z", "2026-10-29"),  # from the future
    ("2026-10-26T05:00:00Z", "2026-10-24"),  # two days before: older than the max age, and not this week's Monday
])
def test_a_snapshot_of_another_day_or_week_is_skipped(started, as_of):
    with pytest.raises(trend_drafts.Skip, match="stale"):
        trend_drafts.run({**BASE, "KNOWLEDGE_EXECUTION_START": started}, fetch=lambda url: as_of, sleep=lambda s: None, read_key=lambda n: "k", execute=lambda a, e: 0)


def test_the_max_age_is_configurable():
    environment = {**BASE, "KNOWLEDGE_EXECUTION_START": "2026-10-26T05:00:00Z", "TREND_DRAFTS_MAX_AGE_DAYS": "2"}
    calls = []
    trend_drafts.run(environment, fetch=lambda url: "2026-10-24", read_key=lambda n: "k", execute=lambda a, e: calls.append(a) or 0)
    assert len(calls) == 1


def test_the_retired_window_and_cooldown_settings_are_not_passed_to_the_command():
    calls = []
    environment = {**BASE, "TREND_DRAFTS_WINDOW_DAYS": "14", "TREND_DRAFTS_COOLDOWN_DAYS": "0"}
    trend_drafts.run(environment, fetch=lambda url: "2026-10-26", read_key=lambda n: "k", execute=lambda a, e: calls.append(a) or 0)
    assert not [flag for flag in calls[0] if flag in {"--window-days", "--cooldown-days"}]


def test_a_fresh_snapshot_runs_the_command_once_with_iam_and_the_key_only_in_the_child_environment():
    calls = []
    outcome = trend_drafts.run(BASE, fetch=lambda url: "2026-10-26", read_key=lambda name: "sk-test", execute=lambda args, env: calls.append((args, env)) or 0)
    assert "2026-10-26" in outcome
    [(args, env)] = calls
    assert args == ["papyrus", "ideas", "trends", "--site", "shipped", "--snapshot", URL, "--store", "proposals", "--max", "2"]
    assert env["PAPYRUS_GRAPHQL_AUTH"] == "iam" and env["PAPYRUS_GRAPHQL_ENDPOINT"] == ENDPOINT and env["OPENAI_API_KEY"] == "sk-test"
    assert "sk-test" not in " ".join(args)


def test_a_stale_snapshot_is_skipped_after_waiting_and_never_calls_the_model_or_ssm():
    sleeps, keys = [], []
    with pytest.raises(trend_drafts.Skip, match="stale: asOf 2026-10-19, wanted 2026-10-26"):
        trend_drafts.run(BASE, fetch=lambda url: "2026-10-19", sleep=sleeps.append, read_key=lambda name: keys.append(name) or "k", execute=lambda a, e: 0)
    assert len(sleeps) == 2 and keys == []


def test_a_snapshot_that_turns_fresh_while_waiting_runs():
    answers = iter(["2026-10-19", "2026-10-26"])
    calls = []
    trend_drafts.run(BASE, fetch=lambda url: next(answers), sleep=lambda s: None, read_key=lambda n: "k", execute=lambda a, e: calls.append(a) or 0)
    assert len(calls) == 1


def test_an_unreadable_snapshot_is_a_skip():
    def broken(url):
        raise OSError("down")

    with pytest.raises(trend_drafts.Skip, match="unreadable"):
        trend_drafts.run(BASE, fetch=broken, sleep=lambda s: None, read_key=lambda n: "k", execute=lambda a, e: 0)


@pytest.mark.parametrize("change", [
    {"TREND_DRAFTS_ENDPOINT": ""},
    {"TREND_DRAFTS_ENDPOINT": "https://evil.example.com/graphql"},
    {"TREND_DRAFTS_SNAPSHOT_URL": "http://shipped.anth.us/_data/knowledge/index.json"},
    {"TREND_DRAFTS_SNAPSHOT_URL": ""},
    {"KNOWLEDGE_OPENAI_KEY_PARAMETER": ""},
    {"KNOWLEDGE_EXECUTION_START": ""},
])
def test_missing_or_odd_configuration_is_a_skip_before_any_network_call(change):
    def no_fetch(url):
        raise AssertionError("fetched")

    with pytest.raises(trend_drafts.Skip):
        trend_drafts.run({**BASE, **change}, fetch=no_fetch, read_key=lambda n: "k", execute=lambda a, e: 0)


def test_main_never_fails_the_run(monkeypatch, capsys):
    def explode(environment):
        raise RuntimeError("`papyrus ideas trends` exited with 1")

    monkeypatch.setattr(trend_drafts, "run", explode)
    assert trend_drafts.main() == 0
    assert "trend-drafts: failed: RuntimeError" in capsys.readouterr().err

    def skip(environment):
        raise trend_drafts.Skip("the published snapshot is stale")

    monkeypatch.setattr(trend_drafts, "run", skip)
    assert trend_drafts.main() == 0
    assert "trend-drafts: skipped: the published snapshot is stale" in capsys.readouterr().out


def test_a_nonzero_exit_of_the_command_is_reported_as_a_failure():
    with pytest.raises(RuntimeError, match="exited with 3"):
        trend_drafts.run(BASE, fetch=lambda url: "2026-10-26", read_key=lambda n: "k", execute=lambda a, e: 3)


def test_each_excluded_source_host_is_passed_to_the_command_as_a_flag():
    calls = []
    environment = {**BASE, "KNOWLEDGE_EXCLUDED_SOURCE_HOSTS": "ipwatchdog.com, other.example"}
    trend_drafts.run(environment, fetch=lambda url: "2026-10-26", read_key=lambda n: "k", execute=lambda a, e: calls.append(a) or 0)
    assert calls[0][-4:] == ["--exclude-host", "ipwatchdog.com", "--exclude-host", "other.example"]
    calls.clear()
    trend_drafts.run(BASE, fetch=lambda url: "2026-10-26", read_key=lambda n: "k", execute=lambda a, e: calls.append(a) or 0)
    assert "--exclude-host" not in calls[0]
