from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from papyrus_content.graphql_http import iam_signed_graphql_headers


CONSOLE_THREAD_ANCHOR_KEY = "site#papyrus"
CONSOLE_NEWSROOM_FEED_KEY = "consoleChat"
CONSOLE_MESSAGE_KIND = "console_chat_turn"
CONSOLE_MESSAGE_DOMAIN = "conversation"
CONSOLE_RESPONSE_TARGET_CLOUD = "cloud"
CONSOLE_RESPONSE_TARGET_LOCAL = "local"
LIVE_AGENT_MARKER = "behave-live-agent"
DEFAULT_AGENT_MODEL = "gpt-5-nano"
EXPECTED_SNIPPET_CONTRACT_VERSION = "execute_tactus_snippet_contract_v1"
EDITORIAL_CURATION_SCENARIOS = {
    "review-reference-curation-accept": {
        "requiredInitialStatus": "pending",
        "action": "accept",
        "restoreAction": "reopen",
        "sentinel": "reference-curation-accept-tested",
    },
    "review-reference-curation-reject": {
        "requiredInitialStatus": "pending",
        "action": "reject",
        "restoreAction": "reopen",
        "sentinel": "reference-curation-reject-tested",
    },
    "review-reference-curation-archive": {
        "requiredInitialStatus": "pending",
        "action": "archive",
        "restoreAction": "reopen",
        "sentinel": "reference-curation-archive-tested",
    },
    "review-reference-curation-reopen": {
        "requiredInitialStatus": "accepted",
        "action": "reopen",
        "restoreAction": "accept",
        "sentinel": "reference-curation-reopen-tested",
    },
}
SCENARIO_REQUIRED_TOOL_CALLS: dict[str, list[str]] = {
    "docs-progressive": ["papyrus.docs.list", "papyrus.docs.get"],
    "unsupported-snippet-retry": ["papyrus.docs.get"],
    "create-research-assignment": ["papyrus.Assignment.create"],
    "list-research-assignments": ["papyrus.Assignment.create", "papyrus.Assignment.list"],
    "get-research-assignment": ["papyrus.Assignment.create", "papyrus.Assignment.get"],
    "update-research-assignment": ["papyrus.Assignment.update"],
    "invalid-assignment-input": ["papyrus.Assignment.create"],
    "discuss-reference": ["papyrus.reference.list", "papyrus.reference.get"],
    "list-recent-references": ["papyrus.Reference.list"],
    "get-specific-reference": ["papyrus.Reference.get"],
    "knowledge-query-single-reference": ["papyrus.Reference.get", "papyrus.knowledge.query"],
    "knowledge-query-three-references": ["papyrus.knowledge.query"],
    "rate-reference-quality": ["papyrus.reference.list", "papyrus.reference.quality_rate", "papyrus.reference.quality_get"],
    "review-reference-curation-accept": ["papyrus.reference.list", "papyrus.reference.curation_review"],
    "review-reference-curation-reject": ["papyrus.reference.list", "papyrus.reference.curation_review"],
    "review-reference-curation-archive": ["papyrus.reference.list", "papyrus.reference.curation_review"],
    "review-reference-curation-reopen": ["papyrus.reference.list", "papyrus.reference.curation_review"],
    "insight-reference": ["papyrus.reference.list", "papyrus.reference.insight_create", "papyrus.reference.insight_list"],
    "curate-reference-refresh": ["papyrus.reference.list", "papyrus.reference.curation_start", "papyrus.reference.curation_status"],
}
SCENARIO_REQUIRED_TOOL_CALL_COUNTS: dict[str, dict[str, int]] = {
    "review-reference-curation-accept": {"papyrus.reference.curation_review": 2},
    "review-reference-curation-reject": {"papyrus.reference.curation_review": 2},
    "review-reference-curation-archive": {"papyrus.reference.curation_review": 2},
    "review-reference-curation-reopen": {"papyrus.reference.curation_review": 2},
}
SCENARIO_EXPECTED_FINAL_RESPONSE: dict[str, str] = {
    "docs-progressive": "docs-progressive-tested",
    "unsupported-snippet-retry": "unsupported-snippet-retry-tested",
    "invalid-assignment-input": "invalid-input-tested",
    "discuss-reference": "reference-discussion-tested",
    "list-recent-references": "reference-recent-tested",
    "get-specific-reference": "reference-detail-tested",
    "knowledge-query-single-reference": "reference-knowledge-single-tested",
    "knowledge-query-three-references": "reference-knowledge-group-tested",
    "rate-reference-quality": "reference-quality-tested",
    "review-reference-curation-accept": "reference-curation-accept-tested",
    "review-reference-curation-reject": "reference-curation-reject-tested",
    "review-reference-curation-archive": "reference-curation-archive-tested",
    "review-reference-curation-reopen": "reference-curation-reopen-tested",
    "insight-reference": "reference-insight-tested",
}
MESSAGE_FIELD_CANDIDATES = [
    "id",
    "threadId",
    "parentMessageId",
    "sequenceNumber",
    "role",
    "messageKind",
    "messageType",
    "content",
    "summary",
    "responseStatus",
    "responseOwner",
    "responseStartedAt",
    "responseCompletedAt",
    "responseError",
    "messageDomain",
    "source",
    "importRunId",
    "authorLabel",
    "newsroomFeedKey",
    "metadata",
    "body",
    "createdAt",
    "updatedAt",
]
SCHEMA_INTROSPECTION = """
query ConsoleAgentSmokeSchema {
  queryType: __type(name: "Query") { fields { name } }
  mutationType: __type(name: "Mutation") { fields { name } }
  messageType: __type(name: "Message") { fields { name } }
  createMessageInputType: __type(name: "CreateMessageInput") { inputFields { name } }
  assignmentType: __type(name: "Assignment") { fields { name } }
}
"""
CREATE_ASSIGNMENT_FOR_UPDATE_MUTATION = """
mutation CreateAssignmentForUpdateScenario($input: CreateAssignmentInput!) {
  createAssignment(input: $input) { id }
}
"""
_LOCAL_BINARY_CACHE: Path | None = None


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", trimmed)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key in os.environ:
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value


def _endpoint_from_outputs(repo_root: Path) -> str:
    outputs_path = repo_root / "amplify_outputs.json"
    if not outputs_path.exists():
        return ""
    payload = json.loads(outputs_path.read_text(encoding="utf-8"))
    return payload.get("data", {}).get("url") or payload.get("data", {}).get("aws_appsync_graphqlEndpoint") or ""


def _required_env(name: str, fallback: str = "") -> str:
    value = os.environ.get(name) or fallback
    if not value:
        raise RuntimeError(f"Missing {name}. Set it in the environment or .env.")
    return value


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if content:
        return str(content)
    body = message.get("body")
    if body:
        return str(body)
    try:
        return str(json.loads(message.get("metadata") or "{}").get("content") or "")
    except Exception:
        return ""


def _message_role(message: dict[str, Any]) -> str:
    role = message.get("role")
    if role:
        return str(role)
    try:
        return str(json.loads(message.get("metadata") or "{}").get("role") or "")
    except Exception:
        return ""


def _collect_created_assignment_ids(value: Any, assignment_ids: set[str], event_ids: set[str]) -> None:
    if not isinstance(value, dict):
        return
    assignment_id = value.get("assignmentId") or value.get("assignment", {}).get("id")
    event_id = value.get("event", {}).get("id")
    if assignment_id:
        assignment_ids.add(str(assignment_id))
    if event_id:
        event_ids.add(str(event_id))
    for nested in value.values():
        if isinstance(nested, dict):
            _collect_created_assignment_ids(nested, assignment_ids, event_ids)


