"""Steps for poke-in.feature and kill-switches.feature: one site with its agent policy, listener index, wake queue, run records and the real runner.

A change to a Story becomes a wake through the Item change feed's own `wakes_for`; the queue drops a key it already holds, as SQS does inside its window; delivering
runs each wake through `procedure_runner.run_procedure_request` with the gate that reads the site's policy, and a fake procedure that records which agent ran for
which Story. The newsroom's doors are the agent-policy function (`function.handle`) and the Automation page function (`automation_view.handle`); the command line
is the operation table's adapter (`papyrus agents ...`) on the operator's lane, which runs the same code over the same records.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from behave import given, step, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import agent_listeners, agent_poke_in, agent_poke_in_handlers, agent_wakes, item_change_feed, model_attachments, procedure_runner as pr, user_auth_mode  # noqa: E402
from papyrus_content.agent_definitions import release  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.agent_policy.function import PokeInServices, handle as policy_function  # noqa: E402
from papyrus_content.agent_policy.run_gate import PolicyGate  # noqa: E402
from papyrus_content.appsync_event import amplify_function_event, user_pool_identity  # noqa: E402
from papyrus_content.automation_view import handle as automation_function  # noqa: E402
from papyrus_content.images import cli as images_cli  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

TENANT, BUCKET, PUBLICATION = "alpha", "site-bucket", "mom"
ADA, EDIE = "ada@example.test", "edie@example.test"
CONSOLE = {"PERSON_ONLY_CLIENT_IDS": "console-client"}
PROCEDURES = {"announce": "announce_story", "rate": "rate_items"}
NEWSROOM, COMMAND_LINE = "in the newsroom", "on the command line"


class Clock:
    def __init__(self):
        self.moment = datetime(2026, 11, 23, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> str:
        self.moment += timedelta(seconds=1)
        return self.moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class SiteBackend(tpr.NewsroomClient):
    """The site's API: the run records (the id comes from the wake key, a second start is a duplicate), the automations and the site-document catalogue."""

    def __init__(self, table, clock):
        super().__init__()
        self.table, self.clock, self.records, self.tenant_id = table, clock, {}, TENANT
        self.automations = {agent: {"id": agent, "title": agent, "enabled": True, "procedureKey": key, "responsibility": agent} for agent, key in PROCEDURES.items()}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "procedureVersionId": "version-1"})}
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"], "requestedAt": self.clock(), "tenantId": TENANT,
                                    "summary": variables["summary"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        for field, model in (("getSiteDocumentVersion", "SiteDocumentVersion"), ("getSiteDocument", "SiteDocument")):
            if field in query:
                return {field: self.table.get(model, variables["id"])}
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
        return result

    def get_record(self, model, record_id):
        assert model == "Automation", model
        return self.automations.get(record_id)

    def runs_of(self, automation_id):
        return [row for row in self.records.values() if row.get("automationId") == automation_id]

    def list_by_index(self, index, key, limit=100, sort_condition=None, **_):
        if index != agent_poke_in.RUN_WAKES_INDEX:
            return super().list_by_index(index, key, limit)
        since = (sort_condition or {}).get("ge", "")
        return [row for row in self.runs_of(key) if row["requestedAt"] >= since]

    def iterate_newest_first(self, index, key, **_):
        assert index == agent_poke_in.RUN_WAKES_INDEX
        return iter(sorted(self.runs_of(key), key=lambda row: row["requestedAt"], reverse=True))


class Site:
    def __init__(self, context):
        self.clock = Clock()
        self.s3, self.table = FakeS3(), FakeTable()
        self.site_store = SiteStore(self.s3, BUCKET, self.table, now=self.clock)
        self.policy = AgentPolicyStore(self.site_store)
        self.backend = SiteBackend(self.table, self.clock)
        self.queue, self.sent_keys, self.delivered, self.ran = [], set(), [], []
        agent_listeners.publish(self.site_store, TENANT, release.load(None), actor="deploy", apply=True)
        self.feed_site = item_change_feed.Site(publication_id=PUBLICATION, appsync_endpoint=tpr.ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)

    def send(self, request, deduplication=None):
        key = deduplication or request["wakeKey"]
        if key in self.sent_keys:   # the queue drops a key it already holds
            return
        self.sent_keys.add(key)
        self.queue.append(request)

    def change(self, story, change, what, attributes):
        found = item_change_feed.Change(change=change, id=f"{story}-v1", lineage=story, version=f"{story}-v1", what=what, actor_kind="person", actor_label="Edie",
                                        at=self.clock(), attributes=attributes)
        index = agent_listeners.ListenerIndex(self.site_store, TENANT).document()
        for request in item_change_feed.wakes_for(found, index, self.feed_site):
            self.send(request)

    def run(self, request):
        def execute(*args, **kwargs):
            trigger = request.get("trigger") or {}
            self.ran.append((trigger.get("automationId"), (request.get("input") or {}).get("story"), request["wakeKey"]))
            return {"success": True, "output": {"summary": "done"}, "seconds": 1}

        gate = PolicyGate.for_site(self.backend, s3=self.s3, bucket=BUCKET, tenant_id=TENANT)
        pr.run_procedure_request(request, policy=gate, client=self.backend, execute=execute, seconds_available=900, environment={})

    def deliver(self):
        batch, self.queue = self.queue, []
        for request in batch:
            self.run(request)
        self.delivered = batch

    def services(self):
        return PokeInServices(agent_listeners.ListenerIndex(self.site_store, TENANT).document, agent_poke_in.RunLedger(self.backend, TENANT), self.send)

    def runs_for(self, agent, story):
        return [entry for entry in self.ran if entry[0] == agent and entry[1] == story]


def site(context) -> Site:
    return context.poke_site


@given('a site whose announce agent drafts at the rung "{rung}"')
def a_site(context, rung):
    context.poke_site = Site(context)
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)
    clock = agent_poke_in.utc_now
    agent_poke_in.utc_now = context.poke_site.clock
    context.add_cleanup(setattr, agent_poke_in, "utc_now", clock)
    context.poke_site.policy.set_rung(TENANT, Caller(kind="person", subject=ADA, is_admin=True), "announce", rung, reason="Seed")
    context.poke_answer = None


