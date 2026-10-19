"""
Private Papyrus semantic graph access helpers.

The module is intentionally thin over the AppSync data model. It builds the
same state keys used by SemanticRelation indexes and leaves traversal policy to
callers.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from papyrus_knowledge_query.uris import parse_papyrus_uri

SEMANTIC_OBJECT_KINDS = {
    "reference",
    "item",
    "category",
    "categorySet",
    "semanticNode",
    "semanticRelation",
    "message",
    "steeringProposal",
    "steeringDecision",
    "knowledgeArtifact",
    "knowledgeImportRun",
}

SEMANTIC_PREDICATES: dict[str, dict[str, str]] = {
    "classified_as": {"label": "classified as", "group": "classification", "inverse_label": "classified references/items"},
    "quality_rating_is": {"label": "quality rating is", "group": "curation", "inverse_label": "quality rating for"},
    "reference_summary_100_tokens": {"label": "100-token reference summary", "group": "summarization", "inverse_label": "100-token summary for"},
    "reference_summary_200_tokens": {"label": "200-token reference summary", "group": "summarization", "inverse_label": "200-token summary for"},
    "reference_summary_500_tokens": {"label": "500-token reference summary", "group": "summarization", "inverse_label": "500-token summary for"},
    "reference_summary_1000_tokens": {"label": "1000-token reference summary", "group": "summarization", "inverse_label": "1000-token summary for"},
    "mentions": {"label": "mentions", "group": "ontology", "inverse_label": "mentioned by"},
    "about": {"label": "about", "group": "commentary", "inverse_label": "commentary"},
    "comment": {"label": "comments on", "group": "commentary", "inverse_label": "commented on by"},
    "ingestion_rationale": {"label": "ingestion rationale for", "group": "commentary", "inverse_label": "ingestion rationale"},
    "uses_evidence": {"label": "uses evidence", "group": "evidence", "inverse_label": "used by"},
    "uses_signal": {"label": "uses signal", "group": "evidence", "inverse_label": "signal for"},
    "requests_work_on": {"label": "requests work on", "group": "workflow", "inverse_label": "requested work"},
    "planned_for_edition": {"label": "planned for edition", "group": "publication", "inverse_label": "planned assignments"},
    "targets_lane": {"label": "targets lane", "group": "editorial", "inverse_label": "lane targets"},
    "targets_section": {"label": "targets section", "group": "editorial", "inverse_label": "section assignments"},
    "targets_topic": {"label": "targets topic", "group": "editorial", "inverse_label": "topic assignments"},
    "scoped_to_topic": {"label": "scoped to topic", "group": "ontology", "inverse_label": "semantic concepts scoped here"},
    "produces": {"label": "produces", "group": "workflow", "inverse_label": "produced by"},
    "derived_from": {"label": "derived from", "group": "evidence", "inverse_label": "source for"},
    "related_to": {"label": "related to", "group": "generic", "inverse_label": "related from"},
    "broader_than": {"label": "broader than", "group": "ontology", "inverse_label": "narrower concept"},
    "narrower_than": {"label": "narrower than", "group": "ontology", "inverse_label": "broader concept"},
    "supports": {"label": "supports", "group": "evidence", "inverse_label": "supported by"},
    "contradicts": {"label": "contradicts", "group": "evidence", "inverse_label": "contradicted by"},
}


REFERENCE_FIELDS = """
id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt
    retrievedAt importRunId importedAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason updatedAt
"""

ATTACHMENT_FIELDS = """
id referenceId referenceLineageId referenceVersionNumber referenceVersionKey role sortKey storagePath sourceUri filename
mediaType byteSize sha256 etag importRunId importedAt metadata
"""

MESSAGE_FIELDS = """
id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel
content metadata createdAt updatedAt
"""

RELATION_FIELDS = """
id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId subjectLineageId subjectVersionNumber objectKind objectId objectLineageId
objectVersionNumber subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey subjectVersionKey objectVersionKey
score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId importRunId importedAt metadata
"""

OBJECT_FIELD_MAP = {
    "assignment": """
getAssignment(id: $id) {
  id assignmentTypeKey queueKey queueStatusKey status title summary sectionKey sectionStatusKey categorySetId priority
  assigneeKey createdAt updatedAt
}
""",
    "categorySet": """
getCategorySet(id: $id) {
  id lineageId versionNumber versionState corpusId classifierId displayName description status generatedAt categoryCount importRunId
}
""",
    "reference": f"getReference(id: $id) {{ {REFERENCE_FIELDS} }}",
    "semanticNode": """
