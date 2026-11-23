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
        return handle({"identity": event({})["identity"], "arguments": {"input": json.dumps(request)}}, policy, ENVIRONMENT, "alpha", nothing_to_catch_up())

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


class NoRuns:
    def runs_since(self, automation_id, since):
        return []

    def newest_first(self, automation_id):
        return iter(())


def nothing_to_catch_up():
    from papyrus_content.agent_policy.function import PokeInServices

    return PokeInServices(lambda: {}, NoRuns(), lambda request: None)


def test_a_pause_and_a_resume_are_the_poke_in_operations_and_record_who_when_and_why():
    policy = store()
    paused = handle(event({"op": "agents_pause", "agent": "announce", "reason": "Checking the X drafts"}), policy, ENVIRONMENT, "alpha", nothing_to_catch_up())
    assert paused["ok"] is True and paused["result"]["paused"] is True and paused["result"]["pausedBy"] == "ryan@example.test"
    assert paused["document"]["agents"]["announce"]["pausedReason"] == "Checking the X drafts"
    shown = handle(event({"op": "agents_pauses"}), policy, ENVIRONMENT, "alpha")
    assert shown["result"]["agents"]["announce"]["paused"] is True and shown["result"]["site"] == {"paused": False}
    resumed = handle(event({"op": "agents_resume", "agent": "announce", "reason": "Drafts checked"}), policy, ENVIRONMENT, "alpha", nothing_to_catch_up())
    assert resumed["result"]["paused"] is False and resumed["result"]["caughtUp"] == [] and resumed["result"]["policyVersion"] == {"before": 1, "after": 2}
    assert policy.version_record("alpha", 2)["reason"] == "Drafts checked"


def test_a_resume_with_no_way_to_catch_up_is_refused_and_saves_nothing():
    policy = store()
    handle(event({"op": "agents_pause", "reason": "Incident"}), policy, ENVIRONMENT, "alpha", nothing_to_catch_up())
    answer = handle(event({"op": "agents_resume", "reason": "Over"}), policy, ENVIRONMENT, "alpha")
    assert answer["error"] == "service_unavailable" and policy.read("alpha").document["site"]["paused"] is True


def test_a_pause_from_another_client_or_an_editor_or_a_declared_agent_changes_nothing():
    policy = store()
    pause = {"op": "agents_pause", "reason": "x"}
    assert handle(event(pause, client="cli-client"), policy, ENVIRONMENT, "alpha")["error"] == "human_required"
    assert handle(event(pause, groups=("editor",)), policy, ENVIRONMENT, "alpha")["error"] == "not_authorized"
    assert handle(event({**pause, "actorKind": "agent"}), policy, ENVIRONMENT, "alpha")["error"] == "blocked"
    assert handle(event({**pause, "reason": " "}), policy, ENVIRONMENT, "alpha")["error"] == "invalid_input"
    assert policy.read("alpha").version == 0


def test_the_poke_in_door_imports_only_what_the_agent_policy_function_carries():
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2]
    probe = r'''
import json, sys
ALLOWED = set(sys.stdlib_module_names) | {"boto3", "botocore", "s3transfer", "jmespath", "dateutil", "urllib3", "six", "papyrus_content"}
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in ALLOWED and not name.startswith("_"):
            raise ModuleNotFoundError(f"No module named '{name}'")
sys.meta_path.insert(0, Block())
from papyrus_content.agent_policy.function import handle, PokeInServices
from papyrus_content.agent_poke_in import RunLedger, resume, pause, pauses
from papyrus_content.agent_listeners import ListenerIndex
from papyrus_content.agent_wakes import wake_sender
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
print("imported")
'''
    completed = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(source)!r}); exec({probe!r})"], capture_output=True, text=True, timeout=60)
    assert "imported" in completed.stdout, completed.stdout + completed.stderr


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


# --- the console's door to the announcement review (PPY-e2829f) ---------------------------------------------------------------------------------------------

X_STORY = {"channel": "x", "kind": "story_published"}


def review_request(approval, **extra):
    return {"op": "announcements_review_set", "approval": approval, **X_STORY, "reason": "Set in the newsroom's Announcements settings.", **extra}


def without_tenant(request, **options):
    built = event(request, **options)
    built["arguments"]["input"] = json.dumps(request)
    return built


