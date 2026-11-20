"""An Assignment is the request between agents (features_backend/assignment-handoff.feature, PPY-51f96f).

Real code: the operation and its gate, the Assignment writer, the Assignment change feed, the listener index, the wake queue's key and deduplication rules, the
procedure runner (its run record, its claim and its close) and the existing reopen. Stood in for: the site's tables (one in-memory site that also records the
stream a DynamoDB table would write), the queue (SQS's FIFO rules), and the procedure's own work, which is scripted. The site, queue and listener steps are the
change feeds' (item_change_feed_steps.py, change_feeds_steps.py)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import agent_assignments, agent_wakes, handoff_handlers, assignments, model_attachments, change_feeds, item_change_feed, procedure_runner as pr  # noqa: E402
from papyrus_content.agent_gate import GateRun  # noqa: E402
from papyrus_content.agent_policy.resolve import PolicyState  # noqa: E402
from papyrus_content.agent_policy.run_gate import RunDecision  # noqa: E402
from papyrus_content.change_feed_fakes import BUCKET, ENDPOINT, TENANT, FakeSqs, stream_record  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.localize.dispatch import decode_image  # noqa: E402

ARN = "arn:aws:dynamodb:us-east-1:000000000000:table/Assignment-sample/stream/2026-01-01T00:00:00.000"
STORY = "story-1"
WHY = "Claim 3 cites no source. Find one."


class Site(tpr.NewsroomClient):
    """One site's tables: records by model, the stream every Assignment write leaves, and the runner's run records (the id comes from the wake key)."""

    tenant_id = None

    def __init__(self):
        super().__init__()
        self.rows, self.pending, self.summaries, self.payloads, self.runs = {}, [], [], [], {}

    # the authoring client
    def get_record(self, model, record_id):
        row = self.rows.get(model, {}).get(record_id)
        return copy.deepcopy(row) if row else None

    def create_record(self, model, row):
        table = self.rows.setdefault(model, {})
        assert row["id"] not in table, f"{model} {row['id']} exists"
        table[row["id"]] = copy.deepcopy(row)
        if model == "Assignment":
            self.pending.append(("INSERT", None, copy.deepcopy(row)))

    def update_record(self, model, changes):
        old = self.rows[model][changes["id"]]
        new = {**old, **{name: value for name, value in changes.items() if value is not None}}
        for name, value in changes.items():
            if value is None:
                new.pop(name, None)
        self.rows[model][changes["id"]] = new
        if model == "Assignment":
            self.pending.append(("MODIFY", copy.deepcopy(old), copy.deepcopy(new)))

    def upsert(self, model, row):
        if row["id"] in self.rows.get(model, {}):
            self.update_record(model, row)
        else:
            self.create_record(model, row)
        return row["id"]

    def update_newsroom_summary(self, payload, actor_label=None, reason=None):
        self.summaries.append(payload)

    def list_by_index(self, index, key, limit=100):
        if index == "itemsByLineageAndVersion":
            return [{"id": f"{STORY}-v1", "lineageId": STORY, "versionNumber": 1, "versionState": "current"}] if key == STORY else []
        if index == "modelAttachmentsByOwnerRoleAndSortKey" and key != "version-1":
            return []
        return super().list_by_index(index, key, limit)

    # the runner's backend
    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
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
        rung = self.state.document["agents"][agent]["rung"]
        return RunDecision(True, agent, rung, self.state.version, state=self.state)


def _site(context) -> Site:
    if getattr(context, "handoff_site", None) is None:
        site = context.handoff_site = Site()
        context.handoff_run_count, context.handoff_results, context.handoff_answers = 0, [], []
        context.script = {"success": True, "output": {"summary": "Found two primary sources"}, "seconds": 3}
        context.policy_state = PolicyState(1, {"schemaVersion": 1, "site": {}, "agents": {}})
        context.sequence = getattr(context, "sequence", 0)
        saved = (agent_assignments.upload_attachment_body, assignments.upload_attachment_body, handoff_handlers._publication)
        agent_assignments.upload_attachment_body = assignments.upload_attachment_body = lambda client, attachment, body: site.payloads.append((attachment, body))
        handoff_handlers._publication = lambda client: "sample"
        download = model_attachments.download_attachment_buffer
        model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
        context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", download)
        context.add_cleanup(lambda: (setattr(agent_assignments, "upload_attachment_body", saved[0]), setattr(assignments, "upload_attachment_body", saved[1]),
                                     setattr(handoff_handlers, "_publication", saved[2])))
    return context.handoff_site


def _assignments(context, story=STORY):
    return [row for row in _site(context).rows.get("Assignment", {}).values() if row.get("itemLineageId") == story]


def _only(context, responsibility="research"):
    found = [row for row in _assignments(context) if row["assignmentTypeKey"] == agent_assignments.type_key(responsibility)]
    assert len(found) == 1, found
    return found[0]


def _wakes(context):
    return [json.loads(message.body) for message in context.queue.messages]


# --- the site's agents and rungs -------------------------------------------------------------------------------------------------------------------


@given("these responsibilities are at these rungs")
def rungs(context):
    _site(context)
    context.policy_state = PolicyState(1, {"schemaVersion": 1, "site": {}, "agents": {row["responsibility"]: {"rung": row["rung"]} for row in context.table}})


@given('the procedure ends having found "{finding}"')
def procedure_finds(context, finding):
    _site(context)
    context.script = {"success": True, "output": {"summary": finding}, "seconds": 3}


@given('the procedure fails with "{error}"')
def procedure_fails(context, error):
    _site(context)
    context.script = {"success": False, "error": error, "seconds": 3}


@given('the procedure ends asking a person about "{reason}"')
def procedure_asks(context, reason):
    _site(context)
    context.script = {"success": True, "output": {"run_outcome": "asked", "run_outcome_reason": reason}, "seconds": 3}


# --- asking ----------------------------------------------------------------------------------------------------------------------------------------


def _ask(context, caller, responsibility, story, why):
    site = _site(context)
    handlers = handoff_handlers.signed_in_handlers(lambda: site)
    context.envelope = execute("handoffs_request", {"story": story, "responsibility": responsibility, "why": why}, caller, handlers)
    context.handoff_answers.append(context.envelope)


@when('the agent "{agent}" asks "{responsibility}" for work on the Story "{story}" because "{why}"')
@given('the agent "{agent}" asked "{responsibility}" for work on the Story "{story}" because "{why}"')
def agent_asks(context, agent, responsibility, story, why):
    state = _site(context) and context.policy_state
    _ask(context, Caller(kind="agent", subject=agent, gate_run=GateRun(state, agent, f"run-{agent}-ask")), responsibility, story, why)


@when('a person asks "{responsibility}" for work on the Story "{story}" because "{why}"')
@given('a person asked "{responsibility}" for work on the Story "{story}" because "{why}"')
def person_asks(context, responsibility, story, why):
    context.handoff_requests = getattr(context, "handoff_requests", 0) + 1
    _ask(context, Caller(kind="person", subject="ada", request_id=f"request-{context.handoff_requests}"), responsibility, story, why)


@then("the request is accepted and wrote a new Assignment")
def accepted_new(context):
    assert context.envelope["ok"] and context.envelope["result"]["created"] is True, context.envelope


@then("the request is accepted and wrote nothing new")
def accepted_old(context):
    assert context.envelope["ok"] and context.envelope["result"]["created"] is False, context.envelope


@then('the request is refused as "{code}"')
def refused(context, code):
    assert not context.envelope["ok"] and context.envelope["error"]["code"] == code, context.envelope


@then("the request wrote nothing")
def nothing_written(context):
    assert _site(context).rows.get("Assignment", {}) == {} and _site(context).pending == []


@then('the Story "{story}" has {count:d} Assignment for "{responsibility}", {status}, asked by "{asker}" for this reason: "{why}"')
def has_assignment(context, story, count, responsibility, status, asker, why):
    found = [row for row in _assignments(context, story) if row["assignmentTypeKey"] == agent_assignments.type_key(responsibility)]
    assert len(found) == count, found
    row = found[0]
    assert (row["status"], row["createdBy"], row["summary"]) == (status, asker, why), row


@then('the Story "{story}" has {count:d} Assignments for "{responsibility}"')
def has_assignments(context, story, count, responsibility):
    found = [row for row in _assignments(context, story) if row["assignmentTypeKey"] == agent_assignments.type_key(responsibility)]
    assert len(found) == count, found


@then("the Assignment has a created event by {who}")
def created_event(context, who):
    row = _only(context)
    events = [e for e in _site(context).rows["AssignmentEvent"].values() if e["assignmentId"] == row["id"] and e["eventType"] == "created"]
    assert [e["actorLabel"] for e in events] == [who.strip('"')], events


@then("the request wrote no Message")
def no_message(context):
    assert "Message" not in _site(context).rows and "MessageThread" not in _site(context).rows


@then('the handoff Assignment is {status}')
def assignment_is(context, status):
    assert _only(context)["status"] == status, _only(context)


@then('the Assignment was claimed by "{agent}" while the run was in hand')
def claimed_by(context, agent):
    row = _only(context)
    events = [e for e in _site(context).rows["AssignmentEvent"].values() if e["assignmentId"] == row["id"] and e["eventType"] == "claim"]
    assert [e["actorLabel"] for e in events] == [f"agent:{agent}"], events


# --- the stream and the feed -----------------------------------------------------------------------------------------------------------------------


def _feed(context, batch):
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.queue})
    site = item_change_feed.Site(publication_id=context.site_id, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)
    streams = change_feeds.Streams(tables={ARN: "Assignment"})
    return change_feeds.handle(batch, streams=streams, decode=decode_image, listeners=lambda: context.index.document(), send=agent_wakes.wake_sender(sqs), site=site,
                               thread_of=lambda thread: None)


@when("the Assignment stream is delivered to the change feed")
def deliver(context):
    site = _site(context)
    batch = []
    for name, old, new in site.pending:
        context.sequence += 1
        batch.append(stream_record(name, old, new, context.sequence, ARN))
    site.pending.clear()
    context.last_batch = batch
    context.answer = _feed(context, batch)
    assert context.answer["batchItemFailures"] == [], context.answer


@when("the same Assignment stream records are delivered again")
def deliver_again(context):
    context.answer = _feed(context, context.last_batch)


@then('the wake key for "{agent}" names the Assignment and is "{what}"')
def wake_key(context, agent, what):
    keys = [wake["wake"]["key"] for wake in _wakes(context) if wake["wake"]["agent"] == agent]
    assert len(keys) == 1, keys
    assert keys[0].startswith(f"{agent}|{_only(context)['id']}|unversioned|{what}"), keys[0]


@then('the wake for "{agent}" carries who asked and why')
def wake_carries(context, agent):
    wake = next(wake for wake in _wakes(context) if wake["wake"]["agent"] == agent)
    given = wake["request"]["input"]
    row = _only(context)
    assert (given["askedBy"], given["why"], given["story"], given["responsibility"]) == (row["createdBy"], row["summary"], STORY, "research"), given
    assert given["subject"] == {"kind": "Assignment", "id": row["id"]}, given


# --- the run ---------------------------------------------------------------------------------------------------------------------------------------


def _run(context, message):
    site = _site(context)
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": message.body}]})

    def execute_procedure(*args, **kwargs):
        context.handoff_run_count += 1
        return copy.deepcopy(context.script)

    context.handoff_results.append(pr.run_procedure_request(request, client=site, policy=Gate(context.policy_state), execute=execute_procedure, seconds_available=900, environment={}))
    return request


@when('the runner takes the wake for "{agent}"')
def runner_takes(context, agent):
    message = next(message for message in context.queue.messages if json.loads(message.body)["wake"]["agent"] == agent)
    context.queue.messages.remove(message)   # taken: the queue's own window still remembers its deduplication id
    context.last_message = message
    _run(context, message)


@when("the queue delivers that wake to the runner again")
def runner_again(context):
    _run(context, context.last_message)


@then("the responsible procedure ran {count:d} time")
def ran(context, count):
    assert context.handoff_run_count == count, context.handoff_run_count


@then("the second delivery is recognised as a duplicate")
def duplicate(context):
    assert context.handoff_results[-1]["runStatus"] == "duplicate", context.handoff_results[-1]


@then('the responsible run ended "{outcome}"')
def run_ended(context, outcome):
    assert context.handoff_results[-1]["outcome"] == outcome, context.handoff_results[-1]


# --- the result ------------------------------------------------------------------------------------------------------------------------------------


def _payload_of(context, event_type):
    row = _only(context)
    ids = [e["id"] for e in _site(context).rows["AssignmentEvent"].values() if e["assignmentId"] == row["id"] and e["eventType"] == event_type]
    assert len(ids) == 1, ids
    matching = [body for attachment, body in _site(context).payloads if attachment["ownerId"] == ids[0]]
    assert len(matching) == 1, matching
    return json.loads(matching[0] if isinstance(matching[0], str) else matching[0].decode("utf-8")), next(e for e in _site(context).rows["AssignmentEvent"].values() if e["id"] == ids[0])


@then('the completion on the Story records the run, its outcome "{outcome}" and the result "{result}"')
def completion_result(context, outcome, result):
    payload, event = _payload_of(context, "complete")
    assert (payload["outcome"], payload["story"]) == (outcome, STORY) and result in payload["result"], payload   # the run record's own summary of what the run said
    assert payload["runId"].startswith("run-for-research|"), payload
    assert event["toStatus"] == "completed" and event["actorLabel"] == "agent:research", event


@then('the failure on the Assignment records the error "{error}"')
def failure_recorded(context, error):
    payload, event = _payload_of(context, "fail")
    assert payload["error"] == error and event["note"] == error and event["toStatus"] == "failed", (payload, event)


@then("exactly {count:d} flag is raised for a person about the Assignment")
def flags(context, count):
    reviews = list(_site(context).rows.get("ReviewRequest", {}).values())
    assert len(reviews) == count, reviews
    if count:
        row = reviews[0]
        subject = json.loads(row["subject"])
        assert row["mode"] == "flag" and row["raisedBy"] == "agent:research" and subject == {"type": "assignment", "id": _only(context)["id"]}, row


@then("the stream makes no wake and nothing starts the work again")
def nothing_again(context):
    assert len(context.queue.messages) == 0, [wake["wake"]["key"] for wake in _wakes(context)]


@when("a person reopens the Assignment")
def reopens(context):
    site = _site(context)
    assignments.apply_assignment_action(site, auth_claims={"sub": "ada"}, action="reopen", assignment_id=_only(context)["id"], options={}, actor_label="ada")
    row = site.rows["Assignment"][_only(context)["id"]]
    assert row["status"] == "open"


@given('the Assignment of another kind "{kind}" is in the site')
def other_kind(context, kind):
    site = _site(context)
    site.create_record("Assignment", {"id": "assignment-other-1", "assignmentTypeKey": kind, "queueKey": "research:news:exploratory", "queueStatusKey": "research:news:exploratory#open",
                                      "status": "open", "title": "Research the tides", "createdBy": "papyrus-cli", "createdAt": "2026-11-18T09:00:00Z", "updatedAt": "2026-11-18T09:00:00Z",
                                      "itemLineageId": STORY})
