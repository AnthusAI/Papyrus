from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import model_usage, rating_agent  # noqa: E402
from papyrus_content.agent_policy.tiers import TierUnmapped, model_for  # noqa: E402
from papyrus_content.procedure_runner import usage_record  # noqa: E402
from features_backend.steps.agent_policy_steps import ADMIN, TENANT, _policy, _try  # noqa: E402


def _document(context):
    return _policy(context).read(TENANT).document


@then('the "{tier}" tier uses "{model}"')
def tier_uses(context, tier, model):
    assert model_for(_document(context), tier) == model, model_for(_document(context), tier)


@then("the \"{tier}\" tier has no model and the error names the tier")
def tier_has_none(context, tier):
    try:
        model_for(_document(context), tier)
    except TierUnmapped as error:
        assert f'"{tier}"' in str(error), str(error)
        return
    raise AssertionError(f"the {tier} tier answered with a model")


@when('an admin maps the "{tier}" tier to "{model}" because "{why}"')
def admin_maps_tier(context, tier, model, why):
    tiers = {**(_document(context).get("site") or {}).get("tiers", {}), tier: model}
    _try(context, lambda: _policy(context).set_value(TENANT, ADMIN, "tiers", tiers, reason=why))


@then('the refusal mentions "{text}"')
def refusal_names(context, text):
    assert context.refusal is not None and text in str(context.refusal), str(context.refusal)


@given('a site that maps the "{tier}" tier to "{model}"')
def site_maps_tier(context, tier, model):
    from features_backend.steps.agent_policy_steps import _fresh

    _fresh(context)
    _policy(context).set_value(TENANT, ADMIN, "tiers", {tier: model}, reason="Map the tier")


@when("the rating agent judges one Story under that policy")
def rating_agent_judges(context):
    calls = []

    def transport(url, headers, payload):
        calls.append(payload["model"])
        answer = {"stars": 3, "reason": "A sound Story."}
        return {"output_text": json.dumps(answer), "status": "completed", "usage": {"input_tokens": 120, "output_tokens": 14}}

    model, tier = model_for(_document(context), "bulk"), "bulk"
    judge = rating_agent.openai_judge("test-key", model, tier=tier, transport=transport)
    model_usage.drain()
    judge({"id": "story-a", "title": "A routine release note"}, "")
    context.model_calls = calls
    context.usage, _ = usage_record({"usage": model_usage.drain()})


@then('the model call was made with "{model}"')
def call_made_with(context, model):
    assert context.model_calls == [model], context.model_calls


@then('the run\'s usage records the tier "{tier}" and the model "{model}"')
def usage_records(context, tier, model):
    assert context.usage["tiers"] == {tier: 1}, context.usage
    assert [call["model"] for call in context.usage["perCall"]] == [model], context.usage
