import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_knowledge_query.engine import ContextBlock, _render_markdown_context, run_knowledge_query
from papyrus_knowledge_query.lambda_handler import handler as lambda_handler
from papyrus_knowledge_query.ranking import (
    allocate_token_budgets,
    quality_score_from_rating,
    quality_signal_from_relations,
    select_records_by_diversity,
)
from papyrus_knowledge_query.services import KnowledgeQueryServices, S3VectorsProvider, diversify_vector_matches, relation_allowed_for_scope
from papyrus_knowledge_query.tokens import TokenCounter
from papyrus_knowledge_query.vector_index import (
    VectorIndexOptions,
    _sanitize_vector_metadata,
    index_reference_passages,
)


class FakeSemanticProvider:
    name = "fake-semantic"

    def search(self, query, scope, limit):
        return [
            {
                "rank": 1,
                "score": 0.91,
                "kind": "semanticNode",
                "id": "node-agent-memory-v1",
                "lineageId": "node-agent-memory",
                "title": "Agent Memory",
                "summary": f"Semantic match for {query}",
            }
        ][:limit]


class FakeVectorSemanticProvider:
    name = "fake-vector-semantic"

    def search(self, query, scope, limit):
        return [
            {
                "rank": 1,
                "distance": 0.21,
                "kind": "reference",
                "id": "reference-1-v1",
                "lineageId": "reference-1",
                "title": "Scaling Memo",
                "summary": "Production evaluation evidence for agent systems.",
                "metadata": {
                    "kind": "reference",
                    "id": "reference-1-v1",
                    "lineageId": "reference-1",
                    "referenceId": "reference-1-v1",
                    "referenceLineageId": "reference-1",
                    "title": "Scaling Memo",
                    "summary": "Production agent systems need reliability measurement.",
                    "text": (
                        "Production agent systems need reliable evaluation before deployment. "
                        "Teams measure reliability with task success, human review, and regression checks. "
                        "The study reports that human evaluation remains central for production agents."
                    ),
                    "storagePath": "corpora/test/extracted/pipeline/snapshot/text/reference-1.txt",
                    "chunkIndex": 0,
                    "startChar": 0,
                    "endChar": 260,
                    "corpusId": "test-corpus",
                    "categorySetId": "test-category-set",
                },
            },
            {
                "rank": 2,
                "distance": 0.33,
                "kind": "item",
                "id": "item-agent-eval-v1",
                "lineageId": "item-agent-eval",
                "title": "Production Agent Evaluation",
                "deck": "A newsroom article about measuring agent reliability in deployed systems.",
                "body": ["Article body fallback about production measurement for agent systems."],
                "metadata": {"corpusId": "test-corpus", "categorySetId": "test-category-set"},
            },
        ][:limit]


class RepeatedChunkSemanticProvider:
    name = "repeated-chunk-semantic"

    def search(self, query, scope, limit):
        matches = []
        for index in range(4):
            matches.append(
                {
                    "rank": index + 1,
                    "distance": 0.1 + (index * 0.01),
                    "kind": "reference",
                    "id": "reference-a-v1",
                    "lineageId": "reference-a",
                    "title": "Evaluation Source A",
                    "metadata": {
                        "kind": "reference",
                        "id": "reference-a-v1",
                        "lineageId": "reference-a",
                        "referenceId": "reference-a-v1",
                        "referenceLineageId": "reference-a",
                        "title": "Evaluation Source A",
                        "text": (
                            f"Evaluation source A chunk {index} describes model evaluation, reliability measurement, "
                            "benchmark design, and production quality checks for agent systems."
                        ),
                        "storagePath": "corpora/test/extracted/source-a.txt",
                        "chunkIndex": index,
                        "startChar": index * 200,
                        "endChar": (index + 1) * 200,
                    },
                }
            )
        matches.append(
            {
                "rank": 5,
                "distance": 0.2,
                "kind": "reference",
                "id": "reference-b-v1",
                "lineageId": "reference-b",
                "title": "Evaluation Source B",
                "metadata": {
                    "kind": "reference",
                    "id": "reference-b-v1",
                    "lineageId": "reference-b",
                    "referenceId": "reference-b-v1",
                    "referenceLineageId": "reference-b",
                    "title": "Evaluation Source B",
                    "text": (
                        "Evaluation source B describes evaluation protocols, reliability review, benchmark selection, "
                        "and measurement practices for machine learning systems."
                    ),
                    "storagePath": "corpora/test/extracted/source-b.txt",
                    "chunkIndex": 0,
                    "startChar": 0,
                    "endChar": 200,
                },
            }
        )
        return matches[:limit]


class SummaryMessageSemanticProvider:
    name = "summary-message-semantic"

    def search(self, query, scope, limit):
        return [
            {
                "rank": 1,
                "distance": 0.08,
                "kind": "message",
                "id": "message-summary-semantic",
                "lineageId": "message-summary-semantic",
                "messageKind": "reference_summary",
                "messageDomain": "summarization",
                "summary": "Semantic-hit summary: model evaluation requires reliability checks and human review.",
                "metadata": {
                    "kind": "message",
                    "id": "message-summary-semantic",
                    "lineageId": "message-summary-semantic",
                    "messageKind": "reference_summary",
                    "messageDomain": "summarization",
                    "relationTypeKey": "reference_summary_100_tokens",
                    "referenceId": "reference-1-v1",
                    "referenceLineageId": "reference-1",
                    "text": "Semantic-hit summary: model evaluation requires reliability checks and human review.",
                },
            },
            {
                "rank": 2,
                "distance": 0.12,
                "kind": "reference",
                "id": "reference-1-v1",
                "lineageId": "reference-1",
                "title": "Scaling Memo",
                "metadata": {
                    "kind": "reference",
                    "id": "reference-1-v1",
                    "lineageId": "reference-1",
                    "referenceId": "reference-1-v1",
                    "referenceLineageId": "reference-1",
                    "title": "Scaling Memo",
                    "text": (
                        "Production agent systems need reliable evaluation before deployment. "
                        "Teams measure reliability with task success, human review, and regression checks."
                    ),
                    "storagePath": "corpora/test/extracted/pipeline/snapshot/text/reference-1.txt",
                    "chunkIndex": 0,
                    "startChar": 0,
                    "endChar": 160,
                },
            },
        ][:limit]


class InsightMessageSemanticProvider:
    name = "insight-message-semantic"

    def search(self, query, scope, limit):
        return [
            {
                "rank": 1,
                "distance": 0.06,
                "kind": "message",
                "id": "message-insight-semantic",
                "lineageId": "message-insight-semantic",
                "messageKind": "insight",
                "messageDomain": "knowledge",
                "summary": "Insight: production reliability depends on routine human spot checks and clear failure taxonomies.",
                "metadata": {
                    "kind": "message",
                    "id": "message-insight-semantic",
                    "lineageId": "message-insight-semantic",
                    "messageKind": "insight",
                    "messageDomain": "knowledge",
                    "relationTypeKey": "insight_about",
                    "aboutKind": "reference",
                    "aboutId": "reference-1-v1",
                    "aboutLineageId": "reference-1",
                    "text": "Insight: production reliability depends on routine human spot checks and clear failure taxonomies.",
                },
            },
            {
                "rank": 2,
                "distance": 0.2,
                "kind": "reference",
                "id": "reference-1-v1",
                "lineageId": "reference-1",
                "title": "Scaling Memo",
                "metadata": {
                    "kind": "reference",
                    "id": "reference-1-v1",
                    "lineageId": "reference-1",
                    "referenceId": "reference-1-v1",
                    "referenceLineageId": "reference-1",
                    "title": "Scaling Memo",
                    "text": "Production agent systems need reliable evaluation before deployment.",
                    "storagePath": "corpora/test/extracted/pipeline/snapshot/text/reference-1.txt",
                    "chunkIndex": 0,
                    "startChar": 0,
                    "endChar": 80,
                },
            },
        ][:limit]


class RecordingVectorSemanticProvider(FakeVectorSemanticProvider):
    def __init__(self):
        self.queries = []

    def search(self, query, scope, limit):
        self.queries.append(query)
        return super().search(query, scope, limit)


class QualityTieSemanticProvider:
    name = "quality-tie-semantic"

    def search(self, query, scope, limit):
        return [
            {
                "rank": 1,
                "distance": 0.05,
                "kind": "reference",
                "id": "reference-low-v1",
                "lineageId": "reference-low",
                "title": "Relevant But Low Quality",
                "summary": "Production reliability evaluation for agent systems.",
                "metadata": {"corpusId": "test-corpus", "categorySetId": "test-category-set"},
            },
            {
                "rank": 2,
                "distance": 0.35,
                "kind": "reference",
                "id": "reference-high-v1",
                "lineageId": "reference-high",
                "title": "Relevant And High Quality",
                "summary": "Production reliability evaluation for agent systems.",
                "metadata": {"corpusId": "test-corpus", "categorySetId": "test-category-set"},
            },
            {
                "rank": 3,
                "distance": 0.95,
                "kind": "reference",
                "id": "reference-irrelevant-v1",
                "lineageId": "reference-irrelevant",
                "title": "Excellent But Irrelevant",
                "summary": "Unrelated visual design note.",
                "metadata": {"corpusId": "other-corpus", "categorySetId": "other-category-set"},
            },
        ][:limit]


