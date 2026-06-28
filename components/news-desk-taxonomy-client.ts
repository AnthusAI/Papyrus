"use client";

import { generateClient } from "aws-amplify/data";
import { downloadData, getUrl } from "aws-amplify/storage";
import type { Schema } from "../amplify/data/resource";
import type { NewsDeskAppendix, NewsDeskCategoryTreeNode } from "../lib/content-types";
import { createEmptyCategorySteeringDashboard } from "../lib/category-dashboard";
import type {
  CategorySteeringArtifact,
  CategorySteeringCorpus,
  CategorySteeringDashboard,
  CategorySteeringImportRun,
  CategorySteeringProposal,
  CategorySteeringCategoryTree,
  CategorySteeringCategoryTreeNode,
  CategorySteeringCategory,
  CategorySteeringCategorySet,
  CategoryKeywordRecord,
  MessageRecord,
  ModelAttachmentRecord,
  HydratedModelPayload,
  NewsroomSummaryRecord,
  LexicalSteeringRuleRecord,
  AssignmentEventRecord,
  AssignmentRecord,
  EditionRecord,
  EditionSlotRecord,
  MessageThreadRecord,
  DoctrineRecord,
  NewsroomSectionRecord,
  ProcedureDefinitionRecord,
  ProcedureVersionRecord,
  ProcedureRunRecord,
  ReferenceAttachmentRecord,
  ReferenceRecord,
  SemanticNodeRecord,
  SemanticRelationRecord,
  UserDirectoryEntry,
} from "../lib/category-repository";
import { relationTypeKey } from "../lib/semantic-graph";
import { DOCTRINE_DEFINITIONS, getCategoryDoctrineDefinitions, type DoctrineCategory } from "../lib/doctrine";
import { configureAmplifyClient } from "./amplify-client-provider";
import { isUnauthenticatedError, loadReaderSessionSnapshot, type ReaderAuthSnapshot } from "./reader-auth-state";

const USER_POOL_AUTH_MODE = "userPool";
const USER_POOL_LIST_LIMIT = 500;
const USER_POOL_PAGE_LIMIT = 50;
const TEST_EDITOR_STORAGE_KEY = "papyrus:test-editor";
const TEST_EDITOR_NEWSROOM_MOCK_STORAGE_KEY = "papyrus:test-newsroom-mock";
const NEWSROOM_PAGE_LIMIT = 50;
const REFERENCE_REVIEWED_FEED_KEY = "references#reviewed";
const REFERENCE_STATUS_KEYS = ["pending", "accepted", "rejected", "archived"] as const;

const NEWSROOM_MESSAGE_FEED_QUERY = `
  query ListMessagesByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelMessageFilterInput) {
    listMessagesByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey }
      nextToken
    }
  }
`;

const LIST_MESSAGE_THREADS_BY_KIND_AND_UPDATED_AT_QUERY = `
  query ListMessageThreadsByKindAndUpdatedAt($threadKind: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listMessageThreadsByKindAndUpdatedAt(threadKind: $threadKind, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items {
        id
        threadKind
        status
        title
        summary
        primaryAnchorKind
        primaryAnchorId
        primaryAnchorLineageId
        primaryAnchorKey
        createdBySub
        createdByUserProfileId
        createdByLabel
        messageCount
        lastMessageId
        lastMessageAt
        contextDigest
        activeResponseMessageId
        responseLockOwner
        responseLockExpiresAt
        metadata
        createdAt
        updatedAt
        newsroomFeedKey
      }
      nextToken
    }
  }
`;

const LIST_MESSAGES_BY_THREAD_AND_SEQUENCE_QUERY = `
  query ListMessagesByThreadAndSequence($threadId: ID!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listMessagesByThreadAndSequence(threadId: $threadId, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items { id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey }
      nextToken
    }
  }
`;

const LIST_MESSAGES_BY_KIND_AND_CREATED_AT_QUERY = `
  query ListMessagesByKindAndCreatedAt($messageKind: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listMessagesByKindAndCreatedAt(messageKind: $messageKind, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items { id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey }
      nextToken
    }
  }
`;

const GET_MESSAGE_QUERY = `
  query GetMessage($id: ID!) {
    getMessage(id: $id) {
      id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey
    }
  }
`;

const CREATE_MESSAGE_THREAD_MUTATION = `
  mutation CreateMessageThread($input: CreateMessageThreadInput!) {
    createMessageThread(input: $input) {
      id
      threadKind
      status
      title
      summary
      primaryAnchorKind
      primaryAnchorId
      primaryAnchorLineageId
      primaryAnchorKey
      createdBySub
      createdByUserProfileId
      createdByLabel
      messageCount
      lastMessageId
      lastMessageAt
      contextDigest
      activeResponseMessageId
      responseLockOwner
      responseLockExpiresAt
      metadata
      createdAt
      updatedAt
      newsroomFeedKey
    }
  }
`;

const UPDATE_MESSAGE_THREAD_MUTATION = `
  mutation UpdateMessageThread($input: UpdateMessageThreadInput!) {
    updateMessageThread(input: $input) {
      id
      threadKind
      status
      title
      summary
      primaryAnchorKind
      primaryAnchorId
      primaryAnchorLineageId
      primaryAnchorKey
      createdBySub
      createdByUserProfileId
      createdByLabel
      messageCount
      lastMessageId
      lastMessageAt
      contextDigest
      activeResponseMessageId
      responseLockOwner
      responseLockExpiresAt
      metadata
      createdAt
      updatedAt
      newsroomFeedKey
    }
  }
`;

const CREATE_MESSAGE_MUTATION = `
  mutation CreateMessage($input: CreateMessageInput!) {
    createMessage(input: $input) {
      id
      messageKind
      messageDomain
      status
      summary
      source
      importRunId
      authorSub
      authorUserProfileId
      authorLabel
      threadId
      parentMessageId
      sequenceNumber
      role
      messageType
      content
      semanticLayer
      searchVisibility
      responseTarget
      responseStatus
      responseOwner
      responseStartedAt
      responseCompletedAt
      responseError
      metadata
      createdAt
      updatedAt
      newsroomFeedKey
    }
  }
`;

const UPDATE_MESSAGE_MUTATION = `
  mutation UpdateMessage($input: UpdateMessageInput!) {
    updateMessage(input: $input) {
      id
      messageKind
      messageDomain
      status
      summary
      source
      importRunId
      authorSub
      authorUserProfileId
      authorLabel
      threadId
      parentMessageId
      sequenceNumber
      role
      messageType
      content
      semanticLayer
      searchVisibility
      responseTarget
      responseStatus
      responseOwner
      responseStartedAt
      responseCompletedAt
      responseError
      metadata
      createdAt
      updatedAt
      newsroomFeedKey
    }
  }
`;

const NEWSROOM_ASSIGNMENT_FEED_QUERY = `
  query ListAssignmentsByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelAssignmentFilterInput) {
    listAssignmentsByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id assignmentTypeKey queueKey queueStatusKey status priority title summary assigneeType assigneeId assigneeKey claimedAt claimExpiresAt completedAt canceledAt corpusId categorySetId classifierId sectionId sectionKey sectionType sectionStatusKey sectionQueueStatusKey primaryFocusCategoryKey topicScopeCategoryKeys sourceSnapshotId importRunId createdBy createdAt updatedAt newsroomFeedKey }
      nextToken
    }
  }
`;

const NEWSROOM_REFERENCE_FEED_QUERY = `
  query ListReferencesByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt }
      nextToken
    }
  }
`;

const NEWSROOM_REFERENCE_IMPORTED_FEED_QUERY = `
  query ListReferencesByNewsroomFeedAndImportedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByNewsroomFeedAndImportedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt }
      nextToken
    }
  }
`;

const LIST_REFERENCES_BY_CURATION_STATUS_AND_UPDATED_AT_QUERY = `
  query ListReferencesByCurationStatusAndUpdatedAt($curationStatus: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByCurationStatusAndUpdatedAt(curationStatus: $curationStatus, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt }
      nextToken
    }
  }
`;

const LIST_REFERENCES_BY_REVIEWED_FEED_AND_UPDATED_AT_QUERY = `
  query ListReferencesByReviewedFeedAndUpdatedAt($reviewedFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByReviewedFeedAndUpdatedAt(reviewedFeedKey: $reviewedFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt }
      nextToken
    }
  }
`;

const LIST_REFERENCES_FALLBACK_QUERY = `
  query ListReferencesFallback($limit: Int, $nextToken: String) {
    listReferences(limit: $limit, nextToken: $nextToken) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt }
      nextToken
    }
  }
`;

const NEWSROOM_SEMANTIC_NODE_FEED_QUERY = `
  query ListSemanticNodesByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelSemanticNodeFilterInput) {
    listSemanticNodesByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash nodeKey nodeKind corpusId categorySetId categoryLineageId categoryKey displayName description aliases authorityScore authorityRank acceptedReferenceMentionCount distinctSourceKindCount relationCount status importRunId createdAt newsroomFeedKey updatedAt }
      nextToken
    }
  }
`;

const NEWSROOM_SEMANTIC_RELATION_FEED_QUERY = `
  query ListSemanticRelationsByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelSemanticRelationFilterInput) {
    listSemanticRelationsByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId subjectLineageId subjectVersionNumber objectKind objectId objectLineageId objectVersionNumber subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey subjectVersionKey objectVersionKey score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId importRunId importedAt createdAt updatedAt newsroomFeedKey metadata }
      nextToken
    }
  }
`;

const LIST_SEMANTIC_RELATIONS_BY_SUBJECT_STATE_QUERY = `
  query ListSemanticRelationsBySubjectState($subjectStateKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelSemanticRelationFilterInput) {
    listSemanticRelationsBySubjectState(subjectStateKey: $subjectStateKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId subjectLineageId subjectVersionNumber objectKind objectId objectLineageId objectVersionNumber subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey subjectVersionKey objectVersionKey score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId importRunId importedAt createdAt updatedAt newsroomFeedKey metadata }
      nextToken
    }
  }
`;

const LIST_SEMANTIC_RELATIONS_BY_OBJECT_STATE_QUERY = `
  query ListSemanticRelationsByObjectState($objectStateKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelSemanticRelationFilterInput) {
    listSemanticRelationsByObjectState(objectStateKey: $objectStateKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId subjectLineageId subjectVersionNumber objectKind objectId objectLineageId objectVersionNumber subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey subjectVersionKey objectVersionKey score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId importRunId importedAt createdAt updatedAt newsroomFeedKey metadata }
      nextToken
    }
  }
`;

const NEWSROOM_SECTION_LIST_QUERY = `
  query ListNewsroomSections($limit: Int, $nextToken: String) {
    listNewsroomSections(limit: $limit, nextToken: $nextToken) {
      items {
        id
        title
        shortTitle
        type
        editorialMission
        editorialPolicy
        enabled
        enabledStatus
        sortOrder
        defaultArticleTypes
        defaultPageBudget
        assignmentGuidance
        killCriteria
        visualGuidance
        createdAt
        updatedAt
      }
      nextToken
    }
  }
`;

const LIST_STEERING_PROPOSALS_QUERY = `
  query ListSteeringProposals($limit: Int, $nextToken: String) {
    listSteeringProposals(limit: $limit, nextToken: $nextToken) {
      items {
        id
        categorySetId
        corpusId
        importRunId
        proposalKind
        steeringDomain
        status
        title
        summary
        categoryKey
        targetCategoryKey
        graphEntityId
        relationshipType
        displayName
        shortTitle
        subtitle
        description
        evidenceItemIds
        suggestedSeedItemIds
        suggestedHoldoutItemIds
        sourceSnapshotId
        proposedAt
        reviewedAt
        reviewedBy
        updatedAt
      }
      nextToken
    }
  }
`;

const MODEL_ATTACHMENTS_BY_OWNER_QUERY = `
  query ListModelAttachmentsByOwnerRoleAndSortKey($ownerId: ID!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listModelAttachmentsByOwnerRoleAndSortKey(ownerId: $ownerId, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items {
        id
        ownerKind
        ownerId
        ownerLineageId
        ownerVersionNumber
        ownerVersionKey
        role
        sortKey
        storagePath
        filename
        mediaType
        byteSize
        sha256
        etag
        importRunId
        createdAt
        updatedAt
        status
      }
      nextToken
    }
  }
`;

/** Matches Reference model fields in amplify/data/resource.ts (no metadata on Reference). */
const REFERENCE_RECORD_GRAPHQL_FIELDS =
  "id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason newsroomFeedKey reviewedFeedKey updatedAt";

const LIST_REFERENCES_BY_LINEAGE_AND_VERSION_QUERY = `
  query ListReferencesByLineageAndVersion($lineageId: ID!, $limit: Int, $nextToken: String) {
    listReferencesByLineageAndVersion(lineageId: $lineageId, limit: $limit, nextToken: $nextToken) {
      items { ${REFERENCE_RECORD_GRAPHQL_FIELDS} }
      nextToken
    }
  }
`;

const GET_REFERENCE_QUERY = `
  query GetReference($id: ID!) {
    getReference(id: $id) {
      ${REFERENCE_RECORD_GRAPHQL_FIELDS}
    }
  }
`;

const LIST_REFERENCE_ATTACHMENTS_BY_REFERENCE_LINEAGE_AND_SORT_KEY_QUERY = `
  query ListReferenceAttachmentsByReferenceLineageAndSortKey($referenceLineageId: ID!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listReferenceAttachmentsByReferenceLineageAndSortKey(referenceLineageId: $referenceLineageId, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items {
        id
        referenceId
        referenceLineageId
        referenceVersionNumber
        referenceVersionKey
        role
        sortKey
        storagePath
        sourceUri
        filename
        mediaType
        byteSize
        sha256
        etag
        importRunId
        importedAt
        metadata
      }
      nextToken
    }
  }
`;

const CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION = `
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
  ) {
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
    ) {
      ok uploadId attachmentId ownerKind ownerId role sortKey method uploadUrl storagePath mediaType byteSize sha256 expiresAt requiredHeaders
    }
  }
`;

const CREATE_MODEL_ATTACHMENT_DOWNLOAD_MUTATION = `
  mutation CreateModelAttachmentDownload($attachmentId: ID!) {
    createModelAttachmentDownload(attachmentId: $attachmentId) {
      ok
      attachmentId
      method
      downloadUrl
      storagePath
      mediaType
      byteSize
      sha256
      expiresAt
      requiredHeaders
    }
  }
`;

const COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION = `
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
  ) {
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
    ) {
      id ownerKind ownerId ownerLineageId ownerVersionNumber ownerVersionKey role sortKey storagePath filename mediaType byteSize sha256 etag importRunId createdAt updatedAt status
    }
  }
`;

const LIST_PROCEDURE_DEFINITIONS_QUERY = `
  query ListProcedureDefinitions {
    listNewsroomProcedureDefinitions
  }
`;

const GET_PROCEDURE_DEFINITION_QUERY = `
  query GetProcedureDefinition($id: ID, $procedureKey: String) {
    getNewsroomProcedureDefinition(id: $id, procedureKey: $procedureKey)
  }
`;

const SAVE_PROCEDURE_DEFINITION_MUTATION = `
  mutation SaveProcedureDefinition($input: AWSJSON!) {
    saveNewsroomProcedureDefinition(input: $input)
  }
`;

const SAVE_PROCEDURE_VERSION_DRAFT_MUTATION = `
  mutation SaveProcedureVersionDraft($input: AWSJSON!) {
    saveNewsroomProcedureVersionDraft(input: $input)
  }
`;

const PUBLISH_PROCEDURE_VERSION_MUTATION = `
  mutation PublishProcedureVersion($versionId: ID!) {
    publishNewsroomProcedureVersion(versionId: $versionId)
  }
`;

const START_PROCEDURE_RUN_MUTATION = `
  mutation StartProcedureRun(
    $procedureId: ID
    $procedureKey: String
    $procedureVersionId: ID
    $title: String
    $summary: String
    $input: AWSJSON
    $actorLabel: String
  ) {
    startNewsroomProcedureRun(
      procedureId: $procedureId
      procedureKey: $procedureKey
      procedureVersionId: $procedureVersionId
      title: $title
      summary: $summary
      input: $input
      actorLabel: $actorLabel
    )
  }
`;

