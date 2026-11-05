"""Private site-tools invocation; only the CMS may invoke this function.

The CMS passes a principal already verified by its authentication service. The
function's invoke policy must not allow browser, guest, or general staff callers.
No principal, token, tenant or function name is read from tool arguments.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.mcp_tools import Principal, ReaderSteeringInvoke, StaffReads, call_tool, list_tools
from papyrus_content.operator_errors import GraphQLRequestError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UserPoolClient(PapyrusGraphQLAuthoringClient):
    """One user-pool request per operation, with no credential or retry fallback."""

    def __init__(self, endpoint: str, token: str, tenant: str | None):
        if not endpoint or not token:
            raise ValueError("Site endpoint and user identity are required.")
        super().__init__(endpoint=endpoint, header_factory=lambda _: {
            "content-type": "application/json", "Authorization": token,
        }, tenant_id=tenant, site_tenant=False)
        # The site's configured tenant is authoritative even when empty.
        self.tenant_id = tenant

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._send_graphql(query, variables)

    def _send_graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode()
        request = urllib.request.Request(self.endpoint, data=payload, headers=self._request_headers(payload), method="POST")
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout_seconds) as response:
                result = json.load(response)
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as error:
            raise GraphQLRequestError("The site API request failed.") from error
        if result.get("errors"):
            messages = "; ".join(str(e.get("message") or "Site API error") for e in result["errors"])
            raise GraphQLRequestError(messages)
        if not isinstance(result.get("data"), dict):
            raise GraphQLRequestError("The site API returned no data.")
        return result["data"]


def _failure(code: str, message: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": message}],
            "structuredContent": {"code": code, "message": message}}


def handler(event: dict, context: Any) -> dict:
    try:
        if not isinstance(event, dict) or set(event) - {"operation", "principal", "name", "arguments"}:
            return _failure("invalid_request", "The request is malformed.")
        raw = event.get("principal")
        if not isinstance(raw, dict):
            return _failure("unauthorized", "A verified site identity is required.")
        kind = raw.get("kind")
        staff, reader = None, None
        if kind == "staff" and isinstance(raw.get("subject"), str) and raw["subject"] and isinstance(raw.get("idToken"), str) and raw["idToken"]:
            if set(raw) - {"kind", "subject", "idToken", "expiresAt"}:
                return _failure("invalid_request", "The identity is malformed.")
            principal = Principal("staff", raw["subject"], is_agent=True)
            endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "")
            tenant = os.environ.get("PAPYRUS_TENANT_ID", "").strip() or None
            staff = StaffReads(UserPoolClient(endpoint, raw["idToken"], tenant))
            available = set(staff.available_tools)
            if tenant or os.environ.get("PAPYRUS_MCP_STORY_PUBLISH_REQUEST_ENABLED") != "true":
                available.discard("story_request_publish")
            if os.environ.get("PAPYRUS_MCP_STORY_DRAFT_ENABLED") != "true":
                available.discard("story_save_draft")
            if tenant:
                available -= {"reference_get", "reference_search", "reference_decide", "concept_get", "concept_search", "story_evidence", "assignments_list", "assignment_get", "reviews_list", "review_get", "review_answer"}
            elif os.environ.get("PAPYRUS_MCP_REFERENCE_SINGLE_TENANT") != "true":
                available.discard("reference_decide")
            staff.available_tools = frozenset(available)
        elif kind == "reader" and isinstance(raw.get("siteSubject"), str) and re.fullmatch(r"ss1_[A-Za-z0-9_-]{43}", raw["siteSubject"]):
            if set(raw) - {"kind", "siteSubject", "expiresAt"}:
                return _failure("invalid_request", "The identity is malformed.")
            principal = Principal("reader", raw["siteSubject"], site_subject=raw["siteSubject"])
            function_name = os.environ.get("PAPYRUS_READER_STEERING_FUNCTION", "").strip()
            publication = os.environ.get("PAPYRUS_PUBLICATION_ID", "").strip()
            if function_name and publication:
                import boto3
                reader = ReaderSteeringInvoke(boto3.client("lambda"), function_name, publication)
        else:
            return _failure("unauthorized", "A verified site identity is required.")
        if event.get("operation") == "list" and set(event) <= {"operation", "principal"}:
            return {"tools": list_tools(principal, staff=staff, reader=reader)}
        if event.get("operation") != "call" or not isinstance(event.get("name"), str) or not isinstance(event.get("arguments"), dict):
            return _failure("invalid_request", "The request is malformed.")
        result = call_tool(principal, event["name"], event["arguments"], staff=staff, reader=reader)
        if result.get("ok") is False or (kind == "reader" and result.get("statusCode", 500) >= 400):
            return {"isError": True, "content": [{"type": "text", "text": json.dumps(result, default=str)}], "structuredContent": result}
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "structuredContent": result}
    except PermissionError:
        return _failure("forbidden", "This identity cannot use that tool.")
    except ValueError as error:
        if "stale_revision" in str(error) or "stale_version" in str(error):
            return _failure("stale_revision", "The record changed. Refresh the card and try again.")
        return _failure("invalid_request", "The request could not be accepted.")
    except GraphQLRequestError as error:
        if "stale_revision" in str(error) or "stale_version" in str(error):
            return _failure("stale_revision", "The record changed. Refresh the card and try again.")
        return _failure("site_error", "The site could not complete the request.")
    except Exception:
        return _failure("site_error", "The site could not complete the request.")
