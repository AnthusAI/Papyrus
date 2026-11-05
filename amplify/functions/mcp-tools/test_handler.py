"""Contract checks for the private CMS-to-site-tools boundary."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("mcp_tools_handler", Path(__file__).with_name("handler.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_user_pool_client_uses_only_supplied_token(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return b'{"data":{"result":true}}'
    seen = []
    def urlopen(request, timeout):
        seen.append(request)
        return Response()
    class Opener:
        open = staticmethod(urlopen)
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *_: Opener())
    client = module.UserPoolClient("https://example.org/graphql", "verified-id-token", None)
    assert client.graphql("query { result }") == {"result": True}
    assert seen[0].get_header("Authorization") == "verified-id-token"
    assert len(seen) == 1


def test_public_arguments_cannot_choose_identity_or_tenant(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    event = {"operation": "call", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"},
             "name": "story_get", "arguments": {"lineageId": "story", "tenant": "other", "role": "admin"}}
    result = module.handler(event, None)
    assert result["isError"] and result["structuredContent"]["code"] == "invalid_request"


def test_missing_id_token_never_uses_access_or_iam():
    result = module.handler({"operation": "list", "principal": {"kind": "staff", "subject": "editor", "accessToken": "token"}}, None)
    assert result["structuredContent"]["code"] == "unauthorized"


def test_missing_reader_plugin_exposes_no_reader_actions(monkeypatch):
    monkeypatch.delenv("PAPYRUS_READER_STEERING_FUNCTION", raising=False)
    result = module.handler({"operation": "list", "principal": {"kind": "reader", "siteSubject": "ss1_" + "a" * 43}}, None)
    assert result == {"tools": []}


def test_reader_cannot_forge_staff_role():
    result = module.handler({"operation": "list", "principal": {"kind": "reader", "siteSubject": "ss1_" + "a" * 43, "role": "admin"}}, None)
    assert result["structuredContent"]["code"] == "invalid_request"


def test_stale_revision_is_a_stable_tool_error(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    def conflict(*args, **kwargs):
        raise module.GraphQLRequestError("stale_revision: changed")
    monkeypatch.setattr(module, "call_tool", conflict)
    result = module.handler({"operation": "call", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"},
                             "name": "reference_decide", "arguments": {}}, None)
    assert result["isError"] and result["structuredContent"]["code"] == "stale_revision"


def test_graphql_redirect_is_never_followed():
    assert module._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example") is None


def test_reader_identity_requires_verified_subject_format():
    result = module.handler({"operation": "list", "principal": {"kind": "reader", "siteSubject": "forged"}}, None)
    assert result["structuredContent"]["code"] == "unauthorized"


def test_shared_backend_hides_unscoped_models(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "account-one")
    result = module.handler({"operation": "list", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"}}, None)
    names = {tool["name"] for tool in result["tools"]}
    assert "story_get" in names
    assert not names.intersection({"reference_get", "story_evidence", "concept_get", "assignment_get", "review_get"})


def test_story_save_discovery_requires_deployment_opt_in(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    monkeypatch.delenv("PAPYRUS_MCP_STORY_DRAFT_ENABLED", raising=False)
    event = {"operation": "list", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"}}
    assert "story_save_draft" not in {t["name"] for t in module.handler(event, None)["tools"]}
    monkeypatch.setenv("PAPYRUS_MCP_STORY_DRAFT_ENABLED", "true")
    assert "story_save_draft" in {t["name"] for t in module.handler(event, None)["tools"]}


def test_save_result_preserves_post_save_check_status(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    monkeypatch.setenv("PAPYRUS_MCP_STORY_DRAFT_ENABLED", "true")
    def saved(*args, **kwargs):
        return {"ok": True, "item": {"id": "story-v2"}, "editorialCheck": {"notChecked": "Check unavailable"}}
    monkeypatch.setattr(module, "call_tool", saved)
    result = module.handler({"operation": "call", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"},
                             "name": "story_save_draft", "arguments": {}}, None)
    assert result["structuredContent"]["editorialCheck"]["notChecked"] == "Check unavailable"
    assert result["structuredContent"]["item"]["id"] == "story-v2"


def test_publish_request_needs_deployed_capability_and_unscoped_backend(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    monkeypatch.delenv("PAPYRUS_MCP_STORY_PUBLISH_REQUEST_ENABLED", raising=False)
    event = {"operation": "list", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"}}
    names = lambda: {t["name"] for t in module.handler(event, None)["tools"]}
    assert "story_request_publish" not in names()
    monkeypatch.setenv("PAPYRUS_MCP_STORY_PUBLISH_REQUEST_ENABLED", "true")
    assert "story_request_publish" in names()
    assert "story_publish" not in names()
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "tenant-one")
    assert "story_request_publish" not in names()