def test_an_admin_on_a_person_client_sets_the_x_story_review_and_reads_it_back():
    policy = store()
    answer = handle(without_tenant(review_request("soft")), policy, ENVIRONMENT, "alpha")
    assert answer["ok"] is True and answer["result"] == {"policyVersion": 1, "approval": "soft", "rung": "publish_soft", "scope": X_STORY, "changed": True}
    assert policy.version_record("alpha", 1)["by"] == "ryan@example.test"
    shown = handle(without_tenant({"op": "announcements_review_show", **X_STORY}), policy, ENVIRONMENT, "alpha")
    assert shown["ok"] is True and shown["result"]["chosen"]["approval"] == "soft"
    assert shown["result"]["overrides"] == [{"scope": X_STORY, "approval": "soft", "rung": "publish_soft"}]


def test_the_review_from_another_client_is_refused_and_nothing_is_saved():
    policy = store()
    for request in (review_request("soft"), review_request("hard"), {"op": "announcements_review_show", **X_STORY}):
        assert handle(without_tenant(request, client="cli-client"), policy, ENVIRONMENT, "alpha")["error"] == "human_required"
    assert policy.read("alpha").version == 0


def test_an_editor_cannot_set_the_review():
    assert handle(without_tenant(review_request("hard"), groups=("editor",)), store(), ENVIRONMENT, "alpha")["error"] == "not_authorized"


def test_a_caller_that_declares_itself_an_agent_is_blocked_even_on_a_person_client():
    policy = store()
    assert handle(without_tenant(review_request("hard", actorKind="agent")), policy, ENVIRONMENT, "alpha")["error"] == "blocked"
    assert policy.read("alpha").version == 0


def test_posts_right_away_is_refused_in_the_floors_words_while_the_floor_stands():
    policy = store()
    answer = handle(without_tenant(review_request("none")), policy, ENVIRONMENT, "alpha")
    assert answer["error"] == "constraint_conflict" and "publish_auto" in answer["message"] and policy.read("alpha").version == 0


def test_a_review_change_needs_a_reason_a_known_approval_and_this_sites_tenant():
    assert handle(without_tenant(review_request("soft", reason=" ")), store(), ENVIRONMENT, "alpha")["error"] == "invalid_input"
    assert handle(without_tenant(review_request("sometimes")), store(), ENVIRONMENT, "alpha")["error"] == "invalid_input"
    assert handle(without_tenant(review_request("soft", channel=7)), store(), ENVIRONMENT, "alpha")["error"] == "invalid_input"
    assert handle(without_tenant(review_request("soft", tenantId="beta")), store(), ENVIRONMENT, "alpha")["error"] == "not_authorized"


def test_the_console_door_and_the_command_line_make_the_same_change(monkeypatch):
    from papyrus_content.announcements import review_handlers
    from papyrus_content.images.handlers import Caller

    through_console, through_cli = store(), store()
    handle(without_tenant(review_request("hard")), through_console, ENVIRONMENT, "alpha")

    class Client:
        tenant_id = "alpha"

    monkeypatch.setattr(review_handlers, "_publication", lambda client: "publication")
    review_handlers.review_set(Client(), {"approval": "hard", **X_STORY, "reason": "Set in the newsroom's Announcements settings."}, Caller(kind="person", is_admin=True, subject="ryan@example.test"),
                               through_cli)
    assert through_console.read("alpha").document == through_cli.read("alpha").document


def test_the_review_door_imports_only_what_the_agent_policy_function_carries():
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2]
    probe = r'''
import json, sys
ALLOWED = set(sys.stdlib_module_names) | {"boto3", "botocore", "s3transfer", "jmespath", "dateutil", "urllib3", "six", "papyrus_content"}
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in ALLOWED and not name.startswith("_"):
            raise ModuleNotFoundError(f"No module named '{name}'")
sys.meta_path.insert(0, Block())
from papyrus_content.agent_policy.function import handle
from papyrus_content.announcements.review_handlers import set_review_by_person, show_review
print("imported")
'''
    completed = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(source)!r}); exec({probe!r})"], capture_output=True, text=True, timeout=60)
    assert "imported" in completed.stdout, completed.stdout + completed.stderr