type GraphQLListResponse<T> = {
  data?: T[] | null;
  nextToken?: string | null;
  errors?: unknown[] | null;
};

type ListableModel<T> = {
  list: (input?: Record<string, unknown>, options?: Record<string, unknown>) => Promise<GraphQLListResponse<T>>;
};

export type NewsroomRecordPage<T> = {
  items: T[];
  nextToken?: string | null;
  hasMore: boolean;
};

type GraphQLConnectionResponse<T> = {
  data?: Record<string, { items?: Array<T | null> | null; nextToken?: string | null } | null> | null;
  errors?: unknown[] | null;
};

type ModelAttachmentUploadSlot = {
  ok: boolean;
  uploadId: string;
  requiredHeaders?: Record<string, string> | string | null;
  method?: string | null;
  uploadUrl: string;
};

type NewsroomPageOptions = {
  limit?: number;
  nextToken?: string | null;
};

type NewsroomMessagePageOptions = NewsroomPageOptions & {
  kind?: string;
  domain?: string;
  status?: string;
};

type NewsroomAssignmentPageOptions = NewsroomPageOptions & {
  type?: string;
  status?: string;
};

export type NewsroomReferencePageOrder = "published" | "imported";

type NewsroomReferencePageOptions = NewsroomPageOptions & {
  status?: string;
  excludePending?: boolean;
  corpusId?: string;
  order?: NewsroomReferencePageOrder | string;
};

type NewsroomSemanticNodePageOptions = NewsroomPageOptions & {
  nodeKind?: string;
  status?: string;
};

type NewsroomSemanticRelationPageOptions = NewsroomPageOptions & {
  relationTypeKey?: string;
  relationDomain?: string;
};

export type ForumThreadWithMessages = MessageThreadRecord & {
  messages: MessageRecord[];
  scope: "edition" | "section" | "insight";
  sectionKey?: string | null;
  sectionTitle?: string | null;
};

export type InsightForumThreadsPage = {
  threads: ForumThreadWithMessages[];
  nextToken: string | null;
};

export type EditionForumThreadsResult = {
  editionId: string;
  editionThreads: ForumThreadWithMessages[];
  sectionThreads: ForumThreadWithMessages[];
  threadCount: number;
};

type SlugQueryableModel<T> = {
  itemBySlug?: (args: { slug: string }, options: Record<string, unknown>) => Promise<GraphQLListResponse<T>>;
};

type NewsroomSummaryResponse = {
  data?: unknown;
  errors?: unknown[] | null;
};

export type KnowledgeQueryResponse = {
  structured?: unknown;
  context?: {
    format?: string;
    text?: string;
    maxTokens?: number | null;
    totalTokens?: number | null;
    tokenizer?: unknown;
  } | null;
  warnings?: string[];
  provenance?: Record<string, unknown>;
  debug?: Record<string, unknown>;
};

export type EditorCategoryTreeState = {
  isEditor: boolean;
  appendix: NewsDeskAppendix | null;
  categoryTrees: CategorySteeringCategoryTree[];
  categoryNodes: CategorySteeringCategoryTreeNode[];
  error: string | null;
};

export type EditorNewsDeskState =
  | { status: "loading"; dashboard: null; error: null }
  | { status: "signedOut"; dashboard: null; error: null }
  | { status: "forbidden"; dashboard: null; error: null }
  | { status: "ready"; dashboard: CategorySteeringDashboard; error: null }
  | { status: "error"; dashboard: null; error: string };

export async function loadEditorAccessState(): Promise<{ isEditor: boolean; status: EditorAccessState["status"]; error: string | null }> {
  const auth = await loadEditorResolvedAccessState();
  return { isEditor: auth.isEditor, status: auth.status, error: auth.error };
}

export type EditorAccessState =
  | { status: "signedOut"; isEditor: false; isAdmin: false; auth: ReaderAuthSnapshot; error: null }
  | { status: "forbidden"; isEditor: false; isAdmin: false; auth: ReaderAuthSnapshot; error: null }
  | { status: "ready"; isEditor: true; isAdmin: boolean; auth: ReaderAuthSnapshot; error: null }
  | { status: "error"; isEditor: false; isAdmin: false; auth: ReaderAuthSnapshot; error: string };

export async function loadEditorNewsDeskState(): Promise<EditorNewsDeskState> {
  const auth = await loadEditorResolvedAccessState();
  if (auth.status === "signedOut" || auth.status === "forbidden") return { status: auth.status, dashboard: null, error: null };
  if (auth.status === "error") return { status: "error", dashboard: null, error: auth.error };

  try {
    return { status: "ready", dashboard: await loadEditorNewsDeskDashboard({ isAdmin: auth.isAdmin }), error: null };
  } catch (error) {
    return {
      status: "error",
      dashboard: null,
      error: error instanceof Error ? error.message : "Could not load Newsroom data.",
    };
  }
}

export async function loadEditorCategoryTreeState(options?: {
  scenarioAppendix?: NewsDeskAppendix | null;
  allowScenarioEditorOverride?: boolean;
}): Promise<EditorCategoryTreeState> {
  configureAmplifyClient();

  if (options?.allowScenarioEditorOverride && hasTestEditorOverride()) {
    const appendix = options.scenarioAppendix ?? null;
    return {
      isEditor: true,
      appendix,
      categoryTrees: appendix ? [categoryTreeFromAppendix(appendix)] : [],
      categoryNodes: appendix ? appendix.nodes.map(categoryTreeNodeFromAppendixNode) : [],
      error: null,
    };
  }

  const auth = await loadEditorResolvedAccessState();
  if (!auth.isEditor) {
    return { isEditor: false, appendix: null, categoryTrees: [], categoryNodes: [], error: auth.error };
  }

  try {
    const [categoryTrees, categoryNodes] = await Promise.all([
      listUserPoolModel<CategorySteeringCategoryTree>("CategorySet"),
      listUserPoolModel<CategorySteeringCategoryTreeNode>("Category"),
    ]);
    const sortedTaxonomies = sortTaxonomies(categoryTrees);
    const sortedNodes = sortCategoryTreeNodes(categoryNodes);
    const selectedCategoryTree = selectCurrentAcceptedCategoryTree(sortedTaxonomies);
    return {
      isEditor: true,
      appendix: selectedCategoryTree ? appendixFromCategoryTree(selectedCategoryTree, sortedNodes) : null,
      categoryTrees: sortedTaxonomies,
      categoryNodes: sortedNodes,
      error: null,
    };
  } catch (error) {
    if (isUnauthenticatedError(error)) {
      return { isEditor: false, appendix: null, categoryTrees: [], categoryNodes: [], error: null };
    }
    return {
      isEditor: false,
      appendix: null,
      categoryTrees: [],
      categoryNodes: [],
      error: error instanceof Error ? error.message : "Could not load editor categoryTree state.",
    };
  }
}

export async function loadEditorResolvedAccessState(): Promise<EditorAccessState> {
  if (hasTestEditorOverride()) {
    return {
      status: "ready",
      isEditor: true,
      isAdmin: true,
      auth: { status: "signedIn", label: "Test Editor" },
      error: null,
    };
  }
  try {
    const snapshot = await loadReaderSessionSnapshot();
    if (!snapshot.hasSession || snapshot.auth.status === "signedOut") {
      return { status: "signedOut", isEditor: false, isAdmin: false, auth: snapshot.auth, error: null };
    }
    const refreshed = await loadReaderSessionSnapshot({ forceRefresh: true });
    if (!refreshed.hasSession || refreshed.auth.status === "signedOut") {
      return { status: "signedOut", isEditor: false, isAdmin: false, auth: refreshed.auth, error: null };
    }
    return {
      status: "ready",
      isEditor: true,
      isAdmin: refreshed.groups.includes("admin"),
      auth: refreshed.auth,
      error: null,
    };
  } catch (error) {
    return {
      status: "error",
      isEditor: false,
      isAdmin: false,
      auth: { status: "signedOut", label: "Signed out" },
      error: error instanceof Error ? error.message : "Could not verify editor session.",
    };
  }
}

export async function loadEditorNewsDeskDashboard({ isAdmin }: { isAdmin: boolean }): Promise<CategorySteeringDashboard> {
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.summary) {
    return {
      ...createSummaryCategorySteeringDashboard(normalizeNewsroomSummary(testMock.summary)),
      canManageUsers: isAdmin,
      userDirectory: [],
      loadError: null,
    };
  }
  const [summaryResult, userDirectoryResult] = await Promise.allSettled([
    loadNewsroomSummary(),
    isAdmin ? loadUserDirectory() : Promise.resolve([]),
  ]);
  const summaryError = summaryResult.status === "rejected" ? summaryResult.reason : null;
  if (summaryError && isUnauthenticatedError(summaryError)) {
    throw summaryError;
  }
  const summary = summaryResult.status === "fulfilled" ? summaryResult.value : null;
  const userDirectory = userDirectoryResult.status === "fulfilled" ? userDirectoryResult.value : [];

  if (summaryError || newsroomSummaryIsMissing(summary)) {
    return {
      ...createEmptyCategorySteeringDashboard(),
      isPublicSkeleton: false,
      summaryStatus: "missing",
      canManageUsers: isAdmin,
      userDirectory,
      loadError: null,
    };
  }

  return {
    ...createSummaryCategorySteeringDashboard(summary!),
    canManageUsers: isAdmin,
    userDirectory,
    loadError: null,
  };
}

export async function loadEditorFullNewsDeskDashboard({ isAdmin }: { isAdmin: boolean }): Promise<CategorySteeringDashboard> {
  const procedureDataPromise = isAdmin
    ? loadEditorProcedureData().catch(() => ({ definitions: [], versions: [], runs: [] }))
    : Promise.resolve<{ definitions: ProcedureDefinitionRecord[]; versions: ProcedureVersionRecord[]; runs: ProcedureRunRecord[] }>({
      definitions: [],
      versions: [],
      runs: [],
    });
  const [
    corpora,
    importRuns,
    categorySets,
    categorys,
    categoryKeywords,
    lexicalSteeringRules,
    proposals,
    artifacts,
    references,
    referenceAttachments,
    semanticNodes,
    messages,
    semanticRelations,
    assignmentState,
    editionSlots,
    newsroomSections,
    procedureData,
    userDirectory,
  ] = await Promise.all([
    loadDashboardSlice("KnowledgeCorpus", () => listUserPoolModel<CategorySteeringCorpus>("KnowledgeCorpus"), [] as CategorySteeringCorpus[]),
    loadDashboardSlice("KnowledgeImportRun", () => listUserPoolModel<CategorySteeringImportRun>("KnowledgeImportRun"), [] as CategorySteeringImportRun[]),
    loadDashboardSlice("CategorySet", () => listUserPoolModel<CategorySteeringCategorySet>("CategorySet"), [] as CategorySteeringCategorySet[]),
    loadDashboardSlice("Category", () => listUserPoolModel<CategorySteeringCategory>("Category"), [] as CategorySteeringCategory[]),
    loadDashboardSlice("CategoryKeyword", () => listOptionalUserPoolModel<CategoryKeywordRecord>("CategoryKeyword"), [] as CategoryKeywordRecord[]),
    loadDashboardSlice("LexicalSteeringRule", () => listOptionalUserPoolModel<LexicalSteeringRuleRecord>("LexicalSteeringRule"), [] as LexicalSteeringRuleRecord[]),
    loadDashboardSlice("SteeringProposal", () => listSteeringProposalsViaGraphql(), [] as CategorySteeringProposal[]),
    loadDashboardSlice("KnowledgeArtifact", () => listUserPoolModel<CategorySteeringArtifact>("KnowledgeArtifact"), [] as CategorySteeringArtifact[]),
    loadDashboardSlice("Reference", () => listUserPoolModel<ReferenceRecord>("Reference"), [] as ReferenceRecord[]),
    loadDashboardSlice("ReferenceAttachment", () => listUserPoolModel<ReferenceAttachmentRecord>("ReferenceAttachment"), [] as ReferenceAttachmentRecord[]),
    loadDashboardSlice("SemanticNode", () => listUserPoolModel<SemanticNodeRecord>("SemanticNode"), [] as SemanticNodeRecord[]),
    loadDashboardSlice("Message", () => listUserPoolModel<MessageRecord>("Message"), [] as MessageRecord[]),
    loadDashboardSlice("SemanticRelation", () => listUserPoolModel<SemanticRelationRecord>("SemanticRelation"), [] as SemanticRelationRecord[]),
    loadDashboardSlice("Assignments", () => loadEditorAssignmentsData(), { assignments: [], assignmentEvents: [] }),
    loadDashboardSlice("EditionSlot", () => listOptionalUserPoolModel<EditionSlotRecord>("EditionSlot"), [] as EditionSlotRecord[]),
    loadDashboardSlice("NewsroomSection", () => listOptionalUserPoolModel<NewsroomSectionRecord>("NewsroomSection"), [] as NewsroomSectionRecord[]),
    procedureDataPromise,
    loadDashboardSlice("UserDirectory", () => (isAdmin ? loadUserDirectory() : Promise.resolve([])), [] as UserDirectoryEntry[]),
  ]);

  const sortedCorpora = corpora.sort((left, right) => left.name.localeCompare(right.name));
  const sortedImportRuns = importRuns.sort((left, right) => right.importedAt.localeCompare(left.importedAt));
  const sortedCategorySets = sortCategorySets(categorySets, sortedImportRuns);
  const canonicalCategorySet = selectCanonicalCategorySet(sortedCorpora, sortedCategorySets);
  const sortedCategorys = sortCategorys(categorys);
  const sortedCategoryNodes = sortCategoryTreeNodes(categorys);
  const acceptedDoctrineCategories = selectAcceptedCategoriesForDoctrine({
    categorys: sortedCategorys,
    categoryNodes: sortedCategoryNodes,
    categorySetId: canonicalCategorySet?.id ?? null,
  });
  const doctrineRecords = await loadDoctrineRecords(acceptedDoctrineCategories);
  const sortedNewsroomSections = sortNewsroomSections(newsroomSections);
  const sortedEditionSlots = [...editionSlots].sort((left, right) => (
    (left.editionId ?? "").localeCompare(right.editionId ?? "")
    || (left.sectionKey ?? "").localeCompare(right.sectionKey ?? "")
    || Number(left.slotRank ?? 0) - Number(right.slotRank ?? 0)
    || (left.id ?? "").localeCompare(right.id ?? "")
  ));

  return {
    canonicalCorpusId: canonicalCategorySet?.corpusId ?? selectCanonicalCorpus(sortedCorpora)?.id ?? null,
    canonicalCategorySetId: canonicalCategorySet?.id ?? null,
    canManageUsers: isAdmin,
    userDirectory,
    corpora: sortedCorpora,
    importRuns: sortedImportRuns,
    categorySets: sortedCategorySets,
    categorys: sortedCategorys,
    categoryTrees: sortTaxonomies(categorySets),
    categoryNodes: sortedCategoryNodes,
    categoryKeywords: categoryKeywords.sort((left, right) => keywordSortKey(left).localeCompare(keywordSortKey(right))),
    lexicalSteeringRules: lexicalSteeringRules.sort((left, right) => lexicalRuleSortKey(left).localeCompare(lexicalRuleSortKey(right))),
    proposals: sortProposals(proposals),
    artifacts: artifacts.sort((left, right) => (right.createdAt ?? "").localeCompare(left.createdAt ?? "")),
    references: references.sort((left, right) => (right.importedAt ?? "").localeCompare(left.importedAt ?? "")),
    referenceAttachments: referenceAttachments.sort((left, right) => left.sortKey.localeCompare(right.sortKey)),
    semanticNodes: semanticNodes.sort((left, right) => (left.displayName ?? left.nodeKey).localeCompare(right.displayName ?? right.nodeKey)),
    messages: messages.sort((left, right) => right.createdAt.localeCompare(left.createdAt)),
    semanticRelations: semanticRelations.sort((left, right) => (right.score ?? 0) - (left.score ?? 0)),
    assignments: assignmentState.assignments,
    assignmentEvents: assignmentState.assignmentEvents,
    editionSlots: sortedEditionSlots,
    doctrineRecords,
    newsroomSections: sortedNewsroomSections,
    procedureDefinitions: procedureData.definitions,
    procedureVersions: procedureData.versions,
    procedureRuns: procedureData.runs,
    loadError: null,
  };
}