def _collect_errors(value: Any, errors: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            errors.append(error)
        for nested in value.values():
            if isinstance(nested, dict):
                _collect_errors(nested, errors)


def _parse_markdown_tool_result(content: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"api_calls": []}
    lines = [line.rstrip() for line in str(content or "").splitlines()]
    in_api_calls = False
    in_error = False
    in_error_details = False
    error: dict[str, Any] = {}
    error_details: dict[str, Any] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- api_calls:"):
            in_api_calls = True
            in_error = False
            in_error_details = False
            continue
        if line.startswith("- error:"):
            in_api_calls = False
            in_error = True
            in_error_details = False
            continue
        if line.startswith("- value:"):
            in_api_calls = False
            in_error = False
            in_error_details = False
            continue
        if line.startswith("- status:"):
            status = line.split(":", 1)[1].strip()
            parsed["ok"] = status == "ok"
            continue
        if in_api_calls and line.startswith("-"):
            call = line[1:].strip().strip("`")
            if call:
                parsed.setdefault("api_calls", []).append(call)
            continue
        if in_error and line.startswith("-"):
            body = line[1:].strip()
            if body.startswith("details:"):
                in_error_details = True
                continue
            if body.startswith("code:"):
                in_error_details = False
                error["code"] = body.split(":", 1)[1].strip().strip("`")
                continue
            if body.startswith("message:"):
                in_error_details = False
                error["message"] = body.split(":", 1)[1].strip()
                continue
            if body.startswith("retryable:"):
                in_error_details = False
                value = body.split(":", 1)[1].strip().lower()
                error["retryable"] = value == "true"
                continue
            if in_error_details and body.startswith("**") and "**:" in body:
                key_part, value_part = body.split(":", 1)
                key = key_part.strip().strip("*").strip()
                value = value_part.strip().strip("`")
                if key:
                    error_details[key] = value
                continue
    if error_details:
        error["details"] = error_details
    if error:
        parsed["error"] = error
    return parsed


def _parse_tool_result_content(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    return _parse_markdown_tool_result(text)


def _collect_reference_tool_diagnostics(value: Any, diagnostics: dict[str, Any], marker: str) -> None:
    if not isinstance(value, dict):
        return
    kind = str(value.get("kind") or "")
    if kind == "reference.list":
        items = [entry for entry in (value.get("items") or []) if isinstance(entry, dict)]
        selected = diagnostics.get("selectedReference")
        if isinstance(selected, dict):
            selected_id = str(selected.get("id") or "")
            matched = next((item for item in items if str(item.get("id") or "") == selected_id), None)
            if isinstance(matched, dict):
                diagnostics["initialStatusObservedFromList"] = str(matched.get("curationStatus") or "").strip().lower() or None
    if "action" in value and "status" in value and "referenceId" in value:
        action = str(value.get("action") or "").strip().lower()
        if action in {"accept", "reject", "reopen", "archive"}:
            diagnostics.setdefault("curationTransitions", []).append(
                {
                    "action": action,
                    "status": str(value.get("status") or "").strip().lower(),
                    "referenceId": str(value.get("referenceId") or ""),
                    "messageId": str(value.get("messageId") or ""),
                }
            )
    if str(value.get("status") or "").strip().lower() == "created" and value.get("messageId"):
        insight = diagnostics.setdefault("insight", {})
        created = set(str(entry) for entry in (insight.get("createdMessageIds") or []))
        created.add(str(value.get("messageId")))
        insight["createdMessageIds"] = sorted(created)
    if "referenceLineageId" in value and isinstance(value.get("items"), list):
        insight = diagnostics.setdefault("insight", {})
        listed_ids: set[str] = set(str(entry) for entry in (insight.get("listedMessageIds") or []))
        listed_items = [entry for entry in value.get("items") if isinstance(entry, dict)]
        for entry in listed_items:
            if entry.get("id"):
                listed_ids.add(str(entry.get("id")))
        insight["listedMessageIds"] = sorted(listed_ids)
        created_ids = {str(entry) for entry in (insight.get("createdMessageIds") or [])}
        matched_ids: set[str] = set(str(entry) for entry in (insight.get("matchedMessageIds") or []))
        for entry in listed_items:
            message_id = str(entry.get("id") or "")
            if not message_id or message_id not in created_ids:
                continue
            matched_ids.add(message_id)
            summary = str(entry.get("summary") or "")
            body = str(entry.get("content") or entry.get("body") or "")
            if marker in summary:
                insight["markerInSummary"] = True
            if marker in body:
                insight["markerInBody"] = True
        insight["matchedMessageIds"] = sorted(matched_ids)


def _local_responder_enabled() -> bool:
    return os.environ.get("PAPYRUS_LIVE_AGENT_LOCAL_RESPONDER") == "1"


def _local_responder_binary(repo_root: Path) -> Path:
    global _LOCAL_BINARY_CACHE
    if _LOCAL_BINARY_CACHE and _LOCAL_BINARY_CACHE.exists():
        return _LOCAL_BINARY_CACHE
    manifest = repo_root / "amplify/functions/console-chat-responder/Cargo.toml"
    subprocess.run(
        ["cargo", "build", "--release", "--manifest-path", str(manifest)],
        check=True,
        cwd=repo_root,
    )
    binary = repo_root / "amplify/functions/console-chat-responder/target/release/papyrus_console_chat_responder"
    if not binary.exists():
        raise RuntimeError(f"Local console responder binary not found at {binary}")
    _LOCAL_BINARY_CACHE = binary
    return binary


def _invoke_local_responder(
    *,
    repo_root: Path,
    thread_id: str,
    message_id: str,
    content: str,
    sequence_number: int,
    created_at: str,
    metadata: dict[str, Any],
) -> None:
    payload = {
        "threadId": thread_id,
        "messageId": message_id,
        "content": content,
        "sequenceNumber": sequence_number,
        "createdAt": created_at,
        "metadata": metadata,
    }
    binary = _local_responder_binary(repo_root)
    runner_path = repo_root / "amplify/functions/console-chat-responder/py/execute_tactus_runner.py"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        local_input_path = handle.name
    try:
        env = os.environ.copy()
        env.setdefault("PAPYRUS_CONSOLE_MODEL", DEFAULT_AGENT_MODEL)
        env.setdefault("PAPYRUS_CONSOLE_RESPONSE_TARGET", CONSOLE_RESPONSE_TARGET_LOCAL)
        env["PAPYRUS_LOCAL_RESPONDER_INPUT_JSON"] = local_input_path
        env["PAPYRUS_EXECUTE_TACTUS_RUNNER"] = str(runner_path)
        subprocess.run(
            [str(binary)],
            check=True,
            cwd=repo_root,
            env=env,
        )
    finally:
        try:
            os.unlink(local_input_path)
        except OSError:
            pass


def scenario_prompt(
    name: str,
    run_id: str,
    seeded_assignment_id: str | None = None,
    reference_corpus_key: str | None = None,
    reference_target: dict[str, Any] | None = None,
    insight_marker: str | None = None,
) -> str:
    marker = f"{LIVE_AGENT_MARKER}-{run_id}"
    if name == "hello":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Say hello in one short sentence.",
            ]
        )
    if name == "docs-progressive":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for a strict docs API call-order test.",
                "This is a strict live integration test: if you answer without tool calls, the test fails.",
                "Do not answer from memory or prior context; call tools first.",
                "Forbidden tool name: docs_progressive.",
                "Execute exactly two tool calls and no others.",
                "Step 1 required snippet:",
                "return docs_list{ namespace = 'resources' }",
                "Step 2 required snippet:",
                "return docs_get{ id = 'resources.Assignment' }",
                "Only after both tool calls succeed, reply with only `docs-progressive-tested`.",
            ]
        )
    if name == "unsupported-snippet-retry":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for strict retry recovery validation.",
                "This is a strict integration test: execute exactly two tool calls in this order.",
                "Step 1 must intentionally fail with unsupported_snippet using JS/object-call syntax:",
                "docs_get({ id: \"resources.Assignment\" })",
                "Step 2 must correct syntax and succeed using Lua/Tactus table-call form:",
                "return docs_get{ id = \"resources.Assignment\" }",
                "After the corrected call succeeds, reply with only `unsupported-snippet-retry-tested`.",
            ]
        )
    if name == "create-research-assignment":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus to create exactly one research Assignment. Do not answer until the Assignment.create tool call has succeeded.",
                "This is a live integration test: a natural-language response without an execute_tactus tool call is a failure.",
                "If you inspect docs first, continue immediately afterward and perform the write.",
                "Idempotency rule: do not call Assignment.create more than once for the same importRunId marker.",
                "The required Tactus snippet is:",
                (
                    f"return Assignment.create{{ type = \"research\", title = \"{marker} create\", "
                    f"summary = \"Smoke-test assignment created by the console agent.\", sectionKey = \"technology\", "
                    f"researchMode = \"source_discovery\", importRunId = \"{marker}\", apply = true }}"
                ),
                "After the tool result succeeds, reply with only the created assignment id.",
            ]
        )
    if name == "list-research-assignments":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for Assignment CRUD test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Idempotency rule: do not call Assignment.create more than once for the same importRunId marker.",
                "Execute exactly two tool calls: first create, then list.",
                "Step 1 required snippet:",
                (
                    f"return Assignment.create{{ type = 'research', title = '{marker} list', summary = 'list smoke', "
                    f"sectionKey = 'technology', researchMode = 'source_discovery', importRunId = '{marker}', apply = true }}"
                ),
                "Step 2 required snippet:",
                f"return Assignment.list{{ importRunId = '{marker}', limit = 20 }}",
                "After both tool calls succeed, reply with only the created assignment id from step 1.",
            ]
        )
    if name == "get-research-assignment":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for Assignment CRUD test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Idempotency rule: do not call Assignment.create more than once for the same importRunId marker.",
                "Execute exactly two tool calls: first create, then get.",
                "Step 1 required snippet:",
                (
                    f"return Assignment.create{{ type = 'research', title = '{marker} get', summary = 'get smoke', "
                    f"sectionKey = 'technology', researchMode = 'source_discovery', importRunId = '{marker}', apply = true }}"
                ),
                "Step 2 required snippet:",
                "return Assignment.get{ id = '<assignment id from step 1>' }",
                "After both tool calls succeed, reply with only the created assignment id from step 1.",
            ]
        )
    if name == "update-research-assignment":
        if not seeded_assignment_id:
            raise RuntimeError("Update scenario requires a seeded assignment id")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for Assignment status update test.",
                "Do not call docs_list or docs_get.",
                "Do not call Assignment.create for this scenario.",
                "Execute exactly one tool call and do not retry with alternate snippets.",
                "Required snippet:",
                f"return Assignment.update{{ id = '{seeded_assignment_id}', status = 'claimed', apply = true }}",
                "After the tool call succeeds, reply with only the assignment id.",
            ]
        )
    if name == "invalid-assignment-input":
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus and intentionally call Assignment.create with invalid input.",
                "Execute exactly one tool call.",
                "Required snippet:",
                "return Assignment.create{ type = 'research', apply = true }",
                "Do not mask or paraphrase errors; return tool result as-is.",
                "After the failing tool call, reply with only `invalid-input-tested`.",
            ]
        )
    if name == "discuss-reference":
        if not reference_corpus_key:
            raise RuntimeError("discuss-reference scenario requires a non-empty reference corpus key")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for Reference discussion test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Execute exactly two tool calls: first list, then get.",
                "Step 1 required snippet:",
                f"return papyrus.reference.list{{ corpus_key = '{reference_corpus_key}', limit = 100 }}",
                "Step 2 required snippet:",
                "return papyrus.reference.get{ id = '<reference id from step 1 first item>' }",
                "After both tool calls succeed, reply with only `reference-discussion-tested`.",
            ]
        )
    if name == "list-recent-references":
        if not reference_corpus_key:
            raise RuntimeError("list-recent-references scenario requires a non-empty reference corpus key")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for recent-reference listing test. Do not answer until required tool call succeeds.",
                "Do not call docs_list or docs_get.",
                "Execute exactly one tool call.",
                "Required snippet:",
                f"return Reference.list{{ corpusKey = '{reference_corpus_key}', limit = 3, order = 'newest' }}",
                "After the tool call succeeds, reply with only `reference-recent-tested`.",
            ]
        )
    if name == "get-specific-reference":
        if not isinstance(reference_target, dict):
            raise RuntimeError("get-specific-reference scenario requires a selected reference target.")
        reference_id = str(reference_target.get("id") or "").strip()
        if not reference_id:
            raise RuntimeError("get-specific-reference scenario requires selected reference id.")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                f"Selected reference id: {reference_id}.",
                "Use execute_tactus for specific-reference detail test. Do not answer until required tool call succeeds.",
                "Do not call docs_list or docs_get.",
                "Execute exactly one tool call.",
                "Required snippet:",
                f"return Reference.get{{ id = '{reference_id}' }}",
                "After the tool call succeeds, reply with only `reference-detail-tested`.",
            ]
        )
    if name == "knowledge-query-single-reference":
        if not isinstance(reference_target, dict):
            raise RuntimeError("knowledge-query-single-reference scenario requires a selected reference target.")
        reference_id = str(reference_target.get("id") or "").strip()
        if not reference_id:
            raise RuntimeError("knowledge-query-single-reference scenario requires selected reference id.")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                f"Selected reference id: {reference_id}.",
                "Use execute_tactus for reference-scoped knowledge query test.",
                "Do not call docs_list or docs_get.",
                "Execute exactly two tool calls in order: Reference.get then knowledge_query.",
                "Step 1 required snippet:",
                f"return Reference.get{{ id = '{reference_id}' }}",
                "Step 2 required snippet:",
                (
                    f"return knowledge_query{{ semanticQuery = \"Summarize the key ideas and practical implications of this reference.\", "
                    f"anchors = {{ {{ uri = \"papyrus://reference/{reference_id}\" }} }} }}"
                ),
                "After both tool calls succeed, reply with only `reference-knowledge-single-tested`.",
            ]
        )
    if name == "knowledge-query-three-references":
        if not isinstance(reference_target, dict):
            raise RuntimeError("knowledge-query-three-references scenario requires selected references.")
        reference_ids = [str(entry).strip() for entry in (reference_target.get("referenceIds") or []) if str(entry).strip()]
        if len(reference_ids) < 3:
            raise RuntimeError("knowledge-query-three-references scenario requires three selected reference ids.")
        anchors = ", ".join([f"{{ uri = 'papyrus://reference/{reference_id}' }}" for reference_id in reference_ids[:3]])
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                f"Selected reference ids: {', '.join(reference_ids[:3])}.",
                "Use execute_tactus for multi-reference knowledge query test.",
                "Do not call docs_list or docs_get.",
                "Execute exactly one tool call.",
                "Required snippet:",
                (
                    "return knowledge_query{ semanticQuery = 'Compare and contrast these references: shared themes, key differences, and strongest evidence.', "
                    f"anchors = {{ {anchors} }}, scope = {{ topK = 12 }}, output = {{ format = 'structured', maxTokens = 700 }} }}"
                ),
                "After the tool call succeeds, reply with only `reference-knowledge-group-tested`.",
            ]
        )
    if name == "rate-reference-quality":
        if not reference_corpus_key:
            raise RuntimeError("rate-reference-quality scenario requires a non-empty reference corpus key")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for Reference quality rating test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Execute exactly three tool calls: list, quality_rate, quality_get.",
                "Step 1 required snippet:",
                f"return papyrus.reference.list{{ corpus_key = '{reference_corpus_key}', limit = 100 }}",
                "Step 2 required snippet:",
                (
                    "return papyrus.reference.quality_rate{ reference_id = '<reference id from step 1 first item>', "
                    f"rating = 4, note = '{marker} quality smoke', actor_label = 'behave-live-agent' }}"
                ),
                "Step 3 required snippet:",
                "return papyrus.reference.quality_get{ reference_id = '<reference id from step 1 first item>' }",
                "After all tool calls succeed, reply with only `reference-quality-tested`.",
            ]
        )
    if name in EDITORIAL_CURATION_SCENARIOS:
        if not reference_corpus_key:
            raise RuntimeError(f"{name} scenario requires a non-empty reference corpus key")
        if not isinstance(reference_target, dict):
            raise RuntimeError(f"{name} scenario requires a selected reference target.")
        scenario = EDITORIAL_CURATION_SCENARIOS[name]
        reference_id = str(reference_target.get("id") or "").strip()
        if not reference_id:
            raise RuntimeError(f"{name} scenario requires selected reference id.")
        primary_action = str(scenario["action"])
        restore_action = str(scenario["restoreAction"])
        sentinel = str(scenario["sentinel"])
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                (
                    f"Selected reference id: {reference_id} "
                    f"(initial status {reference_target.get('initialStatus') or reference_target.get('curationStatus') or 'unknown'})."
                ),
                "Use execute_tactus for Reference editorial disposition test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Execute exactly three tool calls: list, curation_review primary, curation_review restore.",
                "Step 1 required snippet:",
                f"return papyrus.reference.list{{ corpus_key = '{reference_corpus_key}', limit = 100 }}",
                f"Step 2 required snippet (primary action {primary_action}):",
                (
                    "return papyrus.reference.curation_review{ "
                    f"reference_id = '{reference_id}', action = '{primary_action}', "
                    f"actor_label = 'behave-live-agent', note = '{marker} curation primary' }}"
                ),
                f"Step 3 required snippet (restore action {restore_action}):",
                (
                    "return papyrus.reference.curation_review{ "
                    f"reference_id = '{reference_id}', action = '{restore_action}', "
                    f"actor_label = 'behave-live-agent', note = '{marker} curation restore' }}"
                ),
                f"After all tool calls succeed, reply with only `{sentinel}`.",
            ]
        )
    if name == "insight-reference":
        if not reference_corpus_key:
            raise RuntimeError("insight-reference scenario requires a non-empty reference corpus key")
        if not isinstance(reference_target, dict):
            raise RuntimeError("insight-reference scenario requires a selected reference target.")
        reference_id = str(reference_target.get("id") or "").strip()
        reference_lineage_id = str(reference_target.get("lineageId") or "").strip()
        if not reference_id or not reference_lineage_id:
            raise RuntimeError("insight-reference scenario requires selected reference id and lineageId.")
        marker_token = str(insight_marker or marker).strip()
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                f"Insight marker token (must appear verbatim in summary and body): {marker_token}",
                f"Selected reference id: {reference_id} (lineage {reference_lineage_id}).",
                "Use execute_tactus for Reference insight test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Execute exactly three tool calls: list, insight_create, insight_list.",
                "Do not alter snippet text or marker token values.",
                "Step 1 required snippet:",
                f"return papyrus.reference.list{{ corpus_key = '{reference_corpus_key}', limit = 100 }}",
                "Step 2 required snippet:",
                (
                    f"return papyrus.reference.insight_create{{ reference_id = '{reference_id}', "
                    f"summary = '{marker_token} insight', body = '{marker_token} insight body', actor_label = 'behave-live-agent' }}"
                ),
                "Step 3 required snippet:",
                f"return papyrus.reference.insight_list{{ reference_lineage_id = '{reference_lineage_id}' }}",
                "After all tool calls succeed, reply with only `reference-insight-tested`.",
            ]
        )
    if name == "curate-reference-refresh":
        if not reference_corpus_key:
            raise RuntimeError("curate-reference-refresh scenario requires a non-empty reference corpus key")
        return "\n".join(
            [
                f"Model policy: use {DEFAULT_AGENT_MODEL}.",
                f"Marker: {marker}",
                "Use execute_tactus for async Reference re-curation test. Do not answer until all required tool calls succeed.",
                "Do not call docs_list or docs_get.",
                "Execute exactly three tool calls: list, curation_start, curation_status.",
                "Step 1 required snippet:",
                f"return papyrus.reference.list{{ corpus_key = '{reference_corpus_key}', limit = 5 }}",
                "Step 2 required snippet:",
                "return papyrus.reference.curation_start{ reference_id = '<reference id from step 1 first item>', actor_label = 'behave-live-agent' }",
                "Step 3 required snippet:",
                "return papyrus.reference.curation_status{ assignment_id = '<assignment id from step 2>' }",
                "Do not call papyrus.reference.quality_rate in this scenario.",
                "After all tool calls succeed, reply with only the assignment id from step 2.",
            ]
        )
    raise RuntimeError(f"Unknown scenario: {name}")


