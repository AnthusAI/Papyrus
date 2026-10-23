"""A fake newsroom backend and a fake model for the idea pipeline tests. Nothing here touches the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
CORPUS = "knowledge-corpus-example-site"


def reference(number: int, *, status: str = "accepted", days_ago: float = 1, corpus: str = CORPUS, title: str | None = None, state: str = "current") -> dict[str, Any]:
    created = datetime.fromtimestamp(NOW.timestamp() - days_ago * 86400, timezone.utc).isoformat().replace("+00:00", "Z")
    lineage = f"reference-{corpus}-r{number}"
    return {
        "id": f"{lineage}-v1",
        "lineageId": lineage,
        "versionState": state,
        "corpusId": corpus,
        "title": title or f"Reference {number}",
        "sourceUri": f"https://www.example{number}.org/post",
        "curationStatus": status,
        "curationStatusReason": f"Accepted because reason {number}",
        "createdAt": created,
        "authors": "[]",
    }


def relevance(reference_row: dict[str, Any], label: str = "include", score: float = 0.9) -> dict[str, Any]:
    return {
        "predicate": "relevance_decision_is",
        "relationState": "current",
        "objectKind": "semanticNode",
        "objectLineageId": f"semantic-node-relevance-{label}",
        "subjectLineageId": reference_row["lineageId"],
        "score": str(score),
        "createdAt": "2026-10-21T00:00:00Z",
        "metadata": json.dumps({"classifier": "example-relevance", "decidedAt": "2026-10-21T00:00:00Z"}),
    }


def entity(reference_row: dict[str, Any], name: str) -> dict[str, Any]:
    return {"predicate": "mentions", "relationState": "current", "objectKind": "semanticNode", "objectLineageId": name, "createdAt": "2026-10-21T00:00:00Z"}


def story(title: str, *, section: str = "Analysis", status: str = "published", days_ago: float = 10, deck: str = "", stage: str = "published") -> dict[str, Any]:
    moment = datetime.fromtimestamp(NOW.timestamp() - days_ago * 86400, timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": f"item-{title.lower().replace(' ', '-')}-v1", "lineageId": f"item-{title.lower().replace(' ', '-')}", "versionState": "current",
        "type": "article", "status": status, "stage": stage, "section": section, "title": title, "deck": deck,
        "publishedAt": moment if status == "published" else None, "updatedAt": moment, "tenantId": None,
    }


class FakeClient:
    """Answers the few reads the pipeline makes. ``calls`` records every request so tests can see what was (not) asked."""

    tenant_id = None

    def __init__(self, references=(), relations=None, stories=(), sections=(), corpora=(CORPUS,), doctrine=None, proposals=()) -> None:
        self.references = list(references)
        self.relations = relations or {}
        self.stories = list(stories)
        self.sections = [{"id": name, "title": name, "enabled": True} for name in sections]
        self.corpora = [{"id": corpus} for corpus in corpora]
        self.doctrine = doctrine or {"editorial-doctrine-mission": "Explain how AI systems fail.", "editorial-doctrine-policy": "Prefer primary sources."}
        self.proposals = list(proposals)
        self.calls: list[tuple[str, Any]] = []

    def list_records(self, model: str) -> list[dict[str, Any]]:
        self.calls.append(("list_records", model))
        return {"KnowledgeCorpus": self.corpora, "NewsroomSection": self.sections}.get(model, [])

    def list_by_index(self, index: str, key: str) -> list[dict[str, Any]]:
        self.calls.append(("list_by_index", key))
        if index == "referencesByCurationStatusKey":
            corpus, _, status = key.rpartition("#")
            return [row for row in self.references if row["corpusId"] == corpus and row["curationStatus"] == status]
        if index == "itemBySlug" and key in self.doctrine:
            return [{"type": "doctrine", "status": "private", "versionState": "current", "body": [self.doctrine[key]]}]
        return []

    def list_semantic_relations_by_subject_state(self, key: str) -> list[dict[str, Any]]:
        self.calls.append(("relations", key))
        return self.relations.get(key.split("#")[1], [])

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("graphql", query.strip().split("(")[0]))
        if "listItems" in query:
            return {"listItems": {"items": self.stories, "nextToken": None}}
        if "fileProposal" in query:
            self.proposals.append({"id": "prop-" + "a" * 32, **(variables or {})})
            return {"fileProposal": {"status": "ok", "id": "prop-" + "a" * 32}}
        if "listProposals" in query:
            return {"listProposals": {"items": [], "nextToken": None}}
        raise AssertionError(f"unexpected request: {query[:60]}")


class FakeModel:
    """A stand-in for the model service: returns the ideas it is given and records the request."""

    def __init__(self, ideas: list[dict[str, Any]], input_tokens: int = 1000, output_tokens: int = 400, cached: int = 0) -> None:
        self.ideas = ideas
        self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "input_tokens_details": {"cached_tokens": cached}}
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        return {"status": "completed", "output_text": json.dumps({"ideas": self.ideas}), "usage": self.usage}

    @property
    def model_input(self) -> dict[str, Any]:
        return json.loads(self.requests[-1]["input"])


def idea(title: str, handles: list[str], *, section: str = "Analysis", angle: str | None = None, note: str = "Not covered by recent stories.") -> dict[str, Any]:
    return {
        "working_title": title,
        "section": section,
        "angle": angle or f"A story on {title.lower()}, drawing the cited references together.",
        "cited_references": handles,
        "claims": [{"claim": f"The references both bear on {title.lower()}.", "references": handles}],
        "novelty_note": note,
    }