async function loadDashboardSlice<T>(label: string, loader: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await loader();
  } catch (error) {
    console.warn(`Newsroom dashboard slice failed: ${label}`, error);
    return fallback;
  }
}

export async function loadEditorProcedureData(): Promise<{
  definitions: ProcedureDefinitionRecord[];
  versions: ProcedureVersionRecord[];
  runs: ProcedureRunRecord[];
}> {
  const dataClient = generateClient<Schema>();
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, unknown> | null; errors?: unknown[] | null }>;
  };
  const response = await graphClient.graphql({
    query: LIST_PROCEDURE_DEFINITIONS_QUERY,
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  const payload = normalizeJsonValue(response.data?.listNewsroomProcedureDefinitions);
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const definitions: ProcedureDefinitionRecord[] = [];
  const versions: ProcedureVersionRecord[] = [];
  const runs: ProcedureRunRecord[] = [];
  const versionIds = new Set<string>();
  const runIds = new Set<string>();
  const hydrateDefinitionIds: string[] = [];

  const pushVersion = (value: unknown) => {
    const normalized = normalizeJsonValue(value);
    if (!normalized?.id || !normalized?.procedureId) return;
    const id = String(normalized.id);
    if (versionIds.has(id)) return;
    versionIds.add(id);
    versions.push(normalized as ProcedureVersionRecord);
  };

  const pushRun = (value: unknown) => {
    const normalized = normalizeJsonValue(value);
    if (!normalized?.id || !normalized?.procedureId) return;
    const id = String(normalized.id);
    if (runIds.has(id)) return;
    runIds.add(id);
    runs.push(normalized as ProcedureRunRecord);
  };

  for (const item of items) {
    const row = normalizeJsonValue(item);
    if (!row || !row.id || !row.procedureKey) continue;
    definitions.push(row as ProcedureDefinitionRecord);
    pushVersion(row.currentVersion);
    const rowVersions = Array.isArray(row.versions) ? row.versions : [];
    for (const version of rowVersions) pushVersion(version);
    if (rowVersions.length === 0) hydrateDefinitionIds.push(String(row.id));
    const rowRuns = Array.isArray(row.recentRuns) ? row.recentRuns : [];
    for (const run of rowRuns) pushRun(run);
  }

  if (hydrateDefinitionIds.length > 0) {
    await Promise.all(hydrateDefinitionIds.map(async (definitionId) => {
      const detailResponse = await graphClient.graphql({
        query: GET_PROCEDURE_DEFINITION_QUERY,
        variables: { id: definitionId },
        authMode: USER_POOL_AUTH_MODE,
      });
      assertNoGraphQLErrors(detailResponse.errors);
      const detail = normalizeJsonValue(detailResponse.data?.getNewsroomProcedureDefinition);
      if (!detail) return;
      pushVersion(detail.currentVersion);
      const detailVersions = Array.isArray(detail.versions) ? detail.versions : [];
      for (const version of detailVersions) pushVersion(version);
      const detailRuns = Array.isArray(detail.recentRuns) ? detail.recentRuns : [];
      for (const run of detailRuns) pushRun(run);
    }));
  }

  return {
    definitions: definitions.sort((left, right) => (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "")),
    versions: versions.sort((left, right) => (right.versionNumber ?? 0) - (left.versionNumber ?? 0)),
    runs: runs.sort((left, right) => (right.requestedAt ?? "").localeCompare(left.requestedAt ?? "")),
  };
}

export async function saveProcedureDefinitionRecord(input: Record<string, unknown>) {
  const dataClient = generateClient<Schema>();
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, unknown> | null; errors?: unknown[] | null }>;
  };
  const response = await graphClient.graphql({
    query: SAVE_PROCEDURE_DEFINITION_MUTATION,
    variables: { input },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return normalizeJsonValue(response.data?.saveNewsroomProcedureDefinition);
}

export async function saveProcedureVersionDraftRecord(input: Record<string, unknown>) {
  const dataClient = generateClient<Schema>();
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, unknown> | null; errors?: unknown[] | null }>;
  };
  const response = await graphClient.graphql({
    query: SAVE_PROCEDURE_VERSION_DRAFT_MUTATION,
    variables: { input },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return normalizeJsonValue(response.data?.saveNewsroomProcedureVersionDraft);
}

export async function publishProcedureVersionRecord(versionId: string) {
  const dataClient = generateClient<Schema>();
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, unknown> | null; errors?: unknown[] | null }>;
  };
  const response = await graphClient.graphql({
    query: PUBLISH_PROCEDURE_VERSION_MUTATION,
    variables: { versionId },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return normalizeJsonValue(response.data?.publishNewsroomProcedureVersion);
}

export async function startProcedureRunRecord(input: {
  procedureId?: string;
  procedureKey?: string;
  procedureVersionId?: string;
  title?: string;
  summary?: string;
  actorLabel?: string;
  parameters?: Record<string, unknown>;
}) {
  const dataClient = generateClient<Schema>();
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, unknown> | null; errors?: unknown[] | null }>;
  };
  const response = await graphClient.graphql({
    query: START_PROCEDURE_RUN_MUTATION,
    variables: {
      procedureId: input.procedureId,
      procedureKey: input.procedureKey,
      procedureVersionId: input.procedureVersionId,
      title: input.title,
      summary: input.summary,
      actorLabel: input.actorLabel,
      input: input.parameters ?? {},
    },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return normalizeJsonValue(response.data?.startNewsroomProcedureRun);
}

export async function loadEditorMessagesData(): Promise<MessageRecord[]> {
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.messages) return testMock.messages;
  const page = await loadNewsroomMessagePage();
  return page.items;
}

export async function loadNewsroomMessagePage(options: NewsroomMessagePageOptions = {}): Promise<NewsroomRecordPage<MessageRecord>> {
  return loadNewsroomFeedPage<MessageRecord>({
    query: NEWSROOM_MESSAGE_FEED_QUERY,
    field: "listMessagesByNewsroomFeedAndCreatedAt",
    newsroomFeedKey: "messages",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: equalityMatcher({
      messageKind: options.kind,
      messageDomain: options.domain,
      status: options.status,
    }),
  });
}

export async function loadEditionForumThreads(options: {
  editionId: string;
  sectionId?: string | null;
  sectionKey?: string | null;
  includeMessages?: boolean;
  status?: string;
  limit?: number;
}): Promise<EditionForumThreadsResult> {
  const editionId = String(options.editionId || "").trim();
  if (!editionId) {
    return { editionId: "", editionThreads: [], sectionThreads: [], threadCount: 0 };
  }
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.forumThreadsByEdition?.[editionId]) {
    const allThreads = testMock.forumThreadsByEdition[editionId] ?? [];
    const sectionId = String(options.sectionId || "").trim();
    const sectionKey = slugifyKey(options.sectionKey);
    const editionThreads = allThreads.filter((thread) => thread.scope === "edition");
    let sectionThreads = allThreads.filter((thread) => thread.scope === "section");
    if (sectionId) sectionThreads = sectionThreads.filter((thread) => thread.primaryAnchorId === sectionId);
    if (sectionKey) {
      sectionThreads = sectionThreads.filter((thread) => (
        slugifyKey(thread.sectionKey)
        || slugifyKey(metadataString(thread.metadata, "sectionKey"))
      ) === sectionKey);
    }
    return {
      editionId,
      editionThreads: editionThreads.sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? ""))),
      sectionThreads: sectionThreads.sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? ""))),
      threadCount: editionThreads.length + sectionThreads.length,
    };
  }

  const status = String(options.status || "active").trim();
  const limit = Math.max(1, Math.min(options.limit ?? 200, 500));
  const includeMessages = options.includeMessages !== false;
  const [editionThreadsRaw, sectionThreadsRaw] = await Promise.all([
    listMessageThreadsByKind("edition_forum", limit),
    listMessageThreadsByKind("section_forum", limit),
  ]);
  const sectionId = String(options.sectionId || "").trim();
  const sectionKey = slugifyKey(options.sectionKey);
  const editionThreads = editionThreadsRaw.filter((thread) => (
    (!status || thread.status === status)
    && thread.primaryAnchorKind === "edition"
    && thread.primaryAnchorId === editionId
  ));
  let sectionThreads = sectionThreadsRaw.filter((thread) => (
    (!status || thread.status === status)
    && thread.primaryAnchorKind === "newsroom_section"
    && thread.primaryAnchorLineageId === editionId
  ));
  if (sectionId) sectionThreads = sectionThreads.filter((thread) => thread.primaryAnchorId === sectionId);
  if (sectionKey) {
    sectionThreads = sectionThreads.filter((thread) => (
      slugifyKey(metadataString(thread.metadata, "sectionKey"))
      || slugifyKey(thread.primaryAnchorId)
    ) === sectionKey);
  }

  async function hydrateThread(thread: MessageThreadRecord, scope: "edition" | "section"): Promise<ForumThreadWithMessages> {
    const messages = includeMessages ? await listMessagesByThreadId(thread.id, 500) : [];
    return {
      ...thread,
      scope,
      sectionKey: metadataString(thread.metadata, "sectionKey"),
      sectionTitle: metadataString(thread.metadata, "sectionTitle"),
      messages,
    };
  }

  const [editionHydrated, sectionHydrated] = await Promise.all([
    Promise.all(editionThreads.map((thread) => hydrateThread(thread, "edition"))),
    Promise.all(sectionThreads.map((thread) => hydrateThread(thread, "section"))),
  ]);
  editionHydrated.sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
  sectionHydrated.sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
  return {
    editionId,
    editionThreads: editionHydrated,
    sectionThreads: sectionHydrated,
    threadCount: editionHydrated.length + sectionHydrated.length,
  };
}

export async function loadInsightForumThreads(options: {
  domain?: string;
  limit?: number;
  nextToken?: string | null;
  includeMessages?: boolean;
} = {}): Promise<InsightForumThreadsPage> {
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.insightForumThreads) {
    const domain = String(options.domain || "").trim();
    let threads = testMock.insightForumThreads;
    if (domain) threads = threads.filter((thread) => thread.sectionKey === domain);
    return { threads, nextToken: null };
  }

  const limit = Math.max(1, Math.min(options.limit ?? NEWSROOM_PAGE_LIMIT, 100));
  const domain = String(options.domain || "").trim();
  const includeMessages = options.includeMessages !== false;
  type KindConnectionResponse = {
    listMessagesByKindAndCreatedAt?: {
      items?: Array<MessageRecord | null> | null;
      nextToken?: string | null;
    } | null;
  };
  const response: KindConnectionResponse = await runGraphql<KindConnectionResponse>(
    LIST_MESSAGES_BY_KIND_AND_CREATED_AT_QUERY,
    {
      messageKind: "insight",
      sortDirection: "DESC",
      limit,
      nextToken: options.nextToken ?? null,
    },
  );
  const connection = response.listMessagesByKindAndCreatedAt;
  const roots = (connection?.items ?? [])
    .filter(Boolean)
    .map((item) => normalizeMessageRecord(item as MessageRecord))
    .filter(isInsightThreadRootMessage)
    .filter((message) => !domain || message.messageDomain === domain);

  const threads = await Promise.all(roots.map(async (root) => {
    const messages = includeMessages
      ? await loadInsightThreadMessages(root.id, root)
      : [root];
    return buildInsightForumThread(root, messages);
  }));

  return {
    threads,
    nextToken: connection?.nextToken ?? null,
  };
}

export async function loadInsightForumThreadById(
  threadId: string,
  options: { includeMessages?: boolean } = {},
): Promise<ForumThreadWithMessages | null> {
  const normalized = String(threadId || "").trim();
  if (!normalized) return null;
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.insightForumThreads) {
    return testMock.insightForumThreads.find((thread) => thread.id === normalized) ?? null;
  }
  const root = await getMessageRecordById(normalized);
  if (!root || !isInsightThreadRootMessage(root)) return null;
  const includeMessages = options.includeMessages !== false;
  const messages = includeMessages
    ? await loadInsightThreadMessages(normalized, root)
    : [root];
  return buildInsightForumThread(root, messages);
}