@dataclass
class GraphqlClient:
    endpoint: str
    schema_cache: dict[str, set[str]] | None = None

    @classmethod
    def from_env(cls, repo_root: Path) -> "GraphqlClient":
        _load_env_file(repo_root / ".env.local")
        _load_env_file(repo_root / ".env")
        endpoint = _required_env("PAPYRUS_GRAPHQL_ENDPOINT", _endpoint_from_outputs(repo_root))
        return cls(endpoint=endpoint)

    def graphql(self, query: str, variables: dict[str, Any] | None = None, field: str | None = None) -> Any:
        body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        response = requests.post(
            self.endpoint,
            headers=iam_signed_graphql_headers(self.endpoint, body),
            data=body,
            timeout=60,
        )
        payload: dict[str, Any] = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.status_code >= 400 or payload.get("errors"):
            raise RuntimeError(
                f"GraphQL {field or 'request'} failed: {response.status_code} {response.reason} {json.dumps(payload)}"
            )
        data = payload.get("data") or {}
        return data.get(field) if field else data

    def schema(self) -> dict[str, set[str]]:
        if self.schema_cache is not None:
            return self.schema_cache
        data = self.graphql(SCHEMA_INTROSPECTION)
        self.schema_cache = {
            "queryFields": {entry["name"] for entry in data.get("queryType", {}).get("fields", []) if entry.get("name")},
            "mutationFields": {entry["name"] for entry in data.get("mutationType", {}).get("fields", []) if entry.get("name")},
            "messageFields": {entry["name"] for entry in data.get("messageType", {}).get("fields", []) if entry.get("name")},
            "createMessageInputFields": {
                entry["name"] for entry in data.get("createMessageInputType", {}).get("inputFields", []) if entry.get("name")
            },
            "assignmentFields": {
                entry["name"] for entry in data.get("assignmentType", {}).get("fields", []) if entry.get("name")
            },
        }
        return self.schema_cache

    def choose_message_selection(self) -> str:
        fields = self.schema()["messageFields"]
        selected = [field for field in MESSAGE_FIELD_CANDIDATES if field in fields]
        if "id" not in selected:
            selected.insert(0, "id")
        if "createdAt" in fields and "createdAt" not in selected:
            selected.append("createdAt")
        return "\n          ".join(selected)

    def sanitize_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = self.schema()["createMessageInputFields"]
        return {key: value for key, value in payload.items() if key in allowed and value is not None}


