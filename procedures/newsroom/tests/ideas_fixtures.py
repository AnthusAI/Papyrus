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
        self.reviews: dict[str, dict[str, Any]] = {}
        self.reject_review_writes = False

    def list_records(self, model: str) -> list[dict[str, Any]]:
        self.calls.append(("list_records", model))
        if model == "ReviewRequest":
            return [dict(row) for row in self.reviews.values()]
        return {"KnowledgeCorpus": self.corpora, "NewsroomSection": self.sections}.get(model, [])

    def get_record(self, model: str, record_id: str) -> dict[str, Any] | None:
        row = self.reviews.get(record_id) if model == "ReviewRequest" else None
        return dict(row) if row else None

    def create_record(self, model: str, payload: dict[str, Any]) -> None:
        if self.reject_review_writes:
            raise RuntimeError("Cannot query field createReviewRequest on type Mutation.")
        self.reviews[payload["id"]] = dict(payload)

    def update_record(self, model: str, payload: dict[str, Any]) -> None:
        self.reviews[payload["id"]] = {**self.reviews[payload["id"]], **payload}

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


# --- trend stories (docs/idea-pipeline.md#trend-stories) ---------------------------------------------------------------------

AS_OF = "2026-10-19"


def snapshot_files() -> dict[str, object]:
    """A small weekly knowledge snapshot: two named clusters, three trending entities and one new entity, as the site publishes them."""

    def entity(key, name, kind, series, last4, prior4, percent, new=False):
        return {"acceptedBy": {"actor": "ai", "name": None, "on": "2026-10-22"}, "aliases": [], "change": {"last4": last4, "percent": percent, "prior4": prior4},
                "href": f"/wiki/{key.replace('--', '-')}/", "isNew": new, "itemCount": sum(series), "key": key, "kind": kind, "name": name, "series8": series,
                "weeksOfHistory": 3 if new else 52}

    index = {
        "asOf": AS_OF, "beats": [], "conceptOfTheWeek": None, "entityCount": 4, "kinds": [], "schemaVersion": 1, "topicCount": 2,
        "trending": ["platform--hugging-face", "licence--apache-2-0", "task--routing"],
        "entities": [
            entity("platform--hugging-face", "Hugging Face", "platform", [1, 2, 3, 4, 7, 3, 3, 2], 15, 10, 50),
            entity("licence--apache-2-0", "Apache-2.0", "licence", [1, 1, 3, 3, 5, 3, 2, 2], 12, 8, 50),
            entity("task--routing", "routing", "task", [0, 1, 2, 2, 3, 3, 4, 4], 14, 5, None),
            entity("task--typed-decisions", "typed decisions", "task", [0, 0, 0, 0, 1, 2, 3, 5], 11, 1, None, new=True),
        ],
    }
    clusters = {
        "asOf": AS_OF, "runId": "run-1", "schemaVersion": 1, "unacceptedClusters": 0,
        "clusters": [
            {"acceptedBy": {"actor": "ai", "name": None, "on": "2026-10-22"}, "beats": ["decision-models"], "href": None, "itemCount": 21, "name": "Decision models",
             "series8": [0, 0, 3, 3, 4, 4, 2, 4], "state": "growing", "topTerms": ["decision", "public", "jev"], "uid": "cl-fb1252e1da52", "weeksOfData": 69},
            {"acceptedBy": {"actor": "ai", "name": None, "on": "2026-10-22"}, "beats": [], "href": None, "itemCount": 22, "name": "Open-weights language models",
             "series8": [1, 2, 1, 1, 2, 1, 1, 1], "state": None, "topTerms": ["licence", "apache"], "uid": "cl-aaaa00000001", "weeksOfData": 69},
        ],
    }
    entities = {
        "platform--hugging-face": {"key": "platform--hugging-face", "neighbours": [{"key": "licence--apache-2-0", "kind": "licence", "name": "Apache-2.0", "relation": "mentioned_with", "weight": 5}],
                                   "relatedItems": [{"title": "A model card worth reading", "url": "/posts/a-model-card/", "publishedAt": "2026-10-14", "reason": "platform--hugging-face"},
                                                    {"title": "Zed releases Zed-7B, a small coding model under Apache-2.0", "url": "/posts/zed-7b/", "publishedAt": "2026-10-17T00:00:00Z", "reason": "platform--hugging-face"}]},
        "licence--apache-2-0": {"key": "licence--apache-2-0",
                                "relatedItems": [{"title": "Zed releases Zed-7B, a small coding model under Apache-2.0", "url": "/posts/zed-7b/", "publishedAt": "2026-10-17T00:00:00Z", "reason": "licence--apache-2-0"},
                                                 {"title": "An older release outside the window", "url": "/posts/older/", "publishedAt": "2026-08-01T00:00:00Z", "reason": "licence--apache-2-0"}]},
    }
    return {"index": index, "clusters": clusters, "entities": entities}


