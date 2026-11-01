"use client";

import { loadReferenceReviewDetails } from "../lib/reference-review-details";
import { loadAllPages } from "../lib/newsroom-all-pages";
import { hasEditorRights } from "../lib/staff-groups";

import { isEditorialWorkAssignment } from "../lib/newsroom-assignments";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { createLocalPreviewRealPublishedVersions, createLocalPreviewAssignments, createLocalPreviewContentItemVersions, createLocalPreviewReferences } from "../lib/local-preview-seed";
import { generateClient } from "aws-amplify/data";
import { testEditorOverrideAllowed } from "../lib/test-editor-override";
import { downloadData, getUrl } from "aws-amplify/storage";
import { fetchAuthSession } from "aws-amplify/auth";
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
import { relationTypeKey, semanticStateKey, semanticVersionKey } from "../lib/semantic-graph";
import {
  CONVERSATION_FEED_KEY,
  GENERAL_CONVERSATION_KIND,
  REFERENCE_CONVERSATION_KIND,
  conversationAnchorKey,
  conversationPreviewLine,
  threadMetadataWithLastAuthor,
  conversationMessageId,
  conversationThreadId,
  conversationThreadKind,
  createWithSequenceRetry,
  findOrCreateThread,
  type ConversationAnchor,
  type ConversationMessage,
  type ConversationViewer,
} from "../lib/conversation";
import { LINK_MESSAGE_HASHTAGS_MUTATION, messageHasHashtag, postMessageArguments, postMessageMutation } from "../lib/post-message";
import { legacyStageKeysToLoad, type ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import { getContentItemStageDefinitions } from "../lib/site-brand";
import { DOCTRINE_DEFINITIONS, getCategoryDoctrineDefinitions, type DoctrineCategory } from "../lib/doctrine";
import { configureAmplifyClient } from "./amplify-client-provider";
import { isUnauthenticatedError, loadReaderSessionSnapshot, type ReaderAuthSnapshot } from "./reader-auth-state";
import { resolveReaderSettings } from "./reader-settings";

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
      items { id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel editedAt deletedAt deletedBySub threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey }
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

const LIST_MESSAGE_THREADS_BY_ANCHOR_AND_UPDATED_AT_QUERY = `
  query ListMessageThreadsByAnchorAndUpdatedAt($primaryAnchorKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listMessageThreadsByAnchorAndUpdatedAt(primaryAnchorKey: $primaryAnchorKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items {
        id threadKind status title summary primaryAnchorKind primaryAnchorId primaryAnchorLineageId primaryAnchorKey createdBySub createdByUserProfileId createdByLabel messageCount lastMessageId lastMessageAt contextDigest activeResponseMessageId responseLockOwner responseLockExpiresAt metadata createdAt updatedAt newsroomFeedKey
      }
      nextToken
    }
  }
`;

const CREATE_SEMANTIC_RELATION_MUTATION = `
  mutation CreateSemanticRelation($input: CreateSemanticRelationInput!) {
    createSemanticRelation(input: $input) { id }
  }
`;

const LIST_MESSAGES_BY_THREAD_AND_SEQUENCE_QUERY = `
  query ListMessagesByThreadAndSequence($threadId: ID!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listMessagesByThreadAndSequence(threadId: $threadId, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items { id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel editedAt deletedAt deletedBySub threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey }
      nextToken
    }
  }
`;

const LIST_MESSAGES_BY_KIND_AND_CREATED_AT_QUERY = `
  query ListMessagesByKindAndCreatedAt($messageKind: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listMessagesByKindAndCreatedAt(messageKind: $messageKind, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items { id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel editedAt deletedAt deletedBySub threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey }
      nextToken
    }
  }
`;

const GET_MESSAGE_QUERY = `
  query GetMessage($id: ID!) {
    getMessage(id: $id) {
      id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel editedAt deletedAt deletedBySub threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey
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

const POST_MESSAGE_SELECTION = "id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel editedAt deletedAt deletedBySub threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey";

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
      editedAt
      deletedAt
      deletedBySub
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
      items { id assignmentTypeKey queueKey queueStatusKey status priority title summary assigneeType assigneeId assigneeKey claimedAt claimExpiresAt completedAt canceledAt corpusId categorySetId classifierId sectionId sectionKey sectionType sectionStatusKey sectionQueueStatusKey primaryFocusCategoryKey topicScopeCategoryKeys sourceSnapshotId importRunId createdBy createdAt updatedAt newsroomFeedKey itemLineageId }
      nextToken
    }
  }
`;

const NEWSROOM_REFERENCE_FEED_QUERY = `
  query ListReferencesByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId newsroomFeedKey reviewedFeedKey discoveredByMonitorId updatedAt }
      nextToken
    }
  }
`;

const NEWSROOM_REFERENCE_IMPORTED_FEED_QUERY = `
  query ListReferencesByNewsroomFeedAndImportedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByNewsroomFeedAndImportedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId newsroomFeedKey reviewedFeedKey discoveredByMonitorId updatedAt }
      nextToken
    }
  }
`;

const LIST_REFERENCES_BY_CURATION_STATUS_AND_UPDATED_AT_QUERY = `
  query ListReferencesByCurationStatusAndUpdatedAt($curationStatus: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByCurationStatusAndUpdatedAt(curationStatus: $curationStatus, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId newsroomFeedKey reviewedFeedKey discoveredByMonitorId updatedAt }
      nextToken
    }
  }
`;

const LIST_REFERENCES_BY_REVIEWED_FEED_AND_UPDATED_AT_QUERY = `
  query ListReferencesByReviewedFeedAndUpdatedAt($reviewedFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {
    listReferencesByReviewedFeedAndUpdatedAt(reviewedFeedKey: $reviewedFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId newsroomFeedKey reviewedFeedKey discoveredByMonitorId updatedAt }
      nextToken
    }
  }
`;

const LIST_REFERENCES_FALLBACK_QUERY = `
  query ListReferencesFallback($limit: Int, $nextToken: String) {
    listReferences(limit: $limit, nextToken: $nextToken) {
      items { id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId newsroomFeedKey reviewedFeedKey discoveredByMonitorId updatedAt }
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

export const LIST_SEMANTIC_RELATIONS_BY_SUBJECT_STATE_QUERY = `
  query ListSemanticRelationsBySubjectState($subjectStateKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelSemanticRelationFilterInput) {
    listSemanticRelationsBySubjectState(subjectStateKey: $subjectStateKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId subjectLineageId subjectVersionNumber objectKind objectId objectLineageId objectVersionNumber subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey subjectVersionKey objectVersionKey score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId importRunId importedAt createdAt updatedAt newsroomFeedKey metadata }
      nextToken
    }
  }