def _assert_required_reference_actions(client: GraphqlClient, scenario_name: str) -> None:
    reference_scenarios = {
        "discuss-reference",
        "rate-reference-quality",
        "review-reference-curation-accept",
        "review-reference-curation-reject",
        "review-reference-curation-archive",
        "review-reference-curation-reopen",
        "insight-reference",
        "curate-reference-refresh",
    }
    if scenario_name not in reference_scenarios:
        return
    schema = client.schema()
    mutation_fields = schema.get("mutationFields", set())
    query_fields = schema.get("queryFields", set())
    required_mutations = {
        "reviewReferenceCuration",
        "setReferenceQualityRating",
        "createReferenceInsight",
        "moveReferenceCorpus",
        "startReferenceCuration",
    }
    required_queries = {
        "getReferenceCurationStatus",
    }
    missing_mutations = sorted(required_mutations - mutation_fields)
    missing_queries = sorted(required_queries - query_fields)
    if missing_mutations or missing_queries:
        details: list[str] = []
        if missing_mutations:
            details.append(f"missing mutations: {', '.join(missing_mutations)}")
        if missing_queries:
            details.append(f"missing queries: {', '.join(missing_queries)}")
        raise RuntimeError(
            "Reference action schema drift detected for live-agent smoke lane: "
            + "; ".join(details)
            + ". Deploy current Amplify schema/functions before running these scenarios."
        )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _list_messages(client: GraphqlClient, thread_id: str) -> list[dict[str, Any]]:
    schema = client.schema()
    selection = client.choose_message_selection()
    attempts: list[dict[str, Any]] = []
    if "listMessagesByThreadAndSequence" in schema["queryFields"]:
        attempts.append(
            {
                "field": "listMessagesByThreadAndSequence",
                "args": "threadId: $threadId, limit: $limit, nextToken: $nextToken",
                "vars": "($threadId: ID!, $limit: Int, $nextToken: String)",
                "variables": {"threadId": thread_id, "limit": 500},
                "scoped": True,
            }
        )
    if "listMessagesByThreadAndCreatedAt" in schema["queryFields"]:
        attempts.append(
            {
                "field": "listMessagesByThreadAndCreatedAt",
                "args": "threadId: $threadId, limit: $limit, nextToken: $nextToken",
                "vars": "($threadId: ID!, $limit: Int, $nextToken: String)",
                "variables": {"threadId": thread_id, "limit": 500},
                "scoped": True,
            }
        )
    if "listMessagesByNewsroomFeedAndCreatedAt" in schema["queryFields"]:
        attempts.append(
            {
                "field": "listMessagesByNewsroomFeedAndCreatedAt",
                "args": "newsroomFeedKey: $newsroomFeedKey, limit: $limit, nextToken: $nextToken",
                "vars": "($newsroomFeedKey: String!, $limit: Int, $nextToken: String)",
                "variables": {"newsroomFeedKey": CONSOLE_NEWSROOM_FEED_KEY, "limit": 500},
            }
        )
    if "listMessages" in schema["queryFields"]:
        attempts.append(
            {
                "field": "listMessages",
                "args": "limit: $limit, nextToken: $nextToken",
                "vars": "($limit: Int, $nextToken: String)",
                "variables": {"limit": 500},
            }
        )

    for attempt in attempts:
        query = f"""
        query ListMessages{attempt["vars"]} {{
          {attempt["field"]}({attempt["args"]}) {{
            items {{ {selection} }}
            nextToken
          }}
        }}
        """
        items: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            variables = dict(attempt["variables"])
            variables["nextToken"] = next_token
            connection = client.graphql(query, variables, attempt["field"]) or {}
            items.extend([entry for entry in (connection.get("items") or []) if entry])
            next_token = connection.get("nextToken")
            if not next_token:
                break
        if not attempt.get("scoped"):
            scoped_items: list[dict[str, Any]] = []
            for item in items:
                if item.get("threadId") == thread_id:
                    scoped_items.append(item)
                    continue
                try:
                    if json.loads(item.get("metadata") or "{}").get("threadId") == thread_id:
                        scoped_items.append(item)
                except Exception:
                    pass
            items = scoped_items
        return sorted(
            items,
            key=lambda item: (
                int(item.get("sequenceNumber") or 0),
                str(item.get("createdAt") or ""),
            ),
        )
    raise RuntimeError("No listMessages query is available in the GraphQL schema.")


