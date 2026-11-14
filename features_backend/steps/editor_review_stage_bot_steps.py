import json
import sys
from pathlib import Path

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_editor_review as tr  # noqa: E402
import test_story_triggers as t  # noqa: E402
from papyrus_content import editor_review as er  # noqa: E402

BOT = "anthus.editor-review"


def stored_review(context):
    return json.loads(context.world.client.tables["Item"][t.LINEAGE]["metadata"]).get("editorReview")


def run_review(context, raw, check=None):
    world = context.world
    (outcome,) = world.deliver()
    assert outcome["status"] == "started", outcome
    request = world.invoked[0]
    try:
        contract = tr.record(world, raw, check=check or context.check)
    except ValueError as error:
        context.refused = error
        return
    context.contract = contract
    world.finish(request, output=contract)


def review_with(*overrides, **changes):
    return tr.with_findings(*overrides, **changes)


@given("a story in the copywriting stage with a table in its body and an editor-review bot that moves stories to typesetting")
def setup(context):
    context.world = t.World(t.stage_automation(BOT, "copywriting", "typesetting"), stage="copywriting")
    context.world.client.update_record("Item", {"id": t.LINEAGE, "bodyMarkus": tr.BODY})
    context.body_before = dict(context.world.client.tables["Item"][t.LINEAGE])
    context.check, context.refused, context.attachment = None, None, None


@given('the copywriting Assignment has a brief attachment reading "{text}"')
def brief_attachment(context, text):
    tr.add_assignment(context.world)
    context.world.client.tables["ModelAttachment"] = {"att-1": {"id": "att-1", "ownerId": "assignment-1", "role": "assignment_brief", "sortKey": "a", "status": "active"}}
    context.attachment = text.encode()


@given('the editorial check found an error-level violation of "{rule}"')
def violation(context, rule):
    context.check = {"status": "checked", "violations": 1, "reviews": 0, "findings": [{"rule": rule, "severity": "error", "status": "violation", "message": "x"}]}


@when("the editor approves the version")
def approve(context):
    run_review(context, tr.passing())


@when('the editor asks for a revision because the promised links are missing, with the note "{note}"')
def revise(context, note):
    run_review(context, review_with(tr.failing_finding("promises-kept"), verdict="revise", revisionNotes=[note]))


@when('the editor asks for a reframe with the note "{note}"')
def reframe(context, note):
    run_review(context, tr.passing(verdict="reframe", revisionNotes=[note]))


@when('the editor approves although "{criterion}" failed at error severity')
def approve_failed(context, criterion):
    run_review(context, review_with(tr.failing_finding(criterion)))


@when('the editor approves but never assessed "{criterion}"')
def approve_unassessed(context, criterion):
    raw = tr.passing()
    raw["findings"] = [f for f in raw["findings"] if f["criterion"] != criterion]
    run_review(context, raw)


@when("the editor approves and marks the tables criterion not applicable")
def approve_na(context):
    run_review(context, review_with({"criterion": "tables-verified", "status": "na", "severity": "info", "note": "none"}))


@when('the editor answers with the verdict "{verdict}"')
def bad_verdict(context, verdict):
    run_review(context, {"verdict": verdict})


@when("the editor reads the inputs for the version")
def read_inputs(context):
    kwargs = {"read_attachment": lambda client, attachment: context.attachment}
    context.inputs = tr.inputs_for(context.world, **kwargs)


@then("the story is still in the {stage} stage")
def still_in_stage(context, stage):
    assert context.world.stage() == stage


@then('the version records an editor review with verdict "{verdict}", the model, the context hash and the time')
def records(context, verdict):
    review = stored_review(context)
    assert review["verdict"] == verdict and review["model"] == "gpt-6-luna" and review["contextHash"] == "ctx-hash-1" and review["at"] == t.NOW


@then('a flag review request raised by the bot mentions "{text}"')
def flag(context, text):
    (review,) = context.world.reviews()
    assert review["mode"] == "flag" and review["raisedBy"] == f"automation:{BOT}" and text in review["reason"], review


@then('the version records the revision notes "{note}"')
def notes(context, note):
    assert note in stored_review(context)["revisionNotes"]


@then('the version records the failed criterion "{criterion}"')
def failed(context, criterion):
    assert any(f["criterion"] == criterion and f["status"] == "fail" for f in stored_review(context)["findings"])


@then('the version records the verdict "{verdict}", downgraded from "{origin}"')
def downgraded(context, verdict, origin):
    review = stored_review(context)
    assert review["verdict"] == verdict and review["downgradedFrom"] == origin


@then("the version records an illustration plan and a typesetting plan")
def plans(context):
    review = stored_review(context)
    assert review["illustrationPlan"] and review["typesettingPlan"]


@then('the brief source is "{source}" and the inputs say the editorial context is the brief')
def no_brief(context, source):
    assert context.inputs["brief"]["source"] == source and "editorial context" in context.inputs["briefFallback"]


@then('the brief source is "{source}" and its text is "{text}"')
def brief_text(context, source, text):
    assert context.inputs["brief"]["source"] == source and context.inputs["brief"]["text"] == text


@then("the inputs carry the editorial context text and its hash")
def context_inputs(context):
    assert context.inputs["editorialContext"]["text"] and context.inputs["editorialContext"]["hash"] == "ctx-hash-1"


@then("the inputs list one table and the editorial check result")
def tables(context):
    assert len(context.inputs["tables"]) == 1 and context.inputs["editorialCheck"]["status"] == "checked"


@then("the review is refused and the version has no editor review")
def refused(context):
    assert context.refused is not None and stored_review(context) is None


@then("the version's body, state and status are unchanged")
def unchanged(context):
    row = context.world.client.tables["Item"][t.LINEAGE]
    for key in ("bodyMarkus", "versionState", "status", "stage"):
        assert row[key] == context.body_before[key], key


@then("no Message and no published item exists")
def nothing_else(context):
    tables_ = context.world.client.tables
    assert not tables_.get("Message") and not tables_.get("PublishedItem")
