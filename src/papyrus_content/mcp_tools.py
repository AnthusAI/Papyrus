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
    "reference_search": ("staff", _schema({"query": S}, {"limit": LIMIT, "nextToken": S})),
    "reference_get": ("staff", _schema(LINEAGE)),
    "concept_search": ("staff", _schema({"query": S}, {"limit": LIMIT, "nextToken": S})),
    "concept_get": ("staff", _schema({"id": S})),
    "story_search": ("staff", _schema({"query": S}, {"limit": LIMIT, "nextToken": S})),
    "story_get": ("staff", _schema(LINEAGE)),
    "story_versions": ("staff", _schema(LINEAGE)),
    "story_evidence": ("staff", _schema(LINEAGE, {"limit": LIMIT, "nextToken": S})),
    "story_next": ("staff", _schema(LINEAGE)),
    "assignments_list": ("staff", _schema({"storyLineageId": S}, {"limit": LIMIT, "nextToken": S})),
    "assignment_get": ("staff", _schema({"id": S})),
    "story_save_draft": ("staff", _schema({**VERSION, "body": S, "reason": S}, {"frontMatter": {"type": "string"}})),
    "reference_decide": ("staff", _schema({**REVISION, "decision": {"type": "string", "enum": ["accept", "reject"]}}, {"note": S})),
    "reference_star": ("staff", _schema({**REVISION, "stars": STARS})),
    "story_star": ("staff", _schema({**REVISION, "stars": STARS})),
    "reviews_list": ("staff", _schema({"subjectType": S, "subjectId": S}, {"state": S, "mode": S, "limit": LIMIT, "nextToken": S})),
    "review_get": ("staff", _schema({"id": S})),
    "review_answer": ("staff", _schema({"id": S, "expectedRevision": S, "decision": S}, {"feedback": S, "steer": S})),
    "story_publish": ("staff", _schema(VERSION)),
    "story_request_publish": ("staff", _schema(VERSION)),
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
    "story_request_publish": "Request a person's approval to publish a Story.",
    "reader_comment": "Comment on a subject under the site's reader policy.",
    "reader_submit": "Submit a link under the site's reader policy.",
}


def _story_fields(row: dict) -> dict:
    import json
    allowed = {"id", "lineageId", "versionNumber", "versionState", "versionCreatedAt", "versionCreatedBy", "changeReason", "updatedAt", "title", "headline", "type", "section", "stage", "status", "bodyMarkus", "starRating"}
    result = {key: value for key, value in row.items() if key in allowed}
    if row.get("updatedAt"):
        result["revision"] = json.dumps([row["updatedAt"], row.get("starRevision")], separators=(",", ":"))
    return result


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


from .mcp_story_writes import StaffStoryWrites


