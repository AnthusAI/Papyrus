"""Only a person signed in to the console changes the agent policy (features_backend/agents/agent-policy-change.feature, PPY-1ea28b)."""
from __future__ import annotations

import io
import json

from behave import given, then, when

from papyrus_content.agent_definitions import cli as agents_cli
from papyrus_content.agent_policy import AgentPolicyStore, PolicyError
from papyrus_content.agent_policy.function import handle
from papyrus_content.agent_policy.remote import RemoteAgentPolicyStore
from papyrus_content.images.handlers import Caller
from papyrus_content.site_store import SiteStore

TENANT, BUCKET, CONSOLE_CLIENT, OTHER_CLIENT = "alpha", "site-bucket", "console-client", "other-client"
SAVED_AT = "2026-11-22T09:00:00Z"
# What the CLI believes about its caller: the server decides by the token, so both callers look like a person from here.
SIGNED_IN_ADMIN = Caller(kind="person", subject="ada", is_admin=True)


class SharedObjects:
    """The site's bucket and catalogue, seen through two credentials: the function's role writes; the signed-in admin's only reads (GetObject only)."""

    def __init__(self):
        self.objects, self.rows, self.writers = {}, {}, []


class ObjectsAs:
    def __init__(self, shared: SharedObjects, writer: str | None):
        self.shared, self.writer = shared, writer

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.writer is None:
            raise PermissionError(f"AccessDenied: s3:PutObject on {Key}")
        self.shared.objects[Key] = Body
        self.shared.writers.append(("object", Key, self.writer))

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.shared.objects[Key])}


class CatalogueAs:
    def __init__(self, shared: SharedObjects, writer: str | None):
        self.shared, self.writer = shared, writer

    def _may_write(self, model, row_id):
        if self.writer is None:
            raise PermissionError(f"Unauthorized: write of {model} {row_id}")
        self.shared.writers.append(("row", row_id, self.writer))

    def get(self, model, row_id):
        row = self.shared.rows.get((model, row_id))
        return dict(row) if row else None

    def create(self, model, row):
        if (model, row["id"]) in self.shared.rows:
            raise KeyError(row["id"])
        self._may_write(model, row["id"])
        self.shared.rows[(model, row["id"])] = dict(row)

    def update_if(self, model, row_id, changes, expected):
        row = self.shared.rows[(model, row_id)]
        if any(row.get(name) != value for name, value in expected.items()):
            return False
        self._may_write(model, row_id)
        row.update(changes)
        return True

    def latest_version(self, document_id):
        versions = [row for (model, _), row in self.shared.rows.items() if model == "SiteDocumentVersion" and row["documentId"] == document_id]
        return max(versions, key=lambda row: row["version"], default=None)


class SiteClient:
    """The site's API as set-budget reads it: the tenant, and no run waiting for the budget cycle."""

    tenant_id = TENANT

    def list_by_index(self, index, value):
        return []


def function_store(context) -> AgentPolicyStore:
    return AgentPolicyStore(SiteStore(ObjectsAs(context.shared, "agent-policy function"), BUCKET, CatalogueAs(context.shared, "agent-policy function"),
                                      now=lambda: SAVED_AT))


def signed_in_store(context, token_client: str) -> RemoteAgentPolicyStore:
    """What `papyrus agents ...` uses on the signed-in lane: reads with the admin's own (read-only) credentials, sends every change to the function."""

    def send(request):
        event = {"identity": {"groups": ["admin"], "claims": {"email": "ada@example.test", "aud": token_client}, "username": "ada"},
                 "arguments": {"input": json.dumps(request)}}
        return handle(event, function_store(context), context.function_environment, TENANT)

    return RemoteAgentPolicyStore(SiteStore(ObjectsAs(context.shared, None), BUCKET, CatalogueAs(context.shared, None)), send)


def client_of(who: str) -> str:
    return CONSOLE_CLIENT if who == "console" else OTHER_CLIENT


@given('a site whose agent policy holds "{agent}" at the rung "{rung}" and a budget of {amount:d} dollars a week, changed only through the policy function')
def site_with_policy(context, agent, rung, amount):
    context.shared = SharedObjects()
    context.function_environment = {"PERSON_ONLY_CLIENT_IDS": CONSOLE_CLIENT}
    function_store(context).change(TENANT, SIGNED_IN_ADMIN, "Start", lambda document: (document["agents"].__setitem__(agent, {"rung": rung}),
                                                                      document["site"].__setitem__("budget", {"amountUsd": amount, "period": "week"})))
    context.shared.writers.clear()