@given('the rating agent suggests at the rung "{rung}"')
def rating_rung(context, rung):
    site(context).policy.set_rung(TENANT, Caller(kind="person", subject=ADA, is_admin=True), "rate", rung, reason="Seed")


# --- the doors -------------------------------------------------------------------------------------------------------------------------------------


def newsroom_policy(context, request):
    event = {"identity": {"groups": ["admin"], "claims": {"email": ADA, "aud": "console-client"}, "username": "ada"},
             "arguments": {"input": json.dumps({"tenantId": TENANT, **request})}}
    answer = policy_function(event, site(context).policy, CONSOLE, TENANT, site(context).services())
    context.poke_answer = answer
    return answer


def newsroom_wake(context, agent, subject, reason):
    event = amplify_function_event("Mutation", "agentWake", {"input": json.dumps({"op": "agents_wake", "agent": agent, "subject": subject, "reason": reason})},
                                   user_pool_identity("edie", ["editor"], email=EDIE))
    context.poke_answer = automation_function(event, env={}, client_factory=lambda: site(context).backend, invoker=site(context).send)
    return context.poke_answer


def command_line(context, argv, *, person=ADA, actor="person"):
    """`papyrus agents <argv>` on the operator's lane: the operation table's adapter and the poke-in handlers over this site's records."""
    patches = [(user_auth_mode, "user_auth_requested", lambda: False),
               (agent_poke_in_handlers, "_site_store", lambda client: site(context).site_store),
               (agent_poke_in_handlers, "_operator_caller", lambda client, caller: Caller(kind=caller.kind, subject=person, is_admin=person == ADA)),
               (agent_wakes, "wake_sender", lambda sqs=None: site(context).send),
               (images_cli, "caller_from", lambda environ: Caller(kind=actor))]
    saved = [(owner, name, getattr(owner, name)) for owner, name, _ in patches]
    for owner, name, value in patches:
        setattr(owner, name, value)
    try:
        out = io.StringIO()
        images_cli.command(argv, group="agents", handlers=agent_poke_in_handlers.signed_in_handlers(client_factory=lambda: site(context).backend), environ={}, stdout=out)
    finally:
        for owner, name, value in saved:
            setattr(owner, name, value)
    context.poke_answer = json.loads(out.getvalue())
    return context.poke_answer