`;

export const LIST_SEMANTIC_RELATIONS_BY_OBJECT_STATE_QUERY = `
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
  "id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt retrievedAt inboundCitationCount outboundCitationCount importRunId importedAt createdAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason curationReasonCode curationActorKind curationSectionId curationShareable curationDelegation curationDecisionRelationId newsroomFeedKey reviewedFeedKey discoveredByMonitorId updatedAt";

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
  scope: "edition" | "section";
  sectionKey?: string | null;
  sectionTitle?: string | null;
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
    // One refreshed session supplies both identity and current group claims.
    // A second, sequential session read only extends the blocking access check.
    const refreshed = await loadReaderSessionSnapshot({ forceRefresh: true });
    if (!refreshed.hasSession || refreshed.auth.status === "signedOut") {
      return { status: "signedOut", isEditor: false, isAdmin: false, auth: refreshed.auth, error: null };
    }
    const isEditor = hasEditorRights(refreshed.groups);
    if (!isEditor) {
      return {
        status: "forbidden",
        isEditor: false,
        isAdmin: false,
        auth: refreshed.auth,
        error: null,
      };
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
  if (summaryError) throw summaryError;
  if (userDirectoryResult.status === "rejected") throw userDirectoryResult.reason;
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

const UPDATE_ASSIGNMENT_DESK_MUTATION = `
  mutation UpdateAssignmentDesk($input: UpdateAssignmentInput!) {
    updateAssignment(input: $input) { id sectionId sectionKey }
  }
`;

/** Puts an assignment on a desk's board, or takes it off every desk when `deskId` is null. */
export async function saveNewsroomAssignmentDesk(assignmentId: string, deskId: string | null): Promise<void> {
  if (isLocalPreviewEnabled()) return;
  const dataClient = generateClient<Schema>();
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, unknown> | null; errors?: unknown[] | null }>;
  };
  const response = await graphClient.graphql({
    query: UPDATE_ASSIGNMENT_DESK_MUTATION,
    variables: { input: { id: assignmentId, sectionId: deskId, sectionKey: deskId } },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
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

/**
 * Appends one Message to a thread: the next sequence number, the Message, then the thread's count and last Message. The Message id
 * derives from the sequence number, so a create that loses a race for the number collides and retries with the next one.
 */
async function appendMessageToThread(thread: MessageThreadRecord, build: (sequenceNumber: number, now: string) => MessageRecord, threadFields: { summary?: string; metadata?: string } = {}): Promise<{ thread: MessageThreadRecord; message: MessageRecord }> {
  const threadId = thread.id;
  let now = new Date().toISOString();
  let built: MessageRecord | null = null;
  const { created } = await createWithSequenceRetry({
    list: () => listMessagesByThreadId(threadId, 1000),
    create: (sequenceNumber) => {
      now = new Date().toISOString();
      // `createdAt` is part of the composite sort key of messagesByResponseTargetStatusCreatedAt, so AppSync refuses a Message that
      // sets it without `responseStatus`. A person's message waits on no responder: COMPLETED, as the Python message contract writes.
      built = { responseStatus: "COMPLETED", ...build(sequenceNumber, now) };
      // The backend stamps the author from the signed-in identity (postMessage); nothing here names one.
      const args = postMessageArguments(built as unknown as Record<string, unknown>);
      return runGraphql<{ postMessage?: MessageRecord | null }>(postMessageMutation(args, POST_MESSAGE_SELECTION), args);
    },
  });
  const createdMessage = normalizeMessageRecord(created.postMessage ?? built!);
  if (messageHasHashtag(createdMessage.content ?? (built as MessageRecord | null)?.content)) {
    void runGraphql(LINK_MESSAGE_HASHTAGS_MUTATION, { messageId: createdMessage.id }).catch(() => undefined);
  }
  const updated = await runGraphql<{ updateMessageThread?: MessageThreadRecord | null }>(
    UPDATE_MESSAGE_THREAD_MUTATION,
    {
      input: {
        id: threadId,
        messageCount: (thread.messageCount ?? 0) + 1,
        lastMessageId: createdMessage.id,
        lastMessageAt: createdMessage.createdAt,
        updatedAt: now,
        ...threadFields,
      },
    },
  );
  return {
    thread: normalizeThreadRecord(updated.updateMessageThread ?? { ...thread, ...threadFields, updatedAt: now }),
    message: createdMessage,
  };
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
  return appendMessageToThread(thread, (sequenceNumber, now) => ({
    id: `message-forum-${safeForumId(threadId)}-${String(sequenceNumber).padStart(4, "0")}`,
    messageKind: "forum_post",
    messageDomain: "edition_coordination",
    status: "active",
    summary,
    source: "newsroom.forum",
    authorLabel: input.authorLabel?.trim() || "editor",
    threadId,
    parentMessageId: input.parentMessageId?.trim() || null,
    sequenceNumber,
    role: input.role || "human",
    messageType: "forum_message",
    content,
    metadata: input.metadata ?? {},
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "messages",
  }));
}

type ConversationAuthor = { sub: string | null; label: string; userProfileId: string | null; isAdmin: boolean };

async function currentConversationAuthor(): Promise<ConversationAuthor> {
  const snapshot = await loadReaderSessionSnapshot();
  let sub: string | null = null;
  try {
    const session = await fetchAuthSession();
    const claim = session.tokens?.idToken?.payload?.sub ?? session.tokens?.accessToken?.payload?.sub;
    sub = typeof claim === "string" && claim ? claim : null;
  } catch {
    sub = null;
  }
  const profile = await currentUserProfile();
  // The author's name travels on the message (other editors cannot read profiles): their display name, else the session's label.
  const sessionLabel = snapshot.auth.status === "signedIn" ? snapshot.auth.label : "editor";
  return { sub, label: profile.displayName || sessionLabel, userProfileId: profile.id, isAdmin: snapshot.groups.some((group) => group.trim().toLowerCase() === "admin") };
}

let userProfileLookup: Promise<{ id: string | null; displayName: string | null }> | null = null;
/** The signed-in person's profile id and display name (their own profile is readable by them), read once per page load. A failed read is not kept, and does not stop a post. */
function currentUserProfile(): Promise<{ id: string | null; displayName: string | null }> {
  userProfileLookup ??= (async () => {
    const resolution = await resolveReaderSettings();
    const id = resolution.userProfileId ?? null;
    if (!id) return { id: null, displayName: null };
    const names = await loadUserProfileNames([id]);
    return { id, displayName: names.get(id) ?? null };
  })().catch(() => { userProfileLookup = null; return { id: null, displayName: null }; });
  return userProfileLookup;
}

/** Who is looking at a conversation: their sub, and whether they are an admin. Decided from the session, never from a Message. */
export async function loadConversationViewer(): Promise<ConversationViewer> {
  const author = await currentConversationAuthor();
  return { sub: author.sub, isAdmin: author.isAdmin };
}

/** Display names by profile id, in one request. A profile this person may not read is left out and its Messages keep the saved label. */
export async function loadUserProfileNames(profileIds: string[]): Promise<Map<string, string>> {
  const ids = [...new Set(profileIds.filter(Boolean))];
  const names = new Map<string, string>();
  if (!ids.length) return names;
  const query = `query UserProfileNames { ${ids.map((id, index) => `p${index}: getUserProfile(id: ${JSON.stringify(id)}) { id displayName }`).join(" ")} }`;
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as { graphql: (options: Record<string, unknown>) => Promise<{ data?: Record<string, { id?: string; displayName?: string | null } | null> | null }> };
  let data: Record<string, { id?: string; displayName?: string | null } | null> | null | undefined;
  try {
    data = (await client.graphql({ query, authMode: USER_POOL_AUTH_MODE })).data;
  } catch (failure) {
    // Some of the profiles are refused: the rest of the answer is still good.
    data = (failure as { data?: typeof data } | null)?.data;
  }
  for (const profile of Object.values(data ?? {})) {
    if (profile?.id && profile.displayName?.trim()) names.set(profile.id, profile.displayName.trim());
  }
  return names;
}

async function findConversationThread(anchorKey: string): Promise<MessageThreadRecord | null> {
  type Response = { listMessageThreadsByAnchorAndUpdatedAt?: { items?: Array<MessageThreadRecord | null> | null } | null };
  const response = await runGraphql<Response>(LIST_MESSAGE_THREADS_BY_ANCHOR_AND_UPDATED_AT_QUERY, {
    primaryAnchorKey: anchorKey,
    sortDirection: "DESC",
    limit: 10,
  });
  const found = (response.listMessageThreadsByAnchorAndUpdatedAt?.items ?? []).filter(Boolean) as MessageThreadRecord[];
  const thread = found.find((entry) => entry.status !== "deleted") ?? null;
  return thread ? normalizeThreadRecord(thread) : null;
}

/** The one conversation for an anchor: found by its anchor key, created when there is none. Concurrent first posts share the thread. */
export async function ensureConversationThread(anchor: ConversationAnchor, author?: ConversationAuthor): Promise<MessageThreadRecord> {
  const anchorKey = conversationAnchorKey(anchor);
  if (!anchorKey) throw new Error("An unattached conversation starts its own thread.");
  return findOrCreateThread({
    find: () => findConversationThread(anchorKey),
    create: async () => {
      const now = new Date().toISOString();
      const lineageId = anchor.lineageId!.trim();
      const thread: MessageThreadRecord = {
        id: conversationThreadId(anchor),
        threadKind: conversationThreadKind(anchor),
        status: "active",
        title: anchor.title?.trim() || lineageId,
        primaryAnchorKind: anchor.kind,
        primaryAnchorId: lineageId,
        primaryAnchorLineageId: lineageId,
        primaryAnchorKey: anchorKey,
        createdBySub: author?.sub ?? null,
        createdByUserProfileId: author?.userProfileId ?? null,
        createdByLabel: author?.label ?? "editor",
        messageCount: 0,
        lastMessageId: null,
        lastMessageAt: null,
        metadata: JSON.stringify({ anchorKind: anchor.kind, anchorLineageId: lineageId }),
        createdAt: now,
        updatedAt: now,
        newsroomFeedKey: CONVERSATION_FEED_KEY,
      };
      const response = await runGraphql<{ createMessageThread?: MessageThreadRecord | null }>(CREATE_MESSAGE_THREAD_MUTATION, { input: thread });
      return normalizeThreadRecord(response.createMessageThread ?? thread);
    },
  });
}

function toConversationMessage(record: MessageRecord): ConversationMessage {
  return {
    id: record.id,
    parentMessageId: record.parentMessageId ?? null,
    authorLabel: record.authorLabel ?? "",
    authorSub: record.authorSub ?? null,
    authorUserProfileId: record.authorUserProfileId ?? null,
    content: record.status === "deleted" ? "" : record.content ?? record.body ?? "",
    createdAt: record.createdAt,
    sequenceNumber: Number(record.sequenceNumber ?? 0),
    editedAt: record.editedAt ?? null,
    deleted: record.status === "deleted",
    deletedAt: record.deletedAt ?? null,
  };
}

/** Every Message in the anchor's conversation, oldest first. An anchor with no conversation yet has none. */
export async function loadConversationMessages(anchor: ConversationAnchor): Promise<ConversationMessage[]> {
  const anchorKey = conversationAnchorKey(anchor);
  if (!anchorKey) return [];
  const thread = await findConversationThread(anchorKey);
  if (!thread) return [];
  const records = await listMessagesByThreadId(thread.id, 500);
  return records.map(toConversationMessage);
}

/** How many Messages each Reference has, from the Reference conversation threads alone (no query per card). Keyed by lineage id. */
export async function loadReferenceConversationCounts(): Promise<Map<string, number>> {
  const threads = await listMessageThreadsByKind(REFERENCE_CONVERSATION_KIND, 500);
  const counts = new Map<string, number>();
  for (const thread of threads) {
    const lineageId = thread.primaryAnchorLineageId;
    if (lineageId && thread.status !== "deleted" && (thread.messageCount ?? 0) > 0) counts.set(lineageId, thread.messageCount ?? 0);
  }
  return counts;
}

/**
 * Writes a Message into the anchor's conversation (finding or creating the thread), and a `comment` relation from the Message to
 * the Reference or Item so the thing's own detail can find it. The relation is secondary: if it fails the Message is still saved.
 */
export async function appendConversationMessage(input: {
  anchor: ConversationAnchor;
  body: string;
  parentMessageId?: string | null;
  /** The conversation to write into, when the caller already holds it (the Messages page). Without it the anchor finds or creates it. */
  thread?: MessageThreadRecord;
}): Promise<{ message: ConversationMessage; thread: MessageThreadRecord; relationError: string | null }> {
  const content = String(input.body || "").trim();
  if (!content) throw new Error("Write something to post.");
  const author = await currentConversationAuthor();
  const thread = input.thread ?? await ensureConversationThread(input.anchor, author);
  const result = await appendMessageToThread(thread, (sequenceNumber, now) => ({
    id: conversationMessageId(thread.id, sequenceNumber),
    messageKind: "comment",
    messageDomain: "commentary",
    status: "active",
    summary: content.slice(0, 120),
    source: "newsroom.conversation",
    authorLabel: author.label,
    threadId: thread.id,
    parentMessageId: input.parentMessageId?.trim() || null,
    sequenceNumber,
    role: "human",
    messageType: "comment",
    content,
    metadata: JSON.stringify({ messageKind: "comment", anchorKey: conversationAnchorKey(input.anchor) }),
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: CONVERSATION_FEED_KEY,
  }), { summary: conversationPreviewLine(content), metadata: threadMetadataWithLastAuthor(thread.metadata, author.label) });
  let relationError: string | null = null;
  if (input.anchor.kind !== "none") {
    try {
      await createCommentRelation(result.message, input.anchor);
    } catch (error) {
      relationError = error instanceof Error ? error.message : "The link to the Reference could not be saved.";
    }
  }
  return { message: toConversationMessage(result.message), thread: result.thread, relationError };
}

/** One page of conversation threads of a kind, newest activity first. */
export async function loadConversationThreadPage(threadKind: string, nextToken: string | null, limit = 20): Promise<{ items: MessageThreadRecord[]; nextToken: string | null }> {
  type ThreadConnectionResponse = { listMessageThreadsByKindAndUpdatedAt?: { items?: Array<MessageThreadRecord | null> | null; nextToken?: string | null } | null };
  const response = await runGraphql<ThreadConnectionResponse>(LIST_MESSAGE_THREADS_BY_KIND_AND_UPDATED_AT_QUERY, { threadKind, sortDirection: "DESC", limit, nextToken });
  const connection = response.listMessageThreadsByKindAndUpdatedAt;
  const items = ((connection?.items ?? []).filter(Boolean) as MessageThreadRecord[]).map(normalizeThreadRecord).filter((thread) => thread.status !== "deleted");
  return { items, nextToken: connection?.nextToken ?? null };
}

/** Every Message in a conversation thread, oldest first. */
export async function loadConversationThreadMessages(threadId: string): Promise<ConversationMessage[]> {
  const records = await listMessagesByThreadId(threadId, 500);
  return records.map(toConversationMessage);
}

/** Starts a conversation about nothing but itself: its own thread, and its first Message. */
export async function startUnattachedConversation(title: string, body: string): Promise<{ message: ConversationMessage; thread: MessageThreadRecord }> {
  const content = String(body || "").trim();
  const heading = String(title || "").trim();
  if (!heading) throw new Error("Give the conversation a title.");
  if (!content) throw new Error("Write something to post.");
  const author = await currentConversationAuthor();
  const now = new Date().toISOString();
  const id = `message-thread-conversation-new-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const thread: MessageThreadRecord = {
    id,
    threadKind: GENERAL_CONVERSATION_KIND,
    status: "active",
    title: heading.slice(0, 120),
    createdBySub: author.sub,
    createdByUserProfileId: author.userProfileId,
    createdByLabel: author.label,
    messageCount: 0,
    lastMessageId: null,
    lastMessageAt: null,
    metadata: JSON.stringify({ anchorKind: "none" }),
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: CONVERSATION_FEED_KEY,
  };
  const created = await runGraphql<{ createMessageThread?: MessageThreadRecord | null }>(CREATE_MESSAGE_THREAD_MUTATION, { input: thread });
  const saved = normalizeThreadRecord(created.createMessageThread ?? thread);
  const result = await appendConversationMessage({ anchor: { kind: "none" }, body: content, thread: saved });
  return { message: result.message, thread: result.thread };
}

const GET_MESSAGE_THREAD_QUERY = `
  query GetMessageThread($id: ID!) {
    getMessageThread(id: $id) {
      id threadKind status title summary primaryAnchorKind primaryAnchorId primaryAnchorLineageId primaryAnchorKey createdBySub createdByUserProfileId createdByLabel messageCount lastMessageId lastMessageAt contextDigest activeResponseMessageId responseLockOwner responseLockExpiresAt metadata createdAt updatedAt newsroomFeedKey
    }
  }
`;

const MESSAGE_ACTION_SELECTION = "id messageKind messageDomain status summary source importRunId authorSub authorUserProfileId authorLabel editedAt deletedAt deletedBySub threadId parentMessageId sequenceNumber role messageType content semanticLayer searchVisibility responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError metadata createdAt updatedAt newsroomFeedKey";

/** The author changes the text of their own Message. The backend (editMessage) checks the stored author against the signed-in user and records when. */
export async function editConversationMessage(messageId: string, body: string): Promise<ConversationMessage> {
  const content = String(body || "").trim();
  if (!content) throw new Error("A message cannot be empty.");
  const updated = await runGraphql<{ editMessage?: MessageRecord | null }>(
    `mutation EditMessage($id: ID!, $content: String!, $summary: String) { editMessage(id: $id, content: $content, summary: $summary) { ${MESSAGE_ACTION_SELECTION} } }`,
    { id: messageId, content, summary: content.slice(0, 120) },
  );
  if (!updated.editMessage) throw new Error("The message was not saved.");
  return toConversationMessage(normalizeMessageRecord(updated.editMessage));
}

/**
 * Deletes a Message softly: it stays (so its replies keep their place) marked deleted, with when and by whom. Nothing is removed.
 * An author deletes their own (deleteOwnMessage); an admin deleting someone else's moderates it (moderateMessage). The backend decides.
 */
export async function deleteConversationMessage(messageId: string, moderate = false): Promise<ConversationMessage> {
  const field = moderate ? "moderateMessage" : "deleteOwnMessage";
  const updated = await runGraphql<Record<string, MessageRecord | null | undefined>>(
    `mutation DeleteMessage($id: ID!) { ${field}(id: $id) { ${MESSAGE_ACTION_SELECTION} } }`,
    { id: messageId },
  );
  const record = updated[field];
  if (!record) throw new Error("The message was not deleted.");
  return toConversationMessage(normalizeMessageRecord(record));
}

/** One conversation thread by id (a linked address), or null when there is none or it was removed. */
export async function loadConversationThread(threadId: string): Promise<MessageThreadRecord | null> {
  const response = await runGraphql<{ getMessageThread?: MessageThreadRecord | null }>(GET_MESSAGE_THREAD_QUERY, { id: threadId });
  const thread = response.getMessageThread ? normalizeThreadRecord(response.getMessageThread) : null;
  return thread && thread.status !== "deleted" ? thread : null;
}

/** Gives a conversation a new title. Nothing else about the thread changes. */
export async function renameConversationThread(thread: MessageThreadRecord, title: string): Promise<MessageThreadRecord> {
  const next = String(title || "").trim();
  if (!next) throw new Error("A title cannot be empty.");
  // renameThread (the backend): only the person who started the conversation, or an admin.
  const updated = await runGraphql<{ renameThread?: MessageThreadRecord | null }>(
    `mutation RenameThread($id: ID!, $title: String!) { renameThread(id: $id, title: $title) { id threadKind status title summary primaryAnchorKind primaryAnchorId primaryAnchorLineageId primaryAnchorKey createdBySub createdByUserProfileId createdByLabel messageCount lastMessageId lastMessageAt contextDigest activeResponseMessageId responseLockOwner responseLockExpiresAt metadata createdAt updatedAt newsroomFeedKey } }`,
    { id: thread.id, title: next.slice(0, 120) },
  );
  return normalizeThreadRecord(updated.renameThread ?? { ...thread, title: next.slice(0, 120) });
}

/** The title and editorial stage of each Story, by lineage id. A Story that cannot be read has no entry. */
export async function loadStoryHeaders(lineageIds: string[]): Promise<Map<string, { title: string; stage: string | null }>> {
  const headers = new Map<string, { title: string; stage: string | null }>();
  await Promise.all([...new Set(lineageIds)].map(async (lineageId) => {
    try {
      type Response = { listItemsByLineageAndVersion?: { items?: Array<{ versionNumber?: number | null; headline?: string | null; title?: string | null; stage?: string | null } | null> | null } | null };
      const response = await runGraphql<Response>(`query StoryHeader($lineageId: ID!) { listItemsByLineageAndVersion(lineageId: $lineageId, limit: 50) { items { versionNumber headline title stage } } }`, { lineageId });
      const items = (response.listItemsByLineageAndVersion?.items ?? []).filter(Boolean) as Array<{ versionNumber?: number | null; headline?: string | null; title?: string | null; stage?: string | null }>;
      const newest = items.sort((left, right) => (right.versionNumber ?? 0) - (left.versionNumber ?? 0))[0];
      const title = newest?.headline || newest?.title;
      if (title) headers.set(lineageId, { title, stage: newest?.stage ?? null });
    } catch { /* a Story that cannot be read keeps the title the thread was started with */ }
  }));
  return headers;
}

async function createCommentRelation(message: MessageRecord, anchor: ConversationAnchor): Promise<void> {
  if (anchor.kind === "none") return;
  const lineageId = anchor.lineageId.trim();
  const objectId = anchor.id?.trim() || lineageId;
  const now = message.createdAt;
  await runGraphql(CREATE_SEMANTIC_RELATION_MUTATION, {
    input: {
      id: `semantic-relation-${message.id}-comment`,
      relationState: "current",
      predicate: "comment",
      relationTypeId: "semantic-relation-type-comment",
      relationTypeKey: "comment",
      relationDomain: "commentary",
      subjectKind: "message",
      subjectId: message.id,
      subjectLineageId: message.id,
      subjectVersionNumber: 1,
      objectKind: anchor.kind,
      objectId,
      objectLineageId: lineageId,
      subjectStateKey: semanticStateKey("message", message.id),
      objectStateKey: semanticStateKey(anchor.kind, lineageId),
      objectSubjectStateKey: `${semanticStateKey(anchor.kind, lineageId)}#message`,
      predicateObjectStateKey: `comment#${semanticStateKey(anchor.kind, lineageId)}`,
      subjectVersionKey: semanticVersionKey("message", message.id),
      objectVersionKey: semanticVersionKey(anchor.kind, objectId),
      score: 1,
      rank: 1,
      reviewRecommended: false,
      importedAt: now,
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: "semanticRelations",
      metadata: JSON.stringify({ kind: "conversation.comment", messageKind: "comment" }),
    },
  });
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