export async function appendInsightThreadReplyRecord(input: {
  threadId: string;
  summary: string;
  content: string;
  role?: string;
  authorLabel?: string;
  parentMessageId?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<MessageRecord> {
  const threadId = String(input.threadId || "").trim();
  const summary = String(input.summary || "").trim();
  const content = String(input.content || "").trim();
  if (!threadId) throw new Error("threadId is required");
  if (!summary) throw new Error("summary is required");
  if (!content) throw new Error("content is required");
  const root = await getMessageRecordById(threadId);
  if (!root || !isInsightThreadRootMessage(root)) throw new Error(`Insight thread not found: ${threadId}`);
  const existing = await listMessagesByThreadId(threadId, 1000);
  const nextSequence = Math.max(1, ...existing.map((message) => Number(message.sequenceNumber || 0))) + 1;
  const now = new Date().toISOString();
  const message: MessageRecord = {
    id: `message-insight-reply-${safeForumId(threadId)}-${String(nextSequence).padStart(4, "0")}`,
    messageKind: "insight_reply",
    messageDomain: root.messageDomain ?? "knowledge",
    status: "active",
    summary,
    source: "newsroom.insights",
    authorLabel: input.authorLabel?.trim() || "editor",
    threadId,
    parentMessageId: input.parentMessageId?.trim() || null,
    sequenceNumber: nextSequence,
    role: input.role || "human",
    messageType: "insight_forum_reply",
    content,
    metadata: input.metadata ?? {},
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "messages",
  };
  const created = await runGraphql<{ createMessage?: MessageRecord | null }>(
    CREATE_MESSAGE_MUTATION,
    { input: message },
  );
  return normalizeMessageRecord(created.createMessage ?? message);
}

export async function deleteInsightThreadMessageRecord(input: {
  threadId: string;
  messageId: string;
}): Promise<MessageRecord> {
  const threadId = String(input.threadId || "").trim();
  const messageId = String(input.messageId || "").trim();
  if (!threadId) throw new Error("threadId is required");
  if (!messageId) throw new Error("messageId is required");
  const existing = await listMessagesByThreadId(threadId, 1000);
  const target = existing.find((message) => message.id === messageId);
  if (!target) throw new Error(`Message not found in thread: ${messageId}`);
  const now = new Date().toISOString();
  const updatedMessage = await runGraphql<{ updateMessage?: MessageRecord | null }>(
    UPDATE_MESSAGE_MUTATION,
    {
      input: {
        id: target.id,
        status: "deleted",
        updatedAt: now,
      },
    },
  );
  return normalizeMessageRecord(updatedMessage.updateMessage ?? { ...target, status: "deleted", updatedAt: now });
}

export async function ensureEditionForumThreadRecord(input: {
  editionId: string;
  title?: string;
  summary?: string;
  actorLabel?: string;
  metadata?: Record<string, unknown>;
}): Promise<{ created: boolean; thread: MessageThreadRecord }> {
  const editionId = String(input.editionId || "").trim();
  if (!editionId) throw new Error("editionId is required");
  const existing = await loadEditionForumThreads({
    editionId,
    includeMessages: false,
    status: "",
    limit: 40,
  });
  if (existing.editionThreads.length) return { created: false, thread: existing.editionThreads[0] };
  const now = new Date().toISOString();
  const thread: MessageThreadRecord = {
    id: `message-thread-edition-forum-${safeForumId(editionId)}`,
    threadKind: "edition_forum",
    status: "active",
    title: input.title?.trim() || "Upcoming edition",
    summary: input.summary?.trim() || "Cross-section editor and human coordination for this edition.",
    primaryAnchorKind: "edition",
    primaryAnchorId: editionId,
    primaryAnchorLineageId: editionId,
    primaryAnchorKey: `edition#${editionId}`,
    createdByLabel: input.actorLabel?.trim() || "editor",
    messageCount: 0,
    lastMessageId: null,
    lastMessageAt: null,
    metadata: {
      editionId,
      ...(input.metadata ?? {}),
    },
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "messages",
  };
  const response = await runGraphql<{ createMessageThread?: MessageThreadRecord | null }>(
    CREATE_MESSAGE_THREAD_MUTATION,
    { input: thread },
  );
  return { created: true, thread: normalizeThreadRecord(response.createMessageThread ?? thread) };
}

export async function createSectionForumThreadRecord(input: {
  editionId: string;
  sectionId: string;
  sectionKey?: string | null;
  sectionTitle?: string | null;
  title?: string;
  summary?: string;
  actorLabel?: string;
  metadata?: Record<string, unknown>;
}): Promise<{ created: boolean; thread: MessageThreadRecord }> {
  const editionId = String(input.editionId || "").trim();
  const sectionId = String(input.sectionId || "").trim();
  if (!editionId) throw new Error("editionId is required");
  if (!sectionId) throw new Error("sectionId is required");
  const now = new Date().toISOString();
  const thread: MessageThreadRecord = {
    id: `message-thread-section-forum-${safeForumId(editionId)}-${safeForumId(sectionId)}-${safeForumId(now)}`,
    threadKind: "section_forum",
    status: "active",
    title: input.title?.trim() || `Section Forum: ${input.sectionTitle || input.sectionKey || sectionId}`,
    summary: input.summary?.trim() || "Section-scoped editorial steering thread for this edition.",
    primaryAnchorKind: "newsroom_section",
    primaryAnchorId: sectionId,
    primaryAnchorLineageId: editionId,
    primaryAnchorKey: `edition#${editionId}#section#${sectionId}`,
    createdByLabel: input.actorLabel?.trim() || "editor",
    messageCount: 0,
    lastMessageId: null,
    lastMessageAt: null,
    metadata: {
      editionId,
      sectionId,
      sectionKey: input.sectionKey || sectionId,
      sectionTitle: input.sectionTitle || null,
      ...(input.metadata ?? {}),
    },
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "messages",
  };
  const response = await runGraphql<{ createMessageThread?: MessageThreadRecord | null }>(
    CREATE_MESSAGE_THREAD_MUTATION,
    { input: thread },
  );
  return { created: true, thread: normalizeThreadRecord(response.createMessageThread ?? thread) };
}

export async function appendForumThreadMessageRecord(input: {
  threadId: string;
  summary: string;
  content: string;
  role?: string;
  authorLabel?: string;
  parentMessageId?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<{ thread: MessageThreadRecord; message: MessageRecord }> {
  const threadId = String(input.threadId || "").trim();
  const summary = String(input.summary || "").trim();
  const content = String(input.content || "").trim();
  if (!threadId) throw new Error("threadId is required");
  if (!summary) throw new Error("summary is required");
  if (!content) throw new Error("content is required");
  const thread = await getMessageThreadRecord(threadId);
  const existing = await listMessagesByThreadId(threadId, 1000);
  const nextSequence = Math.max(0, ...existing.map((message) => Number(message.sequenceNumber || 0))) + 1;
  const now = new Date().toISOString();
  const message: MessageRecord = {
    id: `message-forum-${safeForumId(threadId)}-${String(nextSequence).padStart(4, "0")}`,
    messageKind: "forum_post",
    messageDomain: "edition_coordination",
    status: "active",
    summary,
    source: "newsroom.forum",
    authorLabel: input.authorLabel?.trim() || "editor",
    threadId,
    parentMessageId: input.parentMessageId?.trim() || null,
    sequenceNumber: nextSequence,
    role: input.role || "human",
    messageType: "forum_message",
    content,
    metadata: input.metadata ?? {},
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "messages",
  };
  const created = await runGraphql<{ createMessage?: MessageRecord | null }>(
    CREATE_MESSAGE_MUTATION,
    { input: message },
  );
  const createdMessage = normalizeMessageRecord(created.createMessage ?? message);
  const updated = await runGraphql<{ updateMessageThread?: MessageThreadRecord | null }>(
    UPDATE_MESSAGE_THREAD_MUTATION,
    {
      input: {
        id: threadId,
        messageCount: (thread.messageCount ?? 0) + 1,
        lastMessageId: createdMessage.id,
        lastMessageAt: createdMessage.createdAt,
        updatedAt: now,
      },
    },
  );
  return {
    thread: normalizeThreadRecord(updated.updateMessageThread ?? { ...thread, updatedAt: now }),
    message: createdMessage,
  };
}

export async function deleteForumThreadMessageRecord(input: {
  threadId: string;
  messageId: string;
}): Promise<{ thread: MessageThreadRecord; message: MessageRecord }> {
  const threadId = String(input.threadId || "").trim();
  const messageId = String(input.messageId || "").trim();
  if (!threadId) throw new Error("threadId is required");
  if (!messageId) throw new Error("messageId is required");
  const now = new Date().toISOString();
  const thread = await getMessageThreadRecord(threadId);
  const existing = await listMessagesByThreadId(threadId, 1000);
  const target = existing.find((message) => message.id === messageId);
  if (!target) throw new Error(`Message not found in thread: ${messageId}`);
  const updatedMessage = await runGraphql<{ updateMessage?: MessageRecord | null }>(
    UPDATE_MESSAGE_MUTATION,
    {
      input: {
        id: target.id,
        status: "deleted",
        updatedAt: now,
      },
    },
  );
  const materialized = existing.map((message) => (
    message.id === messageId
      ? { ...message, status: "deleted", updatedAt: now }
      : message
  ));
  const activeMessages = materialized
    .filter((message) => String(message.status || "active") === "active")
    .sort((left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0));
  const lastActive = activeMessages.at(-1) ?? null;
  const updatedThread = await runGraphql<{ updateMessageThread?: MessageThreadRecord | null }>(
    UPDATE_MESSAGE_THREAD_MUTATION,
    {
      input: {
        id: threadId,
        messageCount: activeMessages.length,
        lastMessageId: lastActive?.id ?? null,
        lastMessageAt: lastActive?.createdAt ?? null,
        updatedAt: now,
      },
    },
  );
  return {
    thread: normalizeThreadRecord(updatedThread.updateMessageThread ?? { ...thread, updatedAt: now }),
    message: normalizeMessageRecord(updatedMessage.updateMessage ?? { ...target, status: "deleted", updatedAt: now }),
  };
}

async function getMessageThreadRecord(threadId: string): Promise<MessageThreadRecord> {
  const rows = await Promise.all([
    listMessageThreadsByKind("edition_forum", 500),
    listMessageThreadsByKind("section_forum", 500),
  ]);
  const thread = [...rows[0], ...rows[1]].find((entry) => entry.id === threadId) ?? null;
  if (!thread) throw new Error(`Thread not found: ${threadId}`);
  return thread;
}

async function listMessageThreadsByKind(threadKind: string, limit = 200): Promise<MessageThreadRecord[]> {
  type ThreadConnectionResponse = {
    listMessageThreadsByKindAndUpdatedAt?: {
      items?: Array<MessageThreadRecord | null> | null;
      nextToken?: string | null;
    } | null;
  };
  const records: MessageThreadRecord[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const response: ThreadConnectionResponse = await runGraphql<ThreadConnectionResponse>(LIST_MESSAGE_THREADS_BY_KIND_AND_UPDATED_AT_QUERY, {
      threadKind,
      sortDirection: "DESC",
      limit: Math.max(1, Math.min(limit, 500)),
      nextToken,
    });
    const connection: ThreadConnectionResponse["listMessageThreadsByKindAndUpdatedAt"] = response.listMessageThreadsByKindAndUpdatedAt;
    const items = (connection?.items ?? []).filter(Boolean) as MessageThreadRecord[];
    for (const item of items) records.push(normalizeThreadRecord(item));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return records;
}

async function listMessagesByThreadId(threadId: string, limit = 400): Promise<MessageRecord[]> {
  type MessageConnectionResponse = {
    listMessagesByThreadAndSequence?: {
      items?: Array<MessageRecord | null> | null;
      nextToken?: string | null;
    } | null;
  };
  const records: MessageRecord[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const response: MessageConnectionResponse = await runGraphql<MessageConnectionResponse>(LIST_MESSAGES_BY_THREAD_AND_SEQUENCE_QUERY, {
      threadId,
      sortDirection: "ASC",
      limit: Math.max(1, Math.min(limit, 500)),
      nextToken,
    });
    const connection: MessageConnectionResponse["listMessagesByThreadAndSequence"] = response.listMessagesByThreadAndSequence;
    const items = (connection?.items ?? []).filter(Boolean) as MessageRecord[];
    for (const item of items) records.push(normalizeMessageRecord(item));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  records.sort((left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0));
  return records;
}

function isInsightThreadRootMessage(message: MessageRecord): boolean {
  if (String(message.messageKind || "") !== "insight") return false;
  const threadId = String(message.threadId || "").trim();
  const sequenceNumber = Number(message.sequenceNumber || 0);
  if (threadId && threadId !== message.id && sequenceNumber > 1) return false;
  return true;
}

async function getMessageRecordById(messageId: string): Promise<MessageRecord | null> {
  const normalized = String(messageId || "").trim();
  if (!normalized) return null;
  const response = await runGraphql<{ getMessage?: MessageRecord | null }>(
    GET_MESSAGE_QUERY,
    { id: normalized },
  );
  const message = response.getMessage;
  return message ? normalizeMessageRecord(message) : null;
}

async function loadInsightThreadMessages(threadId: string, root: MessageRecord): Promise<MessageRecord[]> {
  const threadMessages = await listMessagesByThreadId(threadId, 500);
  const byId = new Map<string, MessageRecord>();
  byId.set(root.id, root);
  for (const message of threadMessages) byId.set(message.id, message);
  const merged = [...byId.values()].sort(
    (left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0),
  );
  return hydrateMessageRecordsContent(merged);
}

function insightForumThreadTitle(root: MessageRecord): string {
  const metadata = normalizeJsonValue(root.metadata);
  if (metadata && typeof metadata === "object" && !Array.isArray(metadata)) {
    const explicit = String((metadata as Record<string, unknown>).insightTitle || "").trim();
    if (explicit) return explicit;
  }
  const summary = String(root.summary || "").trim();
  return summary || "Insight";
}

function buildInsightForumThread(root: MessageRecord, messages: MessageRecord[]): ForumThreadWithMessages {
  const activeMessages = messages.filter((message) => String(message.status || "active") === "active");
  const sorted = [...activeMessages].sort(
    (left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0),
  );
  const lastMessage = sorted.at(-1) ?? root;
  const activityAt = lastMessage.updatedAt ?? lastMessage.createdAt ?? root.updatedAt ?? root.createdAt;
  return {
    id: root.id,
    threadKind: "insight_forum",
    status: "active",
    title: insightForumThreadTitle(root),
    summary: formatInsightForumDomainLabel(root.messageDomain),
    primaryAnchorKind: "message",
    primaryAnchorId: root.id,
    primaryAnchorLineageId: root.id,
    primaryAnchorKey: `message#${root.id}`,
    createdByLabel: root.authorLabel ?? null,
    messageCount: sorted.length,
    lastMessageId: lastMessage.id,
    lastMessageAt: activityAt,
    metadata: normalizeJsonValue(root.metadata) as Record<string, unknown>,
    createdAt: root.createdAt,
    updatedAt: activityAt,
    newsroomFeedKey: "messages",
    messages: sorted.length ? sorted : [root],
    scope: "insight",
    sectionKey: root.messageDomain ?? null,
  };
}

function formatInsightForumDomainLabel(domain: string | null | undefined): string {
  const value = String(domain || "").trim();
  if (value === "assignment_work") return "Assignment research";
  if (value === "knowledge") return "Reference knowledge";
  if (!value) return "Insight";
  return value.replace(/_/g, " ");
}

async function hydrateMessageRecordsContent(messages: MessageRecord[]): Promise<MessageRecord[]> {
  return Promise.all(messages.map(async (message) => {
    try {
      const payloads = await loadModelPayloadsForOwner("message", message.id, ["message_body"]);
      const body = payloads
        .find((payload) => payload.attachment.role === "message_body")
        ?.text
        ?.trim();
      if (body) return { ...message, content: body };
    } catch {
      return String(message.content || "").trim() ? message : { ...message, content: "" };
    }
    return String(message.content || "").trim() ? message : { ...message, content: "" };
  }));
}

function normalizeMessageRecord(message: MessageRecord): MessageRecord {
  return {
    ...message,
    metadata: normalizeJsonValue(message.metadata),
  };
}

function normalizeThreadRecord(thread: MessageThreadRecord): MessageThreadRecord {
  return {
    ...thread,
    metadata: normalizeJsonValue(thread.metadata),
  };
}

function metadataString(metadata: unknown, key: string): string | null {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return null;
  const value = (metadata as Record<string, unknown>)[key];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function slugifyKey(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function safeForumId(value: string): string {
  return slugifyKey(value).slice(0, 120) || "thread";
}

async function runGraphql<T extends Record<string, unknown>>(
  query: string,
  variables: Record<string, unknown>,
): Promise<T> {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: T | null; errors?: unknown[] | null }>;
  };
  const response = await client.graphql({
    query,
    variables,
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return (response.data ?? {}) as T;
}

export async function loadEditorReferencesData(): Promise<{
  references: ReferenceRecord[];
  referenceAttachments: ReferenceAttachmentRecord[];
}> {
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.references || testMock?.referenceAttachments) {
    const referenceAttachments = (testMock.referenceAttachments ?? [])
      .slice()
      .sort((left, right) => left.sortKey.localeCompare(right.sortKey));
    if (testMock.references) {
      return {
        references: testMock.references,
        referenceAttachments,
      };
    }
    const referencePage = await loadNewsroomReferencePage();
    return {
      references: referencePage.items,
      referenceAttachments,
    };
  }
  const [referencePage, referenceAttachments] = await Promise.all([
    loadNewsroomReferencePage(),
    listUserPoolModel<ReferenceAttachmentRecord>("ReferenceAttachment"),
  ]);
  return {
    references: referencePage.items,
    referenceAttachments: referenceAttachments.sort((left, right) => left.sortKey.localeCompare(right.sortKey)),
  };
}

export function normalizeNewsroomReferencePageOrder(value?: string | null): NewsroomReferencePageOrder {
  return value?.trim() === "imported" ? "imported" : "published";
}

export async function loadNewsroomReferencePage(options: NewsroomReferencePageOptions = {}): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const order = normalizeNewsroomReferencePageOrder(options.order);
  if (order === "imported") {
    try {
      const importedPage = await loadReferencePageByImportedFeed(options);
      if (importedPage.items.length > 0 || options.nextToken) return importedPage;
    } catch (error) {
      if (!isMissingGraphQLQueryFieldError(error, "listReferencesByNewsroomFeedAndImportedAt")) {
        throw error;
      }
      console.warn(
        "listReferencesByNewsroomFeedAndImportedAt is not deployed in this environment; "
        + "falling back to legacy reference queries with client-side import-date sort.",
      );
    }
    const fallbackPage = await loadReferencePageByFallbackList(options);
    if (fallbackPage.items.length > 0 || options.nextToken) return fallbackPage;
    // Continue into status-index loaders below when the table scan is empty.
  }
  const normalizedStatus = normalizeReferenceStatusKey(options.status);
  if (normalizedStatus) {
    const indexedPage = await loadReferencePageByStatus({
      status: normalizedStatus,
      limit: options.limit,
      nextToken: options.nextToken,
      corpusId: options.corpusId,
    });
    if (indexedPage.items.length > 0 || options.nextToken) return sortReferencePageByOrder(indexedPage, order);
    const legacyPage = await loadReferencePageByLegacyFeed(options);
    if (legacyPage.items.length > 0 || options.nextToken) return sortReferencePageByOrder(legacyPage, order);
    return loadReferencePageByFallbackList(options);
  }
  if (options.excludePending) {
    // Use the curation-status merge, not reviewedFeedKey. The reviewed-feed GSI is only
    // populated for references that went through backfill; treating it as authoritative
    // capped production at ~100 rows while thousands exist in the status indexes.
    const mergedReviewedPage = await loadMergedReferenceStatusPage({
      statuses: ["accepted", "rejected", "archived"],
      limit: options.limit,
      nextToken: options.nextToken,
      corpusId: options.corpusId,
      order,
    });
    if (mergedReviewedPage.items.length > 0 || options.nextToken) return mergedReviewedPage;
    const legacyPage = await loadReferencePageByLegacyFeed(options);
    if (legacyPage.items.length > 0 || options.nextToken) return sortReferencePageByOrder(legacyPage, order);
    return loadReferencePageByFallbackList(options);
  }
  const mergedPage = await loadMergedReferenceStatusPage({
    statuses: REFERENCE_STATUS_KEYS,
    limit: options.limit,
    nextToken: options.nextToken,
    corpusId: options.corpusId,
    order,
  });
  if (mergedPage.items.length > 0 || options.nextToken) return mergedPage;
  const legacyPage = await loadReferencePageByLegacyFeed(options);
  if (legacyPage.items.length > 0 || options.nextToken) return sortReferencePageByOrder(legacyPage, order);
  return loadReferencePageByFallbackList(options);
}

function referencePageMatchesFilters(
  reference: ReferenceRecord,
  options: NewsroomReferencePageOptions,
  normalizedStatus: ReferenceStatus | null,
): boolean {
  if (reference.versionState && reference.versionState !== "current") return false;
  if (options.corpusId && reference.corpusId !== options.corpusId) return false;
  const status = normalizeReferenceStatusKey(reference.curationStatus) ?? "pending";
  if (normalizedStatus) return status === normalizedStatus;
  if (options.excludePending) return status !== "pending";
  return true;
}

async function loadReferencePageByLegacyFeed(options: NewsroomReferencePageOptions): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const normalizedStatus = normalizeReferenceStatusKey(options.status);
  return loadNewsroomFeedPage<ReferenceRecord>({
    query: NEWSROOM_REFERENCE_FEED_QUERY,
    field: "listReferencesByNewsroomFeedAndCreatedAt",
    newsroomFeedKey: "references",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: (reference) => referencePageMatchesFilters(reference, options, normalizedStatus),
  });
}

async function loadReferencePageByImportedFeed(options: NewsroomReferencePageOptions): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const normalizedStatus = normalizeReferenceStatusKey(options.status);
  return loadNewsroomFeedPage<ReferenceRecord>({
    query: NEWSROOM_REFERENCE_IMPORTED_FEED_QUERY,
    field: "listReferencesByNewsroomFeedAndImportedAt",
    newsroomFeedKey: "references",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: (reference) => referencePageMatchesFilters(reference, options, normalizedStatus),
  });
}

async function loadReferencePageByFallbackList(options: NewsroomReferencePageOptions): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<ReferenceRecord>>;
  };
  const limit = Math.max(1, Math.min(options.limit ?? NEWSROOM_PAGE_LIMIT, 200));
  const normalizedStatus = normalizeReferenceStatusKey(options.status);
  const items: ReferenceRecord[] = [];
  let cursor = options.nextToken ?? null;
  let connectionNextToken: string | null = null;
  let pageCount = 0;

  do {
    pageCount += 1;
    let response: GraphQLConnectionResponse<ReferenceRecord>;
    try {
      response = await client.graphql({
        query: LIST_REFERENCES_FALLBACK_QUERY,
        variables: {
          limit,
          nextToken: cursor,
        },
        authMode: USER_POOL_AUTH_MODE,
      });
    } catch (error) {
      throw new Error(normalizeUnknownErrorMessage(error, "Failed to load listReferences fallback"));
    }

    const connection = response.data?.listReferences;
    if (!connection) {
      assertNoGraphQLErrors(response.errors);
      throw new Error("Missing GraphQL connection payload for listReferences fallback.");
    }
    if (response.errors?.length) {
      console.warn("GraphQL returned partial data for listReferences fallback.", response.errors);
    }

    connectionNextToken = connection.nextToken ?? null;
    const pageItems = ((connection.items ?? []).filter(Boolean) as ReferenceRecord[])
      .filter((reference) => {
        if (reference.versionState && reference.versionState !== "current") return false;
        if (options.corpusId && reference.corpusId !== options.corpusId) return false;
        const status = normalizeReferenceStatusKey(reference.curationStatus) ?? "pending";
        if (normalizedStatus) return status === normalizedStatus;
        if (options.excludePending) return status !== "pending";
        return true;
      });
    items.push(...pageItems);
    cursor = connectionNextToken;
  } while (items.length < limit && cursor && pageCount < 40);

  const order = normalizeNewsroomReferencePageOrder(options.order);
  const sorted = sortReferencePageByOrder({
    items,
    nextToken: connectionNextToken,
    hasMore: Boolean(connectionNextToken),
  }, order);
  return {
    ...sorted,
    items: sorted.items.slice(0, limit),
  };
}

export async function loadEditorSemanticRelationsData(): Promise<SemanticRelationRecord[]> {
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.semanticRelations) return testMock.semanticRelations;
  const rows: SemanticRelationRecord[] = [];
  const seenIds = new Set<string>();
  let nextToken: string | null | undefined = null;
  let pageCount = 0;

  do {
    const page = await loadNewsroomSemanticRelationPage({ nextToken });
    for (const relation of page.items) {
      if (!relation?.id || seenIds.has(relation.id)) continue;
      seenIds.add(relation.id);
      rows.push(relation);
    }
    nextToken = page.nextToken;
    pageCount += 1;
  } while (nextToken && pageCount < 40);

  return rows;
}

export async function loadNewsroomSemanticRelationPage(options: NewsroomSemanticRelationPageOptions = {}): Promise<NewsroomRecordPage<SemanticRelationRecord>> {
  return loadNewsroomFeedPage<SemanticRelationRecord>({
    query: NEWSROOM_SEMANTIC_RELATION_FEED_QUERY,
    field: "listSemanticRelationsByNewsroomFeedAndCreatedAt",
    newsroomFeedKey: "semanticRelations",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: equalityMatcher({
      relationTypeKey: options.relationTypeKey,
      relationDomain: options.relationDomain,
    }),
  });
}

export async function loadReferenceCitationRelations(reference: {
  id?: string | null;
  lineageId?: string | null;
}): Promise<{
  incoming: SemanticRelationRecord[];
  outgoing: SemanticRelationRecord[];
}> {
  const referenceKeys = Array.from(new Set([
    String(reference.lineageId || "").trim(),
    String(reference.id || "").trim(),
  ].filter(Boolean)));
  const stateKeys = referenceKeys.map((value) => `reference#${value}#current`);
  const [outgoingPages, incomingPages] = await Promise.all([
    Promise.all(stateKeys.map((stateKey) => loadSemanticRelationsByState({
      field: "listSemanticRelationsBySubjectState",
      keyName: "subjectStateKey",
      keyValue: stateKey,
      query: LIST_SEMANTIC_RELATIONS_BY_SUBJECT_STATE_QUERY,
    }))),
    Promise.all(stateKeys.map((stateKey) => loadSemanticRelationsByState({
      field: "listSemanticRelationsByObjectState",
      keyName: "objectStateKey",
      keyValue: stateKey,
      query: LIST_SEMANTIC_RELATIONS_BY_OBJECT_STATE_QUERY,
    }))),
  ]);
  const outgoing = dedupeSemanticRelationsById(outgoingPages.flat());
  const incoming = dedupeSemanticRelationsById(incomingPages.flat());
  return {
    outgoing: outgoing.filter((relation) => (
      relation.subjectKind === "reference"
      && relation.objectKind === "reference"
      && relationTypeKey(relation) === "cites"
      && relation.relationState === "current"
    )),
    incoming: incoming.filter((relation) => (
      relation.subjectKind === "reference"
      && relation.objectKind === "reference"
      && relationTypeKey(relation) === "cites"
      && relation.relationState === "current"
    )),
  };
}

export async function loadEditorAssignmentsData(): Promise<{
  assignments: AssignmentRecord[];
  assignmentEvents: AssignmentEventRecord[];
}> {
  const [assignmentPage, assignmentEvents] = await Promise.all([
    loadNewsroomAssignmentPage(),
    listOptionalUserPoolModelPage<AssignmentEventRecord>("AssignmentEvent", USER_POOL_PAGE_LIMIT),
  ]);
  return {
    assignments: assignmentPage.items,
    assignmentEvents: assignmentEvents.sort((left, right) => right.createdAt.localeCompare(left.createdAt)),
  };
}

export async function loadEditorOverviewEditionData(): Promise<{
  editions: EditionRecord[];
  editionSlots: EditionSlotRecord[];
  assignments: AssignmentRecord[];
}> {
  const [editions, editionSlots, assignmentState] = await Promise.all([
    listOptionalUserPoolModel<EditionRecord>("Edition"),
    listOptionalUserPoolModel<EditionSlotRecord>("EditionSlot"),
    loadEditorAssignmentsData(),
  ]);
  const sortedEditions = [...editions].sort((left, right) => (
    String(right.editionDate ?? "").localeCompare(String(left.editionDate ?? ""))
    || String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? ""))
    || String(left.id ?? "").localeCompare(String(right.id ?? ""))
  ));
  const sortedEditionSlots = [...editionSlots].sort((left, right) => (
    String(left.editionId ?? "").localeCompare(String(right.editionId ?? ""))
    || String(left.sectionKey ?? "").localeCompare(String(right.sectionKey ?? ""))
    || Number(left.slotRank ?? 0) - Number(right.slotRank ?? 0)
    || String(left.id ?? "").localeCompare(String(right.id ?? ""))
  ));
  return {
    editions: sortedEditions,
    editionSlots: sortedEditionSlots,
    assignments: assignmentState.assignments,
  };
}

