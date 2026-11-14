"""A stand-in for a site's GraphQL API that enforces the rules a signed-in token meets on SemanticRelation.

The groups may read and create a SemanticRelation and never update one (`categoryAppendOnlyOperations` in amplify/data/schema.ts), so a direct
update is refused with the very message AppSync gives. `setStoryReferenceRole` is open to the editor and administrator groups; with
``run_site_code=True`` the stand-in hands each call to the site's own code (scripts/story-reference-role-probe.ts) and applies what it wrote,
otherwise a small Python copy answers, for unit tests that should not start Node. No network, login or AWS.
"""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

from fake_client import FakeAuthoringClient
from papyrus_content.operator_errors import GraphQLRequestError

REPO_ROOT = Path(__file__).resolve().parents[3]
STAFF_GROUPS = ("editor", "admin")
NOW = "2026-11-08T12:00:00.000Z"


def not_authorized(field: str) -> GraphQLRequestError:
    return GraphQLRequestError(f'GraphQL errors: [{{"errorType": "Unauthorized", "message": "Not Authorized to access {field} on type Mutation"}}]')


class SignedInSite(FakeAuthoringClient):
    def __init__(self, records: dict[str, list[dict[str, Any]]], *, groups: list[str], label: str = "Grace Editor",
                 run_site_code: bool = False, has_route: bool = True) -> None:
        super().__init__(records)
        self.endpoint = "https://example.test/graphql"
        self.groups = groups
        self.label = label
        self.run_site_code = run_site_code
        self.has_route = has_route
        self.refused: list[str] = []
        self.route_calls: list[dict[str, Any]] = []

    def _staff(self) -> bool:
        return any(group in STAFF_GROUPS for group in self.groups)

    def upsert(self, model_name: str, payload: dict[str, Any]) -> str:
        if model_name == "SemanticRelation":
            exists = payload["id"] in self._table(model_name)
            if exists or not self._staff():   # update is never granted to the groups; create only to editor and admin
                field = "updateSemanticRelation" if exists else "createSemanticRelation"
                self.refused.append(field)
                raise not_authorized(field)
        return super().upsert(model_name, payload)

    def update_record(self, model_name: str, payload: dict[str, Any]) -> None:
        if model_name == "SemanticRelation":
            self.refused.append("updateSemanticRelation")
            raise not_authorized("updateSemanticRelation")
        super().update_record(model_name, payload)

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if "setStoryReferenceRole" not in query:
            raise AssertionError(f"unexpected request: {query}")
        if not self.has_route:
            raise GraphQLRequestError("GraphQL errors: [{\"message\": \"Validation error of type FieldUndefined: Field 'setStoryReferenceRole' in type 'Mutation' is undefined\"}]")
        if not self._staff():   # the schema admits only editor and admin to the route
            self.refused.append("setStoryReferenceRole")
            raise not_authorized("setStoryReferenceRole")
        call = dict(variables or {})
        self.route_calls.append(call)
        answer = self._site_code(call) if self.run_site_code else self._python_copy(call)
        for patch in answer.get("writes", []):
            self._table("SemanticRelation")[patch["id"]] = {**self._table("SemanticRelation")[patch["id"]], **copy.deepcopy(patch)}
        if "error" in answer:
            raise GraphQLRequestError(f"GraphQL errors: [{{\"message\": {json.dumps(answer['error'])}}}]")
        return {"setStoryReferenceRole": answer["result"]}

    def _site_code(self, call: dict[str, Any]) -> dict[str, Any]:
        probe = {"relations": self._table("SemanticRelation"), "call": call, "callerGroups": self.groups, "actor": self.label, "now": NOW, "origin": "cli"}
        done = subprocess.run(["node", "--import", "tsx", "scripts/story-reference-role-probe.ts"], cwd=REPO_ROOT, input=json.dumps(probe),
                              capture_output=True, text=True, timeout=120, check=True)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def _python_copy(self, call: dict[str, Any]) -> dict[str, Any]:
        row = self._table("SemanticRelation").get(call["relationId"])
        metadata = json.loads(row["metadata"]) if row else {}
        if not row or row.get("predicate") != "uses_evidence" or metadata.get("kind") != "story.reference":
            return {"error": f"{call['relationId']} is not a source attached to a Story; only a Story source's role can be changed here."}
        role = "based_on" if metadata.get("role") == "based_on" else call["role"]
        metadata.update({"role": role, "updatedBy": self.label, "updatedAt": NOW, "updatedVia": "cli"})
        for key, name in (("citationKey", "citationKey"), ("note", "note")):
            if call.get(key):
                metadata[name] = call[key]
        patch = {"id": row["id"], "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": NOW}
        return {"writes": [patch], "result": {"ok": True, "relationId": row["id"], "role": role, "previousRole": None, "citationKey": metadata.get("citationKey")}}
