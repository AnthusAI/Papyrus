from __future__ import annotations

import json
import http.client
import os
import urllib.parse
from typing import Any

from .env import graphql_endpoint, graphql_jwt, graphql_timeout_seconds
from .graphql_http import graphql_request_headers, graphql_use_iam, running_in_aws_lambda

VERSION_FIELDS = (
    "lineageId versionNumber previousVersionId versionState versionCreatedAt "
    "versionCreatedBy changeReason contentHash"
)
CATEGORY_SET_FIELDS = (
    f"{VERSION_FIELDS} id corpusId classifierId displayName description status generatedAt "
    "categoryCount importRunId"
)
CATEGORY_FIELDS = (
    f"{VERSION_FIELDS} id categorySetId corpusId categoryKey parentCategoryId parentCategoryKey "
    "displayName shortTitle subtitle description aliases status seedItemIds holdoutItemIds rank depth "
    "isPinned importRunId updatedAt"
)
CATEGORY_KEYWORD_FIELDS = (
    "id categorySetId corpusId categoryKey categoryLineageId categoryId keyword normalizedKeyword weight rank "
    "source sourceTopicId importRunId metadata createdAt updatedAt"
)
PROPOSAL_FIELDS = (
    "id categorySetId corpusId importRunId proposalKind steeringDomain status title summary categoryKey "
    "targetCategoryKey graphEntityId relationshipType displayName shortTitle subtitle description "
    "evidenceItemIds suggestedSeedItemIds suggestedHoldoutItemIds sourceSnapshotId proposedAt "
    "reviewedAt reviewedBy updatedAt"
)
DECISION_FIELDS = "id proposalId categorySetId action actorSub actorLabel note selectedCategoryKey createdAt"
SEMANTIC_RELATION_TYPE_FIELDS = (
    "id key label inverseLabel description domain status allowedSubjectKinds allowedObjectKinds "
    "isDirectional isSymmetric isTransitive contextPackTags createdAt updatedAt metadata"
)
KNOWLEDGE_CORPUS_FIELDS = "id name role itemCount generatedAt latestImportRunId createdAt updatedAt"
KNOWLEDGE_IMPORT_RUN_FIELDS = (
    "id corpusId importKind corpusImportKindKey classifierId sourceSnapshotId status generatedAt "
    "importedAt itemCount categoryCount proposalCount artifactCount referenceCount relationCount warningCount"
)
KNOWLEDGE_RAW_PAYLOAD_FIELDS = "id ownerType ownerId payloadKind importRunId createdAt updatedAt"
REFERENCE_FIELDS = (
    f"{VERSION_FIELDS} id corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 "
    "sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount "
    "importRunId importedAt createdAt curationStatus "
    "curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt"
)
REFERENCE_ATTACHMENT_FIELDS = (
    "id referenceId referenceLineageId referenceVersionNumber referenceVersionKey role sortKey storagePath "
    "sourceUri filename mediaType byteSize sha256 etag importRunId importedAt metadata"
)
ASSIGNMENT_FIELDS = (
    "id assignmentTypeKey queueKey queueStatusKey status priority title assigneeType assigneeId assigneeKey "
    "claimedAt claimExpiresAt completedAt canceledAt corpusId categorySetId classifierId sourceSnapshotId "
    "importRunId sectionId sectionKey sectionType sectionStatusKey sectionQueueStatusKey primaryFocusCategoryKey "
    "topicScopeCategoryKeys createdBy createdAt updatedAt summary newsroomFeedKey"
)
ASSIGNMENT_EVENT_FIELDS = (
    "id assignmentId assignmentTypeKey queueKey eventType fromStatus toStatus actorSub actorLabel note createdAt"
)
SEMANTIC_RELATION_FIELDS = (
    "id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId "
    "subjectLineageId subjectVersionNumber objectKind objectId objectLineageId objectVersionNumber "
    "subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey subjectVersionKey "
    "objectVersionKey score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId "
    "importRunId importedAt createdAt updatedAt newsroomFeedKey metadata"
)
MESSAGE_FIELDS = (
    "id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel "
    "threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget "
    "responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata newsroomFeedKey createdAt updatedAt"
)
MESSAGE_THREAD_FIELDS = (
    "id threadKind status title summary primaryAnchorKind primaryAnchorId primaryAnchorLineageId primaryAnchorKey "
    "createdBySub createdByUserProfileId createdByLabel messageCount lastMessageId lastMessageAt contextDigest "
    "activeResponseMessageId responseLockOwner responseLockExpiresAt metadata createdAt updatedAt newsroomFeedKey"
)
PROCEDURE_DEFINITION_FIELDS = (
    "id procedureKey title category description enabled enabledStatus currentVersionId createdBy createdAt "
    "updatedBy updatedAt newsroomFeedKey"
)
PROCEDURE_VERSION_FIELDS = (
    "id procedureId procedureKey versionNumber status isCurrent label tactusSource parameterSchema defaults "
    "changelog createdBy createdAt updatedBy updatedAt"
)
PROCEDURE_RUN_FIELDS = (
    "id procedureId procedureKey procedureVersionId procedureVersionNumber assignmentId runStatus requestedBy "
    "requestedAt startedAt finishedAt input normalizedInput resultSummary errorSummary output error attempt newsroomFeedKey"
)
USER_ROLE_ASSIGNMENT_FIELDS = (
    "id userProfileId userSub email role status grantedBy grantedAt revokedAt notes"
)
MODEL_ATTACHMENT_FIELDS = (
    "id ownerKind ownerId ownerLineageId ownerVersionNumber ownerVersionKey role sortKey storagePath filename "
    "mediaType byteSize sha256 etag importRunId createdAt updatedAt status"
)
NEWSROOM_SECTION_FIELDS = (
    "id title shortTitle type editorialMission editorialPolicy enabled enabledStatus sortOrder "
    "defaultArticleTypes defaultPageBudget assignmentGuidance killCriteria visualGuidance createdAt updatedAt"
)
EDITION_FIELDS = (
    f"{VERSION_FIELDS} id slug title status editionDate publishedAt description layoutPlan metadata"
)
PUBLISHED_EDITION_FIELDS = (
    "id sourceEditionId editionLineageId versionNumber slug title status editionDate publishedAt description layoutPlan metadata"
)
EDITION_ITEM_FIELDS = (
    "id editionId editionLineageId itemId itemLineageId placementKey sortKey pageNumber priority metadata"
)
EDITION_SLOT_FIELDS = (
    "id editionId sectionKey slotRank targetType targetLengthBand minImageAssets status selectedAssignmentId metadata createdAt updatedAt"
)
PUBLISHED_EDITION_ITEM_FIELDS = (
    "id publishedEditionId publishedItemId sourceEditionItemId sourceEditionId sourceItemId editionLineageId "
    "itemLineageId placementKey sortKey pageNumber priority metadata"
)
ITEM_FIELDS = (
    f"{VERSION_FIELDS} id type status typeStatus slug shortSlug section sectionStatus title headline deck body "
    "byline dateline publishedAt editionDate sortTitle pullQuotes layout editorial updatedAt"
)
PUBLISHED_ITEM_FIELDS = (
    "id sourceItemId itemLineageId versionNumber type status typeStatus slug shortSlug section sectionStatus "
    "title headline deck body byline dateline publishedAt editionDate sortTitle pullQuotes layout editorial"
)
MEDIA_ASSET_FIELDS = (
    "id itemId type role sortKey storagePath externalUrl alt caption credit width height aspectRatio focalX focalY "
    "minHeight preferredHeight maxHeight crop wrapsText metadata"
)
PUBLISHED_MEDIA_ASSET_FIELDS = (
    "id sourceMediaAssetId publishedItemId sourceItemId itemLineageId type role sortKey storagePath externalUrl alt "
    "caption credit width height aspectRatio focalX focalY minHeight preferredHeight maxHeight crop wrapsText metadata"
)
ITEM_TAG_FIELDS = "id itemId tagId itemType itemStatus tagSlug publishedAt"
TAG_FIELDS = "id slug label type description"
SEMANTIC_NODE_FIELDS = (
    f"{VERSION_FIELDS} id nodeKey nodeKind corpusId categorySetId categoryLineageId categoryKey displayName "
    "description aliases authorityScore authorityRank acceptedReferenceMentionCount distinctSourceKindCount relationCount "
    "status importRunId createdAt updatedAt newsroomFeedKey"
)
KNOWLEDGE_ARTIFACT_FIELDS = (
    "id corpusId artifactKind artifactId snapshotId displayName createdAt importRunId"
)