class MixedObjectSemanticProvider:
    name = "mixed-object-semantic"

    def search(self, query, scope, limit):
        return [
            {
                "rank": 1,
                "distance": 0.08,
                "kind": "message",
                "id": "message-research-1",
                "lineageId": "message-research-1",
                "messageKind": "research_context_packet",
                "messageDomain": "workflow",
                "summary": "Research packet summary about AI agents in healthcare.",
                "metadata": {
                    "kind": "message",
                    "id": "message-research-1",
                    "lineageId": "message-research-1",
                    "messageKind": "research_context_packet",
                },
            },
            {
                "rank": 2,
                "distance": 0.1,
                "kind": "assignment",
                "id": "assignment-research-1",
                "lineageId": "assignment-research-1",
                "assignmentTypeKey": "research.source-discovery",
                "title": "Research assignment: healthcare AI agents",
                "summary": "Open research assignment linked to this topic.",
                "metadata": {
                    "kind": "assignment",
                    "id": "assignment-research-1",
                    "lineageId": "assignment-research-1",
                    "assignmentTypeKey": "research.source-discovery",
                },
            },
            {
                "rank": 3,
                "distance": 0.12,
                "kind": "item",
                "id": "item-healthcare-ai-v1",
                "lineageId": "item-healthcare-ai",
                "title": "Healthcare AI Agent Adoption",
                "summary": "Item record covering patient-care use cases.",
                "metadata": {"kind": "item", "id": "item-healthcare-ai-v1", "lineageId": "item-healthcare-ai"},
            },
        ][:limit]


class FakeGraphProvider:
    name = "fake-graph"

    def resolve_anchor(self, anchor):
        if anchor["kind"] == "message":
            summaries = {
                "message-summary-100": "Short summary: production agents need reliability evaluation and human review.",
                "message-summary-200": (
                    "Medium summary: production agents need reliability evaluation before deployment. "
                    "The source emphasizes task success, regression checks, observability, and human review as practical controls."
                ),
                "message-summary-500": (
                    "Long summary: production agents need reliability evaluation before deployment. "
                    "The source emphasizes task success, regression checks, observability, and human review as practical controls. "
                    "It connects measurement choices to production risk, repeatability, and the need to understand failures before agents are trusted."
                ),
                "message-summary-semantic": "Semantic-hit summary: model evaluation requires reliability checks and human review.",
                "message-insight-semantic": (
                    "Insight: production reliability depends on routine human spot checks and clear failure taxonomies."
                ),
            }
            message_id = anchor["id"]
            if message_id.startswith("message-insight"):
                return {
                    "kind": "message",
                    "id": message_id,
                    "lineageId": anchor.get("lineageId", message_id),
                    "messageKind": "insight",
                    "messageDomain": "knowledge",
                    "status": "active",
                    "summary": summaries.get(message_id, "Insight message."),
                    "source": "papyrus-insight-agent",
                    "createdAt": "2026-05-19T12:10:00Z",
                }
            return {
                "kind": "message",
                "id": message_id,
                "lineageId": anchor.get("lineageId", message_id),
                "messageKind": "reference_summary",
                "messageDomain": "summarization",
                "status": "active",
                "summary": summaries.get(message_id, "Summary message."),
                "source": "papyrus-summary-generator",
                "createdAt": "2026-05-19T12:00:00Z",
            }
        if anchor["kind"] == "reference":
            return {
                "kind": "reference",
                "id": anchor["id"],
                "lineageId": anchor.get("lineageId", anchor["id"]),
                "title": "Scaling Memo",
                "authors": ["Ada Reporter"],
                "sourceUri": "https://example.com/scaling",
                "curationStatus": "accepted",
                "corpusId": "test-corpus",
                "categorySetId": "test-category-set",
            }
        if anchor["kind"] == "item":
            return {
                "kind": "item",
                "id": anchor["id"],
                "lineageId": anchor.get("lineageId", anchor["id"]),
                "type": "article",
                "title": "Production Agent Evaluation",
                "deck": "A newsroom article about measuring agent reliability in deployed systems.",
                "body": ["Article body fallback about production measurement for agent systems."],
                "corpusId": "test-corpus",
                "categorySetId": "test-category-set",
            }
        return {
            "kind": anchor["kind"],
            "id": anchor["id"],
            "lineageId": anchor.get("lineageId", anchor["id"]),
            "title": "Scaling Agents",
            "description": "Accepted topic about scaling agent systems.",
            "status": "accepted",
            "corpusId": "test-corpus",
            "categorySetId": "test-category-set",
        }

    def expand_anchor(self, anchor, scope):
        relations = [
            {
                "id": "relation-message-1",
                "predicate": "comment",
                "relationTypeKey": "comment",
                "relationDomain": "commentary",
                "subjectKind": "message",
                "subjectId": "message-1",
                "subjectLineageId": "message-1",
                "objectKind": "category",
                "objectId": anchor["id"],
                "objectLineageId": anchor["lineageId"],
                "metadata": {"summary": "Operational curation note should be excluded by default."},
                "score": 0.8,
            },
            {
                "id": "relation-topic-1",
                "predicate": "classified_as",
                "relationTypeKey": "classified_as",
                "relationDomain": "knowledge",
                "subjectKind": "reference",
                "subjectId": "reference-1-v1",
                "subjectLineageId": "reference-1",
                "objectKind": "category",
                "objectId": anchor["id"],
                "objectLineageId": anchor["lineageId"],
                "metadata": {"summary": "Reference is classified under scaling agent systems."},
                "score": 0.93,
            },
        ]
        return {
            "objects": [
                {
                    "kind": "reference",
                    "id": "reference-1-v1",
                    "lineageId": "reference-1",
                    "title": "Scaling Memo",
                    "authors": ["Ada Reporter"],
                    "sourceUri": "https://example.com/scaling",
                    "curationStatus": "accepted",
                }
            ],
            "relations": [relation for relation in relations if relation_allowed_for_scope(relation, scope)],
            "excludedRelations": [relation for relation in relations if not relation_allowed_for_scope(relation, scope)],
            "warnings": [],
        }

    def list_reference_attachments(self, reference):
        return [
            {
                "id": "attachment-1",
                "referenceId": "reference-1-v1",
                "referenceLineageId": "reference-1",
                "role": "extracted_text",
                "sortKey": "900-extracted-text",
                "storagePath": "corpora/test/extracted/pipeline/snapshot/text/reference-1.txt",
                "mediaType": "text/plain",
            }
        ]

    def list_outgoing_relations(self, obj):
        if obj.get("kind") == "message" and obj.get("lineageId") == "message-summary-semantic":
            return [
                {
                    "id": "summary-reference-1-semantic",
                    "relationState": "current",
                    "predicate": "reference_summary_100_tokens",
                    "relationTypeKey": "reference_summary_100_tokens",
                    "relationDomain": "summarization",
                    "subjectKind": "message",
                    "subjectId": "message-summary-semantic",
                    "subjectLineageId": "message-summary-semantic",
                    "objectKind": "reference",
                    "objectId": "reference-1-v1",
                    "objectLineageId": "reference-1",
                    "metadata": {"maxTokens": 100, "actualTokenEstimate": 20},
                    "importedAt": "2026-05-19T12:30:00Z",
                }
            ]
        if obj.get("kind") == "message" and obj.get("lineageId") == "message-insight-semantic":
            return [
                {
                    "id": "insight-about-reference-1",
                    "relationState": "current",
                    "predicate": "insight_about",
                    "relationTypeKey": "insight_about",
                    "relationDomain": "knowledge",
                    "subjectKind": "message",
                    "subjectId": "message-insight-semantic",
                    "subjectLineageId": "message-insight-semantic",
                    "objectKind": "reference",
                    "objectId": "reference-1-v1",
                    "objectLineageId": "reference-1",
                    "importedAt": "2026-05-19T12:31:00Z",
                }
            ]
        if obj.get("kind") != "reference":
            return []
        lineage_id = obj.get("lineageId") or obj.get("id")
        if lineage_id == "reference-1":
            return [
                {
                    "id": "quality-reference-1",
                    "relationState": "current",
                    "predicate": "quality_rating_is",
                    "relationTypeKey": "quality_rating_is",
                    "relationDomain": "curation",
                    "subjectKind": "reference",
                    "subjectId": "reference-1-v1",
                    "subjectLineageId": "reference-1",
                    "objectKind": "semanticNode",
                    "objectId": "quality.rating.4_star-v1",
                    "objectLineageId": "quality.rating.4_star",
                    "score": 4,
                    "confidence": 0.8,
                    "updatedAt": "2026-05-19T12:00:00Z",
                }
            ]
        if lineage_id in {"reference-low", "reference-high", "reference-irrelevant"}:
            score = {"reference-low": 1, "reference-high": 5, "reference-irrelevant": 5}[lineage_id]
            return [
                {
                    "id": f"quality-{lineage_id}",
                    "relationState": "current",
                    "predicate": "quality_rating_is",
                    "relationTypeKey": "quality_rating_is",
                    "relationDomain": "curation",
                    "subjectKind": "reference",
                    "subjectId": f"{lineage_id}-v1",
                    "subjectLineageId": lineage_id,
                    "objectKind": "semanticNode",
                    "objectId": f"quality.rating.{score}_star-v1",
                    "objectLineageId": f"quality.rating.{score}_star",
                    "score": score,
                    "confidence": 0.9,
                    "updatedAt": "2026-05-19T12:00:00Z",
                }
            ]
        return []

    def list_incoming_relations(self, obj):
        if obj.get("kind") != "reference":
            return []
        lineage_id = obj.get("lineageId") or obj.get("id")
        if lineage_id != "reference-1":
            return []
        relations = []
        for tokens in (100, 200, 500):
            relations.append(
                {
                    "id": f"summary-reference-1-{tokens}",
                    "relationState": "current",
                    "predicate": f"reference_summary_{tokens}_tokens",
                    "relationTypeKey": f"reference_summary_{tokens}_tokens",
                    "relationDomain": "summarization",
                    "subjectKind": "message",
                    "subjectId": f"message-summary-{tokens}",
                    "subjectLineageId": f"message-summary-{tokens}",
                    "objectKind": "reference",
                    "objectId": "reference-1-v1",
                    "objectLineageId": "reference-1",
                    "metadata": {"maxTokens": tokens, "actualTokenEstimate": tokens},
                    "importedAt": "2026-05-19T12:00:00Z",
                }
            )
        return relations