getSemanticNode(id: $id) {
  id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
  nodeKey nodeKind corpusId categorySetId categoryLineageId categoryKey displayName description aliases authorityScore authorityRank
  acceptedReferenceMentionCount distinctSourceKindCount relationCount status importRunId updatedAt
}
""",
    "category": """
getCategory(id: $id) {
  id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
  categorySetId corpusId categoryKey parentCategoryId parentCategoryKey displayName subtitle description aliases status
  seedItemIds holdoutItemIds rank depth isPinned importRunId updatedAt
}
""",
    "item": """
getItem(id: $id) {
  id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
  type status typeStatus slug shortSlug section sectionStatus title headline deck byline dateline publishedAt editionDate sortTitle layout editorial updatedAt
}
""",
    "message": f"getMessage(id: $id) {{ {MESSAGE_FIELDS} }}",
    "semanticRelation": f"getSemanticRelation(id: $id) {{ {RELATION_FIELDS} }}",
    "steeringProposal": """
getSteeringProposal(id: $id) {
  id categorySetId corpusId importRunId proposalKind steeringDomain status title summary categoryKey targetCategoryKey
  graphEntityId relationshipType displayName description sourceSnapshotId proposedAt reviewedAt updatedAt
}
""",
}

LINEAGE_OBJECT_FIELD_MAP = {
    "category": (
        "listCategoriesByLineageAndVersion",
        """
  id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
  categorySetId corpusId categoryKey parentCategoryId parentCategoryKey displayName subtitle description aliases status
  seedItemIds holdoutItemIds rank depth isPinned importRunId updatedAt
""",
    ),
    "categorySet": (
        "listCategorySetsByLineageAndVersion",
        """
  id lineageId versionNumber versionState corpusId classifierId displayName description status generatedAt categoryCount importRunId
""",
    ),
    "item": (
        "listItemsByLineageAndVersion",
        """
  id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
  type status typeStatus slug shortSlug section sectionStatus title headline deck byline dateline publishedAt editionDate sortTitle layout editorial updatedAt
""",
    ),
    "reference": ("listReferencesByLineageAndVersion", REFERENCE_FIELDS),
    "semanticNode": (
        "listSemanticNodesByLineageAndVersion",
        """
  id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
  nodeKey nodeKind corpusId categorySetId categoryLineageId categoryKey displayName description aliases status importRunId updatedAt
