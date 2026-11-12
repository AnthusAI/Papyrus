"""Optional backend features are off by default (features_backend/optional-features-off.feature). Runs the real TypeScript through a small probe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from behave import then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "scripts" / "optional-features-probe.ts"


def probe(payload: dict) -> dict:
    done = subprocess.run(["npx", "tsx", str(PROBE), json.dumps(payload)], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


@when("the backend resolves its features with nothing set")
def step_nothing(context):
    context.outcome = probe({"environment": {}})


@when('the backend resolves its features with "{name}" set to "{value}"')
def step_one(context, name, value):
    context.outcome = probe({"environment": {name: value}})


@when('the infrastructure reads a site whose environment sets "{name}" to "{value}"')
def step_site(context, name, value):
    context.outcome = probe({"site": "pilobol-us.site.json", "environment": {name: value}})


@when("the infrastructure reads each example site as it is")
def step_examples(context):
    names = sorted(path.name for path in (REPO_ROOT / "infra" / "amplify-app-shell" / "examples").glob("*.site.json"))
    context.outcomes = {name: probe({"site": name}) for name in names}


@then("the console responder, inbound email, Slack and storage backups are all off")
def step_all_off(context):
    flags = context.outcome["flags"]
    assert context.outcome["ok"] and not any(flags[name] for name in ("consoleResponder", "inboundEmail", "slack", "storageBackups")), context.outcome


@then("storage backups are on and the other three are off")
def step_backups_on(context):
    flags = context.outcome["flags"]
    assert flags["storageBackups"] and not any(flags[name] for name in ("consoleResponder", "inboundEmail", "slack")), context.outcome


@then('the build fails saying "{text}"')
def step_build_fails(context, text):
    assert not context.outcome["ok"] and text in context.outcome["error"], context.outcome


@then('the synth fails saying "{text}"')
def step_synth_fails(context, text):
    assert not context.outcome["ok"] and text in context.outcome["error"], context.outcome


@then("every example site is accepted")
def step_examples_ok(context):
    bad = {name: outcome for name, outcome in context.outcomes.items() if not outcome["ok"]}
    assert not bad, bad
