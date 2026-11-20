"""The one operation gate (features_backend/agents/operation-gate.feature). The policy is the real agent policy store over in-memory storage."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.agent_gate import GateRun  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.agent_rungs import PERSON_ONLY, RUNGS  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.images.handlers import Outcome  # noqa: E402
from papyrus_content.images.operations import OPERATIONS  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

TENANT = "alpha"
ADMIN = Caller(kind="person", subject="ada", is_admin=True)
ARGUMENTS = {
    "image_apply": {"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "candidateId": "c1", "alt": "A diagram of a sealed room.",
                    "expectedCurrentVersionId": "v1"},
    "image_discard": {"candidateId": "c1", "reason": "Not the right picture."},
    "image_search": {"target": {"kind": "story", "lineageId": "story-1"}},
    "image_review": {"mediaAssetId": "media-asset-1", "decision": "keep"},
    "announcements_settings_set": {"mode": "dry_run"},
}


def _store(context):
    """The site's policy store, made by the agent policy steps' ``a site where ... is at ...``; the gate's own counters start with it."""
    if getattr(context, "gate_policy", None) is not context.policy:
        context.gate_policy = context.policy
        context.writes, context.answer, context.run = 0, None, None
    return context.policy


def _handlers(context):
    def handler(arguments, caller):
        context.writes += 1
        return Outcome({}, "publication")
    return {name: handler for name in ("image_apply", "image_discard", "image_search", "announcements_settings_set", "image_review")}


@given('the section "{section}" narrows "{responsibility}" to "{rung}"')
def section_narrows(context, section, responsibility, rung):
    _store(context).set_rung(TENANT, ADMIN, responsibility, rung, reason="Seed", scope={"section": section})


@step('an agent run of "{responsibility}"')
def agent_run(context, responsibility):
    context.run = GateRun(_store(context).read(TENANT), responsibility, "run-1")
    context.caller = Caller(kind="agent", subject=responsibility, gate_run=context.run)


@when('an admin raises "{responsibility}" to "{rung}" because "{reason}"')
def raise_rung(context, responsibility, rung, reason):
    context.policy.set_rung(TENANT, ADMIN, responsibility, rung, reason=reason)


def _call(context, name, caller, section=None):
    arguments = dict(ARGUMENTS.get(name, {}))
    _store(context)
    if section:
        context.run.context["section"] = section
    context.envelope = execute(name, arguments, caller, _handlers(context))
    answers = context.run.answers if context.run else []
    context.answer = answers[-1] if answers else None


@step('the agent calls "{name}"')
def agent_calls(context, name):
    _call(context, name, context.caller)


@when('for the section "{section}" the agent calls "{name}"')
def agent_calls_in_section(context, section, name):
    _call(context, name, context.caller, section)


@when('the agent asks the gate about "{name}"')
def agent_asks_gate(context, name):
    """The door refuses an unknown name before the gate; the gate is asked directly to show it fails closed on its own."""
    context.answer, context.envelope = context.run.ask(name), {"ok": False}
    context.envelope["error"] = {"code": context.answer.answer}


@when('a person calls "{name}"')
def person_calls(context, name):
    context.run = None
    _call(context, name, Caller(kind="person", subject="ed"))
    context.person_ok = context.envelope.get("ok") is True


@then('the gate answers "{word}"')
def gate_answers(context, word):
    if context.run is None:
        assert context.person_ok and word == "allowed", context.envelope
    else:
        assert context.answer.answer == word, (context.answer, context.envelope)
        assert (context.envelope.get("ok") is True) == (word == "allowed")
        if word != "allowed":
            assert context.envelope["error"]["code"] == word


@then('the gate says "{text}"')
def gate_says(context, text):
    assert text in context.answer.reason, context.answer.reason


@then("the write did not happen")
def write_did_not(context):
    assert context.writes == 0, context.writes


@then("the write happened once")
def write_once(context):
    assert context.writes == 1, context.writes


@then('the run raises {count:d} review request naming "{first}" and "{second}"')
def run_raises(context, count, first, second):
    request = context.run.review_request
    assert request is not None and request["operations"] == [first, second] and request["runId"] == "run-1"


@then("the run raises {count:d} review requests")
def run_raises_none(context, count):
    assert count == 0 and context.run.review_request is None


@then('the run ends as "{outcome}" with the reason "{reason}"')
def run_ends(context, outcome, reason):
    assert context.run.outcome() == {"run_outcome": outcome, "run_outcome_reason": reason}


@then("the run declares no outcome of its own")
def run_declares_none(context):
    assert context.run.outcome() is None


@then("the run record names policy version {version:d} and holds {count:d} answers in order")
def run_record(context, version, count):
    record = context.run.record()
    assert record["policyVersion"] == version and len(record["gate"]) == count


@then('answer 1 is "{first}" for "{first_op}" and answer 2 is "{second}" for "{second_op}" at the rung "{rung}" needing "{needed}"')
def answers_in_order(context, first, first_op, second, second_op, rung, needed):
    one, two = context.run.record()["gate"]
    assert (one["answer"], one["operation"]) == (first, first_op)
    assert (two["answer"], two["operation"], two["rung"], two["neededRung"]) == (second, second_op, rung, needed)


@then("every operation in the table names the lowest rung an agent may call it at, or says only a person may")
def table_names_rungs(context):
    assert all(item.agent_rung == PERSON_ONLY or item.agent_rung in RUNGS[1:] for item in OPERATIONS)
    assert all(item.agent_rung != "off" for item in OPERATIONS)