LIST_DEFINITIONS: dict[str, dict[str, str]] = {
    "KnowledgeCorpus": {"field": "listKnowledgeCorpuses", "fields": KNOWLEDGE_CORPUS_FIELDS},
    "KnowledgeImportRun": {"field": "listKnowledgeImportRuns", "fields": KNOWLEDGE_IMPORT_RUN_FIELDS},
    "KnowledgeRawPayload": {"field": "listKnowledgeRawPayloads", "fields": KNOWLEDGE_RAW_PAYLOAD_FIELDS},
    "Reference": {"field": "listReferences", "fields": REFERENCE_FIELDS},
    "ReferenceAttachment": {"field": "listReferenceAttachments", "fields": REFERENCE_ATTACHMENT_FIELDS},
    "Assignment": {"field": "listAssignments", "fields": ASSIGNMENT_FIELDS},
    "AssignmentEvent": {"field": "listAssignmentEvents", "fields": ASSIGNMENT_EVENT_FIELDS},
    "CategorySet": {"field": "listCategorySets", "fields": CATEGORY_SET_FIELDS},
    "Category": {"field": "listCategories", "fields": CATEGORY_FIELDS},
    "CategoryKeyword": {"field": "listCategoryKeywords", "fields": CATEGORY_KEYWORD_FIELDS},
    "SteeringProposal": {"field": "listSteeringProposals", "fields": PROPOSAL_FIELDS},
    "SteeringDecision": {"field": "listSteeringDecisions", "fields": DECISION_FIELDS},
    "SemanticRelationType": {"field": "listSemanticRelationTypes", "fields": SEMANTIC_RELATION_TYPE_FIELDS},
    "SemanticRelation": {"field": "listSemanticRelations", "fields": SEMANTIC_RELATION_FIELDS},
    "Message": {"field": "listMessages", "fields": MESSAGE_FIELDS},
    "MessageThread": {"field": "listMessageThreads", "fields": MESSAGE_THREAD_FIELDS},
    "ProcedureDefinition": {"field": "listProcedureDefinitions", "fields": PROCEDURE_DEFINITION_FIELDS},
    "ProcedureVersion": {"field": "listProcedureVersions", "fields": PROCEDURE_VERSION_FIELDS},
    "ProcedureRun": {"field": "listProcedureRuns", "fields": PROCEDURE_RUN_FIELDS},
    "UserRoleAssignment": {"field": "listUserRoleAssignments", "fields": USER_ROLE_ASSIGNMENT_FIELDS},
    "ModelAttachment": {"field": "listModelAttachments", "fields": MODEL_ATTACHMENT_FIELDS},
    "NewsroomSection": {"field": "listNewsroomSections", "fields": NEWSROOM_SECTION_FIELDS},
    "Edition": {"field": "listEditions", "fields": EDITION_FIELDS},
    "PublishedEdition": {"field": "listPublishedEditions", "fields": PUBLISHED_EDITION_FIELDS},
    "EditionItem": {"field": "listEditionItems", "fields": EDITION_ITEM_FIELDS},
    "EditionSlot": {"field": "listEditionSlots", "fields": EDITION_SLOT_FIELDS},
    "PublishedEditionItem": {"field": "listPublishedEditionItems", "fields": PUBLISHED_EDITION_ITEM_FIELDS},
    "Item": {"field": "listItems", "fields": ITEM_FIELDS},
    "PublishedItem": {"field": "listPublishedItems", "fields": PUBLISHED_ITEM_FIELDS},
    "MediaAsset": {"field": "listMediaAssets", "fields": MEDIA_ASSET_FIELDS},
    "PublishedMediaAsset": {"field": "listPublishedMediaAssets", "fields": PUBLISHED_MEDIA_ASSET_FIELDS},
    "ItemTag": {"field": "listItemTags", "fields": ITEM_TAG_FIELDS},
    "Tag": {"field": "listTags", "fields": TAG_FIELDS},
    "SemanticNode": {"field": "listSemanticNodes", "fields": SEMANTIC_NODE_FIELDS},
    "KnowledgeArtifact": {"field": "listKnowledgeArtifacts", "fields": KNOWLEDGE_ARTIFACT_FIELDS},
}