export async function runGraphql<T extends Record<string, unknown>>(
  query: string,
  variables: Record<string, unknown>,
): Promise<T> {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: T | null; errors?: unknown[] | null }>;
  };
  // The Amplify client rejects with the raw `{ data, errors }` response when the API returns errors; turn that into an
  // Error carrying the API's own words, so a refusal is said in words instead of as an unknown failure.
  const response = await client.graphql({
    query,
    variables,
    authMode: USER_POOL_AUTH_MODE,
  }).catch((failure: unknown) => {
    if (failure && typeof failure === "object" && Array.isArray((failure as { errors?: unknown }).errors)) {
      assertNoGraphQLErrors((failure as { errors: unknown[] }).errors);
    }
    throw failure;
  });
  assertNoGraphQLErrors(response.errors);
  return (response.data ?? {}) as T;
}

export async function loadEditorReferencesData(): Promise<{
  references: ReferenceRecord[];
  referenceAttachments: ReferenceAttachmentRecord[];
}> {
  configureAmplifyClient();
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
    return {
      references: await loadAllNewsroomReferences(),
      referenceAttachments,
    };
  }
  const [references, referenceAttachments] = await Promise.all([
    loadAllNewsroomReferences(),
    listUserPoolModel<ReferenceAttachmentRecord>("ReferenceAttachment"),
  ]);
  return {
    references,
    referenceAttachments: referenceAttachments.sort((left, right) => left.sortKey.localeCompare(right.sortKey)),
  };
}