@given("the site's stack names no person-only app client")
def no_person_client(context):
    context.function_environment = {}


def set_rung(context, who, agent, rung, reason):
    context.refusal = None
    try:
        context.saved = signed_in_store(context, client_of(who)).set_rung(TENANT, SIGNED_IN_ADMIN, agent, rung, reason=reason)
    except PolicyError as error:
        context.refusal = error


@when('ada, an admin signed in on the console\'s app client, sets "{agent}" to the rung "{rung}" because "{reason}"')
def person_sets_rung(context, agent, rung, reason):
    set_rung(context, "console", agent, rung, reason)


@when('an agent holding an admin token from another app client sets "{agent}" to the rung "{rung}" because "{reason}"')
def agent_sets_rung(context, agent, rung, reason):
    set_rung(context, "other", agent, rung, reason)


def set_budget(context, who, amount, reason):
    out = io.StringIO()
    context.sent_wakes = []
    context.exit_code = agents_cli.set_budget_command(
        ["--amount", str(amount), "--period", "week", "--reason", reason, "--apply"], out, client_factory=SiteClient,
        policy_factory=lambda client: signed_in_store(context, client_of(who)), caller_factory=lambda client, caller: SIGNED_IN_ADMIN,
        sender_factory=lambda: lambda wake, deduplication: context.sent_wakes.append(wake))
    context.envelope = json.loads(out.getvalue())


@when('ada, an admin signed in on the console\'s app client, runs set-budget for {amount:d} dollars a week because "{reason}" and applies it')
def person_sets_budget(context, amount, reason):
    set_budget(context, "console", amount, reason)


@when('an agent holding an admin token from another app client runs set-budget for {amount:d} dollars a week because "{reason}" and applies it')
def agent_sets_budget(context, amount, reason):
    set_budget(context, "other", amount, reason)


def live_policy(context):
    return function_store(context).read(TENANT)


@then('the policy function saved version {version:d} with "{agent}" at the rung "{rung}"')
def saved_rung(context, version, agent, rung):
    assert context.refusal is None, context.refusal
    state = live_policy(context)
    assert (context.saved.version, state.version, state.document["agents"][agent]["rung"]) == (version, version, rung), (context.saved, state)


@then('version {version:d} of the agent policy records "{by}", the time "{at}" and the reason "{reason}"')
def version_record(context, version, by, at, reason):
    record = function_store(context).version_record(TENANT, version)
    assert (record["by"], record["at"], record["reason"]) == (by, at, reason), record


@then('the policy function refused the change as "{code}"')
def refused(context, code):
    assert context.refusal is not None and context.refusal.code == code, context.refusal


@then('the agent policy is still version {version:d} with "{agent}" at the rung "{rung}"')
def unchanged_rung(context, version, agent, rung):
    state = live_policy(context)
    assert (state.version, state.document["agents"][agent]["rung"]) == (version, rung), state


@then("the budget command succeeded and saved version {version:d}")
def budget_saved(context, version):
    assert context.exit_code == 0, context.envelope
    assert context.envelope["result"]["applied"] is True and context.envelope["result"]["policyVersion"]["after"] == version, context.envelope


@then('the budget command was refused as "{code}"')
def budget_refused(context, code):
    assert context.exit_code != 0 and context.envelope["error"]["code"] == code, context.envelope
    assert context.sent_wakes == []


@then("the agent policy holds a budget of {amount:d} dollars a week at version {version:d}")
def budget_held(context, amount, version):
    state = live_policy(context)
    assert (state.version, state.document["site"]["budget"]) == (version, {"amountUsd": amount, "period": "week"}), state


@then("the signed-in command's own credentials wrote no policy object and no catalogue row")
def nothing_written_by_the_command(context):
    assert all(writer == "agent-policy function" for _, _, writer in context.shared.writers), context.shared.writers


@then("every policy object was written by the policy function")
def objects_by_function(context):
    objects = [entry for entry in context.shared.writers if entry[0] == "object"]
    assert objects and all(key.startswith(f"tenants/{TENANT}/site/agents/") and writer == "agent-policy function" for _, key, writer in objects), objects


