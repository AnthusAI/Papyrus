from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import cli, project_commands  # noqa: E402
from papyrus_content.projection.engine import PluginPagesRefused, reconcile  # noqa: E402
from papyrus_content.projection.plugins import PLUGINS_ENV  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite  # noqa: E402
from procedures.newsroom.tests.test_reconcile_plugin_guard import PAGE_KEYS, context_with  # noqa: E402


def quoted_list(text: str) -> list[str]:
    return [part for part in text.replace(" and ", ",").replace('"', "").split(",") if part.strip() for part in [part.strip()]]


def attempt(context, action) -> None:
    context.before = context.site.digests()
    context.refusal = None
    context.report = None
    try:
        context.report = action()
    except PluginPagesRefused as refusal:
        context.refusal = refusal


def plugins_of(name: str) -> tuple[str, ...]:
    return (name,) if name else ()


@given("a projected site with the newsletter plugin enabled")
def projected_site(context) -> None:
    context.site = ProjectedSite("sectioned", plugins=("newsletter",))
    context.add_cleanup(context.site.cleanup)
    context.work = tempfile.TemporaryDirectory()
    context.add_cleanup(context.work.cleanup)


@given('the store holds the stray pages {keys}')
def stray_pages(context, keys: str) -> None:
    for key in quoted_list(keys):
        context.site.writer.put(key, b"<html></html>")


@when("the site is reconciled with no plugins")
def reconcile_without_plugins(context) -> None:
    attempt(context, lambda: reconcile(context_with(context.site, plugins=())))


@when("the site is reconciled as a dry run with no plugins")
def dry_run_without_plugins(context) -> None:
    attempt(context, lambda: reconcile(context_with(context.site, plugins=()), dry_run=True))


@when('the site is reconciled with the plugin "{name}"')
def reconcile_with_plugin(context, name: str) -> None:
    attempt(context, lambda: reconcile(context_with(context.site, plugins=plugins_of(name))))


@when("the site is reconciled with no plugins and the newsletter plugin known to be disabled")
def reconcile_disabled(context) -> None:
    attempt(context, lambda: reconcile(context_with(context.site, plugins=(), disabled=frozenset({"newsletter"}))))


@when('the site is reconciled as a dry run with the plugin "{name}" and only "{prefix}"')
def dry_run_only(context, name: str, prefix: str) -> None:
    attempt(context, lambda: reconcile(context_with(context.site, plugins=plugins_of(name)), dry_run=True, only=prefix))


@then("the reconcile is refused")
def is_refused(context) -> None:
    assert context.refusal is not None, "the reconcile went ahead"


@then("the reconcile is not refused")
def is_not_refused(context) -> None:
    assert context.refusal is None, str(context.refusal)


@then("the refusal names the six newsletter pages")
def names_pages(context) -> None:
    message = str(context.refusal)
    assert len(PAGE_KEYS) == 6 and all(key in message for key in PAGE_KEYS), message


@then("the stored pages are exactly as they were")
def store_unchanged(context) -> None:
    assert context.site.digests() == context.before


@then("no orphan pages are listed")
def no_orphans(context) -> None:
    assert context.report.orphan_pages == [], context.report.orphan_pages


@then("the six newsletter pages are reported as kept plugin pages")
def kept(context) -> None:
    assert set(context.report.protected_pages) == set(PAGE_KEYS)


@then("no drift is reported")
def no_drift(context) -> None:
    assert not context.report.drift


@then("the six newsletter pages still exist")
def pages_exist(context) -> None:
    assert set(PAGE_KEYS) <= set(context.site.tree)


@then("the six newsletter pages no longer exist")
def pages_gone(context) -> None:
    assert not set(PAGE_KEYS) & set(context.site.tree)


@then("the orphan pages are exactly {keys}")
def orphans_are(context, keys: str) -> None:
    assert context.report.orphan_pages == sorted(quoted_list(keys)), context.report.orphan_pages


# ------------------------------------------------------------------ the command line


@given('an amplify_outputs.json that publishes the plugin "{name}"')
def outputs_with_plugin(context, name: str) -> None:
    path = Path(context.work.name) / "amplify_outputs.json"
    path.write_text(json.dumps({"custom": {"papyrusPlugins": {name: {}}}}), encoding="utf-8")
    context.outputs = str(path)


@given("no amplify_outputs.json")
def no_outputs(context) -> None:
    context.outputs = str(Path(context.work.name) / "amplify_outputs.json")


def without_override():
    environment = {key: value for key, value in os.environ.items() if key != PLUGINS_ENV}
    return mock.patch.dict(os.environ, environment, clear=True)


@when("the projection environment is built without a PAPYRUS_PLUGINS override")
def environment_without_override(context) -> None:
    with without_override():
        context.environment = project_commands._projection_environment({"amplify-outputs": context.outputs})


@when('the projection environment is built with PAPYRUS_PLUGINS set to "{value}"')
def environment_with_override(context, value: str) -> None:
    with without_override(), mock.patch.dict(os.environ, {PLUGINS_ENV: value}):
        context.environment = project_commands._projection_environment({"amplify-outputs": context.outputs})


@then('PAPYRUS_PLUGINS is "{value}"')
def plugins_is(context, value: str) -> None:
    assert context.environment[PLUGINS_ENV] == value, context.environment[PLUGINS_ENV]


@when('the command line reconciles with PAPYRUS_PLUGINS set to "{value}"')
def command_reconciles(context, value: str) -> None:
    context.client_created = False

    def create_client():
        context.client_created = True
        return object(), {}

    errors = []
    with without_override(), mock.patch.dict(os.environ, {PLUGINS_ENV: value}), \
            mock.patch.object(project_commands, "create_authoring_client", create_client), \
            mock.patch.object(project_commands, "_context_for", lambda _client, _options: SimpleNamespace(projector=SimpleNamespace())), \
            mock.patch("sys.stderr") as stderr:
        context.exit_code = cli.main(["content", "project", "--reconcile", "--amplify-outputs", context.outputs])
        errors = [call.args[0] for call in stderr.write.call_args_list if call.args]
    context.error_text = "".join(errors)


@then("the command exits with an error that says the plugin list differs from the deployed one")
def differs(context) -> None:
    assert context.exit_code != 0 and "differs from the deployed one" in context.error_text, context.error_text


@then("the command exits with an error that says the plugin list cannot be checked")
def cannot_check(context) -> None:
    assert context.exit_code != 0 and "cannot be checked" in context.error_text, context.error_text


@then("no content is read")
def nothing_read(context) -> None:
    assert not context.client_created
