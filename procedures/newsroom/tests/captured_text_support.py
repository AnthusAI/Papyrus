"""In-memory world for knowledge queries over captured Reference text (pytest and behave share it): no AWS, no network, no model.

The graph answers the three requests the evidence stage makes: the Reference's attachments by lineage (the curation card, any extracted_text), the
owner index of ModelAttachments (``listModelAttachmentsByOwnerRoleAndSortKey``) and the caller-authorized download of one attachment. It records every
request so tests can show the engine never reads a table and never builds an attachment id.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from papyrus_knowledge_query.services import KnowledgeQueryServices  # noqa: E402

# A real Reference id is `reference-<corpus>-<external id>-v1`: well past the 80 characters where the deployed writer starts adding a digest.
LONG_ID = "reference-knowledge-corpus-machines-on-machines-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef-v1"
LINEAGE = LONG_ID[:-3]
SENTINEL = "Oversight of capable agents depends on verifying their actions with independent audit logs and human review of high-risk steps."


class SemanticStub:
    name = "stub-semantic"

    def search(self, query, scope, limit):
        return []


class CorporaOnlyText:
    """The knowledge-query function's own storage role: it reads `corpora/` keys and is refused anything else."""
    name = "corpora-only"

    def __init__(self, files=None):
        self.files, self.reads = files or {}, []

    def read_text(self, storage_path):
        self.reads.append(storage_path)
        if not storage_path.startswith("corpora/"):
            raise PermissionError(f"AccessDenied for {storage_path}")
        return self.files.get(storage_path)


class CapturedTextGraph:
    name = "captured-text-graph"

    def __init__(self, *, reference_id=LONG_ID, lineage=LINEAGE, status="accepted"):
        self.reference = {"kind": "reference", "id": reference_id, "lineageId": lineage, "title": "Overseeing AI Agents", "authors": ["Ada Reporter"],
                          "sourceUri": "https://example.com/oversight", "curationStatus": status, "corpusId": "c"}
        self.reference_attachments: list[dict] = []
        self.model_attachments: list[dict] = []
        self.bodies: dict[str, str] = {}
        self.requests: list[tuple[str, dict]] = []
        self.denied_downloads: set[str] = set()
        self.owner_index_error: str | None = None

    # -- the world ---------------------------------------------------------------------------------------------------------------------------
    def card(self, *, text_sort_key, edits=(), labels=(), capture=None):
        card = {"kind": "reference-curation", "schemaVersion": 1, "status": "ready", "current": {"textSortKey": text_sort_key},
                "capture": capture or {"status": "completed", "capturedAt": "2026-11-01T10:00:00Z", "via": "direct"},
                "edits": list(edits), "labels": list(labels)}
        self.reference_attachments.append({"id": "card", "referenceId": self.reference["id"], "referenceLineageId": self.reference["lineageId"],
                                           "role": "curation", "sortKey": "003-curation", "metadata": json.dumps(card)})
        return card

    def extracted(self, text, path="corpora/c/extracted/ref.txt"):
        self.reference_attachments.append({"id": "extracted", "referenceId": self.reference["id"], "referenceLineageId": self.reference["lineageId"],
                                           "role": "extracted_text", "sortKey": "900-extracted-text", "storagePath": path})
        return path

    def body(self, sort_key, text, *, status="active", owner=None, updated="2026-11-02T00:00:00Z"):
        # The id is whatever the deployed writer made; the engine must not guess it, so these deliberately do not follow the client's formula.
        attachment_id = f"model-attachment-writer-made-{len(self.model_attachments)}"
        path = f"newsroom/payloads/reference/x/metadata/{sort_key}.md"
        self.model_attachments.append({"id": attachment_id, "ownerKind": "reference", "ownerId": owner or self.reference["id"], "role": "metadata",
                                       "sortKey": sort_key, "storagePath": path, "status": status, "updatedAt": updated, "createdAt": updated})
        self.bodies[attachment_id] = text
        return attachment_id

    # -- the provider ------------------------------------------------------------------------------------------------------------------------
    def resolve_anchor(self, anchor):
        return dict(self.reference) if anchor.get("kind") == "reference" else None

    def expand_anchor(self, anchor, scope):
        return {"objects": [dict(self.reference)], "relations": [], "excludedRelations": [], "warnings": []}

    def list_reference_attachments(self, reference):
        self.requests.append(("list_reference_attachments", {"lineageId": reference.get("lineageId")}))
        return [dict(item) for item in self.reference_attachments]

    def list_outgoing_relations(self, obj):
        return []

    def list_incoming_relations(self, obj):
        return []

    def graphql(self, query, variables):
        assert "listModelAttachmentsByOwnerRoleAndSortKey" in query, query
        self.requests.append(("owner_index", dict(variables)))
        if self.owner_index_error:
            raise RuntimeError(self.owner_index_error)
        assert variables.get("ownerId"), "the owner index is always asked for one owner, never a table"
        rows = [dict(row) for row in self.model_attachments if row["ownerId"] == variables["ownerId"]]
        return {"listModelAttachmentsByOwnerRoleAndSortKey": {"items": rows, "nextToken": None}}

    def read_model_attachment_text(self, attachment):
        self.requests.append(("download", {"attachmentId": attachment["id"]}))
        if attachment["id"] in self.denied_downloads:
            raise RuntimeError("GraphQL request failed: Not Authorized to access createModelAttachmentDownload on type Mutation")
        return self.bodies.get(attachment["id"])


def query(graph, *, corpus_text=None, text="how can humans oversee capable AI agents and verify their actions", max_tokens=600):
    from papyrus_knowledge_query.engine import run_knowledge_query

    services = KnowledgeQueryServices(graph=graph, semantic=SemanticStub(), corpus_text=corpus_text or CorporaOnlyText())
    return run_knowledge_query({
        "semanticQuery": text, "anchors": [{"kind": "reference", "id": graph.reference["id"], "lineageId": graph.reference["lineageId"]}],
        "scope": {"depth": 1, "topK": 10}, "profile": "researcher", "output": {"format": "both", "maxTokens": max_tokens}}, services)


def edit(n, sort_key, *, by="agent:researcher", note="Captured by an AI agent; not independently completeness-checked.", at="2026-11-06T18:00:00Z"):
    return {"n": n, "kind": "text", "sortKey": sort_key, "editedBy": by, "editedAt": at, "provenance": "edited by editor", "note": note}
