"""A person's answer to an agent's question wakes that agent (features_backend/agents/ask-and-answer.feature, PPY-ecf852).

Real code: the Item change feed and the ReviewRequest change feed, the listener index, the wake queue's key and deduplication rules, the procedure runner (its
run record, the gate it asks at the end of a run, the review request it files and the answer it reads), and the review request library a person answers with.
Stood in for: the site's tables (one in-memory site that records the stream a DynamoDB table would write), the queue (SQS's FIFO rules) and the procedure's own
work, which is scripted and records the input it was given. The site and queue steps are the change feeds' (item_change_feed_steps.py)."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import agent_wakes, change_feeds, item_change_feed, model_attachments, review_requests, procedure_runner as pr  # noqa: E402
from papyrus_content.agent_gate import review_answers  # noqa: E402
from papyrus_content.agent_policy.resolve import PolicyState  # noqa: E402
from papyrus_content.agent_policy.run_gate import RunDecision  # noqa: E402
from papyrus_content.change_feed_fakes import BUCKET, ENDPOINT, TENANT, FakeSqs, deploy, stream_record  # noqa: E402
from papyrus_content.localize.dispatch import decode_image  # noqa: E402

REVIEW_STREAM = "arn:aws:dynamodb:us-east-1:000000000000:table/ReviewRequest-sample/stream/2026-01-01T00:00:00.000"
AGENT = "illustrate"


class Site(tpr.NewsroomClient):
    """One site's tables: records by model, the stream every ReviewRequest write leaves, and the runner's run records (the id comes from the wake key)."""

    tenant_id = None

    def __init__(self):
        super().__init__()
        self.rows, self.pending, self.runs = {}, [], {}

    def get_record(self, model, record_id):
        if model == review_answers.RUN_MODEL:
            return copy.deepcopy(self.runs.get(record_id))
        row = self.rows.get(model, {}).get(record_id)
        return copy.deepcopy(row) if row else None

    def create_record(self, model, row):
        table = self.rows.setdefault(model, {})
        assert row["id"] not in table, f"{model} {row['id']} exists"
        table[row["id"]] = copy.deepcopy(row)
        if model == "ReviewRequest":
            self.pending.append(("INSERT", None, copy.deepcopy(row)))

    def update_record(self, model, changes):
        old = self.rows[model][changes["id"]]
        new = {**old, **{name: value for name, value in changes.items() if value is not None}}
        self.rows[model][changes["id"]] = new
        if model == "ReviewRequest":
            self.pending.append(("MODIFY", copy.deepcopy(old), copy.deepcopy(new)))

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "procedure-run-wake-" + hashlib.sha256(variables["wakeKey"].encode()).hexdigest()[:32]   # as the newsroom derives it (wake-key.ts)
            duplicate = run_id in self.runs
            self.runs.setdefault(run_id, {"id": run_id, "wakeKey": variables["wakeKey"], "runStatus": "started"})
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": duplicate, "runId": run_id, "procedureVersionId": "version-1"})}
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.runs[variables["input"]["id"]].update(variables["input"])
        return result


class Gate:
    """The policy gate the runner asks: the responsibility is the wake's agent and the policy is the scenario's."""

    def __init__(self, state):
        self.state = state

    def decide(self, request):
        agent = request["trigger"]["automationId"]
        return RunDecision(True, agent, self.state.document["agents"][agent]["rung"], self.state.version, state=self.state)


def _site(context) -> Site:
    if getattr(context, "asking_site", None) is None:
        context.asking_site = Site()
        context.procedure_inputs, context.asking_results, context.stories_needing_nobody = [], [], set()
        context.asked_for = []
        context.policy_state = PolicyState(1, {"schemaVersion": 1, "site": {}, "agents": {}})
        download = model_attachments.download_attachment_buffer
        model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
        context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", download)
    return context.asking_site


def _site_identity(context):
    return item_change_feed.Site(publication_id=context.site_id, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)


def _messages(context):
    return [(message, json.loads(message.body)) for message in context.queue.messages]


def _reviews(context):
    return [review_requests.read_review(row) for row in _site(context).rows.get("ReviewRequest", {}).values()]


def _only_review(context):
    found = _reviews(context)
    assert len(found) == 1, found
    return found[0]


def _last_result(context):
    return context.asking_results[-1]


def _story_row(story, stage):
    return {"id": f"{story}-v3", "lineageId": story, "versionNumber": 3, "versionState": "current", "versionCreatedAt": "2026-11-13T09:00:00Z",
            "versionCreatedBy": "ada", "type": "story", "stage": stage, "section": "world", "language": "en", "updatedAt": "2026-11-17T09:00:00Z",
            "metadata": json.dumps({})}


# --- the agent, its policy and its procedure --------------------------------------------------------------------------------------------------------


@given('the agent "{agent}" runs "{procedure}" when a Story enters "{stage}" and when a review request it raised is answered')
def agent_listens(context, agent, procedure, stage):
    _site(context)
    definition = SimpleNamespace(id=agent, responsibility=agent, data={
        "procedure": procedure, "paid": False, "serialBy": "subject", "safeToRepeat": False,
        "wakes": {"changes": [{"kind": "Item", "change": "stage_entered", "filter": {"stage": stage}}, {"kind": "ReviewRequest", "change": "answered"}]}})
    deploy(context, [definition])


@given('the site\'s policy puts "{agent}" at the rung "{rung}"')
def policy_rung(context, agent, rung):
    _site(context)
    context.policy_state = PolicyState(1, {"schemaVersion": 1, "site": {}, "agents": {agent: {"rung": rung}}})


@given('the agent\'s procedure asks the gate for "{operation}"')
def procedure_asks_for(context, operation):
    _site(context)
    context.asked_for = [operation]


@given('on the Story "{story}" the agent\'s procedure needs nobody\'s leave')
def needs_nobody(context, story):
    _site(context)
    context.stories_needing_nobody.add(story)


# --- changes and the feeds ---------------------------------------------------------------------------------------------------------------------------


def _deliver_item(context, story, stage):
    context.sequence = getattr(context, "sequence", 0) + 1
    batch = [stream_record("MODIFY", _story_row(story, "reporting"), _story_row(story, stage), context.sequence)]
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.queue})
    answer = item_change_feed.handle(batch, decode=decode_image, listeners=lambda: context.index.document(), send=agent_wakes.wake_sender(sqs), site=_site_identity(context))
    assert answer["batchItemFailures"] == [], answer


def _deliver_reviews(context, batch):
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.queue})
    answer = change_feeds.handle(batch, streams=change_feeds.Streams(tables={REVIEW_STREAM: "ReviewRequest"}), decode=decode_image,
                                 listeners=lambda: context.index.document(), send=agent_wakes.wake_sender(sqs), site=_site_identity(context), thread_of=lambda thread: None)
    assert answer["batchItemFailures"] == [], answer


@when('a person moves the Story "{story}" into "{stage}"')
def person_moves(context, story, stage):
    _site(context)
    _deliver_item(context, story, stage)


@when("the review request stream reaches the change feed")
def reviews_reach_feed(context):
    site = _site(context)
    batch = []
    for name, old, new in site.pending:
        context.sequence = getattr(context, "sequence", 0) + 1
        batch.append(stream_record(name, old, new, context.sequence, REVIEW_STREAM))
    site.pending.clear()
    context.last_review_batch = batch
    _deliver_reviews(context, batch)


@when("the same review request stream records reach the change feed again")
def reviews_reach_feed_again(context):
    _deliver_reviews(context, context.last_review_batch)


# --- the runner --------------------------------------------------------------------------------------------------------------------------------------


def _run(context, message):
    site = _site(context)
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": message.body}]})

    def execute_procedure(workdir, source_path, inputs, **kwargs):
        context.procedure_inputs.append(copy.deepcopy(inputs))
        operations = [] if inputs.get("story") in context.stories_needing_nobody else list(context.asked_for)
        return {"success": True, "output": {"summary": "Chose an illustration", "gate_operations": operations}, "seconds": 2}

    context.asking_results.append(pr.run_procedure_request(request, client=site, policy=Gate(context.policy_state), execute=execute_procedure,
                                                           seconds_available=900, environment={}))


def _take(context, matches):
    message = next(message for message, body in _messages(context) if matches(body))
    context.queue.messages.remove(message)   # taken: the queue's own window still remembers its deduplication id
    context.last_message = message
    _run(context, message)


@when('the runner takes the agent\'s wake for the Story "{story}"')
def runner_takes_story(context, story):
    _take(context, lambda body: body["request"]["input"].get("story") == story)


@when("the runner takes the agent's wake for the answer")
def runner_takes_answer(context):
    _take(context, lambda body: body["request"]["trigger"]["event"] == review_answers.REVIEW_ANSWERED_EVENT)


@when("the queue delivers the answer's wake to the runner again")
def runner_again(context):
    _run(context, context.last_message)


@given('the agent asked a person about the Story "{story}"')
def agent_asked(context, story):
    person_moves(context, story, "illustration")
    runner_takes_story(context, story)
    assert _last_result(context)["outcome"] == "asked", _last_result(context)
    context.asking_run_of = {**getattr(context, "asking_run_of", {}), story: _last_result(context)["runId"]}
    reviews_reach_feed(context)   # the request was filed open: no change anyone listens for
    assert context.queue.messages == [], _messages(context)


# --- answers -----------------------------------------------------------------------------------------------------------------------------------------


def _answer(context, decision, feedback=None):
    review_requests.answer_review(_site(context), _only_review(context)["id"], decision=decision, by="ada", feedback=feedback)


@when("a person approves the agent's review request")
def approves(context):
    _answer(context, "approve")


@when('a person rejects the agent\'s review request saying "{words}"')
def rejects(context, words):
    _answer(context, "reject", words)


@when('a person answers the agent\'s review request with the feedback "{words}"')
def gives_feedback(context, words):
    _answer(context, "feedback", words)


# --- outcomes ----------------------------------------------------------------------------------------------------------------------------------------


@then('the agent\'s run ended "{outcome}" with the reason "{reason}"')
def ended_with_reason(context, outcome, reason):
    result = _last_result(context)
    assert (result["outcome"], result["outcomeReason"]) == (outcome, reason), result
    record = _site(context).runs[result["runId"]]
    assert (record["outcome"], record["outcomeReason"]) == (outcome, reason), record


@then('the agent\'s run ended "{outcome}"')
def ended(context, outcome):
    result = _last_result(context)
    assert result["outcome"] == outcome, result
    assert _site(context).runs[result["runId"]]["outcome"] == outcome


@then('the agent has {count:d} review request, open, about {which}, raised by "{raised_by}"')
def one_open_review(context, count, which, raised_by):
    found = _reviews(context)
    assert len(found) == count, found
    run_id = _last_result(context)["runId"] if which == "that run" else context.asking_run_of[which.rsplit('"', 2)[1]]
    review = found[0]
    assert (review["state"], review["subject"], review["raisedBy"], review["mode"]) == ("open", {"type": "automation_run", "id": run_id}, raised_by, "hard_gate"), review


@then("the agent has {count:d} review request")
@then("the agent has {count:d} review requests")
def review_count(context, count):
    assert len(_reviews(context)) == count, _reviews(context)


@then('the gate allowed "{operation}" for that run because the person approved it in the review request')
def gate_allowed_by_approval(context, operation):
    record = _site(context).runs[_last_result(context)["runId"]]
    answers = json.loads(record["output"])["gate"]["gate"]
    request_id = _only_review(context)["id"]
    assert [(a["operation"], a["answer"], a.get("approvedIn")) for a in answers] == [(operation, "allowed", request_id)], answers


@then("the review request names that run as the one that used the answer")
def applied_in(context):
    run_id = _last_result(context)["runId"]
    asked = next(review for review in _reviews(context) if review["state"] == "answered")
    assert asked["appliedIn"]["runId"] == run_id and asked["appliedIn"]["by"] == f"agent:{AGENT}", asked["appliedIn"]
    assert any(entry["event"] == "applied" for entry in asked["history"]), asked["history"]


@then("the second delivery of the answer's wake is a duplicate")
def duplicate(context):
    assert _last_result(context)["runStatus"] == "duplicate", _last_result(context)


@then("the agent's procedure ran {count:d} time")
@then("the agent's procedure ran {count:d} times")
def procedure_ran(context, count):
    assert len(context.procedure_inputs) == count, context.procedure_inputs


@then('the run\'s summary gives the person\'s reason "{words}"')
def summary_reason(context, words):
    record = _site(context).runs[_last_result(context)["runId"]]
    assert words in record["resultSummary"] and "ada" in record["resultSummary"], record


@then('the agent\'s procedure was given the decision "{decision}" and the words "{words}"')
def given_feedback(context, decision, words):
    review = context.procedure_inputs[-1][review_answers.REVIEW_INPUT_KEY]
    assert (review["decision"], review["feedback"], review["approvedOperations"]) == (decision, words, []), review
    assert review["askingRun"] == context.asking_run_of["story-1"], review
