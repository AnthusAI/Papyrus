"""features_backend/suggest-once.feature. Fakes only; the unit tests in procedures/newsroom/tests/test_monitoring_vectors.py share them."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_vectors as tv  # noqa: E402

SORT_KEY = "STATE#suggested#example-site#lineage-1"


def once(context):
    if not hasattr(context, "once"):
        context.once = SimpleNamespace(store=tv.Store(), suggester=tv.Suggester(), lines=[], response=None, message=None, reads=[], calibrations=None)
        context.once.calibrations = tv.once.Calibrations(lambda client: context.once.reads.append(1) or "calibration")
    return context.once


def deliver(context, message):
    held = once(context)
    config = {"publications": [{**tv.PUBLICATION, "monitorStories": tv.POLICY}]}
    held.response = tv.once.handle_queue(held.store, {"Records": [tv.record_for(message, "m1")]}, config_for=lambda monitor: config, appsync=lambda endpoint, *tenant: "client",
                                         provider_for=lambda publication: "provider", calibrations=held.calibrations, suggester=held.suggester, now=tv.RUN_AT, emit=held.lines.append)


@given('a Reference whose summary vector was just stored with the text hash "{content_hash}"')
def step_stored(context, content_hash):
    once(context).message = tv.once.suggestion_message("hn", "example-site", "lineage-1", content_hash)


@given("the vector search fails")
def step_fails(context):
    once(context).suggester.fail = True


@when("its check runs")
def step_check(context):
    deliver(context, once(context).message)


@when("the same message is delivered again")
def step_again(context):
    deliver(context, once(context).message)


@when('a message arrives for the same Reference with the hash "{content_hash}"')
def step_changed(context, content_hash):
    deliver(context, tv.once.suggestion_message("hn", "example-site", "lineage-1", content_hash))


@then('suggestions are made for it and a record is stored under the router\'s table for that Reference with the hash "{content_hash}"')
def step_record(context, content_hash):
    held = once(context)
    assert held.suggester.asked == ["lineage-1"] and held.store.rows[SORT_KEY]["contentHash"] == content_hash and held.store.rows[SORT_KEY]["pk"] == "MONITOR#hn", held.store.rows


@then("the vector search ran once")
def step_once(context):
    assert once(context).suggester.asked == ["lineage-1"], once(context).suggester.asked


@then('the vector search ran twice and the record holds the hash "{content_hash}"')
def step_twice(context, content_hash):
    held = once(context)
    assert held.suggester.asked == ["lineage-1", "lineage-1"] and held.store.rows[SORT_KEY]["contentHash"] == content_hash


@then("the batch reports the message as failed")
def step_failed(context):
    assert once(context).response == {"batchItemFailures": [{"itemIdentifier": "m1"}]}, once(context).response


@then("no record is stored")
def step_no_record(context):
    assert once(context).store.rows == {}


@then("the calibration was read once")
def step_calibration(context):
    assert len(once(context).reads) == 1, once(context).reads


@given("a site whose References are all indexed and checked")
def step_all_checked(context):
    site = tv.Site([tv.row(n, n) for n in range(1, 6)], place=tv.quiet_place(5))
    site.fill_index()
    context.checked_site = site


@when("editors vote on, star, accept and reject some of them and the vector pass runs")
def step_edits(context):
    site = context.checked_site
    site.feed.references["ref-1"].update(updatedAt=tv.stamp(10), starRating=4)
    site.feed.references["ref-2"].update(updatedAt=tv.stamp(11), predictedAcceptProbability=0.9)
    site.feed.references["ref-3"].update(**tv.row(3, 12, "pending"))
    site.feed.references["ref-4"].update(**tv.row(4, 13, "rejected"))
    context.sqs = tv.Sqs()
    site.run(hook=tv.once.queue_sender("hn", "example-site", context.sqs, "https://queue"))


@then("no message was put on the suggestion queue")
def step_no_message(context):
    assert context.sqs.requests == [], context.sqs.requests


def template_resources():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: {suffix: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node)
                                                                   if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)})
    return yaml.load(tv.template_text(), Loader=Loader)["Resources"]


@given("the monitoring template and its suggestion queue")
def step_template(context):
    context.resources = template_resources()


@then("the suggestion queue redrives to its dead-letter queue after {count:d} receives")
def step_redrive(context, count):
    policy = context.resources["SuggestQueue"]["Properties"]["RedrivePolicy"]
    assert policy["maxReceiveCount"] == count and policy["deadLetterTargetArn"] == {"GetAtt": "SuggestDeadLetterQueue.Arn"}


@then("an alarm watches the dead-letter queue")
def step_alarm(context):
    alarm = context.resources["SuggestDeadLetterAlarm"]["Properties"]
    assert alarm["Namespace"] == "AWS/SQS" and alarm["AlarmActions"] == [{"Ref": "AlarmTopic"}]


@then("no schedule starts a suggestion task")
def step_no_schedule(context):
    for name, resource in context.resources.items():
        if resource["Type"] == "AWS::Scheduler::Schedule":
            target = resource["Properties"]["Target"].get("Input")
            assert not (isinstance(target, str) and "suggest" in target), name


@given("a site with 3 accepted or pending References of which one has a record")
def step_three(context):
    context.unchecked = SimpleNamespace(store=tv.Store(), client=tv.ListingClient(["lineage-1", "lineage-2"], ["lineage-3"]), sqs=tv.Sqs(), dry=None, wet=None)
    tv.check(context.unchecked.store, tv.Suggester(), lineage="lineage-1")


@when("the command runs without write")
def step_dry(context):
    held = context.unchecked
    held.dry = tv.once.queue_unchecked(held.client, held.store, "hn", tv.PUBLICATION, write=False, sqs=held.sqs, queue_url="https://queue")


@then("it reports {count:d} unchecked References, says it scanned all of them, and queues nothing")
def step_dry_result(context, count):
    held = context.unchecked
    assert held.dry["unchecked"] == count and "all" in held.dry["scanned"] and held.sqs.requests == [] and held.dry["write"] is False


@when("the command runs with write")
def step_wet(context):
    held = context.unchecked
    held.wet = tv.once.queue_unchecked(held.client, held.store, "hn", tv.PUBLICATION, write=True, sqs=held.sqs, queue_url="https://queue")


@then("{count:d} messages are queued, one for each unchecked Reference")
def step_wet_result(context, count):
    held = context.unchecked
    bodies = [json.loads(entry["MessageBody"]) for _, entries in held.sqs.requests for entry in entries]
    assert held.wet["queued"] == count and sorted(body["referenceLineageId"] for body in bodies) == ["lineage-2", "lineage-3"]