def result_of(answer):
    assert answer.get("ok"), answer
    return answer["result"]


def pause_by(context, agent, door, reason):
    if door == NEWSROOM:
        return result_of(newsroom_policy(context, {"op": "agents_pause", "agent": agent, "reason": reason}))
    assert door == COMMAND_LINE, door
    return result_of(command_line(context, ["pause", *(["--agent", agent] if agent else []), "--reason", reason]))


def resume_by(context, agent, door, reason):
    if door == NEWSROOM:
        result = result_of(newsroom_policy(context, {"op": "agents_resume", "agent": agent, "reason": reason}))
    else:
        assert door == COMMAND_LINE, door
        result = result_of(command_line(context, ["resume", *(["--agent", agent] if agent else []), "--reason", reason]))
    context.poke_resume = result
    return result


@step('Ada paused "{agent}" in the newsroom because "{reason}"')
def ada_paused(context, agent, reason):
    context.poke_pause = pause_by(context, agent, NEWSROOM, reason)


@step('Ada pauses "{agent}" {door} because "{reason}"')
def ada_pauses(context, agent, door, reason):
    context.poke_pause = pause_by(context, agent, door, reason)


@step('Ada paused the whole site in the newsroom because "{reason}"')
def ada_paused_site(context, reason):
    context.poke_pause = pause_by(context, None, NEWSROOM, reason)


@step('Ada resumes "{agent}" {door} because "{reason}"')
def ada_resumes(context, agent, door, reason):
    resume_by(context, agent, door, reason)


@step('Ada resumes the whole site in the newsroom because "{reason}"')
def ada_resumes_site(context, reason):
    resume_by(context, None, NEWSROOM, reason)


@step('Edie wakes "{agent}" now for "{subject}" {door} because "{reason}"')
def edie_wakes(context, agent, subject, door, reason):
    if door == NEWSROOM:
        newsroom_wake(context, agent, subject, reason)
    else:
        assert door == COMMAND_LINE, door
        command_line(context, ["wake", "--agent", agent, "--subject", subject, "--reason", reason], person=EDIE)


@when('an agent asks the command line to pause "{agent}" because "{reason}"')
def agent_pauses(context, agent, reason):
    context.poke_versions = site(context).policy.read(TENANT).version
    command_line(context, ["pause", "--agent", agent, "--reason", reason], actor="agent")


@when('an agent asks the command line to wake "{agent}" now for "{subject}" because "{reason}"')
def agent_wakes_now(context, agent, subject, reason):
    command_line(context, ["wake", "--agent", agent, "--subject", subject, "--reason", reason], actor="agent")


# --- changes and deliveries ------------------------------------------------------------------------------------------------------------------------


@step('Story "{story}" is rated {stars:d} stars')
def rated(context, story, stars):
    site(context).change(story, "rated", f"rated:{stars}", {"stage": "published", "stars": stars})


@step('Story "{story}" goes live')
def goes_live(context, story):
    site(context).change(story, "stage_entered", "stage:published", {"stage": "published"})


