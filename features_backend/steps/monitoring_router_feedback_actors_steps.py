from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402


def feedback_posts(context):
    return [c[2] for c in context.cyclotron.posts() if c[2]["operation"] == "feedback"]


@given("a router and three delivered stories")
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
@then("the feedback task runs")
def step_run(context):
    context.reads = []
    reads = context.reads

    class Counting(tr.FakeAppSync):
        def get_record(self, model, record_id):
            reads.append(record_id)
            return super().get_record(model, record_id)

    config = tr.validate_router_config(context.table_.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    client = tr.CyclotronClient(config, sign=lambda m, u, b: {}, http=context.cyclotron.http, sleep=lambda s: None, clock=lambda: 0)
    context.result = tr.run_router(context.store, "hn", now=5000, task="feedback", cyclotron=client,
                                   appsync=lambda e: Counting(context.references), deliver=tr.Delivery())


@then("one feedback was sent to Cyclotron with the label include")
def step_sent(context):
    sent = feedback_posts(context)
    assert len(sent) == 1 and sent[0]["payload"]["label"] == "include", sent


@then("the editor subject sent does not contain an email address")
def step_no_email(context):
    assert "@" not in feedback_posts(context)[0]["payload"]["reviewer"]


@then("no feedback was sent to Cyclotron")
def step_none(context):
    assert feedback_posts(context) == []
    assert context.result["feedback"]["sent"] == 0 and context.result["feedback"]["skipped"] == 0   # not votes: never even candidates


@given("the publication binding has since moved to revision {revision} with unchanged criteria")
def step_rebind(context, revision):
    tr.rebind(context.table_, revision, since="1")


@given("the publication binding has since moved to revision {revision} with changed criteria")
def step_rebind_changed(context, revision):
    tr.rebind(context.table_, revision, since=revision)


@given('the vote was stored under criteria fingerprint "{voted}" and the publication\'s criteria are {tense} "{current}"')
def step_fingerprints(context, voted, tense, current):
    tr.set_fingerprints(context.table_, voted, current)


@then("the vote was recorded as stale")
def step_stale(context):
    assert context.table_.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]["feedback"] == "stale"
    assert context.result["feedback"]["skipped"] == 1


@then("no feedback was sent to Cyclotron that was accepted")
def step_none_accepted(context):
    assert feedback_posts(context) == []


@then("the feedback was sent under binding revision {revision}")
def step_revision(context, revision):
    assert [p["payload"]["bindingRevision"] for p in feedback_posts(context)] == [revision]


@then("the feedback stays waiting for the next run")
def step_queued(context):
    assert context.result["feedback"]["failed"] == 1 and context.result["feedback"]["status"] == "complete"
    assert not [key for key in context.table_.items if key[1].startswith("FB#")]   # no final receipt: the vote is asked for again


@given("Cyclotron answers feedback with publication binding changed")
def step_409(context):
    context.cyclotron.feedback_override = (409, {"detail": "publication binding changed"})


@when("Cyclotron accepts feedback again")
def step_ok(context):
    context.cyclotron.feedback_override = None


@then("the feedback was delivered on the second attempt with the same request id")
def step_second(context):
    sent = feedback_posts(context)
    assert len(sent) == 2 and sent[0]["requestId"] == sent[1]["requestId"], sent
    assert context.result["feedback"]["sent"] == 1


@given("the stored router config has no feedback setting")
def step_no_switch(context):
    config = tr.router_config()
    assert "feedback" not in config
    context.table_.put_item(config)


@given("the stored router config still says feedback is false")
def step_old_switch(context):
    context.table_.put_item(tr.router_config(feedback=False))


@when("the Cyclotron accepts a reference automatically")
def step_auto(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "auto:cyclotron")


@given("the Cyclotron accepted a reference automatically and the feedback task ran")
def step_auto_ran(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "auto:cyclotron")
    step_run(context)


@when("an editor rejects that reference in the newsroom UI")
def step_editor_rejects(context):
    context.references["reference-anth-us-101"] = tr.ref("rejected", "editor@example.test", at="2026-10-22T01:00:00Z")


@when("an editor accepts that reference in the newsroom UI")
def step_editor_reaccepts(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "editor@example.test", at="2026-10-22T01:00:00Z")