class FakeVectorIndexGraphProvider:
    name = "fake-vector-index-graph"

    def __init__(self):
        self.references = [
            {
                "id": "reference-1-v1",
                "lineageId": "reference-1",
                "versionState": "current",
                "curationStatus": "accepted",
                "corpusId": "test-corpus",
                "title": "Evaluation Source One",
                "metadata": json.dumps({"subtitle": "Operational measurement and regression discipline"}),
                "authors": ["Ada Reporter"],
                "sourceUri": "https://example.com/one",
            },
            {
                "id": "reference-2-v1",
                "lineageId": "reference-2",
                "versionState": "current",
                "curationStatus": "accepted",
                "corpusId": "test-corpus",
                "title": "Evaluation Source Two",
                "metadata": json.dumps({"subtitle": "Production readiness and review operations"}),
                "authors": ["Grace Editor"],
                "sourceUri": "https://example.com/two",
            },
            {
                "id": "reference-draft-v1",
                "lineageId": "reference-draft",
                "versionState": "current",
                "curationStatus": "proposed",
                "corpusId": "test-corpus",
                "title": "Draft Source",
            },
        ]
        self.messages = [
            {
                "id": "message-insight-1",
                "lineageId": "message-insight-1",
                "messageKind": "insight",
                "messageDomain": "knowledge",
                "status": "active",
                "summary": "Insight summary: reliability work needs repeatable scorecards and routine human checks.",
            },
            {
                "id": "message-comment-1",
                "lineageId": "message-comment-1",
                "messageKind": "comment",
                "messageDomain": "commentary",
                "status": "active",
                "summary": "Comment summary: this is a curation note and should not be indexed as insight.",
            },
        ]

    def graphql(self, query, variables):
        if "listMessagesByKindAndCreatedAt" in query:
            return {
                "listMessagesByKindAndCreatedAt": {
                    "items": [message for message in self.messages if message["messageKind"] == variables.get("messageKind")],
                    "nextToken": None,
                }
            }
        if "listModelAttachmentsByOwnerRoleAndSortKey" in query:
            payload = {}
            for key, value in variables.items():
                if not key.startswith("m"):
                    continue
                alias = f"a{key[1:]}"
                payload[alias] = {
                    "items": [
                        {
                            "id": f"model-attachment-{value}-body",
                            "ownerKind": "message",
                            "ownerId": value,
                            "role": "message_body",
                            "sortKey": "message",
                            "storagePath": f"newsroom/payloads/message/{value}/message-body/message.md",
                            "mediaType": "text/markdown",
                            "status": "active",
                        }
                    ],
                    "nextToken": None,
                }
            return payload
        return {"listReferences": {"items": self.references, "nextToken": None}}

    def resolve_anchor(self, anchor):
        if anchor.get("kind") == "message":
            message_id = anchor.get("id")
            summaries = {
                "message-summary-100": "Short summary: production readiness depends on clear regression checks.",
                "message-summary-500": (
                    "Long summary: production readiness depends on clear regression checks, human oversight, "
                    "and consistent reliability evaluation across deployment cycles."
                ),
            }
            return {
                "kind": "message",
                "id": message_id,
                "lineageId": anchor.get("lineageId", message_id),
                "messageKind": "reference_summary",
                "messageDomain": "summarization",
                "status": "active",
                "summary": summaries.get(message_id, ""),
                "createdAt": "2026-05-19T12:00:00Z",
            }
        return anchor

    def list_reference_attachments(self, reference):
        return [
            {
                "role": "extracted_text",
                "storagePath": f"corpora/test/{reference['lineageId']}.txt",
            }
        ]

    def list_incoming_relations(self, obj):
        if obj.get("kind") != "reference":
            return []
        if (obj.get("lineageId") or obj.get("id")) != "reference-1":
            return []
        return [
            {
                "id": "summary-reference-1-100",
                "relationState": "current",
                "predicate": "reference_summary_100_tokens",
                "relationTypeKey": "reference_summary_100_tokens",
                "subjectKind": "message",
                "subjectId": "message-summary-100",
                "subjectLineageId": "message-summary-100",
                "objectKind": "reference",
                "objectId": "reference-1-v1",
                "objectLineageId": "reference-1",
                "importedAt": "2026-05-19T12:00:00Z",
            },
            {
                "id": "summary-reference-1-500",
                "relationState": "current",
                "predicate": "reference_summary_500_tokens",
                "relationTypeKey": "reference_summary_500_tokens",
                "subjectKind": "message",
                "subjectId": "message-summary-500",
                "subjectLineageId": "message-summary-500",
                "objectKind": "reference",
                "objectId": "reference-1-v1",
                "objectLineageId": "reference-1",
                "importedAt": "2026-05-19T12:10:00Z",
            },
        ]

    def list_outgoing_relations(self, obj):
        if obj.get("kind") != "message":
            return []
        lineage_id = obj.get("lineageId") or obj.get("id")
        if lineage_id == "message-insight-1":
            return [
                {
                    "id": "relation-insight-1",
                    "relationState": "current",
                    "predicate": "insight_about",
                    "relationTypeKey": "insight_about",
                    "relationDomain": "knowledge",
                    "subjectKind": "message",
                    "subjectId": "message-insight-1",
                    "subjectLineageId": "message-insight-1",
                    "objectKind": "reference",
                    "objectId": "reference-1-v1",
                    "objectLineageId": "reference-1",
                }
            ]
        return []


class FakeVectorIndexTextProvider:
    def read_text(self, storage_path):
        if "message-insight-1" in storage_path:
            return (
                "Insight body: teams should inspect reliability evidence across many production runs, "
                "watch for evaluator drift, and keep human review notes close to deployment decisions. "
                "Insight body detail repeats for passage chunk creation."
            )
        return (
            (
                f"{storage_path} describes model evaluation, production monitoring, reliability checks, "
                "human review, regression testing, benchmark design, and operational measurement. "
                "The document discusses how teams decide whether AI systems are ready for deployment.\n"
            )
        ) * 8


class ShortFakeVectorIndexTextProvider(FakeVectorIndexTextProvider):
    def read_text(self, storage_path):
        if "message-insight-1" in storage_path:
            return super().read_text(storage_path)
        return "Tiny source text."

    def list_incoming_relations(self, obj):
        if obj.get("kind") != "reference":
            return []
        lineage_id = obj.get("lineageId") or obj.get("id")
        if lineage_id != "reference-1":
            return []
        relations = []
        for tokens in (100, 200, 500):
            relations.append(
                {
                    "id": f"summary-reference-1-{tokens}",
                    "relationState": "current",
                    "predicate": f"reference_summary_{tokens}_tokens",
                    "relationTypeKey": f"reference_summary_{tokens}_tokens",
                    "relationDomain": "summarization",
                    "subjectKind": "message",
                    "subjectId": f"message-summary-{tokens}",
                    "subjectLineageId": f"message-summary-{tokens}",
                    "objectKind": "reference",
                    "objectId": "reference-1-v1",
                    "objectLineageId": "reference-1",
                    "metadata": {"maxTokens": tokens, "actualTokenEstimate": tokens},
                    "importedAt": "2026-05-19T12:00:00Z",
                }
            )
        return relations


class FakeVectorIndexGraphProviderWithoutMessageBody(FakeVectorIndexGraphProvider):
    def graphql(self, query, variables):
        if "listModelAttachmentsByOwnerRoleAndSortKey" in query:
            payload = {}
            for key in variables:
                if key.startswith("m"):
                    payload[f"a{key[1:]}"] = {"items": [], "nextToken": None}
            return payload
        return super().graphql(query, variables)


class FakeCorpusTextProvider:
    name = "fake-corpus-text"

    def read_text(self, storage_path):
        return (
            "Abstract\n"
            "Production agent systems need reliable evaluation before deployment. "
            "Teams measure reliability with task success, human review, and regression checks. "
            "The study reports that human evaluation remains central for production agents.\n"
            "1. Results\n"
            "Agent memory systems are useful only when their behavior is observable and repeatable."
        )


class LongFakeCorpusTextProvider(FakeCorpusTextProvider):
    def read_text(self, storage_path):
        return "\n\n".join([super().read_text(storage_path)] * 12)


def fake_services():
    return KnowledgeQueryServices(graph=FakeGraphProvider(), semantic=FakeSemanticProvider(), corpus_text=FakeCorpusTextProvider())