""",
    ),
}


GET_REFERENCE_QUERY = f"""
query GetReference($id: ID!) {{
  getReference(id: $id) {{ {REFERENCE_FIELDS} }}
}}
"""

FIND_REFERENCE_QUERY = f"""
query FindReference($corpusId: ID!, $externalItemId: String!, $limit: Int, $nextToken: String) {{
  listReferencesByCorpusAndExternalItem(corpusId: $corpusId, externalItemId: {{ eq: $externalItemId }}, limit: $limit, nextToken: $nextToken) {{
    items {{ {REFERENCE_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_ATTACHMENTS_BY_VERSION_QUERY = f"""
query ListReferenceAttachmentsByVersion($referenceVersionKey: String!, $limit: Int, $nextToken: String) {{
  listReferenceAttachmentsByReferenceVersionAndSortKey(referenceVersionKey: $referenceVersionKey, limit: $limit, nextToken: $nextToken) {{
    items {{ {ATTACHMENT_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_ATTACHMENTS_BY_LINEAGE_QUERY = f"""
query ListReferenceAttachmentsByLineage($referenceLineageId: ID!, $limit: Int, $nextToken: String) {{
  listReferenceAttachmentsByReferenceLineageAndSortKey(referenceLineageId: $referenceLineageId, limit: $limit, nextToken: $nextToken) {{
    items {{ {ATTACHMENT_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_RELATIONS_BY_SUBJECT_QUERY = f"""
query ListRelationsBySubject($subjectStateKey: String!, $limit: Int, $nextToken: String) {{
  listSemanticRelationsBySubjectState(subjectStateKey: $subjectStateKey, limit: $limit, nextToken: $nextToken) {{
    items {{ {RELATION_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_RELATIONS_BY_OBJECT_QUERY = f"""
query ListRelationsByObject($objectStateKey: String!, $limit: Int, $nextToken: String) {{
  listSemanticRelationsByObjectState(objectStateKey: $objectStateKey, limit: $limit, nextToken: $nextToken) {{
    items {{ {RELATION_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_RELATIONS_BY_OBJECT_SUBJECT_QUERY = f"""
query ListRelationsByObjectSubject($objectSubjectStateKey: String!, $limit: Int, $nextToken: String) {{
  listSemanticRelationsByObjectSubjectStateAndScore(objectSubjectStateKey: $objectSubjectStateKey, limit: $limit, nextToken: $nextToken, sortDirection: DESC) {{
    items {{ {RELATION_FIELDS} }}
    nextToken
  }}
}}
"""


def semantic_state_key(kind: str, lineage_id: str, state: str = "current") -> str:
    return f"{kind}#{lineage_id}#{state}"


def semantic_version_key(kind: str, version_id: str) -> str:
    return f"{kind}#{version_id}"


def semantic_object_subject_state_key(object_kind: str, object_lineage_id: str, subject_kind: str, state: str = "current") -> str:
    return f"{object_kind}#{object_lineage_id}#{state}#{subject_kind}"


def semantic_predicate_object_state_key(predicate: str, object_kind: str, object_lineage_id: str, state: str = "current") -> str:
    return f"{predicate}#{object_kind}#{object_lineage_id}#{state}"


@dataclass
class PapyrusSemanticClient:
    graphql: Callable[[str, dict[str, Any]], dict[str, Any]]
    decode_record: Callable[[dict[str, Any]], dict[str, Any]] = lambda record: record
    page_limit: int = 100

    def get_reference(self, reference_id: str) -> dict[str, Any]:
        reference_key = _required(reference_id, "reference_id")
        data = self.graphql(GET_REFERENCE_QUERY, {"id": reference_key})
        reference = data.get("getReference")
        if not reference:
            reference = self._resolve_current_by_lineage("reference", reference_key)
        if not reference:
            raise ValueError(f"Reference not found: {reference_id}")
        return {"reference": self.decode_record(reference)}

    def find_reference(self, corpus_id: str, external_item_id: str) -> dict[str, Any]:
        references = self._list_connection(
            FIND_REFERENCE_QUERY,
            {"corpusId": _required(corpus_id, "corpus_id"), "externalItemId": _required(external_item_id, "external_item_id")},
            "listReferencesByCorpusAndExternalItem",
        )
        return {"references": references, "reference": references[0] if references else None}

    def list_reference_attachments(
        self,
        reference_lineage_id: str | None = None,
        reference_version_key: str | None = None,
    ) -> dict[str, Any]:
        if reference_version_key:
            attachments = self._list_connection(
                LIST_ATTACHMENTS_BY_VERSION_QUERY,
                {"referenceVersionKey": reference_version_key},
                "listReferenceAttachmentsByReferenceVersionAndSortKey",
            )
        else:
            attachments = self._list_connection(
                LIST_ATTACHMENTS_BY_LINEAGE_QUERY,
                {"referenceLineageId": _required(reference_lineage_id, "reference_lineage_id")},
                "listReferenceAttachmentsByReferenceLineageAndSortKey",
            )
        return {"attachments": attachments}

    def list_reference_messages(self, reference_lineage_id: str) -> dict[str, Any]:
        messages = self.list_messages("reference", reference_lineage_id)["messages"]
        return {"messages": messages}

    def list_reference_summaries(self, reference_lineage_id: str, max_tokens: int | None = None) -> dict[str, Any]:
        relations = self.list_incoming("reference", reference_lineage_id)["relations"]
        allowed = {f"reference_summary_{max_tokens}_tokens"} if max_tokens else {
            "reference_summary_100_tokens",
            "reference_summary_200_tokens",
            "reference_summary_500_tokens",
            "reference_summary_1000_tokens",
        }
        summaries: list[dict[str, Any]] = []
        for relation in relations:
            relation_type = relation.get("relationTypeKey") or relation.get("predicate")
            if relation.get("subjectKind") != "message" or relation_type not in allowed:
                continue
            try:
                message = self.get_semantic_object("message", relation["subjectId"])["object"]
            except ValueError:
                continue
            summaries.append({"message": message, "relation": relation, "maxTokens": _summary_tokens_from_relation_type(relation_type)})
        summaries.sort(key=lambda entry: entry["message"].get("createdAt") or "", reverse=True)
        return {"summaries": summaries}

    def list_messages(self, object_kind: str, object_lineage_id: str) -> dict[str, Any]:
        relations = self.list_incoming(object_kind, object_lineage_id)["relations"]
        if object_kind == "assignment":
            relations.extend(self.list_outgoing(object_kind, object_lineage_id)["relations"])
        messages: list[dict[str, Any]] = []
        for relation in relations:
            relation_type = relation.get("relationTypeKey") or relation.get("predicate")
            if relation_type in {"comment", "note_about"}:
                if relation.get("subjectKind") != "message":
                    continue
                message_id = relation["subjectId"]
            elif relation_type == "produces" and relation.get("objectKind") == "message":
                message_id = relation["objectId"]
            else:
                continue
            try:
                messages.append(self.get_semantic_object("message", message_id)["object"])
            except ValueError:
                continue
        messages.sort(key=lambda message: message.get("createdAt") or "", reverse=True)
        return {"messages": messages}

    def get_semantic_object(self, kind: str, object_id: str) -> dict[str, Any]:
        kind = _required(kind, "kind")
        if kind not in OBJECT_FIELD_MAP:
            raise ValueError(f"Unsupported semantic object kind: {kind}")
        query = f"query GetSemanticObject($id: ID!) {{ {OBJECT_FIELD_MAP[kind]} }}"
        object_id = _required(object_id, "object_id")
        data = self.graphql(query, {"id": object_id})
        field_name = next(key for key in data if key.startswith("get"))
        record = data.get(field_name)
        if not record and kind in LINEAGE_OBJECT_FIELD_MAP:
            record = self._resolve_current_by_lineage(kind, object_id)
        if not record:
            raise ValueError(f"{kind} not found: {object_id}")
        return {"kind": kind, "object": self.decode_record(record)}

    def resolve_uri(self, uri: str) -> dict[str, Any]:
        parsed = parse_papyrus_uri(uri)
        result = self.get_semantic_object(parsed["kind"], parsed["id"])
        obj = result["object"]
        return {
            "uri": parsed["objectUri"],
            "kind": parsed["kind"],
            "id": parsed["id"],
            "lineageId": obj.get("lineageId") or parsed["lineageId"],
            "object": obj,
        }

    def list_outgoing(self, subject_kind: str, subject_lineage_id: str) -> dict[str, Any]:
        relations = self._list_connection(
            LIST_RELATIONS_BY_SUBJECT_QUERY,
            {"subjectStateKey": semantic_state_key(_required(subject_kind, "subject_kind"), _required(subject_lineage_id, "subject_lineage_id"))},
            "listSemanticRelationsBySubjectState",
        )
        return {"relations": relations}

    def list_incoming(self, object_kind: str, object_lineage_id: str) -> dict[str, Any]:
        relations = self._list_connection(
            LIST_RELATIONS_BY_OBJECT_QUERY,
            {"objectStateKey": semantic_state_key(_required(object_kind, "object_kind"), _required(object_lineage_id, "object_lineage_id"))},
            "listSemanticRelationsByObjectState",
        )
        return {"relations": relations}

    def neighbors(self, kind: str, lineage_id: str, direction: str = "both") -> dict[str, Any]:
        direction = direction or "both"
        relations: list[dict[str, Any]] = []
        if direction in {"both", "outgoing"}:
            relations.extend(self.list_outgoing(kind, lineage_id)["relations"])
        if direction in {"both", "incoming"}:
            relations.extend(self.list_incoming(kind, lineage_id)["relations"])
        return {"relations": _dedupe_records(relations), "neighborRefs": relation_neighbor_refs(relations, kind, lineage_id)}

    def references_for_category(self, category_lineage_id: str) -> dict[str, Any]:
        return self._subjects_for_object("category", category_lineage_id, "reference", predicate="classified_as")

    def references_for_semantic_node(self, node_lineage_id: str, predicate: str | None = None) -> dict[str, Any]:
        return self._subjects_for_object("semanticNode", node_lineage_id, "reference", predicate=predicate)

    def items_using_reference(self, reference_lineage_id: str) -> dict[str, Any]:
        incoming = self.list_incoming("reference", reference_lineage_id)["relations"]
        relations = [relation for relation in incoming if relation.get("subjectKind") == "item"]
        return {"relations": relations, "itemRefs": relation_neighbor_refs(relations, "reference", reference_lineage_id)}

    def walk(
        self,
        start_kind: str,
        start_lineage_id: str,
        depth: int = 2,
        predicates: Iterable[str] | None = None,
        kinds: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        predicate_filter = set(predicates or [])
        kind_filter = set(kinds or [])
        seen_nodes = {(start_kind, start_lineage_id)}
        seen_edges: dict[str, dict[str, Any]] = {}
        queue = deque([(start_kind, start_lineage_id, 0)])
        warnings: list[str] = []

        while queue:
            kind, lineage_id, level = queue.popleft()
            if level >= max(0, depth):
                continue
            try:
                relations = self.neighbors(kind, lineage_id)["relations"]
            except Exception as exc:  # pragma: no cover - defensive runtime note
                warnings.append(f"Could not load neighbors for {kind}#{lineage_id}: {exc}")
                continue
            for relation in relations:
                if predicate_filter and relation.get("predicate") not in predicate_filter:
                    continue
                relation_id = relation.get("id") or f"{relation.get('subjectStateKey')}->{relation.get('objectStateKey')}"
                seen_edges[str(relation_id)] = relation
                neighbor = relation_other_side(relation, kind, lineage_id)
                if not neighbor:
                    continue
                if kind_filter and neighbor["kind"] not in kind_filter:
                    continue
                node_key = (neighbor["kind"], neighbor["lineageId"])
                if node_key in seen_nodes:
                    continue
                seen_nodes.add(node_key)
                queue.append((neighbor["kind"], neighbor["lineageId"], level + 1))

        return {
            "start": {"kind": start_kind, "lineageId": start_lineage_id},
            "nodes": [{"kind": kind, "lineageId": lineage_id} for kind, lineage_id in sorted(seen_nodes)],
            "edges": list(seen_edges.values()),
            "warnings": warnings,
        }

    def _subjects_for_object(self, object_kind: str, object_lineage_id: str, subject_kind: str, predicate: str | None = None) -> dict[str, Any]:
        relations = self._list_connection(
            LIST_RELATIONS_BY_OBJECT_SUBJECT_QUERY,
            {"objectSubjectStateKey": semantic_object_subject_state_key(object_kind, _required(object_lineage_id, "object_lineage_id"), subject_kind)},
            "listSemanticRelationsByObjectSubjectStateAndScore",
        )
        if predicate:
            relations = [relation for relation in relations if relation.get("predicate") == predicate]
        return {"relations": relations, "subjectRefs": [{"kind": relation.get("subjectKind"), "lineageId": relation.get("subjectLineageId"), "id": relation.get("subjectId")} for relation in relations]}

    def _resolve_current_by_lineage(self, kind: str, lineage_id: str) -> dict[str, Any] | None:
        field_name, fields = LINEAGE_OBJECT_FIELD_MAP[kind]
        query = f"""
query ResolveSemanticObjectByLineage($lineageId: ID!, $limit: Int, $nextToken: String) {{
  {field_name}(lineageId: $lineageId, limit: $limit, nextToken: $nextToken) {{
    items {{ {fields} }}
    nextToken
  }}
}}
"""
        records = self._list_connection(query, {"lineageId": _required(lineage_id, "lineage_id")}, field_name)
        return _select_current_version(records)

    def _list_connection(self, query: str, variables: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        next_token = None
        while True:
            data = self.graphql(query, {**variables, "limit": self.page_limit, "nextToken": next_token})
            connection = data.get(field_name) or {}
            records.extend(self.decode_record(item) for item in (connection.get("items") or []) if item)
            next_token = connection.get("nextToken")
            if not next_token:
                break
        return records


def relation_neighbor_refs(relations: list[dict[str, Any]], start_kind: str, start_lineage_id: str) -> list[dict[str, Any]]:
    refs = []
    seen = set()
    for relation in relations:
        ref = relation_other_side(relation, start_kind, start_lineage_id)
        if not ref:
            continue
        key = (ref["kind"], ref["lineageId"])
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return refs


def relation_other_side(relation: dict[str, Any], start_kind: str, start_lineage_id: str) -> dict[str, Any] | None:
    if relation.get("subjectKind") == start_kind and relation.get("subjectLineageId") == start_lineage_id:
        return {"kind": relation.get("objectKind"), "lineageId": relation.get("objectLineageId"), "id": relation.get("objectId")}
    if relation.get("objectKind") == start_kind and relation.get("objectLineageId") == start_lineage_id:
        return {"kind": relation.get("subjectKind"), "lineageId": relation.get("subjectLineageId"), "id": relation.get("subjectId")}
    return None


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = {}
    for record in records:
        key = record.get("id") or (record.get("subjectStateKey"), record.get("predicateObjectStateKey"))
        deduped[key] = record
    return list(deduped.values())


def _select_current_version(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    current = [record for record in records if record.get("versionState") == "current"]
    candidates = current or records
    return sorted(candidates, key=lambda record: int(record.get("versionNumber") or 0), reverse=True)[0]


def _required(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _summary_tokens_from_relation_type(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"reference_summary_([0-9]+)_tokens", value)
    return int(match.group(1)) if match else None
