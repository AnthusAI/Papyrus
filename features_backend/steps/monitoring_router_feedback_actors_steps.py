from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402


def feedback_posts(context):
    return [c[2] for c in context.cyclotron.posts() if c[2]["operation"] == "feedback"]


@given("a router with feedback on and three delivered stories")
def step_given(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1000)
    context.store, context.cyclotron = tr.delivered_table(context.table_)
    context.references = {}


@when("an editor accepts a reference in the newsroom UI")
def step_editor(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "editor@example.test")


@when("the worker accepts a reference and an AI accepts another")
def step_machine(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "papyrus-monitoring-worker")
    context.references["reference-p-apyr-us-101"] = tr.ref("accepted", "ai")


@when("the feedback task runs")
def step_run(context):
    context.result = tr.feedback_run(context.table_, context.store, context.cyclotron, context.references)


@then("one feedback was sent to Cyclotron with the label include")
def step_sent(context):
    sent = feedback_posts(context)
    assert len(sent) == 1 and sent[0]["payload"]["label"] == "include", sent


@then("the editor subject sent does not contain an email address")
def step_no_email(context):
    assert "@" not in feedback_posts(context)[0]["payload"]["editor"]["subject"]


@then("no feedback was sent to Cyclotron")
def step_none(context):
    assert feedback_posts(context) == []
    assert context.result["feedback"]["skipped"] == 2
