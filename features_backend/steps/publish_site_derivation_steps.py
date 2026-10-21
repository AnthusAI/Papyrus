from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content import projection_trigger  # noqa: E402


def _site(context, outputs) -> None:
    context.site_root = Path(tempfile.mkdtemp())
    context.environment = {"PAPYRUS_SITE_ROOT": str(context.site_root)}
    if outputs is not None:
        (context.site_root / "amplify_outputs.json").write_text(json.dumps(outputs), encoding="utf-8")


@given('a site whose amplify_outputs.json declares an s3-projection publication with function "{name}"')
def declared(context, name: str) -> None:
    _site(context, {"custom": {"publication": {"kind": "s3-projection", "contentActionsFunction": name}}})


@given("a site whose amplify_outputs.json declares no publication")
def undeclared(context) -> None:
    _site(context, {"custom": {"publicForms": {"endpoint": "https://example.org"}}})


@given("a site with no amplify_outputs.json")
def missing(context) -> None:
    _site(context, None)


@given("no publication environment variables are set")
def no_env(context) -> None:
    pass


@given('the environment names the function "{name}"')
def env_function(context, name: str) -> None:
    context.environment["PAPYRUS_CONTENT_ACTIONS_FUNCTION"] = name


def _patched(context):
    return mock.patch.dict("os.environ", context.environment, clear=True)


@then("projection is enabled")
def enabled(context) -> None:
    with _patched(context):
        assert projection_trigger.projection_enabled()


@then("projection is not enabled")
def disabled(context) -> None:
    with _patched(context):
        assert not projection_trigger.projection_enabled()


@then('the projection is scheduled on "{name}"')
def scheduled(context, name: str) -> None:
    with _patched(context), mock.patch.object(projection_trigger, "_invoke_lambda") as invoke:
        result = projection_trigger.trigger_projection(projection_trigger.ALL_TASK)
    assert result == {"ok": True, "scheduled": "all", "via": name}, result
    assert invoke.call_args.args[0] == name