def history_entry() -> dict[str, object]:
    files = snapshot_files()
    return {"schemaVersion": 1, "asOf": AS_OF, "runId": "run-1", "runAsOf": "2026-10-22", "archivedAt": "2026-10-22T16:59:53Z", "counts": {"clusters": 2, "entities": 4, "topics": 2},
            "clusters": [], "snapshot": files}


def sentence(text: str, *cites: str) -> dict[str, object]:
    return {"text": text, "cites": list(cites)}


def trend_draft(headline: str = "Hugging Face and Apache-2.0 climb together", *, section: str = "Analysis", body=None, figure=("S3",), cites=("S3", "S4")) -> dict[str, object]:
    """A draft that passes the citation check against ``snapshot_files``: S1 and S2 are the clusters, S3 to S5 the trending entities, S6 the new one."""
    first, second = cites[0], cites[-1]
    return {
        "headline": sentence(headline, first, second),
        "dek": sentence("Both rose in the four weeks to 2026-10-19.", first, second),
        "section": section,
        "paragraphs": body or [
            {"sentences": [
                sentence("Hugging Face appeared in 15 items over the last four weeks, against 10 in the four before.", "S3"),
                sentence("Apache-2.0 appeared in 12 items over the last four weeks, against 8 before.", "S4"),
            ]},
            {"sentences": [sentence("The two are mentioned together in 5 items.", "S3", "S4")]},
        ],
        "figure_signals": list(figure),
        "figure_title": "Items per week",
        "figure_caption": "Hugging Face peaked at 7 items in one week.",
    }


SITE_BASE = "https://site.example"
ITEM_PAGES = {
    f"{SITE_BASE}/posts/zed-7b.md": "# Zed releases Zed-7B\n\n> A 7B coding model with 32k context, trained on permissively licensed code.\n\nPublished 2026-10-17\n\nBody text.\n",
    f"{SITE_BASE}/posts/a-model-card.md": "# A model card worth reading\n\n> The card lists its evaluation limits.\n\nBody text.\n",
}


def read_item_page(url: str) -> str:
    """Stands in for reading the published ``.md`` of an item."""
    if url not in ITEM_PAGES:
        raise OSError(f"no page at {url}")
    return ITEM_PAGES[url]


def release_draft(headline: str = "Zed-7B brings an Apache-2.0 coding model to Hugging Face") -> dict[str, object]:
    """A draft about the releases that passes the check once the items are read: S3 is Hugging Face, S4 Apache-2.0, I1 the Zed-7B release, I2 the model card."""
    return {
        "headline": sentence(headline, "I1"),
        "dek": sentence("Zed's release on 2026-10-17 is one of 15 Hugging Face items in four weeks.", "I1", "S3"),
        "section": "Analysis",
        "paragraphs": [
            {"sentences": [
                sentence("Zed released Zed-7B, a 7B coding model with 32k context, under Apache-2.0.", "I1"),
                sentence("Apache-2.0 appeared in 12 items over the last four weeks.", "S4"),
            ]},
            {"sentences": [sentence("Another release on Hugging Face ships a model card that lists its evaluation limits, which suggests documentation is part of the pattern.", "I2", "S3")]},
        ],
        "figure_signals": ["S3"],
        "figure_title": "Items per week",
        "figure_caption": "Hugging Face peaked at 7 items in one week.",
    }


class FakeTrendModel(FakeModel):
    """Like ``FakeModel`` but answers in the trend drafts format."""

    def __call__(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        return {"status": "completed", "output_text": json.dumps({"drafts": self.ideas}), "usage": self.usage}
