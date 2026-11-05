"""Typed site-tool boundary. Authentication and transactional writes belong to the site adapter.

The adapter is bound to one verified request, not a process-wide credential. Conditional
writes must be implemented atomically by that adapter; this module never emulates them
with a read followed by an unconditional update.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Principal:
    kind: str
    subject: str
    site_subject: str | None = None
    is_agent: bool = False
    delegated_by: str | None = None


def _schema(required: dict[str, dict], optional: dict[str, dict] | None = None) -> dict:
    return {"type": "object", "properties": {**required, **(optional or {})},
            "required": list(required), "additionalProperties": False}


S = {"type": "string", "minLength": 1}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}
STARS = {"type": "integer", "minimum": 1, "maximum": 5}
LINEAGE = {"lineageId": S}
VERSION = {**LINEAGE, "expectedCurrentVersionId": S}
REVISION = {**VERSION, "expectedRevision": S}
TOOLS = {
    "reference_search": ("staff", _schema({"query": S}, {"limit": LIMIT})),
    "reference_get": ("staff", _schema(LINEAGE)),
    "concept_search": ("staff", _schema({"query": S}, {"limit": LIMIT})),
    "concept_get": ("staff", _schema({"id": S})),
    "story_search": ("staff", _schema({"query": S}, {"limit": LIMIT})),
    "story_get": ("staff", _schema(LINEAGE)),
    "story_versions": ("staff", _schema(LINEAGE)),
    "story_evidence": ("staff", _schema(LINEAGE)),
    "story_next": ("staff", _schema(LINEAGE)),
    "assignments_list": ("staff", _schema({}, {"storyLineageId": S})),
    "assignment_get": ("staff", _schema({"id": S})),
    "story_save_draft": ("staff", _schema({**VERSION, "body": S, "reason": S}, {"frontMatter": {"type": "string"}})),
    "reference_decide": ("staff", _schema({**REVISION, "decision": {"type": "string", "enum": ["accept", "reject"]}})),
    "reference_star": ("staff", _schema({**REVISION, "stars": STARS})),
    "story_star": ("staff", _schema({**REVISION, "stars": STARS})),
    "reviews_list": ("staff", _schema({}, {"state": S, "mode": S})),
    "review_get": ("staff", _schema({"id": S})),
    "review_answer": ("staff", _schema({"id": S, "decision": S}, {"feedback": S, "steer": S})),
    "story_publish": ("staff", _schema(VERSION)),
    "reader_comment": ("reader", _schema({"subject": S, "body": S}, {"parent": S, "ratingContext": {"type": "object"}})),
    "reader_submit": ("reader", _schema({"url": S, "title": S}, {"kind": S, "note": S})),
}


DESCRIPTIONS = {
    "reference_search": "Find References matching a phrase.", "reference_get": "Read a current Reference.",
    "concept_search": "Find concepts matching a phrase.", "concept_get": "Read a concept.",
    "story_search": "Find Stories matching a phrase.", "story_get": "Read the current version of a Story.",
    "story_versions": "List a Story's saved versions.", "story_evidence": "Read the evidence linked to a Story.",
    "story_next": "Read the next steps in the Story procedure.", "assignments_list": "List Assignments.",
    "assignment_get": "Read an Assignment.", "story_save_draft": "Save a new immutable Story draft.",
    "reference_decide": "Accept or reject a Reference.", "reference_star": "Rate a Reference with stars.",
    "story_star": "Rate a Story with stars.", "reviews_list": "List review requests.",
    "review_get": "Read a review request.", "review_answer": "Answer a review request.",
    "story_publish": "Publish a Story through its existing gates.",
    "reader_comment": "Comment on a subject under the site's reader policy.",
    "reader_submit": "Submit a link under the site's reader policy.",
}


def _story_fields(row: dict) -> dict:
    allowed = {"id", "lineageId", "versionNumber", "versionState", "versionCreatedAt", "versionCreatedBy", "changeReason", "updatedAt", "title", "headline", "type", "section", "stage", "status", "bodyMarkus"}
    return {key: value for key, value in row.items() if key in allowed}


def list_tools(principal: Principal, *, staff: Any = None, reader: Callable[[dict], dict] | None = None) -> list[dict[str, Any]]:
    _identity(principal)
    return [{"name": name, "description": DESCRIPTIONS[name], "inputSchema": schema}
            for name, (kind, schema) in TOOLS.items() if kind == principal.kind
            and ((kind == "reader" and reader is not None) or (kind == "staff" and callable(getattr(staff, name, None)) and name in getattr(staff, "available_tools", ())))]


def _identity(principal: Principal) -> None:
    if principal.kind not in ("staff", "reader") or not principal.subject:
        raise PermissionError("A verified site identity is required.")
    if principal.kind == "reader" and not principal.site_subject:
        raise PermissionError("A verified site subject is required.")


def _validate(schema: dict, args: Any) -> None:
    if not isinstance(args, dict) or set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
        raise ValueError("Invalid tool arguments.")
    for key, value in args.items():
        rule = schema["properties"][key]
        kind = rule["type"]
        if ((kind == "string" and (not isinstance(value, str) or len(value) < rule.get("minLength", 0)))
            or (kind == "integer" and (type(value) is not int or value < rule.get("minimum", value) or value > rule.get("maximum", value)))
            or (kind == "object" and not isinstance(value, dict))
            or ("enum" in rule and value not in rule["enum"])):
            raise ValueError(f"Invalid argument: {key}.")


def call_tool(principal: Principal, name: str, arguments: dict, *, staff: Any,
              reader: Callable[[dict], dict] | None = None) -> dict:
    """Dispatch to authenticated site operations; writes must enforce their own conditions.

    ``staff`` implements named operations, including atomic conditional writes and the
    existing publishing/review gates. It must preserve the supplied principal's authority.
    ``reader`` invokes the site's existing Reader Steering handler, including its policy.
    """
    _identity(principal)
    spec = TOOLS.get(name)
    if spec is None or spec[0] != principal.kind:
        raise PermissionError("Tool is unavailable to this identity.")
    _validate(spec[1], arguments)
    if principal.kind == "reader":
        if reader is None:
            raise RuntimeError("Reader Steering is unavailable.")
        return reader({"siteSubject": principal.site_subject, "isStaff": False,
                       "action": "comment" if name == "reader_comment" else "submit", "payload": arguments})
    operation = getattr(staff, name, None)
    if name not in getattr(staff, "available_tools", ()) or not callable(operation):
        raise RuntimeError("Site operation is unavailable.")
    return operation(principal, **arguments)


class StaffReads:
    """Read through the same scoped GraphQL client used by the operator library."""

    available_tools = frozenset({"story_get", "story_versions", "story_evidence"})

    def __init__(self, client: Any):
        self.client = client

    def reference_get(self, principal: Principal, *, lineageId: str) -> dict:
        from .story_reporting import current_reference
        row = current_reference(self.client, lineageId)
        if row is None:
            raise ValueError("Reference not found.")
        return {"reference": row}

    def story_get(self, principal: Principal, *, lineageId: str) -> dict:
        from .story_reporting import current_story_version
        from .editorial_context import _check_tenant
        row = current_story_version(self.client, lineageId)
        _check_tenant(self.client, row)
        return {"story": _story_fields(row)}

    def story_versions(self, principal: Principal, *, lineageId: str) -> dict:
        from .story_reporting import story_versions
        from .editorial_context import _check_tenant
        rows = story_versions(self.client, lineageId)
        for row in rows:
            _check_tenant(self.client, row)
        return {"versions": [_story_fields(row) for row in rows]}

    def story_evidence(self, principal: Principal, *, lineageId: str) -> dict:
        from .story_reporting import story_references
        self.story_get(principal, lineageId=lineageId)
        return {"evidence": story_references(self.client, lineageId)}

    def story_next(self, principal: Principal, *, lineageId: str) -> dict:
        from .newsroom_process import assess, story_facts
        return {"procedure": assess(story_facts(self.client, lineageId))}

    def assignment_get(self, principal: Principal, *, id: str) -> dict:
        row = self.client.get_record("Assignment", id)
        if row is None:
            raise ValueError("Assignment not found.")
        return {"assignment": row}

    def assignments_list(self, principal: Principal, *, storyLineageId: str | None = None) -> dict:
        rows = self.client.list_records("Assignment")
        return {"assignments": [r for r in rows if storyLineageId is None or r.get("itemLineageId") == storyLineageId]}

    def concept_get(self, principal: Principal, *, id: str) -> dict:
        rows = self.client.list_records("SemanticNode")
        match = next((r for r in rows if (r.get("lineageId") == id or r.get("id") == id) and r.get("versionState", "current") == "current"), None)
        if match is None:
            raise ValueError("Concept not found.")
        return {"concept": match}

    def concept_search(self, principal: Principal, *, query: str, limit: int = 20) -> dict:
        rows = self.client.list_records("SemanticNode")
        text = query.casefold()
        return {"concepts": [r for r in rows if r.get("versionState", "current") == "current" and text in str(r.get("displayName") or "").casefold()][:limit]}

    def reference_search(self, principal: Principal, *, query: str, limit: int = 20) -> dict:
        rows = self.client.list_records("Reference")
        text = query.casefold()
        return {"references": [r for r in rows if r.get("versionState", "current") == "current" and text in str(r.get("title") or "").casefold()][:limit]}

    def review_get(self, principal: Principal, *, id: str) -> dict:
        from .review_requests import get_review
        return {"review": get_review(self.client, id, sweep=False)}

    def reviews_list(self, principal: Principal, *, state: str | None = None, mode: str | None = None) -> dict:
        from .review_requests import list_reviews
        return {"reviews": list_reviews(self.client, state=state, mode=mode, sweep=False)}


class ReaderSteeringInvoke:
    """Invoke the site's existing reader function using an injected Lambda client."""

    def __init__(self, client: Any, function_name: str, publication: str):
        if not function_name or not publication:
            raise ValueError("Reader function and publication are required.")
        self.client, self.function_name, self.publication = client, function_name, publication

    def __call__(self, event: dict) -> dict:
        import json
        response = self.client.invoke(FunctionName=self.function_name, InvocationType="RequestResponse",
                                      Payload=json.dumps({**event, "publication": self.publication}).encode())
        if response.get("FunctionError"):
            raise RuntimeError("Reader Steering failed.")
        result = json.loads(response["Payload"].read())
        if not isinstance(result, dict) or not isinstance(result.get("statusCode"), int):
            raise RuntimeError("Reader Steering returned an invalid response.")
        return result
