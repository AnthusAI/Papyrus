"""features_backend/localize-repair-acceptance.feature: when a polished block is accepted."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from papyrus_content.localize.checks import Finding, faithfulness_worse  # noqa: E402


def finding(policy: str, severity: str) -> Finding:
    return Finding(category="faithfulness", policy=policy, severity=severity, status="violation", message=f"{policy}", excerpt="", source_excerpt="", replacement=None, span=None, drives_rewrite=False)


@given('a block with the error "{policy}" and no other finding')
def step_before(context, policy):
    context.before = [finding(policy, "error")]


@when('the repair has only the warning "{policy}"')
def step_after_warning(context, policy):
    context.after = [finding(policy, "warn")]


@when('the repair has the warning "{policy}"')
def step_after_other(context, policy):
    context.after = [finding(policy, "warn")]


@then("the repair is not worse")
def step_not_worse(context):
    assert not faithfulness_worse(context.before, context.after)


@then("the repair is worse")
def step_worse(context):
    assert faithfulness_worse(context.before, context.after)