# --- the console's door to the announcement review (PPY-e2829f) ---------------------------------------------------------------------------------------------

X_STORY_POSTS = {"channel": "x", "kind": "story_published"}


def console_review_request(context, token_client: str, request: dict) -> dict:
    """What the Announcements settings page sends: an agentPolicyChange with the review request and no tenant (the function takes the caller's own)."""
    event = {"identity": {"groups": ["admin"], "claims": {"email": "ada@example.test", "aud": token_client}, "username": "ada"},
             "arguments": {"input": json.dumps(request)}}
    return handle(event, function_store(context), context.function_environment, TENANT)


def set_review(context, token_client, approval, reason, **extra):
    context.review_answer = console_review_request(context, token_client, {"op": "announcements_review_set", "approval": approval, **X_STORY_POSTS, "reason": reason, **extra})


@when('ada, an admin signed in on the console\'s app client, sets the review of X story posts to "{approval}" because "{reason}"')
def person_sets_review(context, approval, reason):
    set_review(context, CONSOLE_CLIENT, approval, reason)


@when('an agent holding an admin token from another app client sets the review of X story posts to "{approval}" because "{reason}"')
def other_client_sets_review(context, approval, reason):
    set_review(context, OTHER_CLIENT, approval, reason)


@when('an agent declaring itself on the console\'s app client sets the review of X story posts to "{approval}" because "{reason}"')
def declared_agent_sets_review(context, approval, reason):
    set_review(context, CONSOLE_CLIENT, approval, reason, actorKind="agent")


@then('the policy function saved the review as version {version:d}, with "{agent}" at the rung "{rung}" for the channel "{channel}" and the kind "{kind}"')
def saved_override(context, version, agent, rung, channel, kind):
    answer = context.review_answer
    assert answer["ok"] is True and answer["result"]["policyVersion"] == version, answer
    state = live_policy(context)
    overrides = state.document["agents"][agent].get("overrides", [])
    assert state.version == version and any(item.get("channel") == channel and item.get("kind") == kind and item["rung"] == rung for item in overrides), state.document


@then('ada, reading the review of X story posts on the console\'s app client, sees "{approval}"')
def reads_review(context, approval):
    answer = console_review_request(context, CONSOLE_CLIENT, {"op": "announcements_review_show", **X_STORY_POSTS})
    assert answer["ok"] is True and answer["result"]["chosen"]["approval"] == approval, answer


@then('the policy function refused the review as "{code}"')
def review_refused(context, code):
    assert context.review_answer.get("ok") is False and context.review_answer["error"] == code, context.review_answer


# --- the site documents' catalogue: the admin group reads it and writes none of it ------------------------------------------------------------------------

SCHEMA_FILES = ("amplify/data/schema.ts", "amplify/data/resource.ts")
WRITE_OPERATIONS = ("create", "update", "delete")


def authorization_rules(source: str, model: str) -> list[str]:
    """The ``allow.*`` rules of one model's ``.authorization((allow) => [...])``, as written."""
    import re

    start = re.search(rf"^\s+{model}: ", source, re.MULTILINE)
    assert start, f"{model} is not a model of the schema"
    block = source[start.end():]
    opening = block.index(".authorization((allow) => [")
    closing = re.compile(r"^\s*\]\),", re.MULTILINE).search(block, opening).start()   # the line that closes the list, not a rule's own ``.to([...]),``
    rules = [line.strip().rstrip(",") for line in block[opening:closing].splitlines() if line.strip().startswith("allow.")]
    assert rules, f"{model} has no authorization rules"
    return rules


@when('the data API\'s rules for "{first}" and "{second}" are read from the deployed schema and the typed schema')
def read_catalogue_rules(context, first, second):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    context.catalogue_rules = {(path, model): authorization_rules((root / path).read_text(encoding="utf-8"), model)
                               for path in SCHEMA_FILES for model in (first, second)}


@then("in both schemas the admin group may only read each of the two models")
def admin_group_reads_only(context):
    for where, rules in context.catalogue_rules.items():
        admin = [rule for rule in rules if rule.startswith("allow.group(adminGroup)")]
        assert admin == ['allow.group(adminGroup).to(["read"])'], (where, rules)