export async function loadNewsroomAssignmentPage(options: NewsroomAssignmentPageOptions = {}): Promise<NewsroomRecordPage<AssignmentRecord>> {
  return loadNewsroomFeedPage<AssignmentRecord>({
    query: NEWSROOM_ASSIGNMENT_FEED_QUERY,
    field: "listAssignmentsByNewsroomFeedAndCreatedAt",
    newsroomFeedKey: "assignments",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: equalityMatcher({
      assignmentTypeKey: options.type,
      status: options.status,
    }),
  });
}

export async function loadModelPayloadsForOwner(
  ownerKind: string,
  ownerId: string,
  roles?: string[],
): Promise<HydratedModelPayload[]> {
  const testMock = getTestEditorNewsroomMock();
  const mockPayloads = testMock?.payloads?.[`${ownerKind}:${ownerId}`];
  if (mockPayloads) {
    const allowedRoles = new Set((roles ?? []).filter(Boolean));
    return mockPayloads.filter((payload) => !allowedRoles.size || allowedRoles.has(payload.attachment.role));
  }
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<ModelAttachmentRecord>>;
  };
  const allowedRoles = new Set((roles ?? []).filter(Boolean));
  const attachments: ModelAttachmentRecord[] = [];
  let nextToken: string | null | undefined = null;

  do {
    const response = await client.graphql({
      query: MODEL_ATTACHMENTS_BY_OWNER_QUERY,
      variables: {
        ownerId,
        sortDirection: "ASC",
        limit: USER_POOL_PAGE_LIMIT,
        nextToken,
      },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.listModelAttachmentsByOwnerRoleAndSortKey;
    attachments.push(...((connection?.items ?? []).filter(Boolean) as ModelAttachmentRecord[])
      .filter((attachment) => attachment.ownerKind === ownerKind)
      .filter((attachment) => !allowedRoles.size || allowedRoles.has(attachment.role)));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);

  return Promise.all(attachments.map(hydrateModelAttachment));
}

export async function loadReferenceRecordById(id: string): Promise<ReferenceRecord | null> {
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.references) {
    return testMock.references.find((reference) => reference.id === id || reference.lineageId === id) ?? null;
  }
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{
      data?: { getReference?: ReferenceRecord | null } | null;
      errors?: unknown[] | null;
    }>;
  };
  const response = await client.graphql({
    query: GET_REFERENCE_QUERY,
    variables: { id },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return response.data?.getReference ?? null;
}

function pickPreferredReferenceRecord(references: ReferenceRecord[]): ReferenceRecord | null {
  if (!references.length) return null;
  return references.reduce((best, current) => {
    const currentCurrent = current.versionState === "current" ? 1 : 0;
    const bestCurrent = best.versionState === "current" ? 1 : 0;
    if (currentCurrent !== bestCurrent) return currentCurrent > bestCurrent ? current : best;
    const currentVersion = current.versionNumber ?? 0;
    const bestVersion = best.versionNumber ?? 0;
    if (currentVersion !== bestVersion) return currentVersion > bestVersion ? current : best;
    return (current.updatedAt ?? "").localeCompare(best.updatedAt ?? "") > 0 ? current : best;
  });
}

export async function loadReferenceRecordByLineageId(lineageId: string): Promise<ReferenceRecord | null> {
  const normalized = lineageId.trim();
  if (!normalized) return null;

  const direct = await loadReferenceRecordById(normalized);
  if (direct) return direct;

  if (!/-v\d+$/i.test(normalized)) {
    const versioned = await loadReferenceRecordById(`${normalized}-v1`);
    if (versioned) return versioned;
  }

  const testMock = getTestEditorNewsroomMock();
  if (testMock?.references) {
    const matches = testMock.references.filter(
      (reference) => reference.id === normalized || reference.lineageId === normalized,
    );
    return pickPreferredReferenceRecord(matches);
  }

  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{
      data?: { listReferencesByLineageAndVersion?: { items?: ReferenceRecord[] | null; nextToken?: string | null } | null } | null;
      errors?: unknown[] | null;
    }>;
  };
  const response = await client.graphql({
    query: LIST_REFERENCES_BY_LINEAGE_AND_VERSION_QUERY,
    variables: { lineageId: normalized, limit: 20 },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  const items = (response.data?.listReferencesByLineageAndVersion?.items ?? []).filter(Boolean) as ReferenceRecord[];
  return pickPreferredReferenceRecord(items);
}

export async function loadReferenceAttachmentsForLineageId(referenceLineageId: string): Promise<ReferenceAttachmentRecord[]> {
  if (!referenceLineageId) return [];
  const testMock = getTestEditorNewsroomMock();
  if (testMock?.referenceAttachments) {
    return testMock.referenceAttachments
      .filter((attachment) => attachment.referenceLineageId === referenceLineageId)
      .slice()
      .sort((left, right) => left.sortKey.localeCompare(right.sortKey));
  }
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{
      data?: {
        listReferenceAttachmentsByReferenceLineageAndSortKey?: {
          items?: ReferenceAttachmentRecord[] | null;
          nextToken?: string | null;
        } | null;
      } | null;
      errors?: unknown[] | null;
    }>;
  };
  const attachments: ReferenceAttachmentRecord[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const response = await client.graphql({
      query: LIST_REFERENCE_ATTACHMENTS_BY_REFERENCE_LINEAGE_AND_SORT_KEY_QUERY,
      variables: {
        referenceLineageId,
        sortDirection: "ASC",
        limit: USER_POOL_PAGE_LIMIT,
        nextToken,
      },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.listReferenceAttachmentsByReferenceLineageAndSortKey;
    attachments.push(...((connection?.items ?? []).filter(Boolean) as ReferenceAttachmentRecord[]));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return attachments.sort((left, right) => left.sortKey.localeCompare(right.sortKey));
}

export async function uploadModelPayloadForOwner(input: {
  ownerKind: string;
  ownerId: string;
  ownerLineageId?: string | null;
  ownerVersionNumber?: number | null;
  ownerVersionKey?: string | null;
  role: string;
  sortKey?: string | null;
  filename: string;
  mediaType: string;
  content: string | Blob | ArrayBuffer | Uint8Array;
  importRunId?: string | null;
  status?: string | null;
}): Promise<ModelAttachmentRecord> {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{
      data?: {
        createModelAttachmentUpload?: ModelAttachmentUploadSlot | null;
        completeModelAttachmentUpload?: ModelAttachmentRecord | null;
      } | null;
      errors?: unknown[] | null;
    }>;
  };
  const uploadBody = await normalizeUploadBody(input.content);
  const variables = {
    ownerKind: input.ownerKind,
    ownerId: input.ownerId,
    ownerLineageId: input.ownerLineageId ?? null,
    ownerVersionNumber: input.ownerVersionNumber ?? null,
    ownerVersionKey: input.ownerVersionKey ?? null,
    role: input.role,
    sortKey: input.sortKey ?? input.role,
    filename: input.filename,
    mediaType: input.mediaType,
    byteSize: uploadBody.byteSize,
    sha256: await sha256Hex(uploadBody.body),
    importRunId: input.importRunId ?? null,
    status: input.status ?? "active",
  };
  const slotResponse = await client.graphql({
    query: CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION,
    variables,
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(slotResponse.errors);
  const slot = slotResponse.data?.createModelAttachmentUpload;
  if (!slot?.uploadUrl) throw new Error("Attachment upload slot did not include an upload URL.");
  const uploadResponse = await fetch(slot.uploadUrl, {
    method: slot.method ?? "PUT",
    headers: normalizeUploadHeaders(slot.requiredHeaders),
    body: uploadBody.body,
  });
  if (!uploadResponse.ok) {
    throw new Error(`Attachment upload failed: ${uploadResponse.status} ${uploadResponse.statusText}`);
  }
  const completeResponse = await client.graphql({
    query: COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION,
    variables: { uploadId: slot.uploadId, ...variables },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(completeResponse.errors);
  const attachment = completeResponse.data?.completeModelAttachmentUpload;
  if (!attachment) throw new Error("Attachment upload completed without a ModelAttachment record.");
  return attachment;
}

async function hydrateModelAttachment(attachment: ModelAttachmentRecord): Promise<HydratedModelPayload> {
  try {
    const text = attachment.storagePath?.startsWith("newsroom/payloads/")
      ? await downloadModelAttachmentText(attachment)
      : await downloadStoragePathTextRaw(attachment.storagePath);
    const json = text && isJsonMediaType(attachment.mediaType) ? parseAttachmentJson(text) : null;
    return { attachment, text, json, error: null };
  } catch (error) {
    return {
      attachment,
      text: null,
      json: null,
      error: error instanceof Error ? error.message : "Could not hydrate attachment payload.",
    };
  }
}

export async function loadStoragePathText(path: string | null | undefined): Promise<{ error: string | null; text: string | null }> {
  if (!path) {
    return { error: "Extracted text attachment is missing a storage path.", text: null };
  }
  const testMock = getTestEditorNewsroomMock();
  const mockText = testMock?.storageTextByPath?.[path];
  if (typeof mockText === "string") {
    return { error: null, text: mockText };
  }
  try {
    const text = await downloadStoragePathTextRaw(path);
    return { error: null, text };
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Could not load extracted text.",
      text: null,
    };
  }
}

export async function loadStoragePathUrl(path: string | null | undefined): Promise<{ error: string | null; url: string | null }> {
  if (!path) {
    return { error: "Attachment is missing a storage path.", url: null };
  }
  const testMock = getTestEditorNewsroomMock();
  const mockUrl = testMock?.storageUrlByPath?.[path];
  if (typeof mockUrl === "string" && mockUrl.trim().length > 0) {
    return { error: null, url: mockUrl };
  }
  try {
    configureAmplifyClient();
    const signed = await getUrl({
      path,
      options: { validateObjectExistence: true },
    });
    const url = signed?.url ? signed.url.toString() : null;
    if (!url) {
      return { error: "Could not resolve attachment URL.", url: null };
    }
    return { error: null, url };
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Could not resolve attachment URL.",
      url: null,
    };
  }
}

async function downloadStoragePathTextRaw(path: string | null | undefined): Promise<string | null> {
  if (!path) return null;
  const downloaded = await downloadData({ path }).result;
  const body = downloaded.body as { text?: () => Promise<string> };
  return typeof body.text === "function" ? await body.text() : null;
}

async function downloadModelAttachmentText(attachment: ModelAttachmentRecord): Promise<string | null> {
  if (!attachment.id) return null;
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{
      data?: {
        createModelAttachmentDownload?: {
          downloadUrl?: string | null;
          method?: string | null;
          requiredHeaders?: Record<string, string> | string | null;
        } | null;
      } | null;
      errors?: unknown[] | null;
    }>;
  };
  const response = await client.graphql({
    query: CREATE_MODEL_ATTACHMENT_DOWNLOAD_MUTATION,
    variables: { attachmentId: attachment.id },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  const slot = response.data?.createModelAttachmentDownload;
  const downloadUrl = slot?.downloadUrl;
  if (!downloadUrl) return downloadStoragePathTextRaw(attachment.storagePath);
  const fetchResponse = await fetch(downloadUrl, {
    method: slot?.method ?? "GET",
    headers: normalizeUploadHeaders(slot?.requiredHeaders),
    cache: "no-store",
  });
  if (!fetchResponse.ok) {
    throw new Error(`Attachment download failed: ${fetchResponse.status} ${fetchResponse.statusText}`);
  }
  return fetchResponse.text();
}

async function normalizeUploadBody(content: string | Blob | ArrayBuffer | Uint8Array): Promise<{ body: Blob; byteSize: number }> {
  if (typeof content === "string") {
    const body = new Blob([content]);
    return { body, byteSize: body.size };
  }
  if (content instanceof Blob) return { body: content, byteSize: content.size };
  const body = new Blob([content instanceof Uint8Array ? content.slice() : content]);
  return { body, byteSize: body.size };
}

async function sha256Hex(body: Blob): Promise<string> {
  const bytes = await body.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function normalizeUploadHeaders(value: Record<string, string> | string | null | undefined): Record<string, string> {
  const parsed = typeof value === "string" ? parseAttachmentJson(value) : value;
  const headers: Record<string, string> = {};
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return headers;
  for (const [key, entry] of Object.entries(parsed)) {
    if (entry !== undefined && entry !== null) headers[key] = String(entry);
  }
  return headers;
}

function isJsonMediaType(mediaType: string | null | undefined): boolean {
  const normalized = (mediaType ?? "").toLowerCase();
  return normalized.includes("json") || normalized.endsWith("+json");
}

function parseAttachmentJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function loadNewsroomSemanticNodePage(options: NewsroomSemanticNodePageOptions = {}): Promise<NewsroomRecordPage<SemanticNodeRecord>> {
  return loadNewsroomFeedPage<SemanticNodeRecord>({
    query: NEWSROOM_SEMANTIC_NODE_FEED_QUERY,
    field: "listSemanticNodesByNewsroomFeedAndCreatedAt",
    newsroomFeedKey: "semanticNodes",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: equalityMatcher({
      nodeKind: options.nodeKind,
      status: options.status,
    }),
  });
}

export async function loadEditorDoctrineRecordsData(options?: {
  dashboard?: Pick<CategorySteeringDashboard, "categorys" | "categoryNodes" | "canonicalCategorySetId"> | null;
  doctrineCategories?: DoctrineCategory[];
}): Promise<DoctrineRecord[]> {
  const doctrineCategories = options?.doctrineCategories
    ?? (options?.dashboard
      ? selectAcceptedCategoriesForDoctrine({
        categorys: options.dashboard.categorys,
        categoryNodes: options.dashboard.categoryNodes,
        categorySetId: options.dashboard.canonicalCategorySetId ?? null,
      })
      : []);
  return loadDoctrineRecords(doctrineCategories);
}

export async function loadEditorUserDirectoryData(): Promise<UserDirectoryEntry[]> {
  return loadUserDirectory();
}

export async function runNewsroomKnowledgeQuery(input: Record<string, unknown>): Promise<KnowledgeQueryResponse> {
  const client = generateClient<Schema>();
  const query = client.queries.knowledgeQuery as unknown as (
    args: { input: string },
    options: { authMode: typeof USER_POOL_AUTH_MODE },
  ) => Promise<{ data?: unknown; errors?: unknown[] | null }>;
  const response = await query({ input: JSON.stringify(input) }, { authMode: USER_POOL_AUTH_MODE });
  assertNoGraphQLErrors(response.errors);
  return normalizeKnowledgeQueryResponse(response.data);
}

export function hasTestEditorOverride(): boolean {
  if (typeof window === "undefined") return false;
  const allowOverride = process.env.NODE_ENV === "test"
    || process.env.NEXT_PUBLIC_ENABLE_TEST_EDITOR_OVERRIDE === "true";
  if (!allowOverride) return false;
  return window.localStorage.getItem(TEST_EDITOR_STORAGE_KEY) === "true";
}

type TestEditorNewsroomMock = {
  forumThreadsByEdition?: Record<string, ForumThreadWithMessages[]>;
  insightForumThreads?: ForumThreadWithMessages[];
  messages?: MessageRecord[];
  payloads?: Record<string, HydratedModelPayload[]>;
  referenceAttachments?: ReferenceAttachmentRecord[];
  references?: ReferenceRecord[];
  semanticRelations?: SemanticRelationRecord[];
  storageTextByPath?: Record<string, string>;
  storageUrlByPath?: Record<string, string>;
  summary?: unknown;
};

function getTestEditorNewsroomMock(): TestEditorNewsroomMock | null {
  if (!hasTestEditorOverride() || typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(TEST_EDITOR_NEWSROOM_MOCK_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return parsed as TestEditorNewsroomMock;
  } catch {
    return null;
  }
}

function normalizeKnowledgeQueryResponse(value: unknown): KnowledgeQueryResponse {
  let parsed = value;
  if (typeof parsed === "string") {
    const rawText = parsed;
    try {
      parsed = JSON.parse(parsed);
    } catch {
      return { warnings: ["knowledgeQuery returned non-JSON text"], context: { format: "markdown", text: rawText } };
    }
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { warnings: ["knowledgeQuery returned an empty response"], context: null };
  }
  const record = parsed as KnowledgeQueryResponse;
  return {
    structured: record.structured,
    context: record.context ?? null,
    warnings: Array.isArray(record.warnings) ? record.warnings.filter((warning): warning is string => typeof warning === "string") : [],
    provenance: record.provenance && typeof record.provenance === "object" && !Array.isArray(record.provenance) ? record.provenance as Record<string, unknown> : {},
    debug: record.debug && typeof record.debug === "object" && !Array.isArray(record.debug) ? record.debug as Record<string, unknown> : {},
  };
}

async function loadNewsroomSummary(): Promise<NewsroomSummaryRecord> {
  const client = generateClient<Schema>();
  const response = await (client.queries.getNewsroomSummary as unknown as (
    args: Record<string, never>,
    options: { authMode: typeof USER_POOL_AUTH_MODE },
  ) => Promise<NewsroomSummaryResponse>)({}, { authMode: USER_POOL_AUTH_MODE });
  assertNoGraphQLErrors(response.errors);
  return normalizeNewsroomSummary(response.data);
}

function createSummaryCategorySteeringDashboard(summary: NewsroomSummaryRecord): CategorySteeringDashboard {
  const latestImportRun = summary.latestImportRun;
  return {
    ...createEmptyCategorySteeringDashboard(),
    isPublicSkeleton: false,
    summaryStatus: "ready",
    summary,
    importRuns: latestImportRun ? [latestImportRun] : [],
    loadError: null,
  };
}

function newsroomSummaryIsMissing(summary: NewsroomSummaryRecord | null | undefined): boolean {
  return (summary?.source ?? "").trim().toLowerCase() === "missing";
}

function normalizeNewsroomSummary(value: unknown): NewsroomSummaryRecord {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    generatedAt: typeof record.generatedAt === "string" ? record.generatedAt : new Date().toISOString(),
    staleAt: typeof record.staleAt === "string" ? record.staleAt : null,
    source: typeof record.source === "string" ? record.source : null,
    latestImportRun: normalizeLatestImportRun(record.latestImportRun),
    counts: numberRecord(record.counts),
    facets: normalizeSummaryFacets(record.facets, record),
    assignmentStatusCounts: numberRecord(record.assignmentStatusCounts),
    assignmentTypeCounts: numberRecord(record.assignmentTypeCounts),
    referenceStatusCounts: numberRecord(record.referenceStatusCounts),
    messageKindCounts: numberRecord(record.messageKindCounts),
    messageDomainCounts: numberRecord(record.messageDomainCounts),
  };
}

function normalizeSummaryFacets(value: unknown, legacy: Record<string, unknown>) {
  const parsed = parseJsonish(value);
  const record = parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  return {
    assignments: {
      byStatus: { ...numberRecord(legacy.assignmentStatusCounts), ...sectionCounts(record.assignments, "byStatus") },
      byType: { ...numberRecord(legacy.assignmentTypeCounts), ...sectionCounts(record.assignments, "byType") },
      statusByType: nestedCounts(record.assignments, "statusByType"),
    },
    messages: {
      byKind: { ...numberRecord(legacy.messageKindCounts), ...sectionCounts(record.messages, "byKind") },
      byDomain: { ...numberRecord(legacy.messageDomainCounts), ...sectionCounts(record.messages, "byDomain") },
      byStatus: sectionCounts(record.messages, "byStatus"),
      domainByKind: nestedCounts(record.messages, "domainByKind"),
    },
    references: {
      byCurationStatus: { ...numberRecord(legacy.referenceStatusCounts), ...sectionCounts(record.references, "byCurationStatus") },
      byCorpus: sectionCounts(record.references, "byCorpus"),
      statusByCorpus: nestedCounts(record.references, "statusByCorpus"),
    },
    semanticNodes: {
      byNodeKind: sectionCounts(record.semanticNodes, "byNodeKind"),
      byStatus: sectionCounts(record.semanticNodes, "byStatus"),
      byCorpus: sectionCounts(record.semanticNodes, "byCorpus"),
      byCategorySet: sectionCounts(record.semanticNodes, "byCategorySet"),
    },
    semanticRelations: {
      byRelationTypeKey: sectionCounts(record.semanticRelations, "byRelationTypeKey"),
      byRelationDomain: sectionCounts(record.semanticRelations, "byRelationDomain"),
      bySubjectKind: sectionCounts(record.semanticRelations, "bySubjectKind"),
      byObjectKind: sectionCounts(record.semanticRelations, "byObjectKind"),
    },
    imports: {
      byCorpus: sectionCounts(record.imports, "byCorpus"),
    },
  };
}

function sectionCounts(section: unknown, key: string): Record<string, number> {
  const record = parseJsonish(section);
  return record && typeof record === "object" && !Array.isArray(record)
    ? numberRecord((record as Record<string, unknown>)[key])
    : {};
}

function nestedCounts(section: unknown, key: string): Record<string, Record<string, number>> {
  const record = parseJsonish(section);
  const value = record && typeof record === "object" && !Array.isArray(record) ? (record as Record<string, unknown>)[key] : null;
  const parsed = parseJsonish(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
  const result: Record<string, Record<string, number>> = {};
  for (const [outerKey, inner] of Object.entries(parsed as Record<string, unknown>)) {
    result[outerKey] = numberRecord(inner);
  }
  return result;
}

function normalizeLatestImportRun(value: unknown): CategorySteeringImportRun | null {
  const parsed = parseJsonish(value);
  return parsed && typeof parsed === "object" && typeof (parsed as { id?: unknown }).id === "string"
    ? parsed as CategorySteeringImportRun
    : null;
}

function numberRecord(value: unknown): Record<string, number> {
  const parsed = parseJsonish(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
  const entries = Object.entries(parsed as Record<string, unknown>)
    .map(([key, entry]) => [key, Number(entry)] as const)
    .filter(([, entry]) => Number.isFinite(entry));
  return Object.fromEntries(entries);
}

function parseJsonish(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

async function listUserPoolModel<T>(modelName: string): Promise<T[]> {
  const client = generateClient<Schema>();
  const model = (client.models as Record<string, ListableModel<T>>)[modelName];
  if (!model) throw new Error(`GraphQL model ${modelName} is not available in the deployed schema.`);
  const list = model.list as (input?: Record<string, unknown>, options?: Record<string, unknown>) => Promise<GraphQLListResponse<T>>;

  const items: T[] = [];
  let nextToken: string | null | undefined;
  do {
    const response = await list({
      limit: USER_POOL_LIST_LIMIT,
      nextToken,
    }, {
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    items.push(...((response.data ?? []).filter(Boolean) as T[]));
    nextToken = response.nextToken;
  } while (nextToken);
  return items;
}

async function listOptionalUserPoolModel<T>(modelName: string): Promise<T[]> {
  const client = generateClient<Schema>();
  const model = (client.models as Record<string, ListableModel<T>>)[modelName];
  if (!model) {
    if (modelName === "NewsroomSection") {
      return (await listNewsroomSectionsViaGraphql(client)) as T[];
    }
    return [];
  }
  return listUserPoolModel<T>(modelName);
}

async function listUserPoolModelPage<T>(modelName: string, limit: number): Promise<T[]> {
  const client = generateClient<Schema>();
  const model = (client.models as Record<string, ListableModel<T>>)[modelName];
  if (!model) throw new Error(`GraphQL model ${modelName} is not available in the deployed schema.`);
  const list = model.list as (input?: Record<string, unknown>, options?: Record<string, unknown>) => Promise<GraphQLListResponse<T>>;
  const response = await list({
    limit,
  }, {
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  return (response.data ?? []).filter(Boolean) as T[];
}

async function listOptionalUserPoolModelPage<T>(modelName: string, limit: number): Promise<T[]> {
  const client = generateClient<Schema>();
  const model = (client.models as Record<string, ListableModel<T>>)[modelName];
  if (!model) return [];
  return listUserPoolModelPage<T>(modelName, limit);
}

type ReferenceStatus = (typeof REFERENCE_STATUS_KEYS)[number];

function normalizeReferenceStatusKey(status: unknown): ReferenceStatus | null {
  const normalized = typeof status === "string" ? status.trim().toLowerCase() : "";
  if (!normalized) return null;
  if (normalized === "pending" || normalized === "accepted" || normalized === "rejected" || normalized === "archived") {
    return normalized;
  }
  return null;
}

type MergedReferenceStatusCursor = {
  cursors: Record<ReferenceStatus, string | null | undefined>;
  pendingByStatus: Record<ReferenceStatus, ReferenceRecord[]>;
};

async function loadReferencePageByStatus({
  status,
  limit = NEWSROOM_PAGE_LIMIT,
  nextToken,
  corpusId,
}: {
  status: ReferenceStatus;
  limit?: number;
  nextToken?: string | null;
  corpusId?: string;
}): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const filter = buildReferenceServerFilter(corpusId);
  return runReferenceIndexedQuery({
    query: LIST_REFERENCES_BY_CURATION_STATUS_AND_UPDATED_AT_QUERY,
    field: "listReferencesByCurationStatusAndUpdatedAt",
    keyName: "curationStatus",
    keyValue: status,
    limit,
    nextToken,
    filter,
  });
}

async function loadReferencePageByReviewedFeed({
  limit = NEWSROOM_PAGE_LIMIT,
  nextToken,
  corpusId,
}: {
  limit?: number;
  nextToken?: string | null;
  corpusId?: string;
}): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const filter = buildReferenceServerFilter(corpusId);
  return runReferenceIndexedQuery({
    query: LIST_REFERENCES_BY_REVIEWED_FEED_AND_UPDATED_AT_QUERY,
    field: "listReferencesByReviewedFeedAndUpdatedAt",
    keyName: "reviewedFeedKey",
    keyValue: REFERENCE_REVIEWED_FEED_KEY,
    limit,
    nextToken,
    filter,
  });
}

async function loadMergedReferenceStatusPage({
  statuses,
  limit = NEWSROOM_PAGE_LIMIT,
  nextToken,
  corpusId,
  order = "published",
}: {
  statuses: readonly ReferenceStatus[];
  limit?: number;
  nextToken?: string | null;
  corpusId?: string;
  order?: NewsroomReferencePageOrder;
}): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const cursor = decodeMergedReferenceStatusCursor(nextToken, statuses);
  const output: ReferenceRecord[] = [];
  const emitted = new Set<string>();
  const maxIterations = Math.max(200, limit * 8);
  let iterations = 0;

  while (output.length < limit && iterations < maxIterations) {
    iterations += 1;
    for (const status of statuses) {
      const pending = cursor.pendingByStatus[status];
      if (pending.length > 0) continue;
      const token = cursor.cursors[status];
      if (token === null) continue;
      const page = await loadReferencePageByStatus({
        status,
        limit: Math.max(8, Math.ceil(limit / statuses.length)),
        nextToken: token,
        corpusId,
      });
      pending.push(...page.items);
      cursor.cursors[status] = page.nextToken ?? null;
    }

    const nextStatus = selectNextReferenceStatus(cursor.pendingByStatus, statuses, order);
    if (!nextStatus) break;
    const nextReference = cursor.pendingByStatus[nextStatus].shift();
    if (!nextReference?.id || emitted.has(nextReference.id)) continue;
    emitted.add(nextReference.id);
    output.push(nextReference);
  }

  const hasMore = statuses.some((status) => (
    cursor.pendingByStatus[status].length > 0 || cursor.cursors[status] !== null
  ));
  return {
    items: output,
    nextToken: hasMore ? encodeMergedReferenceStatusCursor(cursor) : null,
    hasMore,
  };
}

function buildReferenceServerFilter(corpusId?: string): Record<string, unknown> {
  const filter: Record<string, unknown> = {
    versionState: { eq: "current" },
    newsroomFeedKey: { eq: "references" },
  };
  if (corpusId) filter.corpusId = { eq: corpusId };
  return filter;
}

async function runReferenceIndexedQuery({
  query,
  field,
  keyName,
  keyValue,
  limit,
  nextToken,
  filter,
}: {
  query: string;
  field: "listReferencesByCurationStatusAndUpdatedAt" | "listReferencesByReviewedFeedAndUpdatedAt";
  keyName: "curationStatus" | "reviewedFeedKey";
  keyValue: string;
  limit: number;
  nextToken?: string | null;
  filter: Record<string, unknown>;
}): Promise<NewsroomRecordPage<ReferenceRecord>> {
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<ReferenceRecord>>;
  };
  let response: GraphQLConnectionResponse<ReferenceRecord>;
  try {
    response = await client.graphql({
      query,
      variables: {
        [keyName]: keyValue,
        sortDirection: "DESC",
        limit,
        nextToken: nextToken ?? null,
        filter,
      },
      authMode: USER_POOL_AUTH_MODE,
    });
  } catch (error) {
    throw new Error(normalizeUnknownErrorMessage(error, `Failed to load ${field}`));
  }
  const connection = response.data?.[field];
  if (!connection) {
    assertNoGraphQLErrors(response.errors);
    throw new Error(`Missing GraphQL connection payload for ${field}.`);
  }
  if (response.errors?.length) {
    console.warn(`GraphQL returned partial data for ${field}.`, response.errors);
  }
  return {
    items: ((connection.items ?? []).filter(Boolean) as ReferenceRecord[]),
    nextToken: connection.nextToken ?? null,
    hasMore: Boolean(connection.nextToken),
  };
}

function selectNextReferenceStatus(
  pendingByStatus: Record<ReferenceStatus, ReferenceRecord[]>,
  statuses: readonly ReferenceStatus[],
  order: NewsroomReferencePageOrder = "published",
): ReferenceStatus | null {
  let selected: ReferenceStatus | null = null;
  for (const status of statuses) {
    const queue = pendingByStatus[status];
    const candidate = queue[0];
    if (!candidate) continue;
    if (!selected) {
      selected = status;
      continue;
    }
    const current = pendingByStatus[selected][0];
    if (!current || compareReferencesForPageOrder(candidate, current, order) < 0) selected = status;
  }
  return selected;
}

function compareReferencesForPageOrder(
  left: ReferenceRecord,
  right: ReferenceRecord,
  order: NewsroomReferencePageOrder,
): number {
  if (order === "imported") return compareReferencesByImportedAt(left, right);
  return compareReferencesByPublicationDate(left, right);
}

function compareReferencesByRecency(left: ReferenceRecord, right: ReferenceRecord): number {
  const leftTs = Date.parse(referenceRecencyTimestamp(left));
  const rightTs = Date.parse(referenceRecencyTimestamp(right));
  const leftRank = Number.isFinite(leftTs) ? leftTs : 0;
  const rightRank = Number.isFinite(rightTs) ? rightTs : 0;
  if (leftRank !== rightRank) return rightRank - leftRank;
  return String(right.id).localeCompare(String(left.id));
}

function compareReferencesByImportedAt(left: ReferenceRecord, right: ReferenceRecord): number {
  const leftTs = Date.parse(referenceImportedTimestamp(left));
  const rightTs = Date.parse(referenceImportedTimestamp(right));
  const leftRank = Number.isFinite(leftTs) ? leftTs : 0;
  const rightRank = Number.isFinite(rightTs) ? rightTs : 0;
  if (leftRank !== rightRank) return rightRank - leftRank;
  return String(right.id).localeCompare(String(left.id));
}

function compareReferencesByPublicationDate(left: ReferenceRecord, right: ReferenceRecord): number {
  const leftTs = Date.parse(referencePublicationTimestamp(left));
  const rightTs = Date.parse(referencePublicationTimestamp(right));
  const leftRank = Number.isFinite(leftTs) ? leftTs : 0;
  const rightRank = Number.isFinite(rightTs) ? rightTs : 0;
  if (leftRank !== rightRank) return rightRank - leftRank;
  return String(right.id).localeCompare(String(left.id));
}

function sortReferencePageByOrder(
  page: NewsroomRecordPage<ReferenceRecord>,
  order: NewsroomReferencePageOrder,
): NewsroomRecordPage<ReferenceRecord> {
  const compare = order === "imported" ? compareReferencesByImportedAt : compareReferencesByPublicationDate;
  return {
    ...page,
    items: [...page.items].sort(compare),
  };
}

function referenceRecencyTimestamp(reference: ReferenceRecord): string {
  return reference.updatedAt
    || reference.curationStatusUpdatedAt
    || reference.importedAt
    || reference.createdAt
    || "";
}

function referenceImportedTimestamp(reference: ReferenceRecord): string {
  return reference.importedAt
    || reference.createdAt
    || "";
}

function referencePublicationTimestamp(reference: ReferenceRecord): string {
  return reference.sourcePublishedAt
    || reference.sourceUpdatedAt
    || reference.retrievedAt
    || reference.importedAt
    || reference.updatedAt
    || "";
}

function encodeMergedReferenceStatusCursor(cursor: MergedReferenceStatusCursor): string {
  const payload = JSON.stringify({ v: 1, ...cursor });
  return `ref-status-merge:${encodeURIComponent(payload)}`;
}

function decodeMergedReferenceStatusCursor(
  token: string | null | undefined,
  statuses: readonly ReferenceStatus[],
): MergedReferenceStatusCursor {
  const empty = buildEmptyMergedReferenceStatusCursor(statuses);
  if (!token) return empty;
  if (!token.startsWith("ref-status-merge:")) return empty;
  try {
    const parsed = JSON.parse(decodeURIComponent(token.slice("ref-status-merge:".length))) as {
      v?: number;
      cursors?: Record<string, unknown>;
      pendingByStatus?: Record<string, unknown>;
    };
    if (parsed.v !== 1) return empty;
    const next: MergedReferenceStatusCursor = buildEmptyMergedReferenceStatusCursor(statuses);
    for (const status of statuses) {
      const rawCursor = parsed.cursors?.[status];
      next.cursors[status] = typeof rawCursor === "string" ? rawCursor : rawCursor === null ? null : undefined;
      const rawRows = parsed.pendingByStatus?.[status];
      next.pendingByStatus[status] = Array.isArray(rawRows)
        ? (rawRows.filter((row): row is ReferenceRecord => Boolean(row && typeof row === "object")) as ReferenceRecord[])
        : [];
    }
    return next;
  } catch {
    return empty;
  }
}

function buildEmptyMergedReferenceStatusCursor(statuses: readonly ReferenceStatus[]): MergedReferenceStatusCursor {
  const cursors = {} as Record<ReferenceStatus, string | null | undefined>;
  const pendingByStatus = {} as Record<ReferenceStatus, ReferenceRecord[]>;
  for (const status of statuses) {
    cursors[status] = undefined;
    pendingByStatus[status] = [];
  }
  return { cursors, pendingByStatus };
}

async function loadNewsroomFeedPage<T>({
  query,
  field,
  newsroomFeedKey,
  matches,
  limit = NEWSROOM_PAGE_LIMIT,
  nextToken,
}: {
  query: string;
  field: string;
  newsroomFeedKey: string;
  matches?: ((item: T) => boolean) | null;
  limit?: number;
  nextToken?: string | null;
}): Promise<NewsroomRecordPage<T>> {
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<T>>;
  };
  const items: T[] = [];
  let cursor = nextToken ?? null;
  let pageCount = 0;
  let connectionNextToken: string | null = null;

  do {
    pageCount += 1;
    let response: GraphQLConnectionResponse<T>;
    try {
      response = await client.graphql({
        query,
        variables: {
          newsroomFeedKey,
          sortDirection: "DESC",
          limit,
          nextToken: cursor,
          filter: null,
        },
        authMode: USER_POOL_AUTH_MODE,
      });
    } catch (error) {
      throw new Error(normalizeUnknownErrorMessage(error, `Failed to load ${field}`));
    }
    const connection = response.data?.[field];
    if (!connection) {
      if (isMissingGraphQLQueryFieldError(response.errors, field)) {
        throw new Error(
          `Validation error of type FieldUndefined: Field '${field}' in type 'Query' is undefined @ '${field}'`,
        );
      }
      assertNoGraphQLErrors(response.errors);
      throw new Error(`Missing GraphQL connection payload for ${field}.`);
    }
    if (response.errors?.length) {
      // Preserve list rendering when AppSync returns partial data and per-row errors.
      console.warn(`GraphQL returned partial data for ${field}.`, response.errors);
    }
    connectionNextToken = connection?.nextToken ?? null;
    const pageItems = ((connection?.items ?? []).filter(Boolean) as T[])
      .filter((item) => matches ? matches(item) : true);
    items.push(...pageItems);
    cursor = connectionNextToken;
  } while (items.length < limit && cursor && pageCount < 10);

  return {
    items: items.slice(0, limit),
    nextToken: connectionNextToken,
    hasMore: Boolean(connectionNextToken),
  };
}

async function loadSemanticRelationsByState({
  field,
  keyName,
  keyValue,
  query,
}: {
  field: "listSemanticRelationsByObjectState" | "listSemanticRelationsBySubjectState";
  keyName: "objectStateKey" | "subjectStateKey";
  keyValue: string;
  query: string;
}): Promise<SemanticRelationRecord[]> {
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<SemanticRelationRecord>>;
  };
  const rows: SemanticRelationRecord[] = [];
  const seenIds = new Set<string>();
  let nextToken: string | null = null;
  let pageCount = 0;
  do {
    pageCount += 1;
    const response = await client.graphql({
      query,
      variables: {
        [keyName]: keyValue,
        sortDirection: "DESC",
        limit: 200,
        nextToken,
        filter: null,
      },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.[field];
    if (!connection) break;
    for (const item of (connection.items ?? []).filter(Boolean) as SemanticRelationRecord[]) {
      if (!item.id || seenIds.has(item.id)) continue;
      seenIds.add(item.id);
      rows.push(item);
    }
    nextToken = connection.nextToken ?? null;
  } while (nextToken && pageCount < 200);
  return rows;
}

function dedupeSemanticRelationsById(relations: SemanticRelationRecord[]): SemanticRelationRecord[] {
  const seen = new Set<string>();
  const deduped: SemanticRelationRecord[] = [];
  for (const relation of relations) {
    if (!relation.id || seen.has(relation.id)) continue;
    seen.add(relation.id);
    deduped.push(relation);
  }
  return deduped;
}

async function listNewsroomSectionsViaGraphql(client: ReturnType<typeof generateClient<Schema>>): Promise<NewsroomSectionRecord[]> {
  const graphClient = client as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<NewsroomSectionRecord>>;
  };
  const rows: NewsroomSectionRecord[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const response = await graphClient.graphql({
      query: NEWSROOM_SECTION_LIST_QUERY,
      variables: { limit: USER_POOL_LIST_LIMIT, nextToken },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.listNewsroomSections;
    rows.push(...((connection?.items ?? []).filter(Boolean) as NewsroomSectionRecord[]));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return rows;
}

async function listSteeringProposalsViaGraphql(): Promise<CategorySteeringProposal[]> {
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<CategorySteeringProposal>>;
  };
  const rows: CategorySteeringProposal[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const response = await client.graphql({
      query: LIST_STEERING_PROPOSALS_QUERY,
      variables: { limit: USER_POOL_LIST_LIMIT, nextToken },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.listSteeringProposals;
    rows.push(...((connection?.items ?? []).filter(Boolean) as CategorySteeringProposal[]));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return rows;
}

function equalityMatcher<T extends Record<string, unknown>>(values: Record<string, string | null | undefined>): ((item: T) => boolean) | null {
  const entries = Object.entries(values)
    .map(([key, value]) => [key, typeof value === "string" ? value.trim() : ""] as const)
    .filter((entry): entry is readonly [string, string] => Boolean(entry[1]));
  if (!entries.length) return null;
  return (item: T) => entries.every(([key, value]) => item[key] === value);
}

export function selectRootDeskCategoriesForDoctrine({
  categorys,
  categoryNodes,
  categorySetId,
}: {
  categorys: CategorySteeringCategory[];
  categoryNodes: CategorySteeringCategoryTreeNode[];
  categorySetId: string | null;
}): CategorySteeringCategory[] {
  const categorySetFilter = (category: { categorySetId: string }) => !categorySetId || category.categorySetId === categorySetId;
  const currentCategorys = categorys.filter((category) => (
    categorySetFilter(category)
    && category.status !== "deprecated"
    && category.versionState !== "superseded"
  ));
  const categoryByKey = new Map(currentCategorys.map((category) => [category.categoryKey, category]));
  const rootNodes = categoryNodes
    .filter((node) => (
      categorySetFilter(node)
      && node.status === "accepted"
      && node.versionState !== "superseded"
      && !node.parentCategoryKey
    ))
    .sort((left, right) => categorySortKey(left).localeCompare(categorySortKey(right)));

  if (rootNodes.length) {
    return rootNodes.map((node) => mergeRootNodeWithCategory(node, categoryByKey.get(node.categoryKey)));
  }

  return currentCategorys
    .filter((category) => category.status === "accepted" && category.versionState !== "superseded" && !category.parentCategoryKey)
    .sort((left, right) => categorySortKey(left).localeCompare(categorySortKey(right)));
}

export function selectAcceptedCategoriesForDoctrine({
  categorys,
  categoryNodes,
  categorySetId,
}: {
  categorys: CategorySteeringCategory[];
  categoryNodes: CategorySteeringCategoryTreeNode[];
  categorySetId: string | null;
}): DoctrineCategory[] {
  const categorySetFilter = (category: { categorySetId: string }) => !categorySetId || category.categorySetId === categorySetId;
  const currentCategorys = categorys.filter((category) => (
    categorySetFilter(category)
    && category.status !== "deprecated"
    && category.versionState !== "superseded"
  ));
  const categoryByKey = new Map(currentCategorys.map((category) => [category.categoryKey, category]));
  return categoryNodes
    .filter((node) => (
      categorySetFilter(node)
      && node.status === "accepted"
      && node.versionState !== "superseded"
    ))
    .sort((left, right) => categorySortKey(left).localeCompare(categorySortKey(right)))
    .map((node) => mergeRootNodeWithCategory(node, categoryByKey.get(node.categoryKey)));
}

async function loadDoctrineRecords(doctrineCategories: DoctrineCategory[] = []): Promise<DoctrineRecord[]> {
  const definitions = uniqueDoctrineDefinitions([
    ...DOCTRINE_DEFINITIONS,
    ...doctrineCategories.flatMap((category) => getCategoryDoctrineDefinitions(category)),
  ]);
  const records = await Promise.all(
    definitions.map((definition) => getDoctrineRecordBySlug(definition.slug)),
  );
  return records.filter((record): record is DoctrineRecord => record !== null);
}

async function getDoctrineRecordBySlug(slug: string): Promise<DoctrineRecord | null> {
  const client = generateClient<Schema>();
  const model = client.models.Item as unknown as SlugQueryableModel<DoctrineRecord>;
  if (typeof model.itemBySlug !== "function") {
    throw new Error("GraphQL Item.itemBySlug is not available in the deployed schema.");
  }

  const records: DoctrineRecord[] = [];
  let nextToken: string | null | undefined;
  do {
    const response = await model.itemBySlug(
      { slug },
      {
        authMode: USER_POOL_AUTH_MODE,
        limit: 100,
        nextToken,
      },
    );
    assertNoGraphQLErrors(response.errors);
    records.push(...((response.data ?? []).filter(Boolean) as DoctrineRecord[]));
    nextToken = response.nextToken;
  } while (nextToken);

  const doctrine = records.find((record) => record.type === "doctrine") ?? records[0] ?? null;
  return doctrine;
}

function uniqueDoctrineDefinitions(definitions: typeof DOCTRINE_DEFINITIONS): typeof DOCTRINE_DEFINITIONS {
  const bySlug = new Map<string, (typeof DOCTRINE_DEFINITIONS)[number]>();
  for (const definition of definitions) bySlug.set(definition.slug, definition);
  return Array.from(bySlug.values());
}

function mergeRootNodeWithCategory(
  node: CategorySteeringCategoryTreeNode,
  category?: CategorySteeringCategory,
): CategorySteeringCategory {
  return {
    ...node,
    ...category,
    id: category?.id ?? node.id,
    lineageId: category?.lineageId ?? node.lineageId ?? category?.id ?? node.id,
    versionNumber: category?.versionNumber ?? node.versionNumber,
    previousVersionId: category?.previousVersionId ?? node.previousVersionId,
    versionState: category?.versionState ?? node.versionState,
    versionCreatedAt: category?.versionCreatedAt ?? node.versionCreatedAt,
    versionCreatedBy: category?.versionCreatedBy ?? node.versionCreatedBy,
    changeReason: category?.changeReason ?? node.changeReason,
    contentHash: category?.contentHash ?? node.contentHash,
    categorySetId: category?.categorySetId ?? node.categorySetId,
    corpusId: category?.corpusId ?? node.corpusId,
    categoryKey: node.categoryKey,
    parentCategoryId: null,
    parentCategoryKey: null,
    displayName: category?.displayName ?? node.displayName,
    shortTitle: category?.shortTitle ?? node.shortTitle,
    subtitle: category?.subtitle ?? node.subtitle,
    description: category?.description ?? node.description,
    aliases: category?.aliases ?? node.aliases,
    status: category?.status ?? node.status,
    seedItemIds: category?.seedItemIds ?? node.seedItemIds,
    holdoutItemIds: category?.holdoutItemIds ?? node.holdoutItemIds,
    rank: category?.rank ?? node.rank,
    depth: 0,
    isPinned: category?.isPinned ?? node.isPinned,
    importRunId: category?.importRunId ?? node.importRunId,
    updatedAt: category?.updatedAt ?? node.updatedAt,
  };
}

function categorySortKey(category: Pick<CategorySteeringCategory, "rank" | "categoryKey">): string {
  return `${String(category.rank ?? 999999).padStart(6, "0")}#${category.categoryKey}`;
}

async function loadUserDirectory(): Promise<UserDirectoryEntry[]> {
  const client = generateClient<Schema>();
  const response = await client.queries.listUserDirectory({ authMode: USER_POOL_AUTH_MODE });
  assertNoGraphQLErrors(response.errors);
  return ((response.data?.entries ?? []).filter(Boolean) as UserDirectoryEntry[])
    .sort((left, right) => (left.displayName ?? left.email ?? left.userSub ?? "").localeCompare(right.displayName ?? right.email ?? right.userSub ?? ""));
}

function appendixFromCategoryTree(categoryTree: CategorySteeringCategoryTree, nodes: CategorySteeringCategoryTreeNode[]): NewsDeskAppendix {
  return {
    categorySetId: categoryTree.id,
    corpusId: categoryTree.corpusId,
    displayName: categoryTree.displayName,
    description: categoryTree.description,
    generatedAt: categoryTree.generatedAt,
    nodes: nodes
      .filter((node) => node.categorySetId === categoryTree.id)
      .map((node) => ({
        id: node.id,
        categorySetId: node.categorySetId,
        categoryKey: node.categoryKey,
        parentCategoryKey: node.parentCategoryKey,
        displayName: node.displayName,
        shortTitle: node.shortTitle,
        subtitle: node.subtitle,
        description: node.description,
        status: node.status,
        seedItemIds: node.seedItemIds,
        holdoutItemIds: node.holdoutItemIds,
        rank: node.rank,
        depth: node.depth,
      })),
  };
}

function categoryTreeFromAppendix(appendix: NewsDeskAppendix): CategorySteeringCategoryTree {
  const roots = appendix.nodes.filter((node) => node.status === "accepted" && !node.parentCategoryKey);
  return {
    id: appendix.categorySetId,
    corpusId: appendix.corpusId,
    classifierId: "scenario",
    displayName: appendix.displayName,
    description: appendix.description,
    status: "accepted",
    generatedAt: appendix.generatedAt,
    nodeCount: appendix.nodes.length,
    rootCount: roots.length,
  };
}

function categoryTreeNodeFromAppendixNode(node: NewsDeskCategoryTreeNode): CategorySteeringCategoryTreeNode {
  return {
    id: node.id,
    categorySetId: node.categorySetId,
    corpusId: "",
    categoryKey: node.categoryKey,
    parentCategoryKey: node.parentCategoryKey,
    displayName: node.displayName,
    shortTitle: node.shortTitle,
    subtitle: node.subtitle,
    description: node.description,
    status: node.status,
    seedItemIds: node.seedItemIds,
    holdoutItemIds: node.holdoutItemIds,
    rank: node.rank,
    depth: node.depth,
  };
}

function selectCurrentAcceptedCategoryTree(categoryTrees: CategorySteeringCategoryTree[]): CategorySteeringCategoryTree | null {
  return categoryTrees.find(isCurrentAcceptedCategorySet) ?? null;
}

function selectCanonicalCategorySet(corpora: CategorySteeringCorpus[], categorySets: CategorySteeringCategorySet[]): CategorySteeringCategorySet | null {
  const canonicalCorpus = selectCanonicalCorpus(corpora);
  const candidates = categorySets.filter(isCurrentAcceptedCategorySet);
  const canonicalCandidates = canonicalCorpus ? candidates.filter((categorySet) => categorySet.corpusId === canonicalCorpus.id) : candidates;
  return canonicalCandidates[0] ?? candidates[0] ?? null;
}

function isCurrentAcceptedCategorySet(categorySet: CategorySteeringCategorySet | CategorySteeringCategoryTree): boolean {
  return categorySet.versionState === "current" && categorySet.status === "accepted";
}

function selectCanonicalCorpus(corpora: CategorySteeringCorpus[]): CategorySteeringCorpus | null {
  return corpora.find((corpus) => corpus.role === "canonical")
    ?? corpora.find((corpus) => corpus.role === "authority")
    ?? corpora[0]
    ?? null;
}

function sortCategorySets(categorySets: CategorySteeringCategorySet[], importRuns: CategorySteeringImportRun[]): CategorySteeringCategorySet[] {
  const importRunById = new Map(importRuns.map((importRun) => [importRun.id, importRun]));
  return [...categorySets].sort((left, right) => {
    const statusDiff = categorySetStatusRank(left.status) - categorySetStatusRank(right.status);
    if (statusDiff !== 0) return statusDiff;
    const dateDiff = categorySetSortDate(right, importRunById).localeCompare(categorySetSortDate(left, importRunById));
    if (dateDiff !== 0) return dateDiff;
    return left.displayName.localeCompare(right.displayName);
  });
}

function categorySetSortDate(categorySet: CategorySteeringCategorySet, importRunById: Map<string, CategorySteeringImportRun>): string {
  return categorySet.generatedAt ?? (categorySet.importRunId ? importRunById.get(categorySet.importRunId)?.importedAt : null) ?? "";
}

function categorySetStatusRank(status: string): number {
  if (status === "accepted") return 0;
  if (status === "draft") return 1;
  if (status === "proposed") return 2;
  if (status === "deprecated") return 8;
  return 5;
}

function sortCategorys(categorys: CategorySteeringCategory[]): CategorySteeringCategory[] {
  return [...categorys].sort((left, right) => {
    const rankDiff = (left.rank ?? 999999) - (right.rank ?? 999999);
    if (rankDiff !== 0) return rankDiff;
    return left.categoryKey.localeCompare(right.categoryKey);
  });
}

function normalizeNewsroomSectionType(value: string | null | undefined): "canonical" | "floating" {
  return value === "floating" || value === "rotating" ? "floating" : "canonical";
}

function sortNewsroomSections(sections: NewsroomSectionRecord[]): NewsroomSectionRecord[] {
  return [...sections]
    .map((section) => ({ ...section, type: normalizeNewsroomSectionType(section.type) }))
    .sort((left, right) => {
      const typeDiff = (left.type === "canonical" ? 0 : 1) - (right.type === "canonical" ? 0 : 1);
      if (typeDiff !== 0) return typeDiff;
      const sortDiff = (left.sortOrder ?? 999999) - (right.sortOrder ?? 999999);
      if (sortDiff !== 0) return sortDiff;
      return left.title.localeCompare(right.title);
    });
}

function sortProposals(proposals: CategorySteeringProposal[]): CategorySteeringProposal[] {
  const statusWeight = new Map([
    ["proposed", 0],
    ["deferred", 1],
    ["accepted", 2],
    ["rejected", 3],
  ]);
  return [...proposals].sort((left, right) => {
    const statusDiff = (statusWeight.get(left.status) ?? 9) - (statusWeight.get(right.status) ?? 9);
    if (statusDiff !== 0) return statusDiff;
    return (right.proposedAt ?? right.updatedAt ?? "").localeCompare(left.proposedAt ?? left.updatedAt ?? "");
  });
}


function keywordSortKey(keyword: CategoryKeywordRecord): string {
  return `${keyword.categorySetId}#${keyword.categoryKey}#${String(keyword.rank ?? 999999).padStart(6, "0")}#${keyword.normalizedKeyword}`;
}

function lexicalRuleSortKey(rule: LexicalSteeringRuleRecord): string {
  return `${rule.status === "active" ? "0" : "1"}#${rule.scope}#${rule.normalizedTerm}#${rule.id}`;
}

function assignmentSortKey(assignment: AssignmentRecord): string {
  return `${String(assignment.priority ?? 999999).padStart(6, "0")}#${assignment.createdAt}#${assignment.id}`;
}

function sortTaxonomies(categoryTrees: CategorySteeringCategoryTree[]): CategorySteeringCategoryTree[] {
  return [...categoryTrees].sort((left, right) => {
    const statusDiff = categoryTreeStatusRank(left.status) - categoryTreeStatusRank(right.status);
    if (statusDiff !== 0) return statusDiff;
    const dateDiff = categoryTreeDate(right).localeCompare(categoryTreeDate(left));
    if (dateDiff !== 0) return dateDiff;
    return left.displayName.localeCompare(right.displayName);
  });
}

function sortCategoryTreeNodes(nodes: CategorySteeringCategoryTreeNode[]): CategorySteeringCategoryTreeNode[] {
  return [...nodes].sort((left, right) => {
    const depthDiff = (left.depth ?? 0) - (right.depth ?? 0);
    if (depthDiff !== 0) return depthDiff;
    const rankDiff = (left.rank ?? 999999) - (right.rank ?? 999999);
    if (rankDiff !== 0) return rankDiff;
    return left.categoryKey.localeCompare(right.categoryKey);
  });
}

function categoryTreeStatusRank(status: string): number {
  if (status === "accepted") return 0;
  if (status === "draft") return 1;
  if (status === "proposed") return 2;
  if (status === "deprecated") return 8;
  return 5;
}

function categoryTreeDate(categoryTree: CategorySteeringCategoryTree): string {
  return categoryTree.generatedAt ?? categoryTree.updatedAt ?? categoryTree.createdAt ?? "";
}

function normalizeJsonValue(value: unknown): Record<string, any> | null {
  if (!value) return null;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, any> : null;
    } catch {
      return null;
    }
  }
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, any>;
  return null;
}

function assertNoGraphQLErrors(errors?: unknown[] | null) {
  if (!errors?.length) return;
  const details = errors
    .map((error) => {
      if (error && typeof error === "object" && "message" in error) return String((error as { message?: unknown }).message);
      return String(error);
    })
    .join("; ");
  throw new Error(details);
}

function isMissingGraphQLQueryFieldError(error: unknown, fieldName: string): boolean {
  if (Array.isArray(error)) {
    return error.some((entry) => isMissingGraphQLQueryFieldError(entry, fieldName));
  }
  const message = normalizeUnknownErrorMessage(error, "");
  return message.includes("FieldUndefined") && message.includes(fieldName);
}

function normalizeUnknownErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  if (!error || typeof error !== "object") return fallback;
  const record = error as Record<string, unknown>;
  const directMessage = typeof record.message === "string" ? record.message.trim() : "";
  if (directMessage) return directMessage;
  const errors = Array.isArray(record.errors) ? record.errors : [];
  const nestedMessages = errors
    .map((entry) => {
      if (!entry || typeof entry !== "object") return "";
      const message = (entry as { message?: unknown }).message;
      return typeof message === "string" ? message.trim() : "";
    })
    .filter(Boolean);
  if (nestedMessages.length) return nestedMessages.join("; ");
  try {
    return JSON.stringify(error);
  } catch {
    return fallback;
  }
}