/** Every reference, page by page: the References feed ranks the whole set, so stopping at the first page hid most of it. */
function loadAllNewsroomReferences(): Promise<ReferenceRecord[]> {
  return loadAllPages((nextToken) => loadNewsroomReferencePage({ nextToken }));
}

export function normalizeNewsroomReferencePageOrder(value?: string | null): NewsroomReferencePageOrder {
  return value?.trim() === "imported" ? "imported" : "published";
}

export async function loadNewsroomReferencePage(options: NewsroomReferencePageOptions = {}): Promise<NewsroomRecordPage<ReferenceRecord>> {
  if (isLocalPreviewEnabled()) return { items: createLocalPreviewReferences(), nextToken: null, hasMore: false };
  configureAmplifyClient();
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

  if (nextToken) throw new Error("The activity feed is incomplete. Select a reference to load its prediction directly.");
  return rows;
}

/** Selected-reference details use indexes, not the bounded global activity feed. */
export async function loadEditorReferenceReviewDetails(lineageId: string) {
  configureAmplifyClient();
  const testMock = getTestEditorNewsroomMock();
  return loadReferenceReviewDetails(lineageId, {
    relations: async () => {
      if (testMock?.semanticRelations) return testMock.semanticRelations;
      return loadSemanticRelationsByState({
        field: "listSemanticRelationsBySubjectState",
        keyName: "subjectStateKey",
        keyValue: `reference#${lineageId}#current`,
        query: LIST_SEMANTIC_RELATIONS_BY_SUBJECT_STATE_QUERY,
      });
    },
  });
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
  if (isLocalPreviewEnabled()) return { items: createLocalPreviewAssignments(), nextToken: null, hasMore: false };
  return loadNewsroomFeedPage<AssignmentRecord>({
    query: NEWSROOM_ASSIGNMENT_FEED_QUERY,
    field: "listAssignmentsByNewsroomFeedAndCreatedAt",
    newsroomFeedKey: "assignments",
    limit: options.limit,
    nextToken: options.nextToken,
    matches: (assignment) => isEditorialWorkAssignment(assignment) && (equalityMatcher<AssignmentRecord>({
      assignmentTypeKey: options.type,
      status: options.status,
    })?.(assignment) ?? true),
  });
}