@then("no rule of either model in either schema lets a group or an owner create, update or delete a row")
def no_rule_writes(context):
    for where, rules in context.catalogue_rules.items():
        for rule in rules:
            assert rule.endswith('.to(["read"])') and not any(operation in rule for operation in WRITE_OPERATIONS), (where, rule)


class ListenerSite:
    tenant_id = TENANT


def run_listeners(context, lane: str, *, client_factory, site_store_factory) -> None:
    import contextlib
    import os
    import tempfile
    import unittest.mock

    from papyrus_content.agent_definitions import definition

    out = io.StringIO()
    with tempfile.TemporaryDirectory() as root, unittest.mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": lane}), contextlib.redirect_stdout(io.StringIO()):
        context.listeners_code = agents_cli.listeners_command(["--core", str(definition.CORE_DIRECTORY), "--root", root], out,
                                                              client_factory=client_factory, site_store_factory=site_store_factory)
    context.listeners_answer = json.loads(out.getvalue())


@when('ada, signed in to the site, runs "papyrus agents listeners" to write the listener index')
def person_writes_listeners(context):
    context.listeners_reads = []

    def client():
        context.listeners_reads.append("site API")
        return ListenerSite()

    def store(client):
        context.listeners_reads.append("site store")
        return SiteStore(ObjectsAs(context.shared, None), BUCKET, CatalogueAs(context.shared, None))

    run_listeners(context, "user", client_factory=client, site_store_factory=store)


@then('the listeners command was refused as "{code}", naming the deploy\'s own role')
def listeners_refused(context, code):
    error = context.listeners_answer.get("error") or {}
    assert context.listeners_code == 2 and error.get("code") == code, context.listeners_answer
    assert "PAPYRUS_GRAPHQL_AUTH=iam papyrus agents listeners" in error["message"], error


@then("the command read no site document and wrote no object and no catalogue row")
def listeners_touched_nothing(context):
    assert context.listeners_reads == [] and context.shared.writers == [], (context.listeners_reads, context.shared.writers)


@when('the deploy runs "papyrus agents listeners" as its own role')
def deploy_writes_listeners(context):
    role = "deploy role"
    run_listeners(context, "iam", client_factory=ListenerSite,
                  site_store_factory=lambda client: SiteStore(ObjectsAs(context.shared, role), BUCKET, CatalogueAs(context.shared, role), now=lambda: SAVED_AT))


@then("the listener index is at version {version:d}, and every object and catalogue row of it was written by the deploy's role")
def listeners_written_by_deploy(context, version):
    assert context.listeners_code == 0 and context.listeners_answer["result"]["index"] == {"action": "created", "version": version, "applied": True}, context.listeners_answer
    reader = SiteStore(ObjectsAs(context.shared, None), BUCKET, CatalogueAs(context.shared, None))
    assert reader.current_version(TENANT, "listeners") == version
    writes = context.shared.writers
    of_the_index = {"object": f"tenants/{TENANT}/site/listeners/", "row": f"{TENANT}#listeners"}
    assert {kind for kind, _, _ in writes} == {"object", "row"}, writes
    assert all(key.startswith(of_the_index[kind]) and writer == "deploy role" for kind, key, writer in writes), writes


# --- the newsroom's rung board (console_rungs.py) ---------------------------------------------------------------------------------------

def _registered_row(definition_id: str, *, retired: bool = False) -> dict:
    from papyrus_content.agent_definitions.definition import core_definition

    data = dict(core_definition(definition_id)) if definition_id in ("announce", "rate") else {**core_definition("rate"), "id": definition_id, "responsibility": definition_id}
    return {"id": f"automation-{definition_id}", "definition": json.dumps(data), "definitionRetiredAt": "2026-11-01T00:00:00Z" if retired else None}


@given('the site\'s registered agents are "{first}" and "{second}", and a retired "{retired}"')
def registered_agents(context, first, second, retired):
    context.registered_rows = [_registered_row(first), _registered_row(second), _registered_row(retired, retired=True)]


def rung_board_request(context, who: str, request: dict) -> dict:
    from papyrus_content.agent_policy.console_rungs import registered_definitions
    from papyrus_content.agent_policy.function import PokeInServices

    event = {"identity": {"groups": ["admin"], "claims": {"email": "ada@example.test", "aud": client_of(who)}, "username": "ada"},
             "arguments": {"input": json.dumps(request)}}
    services = PokeInServices(None, None, None, definitions=lambda: registered_definitions(context.registered_rows))
    context.board_answer = handle(event, function_store(context), context.function_environment, TENANT, services)
    return context.board_answer