@step("the rating agent's daily timer fires")
def timer_fires(context):
    site(context).send({**tpr.REQUEST, "procedureKey": PROCEDURES["rate"], "wakeKey": "rate|schedule|2026-11-23T08:30:00Z", "publicationId": PUBLICATION,
                        "actorLabel": "automation:rate", "input": {}, "tenantId": TENANT, "siteBucket": BUCKET,
                        "trigger": {"kind": "schedule", "automationId": "rate", "summary": "Agent rate woke on its daily schedule"}})


@step("the site's wake queue is delivered")
def delivered(context):
    site(context).deliver()


@step("the same wake is delivered again")
@step("the same wakes are delivered again")
def delivered_again(context):
    for request in site(context).delivered:
        site(context).run(request)


# --- what happened ---------------------------------------------------------------------------------------------------------------------------------


@then("the announce agent drafted nothing")
def drafted_nothing(context):
    assert [entry for entry in site(context).ran if entry[0] == "announce"] == [], site(context).ran


@then('the announce agent drafted for "{story}" {count:d} time')
@then('the announce agent drafted for "{story}" {count:d} times')
def drafted_for(context, story, count):
    assert len(site(context).runs_for("announce", story)) == count, site(context).ran


@then('the rating agent ran for "{story}" {count:d} time')
@then('the rating agent ran for "{story}" {count:d} times')
def rating_ran(context, story, count):
    assert len(site(context).runs_for("rate", story)) == count, site(context).ran


@then("the rating agent's skipped tick did not run")
def tick_not_run(context):
    assert not any("|schedule|" in entry[2] for entry in site(context).ran), site(context).ran
    assert not any("|schedule|" in again["repeats"] for again in context.poke_resume["caughtUp"])


@then('the stopped run for "{story}" says "{words}"')
def stopped_run_says(context, story, words):
    stopped = [row for row in site(context).backend.records.values() if row.get("subjectId") == story and row.get("outcomeReason") == "paused"]
    assert stopped and all(row["resultSummary"] == words and row["outcome"] == "nothing" for row in stopped), stopped
    assert all(json.loads(row["wake"])["trigger"]["story"] == story for row in stopped), "a stopped run keeps its wake"


@then('the newest run for "{story}" says it was woken by "{person}" because "{reason}"')
def woken_by(context, story, person, reason):
    runs = sorted((row for row in site(context).backend.runs_of("announce") if row.get("subjectId") == story), key=lambda row: row["requestedAt"])
    newest = runs[-1]
    assert newest["summary"].startswith(f"{person} woke it now ({reason})"), newest["summary"]
    assert json.loads(newest["wake"])["trigger"]["poke"]["by"] == person


@then('the pauses show "{agent}" paused by "{person}" because "{reason}"')
def pauses_paused(context, agent, person, reason):
    shown = result_of(newsroom_policy(context, {"op": "agents_pauses"}))["agents"][agent]
    assert (shown["paused"], shown["pausedBy"], shown["reason"]) == (True, person, reason) and shown["pausedAt"], shown


@then('the pauses show "{agent}" running')
def pauses_running(context, agent):
    assert result_of(newsroom_policy(context, {"op": "agents_pauses"}))["agents"][agent] == {"paused": False}


@then('the policy version the pause made records "{person}" and the reason "{reason}"')
def pause_version(context, person, reason):
    record = site(context).policy.version_record(TENANT, context.poke_pause["policyVersion"]["after"])
    assert (record["by"], record["reason"]) == (person, reason) and record["at"], record


@then('the policy version the resume made records "{person}" and the reason "{reason}"')
def resume_version(context, person, reason):
    record = site(context).policy.version_record(TENANT, context.poke_resume["policyVersion"]["after"])
    assert (record["by"], record["reason"]) == (person, reason) and record["at"], record


@then('the wake is refused as not found, saying "{words}"')
def wake_not_found(context, words):
    answer = context.poke_answer
    assert answer["ok"] is False and answer["error"] == "not_found" and words in answer["message"], answer


@then("the site's wake queue is empty")
def queue_empty(context):
    assert site(context).queue == [], site(context).queue


