"""Excluded source hosts (features_backend/idea-excluded-source-hosts.feature). The backend, the pages and the model are fakes."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import NOW, SITE_BASE, history_entry, read_item_page, reference, release_draft  # noqa: E402
from papyrus_content.ideas import monitor_stories, trends  # noqa: E402
from papyrus_content.ideas.store import JsonStore  # noqa: E402
from test_monitor_stories import PAGE, MonitorClient, StoryModel, context as site_context, decision, provenance  # noqa: E402


def load_job(name):
    spec = importlib.util.spec_from_file_location(f"{name}_excluded_steps", REPO_ROOT / "infra" / "knowledge-run" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@given("the monitors of the site delivered these excluded-host items:")
def step_items(context):
    rows, incoming, relations, context.eh_titles = [], {}, {}, {}
    for number, row in enumerate(context.table, start=1):
        item = reference(number, status="accepted", days_ago=float(row["days ago"]), title=row["title"])
        item["sourceUri"] = row["address"]
        rows.append(item)
        context.eh_titles[row["title"]] = row["address"]
        incoming[item["lineageId"]] = [provenance(item, row["monitor"].strip())]
        relations[item["lineageId"]] = [decision(item, 0.8)]
    context.eh_client = MonitorClient(references=rows, incoming=incoming, relations=relations, sections=("Analysis", "Tools"))


@given('an enabled automation is triggered by the monitor "{monitor}"')
def step_automation(context, monitor):
    context.eh_client.automations = [{"id": f"example.{monitor}", "enabled": True, "trigger": json.dumps({"kind": "monitor", "config": {"monitorId": monitor, "publicationId": "example"}})}]


def draft(context, hosts):
    with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
        context.eh_model = StoryModel()
        context.eh_run = monitor_stories.draft_monitor_stories(
            client=context.eh_client, site="example-site", context=site_context(), json_store=JsonStore(Path(directory)), transport=context.eh_model,
            review_client=context.eh_client, limit=5, dry_run=True, now=NOW, fetch=lambda url: PAGE, excluded_hosts=hosts,
        )


@when('the operator drafts monitor stories excluding the host "{host}"')
def step_draft(context, host):
    draft(context, [host])


@when("the operator drafts monitor stories excluding no host")
def step_draft_none(context):
    draft(context, [])


@then('no monitor story was drafted from "{title}"')
def step_not_drafted(context, title):
    address = context.eh_titles[title]
    assert not [d for d in context.eh_run["drafts"] if d["citedItems"][0]["url"] == address], context.eh_run["drafts"]
    assert not [request for request in context.eh_model.requests if address in request["input"]]


@then("the monitor story run counted {count:d} item as excluded host")
def step_counted(context, count):
    assert context.eh_run["inputs"]["excludedHost"] == count, context.eh_run["inputs"]


@then("the monitor story run counted {count:d} item as handled by an automation")
def step_handled(context, count):
    assert context.eh_run["inputs"]["handledByAutomation"] == count, context.eh_run["inputs"]


@given('a trend snapshot whose releases are published on "{host}"')
def step_snapshot(context, host):
    assert host in SITE_BASE
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "history" / "2026-10-19.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(history_entry()))
        context.eh_snapshot = {**trends.load_snapshot(str(path)), "siteBase": SITE_BASE}


@when('the trends are built excluding the host "{host}"')
def step_build(context, host):
    context.eh_plain = {s["id"]: s for s in trends.build_signals(context.eh_snapshot, read_item_page)}
    context.eh_signals = trends.build_signals(context.eh_snapshot, read_item_page, excluded_hosts=[host])


@then("the model is shown no items")
def step_no_items(context):
    model_input = trends.build_input(context.eh_snapshot, context.eh_signals, {"sections": [{"title": "Analysis"}], "stories": []}, 3)
    assert model_input["items"] == []


@then('the signal for "{name}" still reports its window count from the snapshot')
def step_counts(context, name):
    key = next(identifier for identifier, signal in context.eh_plain.items() if signal["name"] == name)
    after = {s["id"]: s for s in context.eh_signals}[key]
    assert after["windowCount"] == context.eh_plain[key]["windowCount"] and after["history"] == context.eh_plain[key]["history"]


@when('a draft citing those releases is checked excluding the host "{host}"')
def step_check(context, host):
    signals = trends.build_signals(context.eh_snapshot, read_item_page)
    context.eh_valid, context.eh_invalid = trends.validate_drafts(
        [release_draft()], trends.handles_for(signals), {s["id"]: s for s in signals}, ["Analysis", "News"], 3, excluded_hosts=[host]
    )


@then("the draft fails the citation check because it cites an excluded source host")
def step_rejected(context):
    assert context.eh_valid == []
    reasons = [problem["reason"] for problem in context.eh_invalid[0]["citationCheck"]["problems"]]
    assert any(reason.startswith("cites_excluded_source_host:") for reason in reasons), reasons


@given('the scheduled run excludes the hosts "{hosts}"')
def step_hosts(context, hosts):
    context.eh_environment = {"KNOWLEDGE_EXCLUDED_SOURCE_HOSTS": hosts}


@when("the trend-drafts and monitor-stories steps build their commands")
def step_commands(context):
    environment = context.eh_environment
    trend, stories = load_job("trend_drafts"), load_job("monitor_stories")
    context.eh_commands = [
        trend.trends_command("example-site", "https://example.test/index.json", 2, trend.exclude_flags(environment)),
        stories.command_for("example-site", 3, "", stories.exclude_flags(environment)),
    ]


@then('both commands carry an exclude-host flag for "{first}" and for "{second}"')
def step_flags(context, first, second):
    for command in context.eh_commands:
        pairs = [command[i + 1] for i, token in enumerate(command) if token == "--exclude-host"]
        assert pairs == [first, second], command