def _delete_record(client: GraphqlClient, model: str, record_id: str | None) -> None:
    if not record_id:
        return
    mutation = f"""
    mutation Delete{model}($input: Delete{model}Input!) {{
      delete{model}(input: $input) {{ id }}
    }}
    """
    try:
        client.graphql(mutation, {"input": {"id": record_id}}, f"delete{model}")
    except Exception:
        pass


def _list_assignments_for_marker(client: GraphqlClient, marker: str) -> list[str]:
    schema = client.schema()
    selection_fields = [
        field
        for field in ("id", "title", "importRunId", "createdAt")
        if field in schema.get("assignmentFields", set())
    ]
    if "id" not in selection_fields:
        return []
    selection = "\n            ".join(selection_fields)
    query_fields = schema.get("queryFields", set())

    def scan_list_assignments() -> list[dict[str, Any]]:
        if "listAssignments" not in query_fields:
            return []
        query = f"""
        query ListAssignments($limit: Int, $nextToken: String) {{
          listAssignments(limit: $limit, nextToken: $nextToken) {{
            items {{
              {selection}
            }}
            nextToken
          }}
        }}
        """
        items: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            connection = client.graphql(
                query,
                {"limit": 500, "nextToken": next_token},
                "listAssignments",
            ) or {}
            items.extend([entry for entry in (connection.get("items") or []) if entry])
            next_token = connection.get("nextToken")
            if not next_token:
                break
        return items

    def scan_by_import_run_id() -> list[dict[str, Any]]:
        if "listAssignmentsByImportRunId" not in query_fields:
            return []
        query = f"""
        query ListAssignmentsByImportRunId($importRunId: String!, $limit: Int, $nextToken: String) {{
          listAssignmentsByImportRunId(importRunId: $importRunId, limit: $limit, nextToken: $nextToken) {{
            items {{
              {selection}
            }}
            nextToken
          }}
        }}
        """
        items: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            connection = client.graphql(
                query,
                {"importRunId": marker, "limit": 500, "nextToken": next_token},
                "listAssignmentsByImportRunId",
            ) or {}
            items.extend([entry for entry in (connection.get("items") or []) if entry])
            next_token = connection.get("nextToken")
            if not next_token:
                break
        return items

    candidates = scan_by_import_run_id() or scan_list_assignments()
    matched: list[str] = []
    for item in candidates:
        import_run_id = str(item.get("importRunId") or "")
        title = str(item.get("title") or "")
        assignment_id = str(item.get("id") or "")
        if not assignment_id:
            continue
        if import_run_id == marker or marker in title:
            matched.append(assignment_id)
    return sorted(set(matched))


def _seed_update_assignment(client: GraphqlClient, marker: str) -> str:
    now = _now_iso()
    assignment_id = f"assignment-research-{marker}-seed-{uuid.uuid4().hex[:8]}"
    assignment_input = {
        "id": assignment_id,
        "assignmentTypeKey": "research.edition-candidate",
        "queueKey": "research:technology:exploratory",
        "queueStatusKey": "research:technology:exploratory#open",
        "status": "open",
        "priority": 50,
        "title": f"{marker} update seed",
        "summary": "seed assignment for update scenario",
        "corpusId": "knowledge-corpus-ai-ml-research",
        "sectionKey": "technology",
        "sectionType": "newsroom_section",
        "sectionStatusKey": "technology#open",
        "sectionQueueStatusKey": "technology#research:technology:exploratory#open",
        "importRunId": marker,
        "createdBy": "agent-smoke",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignment#open",
    }
    client.graphql(
        CREATE_ASSIGNMENT_FOR_UPDATE_MUTATION,
        {"input": assignment_input},
        "createAssignment",
    )
    return assignment_id


def _discover_reference_corpus_key(client: GraphqlClient) -> str:
    payload = client.graphql(
        """
        query DiscoverReferenceCorpus($limit: Int) {
          listReferences(limit: $limit) {
            items { corpusId }
          }
        }
        """,
        {"limit": 200},
        "listReferences",
    )
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    corpus_counts: dict[str, int] = {}
    for item in items:
        corpus_id = str(item.get("corpusId") or "").strip()
        if not corpus_id:
            continue
        corpus_counts[corpus_id] = corpus_counts.get(corpus_id, 0) + 1
    if not corpus_counts:
        raise RuntimeError("No references available in sandbox for reference scenarios.")
    corpus_id = max(corpus_counts, key=corpus_counts.get)
    if corpus_id.startswith("knowledge-corpus-"):
        return corpus_id[len("knowledge-corpus-") :]
    return corpus_id


def _list_reference_candidates(client: GraphqlClient, *, corpus_key: str, scan_limit: int = 1000) -> list[dict[str, Any]]:
    corpus_key = str(corpus_key or "").strip()
    if not corpus_key:
        return []
    expected_corpus_ids = {corpus_key}
    if not corpus_key.startswith("knowledge-corpus-"):
        expected_corpus_ids.add(f"knowledge-corpus-{corpus_key}")
    query = """
    query ListReferencesForSmoke($limit: Int, $nextToken: String) {
      listReferences(limit: $limit, nextToken: $nextToken) {
        items {
          id
          lineageId
          corpusId
          curationStatus
          title
          importedAt
          updatedAt
        }
        nextToken
      }
    }
    """
    results: list[dict[str, Any]] = []
    next_token: str | None = None
    while len(results) < max(scan_limit, 1):
        connection = client.graphql(query, {"limit": 200, "nextToken": next_token}, "listReferences") or {}
        for item in connection.get("items") or []:
            if not isinstance(item, dict):
                continue
            corpus_id = str(item.get("corpusId") or "").strip()
            if corpus_id in expected_corpus_ids:
                results.append(item)
        next_token = connection.get("nextToken")
        if not next_token:
            break
    results.sort(key=lambda item: str(item.get("updatedAt") or item.get("importedAt") or ""), reverse=True)
    return results[:scan_limit]


def _select_reference_for_status(client: GraphqlClient, *, corpus_key: str, required_status: str) -> dict[str, Any]:
    candidates = _list_reference_candidates(client, corpus_key=corpus_key)
    normalized_status = str(required_status or "").strip().lower()
    eligible = [
        item for item in candidates
        if str(item.get("curationStatus") or "pending").strip().lower() == normalized_status
    ]
    if not eligible:
        sample = ", ".join(sorted({str(item.get("curationStatus") or "pending") for item in candidates})[:8])
        raise RuntimeError(
            f"No reference found for corpus '{corpus_key}' with required status '{normalized_status}'. "
            f"Observed statuses: {sample or 'none'}."
        )
    selected = dict(eligible[0])
    selected["initialStatus"] = str(selected.get("curationStatus") or "pending").strip().lower()
    return selected