GET_DEFINITIONS: dict[str, dict[str, str]] = {
    model: {
        "field": f"get{model}",
        "fields": LIST_DEFINITIONS[model]["fields"],
    }
    for model in LIST_DEFINITIONS
}

UPDATE_NEWSROOM_SUMMARY_MUTATION = """
mutation UpdateNewsroomSummary($delta: AWSJSON!, $actorLabel: String, $reason: String) {
  updateNewsroomSummary(delta: $delta, actorLabel: $actorLabel, reason: $reason) {
    generatedAt
    staleAt
    source
    counts
    facets
    assignmentStatusCounts
    assignmentTypeCounts
    referenceStatusCounts
    messageKindCounts
    messageDomainCounts
  }
}
"""

MODEL_ATTACHMENT_UPLOAD_FIELDS = """
  ok
  uploadId
  attachmentId
  ownerKind
  ownerId
  role
  sortKey
  method
  uploadUrl
  storagePath
  mediaType
  byteSize
  sha256
  expiresAt
  requiredHeaders
"""

CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION = f"""
mutation CreateModelAttachmentUpload(
  $ownerKind: String!
  $ownerId: ID!
  $ownerLineageId: ID
  $ownerVersionNumber: Int
  $ownerVersionKey: String
  $role: String!
  $sortKey: String
  $filename: String!
  $mediaType: String!
  $byteSize: Int!
  $sha256: String
  $importRunId: ID
  $status: String
) {{
  createModelAttachmentUpload(
    ownerKind: $ownerKind
    ownerId: $ownerId
    ownerLineageId: $ownerLineageId
    ownerVersionNumber: $ownerVersionNumber
    ownerVersionKey: $ownerVersionKey
    role: $role
    sortKey: $sortKey
    filename: $filename
    mediaType: $mediaType
    byteSize: $byteSize
    sha256: $sha256
    importRunId: $importRunId
    status: $status
  ) {{
    {MODEL_ATTACHMENT_UPLOAD_FIELDS}
  }}
}}
"""

