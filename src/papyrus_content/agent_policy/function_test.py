from __future__ import annotations

import json

from papyrus_content.agent_policy import AgentPolicyStore
from papyrus_content.agent_policy.function import handle
from papyrus_content.agent_policy.remote import RemoteAgentPolicyStore
from papyrus_content.site_store import SiteStore

ENVIRONMENT = {"PERSON_ONLY_CLIENT_IDS": "console-client"}


class Bucket:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objects[Key])}


class Catalogue:
    def __init__(self):
        self.rows = {}

    def get(self, model, row_id):
        return self.rows.get((model, row_id))

    def create(self, model, row):
        if (model, row["id"]) in self.rows:
            raise KeyError(row["id"])
        self.rows[(model, row["id"])] = dict(row)

    def update_if(self, model, row_id, changes, expected):
        row = self.rows[(model, row_id)]
        if any(row.get(name) != value for name, value in expected.items()):
            return False
        row.update(changes)
        return True

    def latest_version(self, document_id):
        versions = [row for (model, _), row in self.rows.items() if model == "SiteDocumentVersion" and row["documentId"] == document_id]
        return max(versions, key=lambda row: row["version"], default=None)


def store():
    return AgentPolicyStore(SiteStore(Bucket(), "bucket", Catalogue()))


def event(request, *, groups=("admin",), client="console-client"):
    return {"identity": {"groups": list(groups), "claims": {"email": "ryan@example.test", "aud": client}, "username": "ryan"},
            "arguments": {"input": json.dumps({"tenantId": "alpha", **request})}}


RAISE = {"op": "set_rung", "responsibility": "improve", "rung": "prepare", "reason": "start preparing"}


def test_an_admin_on_a_person_client_changes_the_policy_and_the_version_is_theirs():
    policy = store()
    answer = handle(event(RAISE), policy, ENVIRONMENT, "alpha")
    assert answer["ok"] is True and answer["version"] == 1 and answer["document"]["agents"]["improve"]["rung"] == "prepare"
    assert policy.read("alpha").document["agents"]["improve"]["rung"] == "prepare"
    assert policy.version_record("alpha", 1)["by"] == "ryan@example.test"


def test_a_credential_from_another_client_changes_nothing():
    policy = store()
    answer = handle(event(RAISE, client="cli-client"), policy, ENVIRONMENT, "alpha")
    assert answer["error"] == "human_required" and policy.read("alpha").version == 0


def test_with_no_person_client_configured_nobody_changes_the_policy():
    policy = store()
    assert handle(event(RAISE), policy, {}, "alpha")["error"] == "human_required"
    assert policy.read("alpha").version == 0


def test_an_editor_cannot_change_the_policy():
    assert handle(event(RAISE, groups=("editor",)), store(), ENVIRONMENT, "alpha")["error"] == "not_authorized"


def test_another_sites_tenant_is_refused():
    other = {"identity": event(RAISE)["identity"], "arguments": {"input": json.dumps({**RAISE, "tenantId": "beta"})}}
    assert handle(other, store(), ENVIRONMENT, "alpha")["error"] == "not_authorized"


def test_publish_auto_is_refused_while_the_floor_stands():
    policy = store()
    answer = handle(event({**RAISE, "rung": "publish_auto"}), policy, ENVIRONMENT, "alpha")
    assert answer["error"] == "constraint_conflict" and policy.read("alpha").version == 0


def test_an_unknown_operation_and_a_missing_reason_are_refused():
    assert handle(event({"op": "delete_everything", "reason": "x"}), store(), ENVIRONMENT, "alpha")["error"] == "invalid_input"
    assert handle(event({**RAISE, "reason": " "}), store(), ENVIRONMENT, "alpha")["error"] == "invalid_input"