@then("one feedback was sent to Cyclotron with the label exclude")
def step_sent_exclude(context):
    sent = feedback_posts(context)
    assert len(sent) == 1 and sent[0]["payload"]["label"] == "exclude", sent


@then("the automatic acceptance is not counted as an editor's vote")
def step_auto_queued(context):
    assert context.result["feedback"]["sent"] == 0 and context.result["feedback"]["skipped"] == 0
    assert not [key for key in context.table_.items if key[1].startswith("FB#")]


@when("a monitor's rule accepts a reference automatically")
def step_rule(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "auto:rule")


def with_reason(status, actor, why, at="2026-10-21T01:00:00Z"):
    return tr.ref(status, actor, at) | {"curationStatusReason": why}


@when('an editor rejects a reference in the newsroom UI saying "{why}"')
def step_rejects_saying(context, why):
    context.references["reference-anth-us-101"] = with_reason("rejected", "editor@example.test", why)


@when('an editor accepts a reference in the newsroom UI saying "{why}"')
def step_accepts_saying(context, why):
    context.references["reference-anth-us-101"] = with_reason("accepted", "editor@example.test", why)


@when('an editor rejects that reference in the newsroom UI saying "{why}"')
def step_rejects_that_saying(context, why):
    context.references["reference-anth-us-101"] = with_reason("rejected", "editor@example.test", why, at="2026-10-22T01:00:00Z")


@given("an editor accepted a reference and the feedback task ran")
def step_accepted_and_ran(context):
    context.references["reference-anth-us-101"] = tr.ref("accepted", "editor@example.test")
    step_run(context)


@when('the editor adds the explanation "{why}" to that vote')
def step_adds_explanation(context, why):
    context.references["reference-anth-us-101"] = with_reason("accepted", "editor@example.test", why)   # same status, same time: only the words are new


@given("{count:d} earlier deliveries that nobody voted on")
def step_old_deliveries(context, count):
    for number in range(count):
        key = f"DELIV#anth-us#reference-anth-us-old-{number}"
        context.table_.items[("MONITOR#hn", key)] = {
            "pk": "MONITOR#hn", "sk": key, "publicationId": "anth-us", "referenceId": f"reference-anth-us-old-{number}", "itemId": "hn-1",
            "source": {"revision": 1}, "output": "anth-us-relevance", "bindingRevision": "1",
            "gsi1pk": "FEEDBACK#hn#pending", "gsi1sk": f"2026-10-01T00:00:00Z#{number}"}


@then('the feedback carries the explanation "{why}"')
def step_carries(context, why):
    assert feedback_posts(context)[-1]["payload"].get("comment") == why, feedback_posts(context)


@then("the feedback carries no explanation")
def step_carries_none(context):
    assert "comment" not in feedback_posts(context)[-1]["payload"], feedback_posts(context)


@then('the latest feedback carries the explanation "{why}"')
def step_latest_carries(context, why):
    step_carries(context, why)


@then('the latest feedback has the label {label} and carries the explanation "{why}"')
def step_latest_label(context, label, why):
    assert feedback_posts(context)[-1]["payload"]["label"] == label
    step_carries(context, why)


@then("Cyclotron has received {count:d} feedback request")
@then("Cyclotron has received {count:d} feedback requests")
def step_count(context, count):
    assert len(feedback_posts(context)) == count, feedback_posts(context)


@then("Cyclotron has received {count:d} feedback requests with different request ids")
def step_count_distinct(context, count):
    sent = feedback_posts(context)
    assert len(sent) == count and len({post["requestId"] for post in sent}) == count, sent


@then("the feedback task read no delivered reference one by one")
def step_no_reads(context):
    assert context.reads == []


@when('an editor confirms that automatic acceptance saying "{why}"')
def step_confirms_saying(context, why):
    # The newsroom's Accept on an automatically accepted Reference: still accepted, but the actor is now the editor, the time is the editor's
    # and the reason is the editor's own words (the router's reason is replaced).
    context.references["reference-anth-us-101"] = with_reason("accepted", "editor@example.test", why, at="2026-10-22T01:00:00Z")


@when("an editor confirms that automatic acceptance without an explanation")
def step_confirms_plain(context):
    context.references["reference-anth-us-101"] = with_reason("accepted", "editor@example.test", None, at="2026-10-22T01:00:00Z")