LIST_EDITIONS_QUERY = """
query ListPublishedEditionsByStatusAndEditionDate($status: String!, $limit: Int, $nextToken: String) {
  listPublishedEditionsByStatusAndEditionDate(status: $status, limit: $limit, nextToken: $nextToken) {
    items { id slug title editionDate publishedAt description }
    nextToken
  }
}
"""

LIST_ARTICLES_QUERY = """
query ListPublishedItemsByTypeStatusAndPublishedAt($typeStatus: String!, $limit: Int, $nextToken: String) {
  listPublishedItemsByTypeStatusAndPublishedAt(typeStatus: $typeStatus, limit: $limit, nextToken: $nextToken) {
    items { id slug shortSlug headline title publishedAt }
    nextToken
  }
}
"""

LIST_MESSAGES_SAFE_QUERY = """
query ListMessagesSafe($limit: Int, $nextToken: String) {
  listMessages(limit: $limit, nextToken: $nextToken) {
    items {
      id
      createdAt
      updatedAt
      messageKind
      messageDomain
    }
    nextToken
  }
}
"""

LIST_MESSAGES_STATUS_PAGE_QUERY = """
query ListMessagesStatusPage($limit: Int, $nextToken: String) {
  listMessages(limit: $limit, nextToken: $nextToken) {
    items {
      id
      status
    }
    nextToken
  }
}
"""

GET_MESSAGE_STATUS_QUERY = """
query GetMessageStatus($id: ID!) {
  getMessage(id: $id) {
    id
    status
    updatedAt
  }
}
"""

SCHEMA_TYPE_FIELDS_QUERY = """
query PapyrusSchemaCheck($type: String!) {
  __type(name: $type) {
    name
    fields { name }
  }
}
"""

COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION = f"""
mutation CompleteModelAttachmentUpload(
  $uploadId: String!
  $ownerKind: String!
  $ownerId: ID!
  $ownerLineageId: ID
  $ownerVersionNumber: Int
  $ownerVersionKey: String
  $role: String!
  $sortKey: String
  $filename: String!
  $mediaType: String!
  $byteSize: Int!
  $sha256: String
  $importRunId: ID
  $status: String
) {{
  completeModelAttachmentUpload(
    uploadId: $uploadId
    ownerKind: $ownerKind
    ownerId: $ownerId
    ownerLineageId: $ownerLineageId
    ownerVersionNumber: $ownerVersionNumber
    ownerVersionKey: $ownerVersionKey
    role: $role
    sortKey: $sortKey
    filename: $filename
    mediaType: $mediaType
    byteSize: $byteSize
    sha256: $sha256
    importRunId: $importRunId
    status: $status
  ) {{
    id ownerKind ownerId role sortKey storagePath filename mediaType byteSize sha256 importRunId createdAt updatedAt status
  }}
}}
"""

CREATE_MODEL_ATTACHMENT_DOWNLOAD_MUTATION = """
mutation CreateModelAttachmentDownload($attachmentId: ID!) {
  createModelAttachmentDownload(attachmentId: $attachmentId) {
    ok
    attachmentId
    method
    downloadUrl
    storagePath
    mediaType
    byteSize
    expiresAt
    requiredHeaders
  }
}
"""