@then('the command line refuses it as "{code}" and the policy is unchanged')
def cli_refused_policy(context, code):
    assert context.poke_answer["ok"] is False and context.poke_answer["error"]["code"] == code, context.poke_answer
    assert site(context).policy.read(TENANT).version == context.poke_versions


@then('the command line refuses it as "{code}" and the site\'s wake queue is empty')
def cli_refused_wake(context, code):
    assert context.poke_answer["ok"] is False and context.poke_answer["error"]["code"] == code, context.poke_answer
    assert site(context).queue == []


@then('the resume answered with policy version {version:d} and one caught-up wake for "{story}"')
def resume_answer(context, version, story):
    result = context.poke_resume
    assert result["policyVersion"]["after"] == version, result
    assert [entry["subject"] for entry in result["caughtUp"]] == [story], result


@then("the resume caught up nothing")
def caught_up_nothing(context):
    assert context.poke_resume["caughtUp"] == [], context.poke_resume


@then('the resume caught up nothing and says "{words}"')
def caught_up_nothing_saying(context, words):
    assert context.poke_resume["caughtUp"] == [] and any(words in note for note in context.poke_resume["notes"]), context.poke_resume


# --- the requests against the real schema ----------------------------------------------------------------------------------------------------------


@when("the poke-in requests are built against a recording site API")
def recorded_requests(context):
    from papyrus_content.cloud_procedures import update_cloud_procedure_run_record
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    class RecordingClient(PapyrusGraphQLAuthoringClient):
        def __init__(self):
            super().__init__(endpoint="https://example.test/graphql", tenant_id=TENANT)
            self.requests = []

        def graphql(self, query, variables=None):
            self.requests.append({"query": query, "variables": variables or {}})
            if "updateProcedureRun" in query:
                return {"updateProcedureRun": {"id": variables["input"]["id"]}}
            if "agentPolicyChange" in query or "agentWake" in query:
                return {"agentPolicyChange": json.dumps({"ok": True, "result": {}}), "agentWake": json.dumps({"ok": True, "result": {}})}
            return {"listProcedureRunsByAutomationAndRequestedAt": {"items": [], "nextToken": None}}

    client = RecordingClient()
    ledger = agent_poke_in.RunLedger(client, TENANT)
    ledger.runs_since("announce", "2026-11-23T10:00:00Z")
    list(ledger.newest_first("announce"))
    wake = {"wakeKey": "announce|s1|s1-v1|rated:4", "trigger": {"kind": "event", "automationId": "announce", "summary": "woke"}, "input": {"story": "s1"}}
    update_cloud_procedure_run_record(client, {"id": "run-1", "runStatus": "completed", "outcome": "nothing", "outcomeReason": "paused", **pr.kept_wake(wake)})
    client.graphql(agent_poke_in_handlers.AGENT_POLICY_CHANGE, {"input": json.dumps({"op": "agents_pause", "reason": "r"})})
    client.graphql(agent_poke_in_handlers.AGENT_WAKE, {"input": json.dumps({"op": "agents_wake", "agent": "announce", "subject": "s1", "reason": "r"})})
    context.poke_requests = client.requests


@then("every poke-in request is accepted by the GraphQL schema Amplify generates from the data schema")
def poke_requests_match_schema(context):
    import subprocess
    import tempfile

    repo_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as folder:
        operations = Path(folder) / "operations.json"
        operations.write_text(json.dumps(context.poke_requests))
        run = subprocess.run(["npx", "tsx", "scripts/graphql-operations-contract.mts", str(operations)], cwd=repo_root, capture_output=True, text=True)
    verdicts = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    assert len(verdicts) == len(context.poke_requests), run.stderr[-2000:] or run.stdout[-2000:]
    rejected = [verdict for verdict in verdicts if verdict["problems"]]
    assert not rejected, "the schema refuses: " + json.dumps(rejected, indent=2)