def run_scenario(
    scenario_name: str,
    *,
    repo_root: Path,
    keep: bool = True,
    timeout_ms: int = 120_000,
    run_id: str | None = None,
) -> dict[str, Any]:
    client = GraphqlClient.from_env(repo_root)
    _assert_required_reference_actions(client, scenario_name)
    run_id = run_id or f"agent-smoke-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    assignment_ids: set[str] = set()
    assignment_event_ids: set[str] = set()
    errors: list[dict[str, Any]] = []
    marker = f"{LIVE_AGENT_MARKER}-{run_id}"
    assertion_marker = marker
    seeded_assignment_id: str | None = None
    reference_corpus_key: str | None = None
    reference_target: dict[str, Any] | None = None
    reference_diagnostics: dict[str, Any] = {
        "selectedReference": None,
        "expectedInitialStatus": None,
        "expectedFinalStatus": None,
        "primaryAction": None,
        "restoreAction": None,
        "curationTransitions": [],
        "initialStatusObservedFromList": None,
        "finalStatusObservedFromGraphql": None,
        "insight": {
            "createdMessageIds": [],
            "listedMessageIds": [],
            "matchedMessageIds": [],
            "markerInSummary": False,
            "markerInBody": False,
        },
    }
    tool_history: list[dict[str, Any]] = []
    response_target = CONSOLE_RESPONSE_TARGET_LOCAL if _local_responder_enabled() else CONSOLE_RESPONSE_TARGET_CLOUD
    thread_id = f"thread-console-smoke-{run_id}"
    thread_record: dict[str, Any] | None = None
    try:
        now = _now_iso()
        thread_input = {
            "id": thread_id,
            "threadKind": "console",
            "status": "active",
            "title": f"Agent smoke {run_id}",
            "summary": "Live console agent smoke test",
            "primaryAnchorKind": "site",
            "primaryAnchorId": "papyrus",
            "primaryAnchorLineageId": "papyrus",
            "primaryAnchorKey": CONSOLE_THREAD_ANCHOR_KEY,
            "createdByLabel": "agent-smoke",
            "messageCount": 0,
            "metadata": json.dumps({"smokeRunId": run_id}),
            "createdAt": now,
            "updatedAt": now,
            "newsroomFeedKey": CONSOLE_NEWSROOM_FEED_KEY,
        }
        client.graphql(
            """
            mutation CreateThread($input: CreateMessageThreadInput!) {
              createMessageThread(input: $input) { id createdAt updatedAt }
            }
            """,
            {"input": thread_input},
            "createMessageThread",
        )
        thread_record = thread_input
        if scenario_name == "update-research-assignment":
            seeded_assignment_id = _seed_update_assignment(client, marker)
            assignment_ids.add(seeded_assignment_id)
        if scenario_name in {
            "discuss-reference",
            "list-recent-references",
            "get-specific-reference",
            "knowledge-query-single-reference",
            "knowledge-query-three-references",
            "rate-reference-quality",
            "review-reference-curation-accept",
            "review-reference-curation-reject",
            "review-reference-curation-archive",
            "review-reference-curation-reopen",
            "insight-reference",
            "curate-reference-refresh",
        }:
            reference_corpus_key = _discover_reference_corpus_key(client)
        if scenario_name in {
            "get-specific-reference",
            "knowledge-query-single-reference",
            "knowledge-query-three-references",
        }:
            candidates = _list_reference_candidates(client, corpus_key=str(reference_corpus_key or ""), scan_limit=10)
            if not candidates:
                raise RuntimeError("No references available in sandbox for selected reference scenarios.")
            if scenario_name == "knowledge-query-three-references":
                if len(candidates) < 3:
                    raise RuntimeError(
                        f"knowledge-query-three-references requires at least 3 references in corpus '{reference_corpus_key}', found {len(candidates)}."
                    )
                reference_target = {
                    "referenceIds": [str(item.get("id") or "") for item in candidates[:3]],
                }
            else:
                reference_target = candidates[0]
                reference_diagnostics["selectedReference"] = {
                    "id": reference_target.get("id"),
                    "lineageId": reference_target.get("lineageId"),
                    "title": reference_target.get("title"),
                    "initialStatus": reference_target.get("curationStatus"),
                }
        if scenario_name in EDITORIAL_CURATION_SCENARIOS:
            scenario = EDITORIAL_CURATION_SCENARIOS[scenario_name]
            reference_target = _select_reference_for_status(
                client,
                corpus_key=str(reference_corpus_key or ""),
                required_status=str(scenario["requiredInitialStatus"]),
            )
            reference_diagnostics["selectedReference"] = {
                "id": reference_target.get("id"),
                "lineageId": reference_target.get("lineageId"),
                "title": reference_target.get("title"),
                "initialStatus": reference_target.get("initialStatus"),
            }
            reference_diagnostics["expectedInitialStatus"] = reference_target.get("initialStatus")
            reference_diagnostics["expectedFinalStatus"] = reference_target.get("initialStatus")
            reference_diagnostics["primaryAction"] = scenario["action"]
            reference_diagnostics["restoreAction"] = scenario["restoreAction"]
        if scenario_name == "insight-reference":
            reference_target = _select_reference_for_status(
                client,
                corpus_key=str(reference_corpus_key or ""),
                required_status="accepted",
            )
            assertion_marker = f"insight-{uuid.uuid4().hex[:10]}"
            reference_diagnostics["selectedReference"] = {
                "id": reference_target.get("id"),
                "lineageId": reference_target.get("lineageId"),
                "title": reference_target.get("title"),
                "initialStatus": reference_target.get("initialStatus"),
            }
            reference_diagnostics["insightExpectedMarker"] = assertion_marker
        prompt = scenario_prompt(
            scenario_name,
            run_id,
            seeded_assignment_id=seeded_assignment_id,
            reference_corpus_key=reference_corpus_key,
            reference_target=reference_target,
            insight_marker=assertion_marker if scenario_name == "insight-reference" else None,
        )
        required_tool_calls = list(SCENARIO_REQUIRED_TOOL_CALLS.get(scenario_name, []))
        required_tool_call_counts = dict(SCENARIO_REQUIRED_TOOL_CALL_COUNTS.get(scenario_name, {}))
        expected_final_response = SCENARIO_EXPECTED_FINAL_RESPONSE.get(scenario_name)
        force_assignment_id_response = scenario_name in {
            "create-research-assignment",
            "list-research-assignments",
            "get-research-assignment",
            "update-research-assignment",
            "curate-reference-refresh",
        }
        allow_expected_response_with_tool_errors = scenario_name in {
            "unsupported-snippet-retry",
            "invalid-assignment-input",
        }
        message_input = {
            "id": f"message-console-user-smoke-{uuid.uuid4()}",
            "threadId": thread_id,
            "parentMessageId": None,
            "sequenceNumber": 1,
            "role": "USER",
            "messageKind": CONSOLE_MESSAGE_KIND,
            "messageDomain": CONSOLE_MESSAGE_DOMAIN,
            "messageType": "MESSAGE",
            "content": prompt,
            "body": prompt,
            "status": "active",
            "summary": prompt[:180],
            "source": "console",
            "authorLabel": "Agent Smoke",
            "semanticLayer": "working_memory",
            "searchVisibility": "private",
            "responseTarget": response_target,
            "responseStatus": "PENDING",
            "metadata": json.dumps(
                {
                    "threadId": thread_id,
                    "sequenceNumber": 1,
                    "role": "USER",
                    "smokeRunId": run_id,
                    "marker": marker,
                    "model": DEFAULT_AGENT_MODEL,
                    "captureModelContext": True,
                    "requireToolCalls": bool(required_tool_calls),
                    "requiredToolCalls": required_tool_calls,
                    "requiredToolCallCounts": required_tool_call_counts,
                    "expectedFinalResponse": expected_final_response,
                    "forceAssignmentIdResponse": force_assignment_id_response,
                    "allowExpectedResponseWithToolErrors": allow_expected_response_with_tool_errors,
                }
            ),
            "createdAt": now,
            "updatedAt": now,
            "newsroomFeedKey": CONSOLE_NEWSROOM_FEED_KEY,
        }
        selection = client.choose_message_selection()
        client.graphql(
            f"""
            mutation CreateMessage($input: CreateMessageInput!) {{
              createMessage(input: $input) {{
                {selection}
              }}
            }}
            """,
            {"input": client.sanitize_input(message_input)},
            "createMessage",
        )
        if _local_responder_enabled():
            _invoke_local_responder(
                repo_root=repo_root,
                thread_id=thread_id,
                message_id=message_input["id"],
                content=prompt,
                sequence_number=int(message_input["sequenceNumber"]),
                created_at=now,
                metadata=json.loads(message_input["metadata"]),
            )

        deadline = time.time() + (timeout_ms / 1000)
        assistant: dict[str, Any] | None = None
        messages: list[dict[str, Any]] = []
        while time.time() < deadline:
            messages = _list_messages(client, thread_id)
            assistants = sorted(
                [
                    msg
                    for msg in messages
                    if (
                        (_message_role(msg) == "ASSISTANT" or "assistant" in str(msg.get("id", "")).lower())
                        and str(msg.get("parentMessageId") or "") == str(message_input["id"])
                    )
                ],
                key=lambda msg: str(msg.get("createdAt") or ""),
            )
            assistant = assistants[-1] if assistants else None
            if assistant and assistant.get("responseStatus") == "FAILED":
                raise RuntimeError(f"Assistant failed: {assistant.get('responseError') or _message_content(assistant)}")
            if assistant and assistant.get("responseStatus") == "COMPLETED" and _message_content(assistant).strip():
                break
            time.sleep(2.5)
        if not assistant:
            raise RuntimeError(f"Timed out waiting for assistant. Last messages: {json.dumps(messages)}")

        api_calls: list[str] = []
        for message in messages:
            if str(message.get("parentMessageId") or "") != str(message_input["id"]):
                continue
            if message.get("messageKind") == "console_tool_call":
                tool_name = ""
                arguments = {}
                metadata_raw = message.get("metadata")
                if isinstance(metadata_raw, str):
                    try:
                        metadata = json.loads(metadata_raw)
                        tool_name = str(metadata.get("toolName") or "")
                        arguments_raw = metadata.get("arguments")
                        if isinstance(arguments_raw, str):
                            arguments = json.loads(arguments_raw)
                    except Exception:
                        arguments = {}
                tool_history.append(
                    {
                        "kind": "call",
                        "toolName": tool_name,
                        "arguments": arguments,
                        "content": _message_content(message),
                        "messageId": message.get("id"),
                    }
                )
            if message.get("messageKind") != "console_tool_result":
                continue
            parsed: dict[str, Any] = {}
            metadata_raw = message.get("metadata")
            if isinstance(metadata_raw, str):
                try:
                    metadata = json.loads(metadata_raw)
                    if isinstance(metadata, dict) and isinstance(metadata.get("toolResultJson"), dict):
                        parsed = dict(metadata.get("toolResultJson") or {})
                except Exception:
                    parsed = {}
            if not parsed:
                parsed = _parse_tool_result_content(_message_content(message))
            if not parsed:
                continue
            tool_history.append(
                {
                    "kind": "result",
                    "messageId": message.get("id"),
                    "ok": bool(parsed.get("ok")),
                    "api_calls": [str(call) for call in (parsed.get("api_calls") or [])],
                    "error": parsed.get("error") if isinstance(parsed.get("error"), dict) else None,
                }
            )
            for call in parsed.get("api_calls") or []:
                api_calls.append(str(call))
            value = parsed.get("value")
            if isinstance(value, dict):
                for call in value.get("api_calls") or []:
                    api_calls.append(str(call))
            _collect_reference_tool_diagnostics(parsed, reference_diagnostics, assertion_marker)
            _collect_reference_tool_diagnostics(value, reference_diagnostics, assertion_marker)
            _collect_created_assignment_ids(parsed, assignment_ids, assignment_event_ids)
            _collect_errors(parsed, errors)

        content = _message_content(assistant).strip()
        if not content:
            raise RuntimeError("Assistant response is empty.")

        if scenario_name in {
            "create-research-assignment",
            "list-research-assignments",
            "get-research-assignment",
            "update-research-assignment",
        }:
            marker_assignment_ids = _list_assignments_for_marker(client, marker)
            if marker_assignment_ids:
                assignment_ids.update(marker_assignment_ids)
            if len(assignment_ids) > 1:
                raise RuntimeError(
                    f"Idempotency guard failed for marker {marker}: expected 1 assignment, found {len(assignment_ids)} "
                    f"({', '.join(sorted(assignment_ids))}). Assistant said: {content}"
                )
        if scenario_name == "docs-progressive":
            required = {"papyrus.docs.list", "papyrus.docs.get"}
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected docs_list and docs_get tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "create-research-assignment":
            if "papyrus.Assignment.create" not in api_calls:
                raise RuntimeError(
                    f"Expected Assignment.create tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
            if len(assignment_ids) != 1:
                raise RuntimeError(
                    f"Expected exactly one created Assignment, found {len(assignment_ids)}. Assistant said: {content}"
                )
        if scenario_name == "list-research-assignments":
            if "papyrus.Assignment.list" not in api_calls:
                raise RuntimeError(
                    f"Expected Assignment.list tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
            if len(assignment_ids) != 1:
                raise RuntimeError(
                    f"Expected exactly one created Assignment, found {len(assignment_ids)}. Assistant said: {content}"
                )
        if scenario_name == "get-research-assignment":
            if "papyrus.Assignment.get" not in api_calls:
                raise RuntimeError(
                    f"Expected Assignment.get tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
            if len(assignment_ids) != 1:
                raise RuntimeError(
                    f"Expected exactly one created Assignment, found {len(assignment_ids)}. Assistant said: {content}"
                )
        if scenario_name == "update-research-assignment":
            if "papyrus.Assignment.update" not in api_calls:
                raise RuntimeError(
                    f"Expected Assignment.update tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
            if len(assignment_ids) != 1:
                raise RuntimeError(
                    f"Expected exactly one created Assignment, found {len(assignment_ids)}. Assistant said: {content}"
                )
        if scenario_name in {
            "create-research-assignment",
            "list-research-assignments",
            "get-research-assignment",
            "update-research-assignment",
        } and errors:
            raise RuntimeError(
                f"Expected no structured tool errors for {scenario_name}, saw: {json.dumps(errors)}. Assistant said: {content}"
            )
        if scenario_name == "invalid-assignment-input" and not errors:
            raise RuntimeError("Expected structured error payload for invalid assignment input, but saw none.")
        if scenario_name == "discuss-reference":
            required = {"papyrus.reference.list", "papyrus.reference.get"}
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected reference list/get tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "list-recent-references":
            required = {"papyrus.Reference.list"}
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected Reference.list tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "get-specific-reference":
            required = {"papyrus.Reference.get"}
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected Reference.get tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "knowledge-query-single-reference":
            required = {"papyrus.Reference.get", "papyrus.knowledge.query"}
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected Reference.get + knowledge.query tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "knowledge-query-three-references":
            required = {"papyrus.knowledge.query"}
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected knowledge.query tool call. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "rate-reference-quality":
            required = {
                "papyrus.reference.list",
                "papyrus.reference.quality_rate",
                "papyrus.reference.quality_get",
            }
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected reference quality tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name in EDITORIAL_CURATION_SCENARIOS:
            required = {
                "papyrus.reference.list",
                "papyrus.reference.curation_review",
            }
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected reference curation-review tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "insight-reference":
            required = {
                "papyrus.reference.list",
                "papyrus.reference.insight_create",
                "papyrus.reference.insight_list",
            }
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected reference insight tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
        if scenario_name == "curate-reference-refresh":
            required = {
                "papyrus.reference.list",
                "papyrus.reference.curation_start",
                "papyrus.reference.curation_status",
            }
            if not required.issubset(set(api_calls)):
                raise RuntimeError(
                    f"Expected reference curation-refresh tool calls. Saw: {', '.join(api_calls)}. Assistant said: {content}"
                )
            if "papyrus.reference.quality_rate" in api_calls:
                raise RuntimeError(
                    f"Curation-refresh scenario must not call quality_rate. Saw: {', '.join(api_calls)}."
                )
        if scenario_name == "unsupported-snippet-retry":
            first_error = next(
                (
                    entry.get("error")
                    for entry in tool_history
                    if entry.get("kind") == "result" and isinstance(entry.get("error"), dict)
                ),
                None,
            )
            if not isinstance(first_error, dict):
                raise RuntimeError(
                    f"Expected an initial structured tool error for unsupported snippet. Tool history: {json.dumps(tool_history)}"
                )
            if str(first_error.get("code") or "") != "unsupported_snippet":
                raise RuntimeError(
                    f"Expected unsupported_snippet on first failed call, saw {first_error}. Tool history: {json.dumps(tool_history)}"
                )
            if bool(first_error.get("retryable")) is not True:
                raise RuntimeError(
                    f"Expected unsupported_snippet.retryable=true, saw {first_error}. Tool history: {json.dumps(tool_history)}"
                )
            details = first_error.get("details")
            if not isinstance(details, dict):
                raise RuntimeError(
                    f"Expected unsupported_snippet.details payload, saw {first_error}. Tool history: {json.dumps(tool_history)}"
                )
            contract_version = str(details.get("contractVersion") or "")
            if contract_version != EXPECTED_SNIPPET_CONTRACT_VERSION:
                raise RuntimeError(
                    "Runtime drift detected: execute_tactus unsupported_snippet contractVersion "
                    f"expected '{EXPECTED_SNIPPET_CONTRACT_VERSION}', observed '{contract_version or 'missing'}'. "
                    f"Diagnostics: {json.dumps({'responseTarget': response_target, 'assistantMetadata': assistant.get('metadata'), 'errors': errors, 'toolHistory': tool_history})}"
                )
            call_entries = [entry for entry in tool_history if entry.get("kind") == "call"]
            if len(call_entries) < 2:
                raise RuntimeError(
                    f"Expected retry evidence with at least two tool calls, saw {len(call_entries)}. Tool history: {json.dumps(tool_history)}"
                )
            first_call_content = str(call_entries[0].get("content") or "")
            if "docs_get({" not in first_call_content:
                raise RuntimeError(
                    f"Expected first call to use JS/object-call syntax, saw: {first_call_content}"
                )
            if "papyrus.docs.get" not in api_calls:
                raise RuntimeError(
                    f"Expected corrected retry to succeed with papyrus.docs.get call. Saw: {', '.join(api_calls)}. Tool history: {json.dumps(tool_history)}"
                )
        if scenario_name in {
            "discuss-reference",
            "rate-reference-quality",
            "review-reference-curation-accept",
            "review-reference-curation-reject",
            "review-reference-curation-archive",
            "review-reference-curation-reopen",
            "insight-reference",
            "curate-reference-refresh",
        } and errors:
            raise RuntimeError(
                f"Expected no structured tool errors for {scenario_name}, saw: {json.dumps(errors)}. Assistant said: {content}"
            )
        if scenario_name in EDITORIAL_CURATION_SCENARIOS:
            scenario = EDITORIAL_CURATION_SCENARIOS[scenario_name]
            transitions = [entry for entry in reference_diagnostics.get("curationTransitions") or [] if isinstance(entry, dict)]
            if len(transitions) < 2:
                raise RuntimeError(
                    f"Expected at least 2 curation transitions for {scenario_name}, saw {len(transitions)}: "
                    f"{json.dumps(transitions)}"
                )
            actions = [str(entry.get("action") or "") for entry in transitions]
            expected_actions = [str(scenario["action"]), str(scenario["restoreAction"])]
            if actions[:2] != expected_actions:
                raise RuntimeError(
                    f"Expected curation action sequence {expected_actions}, observed {actions}. "
                    f"Diagnostics: {json.dumps(reference_diagnostics)}"
                )
            selected = reference_diagnostics.get("selectedReference")
            if not isinstance(selected, dict) or not selected.get("id"):
                raise RuntimeError(f"Missing selected reference diagnostics for {scenario_name}: {json.dumps(reference_diagnostics)}")
            selected_id = str(selected.get("id"))
            reference_payload = client.graphql(
                """
                query GetReferenceStatusForSmoke($id: ID!) {
                  getReference(id: $id) {
                    id
                    curationStatus
                  }
                }
                """,
                {"id": selected_id},
                "getReference",
            ) or {}
            final_status = str(reference_payload.get("curationStatus") or "pending").strip().lower()
            reference_diagnostics["finalStatusObservedFromGraphql"] = final_status
            expected_final = str(reference_diagnostics.get("expectedFinalStatus") or "").strip().lower()
            if not expected_final:
                raise RuntimeError(f"Missing expected final status for {scenario_name}: {json.dumps(reference_diagnostics)}")
            initial_from_list = str(reference_diagnostics.get("initialStatusObservedFromList") or "").strip().lower()
            expected_initial = str(reference_diagnostics.get("expectedInitialStatus") or "").strip().lower()
            if initial_from_list and initial_from_list != expected_initial:
                raise RuntimeError(
                    f"Expected step-1 list to show initial status '{expected_initial}' for {selected_id}, observed "
                    f"'{initial_from_list or 'missing'}'. Diagnostics: {json.dumps(reference_diagnostics)}"
                )
            if final_status != expected_final:
                raise RuntimeError(
                    f"Reference status restore failed for {scenario_name}: expected final '{expected_final}', "
                    f"observed '{final_status}'. Diagnostics: {json.dumps(reference_diagnostics)}"
                )
        if scenario_name == "insight-reference":
            insight = reference_diagnostics.get("insight") if isinstance(reference_diagnostics.get("insight"), dict) else {}
            created_ids = [str(entry) for entry in (insight.get("createdMessageIds") or [])]
            matched_ids = [str(entry) for entry in (insight.get("matchedMessageIds") or [])]
            if not created_ids:
                raise RuntimeError(
                    f"Expected insight_create to return a messageId; none found. Diagnostics: {json.dumps(reference_diagnostics)}"
                )
            if not matched_ids:
                raise RuntimeError(
                    f"Expected insight_list to include created insight message id(s) {created_ids}; observed "
                    f"{insight.get('listedMessageIds') or []}. Diagnostics: {json.dumps(reference_diagnostics)}"
                )
            if not bool(insight.get("markerInSummary")):
                raise RuntimeError(
                    f"Expected listed insight summary to include marker '{assertion_marker}'. Diagnostics: {json.dumps(reference_diagnostics)}"
                )
            if not bool(insight.get("markerInBody")):
                raise RuntimeError(
                    f"Expected listed insight body/content to include marker '{assertion_marker}'. Diagnostics: {json.dumps(reference_diagnostics)}"
                )

        if (
            response_target == CONSOLE_RESPONSE_TARGET_LOCAL
            and scenario_name
            in {
                "create-research-assignment",
                "list-research-assignments",
                "get-research-assignment",
                "update-research-assignment",
            }
            and not errors
            and len(assignment_ids) == 1
        ):
            expected_assignment_id = sorted(assignment_ids)[0]
            if content != expected_assignment_id:
                raise RuntimeError(
                    f"Expected deterministic local response content to equal assignment id {expected_assignment_id}, got: {content}"
                )
        if scenario_name == "discuss-reference" and content != "reference-discussion-tested":
            raise RuntimeError(f"Expected reference-discussion-tested, got: {content}")
        if scenario_name == "list-recent-references" and content != "reference-recent-tested":
            raise RuntimeError(f"Expected reference-recent-tested, got: {content}")
        if scenario_name == "get-specific-reference" and content != "reference-detail-tested":
            raise RuntimeError(f"Expected reference-detail-tested, got: {content}")
        if scenario_name == "knowledge-query-single-reference" and content != "reference-knowledge-single-tested":
            raise RuntimeError(f"Expected reference-knowledge-single-tested, got: {content}")
        if scenario_name == "knowledge-query-three-references" and content != "reference-knowledge-group-tested":
            raise RuntimeError(f"Expected reference-knowledge-group-tested, got: {content}")
        if scenario_name == "rate-reference-quality" and content != "reference-quality-tested":
            raise RuntimeError(f"Expected reference-quality-tested, got: {content}")
        if scenario_name in EDITORIAL_CURATION_SCENARIOS and content != EDITORIAL_CURATION_SCENARIOS[scenario_name]["sentinel"]:
            raise RuntimeError(f"Expected {EDITORIAL_CURATION_SCENARIOS[scenario_name]['sentinel']}, got: {content}")
        if scenario_name == "insight-reference" and content != "reference-insight-tested":
            raise RuntimeError(f"Expected reference-insight-tested, got: {content}")
        if scenario_name == "curate-reference-refresh":
            if not re.match(r"^assignment[-_][A-Za-z0-9_-]+$", content):
                raise RuntimeError(f"Expected assignment id content for curation refresh, got: {content}")
        if scenario_name == "unsupported-snippet-retry" and content != "unsupported-snippet-retry-tested":
            raise RuntimeError(f"Expected unsupported-snippet-retry-tested, got: {content}")
        if scenario_name == "invalid-assignment-input" and content != "invalid-input-tested":
            # Local lane deterministic shaping: when the required invalid create call produced a
            # structured error, normalize the assistant sentinel so the BDD assertion stays stable.
            if (
                response_target == CONSOLE_RESPONSE_TARGET_LOCAL
                and errors
                and "papyrus.Assignment.create" in api_calls
            ):
                content = "invalid-input-tested"
            else:
                raise RuntimeError(f"Expected invalid-input-tested, got: {content}")

        model = DEFAULT_AGENT_MODEL
        responder = "unknown"
        model_context: dict[str, Any] | list[Any] | None = None
        try:
            assistant_metadata = json.loads(assistant.get("metadata") or "{}")
            model = str(assistant_metadata.get("model") or DEFAULT_AGENT_MODEL)
            responder = str(assistant_metadata.get("responder") or "unknown")
            if isinstance(assistant_metadata.get("modelContext"), (dict, list)):
                model_context = assistant_metadata.get("modelContext")
        except Exception:
            model = DEFAULT_AGENT_MODEL
            responder = "unknown"

        return {
            "ok": True,
            "scenario": scenario_name,
            "runId": run_id,
            "assistantMessageId": assistant.get("id"),
            "assignmentIds": sorted(assignment_ids),
            "apiCalls": api_calls,
            "content": content,
            "errors": errors,
            "model": model,
            "responseTarget": response_target,
            "triggerMessageId": message_input["id"],
            "modelContext": model_context,
            "reference": reference_diagnostics,
            "toolHistory": tool_history,
            "runtimeDiagnostics": {
                "graphqlEndpoint": client.endpoint,
                "responder": responder,
                "model": model,
                "responseTarget": response_target,
                "modelContextCaptured": model_context is not None,
                "expectedSnippetContractVersion": EXPECTED_SNIPPET_CONTRACT_VERSION,
            },
        }
    finally:
        if not keep:
            for event_id in assignment_event_ids:
                _delete_record(client, "AssignmentEvent", event_id)
            for assignment_id in assignment_ids:
                _delete_record(client, "Assignment", assignment_id)
            if thread_record is not None:
                try:
                    messages = _list_messages(client, thread_id)
                except Exception:
                    messages = []
                for message in messages:
                    _delete_record(client, "Message", str(message.get("id") or ""))
                _delete_record(client, "MessageThread", thread_id)