class StaffReads(StaffStoryWrites):
    """Read through the same scoped GraphQL client used by the operator library."""

    available_tools = frozenset({"story_get", "story_versions", "story_evidence", "story_search", "story_next", "reference_get", "reference_search", "reference_decide", "concept_get", "concept_search", "assignment_get", "assignments_list", "review_get", "reviews_list", "review_answer", "story_star", "story_save_draft", "story_request_publish"})

    def __init__(self, client: Any):
        self.client = client

    def _reference_scope(self) -> None:
        # Reference has no tenant key. A shared backend cannot establish ownership.
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("References are unavailable without a tenant ownership key.")

    def reference_get(self, principal: Principal, *, lineageId: str) -> dict:
        self._reference_scope()
        query = """query CurrentReference($lineageId: ID!, $limit: Int!) {
          listReferencesByLineageAndVersion(lineageId: $lineageId, limit: $limit) {
            items { id lineageId versionNumber versionState title sourceUri curationStatus starRating updatedAt }
            nextToken
          }
        }"""
        result = self.client.graphql(query, {"lineageId": lineageId, "limit": 100})
        page = result.get("listReferencesByLineageAndVersion") or {}
        if page.get("nextToken"):
            raise ValueError("Reference has too many versions to resolve safely.")
        rows = [r for r in page.get("items", []) if r and r.get("lineageId") == lineageId and r.get("versionState") == "current"]
        if len(rows) != 1 or not rows[0].get("updatedAt"):
            raise ValueError("Reference has no unambiguous current version and revision.")
        return {"reference": rows[0]}

    def reference_search(self, principal: Principal, *, query: str, limit: int = 20, nextToken: str | None = None) -> dict:
        self._reference_scope()
        operation = """query SearchReferences($limit: Int!, $nextToken: String, $filter: ModelReferenceFilterInput) {
          listReferences(limit: $limit, nextToken: $nextToken, filter: $filter) {
            items { id lineageId versionNumber versionState title sourceUri curationStatus starRating updatedAt }
            nextToken
          }
        }"""
        result = self.client.graphql(operation, {"limit": limit, "nextToken": nextToken, "filter": {"and": [{"versionState": {"eq": "current"}}, {"title": {"contains": query}}]}})
        page = result.get("listReferences") or {}
        return {"references": [row for row in page.get("items", []) if row], "nextToken": page.get("nextToken")}

    def reference_decide(self, principal: Principal, *, lineageId: str, expectedCurrentVersionId: str,
                         expectedRevision: str, decision: str, note: str | None = None) -> dict:
        self._reference_scope()
        if decision == "reject" and not (note or "").strip():
            raise ValueError("A rejection needs a reason.")
        current = self.reference_get(principal, lineageId=lineageId)["reference"]
        if current["id"] != expectedCurrentVersionId or current["updatedAt"] != expectedRevision:
            raise ValueError("stale_revision: The Reference changed. Refresh the card and try again.")
        mutation = """mutation AgentReviewReference($referenceId: ID!, $lineageId: ID!, $expectedRevision: String!, $action: String!, $note: String) {
          agentReviewReferenceCuration(referenceId: $referenceId, lineageId: $lineageId, expectedRevision: $expectedRevision, action: $action, note: $note) {
            ok action referenceId status reasonCode
          }
        }"""
        result = self.client.graphql(mutation, {"referenceId": expectedCurrentVersionId, "lineageId": lineageId,
            "expectedRevision": expectedRevision, "action": decision, "note": note})
        answer = result.get("agentReviewReferenceCuration")
        if not isinstance(answer, dict) or not answer.get("ok"):
            raise RuntimeError("The site did not confirm the Reference decision.")
        return {"decision": answer, **self.reference_get(principal, lineageId=lineageId)}

    def _story_versions(self, lineage_id: str) -> list[dict]:
        from .editorial_context import _check_tenant
        operation = """query StoryVersions($lineageId: ID!, $limit: Int!) {
          listItemsByLineageAndVersion(lineageId: $lineageId, limit: $limit) {
            items { id lineageId versionNumber versionState versionCreatedAt versionCreatedBy changeReason updatedAt tenantId title headline type section stage status bodyMarkus metadata starRating starRevision }
            nextToken
          }
        }"""
        page = self.client.graphql(operation, {"lineageId": lineage_id, "limit": 100}).get("listItemsByLineageAndVersion") or {}
        if page.get("nextToken"):
            raise ValueError("Story has too many versions to resolve safely.")
        rows = [row for row in page.get("items", []) if row and row.get("lineageId") == lineage_id]
        for row in rows:
            _check_tenant(self.client, row)
        return rows

    def story_get(self, principal: Principal, *, lineageId: str) -> dict:
        rows = [row for row in self._story_versions(lineageId) if row.get("versionState") == "current"]
        if len(rows) != 1:
            raise ValueError("Story has no unambiguous current version.")
        return {"story": _story_fields(rows[0])}

    def story_star(self, principal: Principal, *, lineageId: str, expectedCurrentVersionId: str,
                   expectedRevision: str, stars: int) -> dict:
        import json
        try:
            revision = json.loads(expectedRevision)
            if not isinstance(revision, list) or len(revision) != 2 or not isinstance(revision[0], str) or (revision[1] is not None and not isinstance(revision[1], str)):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Invalid Story revision.") from None
        current = self.story_get(principal, lineageId=lineageId)["story"]
        if current["id"] != expectedCurrentVersionId or current.get("revision") != expectedRevision:
            raise ValueError("stale_revision: The Story changed.")
        query = """mutation AgentStoryStars($itemId: ID!, $lineageId: ID!, $stars: Int!, $expectedUpdatedAt: String!, $expectedStarRevision: String) {
          agentSetItemStars(itemId: $itemId, lineageId: $lineageId, stars: $stars, expectedUpdatedAt: $expectedUpdatedAt, expectedStarRevision: $expectedStarRevision) {
            ok itemId lineageId stars
          }
        }"""
        result = self.client.graphql(query, {"itemId": expectedCurrentVersionId, "lineageId": lineageId, "stars": stars,
                                             "expectedUpdatedAt": revision[0], "expectedStarRevision": revision[1]})
        if not (result.get("agentSetItemStars") or {}).get("ok"):
            raise RuntimeError("The site did not confirm the Story rating.")
        return self.story_get(principal, lineageId=lineageId)

    def story_versions(self, principal: Principal, *, lineageId: str) -> dict:
        rows = self._story_versions(lineageId)
        return {"versions": [_story_fields(row) for row in sorted(rows, key=lambda r: int(r.get("versionNumber") or 0), reverse=True)]}

    def story_evidence(self, principal: Principal, *, lineageId: str, limit: int = 20, nextToken: str | None = None) -> dict:
        self.story_get(principal, lineageId=lineageId)
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("Reference evidence has no tenant ownership key.")
        operation = """query StoryEvidence($subjectStateKey: String!, $limit: Int!, $nextToken: String) {
          listSemanticRelationsBySubjectState(subjectStateKey: $subjectStateKey, limit: $limit, nextToken: $nextToken) {
            items { id predicate objectKind objectLineageId metadata }
            nextToken
          }
        }"""
        page = (self.client.graphql(operation, {"subjectStateKey": f"item#{lineageId}#current", "limit": limit, "nextToken": nextToken}).get("listSemanticRelationsBySubjectState") or {})
        import json
        evidence = []
        for relation in page.get("items", []):
            if not relation or relation.get("predicate") != "uses_evidence" or relation.get("objectKind") != "reference":
                continue
            metadata = relation.get("metadata") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            evidence.append({"relationId": relation["id"], "referenceLineageId": relation.get("objectLineageId"),
                             "role": metadata.get("role", "consulted"), "note": metadata.get("note"), "citationKey": metadata.get("citationKey")})
        return {"evidence": evidence, "nextToken": page.get("nextToken")}

    def story_search(self, principal: Principal, *, query: str, limit: int = 20, nextToken: str | None = None) -> dict:
        filters: list[dict] = [{"title": {"contains": query}}, {"versionState": {"eq": "current"}}]
        tenant = getattr(self.client, "tenant_id", None)
        if tenant:
            filters.append({"tenantId": {"eq": tenant}})
        operation = """query SearchStories($limit: Int!, $nextToken: String, $filter: ModelItemFilterInput) {
          listItems(limit: $limit, nextToken: $nextToken, filter: $filter) {
            items { id lineageId versionNumber versionState updatedAt tenantId type title headline stage status starRating starRevision }
            nextToken
          }
        }"""
        page = (self.client.graphql(operation, {"limit": limit, "nextToken": nextToken, "filter": {"and": filters}}).get("listItems") or {})
        from .content_item_lifecycle import is_story_item_type
        from .editorial_context import _check_tenant
        rows = []
        for row in page.get("items", []):
            if row and is_story_item_type(row.get("type") or ""):
                _check_tenant(self.client, row)
                rows.append(_story_fields(row))
        return {"stories": rows, "nextToken": page.get("nextToken")}

    def story_next(self, principal: Principal, *, lineageId: str) -> dict:
        from .newsroom_process import _metadata_of, assess
        rows = [row for row in self._story_versions(lineageId) if row.get("versionState") == "current"]
        if len(rows) != 1:
            raise ValueError("Story has no unambiguous current version.")
        current = rows[0]
        facts = {"lineage": lineageId, "stage": current.get("stage") or "idea", "versionId": current["id"],
                 "versionNumber": int(current.get("versionNumber") or 1), "body": current.get("bodyMarkus") or "",
                 "metadata": _metadata_of(current), "assignments": [], "assignmentsUnknown": True,
                 "checkRun": None, "checkRunError": True}
        return {"procedure": assess(facts)}

    def _assignment(self, row: dict) -> dict:
        return {key: row[key] for key in ("id", "itemLineageId", "title", "status", "assignmentTypeKey", "priority", "summary", "createdAt", "updatedAt") if key in row}

    def assignment_get(self, principal: Principal, *, id: str) -> dict:
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("Assignments lack a tenant ownership key.")
        row = self.client.get_record("Assignment", id)
        if row is None or not row.get("itemLineageId"):
            raise ValueError("Assignment has no scoped Story.")
        self.story_get(principal, lineageId=row["itemLineageId"])
        return {"assignment": self._assignment(row)}

    def assignments_list(self, principal: Principal, *, storyLineageId: str, limit: int = 20, nextToken: str | None = None) -> dict:
        self.story_get(principal, lineageId=storyLineageId)
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("Assignment indexes lack a tenant ownership key.")
        operation = """query StoryAssignments($itemLineageId: ID!, $limit: Int!, $nextToken: String) {
          listAssignmentsByItemLineageAndCreatedAt(itemLineageId: $itemLineageId, limit: $limit, nextToken: $nextToken) {
            items { id itemLineageId title status assignmentTypeKey priority summary createdAt updatedAt }
            nextToken
          }
        }"""
        page = (self.client.graphql(operation, {"itemLineageId": storyLineageId, "limit": limit, "nextToken": nextToken}).get("listAssignmentsByItemLineageAndCreatedAt") or {})
        return {"assignments": [self._assignment(row) for row in page.get("items", []) if row and row.get("itemLineageId") == storyLineageId], "nextToken": page.get("nextToken")}

    def concept_get(self, principal: Principal, *, id: str) -> dict:
        self._reference_scope()  # SemanticNode, like Reference, has no tenant key.
        page = self._concept_page({"and": [{"lineageId": {"eq": id}}, {"versionState": {"eq": "current"}}]}, 100, None)
        if page.get("nextToken") or len(page.get("items", [])) != 1:
            raise ValueError("Concept has no unambiguous current version.")
        return {"concept": page["items"][0]}

    def _concept_page(self, filter_: dict, limit: int, token: str | None) -> dict:
        operation = """query Concepts($limit: Int!, $nextToken: String, $filter: ModelSemanticNodeFilterInput) {
          listSemanticNodes(limit: $limit, nextToken: $nextToken, filter: $filter) {
            items { id lineageId versionNumber versionState nodeKey nodeKind displayName status updatedAt }
            nextToken
          }
        }"""
        return self.client.graphql(operation, {"limit": limit, "nextToken": token, "filter": filter_}).get("listSemanticNodes") or {}

    def concept_search(self, principal: Principal, *, query: str, limit: int = 20, nextToken: str | None = None) -> dict:
        self._reference_scope()
        page = self._concept_page({"and": [{"displayName": {"contains": query}}, {"versionState": {"eq": "current"}}]}, limit, nextToken)
        return {"concepts": [row for row in page.get("items", []) if row], "nextToken": page.get("nextToken")}

    def _scope_review(self, principal: Principal, row: dict) -> dict:
        from .review_requests import read_review
        review = read_review(row)
        subject = review.get("subject") or {}
        if not isinstance(subject, dict):
            raise ValueError("Review subject is invalid.")
        if getattr(self.client, "tenant_id", None):
            if subject.get("type") != "story" or not subject.get("id"):
                raise PermissionError("Review has no scoped Story.")
            self.story_get(principal, lineageId=subject["id"])
        return {key: review[key] for key in ("id", "subject", "mode", "reason", "ask", "raisedBy", "raisedAt", "deadline", "state", "answer", "updatedAt", "outcome")}

    def review_get(self, principal: Principal, *, id: str) -> dict:
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("Reviews lack a tenant ownership key.")
        row = self.client.get_record("ReviewRequest", id)
        if not row:
            raise ValueError("Review not found.")
        return {"review": self._scope_review(principal, row)}

    def review_answer(self, principal: Principal, *, id: str, expectedRevision: str, decision: str,
                      feedback: str | None = None, steer: str | None = None) -> dict:
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("Reviews lack a tenant ownership key.")
        from .review_requests import answer_review
        from .operator_errors import GraphQLRequestError
        client = self.client

        class ConditionalReviewClient:
            def get_record(self, model: str, record_id: str):
                return client.get_record(model, record_id)

            def update_record(self, model: str, payload: dict):
                if model != "ReviewRequest" or payload.get("id") != id:
                    raise ValueError("Unexpected review update.")
                operation = """mutation ConditionalReview($input: UpdateReviewRequestInput!, $condition: ModelReviewRequestConditionInput) {
                  updateReviewRequest(input: $input, condition: $condition) { id }
                }"""
                try:
                    result = client.graphql(operation, {"input": payload, "condition": {
                        "state": {"eq": "open"}, "updatedAt": {"eq": expectedRevision}}})
                except GraphQLRequestError as error:
                    if "ConditionalCheckFailed" in str(error):
                        raise ValueError("stale_revision: The review changed.") from error
                    raise
                if not result.get("updateReviewRequest"):
                    raise ValueError("stale_revision: The review changed.")

        row = client.get_record("ReviewRequest", id)
        if not row or row.get("state") != "open" or row.get("updatedAt") != expectedRevision:
            raise ValueError("stale_revision: The review changed.")
        self._scope_review(principal, row)
        from .publish_gate import RAISED_BY as PUBLISH_GATE_RAISER
        if row.get("raisedBy") == PUBLISH_GATE_RAISER:
            raise PermissionError("Publish approval requires a person.")
        result = answer_review(ConditionalReviewClient(), id, decision=decision, by=f"agent:{principal.subject}", feedback=feedback, steer=steer, roles=["editor"])
        return {"review": {key: result[key] for key in ("id", "subject", "mode", "reason", "ask", "raisedBy", "raisedAt", "deadline", "state", "answer", "updatedAt", "outcome")}}

    def reviews_list(self, principal: Principal, *, subjectType: str, subjectId: str, state: str | None = None, mode: str | None = None, limit: int = 20, nextToken: str | None = None) -> dict:
        if getattr(self.client, "tenant_id", None):
            raise PermissionError("Reviews lack a tenant ownership key.")
        filters = []
        if state: filters.append({"state": {"eq": state}})
        if mode: filters.append({"mode": {"eq": mode}})
        operation = """query Reviews($limit: Int!, $nextToken: String, $filter: ModelReviewRequestFilterInput) {
          listReviewRequests(limit: $limit, nextToken: $nextToken, filter: $filter) {
            items { id subject mode reason ask raisedBy raisedAt deadline state answer updatedAt }
            nextToken
          }
        }"""
        page = (self.client.graphql(operation, {"limit": limit, "nextToken": nextToken, "filter": {"and": filters} if filters else None}).get("listReviewRequests") or {})
        from .review_requests import read_review
        rows = []
        for row in page.get("items", []):
            subject = (read_review(row).get("subject") if row else None) or {}
            if isinstance(subject, dict) and subject.get("type") == subjectType and subject.get("id") == subjectId:
                rows.append(row)
        return {"reviews": [self._scope_review(principal, row) for row in rows], "nextToken": page.get("nextToken")}


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