class KnowledgeQueryTests(unittest.TestCase):
    def test_vector_match_diversification_limits_repeated_reference_chunks(self):
        matches = [
            {"id": "ref-a-v1", "lineageId": "ref-a", "providerRank": 1, "metadata": {"referenceLineageId": "ref-a"}},
            {"id": "ref-a-v1", "lineageId": "ref-a", "providerRank": 2, "metadata": {"referenceLineageId": "ref-a"}},
            {"id": "ref-a-v1", "lineageId": "ref-a", "providerRank": 3, "metadata": {"referenceLineageId": "ref-a"}},
            {"id": "ref-b-v1", "lineageId": "ref-b", "providerRank": 4, "metadata": {"referenceLineageId": "ref-b"}},
            {"id": "ref-c-v1", "lineageId": "ref-c", "providerRank": 5, "metadata": {"referenceLineageId": "ref-c"}},
        ]

        diversified = diversify_vector_matches(matches, 4)

        self.assertEqual([match["lineageId"] for match in diversified], ["ref-a", "ref-b", "ref-c", "ref-a"])
        self.assertEqual([match["rank"] for match in diversified], [1, 2, 3, 4])

    def test_vector_match_diversification_can_cap_repeated_sources(self):
        matches = [
            {"id": "ref-a-v1", "lineageId": "ref-a", "providerRank": 1, "metadata": {"referenceLineageId": "ref-a"}},
            {"id": "ref-a-v1", "lineageId": "ref-a", "providerRank": 2, "metadata": {"referenceLineageId": "ref-a"}},
            {"id": "ref-b-v1", "lineageId": "ref-b", "providerRank": 3, "metadata": {"referenceLineageId": "ref-b"}},
            {"id": "ref-b-v1", "lineageId": "ref-b", "providerRank": 4, "metadata": {"referenceLineageId": "ref-b"}},
            {"id": "ref-c-v1", "lineageId": "ref-c", "providerRank": 5, "metadata": {"referenceLineageId": "ref-c"}},
        ]

        diversified = diversify_vector_matches(matches, 10, max_per_source=1)

        self.assertEqual([match["lineageId"] for match in diversified], ["ref-a", "ref-b", "ref-c"])
        self.assertEqual([match["rank"] for match in diversified], [1, 2, 3])

    def test_broad_s3_vector_search_queries_new_and_legacy_insight_vector_kinds(self):
        provider = S3VectorsProvider(vector_index_arn="arn:test:index")
        queried_kinds = []

        def fake_query(_vector, _scope, _query_limit, vector_kind=None):
            queried_kinds.append(vector_kind)
            return []

        with mock.patch.object(provider, "_embed", return_value=[0.1, 0.2, 0.3]), \
             mock.patch.object(provider, "_query_vectors", side_effect=fake_query):
            provider.search("evaluation", {"rankingDiversity": "broad"}, 5)

        self.assertIn("reference_summary", queried_kinds)
        self.assertIn("insight_source", queried_kinds)
        self.assertIn("insight_summary", queried_kinds)
        self.assertIn("insight_passage", queried_kinds)

    def test_s3_vector_filter_can_target_explicit_chat_detail(self):
        provider = S3VectorsProvider(vector_index_arn="arn:test:index")

        metadata_filter = provider._metadata_filter({
            "semanticLayer": "chat_detail",
            "searchVisibility": "explicit",
            "objectKind": "message",
        })

        self.assertEqual(metadata_filter, {
            "$and": [
                {"semanticLayer": {"$eq": "chat_detail"}},
                {"searchVisibility": {"$eq": "explicit"}},
                {"kind": {"$eq": "message"}},
            ]
        })

    def test_quality_signal_reads_current_relation_score(self):
        signal, warning = quality_signal_from_relations([
            {
                "id": "quality-1",
                "relationState": "current",
                "relationTypeKey": "quality_rating_is",
                "predicate": "quality_rating_is",
                "subjectKind": "reference",
                "subjectLineageId": "reference-1",
                "objectKind": "semanticNode",
                "objectLineageId": "quality.rating.4_star",
                "score": 4,
            }
        ])

        self.assertIsNone(warning)
        self.assertTrue(signal["qualityKnown"])
        self.assertEqual(signal["qualityRating"], 4)
        self.assertEqual(signal["qualityScore"], quality_score_from_rating(4))
        self.assertEqual(signal["qualityRelationId"], "quality-1")

    def test_quality_signal_uses_object_node_fallback_and_warns_on_duplicates(self):
        signal, warning = quality_signal_from_relations([
            {
                "id": "quality-old",
                "relationState": "current",
                "predicate": "quality_rating_is",
                "subjectKind": "reference",
                "subjectLineageId": "reference-1",
                "objectKind": "semanticNode",
                "objectLineageId": "quality.rating.2_star",
                "confidence": 0.4,
                "updatedAt": "2026-05-18T12:00:00Z",
            },
            {
                "id": "quality-new",
                "relationState": "current",
                "relationTypeKey": "quality_rating_is",
                "subjectKind": "reference",
                "subjectLineageId": "reference-1",
                "objectKind": "semanticNode",
                "objectLineageId": "quality.rating.4_star",
                "confidence": 0.9,
                "updatedAt": "2026-05-19T12:00:00Z",
            },
        ])

        self.assertIn("Multiple current quality_rating_is relations", warning)
        self.assertEqual(signal["qualityRating"], 4)
        self.assertEqual(signal["qualityRelationId"], "quality-new")

    def test_quality_missing_is_unknown_and_neutral(self):
        signal, warning = quality_signal_from_relations([])

        self.assertIsNone(warning)
        self.assertFalse(signal["qualityKnown"])
        self.assertIsNone(signal["qualityRating"])
        self.assertEqual(signal["qualityScore"], 0.5)

    def test_token_counter_matches_tiktoken_default_encoding(self):
        try:
            import tiktoken
        except Exception as exc:  # pragma: no cover - dependency guard
            self.skipTest(f"tiktoken unavailable: {exc}")

        text = "# Context\n\nProduction agents rely on human evaluation, task success, and regression checks."
        counter = TokenCounter()
        encoding = tiktoken.get_encoding("o200k_base")

        self.assertEqual(counter.count(text), len(encoding.encode(text)))
        self.assertEqual(counter.metadata()["provider"], "tiktoken")
        self.assertEqual(counter.metadata()["encoding"], "o200k_base")

    def test_token_counter_truncate_stays_under_budget(self):
        counter = TokenCounter()
        text = "Production measurement and reliability evaluation for LLM agents. " * 20
        truncated = counter.truncate(text, 17)

        self.assertLessEqual(counter.count(truncated), 17)

    def test_token_counter_regex_fallback_can_be_forced(self):
        counter = TokenCounter(use_tiktoken=False)

        self.assertEqual(counter.metadata()["provider"], "regex")
        self.assertEqual(counter.metadata()["encoding"], "regex-word-punctuation")
        self.assertEqual(counter.count("agent memory systems."), 4)
        self.assertEqual(counter.truncate("agent memory systems.", 2), "agent memory")

    def test_core_returns_structured_and_budgeted_markdown(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "agent memory systems",
                "scope": {"depth": 1, "topK": 5},
                "profile": "editor",
                "output": {"format": "both", "maxTokens": 80},
            },
            fake_services(),
        )

        self.assertEqual(result["provenance"]["graphProvider"], "fake-graph")
        self.assertEqual(result["provenance"]["semanticProvider"], "fake-semantic")
        self.assertEqual(result["structured"]["anchors"][0]["title"], "Scaling Agents")
        self.assertEqual(result["structured"]["semanticMatches"][0]["title"], "Agent Memory")
        self.assertIn("Production agent systems need reliable evaluation", result["context"]["text"])
        self.assertNotIn("Operational curation note", result["context"]["text"])
        self.assertLessEqual(result["context"]["totalTokens"], 80)
        self.assertEqual(result["context"]["tokenizer"]["provider"], "tiktoken")
        self.assertEqual(result["context"]["tokenizer"]["encoding"], "o200k_base")
        self.assertEqual(result["debug"]["tokenizerProvider"], "tiktoken")
        self.assertEqual(result["debug"]["tokenizerEncoding"], "o200k_base")
        self.assertEqual(result["structured"]["request"]["ranking"]["diversity"], "balanced")
        self.assertEqual(result["debug"]["diversityProfile"], "balanced")
        self.assertEqual(result["debug"]["vectorDiversification"], "source_round_robin")
        self.assertTrue(any(stage["name"] == "semantic_search" for stage in result["debug"]["stageTimings"]))
        self.assertIn("semanticUniqueSourceCount", result["debug"])

    def test_reporting_profile_is_supported_without_fallback_warning(self):
        result = run_knowledge_query(
            {
                "semanticQuery": "AI in video games reporting orientation",
                "profile": "reporting",
                "output": {"format": "structured", "maxTokens": 120},
            },
            fake_services(),
        )
        self.assertEqual(result["structured"]["request"]["profile"], "reporting")
        self.assertFalse(any("Unknown profile" in warning for warning in result.get("warnings") or []))

    def test_uri_anchor_resolves_like_explicit_anchor(self):
        explicit = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling", "lineageId": "category-scaling"}],
                "output": {"format": "structured", "maxTokens": 120},
            },
            fake_services(),
        )
        by_uri = run_knowledge_query(
            {
                "anchors": [{"uri": "papyrus://category/category-scaling"}],
                "output": {"format": "structured", "maxTokens": 120},
            },
            fake_services(),
        )

        self.assertEqual(by_uri["structured"]["anchors"][0]["kind"], explicit["structured"]["anchors"][0]["kind"])
        self.assertEqual(by_uri["structured"]["anchors"][0]["lineageId"], explicit["structured"]["anchors"][0]["lineageId"])
        self.assertEqual(by_uri["structured"]["anchors"][0]["objectUri"], "papyrus://category/category-scaling")

    def test_unknown_diversity_warns_and_falls_back_to_balanced(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "ranking": {"diversity": "wide"},
                "output": {"format": "structured"},
            },
            fake_services(),
        )

        self.assertEqual(result["structured"]["request"]["ranking"]["diversity"], "balanced")
        self.assertTrue(any("Unknown ranking.diversity" in warning for warning in result["warnings"]))

    def test_broad_diversity_warns_when_semantic_source_spread_is_not_satisfied(self):
        result = run_knowledge_query(
            {
                "semanticQuery": "evaluation",
                "ranking": {"diversity": "broad"},
                "scope": {"topK": 5, "relatedRecordLimit": 8, "semanticSeedLimit": 0},
                "output": {"format": "structured"},
            },
            KnowledgeQueryServices(graph=None, semantic=FakeVectorSemanticProvider(), corpus_text=None),
        )

        self.assertEqual(result["debug"]["semanticUniqueSourceCount"], 2)
        self.assertEqual(result["debug"]["semanticSourceTarget"], 5)
        self.assertTrue(any("Broad diversity requested" in warning for warning in result["warnings"]))

    def test_output_tokenizer_model_override_is_reported(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "output": {"format": "markdown", "maxTokens": 120, "tokenizerModel": "gpt-4o-mini"},
            },
            fake_services(),
        )

        self.assertEqual(result["context"]["tokenizer"]["provider"], "tiktoken")
        self.assertEqual(result["context"]["tokenizer"]["model"], "gpt-4o-mini")
        self.assertEqual(result["debug"]["tokenizerModel"], "gpt-4o-mini")

    def test_anchor_without_semantic_query_derives_query_for_see_also(self):
        semantic = RecordingVectorSemanticProvider()
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=semantic,
            corpus_text=FakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "reference", "id": "reference-1-v1", "lineageId": "reference-1"}],
                "output": {"format": "markdown", "maxTokens": 500},
            },
            services,
        )

        self.assertEqual(result["structured"]["request"]["semanticQuerySource"], "anchor_derived")
        self.assertEqual(result["debug"]["semanticQuerySource"], "anchor_derived")
        self.assertEqual(len(semantic.queries), 1)
        self.assertIn("Scaling Memo", semantic.queries[0])
        self.assertIn("## See Also", result["context"]["text"])
        self.assertIn("Production Agent Evaluation", result["context"]["text"])

    def test_multi_source_markdown_groups_metadata_and_excerpts_by_source(self):
        blocks = [
            ContextBlock("summary", "knowledge_summary", "", "Query focus: agent evaluation.", 120, True),
            ContextBlock(
                "source.a",
                "sources",
                "Source A",
                "Source A\nPapyrus URI: papyrus://reference/a",
                60,
                provenance={"objectUri": "papyrus://reference/a"},
            ),
            ContextBlock(
                "source.b",
                "sources",
                "Source B",
                "Source B\nPapyrus URI: papyrus://reference/b",
                60,
                provenance={"objectUri": "papyrus://reference/b"},
            ),
            ContextBlock(
                "passage.a",
                "source_excerpts",
                "Source A",
                "1. Evidence from source A.",
                110,
                provenance={"objectUri": "papyrus://reference/a", "reason": "semantic_vector", "startChar": 25, "endChar": 50, "truncated": True},
            ),
            ContextBlock(
                "passage.b",
                "source_excerpts",
                "Source B",
                "Evidence from source B.",
                110,
                provenance={"objectUri": "papyrus://reference/b", "reason": "query_overlap"},
            ),
        ]

        result = _render_markdown_context(blocks, 500, KnowledgeQueryServices())
        text = result["text"]

        self.assertIn("## Source Context", text)
        self.assertNotIn("## Source Excerpts", text)
        self.assertNotIn("## Sources", text)
        self.assertNotIn("#### Evidence", text)
        self.assertLess(text.index("### Source A"), text.index("Evidence from source A"))
        self.assertLess(text.index("Evidence from source A"), text.index("### Source B"))
        self.assertLess(text.index("### Source B"), text.index("Evidence from source B."))
        self.assertIn("... Evidence from source A ...", text)
        self.assertNotIn("1. Evidence from source A.", text)

    def test_multi_target_markdown_separates_see_also_records(self):
        blocks = [
            ContextBlock("summary", "knowledge_summary", "", "Query focus: agent evaluation.", 120, True),
            ContextBlock(
                "target.a",
                "target_records",
                "Target A",
                "Target A\nPapyrus URI: papyrus://reference/a",
                60,
                provenance={"objectUri": "papyrus://reference/a"},
            ),
            ContextBlock(
                "target.b",
                "target_records",
                "Target B",
                "Target B\nPapyrus URI: papyrus://reference/b",
                60,
                provenance={"objectUri": "papyrus://reference/b"},
            ),
            ContextBlock(
                "passage.a",
                "source_excerpts",
                "Target A",
                "Target A excerpt.",
                110,
                provenance={"objectUri": "papyrus://reference/a"},
            ),
            ContextBlock(
                "passage.c",
                "source_excerpts",
                "See Also Source",
                "This semantic match excerpt should not be grouped with targets.",
                110,
                provenance={"objectUri": "papyrus://reference/c"},
            ),
            ContextBlock(
                "related.c",
                "related_records",
                "See Also Source",
                "Object: papyrus://reference/c\nWhy related: semantic match.\n" + ("• Related summary. " * 30),
                55,
                provenance={"objectUri": "papyrus://reference/c"},
            ),
        ]

        result = _render_markdown_context(blocks, 700, KnowledgeQueryServices(), see_also_max_tokens=70)
        text = result["text"]

        self.assertIn("## Target Records", text)
        self.assertIn("### Target A", text)
        self.assertIn("### Target B", text)
        self.assertIn("Target A excerpt.", text)
        self.assertNotIn("This semantic match excerpt should not be grouped with targets.", text)
        self.assertIn("## See Also", text)
        self.assertIn("### See Also Source", text)
        self.assertNotIn("• Related summary.", text)
        self.assertLessEqual(result["totalTokens"], 700)
        see_also_text = text.split("## See Also", 1)[1]
        self.assertLessEqual(KnowledgeQueryServices().token_counter.count("## See Also" + see_also_text), 70)

    def test_default_policy_excludes_operational_relations(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "output": {"format": "markdown", "maxTokens": 240},
            },
            fake_services(),
        )

        relation_keys = {relation["relationTypeKey"] for relation in result["structured"]["relations"]}
        operational_keys = {relation["relationTypeKey"] for relation in result["structured"]["operationalRelations"]}
        self.assertIn("classified_as", relation_keys)
        self.assertNotIn("comment", relation_keys)
        self.assertIn("comment", operational_keys)
        self.assertNotIn("Operational curation note", result["context"]["text"])
        self.assertNotIn("Operational curation/workflow relations were excluded", result["context"]["text"])
        self.assertNotIn("## Gaps And Limits", result["context"]["text"])

    def test_explicit_relation_types_include_operational_relations(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "scope": {"relationTypes": ["comment"]},
                "output": {"format": "markdown", "maxTokens": 240},
            },
            fake_services(),
        )

        relation_keys = {relation["relationTypeKey"] for relation in result["structured"]["relations"]}
        self.assertIn("comment", relation_keys)

    def test_provenance_appendix_renders_operational_relations_when_requested(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "output": {"format": "markdown", "maxTokens": 260, "includeProvenanceAppendix": True},
            },
            fake_services(),
        )

        self.assertIn("## Provenance Appendix", result["context"]["text"])
        self.assertIn("Operational curation note", result["context"]["text"])

    def test_evidence_passages_are_structured_output(self):
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "production reliability evaluation",
                "output": {"format": "both", "maxTokens": 300},
            },
            fake_services(),
        )

        self.assertGreaterEqual(len(result["structured"]["evidencePassages"]), 1)
        self.assertIn("Full Source Text", result["context"]["text"])
        self.assertEqual(result["context"]["sourceTextMode"], "full")
        self.assertNotIn("message#", result["context"]["text"])

    def test_related_records_default_excludes_message_and_assignment(self):
        services = KnowledgeQueryServices(
            graph=None,
            semantic=MixedObjectSemanticProvider(),
            corpus_text=None,
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "healthcare ai agents patient care",
                "scope": {"topK": 5, "relatedRecordLimit": 5},
                "output": {"format": "structured"},
            },
            services,
        )

        related_kinds = {record.get("kind") for record in result["structured"]["relatedRecords"]}
        self.assertEqual(related_kinds, {"item"})

    def test_related_records_can_include_message_and_assignment(self):
        services = KnowledgeQueryServices(
            graph=None,
            semantic=MixedObjectSemanticProvider(),
            corpus_text=None,
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "healthcare ai agents patient care",
                "scope": {
                    "topK": 5,
                    "relatedRecordLimit": 5,
                    "includeObjectKinds": ["item", "message", "assignment"],
                    "includeMessageKinds": ["research_context_packet"],
                    "includeAssignmentTypeKeys": ["research.*"],
                },
                "output": {"format": "structured"},
            },
            services,
        )

        related_kinds = {record.get("kind") for record in result["structured"]["relatedRecords"]}
        self.assertEqual(related_kinds, {"item", "message", "assignment"})

    def test_related_records_assignment_type_wildcard_exclude(self):
        services = KnowledgeQueryServices(
            graph=None,
            semantic=MixedObjectSemanticProvider(),
            corpus_text=None,
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "healthcare ai agents patient care",
                "scope": {
                    "topK": 5,
                    "relatedRecordLimit": 5,
                    "includeObjectKinds": ["item", "assignment"],
                    "includeAssignmentTypeKeys": ["research.*"],
                    "excludeAssignmentTypeKeys": ["research.source-*"],
                },
                "output": {"format": "structured"},
            },
            services,
        )

        related_kinds = {record.get("kind") for record in result["structured"]["relatedRecords"]}
        self.assertEqual(related_kinds, {"item"})

    def test_semantic_vector_passages_become_source_excerpts(self):
        services = KnowledgeQueryServices(
            graph=None,
            semantic=FakeVectorSemanticProvider(),
            corpus_text=None,
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "production reliability evaluation for agents",
                "scope": {"depth": 1, "topK": 4},
                "output": {"format": "both", "maxTokens": 320},
            },
            services,
        )

        self.assertGreaterEqual(len(result["structured"]["semanticPassages"]), 1)
        self.assertEqual(result["structured"]["evidencePassages"][0]["selectionReason"], "semantic_vector")
        self.assertIn("## Source Excerpts", result["context"]["text"])
        self.assertNotIn("**Semantic vector match**", result["context"]["text"])
        self.assertIn("Production agent systems need reliable evaluation", result["context"]["text"])
        self.assertIn("papyrus://reference/reference-1", result["context"]["text"])
        self.assertNotIn("### Semantic match", result["context"]["text"])
        self.assertEqual(result["context"]["sourceTextMode"], "excerpted")

    def test_single_source_markdown_starts_with_source_header(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=FakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "markdown", "maxTokens": 500, "extractMode": "always"},
            },
            services,
        )

        text = result["context"]["text"]
        self.assertTrue(text.startswith("# Scaling Memo"))
        self.assertIn("Papyrus URI: papyrus://reference/reference-1", text)
        self.assertNotIn("Primary source:", text)
        self.assertNotIn("- Scaling Memo (papyrus://reference/reference-1)", text)
        self.assertIn("## Context Summary", text)
        self.assertIn("## Full Source Text", text)
        self.assertIn("## See Also", text)
        self.assertEqual(result["context"]["sourceTextMode"], "full")

    def test_smaller_budget_falls_back_to_grouped_source_excerpts(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=LongFakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "markdown", "maxTokens": 500},
            },
            services,
        )

        text = result["context"]["text"]
        self.assertIn("## Source Excerpts", text)
        self.assertNotIn("## Full Source Text", text)
        self.assertNotIn("**Semantic vector match**", text)
        source_excerpts = text.split("## Source Excerpts", 1)[1].split("## See Also", 1)[0]
        self.assertEqual(source_excerpts.count("### Scaling Memo"), 1)
        self.assertEqual(result["context"]["sourceTextMode"], "excerpted")
        self.assertLessEqual(result["context"]["totalTokens"], 500)

    def test_reference_summaries_are_selected_by_record_budget(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=LongFakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "reference", "id": "reference-1-v1", "lineageId": "reference-1"}],
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "both", "maxTokens": 420, "maxPassageTokens": 120},
            },
            services,
        )

        selected = [
            passage for passage in result["structured"]["evidencePassages"]
            if passage["selectionReason"] == "reference_summary"
        ]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["summaryMaxTokens"], 500)
        self.assertIn("summary", result["structured"]["referenceSummaries"][0])
        self.assertIn("Long summary", result["context"]["text"])
        self.assertNotIn("reference_summary_100_tokens", result["context"]["text"])
        self.assertLessEqual(result["context"]["totalTokens"], 420)

    def test_reference_summary_precedes_semantic_chunks_for_same_source(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=LongFakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "reference", "id": "reference-1-v1", "lineageId": "reference-1"}],
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "markdown", "maxTokens": 700, "maxPassageTokens": 120},
            },
            services,
        )

        text = result["context"]["text"]
        self.assertIn("Long summary", text)
        self.assertIn("Production agent systems need reliable evaluation", text)
        self.assertLess(text.index("Long summary"), text.index("Production agent systems need reliable evaluation"))

    def test_semantic_summary_message_hit_maps_to_reference_summary(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=SummaryMessageSemanticProvider(),
            corpus_text=LongFakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "model evaluation",
                "output": {"format": "both", "maxTokens": 420, "maxPassageTokens": 120},
            },
            services,
        )

        self.assertEqual(result["structured"]["semanticMatches"][0]["kind"], "reference")
        self.assertEqual(result["structured"]["semanticMatches"][0]["semanticHitKind"], "reference_summary")
        self.assertEqual(result["structured"]["semanticMatches"][0]["summaryMessageId"], "message-summary-semantic")
        selected = [
            passage for passage in result["structured"]["evidencePassages"]
            if passage.get("selectionReason") == "reference_summary"
        ]
        self.assertGreaterEqual(len(selected), 1)
        self.assertNotEqual(result["structured"]["evidencePassages"][0]["selectionReason"], "semantic_vector")
        self.assertEqual(result["structured"]["evidencePassages"][0]["selectionReason"], "reference_summary")
        self.assertNotIn("papyrus://message/message-summary-semantic", result["context"]["text"])

    def test_semantic_insight_message_hit_maps_to_insight_evidence(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=InsightMessageSemanticProvider(),
            corpus_text=LongFakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "both", "maxTokens": 420, "maxPassageTokens": 120},
            },
            services,
        )

        self.assertEqual(result["structured"]["semanticMatches"][0]["kind"], "reference")
        self.assertEqual(result["structured"]["semanticMatches"][0]["semanticHitKind"], "insight_message")
        self.assertEqual(result["structured"]["insightMessages"][0]["messageKind"], "insight")
        self.assertEqual(result["structured"]["insightMessages"][0]["relationTypeKey"], "insight_about")
        insight_passages = [
            passage for passage in result["structured"]["evidencePassages"]
            if passage.get("selectionReason") == "insight_message"
        ]
        self.assertGreaterEqual(len(insight_passages), 1)
        self.assertEqual(insight_passages[0]["insightMessageId"], "message-insight-semantic")
        self.assertNotIn("papyrus://message/message-insight-semantic", result["context"]["text"])

    def test_semantic_only_query_promotes_matches_to_related_records_and_graph_seed(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=FakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "semanticQuery": "production reliability evaluation for agents",
                "scope": {"depth": 1, "topK": 4, "semanticSeedLimit": 1, "semanticSeedExpansionLimit": 1},
                "output": {"format": "markdown", "maxTokens": 500},
            },
            services,
        )

        related_uris = {record["objectUri"] for record in result["structured"]["relatedRecords"]}
        self.assertIn("papyrus://reference/reference-1", related_uris)
        self.assertIn("papyrus://item/item-agent-eval", related_uris)
        self.assertTrue(any(obj.get("semanticSeedRank") == 1 for obj in result["structured"]["expandedObjects"]))
        self.assertEqual(result["structured"]["request"]["scope"]["semanticSeedGraphTopK"], 6)
        self.assertEqual(result["structured"]["request"]["scope"]["semanticSeedExpansionLimit"], 1)
        seed_stage = next(stage for stage in result["debug"]["stageTimings"] if stage["name"] == "expand_semantic_seeds")
        self.assertEqual(seed_stage["semanticSeedExpansionLimit"], 1)
        self.assertEqual(seed_stage["semanticSeedRelationLimit"], 4)
        self.assertFalse(seed_stage["semanticSeedResolveEnabled"])
        self.assertIn("## See Also", result["context"]["text"])
        self.assertIn("A newsroom article about measuring agent reliability", result["context"]["text"])

    def test_anchored_query_uses_same_record_vector_hit_as_evidence_not_related_record(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=FakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "reference", "id": "reference-1-v1", "lineageId": "reference-1"}],
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "both", "maxTokens": 500},
            },
            services,
        )

        related_uris = {record["objectUri"] for record in result["structured"]["relatedRecords"]}
        self.assertNotIn("papyrus://reference/reference-1", related_uris)
        self.assertIn("papyrus://item/item-agent-eval", related_uris)
        self.assertEqual(result["structured"]["evidencePassages"][0]["selectionReason"], "reference_summary")
        self.assertTrue(any(passage["selectionReason"] == "semantic_vector" for passage in result["structured"]["evidencePassages"]))
        self.assertLessEqual(result["context"]["totalTokens"], 500)

    def test_related_article_records_include_summary_and_object_uri(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=FakeVectorSemanticProvider(),
            corpus_text=FakeCorpusTextProvider(),
        )
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "production reliability evaluation for agents",
                "output": {"format": "markdown", "maxTokens": 500},
            },
            services,
        )

        article = next(record for record in result["structured"]["relatedRecords"] if record["kind"] == "item")
        self.assertEqual(article["objectUri"], "papyrus://item/item-agent-eval")
        self.assertIn("newsroom article", article["summary"])
        self.assertIn("Object: papyrus://item/item-agent-eval", result["context"]["text"])

    def test_related_records_rank_by_relevance_quality_and_graph_context(self):
        services = KnowledgeQueryServices(
            graph=FakeGraphProvider(),
            semantic=QualityTieSemanticProvider(),
            corpus_text=None,
        )
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "production reliability evaluation for agents",
                "scope": {"topK": 3, "relatedRecordLimit": 3},
                "output": {"format": "both", "maxTokens": 500},
            },
            services,
        )

        related = result["structured"]["relatedRecords"]
        self.assertEqual(related[0]["lineageId"], "reference-high")
        self.assertEqual(related[0]["ranking"]["qualityRating"], 5)
        self.assertGreater(related[0]["ranking"]["finalScore"], related[1]["ranking"]["finalScore"])
        self.assertNotIn("reference-irrelevant", {record["lineageId"] for record in related})
        self.assertNotIn("quality_rating_is", result["context"]["text"])

    def test_ranking_profiles_change_related_record_order(self):
        services = KnowledgeQueryServices(graph=FakeGraphProvider(), semantic=QualityTieSemanticProvider())
        relevance_first = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "production reliability evaluation for agents",
                "ranking": {"profile": "relevance_first"},
                "scope": {"topK": 2, "relatedRecordLimit": 2},
            },
            services,
        )
        quality_forward = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "production reliability evaluation for agents",
                "ranking": {"profile": "quality_forward"},
                "scope": {"topK": 2, "relatedRecordLimit": 2},
            },
            services,
        )

        self.assertEqual(relevance_first["structured"]["relatedRecords"][0]["lineageId"], "reference-low")
        self.assertEqual(quality_forward["structured"]["relatedRecords"][0]["lineageId"], "reference-high")

    def test_see_also_token_budgets_follow_ranking(self):
        services = KnowledgeQueryServices(graph=FakeGraphProvider(), semantic=QualityTieSemanticProvider())
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "semanticQuery": "production reliability evaluation for agents",
                "scope": {"topK": 2, "relatedRecordLimit": 2},
                "output": {"format": "markdown", "maxTokens": 500, "seeAlsoMaxTokens": 160},
            },
            services,
        )

        related = result["structured"]["relatedRecords"]
        self.assertGreaterEqual(related[0]["ranking"]["tokenBudget"], related[1]["ranking"]["tokenBudget"])
        self.assertLessEqual(result["context"]["totalTokens"], 500)

    def test_diversity_profile_changes_source_token_budgets(self):
        records = [
            {"lineageId": "reference-a", "ranking": {"finalScore": 0.95}},
            {"lineageId": "reference-b", "ranking": {"finalScore": 0.55}},
            {"lineageId": "reference-c", "ranking": {"finalScore": 0.35}},
        ]

        focused = allocate_token_budgets(records, 360, min_tokens=60, max_tokens=320, diversity="focused")
        broad = allocate_token_budgets(records, 360, min_tokens=90, max_tokens=180, diversity="broad")

        self.assertGreater(focused["reference-a"], broad["reference-a"])
        self.assertLess(max(broad.values()) - min(broad.values()), max(focused.values()) - min(focused.values()))

    def test_broad_diversity_selects_unique_sources_before_repeats(self):
        records = [
            {"id": "a-1", "lineageId": "reference-a", "ranking": {"finalScore": 0.99, "relevanceScore": 0.99, "qualityScore": 0.5}},
            {"id": "a-2", "lineageId": "reference-a", "ranking": {"finalScore": 0.98, "relevanceScore": 0.98, "qualityScore": 0.5}},
            {"id": "b-1", "lineageId": "reference-b", "ranking": {"finalScore": 0.82, "relevanceScore": 0.82, "qualityScore": 0.5}},
        ]

        focused = select_records_by_diversity(records, 2, "focused")
        broad = select_records_by_diversity(records, 2, "broad")

        self.assertEqual([record["id"] for record in focused], ["a-1", "a-2"])
        self.assertEqual([record["id"] for record in broad], ["a-1", "b-1"])

    def test_see_also_diversity_changes_summary_budget(self):
        services = KnowledgeQueryServices(graph=FakeGraphProvider(), semantic=QualityTieSemanticProvider())
        base_payload = {
            "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
            "semanticQuery": "production reliability evaluation for agents",
            "scope": {"topK": 2, "relatedRecordLimit": 2},
            "output": {"format": "markdown", "maxTokens": 500, "seeAlsoMaxTokens": 180},
        }
        focused = run_knowledge_query({**base_payload, "ranking": {"diversity": "focused"}}, services)
        broad = run_knowledge_query({**base_payload, "ranking": {"diversity": "broad"}}, services)

        focused_budget = focused["structured"]["relatedRecords"][0]["ranking"]["tokenBudget"]
        broad_budget = broad["structured"]["relatedRecords"][0]["ranking"]["tokenBudget"]
        self.assertGreater(focused_budget, broad_budget)
        self.assertEqual(focused["structured"]["relatedRecords"][0]["ranking"]["diversity"], "focused")
        self.assertEqual(broad["structured"]["relatedRecords"][0]["ranking"]["diversity"], "broad")

    def test_broad_diversity_caps_repeated_semantic_passages_per_source(self):
        services = KnowledgeQueryServices(graph=None, semantic=RepeatedChunkSemanticProvider(), corpus_text=None)
        focused = run_knowledge_query(
            {
                "semanticQuery": "model evaluation",
                "ranking": {"diversity": "focused"},
                "scope": {"topK": 5},
                "output": {"format": "both", "maxTokens": 800, "maxPassages": 5, "maxPassageTokens": 120},
            },
            services,
        )
        broad = run_knowledge_query(
            {
                "semanticQuery": "model evaluation",
                "ranking": {"diversity": "broad"},
                "scope": {"topK": 5},
                "output": {"format": "both", "maxTokens": 800, "maxPassages": 5, "maxPassageTokens": 120},
            },
            services,
        )

        focused_a = [
            passage for passage in focused["structured"]["evidencePassages"]
            if passage.get("referenceLineageId") == "reference-a"
        ]
        broad_a = [
            passage for passage in broad["structured"]["evidencePassages"]
            if passage.get("referenceLineageId") == "reference-a"
        ]
        self.assertGreater(len(focused_a), len(broad_a))
        self.assertEqual(len(broad_a), 1)

    def test_core_renders_appsync_awsjson_metadata_strings(self):
        services = KnowledgeQueryServices(graph=FakeGraphProvider(), semantic=FakeSemanticProvider())
        original_expand = services.graph.expand_anchor

        def expand_with_awsjson_metadata(anchor, scope):
            expansion = original_expand(anchor, scope)
            expansion["relations"][0]["metadata"] = json.dumps(expansion["relations"][0]["metadata"])
            return expansion

        services.graph.expand_anchor = expand_with_awsjson_metadata
        result = run_knowledge_query(
            {
                "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                "scope": {"relationTypes": ["comment"]},
                "output": {"format": "markdown", "maxTokens": 140},
            },
            services,
        )

        self.assertIn("Operational curation note should be excluded by default.", result["context"]["text"])

    def test_lambda_handler_parses_appsync_awsjson_input(self):
        event = {
            "arguments": {
                "input": json.dumps(
                    {
                        "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
                        "output": {"format": "markdown", "maxTokens": 100},
                    }
                )
            }
        }
        with mock.patch("papyrus_knowledge_query.lambda_handler.build_environment_services", return_value=fake_services()):
            result = lambda_handler(event, None)

        self.assertIn("context", result)
        self.assertIn("Scaling Agents", result["context"]["text"])

    def test_newsroom_cli_delegates_to_same_engine(self):
        from papyrus_newsroom import cli as newsroom_cli

        payload = {
            "anchors": [{"kind": "category", "id": "category-scaling-v1", "lineageId": "category-scaling"}],
            "semanticQuery": "agent memory systems",
            "output": {"format": "both", "maxTokens": 120},
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(payload, handle)
            handle.flush()
            stdout = io.StringIO()
            with mock.patch("papyrus_knowledge_query.cli.build_environment_services", return_value=fake_services()), \
                 contextlib.redirect_stdout(stdout):
                exit_code = newsroom_cli.main(["knowledge-query", "--input", handle.name, "--execution", "local"])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        direct = run_knowledge_query(payload, fake_services())
        self.assertEqual(result["structured"], direct["structured"])
        self.assertEqual(result["context"]["text"], direct["context"]["text"])

    def test_newsroom_cli_remote_executes_appsync_knowledge_query(self):
        from papyrus_newsroom import cli as newsroom_cli

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "data": {
                            "knowledgeQuery": json.dumps(
                                {
                                    "structured": {},
                                    "context": {"text": "remote context"},
                                    "warnings": [],
                                    "provenance": {},
                                    "debug": {},
                                }
                            )
                        }
                    }
                ).encode("utf-8")

        stdout = io.StringIO()
        captured = {}

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.headers.get("Authorization")
            return FakeResponse()

        with mock.patch.dict(
            os.environ,
            {
                "PAPYRUS_GRAPHQL_ENDPOINT": "https://example.appsync-api.us-east-1.amazonaws.com/graphql",
                "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "secret-example",
                "AWS_SESSION_TOKEN": "session-example",
            },
            clear=False,
        ), mock.patch("papyrus_knowledge_query.cli.urllib.request.urlopen", side_effect=fake_urlopen), \
             contextlib.redirect_stdout(stdout):
            exit_code = newsroom_cli.main(["knowledge-query", "--query", "LLM", "--format", "both", "--max-tokens", "1200"])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["context"]["text"], "remote context")
        self.assertEqual(result["debug"]["cliExecution"], "remote")
        self.assertTrue(captured["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/"))
        self.assertIn("/us-east-1/appsync/aws4_request", captured["authorization"])
        self.assertEqual(captured["body"]["variables"]["input"], '{"anchors":[],"semanticQuery":"LLM","scope":{},"profile":"researcher","output":{"format":"both","maxTokens":1200}}')

    def test_newsroom_cli_remote_requires_graphql_auth(self):
        from papyrus_newsroom import cli as newsroom_cli

        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_ENDPOINT": ""}, clear=False):
            with self.assertRaises(RuntimeError):
                newsroom_cli.main(["knowledge-query", "--query", "LLM"])

    def test_semantic_relation_seed_includes_insight_about(self):
        relation_types = (REPO_ROOT / "corpora" / "papyrus-semantic-relation-types.yml").read_text(encoding="utf-8")
        self.assertIn("- key: insight_about", relation_types)
        self.assertRegex(relation_types, r"key: insight_about[\s\S]*allowedObjectKinds: \[reference, item, category, semanticNode, assignment, newsroomSection\]")
        self.assertIn("domain: knowledge", relation_types)

    def test_vector_index_audit_reports_missing_references(self):
        services = KnowledgeQueryServices(graph=FakeVectorIndexGraphProvider(), corpus_text=FakeVectorIndexTextProvider())
        existing = [
            {
                "key": "reference-summary-existing",
                "metadata": {
                    "kind": "reference",
                    "referenceLineageId": "reference-1",
                    "vectorKind": "reference_summary",
                },
            }
        ]
        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:test:index"}), \
             mock.patch("papyrus_knowledge_query.vector_index._list_index_vectors", return_value=existing):
            result = index_reference_passages(services, VectorIndexOptions(action="audit"))

        self.assertEqual(result["acceptedReferences"], 2)
        self.assertEqual(result["existingVectors"], 1)
        self.assertEqual(result["existingIndexedReferences"], 1)
        self.assertEqual(result["missingIndexedReferences"], 1)
        self.assertEqual(result["missingIndexedReferenceSample"], ["reference-2"])
        self.assertEqual(result["eligibleInsightMessages"], 1)
        self.assertEqual(result["insightMessagesMissingBody"], 0)
        self.assertEqual(result["missingIndexedInsightMessages"], 1)
        self.assertEqual(result["missingIndexedInsightMessageSample"], ["message-insight-1"])

    def test_vector_index_skips_insight_without_message_body(self):
        services = KnowledgeQueryServices(graph=FakeVectorIndexGraphProviderWithoutMessageBody(), corpus_text=FakeVectorIndexTextProvider())
        written_batches = []

        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:test:index"}), \
             mock.patch("papyrus_knowledge_query.vector_index._list_index_vectors", return_value=[]), \
             mock.patch("papyrus_knowledge_query.vector_index._embed", return_value=[[0.1, 0.2, 0.3]] * 6), \
             mock.patch("papyrus_knowledge_query.vector_index._put_vectors", side_effect=lambda index_arn, vectors: written_batches.append(vectors)):
            result = index_reference_passages(
                services,
                VectorIndexOptions(action="sync", max_chunks_per_reference=2, progress_every=0),
            )

        written = [vector for batch in written_batches for vector in batch]
        self.assertEqual(result["eligibleInsightMessages"], 0)
        self.assertEqual(result["insightMessagesMissingBody"], 1)
        self.assertFalse(any(vector["metadata"]["vectorKind"].startswith("insight_") for vector in written))
        insight_result = next(entry for entry in result["insightResults"] if entry["messageId"] == "message-insight-1")
        self.assertEqual(insight_result["status"], "missing_message_body")

    def test_vector_index_sync_writes_source_and_passage_vectors_once(self):
        services = KnowledgeQueryServices(graph=FakeVectorIndexGraphProvider(), corpus_text=FakeVectorIndexTextProvider())
        written_batches = []
        embedded_texts = []

        def fake_embed(texts):
            embedded_texts.extend(texts)
            return [[0.1, 0.2, 0.3] for _ in texts]

        def fake_put(index_arn, vectors):
            written_batches.append(vectors)

        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:test:index"}), \
             mock.patch("papyrus_knowledge_query.vector_index._list_index_vectors", return_value=[]), \
             mock.patch("papyrus_knowledge_query.vector_index._embed", side_effect=fake_embed), \
             mock.patch("papyrus_knowledge_query.vector_index._put_vectors", side_effect=fake_put):
            result = index_reference_passages(
                services,
                VectorIndexOptions(
                    action="sync",
                    max_chunks_per_reference=2,
                    batch_size=3,
                    progress_every=0,
                ),
            )

        written = [vector for batch in written_batches for vector in batch]
        self.assertEqual(result["acceptedReferences"], 2)
        self.assertEqual(result["eligibleInsightMessages"], 1)
        self.assertEqual(result["sourceVectorsPrepared"], 2)
        self.assertEqual(result["passageVectorsPrepared"], 4)
        self.assertEqual(result["insightSourceVectorsPrepared"], 1)
        self.assertEqual(result["insightPassageVectorsPrepared"], 1)
        self.assertEqual(result["vectorsWritten"], 8)
        self.assertEqual(
            {vector["metadata"]["vectorKind"] for vector in written},
            {"reference_summary", "reference_passage", "insight_source", "insight_passage"},
        )
        self.assertTrue(
            all(
                vector["metadata"]["referenceLineageId"] in {"reference-1", "reference-2"}
                for vector in written
                if vector["metadata"]["kind"] == "reference"
            )
        )
        self.assertTrue(
            all("subtitle" in vector["metadata"] for vector in written if vector["metadata"]["kind"] == "reference")
        )
        source_vector = next(vector for vector in written if vector["metadata"]["referenceLineageId"] == "reference-1" and vector["metadata"]["vectorKind"] == "reference_summary")
        self.assertIn("Operational measurement and regression discipline", source_vector["metadata"]["text"])
        self.assertIn("referenceSummary", source_vector["metadata"])
        self.assertIn("Long summary: production readiness", source_vector["metadata"]["referenceSummary"])
        self.assertIn("Long summary: production readiness", source_vector["metadata"]["text"])
        insight_vector = next(vector for vector in written if vector["metadata"]["vectorKind"] == "insight_source")
        self.assertEqual(insight_vector["metadata"]["messageKind"], "insight")
        self.assertEqual(insight_vector["metadata"]["relationTypeKey"], "insight_about")
        self.assertIn("Insight summary: reliability work", insight_vector["metadata"]["summary"])
        self.assertIn("Insight body: teams should inspect reliability evidence", insight_vector["metadata"]["text"])
        self.assertNotIn("Insight summary: reliability work", insight_vector["metadata"]["text"])
        self.assertTrue(any("Insight body: teams should inspect reliability evidence" in text for text in embedded_texts))
        self.assertFalse(any("Insight summary: reliability work" in text for text in embedded_texts))
        insight_passage = next(vector for vector in written if vector["metadata"]["vectorKind"] == "insight_passage")
        self.assertIn("Insight body: teams should inspect reliability evidence", insight_passage["metadata"]["text"])

    def test_vector_index_sync_skips_existing_keys(self):
        services = KnowledgeQueryServices(graph=FakeVectorIndexGraphProvider(), corpus_text=FakeVectorIndexTextProvider())
        written_batches = []
        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:test:index"}), \
             mock.patch("papyrus_knowledge_query.vector_index._list_index_vectors", return_value=[]), \
             mock.patch("papyrus_knowledge_query.vector_index._embed", return_value=[[0.1, 0.2, 0.3]] * 8), \
             mock.patch("papyrus_knowledge_query.vector_index._put_vectors", side_effect=lambda index_arn, vectors: written_batches.append(vectors)):
            first = index_reference_passages(
                services,
                VectorIndexOptions(action="sync", max_chunks_per_reference=2, progress_every=0),
            )
        existing = [{"key": vector["key"], "metadata": vector["metadata"]} for batch in written_batches for vector in batch]
        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:test:index"}), \
             mock.patch("papyrus_knowledge_query.vector_index._list_index_vectors", return_value=existing), \
             mock.patch("papyrus_knowledge_query.vector_index._embed") as embed_mock, \
             mock.patch("papyrus_knowledge_query.vector_index._put_vectors") as put_mock:
            second = index_reference_passages(
                services,
                VectorIndexOptions(action="sync", max_chunks_per_reference=2, progress_every=0),
            )

        self.assertEqual(first["vectorsWritten"], 8)
        self.assertEqual(second["vectorsSkippedExisting"], 8)
        self.assertEqual(second["vectorsWritten"], 0)
        embed_mock.assert_not_called()
        put_mock.assert_not_called()

    def test_vector_index_uses_summary_when_extracted_text_is_short(self):
        services = KnowledgeQueryServices(
            graph=FakeVectorIndexGraphProvider(),
            corpus_text=ShortFakeVectorIndexTextProvider(),
        )
        written_batches = []
        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:test:index"}), \
             mock.patch("papyrus_knowledge_query.vector_index._list_index_vectors", return_value=[]), \
             mock.patch("papyrus_knowledge_query.vector_index._embed", return_value=[[0.1, 0.2, 0.3]] * 2), \
             mock.patch("papyrus_knowledge_query.vector_index._put_vectors", side_effect=lambda index_arn, vectors: written_batches.append(vectors)):
            result = index_reference_passages(
                services,
                VectorIndexOptions(action="sync", max_chunks_per_reference=0, progress_every=0),
            )

        written = [vector for batch in written_batches for vector in batch]
        source_vector = next(
            vector
            for vector in written
            if vector["metadata"]["referenceLineageId"] == "reference-1" and vector["metadata"]["vectorKind"] == "reference_summary"
        )
        self.assertEqual(result["sourceVectorsPrepared"], 2)
        self.assertIn("Long summary: production readiness", source_vector["metadata"]["text"])
        self.assertLessEqual(len(source_vector["metadata"]["text"]), 480)
        self.assertLessEqual(len(source_vector["metadata"]["summary"]), 320)
        self.assertLessEqual(len(source_vector["metadata"]["referenceSummary"]), 320)

    def test_sanitize_vector_metadata_drops_none_and_stringifies_objects(self):
        sanitized = _sanitize_vector_metadata(
            {
                "title": "ReAct",
                "referenceSummaryMaxTokens": None,
                "referenceSummaryMessageId": None,
                "chunkIndex": 2,
                "ready": True,
                "tags": ["agent", None, "loop"],
                "nested": {"corpusId": "knowledge-corpus-ai-ml-research"},
            }
        )
        self.assertEqual(sanitized["title"], "ReAct")
        self.assertNotIn("referenceSummaryMaxTokens", sanitized)
        self.assertNotIn("referenceSummaryMessageId", sanitized)
        self.assertEqual(sanitized["chunkIndex"], 2)
        self.assertTrue(sanitized["ready"])
        self.assertEqual(sanitized["tags"], ["agent", "loop"])
        self.assertEqual(sanitized["nested"], "{'corpusId': 'knowledge-corpus-ai-ml-research'}")


if __name__ == "__main__":
    unittest.main()