@when("ada, an admin signed in on the console's app client, opens the rung board")
def open_board(context):
    answer = rung_board_request(context, "console", {"op": "agents_rungs"})
    assert answer["ok"] is True, answer
    context.board = {agent["id"]: agent for agent in answer["result"]["agents"]}


@when('ada, an admin signed in on the console\'s app client, sets "{agent}" to "{rung}" on the rung board because "{reason}"')
def board_sets(context, agent, rung, reason):
    rung_board_request(context, "console", {"op": "agents_set_rung", "agent": agent, "rung": rung, "reason": reason})


@when('ada, an admin signed in on the console\'s app client, sets "{agent}" to "{rung}" on the rung board because ""')
def board_sets_without_reason(context, agent, rung):
    rung_board_request(context, "console", {"op": "agents_set_rung", "agent": agent, "rung": rung, "reason": ""})


@when('an agent holding an admin token from another app client sets "{agent}" to "{rung}" on the rung board because "{reason}"')
def board_sets_other_client(context, agent, rung, reason):
    rung_board_request(context, "other", {"op": "agents_set_rung", "agent": agent, "rung": rung, "reason": reason})


@when('an agent on the console\'s app client declares itself and sets "{agent}" to "{rung}" on the rung board because "{reason}"')
def board_sets_declared_agent(context, agent, rung, reason):
    rung_board_request(context, "console", {"op": "agents_set_rung", "agent": agent, "rung": rung, "reason": reason, "actorKind": "agent"})


@then('the board lists the agents "{first}" and "{second}"')
def board_lists(context, first, second):
    assert sorted(context.board) == [first, second], sorted(context.board)


@then('the board shows "{agent}" at the rung "{rung}", going no higher than "{ceiling}", with the choices "{choices}"')
def board_shows_full(context, agent, rung, ceiling, choices):
    shown = context.board[agent]
    assert (shown["rung"], shown["ceiling"], ", ".join(shown["choices"])) == (rung, ceiling, choices), shown


@then('the board shows "{agent}" at the rung "{rung}"')
def board_shows(context, agent, rung):
    assert context.board[agent]["rung"] == rung, context.board[agent]


@then('the rung board change succeeded and saved version {version:d} with "{agent}" at the rung "{rung}"')
def board_saved(context, version, agent, rung):
    answer = context.board_answer
    assert answer["ok"] is True, answer
    result = answer["result"]
    assert (result["applied"], result["after"]["policyVersion"], result["after"]["entry"]["rung"]) == (True, version, rung), result
    assert next(item for item in result["board"]["agents"] if item["id"] == agent)["rung"] == rung, result["board"]
    state = live_policy(context)
    assert (state.version, state.document["agents"][agent]["rung"]) == (version, rung), state


@then('the rung board refused the change as "{code}", saying "{words}"')
def board_refused(context, code, words):
    answer = context.board_answer
    assert answer["ok"] is False and answer["error"] == code and words in answer["message"], answer


@given('an automation row the deploy registered from the "{definition_id}" definition, never adopted')
def step_registered_unadopted_automation(context, definition_id):
    context.automation_row = {"id": definition_id, "trigger": json.dumps({"kind": "schedule", "config": {}}), "definitionId": definition_id,
                              "definition": json.dumps({"id": definition_id, "responsibility": definition_id, "operations": {"ratings_suggest": "propose"}})}


@given('an automation row the deploy registered from the "{definition_id}" definition, retired since "{retired_at}"')
def step_registered_retired_automation(context, definition_id, retired_at):
    step_registered_unadopted_automation(context, definition_id)
    context.automation_row["definitionRetiredAt"] = retired_at


@then('the Automation page reads it with the responsibility "{responsibility}"')
def step_automation_page_responsibility(context, responsibility):
    from papyrus_content.automations import read_record
    assert read_record(context.automation_row)["responsibility"] == responsibility


@then("the Automation page reads it with no responsibility")
def step_automation_page_no_responsibility(context):
    from papyrus_content.automations import read_record
    assert read_record(context.automation_row)["responsibility"] is None
