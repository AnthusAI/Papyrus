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
