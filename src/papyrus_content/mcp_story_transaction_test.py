from __future__ import annotations
import copy
import json
import pytest
from botocore.exceptions import ClientError
from papyrus_content.mcp_story_transaction import persist_agent_story_version
from papyrus_content.mcp_story_writes import StaffStoryWrites


class Client:
    tenant_id = "tenant-a"
    def _prepared_payload(self, model, record):
        assert model == "Item"
        return {**record, "tenantId": self.tenant_id}


class Dynamo:
    def __init__(self, failure=None): self.calls, self.failure = [], failure
    def transact_write_items(self, **request):
        self.calls.append(copy.deepcopy(request))
        if self.failure: raise self.failure


def draft():
    return {"id": "story-v2", "lineageId": "story", "versionCreatedAt": "2026-01-01T00:00:00Z", "versionState": "current", "bodyIr": json.dumps({"papyrus": {"images": {}}}), "rating": 1.5}


def test_atomic_request_binds_current_lineage_revision_tenant_and_new_id():
    dynamo = Dynamo()
    persist_agent_story_version(Client(), "table", dynamo, "story", "story-v1", "old-revision", draft())
    update, put = dynamo.calls[0]["TransactItems"]
    assert update["Update"]["Key"] == {"id": {"S": "story-v1"}}
    assert "#state = :current" in update["Update"]["ConditionExpression"]
    assert "#lineage = :lineage" in update["Update"]["ConditionExpression"]
    assert "#updated = :updated" in update["Update"]["ConditionExpression"]
    assert "#tenant = :tenant" in update["Update"]["ConditionExpression"]
    assert update["Update"]["ExpressionAttributeValues"][":tenant"] == {"S": "tenant-a"}
    assert put["Put"]["ConditionExpression"] == "attribute_not_exists(id)"
    assert put["Put"]["Item"]["id"] == {"S": "story-v2"}
    assert put["Put"]["Item"]["rating"] == {"N": "1.5"}


def test_transaction_collision_is_reported_as_stale():
    failure = ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "cancelled"}, "CancellationReasons": [{"Code": "ConditionalCheckFailed"}]}, "TransactWriteItems")
    with pytest.raises(ValueError, match="stale_version"):
        persist_agent_story_version(Client(), "table", Dynamo(failure), "story", "story-v1", "rev", draft())


def test_images_are_refused_before_transaction():
    item = draft(); item["bodyIr"] = json.dumps({"papyrus": {"images": {"one": {"src": "image.png"}}}})
    dynamo = Dynamo()
    with pytest.raises(ValueError, match="images"):
        persist_agent_story_version(Client(), "table", dynamo, "story", "story-v1", "rev", item)
    assert not dynamo.calls


def test_mcp_mixin_uses_user_scoped_graphql_mutation():
    class Graph:
        def graphql(self, query, variables):
            assert "agentSaveStoryDraft" in query
            assert json.loads(variables["input"])["expectedCurrentVersionId"] == "story-v1"
            return {"agentSaveStoryDraft": json.dumps({"ok": True, "item": {"id": "story-v2"}})}
    adapter = StaffStoryWrites(); adapter.client = Graph()
    assert adapter.story_save_draft(object(), lineageId="story", expectedCurrentVersionId="story-v1", body="Text", reason="Edit")["item"]["id"] == "story-v2"


def test_handler_verifies_staff_and_reports_committed_draft_when_check_fails(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "amplify/functions/content-actions/handler.py"
    spec = importlib.util.spec_from_file_location("mcp_content_handler", path)
    handler = importlib.util.module_from_spec(spec); spec.loader.exec_module(handler)
    monkeypatch.setenv("PAPYRUS_USER_POOL_ISSUER", "https://issuer.test")
    monkeypatch.setenv("PAPYRUS_ITEM_TABLE", "table")
    module = types.ModuleType("papyrus_content.editorial_commands")
    def failure(_): raise RuntimeError("offline")
    module.check_saved_version_best_effort = failure
    monkeypatch.setitem(sys.modules, "papyrus_content.editorial_commands", module)
    class StoryClient(Client):
        tenant_id = "tenant-a"
        def get_record(self, model, item_id):
            return {"id": "story-v1", "lineageId": "story", "versionNumber": 1, "versionState": "current", "type": "article", "slug": "story", "status": "draft", "stage": "reporting", "title": "Story", "aliases": [], "metadata": "{}", "updatedAt": "old-revision"}
        def list_by_index(self, index, key): return [self.get_record("Item", "story-v1")]
    args = {"lineageId": "story", "expectedCurrentVersionId": "story-v1", "body": "Draft.", "reason": "Edit"}
    dynamo = Dynamo()
    with pytest.raises(PermissionError): handler.agent_save_story_draft_action(args, {"issuer": "https://issuer.test", "sub": "user", "claims": {"cognito:groups": ["reader"]}}, client=StoryClient(), dynamodb=dynamo)
    assert not dynamo.calls
    result = handler.agent_save_story_draft_action(args, {"issuer": "https://issuer.test", "sub": "user", "claims": {"cognito:groups": ["editor"]}}, client=StoryClient(), dynamodb=dynamo)
    assert result["ok"] is True and result["editorialCheck"]["notChecked"]
    assert dynamo.calls[0]["TransactItems"][1]["Put"]["Item"]["versionCreatedBy"] == {"S": "AI"}
