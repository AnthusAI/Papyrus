"""A site's figure rules (features_backend/site-figure-rules.feature). The backend and the files are in-memory fakes."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.figures import cli as figures_cli  # noqa: E402
from papyrus_content.figures.renderer import packaged_text  # noqa: E402
from papyrus_content.guidelines import GuidelineError, GuidelineStore  # noqa: E402
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402
from papyrus_content.guidelines.figure_rules import figure_rules  # noqa: E402


def site(text=None, publication="example"):
    backend = FakeBackend(publication=publication)
    store = GuidelineStore(backend, FakeFiles(backend))
    if text:
        store.save("figure-rules", {"schemaVersion": 1, "bodyMarkus": text}, expected_current_version_id="none", actor="Ada Admin", reason="Our rules", now="2026-11-11T10:00:00Z")
    return backend, store


@given("a site that has saved no figure rules")
def step_none(context):
    context.backend, context.store = site()


@given('a site that saved the figure rules "{text}"')
def step_saved(context, text):
    context.backend, context.store = site(text)


@given("a second site with its own backend that saved no figure rules")
def step_second(context):
    context.second = site(publication="second")


@when("the figure rules are read")
def step_read(context):
    context.rules = figure_rules(context.backend, packaged_text("rules.md"), context.store)


@when("the second site's figure rules are read")
def step_read_second(context):
    backend, store = context.second
    context.rules = figure_rules(backend, packaged_text("rules.md"), store)


@then("they are the packaged general rules")
def step_packaged(context):
    assert context.rules["text"] == packaged_text("rules.md")


@then("they are reported as the packaged default")
def step_reported_default(context):
    assert context.rules["source"] == "default" and context.rules["reference"] is None


@then('the text is exactly "{text}"')
def step_exact(context, text):
    assert context.rules["text"] == text


@then("they are reported as the site's own, at version {number:d}")
def step_reported_site(context, number):
    assert context.rules["source"] == "site" and context.rules["reference"]["versionNumber"] == number


@then("none of the packaged general rules is in the text")
def step_not_merged(context):
    assert "Light and dark are both mandatory" not in context.rules["text"]


@when("an admin saves figure rules with no text")
def step_save_empty(context):
    try:
        context.store.save("figure-rules", {"schemaVersion": 1, "bodyMarkus": "  "}, expected_current_version_id="none", actor="Ada Admin", reason="Empty", now="2026-11-11T10:00:00Z")
        context.refusal = None
    except GuidelineError as error:
        context.refusal = str(error)


@then("the save is refused naming bodyMarkus")
def step_refused(context):
    assert context.refusal and "bodyMarkus" in context.refusal, context.refusal


@when("the figure rules command is run with the packaged flag")
def step_command_packaged(context):
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=AssertionError("the site was read")):
        context.printed = figures_cli.rules_text(packaged_only=True)


@then("it prints the packaged general rules and does not look at the site")
def step_prints_packaged(context):
    assert context.printed == packaged_text("rules.md")


@when("the figure rules command is run and the site cannot be reached")
def step_command_unreachable(context):
    context.command_error = None
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=RuntimeError("not signed in")):
        try:
            figures_cli.rules_text()
        except ValueError as error:
            context.command_error = str(error)


@then("it fails saying the site's figure rules could not be read")
def step_command_failed(context):
    assert context.command_error and "could not read the site's figure rules" in context.command_error, context.command_error