def test_every_change_the_local_store_makes_can_be_sent_through_the_function():
    policy = store()

    def send(request):
        return handle({"identity": event({})["identity"], "arguments": {"input": json.dumps(request)}}, policy, ENVIRONMENT, "alpha")

    remote = RemoteAgentPolicyStore(policy._store, send)
    from papyrus_content.images.handlers import Caller

    person = Caller(kind="person", is_admin=True, subject="ryan")
    assert remote.set_rung("alpha", person, "improve", "prepare", reason="r").version == 1
    assert remote.set_rung("alpha", person, "improve", "observe", reason="r", scope={"list": "daily"}).version == 2
    assert remote.remove_override("alpha", person, "improve", {"list": "daily"}, reason="r").version == 3
    assert remote.pause("alpha", person, reason="holiday").version == 4
    assert remote.resume("alpha", person, reason="back").version == 5
    assert remote.set_value("alpha", person, "budget", {"amountUsd": 5, "period": "week"}, reason="r").version == 6
    assert policy.read("alpha").document["site"]["budget"] == {"amountUsd": 5, "period": "week"}


def test_a_refusal_from_the_function_reaches_the_caller_as_a_policy_error():
    from papyrus_content.agent_policy import PolicyError
    from papyrus_content.images.handlers import Caller

    remote = RemoteAgentPolicyStore(store()._store, lambda request: {"ok": False, "error": "human_required", "message": "Only a person."})
    try:
        remote.set_rung("alpha", Caller(kind="person", is_admin=True), "improve", "prepare", reason="r")
    except PolicyError as error:
        assert error.code == "human_required"
        return
    raise AssertionError("a refused change was accepted")


def test_a_budget_from_another_client_changes_nothing_and_a_persons_is_recorded():
    budget = {"op": "set_value", "field": "budget", "value": {"amountUsd": 50, "period": "week"}, "reason": "launch week"}
    policy = store()
    assert handle(event(budget, client="cli-client"), policy, ENVIRONMENT, "alpha")["error"] == "human_required"
    assert policy.read("alpha").version == 0
    answer = handle(event(budget), policy, ENVIRONMENT, "alpha")
    assert answer["ok"] is True and answer["document"]["site"]["budget"] == {"amountUsd": 50, "period": "week"}
    record = policy.version_record("alpha", 1)
    assert (record["by"], record["reason"]) == ("ryan@example.test", "launch week") and record["at"]


def test_the_signed_in_store_makes_no_free_form_write_of_its_own():
    from papyrus_content.agent_policy import PolicyError
    from papyrus_content.images.handlers import Caller

    policy = store()
    remote = RemoteAgentPolicyStore(policy._store, lambda request: {"ok": True, "version": 1, "document": {}})
    try:
        remote.change("alpha", Caller(kind="person", is_admin=True), "r", lambda document: document["site"].update(budget={"amountUsd": 9, "period": "day"}))
    except PolicyError:
        assert policy.read("alpha").version == 0
        return
    raise AssertionError("the signed-in store wrote the policy itself")


def test_the_cli_sends_policy_changes_to_the_function_on_the_signed_in_lane(monkeypatch):
    from papyrus_content.agent_definitions import cli
    from papyrus_content import user_auth_mode

    class Client:
        sent = []

        def graphql(self, query, variables):
            self.sent.append((query, json.loads(variables["input"])))
            return {"agentPolicyChange": json.dumps({"ok": True, "version": 1, "document": {"schemaVersion": 1, "site": {}, "agents": {}}})}

    monkeypatch.setattr(cli, "_site_store_for", lambda client: store()._store)
    monkeypatch.setattr(user_auth_mode, "user_auth_requested", lambda: True)
    policy = cli._policy_store_for_site(Client())
    assert isinstance(policy, RemoteAgentPolicyStore)
    from papyrus_content.images.handlers import Caller

    policy.set_value("alpha", Caller(kind="person", is_admin=True), "budget", {"amountUsd": 5, "period": "week"}, reason="r")
    (query, request), = Client.sent
    assert "agentPolicyChange" in query and request["op"] == "set_value" and request["field"] == "budget"
    monkeypatch.setattr(user_auth_mode, "user_auth_requested", lambda: False)
    assert type(cli._policy_store_for_site(Client())) is AgentPolicyStore