const CONTENT_ITEMS_BY_STAGE_QUERY = `
  query ListItemsByStageAndUpdatedAt($stage: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listItemsByStageAndUpdatedAt(stage: $stage, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items { id lineageId versionNumber stage type status title headline deck metadata slug section updatedAt versionCreatedBy }
      nextToken
    }
  }
`;

export const CONTENT_ITEM_COLUMN_PAGE_LIMIT = 25;

export type ContentItemStagePage = {
  versions: ContentItemVersionRecord[];
  nextToken: string | null;
};

/** One newest-updated-first page of the content items in one stage, so a board column can load as it is scrolled. */
export async function loadNewsroomContentItemStagePage(
  stage: string,
  nextToken: string | null = null,
  limit: number = CONTENT_ITEM_COLUMN_PAGE_LIMIT,
): Promise<ContentItemStagePage> {
  if (isLocalPreviewEnabled()) {
    const versionsInStage = createLocalPreviewContentItemVersions().filter(version => version.stage === stage);
    const offset = nextToken ? Number(nextToken) : 0;
    const followingOffset = offset + limit;
    return {
      versions: versionsInStage.slice(offset, followingOffset),
      nextToken: followingOffset < versionsInStage.length ? String(followingOffset) : null,
    };
  }
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<ContentItemVersionRecord>>;
  };
  const field = "listItemsByStageAndUpdatedAt";
  const response: GraphQLConnectionResponse<ContentItemVersionRecord> = await client.graphql({
    query: CONTENT_ITEMS_BY_STAGE_QUERY,
    variables: { stage, sortDirection: "DESC", limit, nextToken },
    authMode: USER_POOL_AUTH_MODE,
  });
  assertNoGraphQLErrors(response.errors);
  const connection = response.data?.[field];
  if (!connection) throw new Error(`Missing GraphQL connection payload for ${field}.`);
  return {
    versions: (connection.items ?? []).filter(Boolean) as ContentItemVersionRecord[],
    nextToken: connection.nextToken ?? null,
  };
}