INDEX_DEFINITIONS: dict[str, dict[str, str]] = {
    "assignmentsByQueueStatusAndPriority": {
        "field": "listAssignmentsByQueueStatusAndPriority",
        "partitionKey": "queueStatusKey",
        "fields": ASSIGNMENT_FIELDS,
    },
    "assignmentsByTypeStatusAndCreatedAt": {
        "field": "listAssignmentsByTypeStatusAndCreatedAt",
        "partitionKey": "assignmentTypeKey",
        "fields": ASSIGNMENT_FIELDS,
    },
    "assignmentsBySectionQueueStatusAndPriority": {
        "field": "listAssignmentsBySectionQueueStatusAndPriority",
        "partitionKey": "sectionQueueStatusKey",
        "fields": ASSIGNMENT_FIELDS,
    },
    "assignmentEventsByAssignmentAndCreatedAt": {
        "field": "listAssignmentEventsByAssignmentAndCreatedAt",
        "partitionKey": "assignmentId",
        "fields": ASSIGNMENT_EVENT_FIELDS,
        "partitionType": "ID",
    },
    "semanticRelationsByObjectState": {
        "field": "listSemanticRelationsByObjectState",
        "partitionKey": "objectStateKey",
        "fields": SEMANTIC_RELATION_FIELDS,
    },
    "semanticRelationsBySubjectState": {
        "field": "listSemanticRelationsBySubjectState",
        "partitionKey": "subjectStateKey",
        "fields": SEMANTIC_RELATION_FIELDS,
    },
    "knowledgeImportRunsByCorpusKindAndImportedAt": {
        "field": "listKnowledgeImportRunsByCorpusKindAndImportedAt",
        "partitionKey": "corpusImportKindKey",
        "fields": KNOWLEDGE_IMPORT_RUN_FIELDS,
    },
    "knowledgeImportRunsByKindAndImportedAt": {
        "field": "listKnowledgeImportRunsByKindAndImportedAt",
        "partitionKey": "importKind",
        "fields": KNOWLEDGE_IMPORT_RUN_FIELDS,
    },
    "knowledgeArtifactsByImportRunAndKind": {
        "field": "listKnowledgeArtifactsByImportRunAndKind",
        "partitionKey": "importRunId",
        "fields": KNOWLEDGE_ARTIFACT_FIELDS,
        "partitionType": "ID",
    },
    "editionItemsByEditionAndSortKey": {
        "field": "listEditionItemsByEditionAndSortKey",
        "partitionKey": "editionId",
        "fields": EDITION_ITEM_FIELDS,
        "partitionType": "ID",
    },
    "publishedEditionItemsByEditionAndSortKey": {
        "field": "listPublishedEditionItemsByEditionAndSortKey",
        "partitionKey": "publishedEditionId",
        "fields": PUBLISHED_EDITION_ITEM_FIELDS,
        "partitionType": "ID",
    },
    "mediaAssetsByItemAndSortKey": {
        "field": "listMediaAssetsByItemAndSortKey",
        "partitionKey": "itemId",
        "fields": MEDIA_ASSET_FIELDS,
        "partitionType": "ID",
    },
    "publishedMediaAssetsByItemAndSortKey": {
        "field": "listPublishedMediaAssetsByItemAndSortKey",
        "partitionKey": "publishedItemId",
        "fields": PUBLISHED_MEDIA_ASSET_FIELDS,
        "partitionType": "ID",
    },
    "semanticNodesByImportRunAndNodeKey": {
        "field": "listSemanticNodesByImportRunAndNodeKey",
        "partitionKey": "importRunId",
        "fields": SEMANTIC_NODE_FIELDS,
        "partitionType": "ID",
    },
    "semanticRelationsByImportRunAndImportedAt": {
        "field": "listSemanticRelationsByImportRunAndImportedAt",
        "partitionKey": "importRunId",
        "fields": SEMANTIC_RELATION_FIELDS,
        "partitionType": "ID",
    },
    "modelAttachmentsByOwnerRoleAndSortKey": {
        "field": "listModelAttachmentsByOwnerRoleAndSortKey",
        "partitionKey": "ownerId",
        "fields": MODEL_ATTACHMENT_FIELDS,
        "partitionType": "ID",
    },
    "referenceAttachmentsByReferenceLineageAndSortKey": {
        "field": "listReferenceAttachmentsByReferenceLineageAndSortKey",
        "partitionKey": "referenceLineageId",
        "fields": REFERENCE_ATTACHMENT_FIELDS,
        "partitionType": "ID",
    },
}


def _index_query(field: str, partition_key: str, fields: str, partition_type: str = "String") -> str:
    operation = field[0].upper() + field[1:]
    return f"""
query {operation}(${partition_key}: {partition_type}!, $limit: Int, $nextToken: String) {{
  {field}({partition_key}: ${partition_key}, limit: $limit, nextToken: $nextToken) {{
    items {{ {fields} }}
    nextToken
  }}
}}
"""


def _list_query(field: str, fields: str) -> str:
    operation = field[0].upper() + field[1:]
    return f"""
query {operation}($limit: Int, $nextToken: String) {{
  {field}(limit: $limit, nextToken: $nextToken) {{
    items {{ {fields} }}
    nextToken
  }}
}}
"""


def _get_query(field: str, fields: str) -> str:
    operation = field[0].upper() + field[1:]
    return f"""
query {operation}($id: ID!) {{
  {field}(id: $id) {{ {fields} }}
}}
"""


def _model_mutations(model_name: str) -> dict[str, str]:
    return {
        "create": f"""
mutation Create{model_name}($input: Create{model_name}Input!) {{
  create{model_name}(input: $input) {{ id }}
}}
""",
        "update": f"""
mutation Update{model_name}($input: Update{model_name}Input!) {{
  update{model_name}(input: $input) {{ id }}
}}
""",
        "delete": f"""
mutation Delete{model_name}($input: Delete{model_name}Input!) {{
  delete{model_name}(input: $input) {{ id }}
}}
""",
    }


MUTATIONS = {model: _model_mutations(model) for model in LIST_DEFINITIONS}


