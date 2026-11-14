"""A site adds a feed host as data (features_backend/monitoring-site-feed-hosts.feature). Nothing is fetched: the config validation and the fetch guard only."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import monitoring_feed as feed  # noqa: E402
from papyrus_content.monitoring_cloud import _validate_config  # noqa: E402
from papyrus_content.monitoring_router import source_name_for  # noqa: E402


def attempt(context):
    raw = {"sourceType": "feed", "sourceUrl": context.address, "intervalSeconds": 3600, **({"sourceName": context.source_name} if context.source_name else {})}
    try:
        context.monitor_config, context.refusal = _validate_config(raw), None
    except ValueError as error:
        context.monitor_config, context.refusal = None, str(error)


@given('a feed monitor config for "{address}"')
def step_address(context, address):
    context.address, context.source_name = address, None


@when('the config also names the source "{name}"')
def step_names(context, name):
    context.source_name = name


@then('the config is accepted and keeps the source name "{name}"')
def step_accepted_named(context, name):
    attempt(context)
    assert context.refusal is None and context.monitor_config["sourceName"] == name, context.refusal


@then('the source is shown as "{name}"')
def step_shown(context, name):
    assert source_name_for(context.address, "feed", context.monitor_config["sourceName"]) == name


@then("the config is refused saying the monitor's config must name the source")
def step_refused_name(context):
    attempt(context)
    assert context.refusal and "names the source" in context.refusal, context.refusal


@then("the config is accepted with no source name")
def step_accepted_plain(context):
    attempt(context)
    assert context.refusal is None and "sourceName" not in context.monitor_config, context.refusal


@then("the config is refused")
def step_refused(context):
    attempt(context)
    assert context.refusal, "the address was accepted"


@then("reading that address without the source's name is refused before any request")
def step_fetch_guard(context):
    with mock.patch.object(feed, "urlopen", side_effect=AssertionError("requested")):
        try:
            feed.fetch_feed(context.address)
        except ValueError:
            return
    raise AssertionError("the fetch was not refused")