const PUBLISHED_ITEMS_QUERY = `
  query ListPublishedItems($limit: Int, $nextToken: String) {
    listPublishedItems(limit: $limit, nextToken: $nextToken) {
      items { sourceItemId itemLineageId versionNumber type status title headline slug section publishedAt }
      nextToken
    }
  }
`;

type PublishedItemBoardRow = {
  sourceItemId: string;
  itemLineageId: string;
  versionNumber: number;
  type: string;
  status: string;
  title?: string | null;
  headline?: string | null;
  slug: string;
  section?: string | null;
  publishedAt?: string | null;
};

export async function loadNewsroomPublishedContentItemVersions(): Promise<ContentItemVersionRecord[]> {
  if (isLocalPreviewEnabled()) return createLocalPreviewRealPublishedVersions();
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<GraphQLConnectionResponse<PublishedItemBoardRow>>;
  };
  const rows: PublishedItemBoardRow[] = [];
  let nextToken: string | null = null;
  do {
    const response: GraphQLConnectionResponse<PublishedItemBoardRow> = await client.graphql({
      query: PUBLISHED_ITEMS_QUERY,
      variables: { limit: NEWSROOM_PAGE_LIMIT, nextToken },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.listPublishedItems;
    if (!connection) throw new Error("Missing GraphQL connection payload for listPublishedItems.");
    rows.push(...((connection.items ?? []).filter(Boolean) as PublishedItemBoardRow[]));
    nextToken = connection.nextToken ?? null;
  } while (nextToken);
  return rows.map(row => ({
    id: row.sourceItemId,
    lineageId: row.itemLineageId,
    versionNumber: row.versionNumber,
    stage: "published",
    type: row.type,
    status: row.status,
    title: row.title,
    headline: row.headline,
    slug: row.slug,
    section: row.section,
    updatedAt: row.publishedAt,
  }));
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
  const allowOverride = testEditorOverrideAllowed(process.env.NODE_ENV, process.env.NEXT_PUBLIC_ENABLE_TEST_EDITOR_OVERRIDE);
  if (!allowOverride) return false;
  return window.localStorage.getItem(TEST_EDITOR_STORAGE_KEY) === "true";
}

type TestEditorNewsroomMock = {
  forumThreadsByEdition?: Record<string, ForumThreadWithMessages[]>;
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
  configureAmplifyClient();
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

export async function loadSemanticRelationsByState({
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
    if (!connection) throw new Error(`Missing GraphQL connection payload for ${field}.`);
    for (const item of (connection.items ?? []).filter(Boolean) as SemanticRelationRecord[]) {
      if (!item.id || seenIds.has(item.id)) continue;
      seenIds.add(item.id);
      rows.push(item);
    }
    nextToken = connection.nextToken ?? null;
  } while (nextToken && pageCount < 200);
  if (nextToken) throw new Error("Reference details are incomplete. Try again before reviewing its prediction.");
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

const CREATE_KNOWLEDGE_RAW_PAYLOAD_MUTATION = `
  mutation CreateKnowledgeRawPayload($input: CreateKnowledgeRawPayloadInput!) {
    createKnowledgeRawPayload(input: $input) { id }
  }
`;

const GET_KNOWLEDGE_RAW_PAYLOAD_QUERY = `
  query GetKnowledgeRawPayload($id: ID!) {
    getKnowledgeRawPayload(id: $id) { id }
  }
`;

/** The relevance cyclotron's latest cyclotron-status/v1 snapshot, as the sweep recorded it. */
export async function loadCyclotronStatus(cyclotronId: string): Promise<import("cyclotron/cyclotron-status").CyclotronStatus | null> {
  const { cyclotronStatusPayloadId, latestCyclotronStatus } = await import("../lib/relevance-status");
  const payloads = await loadModelPayloadsForOwner("knowledgeRawPayload", cyclotronStatusPayloadId(cyclotronId), ["raw_payload"]);
  return latestCyclotronStatus(payloads.map((payload) => ({ json: payload.json, updatedAt: payload.attachment.updatedAt })));
}

/** The relevance cyclotron's latest cyclotron-shadow-agreement/v1 payload: suggestions compared with later human decisions. */
export async function loadCyclotronShadowAgreement(cyclotronId: string): Promise<import("../lib/cyclotron-suggestions").ShadowAgreement | null> {
  const { latestShadowAgreement, shadowAgreementPayloadId } = await import("../lib/cyclotron-suggestions");
  const payloads = await loadModelPayloadsForOwner("knowledgeRawPayload", shadowAgreementPayloadId(cyclotronId), ["raw_payload"]);
  return latestShadowAgreement(payloads.map((payload) => ({ json: payload.json, updatedAt: payload.attachment.updatedAt })));
}

/** The site cyclotron's latest per-Section agreement payload, as the Section sweep recorded it. */
export async function loadSiteSectionAgreement(cyclotronId: string): Promise<import("../lib/site-section-suggestions").SiteSectionAgreement | null> {
  const { shadowAgreementPayloadId } = await import("../lib/cyclotron-suggestions");
  const { parseSiteSectionAgreement } = await import("../lib/site-section-suggestions");
  const payloads = await loadModelPayloadsForOwner("knowledgeRawPayload", shadowAgreementPayloadId(cyclotronId), ["raw_payload"]);
  const parsed = payloads
    .map((payload) => ({ agreement: parseSiteSectionAgreement(payload.json), updatedAt: payload.attachment.updatedAt }))
    .filter((entry) => entry.agreement !== null)
    .sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
  return parsed.length ? parsed[0].agreement : null;
}

/** Ask the next decide-relevance sweep to set or clear a manual review rate. */
export async function requestCyclotronReviewRate(
  cyclotronId: string,
  request: import("../lib/relevance-status").ReviewRateRequest,
): Promise<void> {
  const { reviewRateRequestPayloadId, safeId } = await import("../lib/relevance-status");
  const id = reviewRateRequestPayloadId(cyclotronId);
  const existing = await runGraphql<{ getKnowledgeRawPayload?: { id: string } | null }>(GET_KNOWLEDGE_RAW_PAYLOAD_QUERY, { id });
  if (!existing.getKnowledgeRawPayload) {
    await runGraphql(CREATE_KNOWLEDGE_RAW_PAYLOAD_MUTATION, {
      input: {
        id,
        ownerType: "cyclotron",
        ownerId: safeId(cyclotronId),
        payloadKind: "cyclotron-review-rate-request",
        createdAt: request.requestedAt,
        updatedAt: request.requestedAt,
      },
    });
  }
  await uploadModelPayloadForOwner({
    ownerKind: "knowledgeRawPayload",
    ownerId: id,
    ownerLineageId: id,
    role: "raw_payload",
    sortKey: `review-rate-request-${request.requestedAt}`,
    filename: "review-rate-request.json",
    mediaType: "application/json",
    content: JSON.stringify(request),
  });
}

const LIST_PRIMING_REQUEST_PAYLOADS_QUERY = `
  query ListKnowledgeRawPayloadsByOwnerAndKind($ownerId: ID!, $payloadKind: ModelStringKeyConditionInput, $limit: Int, $nextToken: String) {
    listKnowledgeRawPayloadsByOwnerAndKind(ownerId: $ownerId, payloadKind: $payloadKind, limit: $limit, nextToken: $nextToken) {
      items { id }
      nextToken
    }
  }
`;

/** Ask the next decide-relevance sweep to prime the running cyclotron with one pasted URL. */
export async function requestCyclotronPriming(
  cyclotronId: string,
  request: import("../lib/relevance-status").PrimingRequest,
): Promise<void> {
  const { primingRequestPayloadId, PRIMING_REQUEST_KIND, safeId } = await import("../lib/relevance-status");
  const id = primingRequestPayloadId(cyclotronId, request.requestId);
  await runGraphql(CREATE_KNOWLEDGE_RAW_PAYLOAD_MUTATION, {
    input: {
      id,
      ownerType: "cyclotron",
      ownerId: safeId(cyclotronId),
      payloadKind: PRIMING_REQUEST_KIND,
      createdAt: request.requestedAt,
      updatedAt: request.requestedAt,
    },
  });
  await uploadModelPayloadForOwner({
    ownerKind: "knowledgeRawPayload",
    ownerId: id,
    ownerLineageId: id,
    role: "raw_payload",
    sortKey: "priming-request",
    filename: "priming-request.json",
    mediaType: "application/json",
    content: JSON.stringify(request),
  });
}

/** The saved priming requests of a cyclotron, newest first, each with the sweep's outcome once there is one. */
export async function loadCyclotronPrimingRequests(
  cyclotronId: string,
): Promise<import("../lib/relevance-status").PrimingRequestView[]> {
  const { PRIMING_OUTCOME_ROLE, PRIMING_REQUEST_KIND, isPrimingOutcome, safeId } = await import("../lib/relevance-status");
  const ids: string[] = [];
  let nextToken: string | null = null;
  do {
    const page: { listKnowledgeRawPayloadsByOwnerAndKind?: { items?: Array<{ id: string } | null>; nextToken?: string | null } | null } =
      await runGraphql(LIST_PRIMING_REQUEST_PAYLOADS_QUERY, {
        ownerId: safeId(cyclotronId), payloadKind: { eq: PRIMING_REQUEST_KIND }, limit: 100, nextToken,
      });
    const connection = page.listKnowledgeRawPayloadsByOwnerAndKind;
    ids.push(...(connection?.items ?? []).filter((item): item is { id: string } => Boolean(item)).map((item) => item.id));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  const views = await Promise.all(ids.map(async (id) => {
    const payloads = await loadModelPayloadsForOwner("knowledgeRawPayload", id, ["raw_payload", PRIMING_OUTCOME_ROLE]);
    const request = payloads.find((payload) => payload.attachment.role === "raw_payload")?.json;
    const outcome = payloads.find((payload) => payload.attachment.role === PRIMING_OUTCOME_ROLE)?.json;
    if (!request || typeof request !== "object") return null;
    return {
      request: request as import("../lib/relevance-status").PrimingRequest,
      outcome: isPrimingOutcome(outcome) ? outcome : null,
    };
  }));
  return views
    .filter((view): view is import("../lib/relevance-status").PrimingRequestView => view !== null)
    .sort((left, right) => right.request.requestedAt.localeCompare(left.request.requestedAt));
}