class PapyrusGraphQLAuthoringClient:
    def __init__(self, endpoint: str | None = None, auth_token: str | None = None) -> None:
        self.endpoint = endpoint or graphql_endpoint()
        self.use_iam = graphql_use_iam()
        if self.use_iam:
            self.auth_token = auth_token or ""
        elif auth_token is not None:
            self.auth_token = auth_token
        else:
            self.auth_token = graphql_jwt()
        self.timeout_seconds = graphql_timeout_seconds()
        self._parsed_endpoint = urllib.parse.urlparse(self.endpoint)
        if self._parsed_endpoint.scheme != "https":
            raise ValueError(f"Unsupported GraphQL endpoint scheme: {self.endpoint}")
        self._endpoint_path = self._parsed_endpoint.path or "/"
        if self._parsed_endpoint.query:
            self._endpoint_path = f"{self._endpoint_path}?{self._parsed_endpoint.query}"
        self._connection: http.client.HTTPSConnection | None = None

    def _request_headers(self, payload: bytes) -> dict[str, str]:
        if self.use_iam:
            from .graphql_http import iam_signed_graphql_headers

            return iam_signed_graphql_headers(self.endpoint, payload)
        headers = graphql_request_headers(endpoint=self.endpoint, body=payload, token=self.auth_token)
        headers["Connection"] = "keep-alive"
        return headers

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        headers = self._request_headers(payload)
        body: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                connection = self._connection or self._open_connection()
                connection.request("POST", self._endpoint_path, body=payload, headers=headers)
                response = connection.getresponse()
                response_body = response.read().decode("utf-8", errors="replace")
                if response.status >= 400:
                    raise RuntimeError(
                        f"GraphQL request failed: {response.status} {response.reason}: {response_body}"
                    )
                body = json.loads(response_body)
                break
            except (TimeoutError, OSError, http.client.HTTPException, json.JSONDecodeError, RuntimeError) as error:
                last_error = error
                self._reset_connection()
                if attempt == 1:
                    raise RuntimeError(f"GraphQL request failed: {error}") from error
                continue
        if body is None:
            raise RuntimeError(f"GraphQL request failed: {last_error}")

        errors = body.get("errors") or []
        if errors:
            messages = "; ".join(str(entry.get("message") or entry) for entry in errors)
            raise RuntimeError(f"GraphQL request failed: {messages}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("GraphQL response did not include data.")
        return data

    def _open_connection(self) -> http.client.HTTPSConnection:
        connection = http.client.HTTPSConnection(
            self._parsed_endpoint.hostname,
            self._parsed_endpoint.port or 443,
            timeout=self.timeout_seconds,
        )
        self._connection = connection
        return connection

    def _reset_connection(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            pass

    def inspect_reachability(self) -> dict[str, Any]:
        return self.graphql(LIST_EDITIONS_QUERY, {"status": "published", "limit": 1})

    def list_published_articles(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_token = None
        while True:
            result = self.graphql(
                LIST_ARTICLES_QUERY,
                {"typeStatus": "article#published", "limit": 100, "nextToken": next_token},
            )
            connection = result.get("listPublishedItemsByTypeStatusAndPublishedAt") or {}
            items.extend(entry for entry in connection.get("items") or [] if entry)
            next_token = connection.get("nextToken")
            if not next_token:
                break
        return items

    def list_messages_safe(
        self,
        *,
        limit: int = 100,
        next_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        result = self.graphql(
            LIST_MESSAGES_SAFE_QUERY,
            {"limit": limit, "nextToken": next_token},
        )
        connection = result.get("listMessages") or {}
        return [entry for entry in connection.get("items") or [] if entry], connection.get("nextToken")

    def get_message_status(self, message_id: str) -> dict[str, Any] | None:
        result = self.graphql(GET_MESSAGE_STATUS_QUERY, {"id": message_id})
        return result.get("getMessage")

    def list_messages_status_page(
        self,
        *,
        limit: int = 100,
        next_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        result = self.graphql(
            LIST_MESSAGES_STATUS_PAGE_QUERY,
            {"limit": limit, "nextToken": next_token},
        )
        connection = result.get("listMessages") or {}
        return [entry for entry in connection.get("items") or [] if entry], connection.get("nextToken")

    def graphql_type_field_names(self, type_name: str) -> list[str]:
        result = self.graphql(SCHEMA_TYPE_FIELDS_QUERY, {"type": type_name})
        graphql_type = result.get("__type")
        if not graphql_type:
            raise ValueError(f"GraphQL type '{type_name}' was not found.")
        fields = graphql_type.get("fields") or []
        return sorted(str(field.get("name")) for field in fields if field.get("name"))

    def list_records(self, model_name: str) -> list[dict[str, Any]]:
        definition = LIST_DEFINITIONS[model_name]
        query = _list_query(definition["field"], definition["fields"])
        items: list[dict[str, Any]] = []
        next_token = None
        while True:
            result = self.graphql(query, {"limit": 100, "nextToken": next_token})
            connection = result.get(definition["field"]) or {}
            items.extend(entry for entry in connection.get("items") or [] if entry)
            next_token = connection.get("nextToken")
            if not next_token:
                break
        return items

    def get_record(self, model_name: str, record_id: str) -> dict[str, Any] | None:
        definition = GET_DEFINITIONS[model_name]
        query = _get_query(definition["field"], definition["fields"])
        result = self.graphql(query, {"id": record_id})
        return result.get(definition["field"])

    def get_records_by_id(self, model_name: str, record_ids: list[str]) -> dict[str, dict[str, Any]]:
        unique_ids = [record_id for record_id in dict.fromkeys(record_ids) if record_id]
        if not unique_ids:
            return {}
        if model_name not in LIST_DEFINITIONS:
            raise ValueError(f"Unsupported model for get_records_by_id: {model_name}")
        # Point lookups avoid scanning entire tables (e.g. thousands of References).
        if len(unique_ids) <= 100 and model_name in GET_DEFINITIONS:
            resolved: dict[str, dict[str, Any]] = {}
            for record_id in unique_ids:
                row = self.get_record(model_name, record_id)
                if row:
                    resolved[record_id] = row
            return resolved
        rows = self.list_records(model_name)
        by_id = {row["id"]: row for row in rows if row.get("id")}
        return {record_id: by_id[record_id] for record_id in unique_ids if record_id in by_id}

    def list_by_index(self, index_name: str, key_value: str, *, limit: int = 100) -> list[dict[str, Any]]:
        definition = INDEX_DEFINITIONS[index_name]
        query = _index_query(
            definition["field"],
            definition["partitionKey"],
            definition["fields"],
            definition.get("partitionType", "String"),
        )
        items: list[dict[str, Any]] = []
        next_token = None
        while True:
            result = self.graphql(
                query,
                {
                    definition["partitionKey"]: key_value,
                    "limit": limit,
                    "nextToken": next_token,
                },
            )
            connection = result.get(definition["field"]) or {}
            items.extend(entry for entry in connection.get("items") or [] if entry)
            next_token = connection.get("nextToken")
            if not next_token:
                break
        return items

    def list_assignments_by_queue_status_and_priority(self, queue_status_key: str) -> list[dict[str, Any]]:
        return self.list_by_index("assignmentsByQueueStatusAndPriority", queue_status_key)

    def list_assignments_by_type_status_and_created_at(self, assignment_type_key: str) -> list[dict[str, Any]]:
        return self.list_by_index("assignmentsByTypeStatusAndCreatedAt", assignment_type_key)

    def list_assignments_by_section_queue_status_and_priority(self, section_queue_status_key: str) -> list[dict[str, Any]]:
        return self.list_by_index("assignmentsBySectionQueueStatusAndPriority", section_queue_status_key)

    def list_assignment_events_by_assignment_and_created_at(self, assignment_id: str) -> list[dict[str, Any]]:
        return self.list_by_index("assignmentEventsByAssignmentAndCreatedAt", assignment_id)

    def list_semantic_relations_by_object_state(self, object_state_key: str) -> list[dict[str, Any]]:
        return self.list_by_index("semanticRelationsByObjectState", object_state_key)

    def list_semantic_relations_by_subject_state(self, subject_state_key: str) -> list[dict[str, Any]]:
        return self.list_by_index("semanticRelationsBySubjectState", subject_state_key)

    def list_knowledge_import_runs_by_corpus_kind_and_imported_at(self, corpus_import_kind_key: str) -> list[dict[str, Any]]:
        return self.list_by_index("knowledgeImportRunsByCorpusKindAndImportedAt", corpus_import_kind_key)

    def list_knowledge_import_runs_by_kind_and_imported_at(self, import_kind: str) -> list[dict[str, Any]]:
        return self.list_by_index("knowledgeImportRunsByKindAndImportedAt", import_kind)

    def list_knowledge_artifacts_by_import_run_and_kind(self, import_run_id: str) -> list[dict[str, Any]]:
        return self.list_by_index("knowledgeArtifactsByImportRunAndKind", import_run_id)

    def list_semantic_nodes_by_import_run_and_node_key(self, import_run_id: str) -> list[dict[str, Any]]:
        return self.list_by_index("semanticNodesByImportRunAndNodeKey", import_run_id)

    def list_semantic_relations_by_import_run_and_imported_at(self, import_run_id: str) -> list[dict[str, Any]]:
        return self.list_by_index("semanticRelationsByImportRunAndImportedAt", import_run_id)

    def list_reference_attachments_by_lineage(self, reference_lineage_id: str) -> list[dict[str, Any]]:
        return self.list_by_index("referenceAttachmentsByReferenceLineageAndSortKey", reference_lineage_id)

    def delete_record(self, model_name: str, record_id: str) -> None:
        if model_name not in MUTATIONS:
            raise ValueError(f"Unsupported model for delete: {model_name}")
        self.graphql(MUTATIONS[model_name]["delete"], {"input": {"id": record_id}})

    def safe_list_records(self, model_name: str) -> list[dict[str, Any]]:
        try:
            return self.list_records(model_name)
        except RuntimeError as error:
            message = str(error)
            if "FieldUndefined" in message or "not available" in message.lower():
                return []
            raise

    def update_newsroom_summary(
        self,
        delta: dict[str, Any],
        *,
        actor_label: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        result = self.graphql(
            UPDATE_NEWSROOM_SUMMARY_MUTATION,
            {
                "delta": json.dumps(delta),
                "actorLabel": actor_label,
                "reason": reason,
            },
        )
        return result.get("updateNewsroomSummary") or {}

    def create_record(self, model_name: str, input_payload: dict[str, Any]) -> None:
        if model_name not in MUTATIONS:
            raise ValueError(f"Unsupported model for create: {model_name}")
        prepared = strip_unsupported_payload_fields(model_name, add_operational_index_fields(model_name, input_payload))
        self.graphql(MUTATIONS[model_name]["create"], {"input": prepared})

    def upsert(self, model_name: str, input_payload: dict[str, Any]) -> str:
        prepared = strip_unsupported_payload_fields(model_name, add_operational_index_fields(model_name, input_payload))
        current = self.get_record(model_name, prepared["id"])
        mutation = MUTATIONS[model_name]["update" if current else "create"]
        self.graphql(mutation, {"input": prepared})
        return "updated" if current else "created"

    def update_record(self, model_name: str, input_payload: dict[str, Any]) -> None:
        if model_name not in MUTATIONS:
            raise ValueError(f"Unsupported model for update: {model_name}")
        prepared = strip_unsupported_payload_fields(model_name, add_operational_index_fields(model_name, input_payload))
        self.graphql(MUTATIONS[model_name]["update"], {"input": prepared})

    def create_model_attachment_upload(self, attachment: dict[str, Any]) -> dict[str, Any]:
        result = self.graphql(
            CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION,
            model_attachment_upload_variables(attachment),
        )
        slot = result.get("createModelAttachmentUpload") or {}
        headers = slot.get("requiredHeaders")
        if isinstance(headers, str):
            try:
                slot["requiredHeaders"] = json.loads(headers)
            except json.JSONDecodeError:
                slot["requiredHeaders"] = {}
        return slot

    def complete_model_attachment_upload(self, upload_id: str, attachment: dict[str, Any]) -> dict[str, Any]:
        variables = {"uploadId": upload_id, **model_attachment_upload_variables(attachment)}
        result = self.graphql(COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION, variables)
        return result.get("completeModelAttachmentUpload") or {}

    def create_model_attachment_download(self, attachment_id: str) -> dict[str, Any]:
        result = self.graphql(CREATE_MODEL_ATTACHMENT_DOWNLOAD_MUTATION, {"attachmentId": attachment_id})
        slot = result.get("createModelAttachmentDownload") or {}
        headers = slot.get("requiredHeaders")
        if isinstance(headers, str):
            try:
                slot["requiredHeaders"] = json.loads(headers)
            except json.JSONDecodeError:
                slot["requiredHeaders"] = {}
        return slot


def create_authoring_client() -> tuple[PapyrusGraphQLAuthoringClient, dict[str, Any]]:
    from .env import decode_jwt_claims

    if graphql_use_iam():
        return PapyrusGraphQLAuthoringClient(auth_token=""), {}
    token = graphql_jwt()
    return PapyrusGraphQLAuthoringClient(auth_token=token), decode_jwt_claims(token)


def model_attachment_upload_variables(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        "ownerKind": attachment["ownerKind"],
        "ownerId": attachment["ownerId"],
        "ownerLineageId": attachment.get("ownerLineageId"),
        "ownerVersionNumber": attachment.get("ownerVersionNumber"),
        "ownerVersionKey": attachment.get("ownerVersionKey"),
        "role": attachment["role"],
        "sortKey": attachment.get("sortKey"),
        "filename": attachment["filename"],
        "mediaType": attachment["mediaType"],
        "byteSize": attachment["byteSize"],
        "sha256": attachment.get("sha256"),
        "importRunId": attachment.get("importRunId"),
        "status": attachment.get("status"),
    }


def add_operational_index_fields(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(input_payload)
    if model_name == "Assignment":
        status = _clean_string(prepared.get("status")) or "open"
        queue_key = _clean_string(prepared.get("queueKey"))
        section_key = _clean_string(prepared.get("sectionKey")) or _clean_string(prepared.get("sectionId"))
        prepared["queueStatusKey"] = prepared.get("queueStatusKey") or (f"{queue_key}#{status}" if queue_key else None)
        prepared["sectionStatusKey"] = f"{section_key}#{status}" if section_key else None
        prepared["sectionQueueStatusKey"] = (
            f"{section_key}#{queue_key}#{status}" if section_key and queue_key else None
        )
    if model_name == "KnowledgeImportRun":
        corpus_id = _clean_string(prepared.get("corpusId"))
        import_kind = _clean_string(prepared.get("importKind"))
        prepared["corpusImportKindKey"] = (
            f"{corpus_id}#{import_kind}" if corpus_id and import_kind else prepared.get("corpusImportKindKey")
        )
    return prepared


def strip_unsupported_payload_fields(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(input_payload)
    if model_name == "Message":
        prepared.pop("body", None)
        prepared.pop("metadata", None)
    elif model_name == "Assignment":
        prepared.pop("sectionTypeStatusKey", None)
        prepared.pop("brief", None)
        prepared.pop("instructions", None)
        prepared.pop("metadata", None)
    elif model_name == "AssignmentEvent":
        prepared.pop("metadata", None)
    elif model_name == "KnowledgeRawPayload":
        prepared.pop("payload", None)
    return prepared


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
