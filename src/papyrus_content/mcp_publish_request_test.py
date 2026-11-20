from __future__ import annotations
import copy
import json
import pytest
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from papyrus_content import publish_gate, review_requests
from papyrus_content.mcp_publish_request import request_publish
from papyrus_content.publishing import ItemFields, save_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient


class Client(FakeAuthoringClient):
    tenant_id = None
    def _prepared_payload(self, model, payload): return payload


class Dynamo:
    def __init__(self, client, cancel=False): self.client, self.calls, self.cancel = client, [], cancel
    def transact_write_items(self, **request):
        self.calls.append(copy.deepcopy(request))
        if self.cancel:
            raise ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "conflict"}, "CancellationReasons": [{"Code": "ConditionalCheckFailed"}]}, "TransactWriteItems")
        raw = request["TransactItems"][1]["Put"]["Item"]
        row = {key: TypeDeserializer().deserialize(value) for key, value in raw.items()}
        self.client.tables.setdefault("ReviewRequest", {})[row["id"]] = row


def setup():
    client = Client()
    save_item(client, ItemFields(id="story-v1", type="article", slug="story", section="articles", body_markus="Draft.\n", front_matter_yaml="title: Story\n", aliases=[]), actor="AI", now="2026-01-01T00:00:00Z")
    client.update_record("Item", {"id": "story-v1", "lineageId": "story", "versionState": "current", "updatedAt": "revision"})
    return client


def request(client, db, expected="story-v1"):
    return request_publish(client, db, "item-table", "review-table", lineage="story", expected=expected, actor="agent:person")


def test_gate_opens_and_reuses_exact_version_request_without_publishing():
    client = setup(); publish_gate.set_publish_approval(client, "required", by="admin"); db = Dynamo(client)
    result = request(client, db)
    assert result["status"] == "pending"
    assert result["requestId"] == publish_gate.request_prefix(client.get_record("Item", "story-v1"))
    check, put = db.calls[0]["TransactItems"]
    assert check["ConditionCheck"]["Key"]["id"] == {"S": "story-v1"}
    for condition in ("#state = :current", "#lineage = :lineage", "#updated = :updated", "#hash = :hash", "attribute_not_exists(#tenant)"):
        assert condition in check["ConditionCheck"]["ConditionExpression"]
    assert put["Put"]["ConditionExpression"] == "attribute_not_exists(id)"
    assert request(client, db) == result and len(db.calls) == 1
    assert not client.tables.get("PublishedItem")
    review_requests.answer_review(client, result["requestId"], decision="approve", by="person")
    approved = request(client, db)
    assert approved["status"] == "console_handoff" and approved["requestId"] == result["requestId"] and approved["approval"] == "approved"
    assert not client.tables.get("PublishedItem")


def test_stale_and_conflicting_requests_never_publish():
    client = setup(); publish_gate.set_publish_approval(client, "required", by="admin"); db = Dynamo(client, cancel=True)
    with pytest.raises(ValueError, match="stale_version"): request(client, db, expected="old")
    assert not db.calls
    with pytest.raises(ValueError, match="stale_version"): request(client, db)
    assert not client.tables.get("ReviewRequest") and not client.tables.get("PublishedItem")


def test_no_gate_returns_console_handoff_without_any_write():
    client = setup(); db = Dynamo(client)
    assert request(client, db)["status"] == "console_handoff"
    assert not db.calls and not client.tables.get("PublishedItem") and not client.tables.get("ReviewRequest")


def test_tenant_is_denied_and_wrong_staff_cannot_open_request(monkeypatch):
    import importlib.util
    from pathlib import Path
    client = setup(); client.tenant_id = "tenant-a"; db = Dynamo(client)
    with pytest.raises(PermissionError): request(client, db)
    path = Path(__file__).resolve().parents[2] / "amplify/functions/content-actions/handler.py"
    spec = importlib.util.spec_from_file_location("publish_content_handler", path); handler = importlib.util.module_from_spec(spec); spec.loader.exec_module(handler)
    monkeypatch.setenv("PAPYRUS_USER_POOL_ISSUER", "https://issuer.test")
    with pytest.raises(PermissionError): handler.agent_request_story_publish_action({"lineageId": "story", "expectedCurrentVersionId": "story-v1"}, {"issuer": "https://issuer.test", "sub": "user", "claims": {"cognito:groups": ["reader"]}}, client=client, dynamodb=db)
    assert not db.calls


def test_agent_approval_cannot_satisfy_person_gate():
    client = setup(); publish_gate.set_publish_approval(client, "required", by="admin"); db = Dynamo(client)
    first = request(client, db)
    review_requests.answer_review(client, first["requestId"], decision="approve", by="agent:other")
    second = request(client, db)
    assert second["status"] == "pending" and second["requestId"] != first["requestId"]
    assert not client.tables.get("PublishedItem")


def test_existing_rejection_is_reported_without_new_request():
    client = setup(); publish_gate.set_publish_approval(client, "required", by="admin"); db = Dynamo(client)
    pending = request(client, db)
    review_requests.answer_review(client, pending["requestId"], decision="reject", by="person")
    result = request(client, db)
    assert result["status"] == "rejected" and result["requestId"] == pending["requestId"]
    assert len(db.calls) == 1 and not client.tables.get("PublishedItem")


def test_invalid_publish_preflight_does_not_open_approval():
    from papyrus_content.publishing import PublishError
    client = setup(); publish_gate.set_publish_approval(client, "required", by="admin"); db = Dynamo(client)
    client.tables["Item"]["story-v1"]["slug"] = "draft-articles-01234567"
    with pytest.raises(PublishError, match="placeholder slug"): request(client, db)
    assert not db.calls and not client.tables.get("ReviewRequest")


def test_user_scoped_adapter_invokes_publish_request_mutation():
    from papyrus_content.mcp_story_writes import StaffStoryWrites
    class Graph:
        def graphql(self, query, variables):
            assert "agentRequestStoryPublish" in query
            assert json.loads(variables["input"]) == {"lineageId": "story", "expectedCurrentVersionId": "story-v1"}
            return {"agentRequestStoryPublish": json.dumps({"status": "pending", "requestId": "rr-example", "versionId": "story-v1"})}
    adapter = StaffStoryWrites(); adapter.client = Graph()
    assert adapter.story_request_publish(object(), lineageId="story", expectedCurrentVersionId="story-v1")["requestId"] == "rr-example"


def test_action_fails_closed_when_review_models_are_excluded(monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "amplify/functions/content-actions/handler.py"
    spec = importlib.util.spec_from_file_location("publish_excluded_handler", path)
    handler = importlib.util.module_from_spec(spec); spec.loader.exec_module(handler)
    monkeypatch.setenv("PAPYRUS_USER_POOL_ISSUER", "https://issuer.test")
    monkeypatch.delenv("PAPYRUS_MCP_STORY_PUBLISH_REQUEST_ENABLED", raising=False)
    client = setup(); db = Dynamo(client)
    with pytest.raises(ValueError, match="unavailable"):
        handler.agent_request_story_publish_action({"lineageId": "story", "expectedCurrentVersionId": "story-v1"}, {"issuer": "https://issuer.test", "sub": "user", "claims": {"cognito:groups": ["editor"]}}, client=client, dynamodb=db)
    assert not db.calls
