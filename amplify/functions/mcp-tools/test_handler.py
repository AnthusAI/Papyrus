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
    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    client = module.UserPoolClient("https://example.org/graphql", "verified-id-token", None)
    assert client.graphql("query { result }") == {"result": True}
    assert seen[0].get_header("Authorization") == "verified-id-token"
    assert len(seen) == 1


def test_public_arguments_cannot_choose_identity_or_tenant(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://example.org/graphql")
    event = {"operation": "call", "principal": {"kind": "staff", "subject": "editor", "idToken": "token"},
             "name": "story_get", "arguments": {"lineageId": "story", "tenant": "other", "role": "admin"}}
    result = module.handler(event, None)
    assert result["isError"] and result["structuredContent"]["error"]["code"] == "invalid_request"


def test_missing_id_token_never_uses_access_or_iam():
    result = module.handler({"operation": "list", "principal": {"kind": "staff", "subject": "editor", "accessToken": "token"}}, None)
    assert result["structuredContent"]["error"]["code"] == "unauthorized"


def test_missing_reader_plugin_exposes_no_reader_actions(monkeypatch):
    monkeypatch.delenv("PAPYRUS_READER_STEERING_FUNCTION", raising=False)
    result = module.handler({"operation": "list", "principal": {"kind": "reader", "siteSubject": "verified"}}, None)
    assert result == {"tools": []}


def test_reader_cannot_forge_staff_role():
    result = module.handler({"operation": "list", "principal": {"kind": "reader", "siteSubject": "verified", "role": "admin"}}, None)
    assert result["structuredContent"]["error"]["code"] == "invalid_request"
