import { createHash, randomUUID } from "node:crypto";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";
import { putJsonModelPayload, putTextModelPayload, readJsonModelPayload } from "../shared/model-payloads";

type ReviewHandler = Schema["reviewSteeringProposal"]["functionHandler"];
type ReferenceCurationHandler = Schema["reviewReferenceCuration"]["functionHandler"];
type ReferenceQualityHandler = Schema["setReferenceQualityRating"]["functionHandler"];
type ReferenceInsightHandler = Schema["createReferenceInsight"]["functionHandler"];
type MoveReferenceCorpusHandler = Schema["moveReferenceCorpus"]["functionHandler"];
type StartReferenceCurationHandler = Schema["startReferenceCuration"]["functionHandler"];
type GetReferenceCurationStatusHandler = Schema["getReferenceCurationStatus"]["functionHandler"];
type CreateCategorySetDraftHandler = Schema["createCategorySetDraft"]["functionHandler"];
type PromoteCategorySetDraftHandler = Schema["promoteCategorySetDraft"]["functionHandler"];
type DiscardCategorySetDraftHandler = Schema["discardCategorySetDraft"]["functionHandler"];
type CreateDraftCategoryHandler = Schema["createDraftCategory"]["functionHandler"];
type UpdateDraftCategoryHandler = Schema["updateDraftCategory"]["functionHandler"];
type ArchiveDraftCategoryHandler = Schema["archiveDraftCategory"]["functionHandler"];
type ReviewReferenceTopicLabelHandler = Schema["reviewReferenceTopicLabel"]["functionHandler"];
type CategoryActionEvent =
  | Parameters<ReviewHandler>[0]
  | Parameters<ReferenceCurationHandler>[0]
  | Parameters<ReferenceQualityHandler>[0]
  | Parameters<ReferenceInsightHandler>[0]
  | Parameters<MoveReferenceCorpusHandler>[0]
  | Parameters<StartReferenceCurationHandler>[0]
  | Parameters<GetReferenceCurationStatusHandler>[0]
  | Parameters<CreateCategorySetDraftHandler>[0]
  | Parameters<PromoteCategorySetDraftHandler>[0]
  | Parameters<DiscardCategorySetDraftHandler>[0]
  | Parameters<CreateDraftCategoryHandler>[0]
  | Parameters<UpdateDraftCategoryHandler>[0]
  | Parameters<ArchiveDraftCategoryHandler>[0]
  | Parameters<ReviewReferenceTopicLabelHandler>[0];
type DataClient = ReturnType<typeof generateClient<Schema>>;
type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;
type DataClientResult<T = unknown> = {
  data?: T | null;
  errors?: DataClientErrors;
};

const CATEGORY_PROPOSAL_KINDS = new Set([
  "new-category",
  "rename-category",
  "merge-category",
  "deprecate-category",
  "seed-change",
  "holdout-change",
  "category-display-copy-edit",
  "category-copy-edit",
  "display-copy-edit",
  "create-category",
  "move-category",
  "archive-category",
]);
const NEWSROOM_SUMMARY_PAYLOAD_ID = "knowledge-raw-payload-newsroom-summary-current";
const NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND = "knowledgeRawPayload";
const SUMMARY_STALE_AFTER_MS = 15 * 60 * 1000;
const REFERENCE_CURATION_ASSIGNMENT_TYPE = "curation.reference-refresh";
const REFERENCE_CURATION_STAGE_KEYS = [
  "identifier",
  "publicationDate",
  "titleSubtitle",
  "summary",
  "topicPredictions",
] as const;
const DEFAULT_REFERENCE_CURATION_POLICY = {
  recomputeIdentifier: true,
  recomputePublicationDate: true,
  recomputeTitle: true,
  recomputeSubtitle: true,
  recomputeSummary: true,
  recomputeTopicPredictions: true,
  recomputeQuality: false,
  recomputeCorpus: false,
};
const REFERENCE_REVIEWED_FEED_KEY = "references#reviewed";

let clientPromise: Promise<DataClient> | null = null;

export const handler = async (event: CategoryActionEvent) => {
  const fieldName = normalizeOptionalString(event.info?.fieldName) ?? normalizeOptionalString((event as { fieldName?: string | null }).fieldName);
  if (!fieldName) {
    throw new Error("Unsupported steering action: missing GraphQL field name.");
  }
  if (fieldName === "reviewSteeringProposal") return reviewSteeringProposal(event as Parameters<ReviewHandler>[0]);
  if (fieldName === "reviewReferenceCuration") return reviewReferenceCuration(event as Parameters<ReferenceCurationHandler>[0]);
  if (fieldName === "setReferenceQualityRating") return setReferenceQualityRating(event as Parameters<ReferenceQualityHandler>[0]);
  if (fieldName === "createReferenceInsight") return createReferenceInsight(event as Parameters<ReferenceInsightHandler>[0]);
  if (fieldName === "moveReferenceCorpus") return moveReferenceCorpus(event as Parameters<MoveReferenceCorpusHandler>[0]);
  if (fieldName === "startReferenceCuration") return startReferenceCuration(event as Parameters<StartReferenceCurationHandler>[0]);
  if (fieldName === "getReferenceCurationStatus") return getReferenceCurationStatus(event as Parameters<GetReferenceCurationStatusHandler>[0]);
  if (fieldName === "createCategorySetDraft") return createCategorySetDraft(event as Parameters<CreateCategorySetDraftHandler>[0]);
  if (fieldName === "promoteCategorySetDraft") return promoteCategorySetDraft(event as Parameters<PromoteCategorySetDraftHandler>[0]);
  if (fieldName === "discardCategorySetDraft") return discardCategorySetDraft(event as Parameters<DiscardCategorySetDraftHandler>[0]);
  if (fieldName === "createDraftCategory") return createDraftCategory(event as Parameters<CreateDraftCategoryHandler>[0]);
  if (fieldName === "updateDraftCategory") return updateDraftCategory(event as Parameters<UpdateDraftCategoryHandler>[0]);
  if (fieldName === "archiveDraftCategory") return archiveDraftCategory(event as Parameters<ArchiveDraftCategoryHandler>[0]);
  if (fieldName === "reviewReferenceTopicLabel") return reviewReferenceTopicLabel(event as Parameters<ReviewReferenceTopicLabelHandler>[0]);
  throw new Error(`Unsupported steering action ${fieldName}.`);
};

async function reviewSteeringProposal(event: Parameters<ReviewHandler>[0]) {
  const client = await getDataClient();
  const proposalId = normalizeRequiredString(event.arguments.proposalId, "proposalId");
  const action = normalizeReviewAction(event.arguments.action);
  const proposal = await getRequiredRecord(client.models.SteeringProposal, proposalId, "SteeringProposal");
  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const selectedCategoryKey = normalizeOptionalString(proposal.categoryKey);
  const decisionId = `decision-${proposalId}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;

  await requireDataResult(
    client.models.SteeringDecision.create({
      id: decisionId,
      proposalId,
      categorySetId: proposal.categorySetId ?? null,
      action,
      actorSub,
      actorLabel,
      note: normalizeOptionalString(event.arguments.note),
      selectedCategoryKey,
      createdAt: now,
    }),
    "create SteeringDecision",
  );

  const proposalStatus = action === "reject" ? "rejected" : action === "defer" ? "deferred" : "accepted";
  await requireDataResult(
    client.models.SteeringProposal.update({
      id: proposalId,
      status: proposalStatus,
      reviewedAt: now,
      reviewedBy: actorLabel ?? actorSub,
      updatedAt: now,
    }),
    "update SteeringProposal",
  );

  let categoryId: string | null = null;
  if ((action === "accept" || action === "edit") && shouldApplySteeringProposalToCategory(proposal)) {
    categoryId = await createCategoryVersionFromProposal(client, proposal, event.arguments, {
      actorLabel: actorLabel ?? actorSub ?? "Papyrus news desk",
      now,
      reason: `proposal:${proposalId}`,
    });
    await refreshCategorySetCount(client, normalizeRequiredString(proposal.categorySetId, "proposal.categorySetId"));
  }

  return {
    ok: true,
    action,
    proposalId,
    categorySetId: proposal.categorySetId ?? null,
    categoryId,
    decisionId,
    status: proposalStatus,
  };
}

async function reviewReferenceCuration(event: Parameters<ReferenceCurationHandler>[0]) {
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const action = normalizeReferenceCurationAction(event.arguments.action);
  const nextStatus = referenceCurationStatusForAction(action);
  const reasonCode = normalizeReferenceRejectionReasonCode(event.arguments.reasonCode, action === "reject");
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const actor = actorLabel ?? actorSub ?? "Papyrus newsroom";
  const note = normalizeOptionalString(event.arguments.note);
  const referenceLineageId = normalizeOptionalString(reference.lineageId) ?? referenceId;
  const referenceVersionNumber = typeof reference.versionNumber === "number" ? reference.versionNumber : null;
  const referenceTitle = normalizeOptionalString(reference.title) ?? normalizeOptionalString(reference.externalItemId) ?? referenceId;
  const messageId = `message-reference-curation-${safeId(referenceLineageId)}-${safeId(action)}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const relationId = `semantic-relation-${hashStable([
    `message#${messageId}`,
    "comment",
    `reference#${referenceId}`,
    action,
  ]).slice(0, 16)}`;

  await requireDataResult(
    client.models.Reference.update({
      id: referenceId,
      curationStatus: nextStatus,
      curationStatusKey: `${normalizeRequiredString(reference.corpusId, "reference.corpusId")}#${nextStatus}`,
      curationStatusUpdatedAt: now,
      curationStatusUpdatedBy: actor,
      curationStatusReason: note,
      newsroomFeedKey: reference.newsroomFeedKey ?? "references",
      reviewedFeedKey: reviewedFeedKeyForStatus(nextStatus),
      updatedAt: now,
    }),
    "update Reference curation status",
  );

  await requireDataResult(
    client.models.Message.create(buildCanonicalMessageInput({
      id: messageId,
      messageKind: "reference_curation",
      messageDomain: "commentary",
      summary: `${referenceTitle}: ${nextStatus}`,
      source: "newsroom",
      authorSub: actorSub,
      authorLabel: actor,
      now,
    })),
    "create Message",
  );
  await putTextModelPayload(
    client as any,
    { ownerKind: "message", ownerId: messageId, ownerLineageId: messageId },
    "message_body",
    "message",
    note ?? `${actor} marked this reference ${nextStatus}.`,
    { filename: "message.txt", now },
  );
  await putJsonModelPayload(
    client as any,
    { ownerKind: "message", ownerId: messageId, ownerLineageId: messageId },
    "metadata",
    "metadata",
    {
      action,
      curationStatus: nextStatus,
      reasonCode,
      curationReasonCode: reasonCode,
      referenceId,
      referenceLineageId,
    },
    { filename: "metadata.json", now },
  );

  await requireDataResult(
    client.models.SemanticRelation.create({
      id: relationId,
      relationState: "current",
      predicate: "comment",
      relationTypeId: "semantic-relation-type-comment",
      relationTypeKey: "comment",
      relationDomain: "commentary",
      subjectKind: "message",
      subjectId: messageId,
      subjectLineageId: messageId,
      subjectVersionNumber: 1,
      objectKind: "reference",
      objectId: referenceId,
      objectLineageId: referenceLineageId,
      objectVersionNumber: referenceVersionNumber,
      subjectStateKey: semanticStateKey("message", messageId),
      objectStateKey: semanticStateKey("reference", referenceLineageId),
      objectSubjectStateKey: `${semanticStateKey("reference", referenceLineageId)}#message`,
      predicateObjectStateKey: `comment#${semanticStateKey("reference", referenceLineageId)}`,
      subjectVersionKey: semanticVersionKey("message", messageId),
      objectVersionKey: semanticVersionKey("reference", referenceId),
      score: 1,
      confidence: null,
      rank: 1,
      classifierId: null,
      modelVersion: null,
      reviewRecommended: false,
      sourceSnapshotId: null,
      importRunId: null,
      importedAt: now,
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: "semanticRelations",
      metadata: JSON.stringify({
        action,
        curationStatus: nextStatus,
        reasonCode,
        messageKind: "reference_curation",
      }),
    }),
    "create Message SemanticRelation",
  );

  await updateNewsroomSummaryForReferenceCuration(client, {
    corpusId: normalizeOptionalString(reference.corpusId),
    previousStatus: normalizeOptionalString(reference.curationStatus) ?? "pending",
    nextStatus,
    now,
  });

  return {
    ok: true,
    action,
    referenceId,
    status: nextStatus,
    reasonCode,
    messageId,
    relationId,
  };
}

async function setReferenceQualityRating(event: Parameters<ReferenceQualityHandler>[0]) {
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const rating = normalizeReferenceQualityRating(event.arguments.rating);
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const actor = actorLabel ?? actorSub ?? "Papyrus newsroom";
  const note = normalizeOptionalString(event.arguments.note);
  const referenceLineageId = normalizeOptionalString(reference.lineageId) ?? referenceId;
  const nextStatus = rating >= 3 ? "accepted" : "rejected";
  const existingRelations = await listCurrentSemanticRelationsBySubject(
    client,
    "quality_rating_is",
    semanticStateKey("reference", referenceLineageId),
  );
  const existingRating = existingRelations.length === 1 ? qualityRatingFromRelation(existingRelations[0]) : null;
  const currentStatus = normalizeOptionalString(reference.curationStatus) ?? "pending";
  const alreadyAcceptedAtRating = nextStatus === "accepted"
    && currentStatus === "accepted"
    && existingRelations.length === 1
    && existingRating === rating;
  const alreadyRejectedWithoutQuality = nextStatus === "rejected"
    && currentStatus === "rejected"
    && existingRelations.length === 0;

  if (alreadyAcceptedAtRating || alreadyRejectedWithoutQuality) {
    return {
      ok: true,
      referenceId,
      rating,
      status: nextStatus,
      relationId: alreadyAcceptedAtRating ? existingRelations[0]?.id ?? null : null,
    };
  }

  for (const relation of existingRelations) {
    await requireDataResult(
      client.models.SemanticRelation.update({
        id: relation.id,
        relationState: "superseded",
        updatedAt: now,
        metadata: JSON.stringify({
          ...parseMetadataObject(relation.metadata),
          supersededAt: now,
          supersededBy: actor,
          supersededByRating: rating,
        }),
      }),
      "supersede quality_rating_is",
    );
  }

  let relationId: string | null = null;
  if (rating >= 3) {
    const qualityNode = await getRequiredRecord(client.models.SemanticNode, qualityNodeId(rating), "SemanticNode");
    const relation = buildReferenceQualityRelation({
      actor,
      note,
      now,
      qualityNode,
      rating,
      reference,
    });
    await requireDataResult(client.models.SemanticRelation.create(relation), "create quality_rating_is");
    await updateNewsroomSummaryForSemanticRelationDelta(client, relation, 1, now);
    relationId = relation.id;
  }

  await requireDataResult(
    client.models.Reference.update({
      id: referenceId,
      curationStatus: nextStatus,
      curationStatusKey: `${normalizeRequiredString(reference.corpusId, "reference.corpusId")}#${nextStatus}`,
      curationStatusUpdatedAt: now,
      curationStatusUpdatedBy: actor,
      curationStatusReason: note,
      newsroomFeedKey: reference.newsroomFeedKey ?? "references",
      reviewedFeedKey: reviewedFeedKeyForStatus(nextStatus),
      updatedAt: now,
    }),
    "update Reference quality status",
  );

  if (currentStatus !== nextStatus) {
    await updateNewsroomSummaryForReferenceStatus(client, {
      corpusId: normalizeOptionalString(reference.corpusId),
      previousStatus: currentStatus,
      nextStatus,
      now,
    });
  }

  return {
    ok: true,
    referenceId,
    rating,
    status: nextStatus,
    relationId,
  };
}

async function createReferenceInsight(event: Parameters<ReferenceInsightHandler>[0]) {
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const summary = normalizeRequiredString(event.arguments.summary, "summary");
  const body = normalizeRequiredString(event.arguments.body, "body");
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const actor = actorLabel ?? actorSub ?? "Papyrus newsroom";
  const referenceLineageId = normalizeOptionalString(reference.lineageId) ?? referenceId;
  const messageId = `message-reference-insight-${safeId(referenceLineageId)}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const relationId = `semantic-relation-${hashStable([
    `message#${messageId}`,
    "insight_about",
    `reference#${referenceId}`,
  ]).slice(0, 24)}`;

  await requireDataResult(
    client.models.Message.create({
      ...buildCanonicalMessageInput({
        id: messageId,
        messageKind: "insight",
        messageDomain: "knowledge",
        summary,
        source: "newsroom",
        authorSub: actorSub,
        authorLabel: actor,
        now,
      }),
      threadId: messageId,
      sequenceNumber: 1,
    }),
    "create insight Message",
  );
  await putTextModelPayload(
    client as any,
    { ownerKind: "message", ownerId: messageId, ownerLineageId: messageId },
    "message_body",
    "message",
    body,
    { filename: "message.md", mediaType: "text/markdown", now },
  );
  await putJsonModelPayload(
    client as any,
    { ownerKind: "message", ownerId: messageId, ownerLineageId: messageId },
    "metadata",
    "metadata",
    {
      kind: "reference.insight.created",
      targetKind: "reference",
      targetId: referenceId,
      targetLineageId: referenceLineageId,
    },
    { filename: "metadata.json", now },
  );
  await requireDataResult(
    client.models.SemanticRelation.create({
      id: relationId,
      relationState: "current",
      predicate: "insight_about",
      ...semanticRelationTypeFieldsForPredicate("insight_about"),
      subjectKind: "message",
      subjectId: messageId,
      subjectLineageId: messageId,
      subjectVersionNumber: 1,
      objectKind: "reference",
      objectId: referenceId,
      objectLineageId: referenceLineageId,
      objectVersionNumber: typeof reference.versionNumber === "number" ? reference.versionNumber : null,
      subjectStateKey: semanticStateKey("message", messageId),
      objectStateKey: semanticStateKey("reference", referenceLineageId),
      objectSubjectStateKey: `${semanticStateKey("reference", referenceLineageId)}#message`,
      predicateObjectStateKey: `insight_about#${semanticStateKey("reference", referenceLineageId)}`,
      subjectVersionKey: semanticVersionKey("message", messageId),
      objectVersionKey: semanticVersionKey("reference", referenceId),
      score: 1,
      confidence: null,
      rank: 1,
      classifierId: null,
      modelVersion: null,
      reviewRecommended: false,
      sourceSnapshotId: null,
      importRunId: null,
      importedAt: now,
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: "semanticRelations",
      metadata: JSON.stringify({
        kind: "reference.insight",
        summary,
        actor,
      }),
    }),
    "create insight_about relation",
  );
  await updateNewsroomSummaryForSemanticRelationDelta(
    client,
    {
      relationTypeKey: "insight_about",
      relationDomain: "commentary",
      subjectKind: "message",
      objectKind: "reference",
    },
    1,
    now,
  );
  return {
    ok: true,
    referenceId,
    messageId,
    relationId,
    status: "created",
  };
}

async function moveReferenceCorpus(event: Parameters<MoveReferenceCorpusHandler>[0]) {
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const targetCorpusId = normalizeRequiredString(event.arguments.corpusId, "corpusId");
  const requested = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const referenceLineageId = normalizeOptionalString(requested.lineageId) ?? referenceId;
  const lineageVersions = await listReferenceVersionsByLineage(client, referenceLineageId);
  const current = selectCurrentReferenceVersion(lineageVersions) ?? requested;
  const previousCorpusId = normalizeRequiredString(current.corpusId, "reference.corpusId");
  if (previousCorpusId === targetCorpusId) {
    return {
      ok: true,
      referenceId: normalizeRequiredString(current.id, "reference.id"),
      referenceLineageId,
      previousReferenceId: normalizeRequiredString(current.id, "reference.id"),
      previousCorpusId,
      corpusId: targetCorpusId,
      status: "unchanged",
    };
  }

  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const actor = actorLabel ?? actorSub ?? "Papyrus newsroom";
  const nextVersionNumber = Math.max(
    ...lineageVersions.map((entry) => normalizeOptionalPositiveInteger(entry.versionNumber) ?? 0),
    normalizeOptionalPositiveInteger(current.versionNumber) ?? 0,
  ) + 1;
  const nextReferenceId = `reference-${safeId(referenceLineageId)}-v${nextVersionNumber}-${randomUUID().slice(0, 8)}`;
  const curationStatus = normalizeOptionalString(current.curationStatus) ?? "pending";

  if (normalizeOptionalString(current.versionState) === "current") {
    await requireDataResult(
      client.models.Reference.update({
        id: normalizeRequiredString(current.id, "reference.id"),
        versionState: "superseded",
        updatedAt: now,
      }),
      "supersede current Reference version",
    );
  }

  await requireDataResult(
    client.models.Reference.create({
      id: nextReferenceId,
      lineageId: referenceLineageId,
      versionNumber: nextVersionNumber,
      previousVersionId: normalizeRequiredString(current.id, "reference.id"),
      versionState: "current",
      versionCreatedAt: now,
      versionCreatedBy: actor,
      changeReason: normalizeOptionalString(event.arguments.note) ?? `move-corpus:${previousCorpusId}->${targetCorpusId}`,
      contentHash: normalizeOptionalString(current.contentHash),
      corpusId: targetCorpusId,
      externalItemId: normalizeRequiredString(current.externalItemId, "reference.externalItemId"),
      title: normalizeOptionalString(current.title),
      authors: compactStringArray(current.authors) ?? [],
      sourceUri: normalizeOptionalString(current.sourceUri),
      storagePath: normalizeOptionalString(current.storagePath),
      mediaType: normalizeOptionalString(current.mediaType),
      byteSize: normalizeOptionalPositiveInteger(current.byteSize),
      sha256: normalizeOptionalString(current.sha256),
      sourcePublishedAt: normalizeOptionalString(current.sourcePublishedAt),
      sourceUpdatedAt: normalizeOptionalString(current.sourceUpdatedAt),
      retrievedAt: normalizeOptionalString(current.retrievedAt),
      importRunId: normalizeOptionalString(current.importRunId),
      importedAt: normalizeOptionalString(current.importedAt),
      createdAt: normalizeOptionalString(current.createdAt) ?? now,
      curationStatus,
      curationStatusKey: `${targetCorpusId}#${curationStatus}`,
      curationStatusUpdatedAt: normalizeOptionalString(current.curationStatusUpdatedAt) ?? now,
      curationStatusUpdatedBy: normalizeOptionalString(current.curationStatusUpdatedBy) ?? actor,
      curationStatusReason: normalizeOptionalString(current.curationStatusReason),
      newsroomFeedKey: normalizeOptionalString(current.newsroomFeedKey) ?? "references",
      reviewedFeedKey: normalizeOptionalString(current.reviewedFeedKey) ?? reviewedFeedKeyForStatus(curationStatus),
      updatedAt: now,
    }),
    "create moved Reference version",
  );

  return {
    ok: true,
    referenceId: nextReferenceId,
    referenceLineageId,
    previousReferenceId: normalizeRequiredString(current.id, "reference.id"),
    previousCorpusId,
    corpusId: targetCorpusId,
    status: "moved",
  };
}

async function startReferenceCuration(event: Parameters<StartReferenceCurationHandler>[0]) {
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const referenceLineageId = normalizeOptionalString(reference.lineageId) ?? referenceId;
  const queueKey = `curation:reference-refresh:${referenceLineageId}`;
  const existing = [
    ...(await listAssignmentsByQueueStatus(client, `${queueKey}#open`)),
    ...(await listAssignmentsByQueueStatus(client, `${queueKey}#claimed`)),
  ].sort((left, right) => assignmentSortKey(left).localeCompare(assignmentSortKey(right)))[0];
  if (existing?.id) {
    return {
      ok: true,
      referenceId: normalizeRequiredString(reference.id, "reference.id"),
      assignmentId: normalizeRequiredString(existing.id, "assignment.id"),
      status: assignmentLifecycleStatusFromAssignmentStatus(normalizeOptionalString(existing.status) ?? "open"),
      runId: normalizeRequiredString(existing.id, "assignment.id"),
    };
  }

  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const actor = actorLabel ?? actorSub ?? "Papyrus newsroom";
  const policy = normalizeReferenceCurationPolicy(event.arguments.curationPolicy);
  const assignmentId = `assignment-reference-curation-${safeId(referenceLineageId)}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const runId = assignmentId;
  const assignmentTypeKey = REFERENCE_CURATION_ASSIGNMENT_TYPE;
  const relationId = `semantic-relation-${hashStable([
    `assignment#${assignmentId}`,
    "requests_work_on",
    `reference#${reference.id}`,
  ]).slice(0, 24)}`;

  await requireDataResult(
    client.models.Assignment.create({
      id: assignmentId,
      assignmentTypeKey,
      queueKey,
      queueStatusKey: `${queueKey}#open`,
      status: "open",
      priority: 50,
      title: `Re-curate reference: ${normalizeOptionalString(reference.title) ?? normalizeOptionalString(reference.externalItemId) ?? referenceId}`,
      summary: "Recompute identifier, publication date, title/subtitle, summary, and topic predictions.",
      assigneeType: null,
      assigneeId: null,
      assigneeKey: null,
      claimedAt: null,
      claimExpiresAt: null,
      completedAt: null,
      canceledAt: null,
      corpusId: normalizeRequiredString(reference.corpusId, "reference.corpusId"),
      categorySetId: null,
      classifierId: null,
      sectionId: null,
      sectionKey: null,
      sectionType: null,
      sectionStatusKey: null,
      sectionQueueStatusKey: null,
      primaryFocusCategoryKey: null,
      topicScopeCategoryKeys: [],
      sourceSnapshotId: null,
      importRunId: null,
      createdBy: actor,
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: "assignments",
    }),
    "create curation Assignment",
  );
  await requireDataResult(
    client.models.AssignmentEvent.create({
      id: `assignment-event-${assignmentId}-created`,
      assignmentId,
      assignmentTypeKey,
      queueKey,
      eventType: "created",
      fromStatus: null,
      toStatus: "open",
      actorSub,
      actorLabel: actor,
      note: "Queued reference re-curation assignment.",
      createdAt: now,
    }),
    "create curation AssignmentEvent",
  );
  await requireDataResult(
    client.models.SemanticRelation.create({
      id: relationId,
      relationState: "current",
      predicate: "requests_work_on",
      ...semanticRelationTypeFieldsForPredicate("requests_work_on"),
      subjectKind: "assignment",
      subjectId: assignmentId,
      subjectLineageId: assignmentId,
      subjectVersionNumber: 1,
      objectKind: "reference",
      objectId: normalizeRequiredString(reference.id, "reference.id"),
      objectLineageId: referenceLineageId,
      objectVersionNumber: typeof reference.versionNumber === "number" ? reference.versionNumber : null,
      subjectStateKey: semanticStateKey("assignment", assignmentId),
      objectStateKey: semanticStateKey("reference", referenceLineageId),
      objectSubjectStateKey: `${semanticStateKey("reference", referenceLineageId)}#assignment`,
      predicateObjectStateKey: `requests_work_on#${semanticStateKey("reference", referenceLineageId)}`,
      subjectVersionKey: semanticVersionKey("assignment", assignmentId),
      objectVersionKey: semanticVersionKey("reference", normalizeRequiredString(reference.id, "reference.id")),
      score: 1,
      confidence: null,
      rank: 1,
      classifierId: null,
      modelVersion: null,
      reviewRecommended: false,
      sourceSnapshotId: null,
      importRunId: null,
      importedAt: now,
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: "semanticRelations",
      metadata: JSON.stringify({
        kind: "reference.curation.assignment",
        runId,
        curationPolicy: policy,
      }),
    }),
    "create requests_work_on relation",
  );
  await putJsonModelPayload(
    client as any,
    { ownerKind: "assignment", ownerId: assignmentId, ownerLineageId: assignmentId },
    "metadata",
    "reference_curation_status",
    {
      kind: "reference.curation.status",
      runId,
      assignmentId,
      referenceId: normalizeRequiredString(reference.id, "reference.id"),
      referenceLineageId,
      corpusId: normalizeRequiredString(reference.corpusId, "reference.corpusId"),
      curationPolicy: policy,
      lifecycleStatus: "queued",
      status: "queued",
      stageStatuses: defaultReferenceCurationStageStatuses("queued"),
      changedOutputs: {},
      error: null,
      updatedAt: now,
    },
    { filename: "reference-curation-status.json", now },
  );
  return {
    ok: true,
    referenceId: normalizeRequiredString(reference.id, "reference.id"),
    assignmentId,
    status: "queued",
    runId,
  };
}

async function getReferenceCurationStatus(event: Parameters<GetReferenceCurationStatusHandler>[0]) {
  const client = await getDataClient();
  const assignmentId = normalizeRequiredString(event.arguments.assignmentId, "assignmentId");
  const assignment = await getRequiredRecord(client.models.Assignment, assignmentId, "Assignment");
  const payload = await readJsonModelPayload(
    client as any,
    "assignment",
    assignmentId,
    "metadata",
    "reference_curation_status",
  );
  const assignmentStatus = normalizeOptionalString(assignment.status) ?? "open";
  const lifecycleStatus = normalizeOptionalString(payload?.lifecycleStatus)
    ?? assignmentLifecycleStatusFromAssignmentStatus(assignmentStatus);
  const stageStatuses = (payload?.stageStatuses && typeof payload.stageStatuses === "object" && !Array.isArray(payload.stageStatuses))
    ? payload.stageStatuses
    : defaultReferenceCurationStageStatuses(lifecycleStatus);

  return {
    ok: true,
    referenceId: normalizeOptionalString(payload?.referenceId),
    assignmentId,
    status: lifecycleStatus,
    runId: normalizeOptionalString(payload?.runId) ?? assignmentId,
    lifecycleStatus,
    stageStatuses,
    changedOutputs: (payload?.changedOutputs && typeof payload.changedOutputs === "object" && !Array.isArray(payload.changedOutputs))
      ? payload.changedOutputs
      : {},
    error: payload?.error ?? null,
  };
}

async function createCategorySetDraft(event: Parameters<CreateCategorySetDraftHandler>[0]) {
  const client = await getDataClient();
  const sourceCategorySetId = normalizeRequiredString(event.arguments.sourceCategorySetId, "sourceCategorySetId");
  const source = await getRequiredRecord(client.models.CategorySet, sourceCategorySetId, "CategorySet");
  if (source.versionState !== "current" || source.status !== "accepted") {
    throw new Error(`CategorySet ${sourceCategorySetId} is ${source.versionState}/${source.status}; create drafts from the accepted current set.`);
  }
  const sourceCategories = (await listCategoriesForSet(client, sourceCategorySetId))
    .filter((category) => category.versionState !== "superseded" && category.status !== "archived" && category.status !== "deprecated")
    .sort(compareCategoryRank);
  const now = new Date().toISOString();
  const actor = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? getIdentitySub(event) ?? "Papyrus newsroom";
  const lineageId = normalizeOptionalString(source.lineageId) ?? source.id;
  const versionNumber = Number(source.versionNumber ?? 0) + 1;
  const draftId = `category-set-${safeId(lineageId)}-draft-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const displayName = normalizeOptionalString(event.arguments.displayName) ?? `${source.displayName} Draft`;
  const draftCategoryIdBySourceId = new Map<string, string>();
  for (const category of sourceCategories) {
    draftCategoryIdBySourceId.set(
      normalizeRequiredString(category.id, "category.id"),
      `category-${safeId(draftId)}-${safeId(category.categoryKey)}-${randomUUID().slice(0, 8)}`,
    );
  }
  const draftSet = {
    id: draftId,
    lineageId,
    versionNumber,
    previousVersionId: source.id,
    versionState: "draft",
    versionCreatedAt: now,
    versionCreatedBy: actor,
    changeReason: normalizeOptionalString(event.arguments.note) ?? `draft from ${source.id}`,
    contentHash: "",
    corpusId: source.corpusId,
    classifierId: source.classifierId,
    displayName,
    description: source.description ?? null,
    status: "draft",
    generatedAt: now,
    categoryCount: sourceCategories.length,
    importRunId: source.importRunId ?? null,
  };
  await requireDataResult(
    client.models.CategorySet.create({ ...draftSet, contentHash: hashStable({ ...draftSet, contentHash: undefined }) }),
    "create CategorySet draft",
  );
  for (const category of sourceCategories) {
    const categoryId = normalizeRequiredString(category.id, "category.id");
    const parentCategoryId = normalizeOptionalString(category.parentCategoryId);
    const draftCategory = {
      id: draftCategoryIdBySourceId.get(categoryId) ?? `category-${safeId(draftId)}-${safeId(category.categoryKey)}-${randomUUID().slice(0, 8)}`,
      lineageId: normalizeOptionalString(category.lineageId) ?? `category-${safeId(draftId)}-${safeId(category.categoryKey)}`,
      previousVersionId: categoryId,
      versionNumber: Number(category.versionNumber ?? 0) + 1,
      versionState: "draft",
      versionCreatedAt: now,
      versionCreatedBy: actor,
      changeReason: `draft from ${category.id}`,
      categorySetId: draftId,
      corpusId: category.corpusId,
      categoryKey: category.categoryKey,
      parentCategoryId: parentCategoryId ? draftCategoryIdBySourceId.get(parentCategoryId) ?? null : null,
      parentCategoryKey: category.parentCategoryKey ?? null,
      displayName: category.displayName,
      shortTitle: category.shortTitle ?? null,
      subtitle: category.subtitle ?? null,
      description: category.description ?? null,
      aliases: compactStringArray(category.aliases) ?? [],
      status: category.status,
      seedItemIds: compactStringArray(category.seedItemIds) ?? [],
      holdoutItemIds: compactStringArray(category.holdoutItemIds) ?? [],
      rank: category.rank ?? null,
      depth: category.depth ?? null,
      isPinned: Boolean(category.isPinned),
      importRunId: category.importRunId ?? null,
      contentHash: "",
      updatedAt: now,
    };
    await requireDataResult(
      client.models.Category.create({
        ...draftCategory,
        contentHash: hashStable({ ...draftCategory, contentHash: undefined }),
      }),
      "create draft Category",
    );
  }
  return {
    ok: true,
    action: "create_draft",
    categorySetId: draftId,
    sourceCategorySetId,
    categoryCount: sourceCategories.length,
    status: "draft",
  };
}

async function promoteCategorySetDraft(event: Parameters<PromoteCategorySetDraftHandler>[0]) {
  const client = await getDataClient();
  const categorySetId = normalizeRequiredString(event.arguments.categorySetId, "categorySetId");
  const draft = await getRequiredRecord(client.models.CategorySet, categorySetId, "CategorySet");
  if (draft.versionState !== "draft") throw new Error(`CategorySet ${categorySetId} is ${draft.versionState}; only drafts can be promoted.`);
  const now = new Date().toISOString();
  const actor = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? getIdentitySub(event) ?? "Papyrus newsroom";
  const currentSets = await listCategorySetsByLineage(client, normalizeRequiredString(draft.lineageId, "draft.lineageId"));
  for (const categorySet of currentSets.filter((entry) => entry.id !== draft.id && entry.versionState === "current")) {
    await requireDataResult(
      client.models.CategorySet.update({
        id: categorySet.id,
        versionState: "superseded",
        status: "superseded",
        changeReason: `superseded by ${draft.id}`,
      }),
      "supersede CategorySet",
    );
  }
  const categories = await listCategoriesForSet(client, categorySetId);
  const activeCount = categories.filter((category) => category.status !== "archived" && category.status !== "deprecated").length;
  await requireDataResult(
    client.models.CategorySet.update({
      id: draft.id,
      versionState: "current",
      status: "accepted",
      versionCreatedBy: actor,
      changeReason: normalizeOptionalString(event.arguments.note) ?? "draft promoted",
      generatedAt: now,
      categoryCount: activeCount,
    }),
    "promote CategorySet",
  );
  for (const category of categories) {
    await requireDataResult(
      client.models.Category.update({
        id: category.id,
        versionState: "current",
        updatedAt: now,
      }),
      "promote Category",
    );
  }
  return {
    ok: true,
    action: "promote_draft",
    categorySetId,
    sourceCategorySetId: draft.previousVersionId ?? null,
    categoryCount: activeCount,
    status: "accepted",
  };
}

async function discardCategorySetDraft(event: Parameters<DiscardCategorySetDraftHandler>[0]) {
  const client = await getDataClient();
  const categorySetId = normalizeRequiredString(event.arguments.categorySetId, "categorySetId");
  normalizeRequiredString(event.arguments.note, "note");
  const draft = await requireDraftCategorySet(client, categorySetId);
  const categories = await listCategoriesForSet(client, categorySetId);
  const semanticRelations = await listSemanticRelationsForDraftCategories(client, categories);
  const categoryKeywords = await listCategoryKeywordsForSet(client, categorySetId);
  const lexicalSteeringRules = await listLexicalSteeringRulesForSet(client, categorySetId);

  for (const relation of semanticRelations) {
    await requireDataResult((client.models.SemanticRelation as any).delete({ id: relation.id }), "delete draft SemanticRelation");
  }
  for (const keyword of categoryKeywords) {
    await requireDataResult((client.models.CategoryKeyword as any).delete({ id: keyword.id }), "delete draft CategoryKeyword");
  }
  for (const rule of lexicalSteeringRules) {
    await requireDataResult((client.models.LexicalSteeringRule as any).delete({ id: rule.id }), "delete draft LexicalSteeringRule");
  }
  for (const category of categories) {
    await requireDataResult(client.models.Category.delete({ id: category.id }), "delete draft Category");
  }
  await requireDataResult(client.models.CategorySet.delete({ id: draft.id }), "delete draft CategorySet");

  return {
    ok: true,
    action: "discard_draft",
    categorySetId,
    sourceCategorySetId: draft.previousVersionId ?? null,
    categoryCount: categories.length,
    status: "deleted",
  };
}

async function createDraftCategory(event: Parameters<CreateDraftCategoryHandler>[0]) {
  const client = await getDataClient();
  const categorySetId = normalizeRequiredString(event.arguments.categorySetId, "categorySetId");
  const categorySet = await requireDraftCategorySet(client, categorySetId);
  const now = new Date().toISOString();
  const actor = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? getIdentitySub(event) ?? "Papyrus newsroom";
  const displayName = normalizeRequiredString(event.arguments.displayName, "displayName");
  const categoryKey = await uniqueCategoryKey(client, categorySetId, deriveCategoryKey(displayName));
  const parentCategoryKey = normalizeOptionalString(event.arguments.parentCategoryKey);
  const depth = await categoryDepthForParent(client, categorySetId, parentCategoryKey);
  const lineageId = `category-${safeId(categorySetId)}-${safeId(categoryKey)}`;
  const category = {
    id: `${lineageId}-v1`,
    lineageId,
    versionNumber: 1,
    previousVersionId: null,
    versionState: "draft",
    versionCreatedAt: now,
    versionCreatedBy: actor,
    changeReason: normalizeOptionalString(event.arguments.note) ?? "manual draft topic",
    contentHash: "",
    categorySetId,
    corpusId: categorySet.corpusId,
    categoryKey,
    parentCategoryId: null,
    parentCategoryKey,
    displayName,
    shortTitle: normalizeOptionalString(event.arguments.shortTitle) ?? deriveShortTitle(displayName),
    subtitle: normalizeOptionalString(event.arguments.subtitle),
    description: normalizeOptionalString(event.arguments.description),
    aliases: [],
    status: "accepted",
    seedItemIds: [],
    holdoutItemIds: [],
    rank: null,
    depth,
    isPinned: false,
    importRunId: categorySet.importRunId ?? null,
    updatedAt: now,
  };
  await requireDataResult(
    client.models.Category.create({ ...category, contentHash: hashStable({ ...category, contentHash: undefined }) }),
    "create draft Category",
  );
  await refreshCategorySetCount(client, categorySetId);
  return {
    ok: true,
    action: "create_draft_category",
    proposalId: null,
    categorySetId,
    categoryId: category.id,
    decisionId: null,
    status: "draft",
  };
}

async function updateDraftCategory(event: Parameters<UpdateDraftCategoryHandler>[0]) {
  const client = await getDataClient();
  const categoryId = normalizeRequiredString(event.arguments.categoryId, "categoryId");
  const category = await getRequiredRecord(client.models.Category, categoryId, "Category");
  await requireDraftCategorySet(client, normalizeRequiredString(category.categorySetId, "category.categorySetId"));
  if (category.versionState !== "draft") throw new Error(`Category ${categoryId} is ${category.versionState}; only draft categories can be edited.`);
  const now = new Date().toISOString();
  const displayName = normalizeOptionalString(event.arguments.displayName) ?? category.displayName;
  const parentCategoryKey = normalizeOptionalString(event.arguments.parentCategoryKey);
  const parentChanged = parentCategoryKey !== normalizeOptionalString(category.parentCategoryKey);
  const nextParentCategoryKey = parentChanged ? parentCategoryKey : category.parentCategoryKey ?? null;
  const next = {
    ...category,
    displayName,
    shortTitle: normalizeOptionalString(event.arguments.shortTitle) ?? category.shortTitle ?? deriveShortTitle(displayName),
    subtitle: normalizeOptionalString(event.arguments.subtitle),
    description: normalizeOptionalString(event.arguments.description),
    parentCategoryKey: nextParentCategoryKey,
    depth: await categoryDepthForParent(client, category.categorySetId, nextParentCategoryKey),
    changeReason: normalizeOptionalString(event.arguments.note) ?? "manual draft topic edit",
    updatedAt: now,
  };
  await requireDataResult(
    client.models.Category.update({
      id: categoryId,
      displayName: next.displayName,
      shortTitle: next.shortTitle,
      subtitle: next.subtitle,
      description: next.description,
      parentCategoryKey: next.parentCategoryKey,
      depth: next.depth,
      changeReason: next.changeReason,
      contentHash: hashStable({ ...next, contentHash: undefined }),
      updatedAt: now,
    }),
    "update draft Category",
  );
  return {
    ok: true,
    action: "update_draft_category",
    proposalId: null,
    categorySetId: category.categorySetId,
    categoryId,
    decisionId: null,
    status: "draft",
  };
}

async function archiveDraftCategory(event: Parameters<ArchiveDraftCategoryHandler>[0]) {
  const client = await getDataClient();
  const categoryId = normalizeRequiredString(event.arguments.categoryId, "categoryId");
  const category = await getRequiredRecord(client.models.Category, categoryId, "Category");
  await requireDraftCategorySet(client, normalizeRequiredString(category.categorySetId, "category.categorySetId"));
  if (category.versionState !== "draft") throw new Error(`Category ${categoryId} is ${category.versionState}; only draft categories can be archived.`);
  const now = new Date().toISOString();
  await requireDataResult(
    client.models.Category.update({
      id: categoryId,
      status: "deprecated",
      changeReason: normalizeOptionalString(event.arguments.note) ?? "manual draft topic archive",
      updatedAt: now,
    }),
    "archive draft Category",
  );
  await refreshCategorySetCount(client, category.categorySetId);
  return {
    ok: true,
    action: "archive_draft_category",
    proposalId: null,
    categorySetId: category.categorySetId,
    categoryId,
    decisionId: null,
    status: "deprecated",
  };
}

async function reviewReferenceTopicLabel(event: Parameters<ReviewReferenceTopicLabelHandler>[0]) {
  const client = await getDataClient();
  const action = normalizeTopicLabelAction(event.arguments.action);
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const categoryId = normalizeRequiredString(event.arguments.categoryId, "categoryId");
  const sourceRelationId = normalizeOptionalString(event.arguments.sourceRelationId);
  const now = new Date().toISOString();
  const actor = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? getIdentitySub(event) ?? "Papyrus newsroom";
  const note = normalizeOptionalString(event.arguments.note);
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const category = await getRequiredRecord(client.models.Category, categoryId, "Category");
  if (action === "reject_prediction") {
    if (!sourceRelationId) throw new Error("sourceRelationId is required to reject a prediction.");
    const source = await getRequiredSemanticRelation(client, sourceRelationId, "classified_as");
    await requireDataResult((client.models.SemanticRelation as any).delete({ id: source.id }), "delete classified_as prediction");
    await updateNewsroomSummaryForSemanticRelationDelta(client, source, -1, now);
    return { ok: true, action, referenceId, categoryId, relationId: null, sourceRelationId, status: "deleted_prediction" };
  }
  if (action === "unlabel") {
    if (!sourceRelationId) throw new Error("sourceRelationId is required to remove an authoritative label.");
    const source = await getRequiredSemanticRelation(client, sourceRelationId, "authoritative_label");
    await requireDataResult((client.models.SemanticRelation as any).delete({ id: source.id }), "delete authoritative_label");
    await updateNewsroomSummaryForSemanticRelationDelta(client, source, -1, now);
    return { ok: true, action, referenceId, categoryId, relationId: null, sourceRelationId, status: "deleted_authoritative_label" };
  }
  if (!isAcceptedCurrentReference(reference)) {
    throw new Error(`Reference ${referenceId} is ${reference.versionState}/${reference.curationStatus}; authoritative labels require a current accepted Reference.`);
  }
  let sourcePrediction: any | null = null;
  if (action === "accept_prediction") {
    if (!sourceRelationId) throw new Error("sourceRelationId is required to accept a prediction.");
    sourcePrediction = await getRequiredSemanticRelation(client, sourceRelationId, "classified_as");
  }
  const relation = buildAuthoritativeLabelRelation({
    reference,
    category,
    now,
    actor,
    note,
    sourceMode: action === "accept_prediction" ? "accepted_prediction" : "manual",
    sourceRelationId: sourcePrediction?.id ?? null,
  });
  const existing = await findCurrentSemanticRelationByState(client, "authoritative_label", relation.subjectStateKey, relation.objectStateKey);
  if (!existing) {
    await requireDataResult(client.models.SemanticRelation.create(relation), "create authoritative_label");
    await updateNewsroomSummaryForSemanticRelationDelta(client, relation, 1, now);
  }
  return {
    ok: true,
    action,
    referenceId,
    categoryId,
    relationId: existing?.id ?? relation.id,
    sourceRelationId: sourcePrediction?.id ?? sourceRelationId ?? null,
    status: existing ? "idempotent" : "created_authoritative_label",
  };
}

function shouldApplySteeringProposalToCategory(proposal: any): boolean {
  const proposalKind = normalizeOptionalString(proposal.proposalKind);
  return Boolean(
    proposal.categorySetId
      && proposal.categoryKey
      && proposalKind
      && CATEGORY_PROPOSAL_KINDS.has(proposalKind),
  );
}

async function createCategoryVersionFromProposal(
  client: DataClient,
  proposal: any,
  args: Parameters<ReviewHandler>[0]["arguments"],
  options: { actorLabel: string; now: string; reason: string },
): Promise<string> {
  const categorySetId = normalizeRequiredString(proposal.categorySetId, "proposal.categorySetId");
  const categoryKey = normalizeRequiredString(proposal.categoryKey, "proposal.categoryKey");
  const proposalKind = normalizeOptionalString(proposal.proposalKind);
  const current = await findCurrentCategory(client, categorySetId, categoryKey);
  const lineageId = current?.lineageId ?? `category-${safeId(categorySetId)}-${safeId(categoryKey)}`;
  const versionNumber = Number(current?.versionNumber ?? 0) + 1;
  const categoryId = `${lineageId}-v${versionNumber}`;
  const nextStatus = proposalKind === "archive-category" || proposalKind === "deprecate-category" ? "archived" : "accepted";
  const nextParentCategoryKey = proposalKind === "move-category" || proposalKind === "create-category"
    ? normalizeOptionalString(proposal.targetCategoryKey)
    : current?.parentCategoryKey ?? normalizeOptionalString(proposal.targetCategoryKey);
  const depth = await categoryDepthForParent(client, categorySetId, nextParentCategoryKey);
  const input = {
    id: categoryId,
    lineageId,
    versionNumber,
    previousVersionId: current?.id ?? null,
    versionState: "current",
    versionCreatedAt: options.now,
    versionCreatedBy: options.actorLabel,
    changeReason: options.reason,
    contentHash: "",
    categorySetId,
    corpusId: proposal.corpusId,
    categoryKey,
    parentCategoryId: null,
    parentCategoryKey: nextParentCategoryKey,
    displayName: normalizeOptionalString(args.displayName) ?? proposal.displayName ?? current?.displayName ?? proposal.title,
    shortTitle: normalizeOptionalString(args.shortTitle) ?? proposal.shortTitle ?? current?.shortTitle ?? deriveShortTitle(proposal.displayName ?? current?.displayName ?? proposal.title),
    subtitle: normalizeOptionalString(args.subtitle) ?? proposal.subtitle ?? current?.subtitle ?? null,
    description: normalizeOptionalString(args.description) ?? proposal.description ?? proposal.summary ?? current?.description ?? null,
    aliases: normalizeStringArray(args.aliases) ?? current?.aliases ?? [],
    status: nextStatus,
    seedItemIds: normalizeStringArray(args.seedItemIds) ?? compactStringArray(proposal.suggestedSeedItemIds) ?? current?.seedItemIds ?? [],
    holdoutItemIds: normalizeStringArray(args.holdoutItemIds) ?? compactStringArray(proposal.suggestedHoldoutItemIds) ?? current?.holdoutItemIds ?? [],
    rank: current?.rank ?? null,
    depth,
    isPinned: current?.isPinned ?? false,
    importRunId: proposal.importRunId ?? current?.importRunId ?? null,
    updatedAt: options.now,
  };
  const contentHash = hashStable({ ...input, contentHash: undefined });

  if (current?.id) {
    await requireDataResult(
      client.models.Category.update({ id: current.id, versionState: "superseded", updatedAt: options.now }),
      "supersede Category",
    );
  }
  await requireDataResult(client.models.Category.create({ ...input, contentHash }), "create Category version");
  return categoryId;
}

async function findCurrentCategory(client: DataClient, categorySetId: string, categoryKey: string): Promise<any | null> {
  const records = await listCategoriesForSet(client, categorySetId);
  return records
    .filter((category) => category.categoryKey === categoryKey && category.versionState === "current")
    .sort((left, right) => Number(right.versionNumber ?? 0) - Number(left.versionNumber ?? 0))[0]
    ?? records
      .filter((category) => category.categoryKey === categoryKey)
      .sort((left, right) => Number(right.versionNumber ?? 0) - Number(left.versionNumber ?? 0))[0]
    ?? null;
}

async function listCategoriesForSet(client: DataClient, categorySetId: string): Promise<any[]> {
  const model = client.models.Category as any;
  let nextToken: string | null | undefined;
  const records: any[] = [];
  do {
    const page = await model.listCategoriesBySetAndKey(
      { categorySetId },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list Category");
    records.push(...(page.data ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return records;
}

async function listCategoryKeywordsForSet(client: DataClient, categorySetId: string): Promise<any[]> {
  const model = client.models.CategoryKeyword as any;
  let nextToken: string | null | undefined;
  const records: any[] = [];
  do {
    const page = await model.listCategoryKeywordsBySetKeyAndRank(
      { categorySetId },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list CategoryKeyword");
    records.push(...(page.data ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return records;
}

async function listLexicalSteeringRulesForSet(client: DataClient, categorySetId: string): Promise<any[]> {
  const model = client.models.LexicalSteeringRule as any;
  let nextToken: string | null | undefined;
  const records: any[] = [];
  do {
    const page = await model.listLexicalSteeringRulesBySetAndTerm(
      { categorySetId },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list LexicalSteeringRule");
    records.push(...(page.data ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return records;
}

async function listSemanticRelationsForDraftCategories(client: DataClient, categories: any[]): Promise<any[]> {
  const model = client.models.SemanticRelation as any;
  const categoryIds = new Set(categories.map((category) => normalizeOptionalString(category.id)).filter(Boolean));
  const relationById = new Map<string, any>();
  for (const category of categories) {
    const lineageId = normalizeOptionalString(category.lineageId);
    if (!lineageId) continue;
    let nextToken: string | null | undefined;
    do {
      const page = await model.listSemanticRelationsByObjectState(
        { objectStateKey: semanticStateKey("category", lineageId) },
        { limit: 100, nextToken },
      );
      assertNoDataErrors(page.errors, "list SemanticRelation");
      for (const relation of page.data ?? []) {
        if (relation?.objectKind === "category" && categoryIds.has(normalizeOptionalString(relation.objectId))) {
          relationById.set(relation.id, relation);
        }
      }
      nextToken = page.nextToken;
    } while (nextToken);
  }
  return Array.from(relationById.values());
}

async function listCategorySetsByLineage(client: DataClient, lineageId: string): Promise<any[]> {
  const model = client.models.CategorySet as any;
  let nextToken: string | null | undefined;
  const records: any[] = [];
  do {
    const page = await model.listCategorySetsByLineageAndVersion(
      { lineageId },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list CategorySet");
    records.push(...(page.data ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return records;
}

async function requireDraftCategorySet(client: DataClient, categorySetId: string): Promise<any> {
  const categorySet = await getRequiredRecord(client.models.CategorySet, categorySetId, "CategorySet");
  if (categorySet.versionState !== "draft" || categorySet.status !== "draft") {
    throw new Error(`CategorySet ${categorySetId} is ${categorySet.versionState}/${categorySet.status}; this operation requires a draft CategorySet.`);
  }
  return categorySet;
}

async function categoryDepthForParent(client: DataClient, categorySetId: string, parentCategoryKey: string | null): Promise<number> {
  if (!parentCategoryKey) return 0;
  const parent = await findCurrentCategory(client, categorySetId, parentCategoryKey);
  return (typeof parent?.depth === "number" ? parent.depth : 0) + 1;
}

function compareCategoryRank(left: any, right: any): number {
  const depthDiff = Number(left.depth ?? 0) - Number(right.depth ?? 0);
  if (depthDiff !== 0) return depthDiff;
  const rankDiff = Number(left.rank ?? 999999) - Number(right.rank ?? 999999);
  if (rankDiff !== 0) return rankDiff;
  return String(left.categoryKey ?? left.id).localeCompare(String(right.categoryKey ?? right.id));
}

function deriveCategoryKey(value: unknown): string {
  return safeId(value).replace(/-/g, "_") || "topic";
}

async function uniqueCategoryKey(client: DataClient, categorySetId: string, baseKey: string): Promise<string> {
  const existing = new Set((await listCategoriesForSet(client, categorySetId)).map((category) => normalizeOptionalString(category.categoryKey)).filter(Boolean));
  let candidate = baseKey || "topic";
  let suffix = 2;
  while (existing.has(candidate)) {
    candidate = `${baseKey || "topic"}_${suffix}`;
    suffix += 1;
  }
  return candidate;
}

async function refreshCategorySetCount(client: DataClient, categorySetId: string): Promise<void> {
  const categories = await listCategoriesForSet(client, categorySetId);
  const categoryCount = categories.filter((category) => (
    category.versionState !== "superseded"
    && category.status !== "archived"
    && category.status !== "deprecated"
  )).length;
  await requireDataResult(
    client.models.CategorySet.update({ id: categorySetId, categoryCount }),
    "update CategorySet count",
  );
}

type TopicLabelAction = "manual_label" | "accept_prediction" | "reject_prediction" | "unlabel";

function normalizeTopicLabelAction(value: unknown): TopicLabelAction {
  const action = normalizeRequiredString(value, "action").toLowerCase();
  if (action === "manual_label" || action === "accept_prediction" || action === "reject_prediction" || action === "unlabel") {
    return action;
  }
  throw new Error(`Unsupported topic label action ${action}.`);
}

function isAcceptedCurrentReference(reference: any): boolean {
  return reference.versionState === "current" && reference.curationStatus === "accepted";
}

async function getRequiredSemanticRelation(client: DataClient, relationId: string, relationTypeKey: string): Promise<any> {
  const relation = await getRequiredRecord(client.models.SemanticRelation, relationId, "SemanticRelation");
  const key = normalizeOptionalString(relation.relationTypeKey) ?? normalizeOptionalString(relation.predicate);
  if (key !== relationTypeKey) {
    throw new Error(`SemanticRelation ${relationId} is ${key ?? "unknown"}, not ${relationTypeKey}.`);
  }
  if (relation.relationState && relation.relationState !== "current") {
    throw new Error(`SemanticRelation ${relationId} is ${relation.relationState}; only current relations can be reviewed.`);
  }
  return relation;
}

async function findCurrentSemanticRelationByState(
  client: DataClient,
  relationTypeKey: string,
  subjectStateKey: string,
  objectStateKey: string,
): Promise<any | null> {
  const model = client.models.SemanticRelation as any;
  let nextToken: string | null | undefined;
  do {
    const page = await model.listSemanticRelationsBySubjectState(
      { subjectStateKey },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list SemanticRelation by subject");
    const match = (page.data ?? []).find((relation: any) => (
      relation.relationState === "current"
      && relation.objectStateKey === objectStateKey
      && ((relation.relationTypeKey ?? relation.predicate) === relationTypeKey)
    ));
    if (match) return match;
    nextToken = page.nextToken;
  } while (nextToken);
  return null;
}

async function listCurrentSemanticRelationsBySubject(
  client: DataClient,
  relationTypeKey: string,
  subjectStateKey: string,
): Promise<any[]> {
  const model = client.models.SemanticRelation as any;
  let nextToken: string | null | undefined;
  const matches: any[] = [];
  do {
    const page = await model.listSemanticRelationsBySubjectState(
      { subjectStateKey },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list SemanticRelation by subject");
    for (const relation of page.data ?? []) {
      if (
        relation?.relationState === "current"
        && ((relation.relationTypeKey ?? relation.predicate) === relationTypeKey)
      ) {
        matches.push(relation);
      }
    }
    nextToken = page.nextToken;
  } while (nextToken);
  return matches;
}

function semanticRelationTypeFieldsForPredicate(predicate: string): {
  relationTypeId: string;
  relationTypeKey: string;
  relationDomain: string;
} {
  if (predicate === "authoritative_label") {
    return {
      relationTypeId: "semantic-relation-type-authoritative-label",
      relationTypeKey: "authoritative_label",
      relationDomain: "taxonomy",
    };
  }
  if (predicate === "classified_as") {
    return {
      relationTypeId: "semantic-relation-type-classified-as",
      relationTypeKey: "classified_as",
      relationDomain: "taxonomy",
    };
  }
  if (predicate === "quality_rating_is") {
    return {
      relationTypeId: "semantic-relation-type-quality-rating-is",
      relationTypeKey: "quality_rating_is",
      relationDomain: "curation",
    };
  }
  if (predicate === "insight_about") {
    return {
      relationTypeId: "semantic-relation-type-insight-about",
      relationTypeKey: "insight_about",
      relationDomain: "knowledge",
    };
  }
  if (predicate === "requests_work_on") {
    return {
      relationTypeId: "semantic-relation-type-requests-work-on",
      relationTypeKey: "requests_work_on",
      relationDomain: "workflow",
    };
  }
  return {
    relationTypeId: `semantic-relation-type-${safeId(predicate)}`,
    relationTypeKey: predicate,
    relationDomain: "semantic",
  };
}

async function listAssignmentsByQueueStatus(client: DataClient, queueStatusKey: string): Promise<any[]> {
  const model = client.models.Assignment as any;
  let nextToken: string | null | undefined;
  const rows: any[] = [];
  do {
    const page = await model.listAssignmentsByQueueStatusAndPriority(
      { queueStatusKey },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list Assignment by queue status");
    rows.push(...(page.data ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return rows;
}

function assignmentSortKey(assignment: any): string {
  const priority = typeof assignment?.priority === "number"
    ? assignment.priority
    : Number.parseInt(String(assignment?.priority ?? "50"), 10) || 50;
  const createdAt = normalizeOptionalString(assignment?.createdAt) ?? "";
  const id = normalizeOptionalString(assignment?.id) ?? "";
  return `${String(priority).padStart(6, "0")}#${createdAt}#${id}`;
}

async function listReferenceVersionsByLineage(client: DataClient, lineageId: string): Promise<any[]> {
  const model = client.models.Reference as any;
  let nextToken: string | null | undefined;
  const rows: any[] = [];
  do {
    const page = await model.listReferencesByLineageAndVersion(
      { lineageId },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(page.errors, "list Reference by lineage");
    rows.push(...(page.data ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return rows;
}

function selectCurrentReferenceVersion(versions: any[]): any | null {
  if (!versions.length) return null;
  const sorted = [...versions].sort((left, right) => {
    const leftCurrent = normalizeOptionalString(left.versionState) === "current" ? 1 : 0;
    const rightCurrent = normalizeOptionalString(right.versionState) === "current" ? 1 : 0;
    if (leftCurrent !== rightCurrent) return rightCurrent - leftCurrent;
    const leftVersion = normalizeOptionalPositiveInteger(left.versionNumber) ?? 0;
    const rightVersion = normalizeOptionalPositiveInteger(right.versionNumber) ?? 0;
    if (leftVersion !== rightVersion) return rightVersion - leftVersion;
    const leftTime = normalizeOptionalString(left.versionCreatedAt)
      ?? normalizeOptionalString(left.updatedAt)
      ?? "";
    const rightTime = normalizeOptionalString(right.versionCreatedAt)
      ?? normalizeOptionalString(right.updatedAt)
      ?? "";
    if (leftTime !== rightTime) return rightTime.localeCompare(leftTime);
    const leftId = normalizeOptionalString(left.id) ?? "";
    const rightId = normalizeOptionalString(right.id) ?? "";
    return rightId.localeCompare(leftId);
  });
  return sorted[0] ?? null;
}

function normalizeReferenceCurationPolicy(value: unknown): typeof DEFAULT_REFERENCE_CURATION_POLICY {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ...DEFAULT_REFERENCE_CURATION_POLICY };
  }
  const record = value as Record<string, unknown>;
  return {
    recomputeIdentifier: normalizeOptionalBoolean(record.recomputeIdentifier) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeIdentifier,
    recomputePublicationDate: normalizeOptionalBoolean(record.recomputePublicationDate) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputePublicationDate,
    recomputeTitle: normalizeOptionalBoolean(record.recomputeTitle) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeTitle,
    recomputeSubtitle: normalizeOptionalBoolean(record.recomputeSubtitle) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeSubtitle,
    recomputeSummary: normalizeOptionalBoolean(record.recomputeSummary) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeSummary,
    recomputeTopicPredictions: normalizeOptionalBoolean(record.recomputeTopicPredictions) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeTopicPredictions,
    recomputeQuality: normalizeOptionalBoolean(record.recomputeQuality) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeQuality,
    recomputeCorpus: normalizeOptionalBoolean(record.recomputeCorpus) ?? DEFAULT_REFERENCE_CURATION_POLICY.recomputeCorpus,
  };
}

function assignmentLifecycleStatusFromAssignmentStatus(status: string): "queued" | "running" | "completed" | "failed" | "degraded" {
  const normalized = status.trim().toLowerCase();
  if (normalized === "open") return "queued";
  if (normalized === "claimed") return "running";
  if (normalized === "completed") return "completed";
  if (normalized === "degraded") return "degraded";
  return "failed";
}

function defaultReferenceCurationStageStatuses(status: string): Record<(typeof REFERENCE_CURATION_STAGE_KEYS)[number], { status: string }> {
  const normalized = status.trim().toLowerCase();
  const next = normalized === "running" ? "running" : normalized === "queued" ? "queued" : "pending";
  return {
    identifier: { status: next },
    publicationDate: { status: next },
    titleSubtitle: { status: next },
    summary: { status: next },
    topicPredictions: { status: next },
  };
}

function buildAuthoritativeLabelRelation({
  actor,
  category,
  note,
  now,
  reference,
  sourceMode,
  sourceRelationId,
}: {
  actor: string;
  category: any;
  note: string | null;
  now: string;
  reference: any;
  sourceMode: "manual" | "accepted_prediction";
  sourceRelationId: string | null;
}): any {
  const subjectLineageId = normalizeOptionalString(reference.lineageId) ?? normalizeRequiredString(reference.id, "reference.id");
  const objectLineageId = normalizeOptionalString(category.lineageId) ?? normalizeRequiredString(category.id, "category.id");
  const subjectStateKey = semanticStateKey("reference", subjectLineageId);
  const objectStateKey = semanticStateKey("category", objectLineageId);
  const subjectVersionKey = semanticVersionKey("reference", normalizeRequiredString(reference.id, "reference.id"));
  const objectVersionKey = semanticVersionKey("category", normalizeRequiredString(category.id, "category.id"));
  return {
    id: `semantic-relation-${hashStable([subjectStateKey, "authoritative_label", objectStateKey]).slice(0, 24)}`,
    relationState: "current",
    predicate: "authoritative_label",
    ...semanticRelationTypeFieldsForPredicate("authoritative_label"),
    subjectKind: "reference",
    subjectId: reference.id,
    subjectLineageId,
    subjectVersionNumber: typeof reference.versionNumber === "number" ? reference.versionNumber : null,
    objectKind: "category",
    objectId: category.id,
    objectLineageId,
    objectVersionNumber: typeof category.versionNumber === "number" ? category.versionNumber : null,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#reference`,
    predicateObjectStateKey: `authoritative_label#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: 1,
    confidence: null,
    rank: 1,
    classifierId: normalizeOptionalString(category.classifierId),
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: null,
    importRunId: null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: JSON.stringify({
      kind: sourceMode === "accepted_prediction"
        ? "classification.authoritative_label.accepted_from_prediction"
        : "classification.authoritative_label.manual",
      actor,
      note,
      sourceMode,
      sourcePredictionId: sourceRelationId,
      categorySetId: normalizeOptionalString(category.categorySetId),
      categoryKey: normalizeOptionalString(category.categoryKey),
    }),
  };
}

function buildReferenceQualityRelation({
  actor,
  note,
  now,
  qualityNode,
  rating,
  reference,
}: {
  actor: string;
  note: string | null;
  now: string;
  qualityNode: any;
  rating: number;
  reference: any;
}): any {
  const subjectLineageId = normalizeOptionalString(reference.lineageId) ?? normalizeRequiredString(reference.id, "reference.id");
  const objectLineageId = normalizeOptionalString(qualityNode.lineageId) ?? normalizeRequiredString(qualityNode.id, "qualityNode.id");
  const subjectStateKey = semanticStateKey("reference", subjectLineageId);
  const objectStateKey = semanticStateKey("semanticNode", objectLineageId);
  const subjectVersionKey = semanticVersionKey("reference", normalizeRequiredString(reference.id, "reference.id"));
  const objectVersionKey = semanticVersionKey("semanticNode", normalizeRequiredString(qualityNode.id, "qualityNode.id"));
  return {
    id: `semantic-relation-quality-${safeId(subjectLineageId)}-${rating}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`,
    relationState: "current",
    predicate: "quality_rating_is",
    ...semanticRelationTypeFieldsForPredicate("quality_rating_is"),
    subjectKind: "reference",
    subjectId: reference.id,
    subjectLineageId,
    subjectVersionNumber: typeof reference.versionNumber === "number" ? reference.versionNumber : null,
    objectKind: "semanticNode",
    objectId: qualityNode.id,
    objectLineageId,
    objectVersionNumber: typeof qualityNode.versionNumber === "number" ? qualityNode.versionNumber : 1,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#reference`,
    predicateObjectStateKey: `quality_rating_is#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: rating,
    confidence: null,
    rank: 1,
    classifierId: null,
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: null,
    importRunId: null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: JSON.stringify({
      kind: "reference.quality-rating.manual",
      actor,
      note,
      qualityRating: rating,
      ratedAt: now,
    }),
  };
}

async function updateNewsroomSummaryForSemanticRelationDelta(
  client: DataClient,
  relation: any,
  amount: number,
  now: string,
): Promise<void> {
  const response = await client.models.KnowledgeRawPayload.get({ id: NEWSROOM_SUMMARY_PAYLOAD_ID });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const payload = normalizeSummaryPayload(await readNewsroomSummaryPayload(client), now);
  payload.generatedAt = now;
  payload.staleAt = new Date(Date.parse(now) + SUMMARY_STALE_AFTER_MS).toISOString();
  payload.source = "incremental";
  payload.counts.semanticRelations = Math.max(0, (payload.counts.semanticRelations ?? 0) + amount);
  increment(payload.facets.semanticRelations.byRelationTypeKey, normalizeOptionalString(relation.relationTypeKey) ?? normalizeOptionalString(relation.predicate) ?? "unknown", amount);
  increment(payload.facets.semanticRelations.byRelationDomain, normalizeOptionalString(relation.relationDomain) ?? "unknown", amount);
  increment(payload.facets.semanticRelations.bySubjectKind, normalizeOptionalString(relation.subjectKind) ?? "unknown", amount);
  increment(payload.facets.semanticRelations.byObjectKind, normalizeOptionalString(relation.objectKind) ?? "unknown", amount);
  await upsertNewsroomSummaryPayload(client, payload, response.data, now);
}

async function getDataClient(): Promise<DataClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const { resourceConfig, libraryOptions } = await getAmplifyDataClientConfig(process.env as never);
      Amplify.configure(resourceConfig, libraryOptions);
      return generateClient<Schema>();
    })();
  }
  return clientPromise;
}

async function getRequiredRecord(
  model: { get(input: { id: string }): Promise<{ data?: unknown | null; errors?: DataClientErrors }> },
  id: string,
  modelName: string,
): Promise<any> {
  const response = await model.get({ id });
  assertNoDataErrors(response.errors, `get ${modelName}`);
  if (!response.data) throw new Error(`${modelName} ${id} was not found.`);
  return response.data;
}

async function requireDataResult<T>(promise: Promise<DataClientResult<T>>, operation: string): Promise<T> {
  const response = await promise;
  assertNoDataErrors(response.errors, operation);
  if (!response.data) throw new Error(`${operation} returned no data.`);
  return response.data;
}

function assertNoDataErrors(errors: DataClientErrors, operation: string): void {
  if (!errors?.length) return;
  throw new Error(`${operation} failed: ${errors.map(formatDataError).join("; ")}`);
}

function formatDataError(error: { message?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  return error?.message ?? "GraphQL data operation failed.";
}

function normalizeReviewAction(value: unknown): "accept" | "reject" | "defer" | "edit" {
  const action = normalizeRequiredString(value, "action").toLowerCase();
  if (action === "accept" || action === "reject" || action === "defer" || action === "edit") return action;
  throw new Error(`Unsupported proposal action ${action}.`);
}

function normalizeReferenceCurationAction(value: unknown): "accept" | "reject" | "reopen" | "archive" {
  const action = normalizeRequiredString(value, "action").toLowerCase();
  if (action === "accept" || action === "reject" || action === "reopen" || action === "archive") return action;
  throw new Error(`Unsupported reference curation action ${action}.`);
}

function reviewedFeedKeyForStatus(status: string): string | null {
  return status === "pending" ? null : REFERENCE_REVIEWED_FEED_KEY;
}

function referenceCurationStatusForAction(action: "accept" | "reject" | "reopen" | "archive"): "accepted" | "rejected" | "pending" | "archived" {
  if (action === "accept") return "accepted";
  if (action === "reject") return "rejected";
  if (action === "archive") return "archived";
  return "pending";
}

const REFERENCE_REJECTION_REASON_CODES = new Set([
  "out_of_scope",
  "policy_exclusion",
  "duplicate",
  "low_quality",
  "unavailable",
  "provenance",
  "other",
]);

function normalizeReferenceRejectionReasonCode(value: unknown, required: boolean): string | null {
  const normalized = normalizePolicyToken(value);
  if (!normalized) {
    if (required) throw new Error("reasonCode is required when rejecting a reference.");
    return null;
  }
  if (!REFERENCE_REJECTION_REASON_CODES.has(normalized)) {
    throw new Error(`Unsupported reference rejection reason code ${normalized}.`);
  }
  return normalized;
}

function normalizeReferenceQualityRating(value: unknown): number {
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isInteger(numeric) && numeric >= 1 && numeric <= 5) return numeric;
  throw new Error("rating must be an integer from 1 to 5.");
}

function qualityNodeId(rating: number): string {
  return `${qualityNodeLineageId(rating)}-v1`;
}

function qualityNodeLineageId(rating: number): string {
  return `semantic-node-${safeId(`quality.rating.${rating}_star`)}`;
}

function qualityRatingFromRelation(relation: any): number | null {
  const score = typeof relation?.score === "number" ? relation.score : Number(relation?.score);
  if (Number.isFinite(score) && Number.isInteger(score) && score >= 1 && score <= 5) return score;
  return qualityRatingFromNodeKey(normalizeOptionalString(relation?.objectLineageId) ?? normalizeOptionalString(relation?.objectId));
}

function qualityRatingFromNodeKey(value: string | null): number | null {
  const match = /(?:quality[-_.]?rating[-_.]?)?([1-5])[-_.]?star/i.exec(value ?? "");
  return match ? Number(match[1]) : null;
}

function parseMetadataObject(value: unknown): Record<string, unknown> {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function normalizePolicyToken(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

async function updateNewsroomSummaryForReferenceCuration(
  client: DataClient,
  input: { corpusId: string | null; previousStatus: string; nextStatus: string; now: string },
): Promise<void> {
  const response = await client.models.KnowledgeRawPayload.get({ id: NEWSROOM_SUMMARY_PAYLOAD_ID });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const payload = normalizeSummaryPayload(await readNewsroomSummaryPayload(client), input.now);
  payload.generatedAt = input.now;
  payload.staleAt = new Date(Date.parse(input.now) + SUMMARY_STALE_AFTER_MS).toISOString();
  payload.source = "incremental";
  payload.counts.messages = Math.max(0, (payload.counts.messages ?? 0) + 1);
  payload.counts.modelAttachments = Math.max(0, (payload.counts.modelAttachments ?? 0) + 2);
  payload.counts.semanticRelations = Math.max(0, (payload.counts.semanticRelations ?? 0) + 1);
  if (input.previousStatus !== input.nextStatus) {
    increment(payload.referenceStatusCounts, input.previousStatus, -1);
    increment(payload.referenceStatusCounts, input.nextStatus, 1);
    increment(payload.facets.references.byCurationStatus, input.previousStatus, -1);
    increment(payload.facets.references.byCurationStatus, input.nextStatus, 1);
    if (input.corpusId) {
      if (!payload.facets.references.statusByCorpus[input.corpusId]) payload.facets.references.statusByCorpus[input.corpusId] = {};
      increment(payload.facets.references.statusByCorpus[input.corpusId], input.previousStatus, -1);
      increment(payload.facets.references.statusByCorpus[input.corpusId], input.nextStatus, 1);
    }
  }
  increment(payload.messageKindCounts, "reference_curation", 1);
  increment(payload.messageDomainCounts, "commentary", 1);
  increment(payload.facets.messages.byKind, "reference_curation", 1);
  increment(payload.facets.messages.byDomain, "commentary", 1);
  increment(payload.facets.messages.byStatus, "active", 1);
  if (!payload.facets.messages.domainByKind.reference_curation) payload.facets.messages.domainByKind.reference_curation = {};
  increment(payload.facets.messages.domainByKind.reference_curation, "commentary", 1);
  increment(payload.facets.modelAttachments.byOwnerKind, "message", 2);
  increment(payload.facets.modelAttachments.byRole, "message_body", 1);
  increment(payload.facets.modelAttachments.byRole, "metadata", 1);
  increment(payload.facets.modelAttachments.byMediaType, "text/plain", 1);
  increment(payload.facets.modelAttachments.byMediaType, "application/json", 1);
  increment(payload.facets.modelAttachments.byStatus, "active", 2);
  increment(payload.facets.semanticRelations.byRelationTypeKey, "comment", 1);
  increment(payload.facets.semanticRelations.byRelationDomain, "workflow", 1);
  increment(payload.facets.semanticRelations.bySubjectKind, "message", 1);
  increment(payload.facets.semanticRelations.byObjectKind, "reference", 1);
  await upsertNewsroomSummaryPayload(client, payload, response.data, input.now);
}

async function updateNewsroomSummaryForReferenceStatus(
  client: DataClient,
  input: { corpusId: string | null; previousStatus: string; nextStatus: string; now: string },
): Promise<void> {
  const response = await client.models.KnowledgeRawPayload.get({ id: NEWSROOM_SUMMARY_PAYLOAD_ID });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const payload = normalizeSummaryPayload(await readNewsroomSummaryPayload(client), input.now);
  payload.generatedAt = input.now;
  payload.staleAt = new Date(Date.parse(input.now) + SUMMARY_STALE_AFTER_MS).toISOString();
  payload.source = "incremental";
  increment(payload.referenceStatusCounts, input.previousStatus, -1);
  increment(payload.referenceStatusCounts, input.nextStatus, 1);
  increment(payload.facets.references.byCurationStatus, input.previousStatus, -1);
  increment(payload.facets.references.byCurationStatus, input.nextStatus, 1);
  if (input.corpusId) {
    if (!payload.facets.references.statusByCorpus[input.corpusId]) payload.facets.references.statusByCorpus[input.corpusId] = {};
    increment(payload.facets.references.statusByCorpus[input.corpusId], input.previousStatus, -1);
    increment(payload.facets.references.statusByCorpus[input.corpusId], input.nextStatus, 1);
  }
  await upsertNewsroomSummaryPayload(client, payload, response.data, input.now);
}

function normalizeSummaryPayload(value: unknown, now: string): {
  generatedAt: string;
  staleAt: string;
  source: string;
  latestImportRun: Record<string, unknown> | null;
  counts: Record<string, number>;
  assignmentStatusCounts: Record<string, number>;
  assignmentTypeCounts: Record<string, number>;
  referenceStatusCounts: Record<string, number>;
  messageKindCounts: Record<string, number>;
  messageDomainCounts: Record<string, number>;
  facets: {
    assignments: {
      byStatus: Record<string, number>;
      byType: Record<string, number>;
      bySection: Record<string, number>;
      statusByType: Record<string, Record<string, number>>;
      statusBySection: Record<string, Record<string, number>>;
      typeBySection: Record<string, Record<string, number>>;
    };
    messages: { byKind: Record<string, number>; byDomain: Record<string, number>; byStatus: Record<string, number>; domainByKind: Record<string, Record<string, number>> };
    modelAttachments: { byOwnerKind: Record<string, number>; byRole: Record<string, number>; byMediaType: Record<string, number>; byStatus: Record<string, number> };
    references: { byCurationStatus: Record<string, number>; byCorpus: Record<string, number>; statusByCorpus: Record<string, Record<string, number>> };
    semanticNodes: { byNodeKind: Record<string, number>; byStatus: Record<string, number>; byCorpus: Record<string, number>; byCategorySet: Record<string, number> };
    semanticRelations: { byRelationTypeKey: Record<string, number>; byRelationDomain: Record<string, number>; bySubjectKind: Record<string, number>; byObjectKind: Record<string, number> };
    imports: { byCorpus: Record<string, number> };
  };
} {
  const parsed = parseJsonObject(value);
  const facets = normalizeFacets(parsed);
  return {
    generatedAt: normalizeOptionalString(parsed.generatedAt) ?? now,
    staleAt: normalizeOptionalString(parsed.staleAt) ?? now,
    source: normalizeOptionalString(parsed.source) ?? "missing",
    latestImportRun: parseJsonObject(parsed.latestImportRun),
    counts: numberRecord(parsed.counts),
    assignmentStatusCounts: numberRecord(parsed.assignmentStatusCounts),
    assignmentTypeCounts: numberRecord(parsed.assignmentTypeCounts),
    referenceStatusCounts: numberRecord(parsed.referenceStatusCounts),
    messageKindCounts: numberRecord(parsed.messageKindCounts),
    messageDomainCounts: numberRecord(parsed.messageDomainCounts),
    facets,
  };
}

function normalizeFacets(payload: Record<string, unknown>): ReturnType<typeof createEmptyFacets> {
  const facets = createEmptyFacets();
  const parsed = parseJsonObject(payload.facets);
  const assignments = parseJsonObject(parsed.assignments);
  const messages = parseJsonObject(parsed.messages);
  const modelAttachments = parseJsonObject(parsed.modelAttachments);
  const references = parseJsonObject(parsed.references);
  const semanticNodes = parseJsonObject(parsed.semanticNodes);
  const semanticRelations = parseJsonObject(parsed.semanticRelations);
  const imports = parseJsonObject(parsed.imports);
  facets.assignments.byStatus = { ...numberRecord(payload.assignmentStatusCounts), ...numberRecord(assignments.byStatus) };
  facets.assignments.byType = { ...numberRecord(payload.assignmentTypeCounts), ...numberRecord(assignments.byType) };
  facets.assignments.bySection = numberRecord(assignments.bySection);
  facets.assignments.statusByType = nestedNumberRecord(assignments.statusByType);
  facets.assignments.statusBySection = nestedNumberRecord(assignments.statusBySection);
  facets.assignments.typeBySection = nestedNumberRecord(assignments.typeBySection);
  facets.messages.byKind = { ...numberRecord(payload.messageKindCounts), ...numberRecord(messages.byKind) };
  facets.messages.byDomain = { ...numberRecord(payload.messageDomainCounts), ...numberRecord(messages.byDomain) };
  facets.messages.byStatus = numberRecord(messages.byStatus);
  facets.messages.domainByKind = nestedNumberRecord(messages.domainByKind);
  facets.modelAttachments.byOwnerKind = numberRecord(modelAttachments.byOwnerKind);
  facets.modelAttachments.byRole = numberRecord(modelAttachments.byRole);
  facets.modelAttachments.byMediaType = numberRecord(modelAttachments.byMediaType);
  facets.modelAttachments.byStatus = numberRecord(modelAttachments.byStatus);
  facets.references.byCurationStatus = { ...numberRecord(payload.referenceStatusCounts), ...numberRecord(references.byCurationStatus) };
  facets.references.byCorpus = numberRecord(references.byCorpus);
  facets.references.statusByCorpus = nestedNumberRecord(references.statusByCorpus);
  facets.semanticNodes.byNodeKind = numberRecord(semanticNodes.byNodeKind);
  facets.semanticNodes.byStatus = numberRecord(semanticNodes.byStatus);
  facets.semanticNodes.byCorpus = numberRecord(semanticNodes.byCorpus);
  facets.semanticNodes.byCategorySet = numberRecord(semanticNodes.byCategorySet);
  facets.semanticRelations.byRelationTypeKey = numberRecord(semanticRelations.byRelationTypeKey);
  facets.semanticRelations.byRelationDomain = numberRecord(semanticRelations.byRelationDomain);
  facets.semanticRelations.bySubjectKind = numberRecord(semanticRelations.bySubjectKind);
  facets.semanticRelations.byObjectKind = numberRecord(semanticRelations.byObjectKind);
  facets.imports.byCorpus = numberRecord(imports.byCorpus);
  return facets;
}

function createEmptyFacets() {
  return {
    assignments: { byStatus: {}, byType: {}, bySection: {}, statusByType: {}, statusBySection: {}, typeBySection: {} },
    messages: { byKind: {}, byDomain: {}, byStatus: {}, domainByKind: {} },
    modelAttachments: { byOwnerKind: {}, byRole: {}, byMediaType: {}, byStatus: {} },
    references: { byCurationStatus: {}, byCorpus: {}, statusByCorpus: {} },
    semanticNodes: { byNodeKind: {}, byStatus: {}, byCorpus: {}, byCategorySet: {} },
    semanticRelations: { byRelationTypeKey: {}, byRelationDomain: {}, bySubjectKind: {}, byObjectKind: {} },
    imports: { byCorpus: {} },
  };
}

function nestedNumberRecord(value: unknown): Record<string, Record<string, number>> {
  const parsed = parseJsonObject(value);
  const result: Record<string, Record<string, number>> = {};
  for (const [key, entry] of Object.entries(parsed)) result[key] = numberRecord(entry);
  return result;
}

async function upsertNewsroomSummaryPayload(
  client: DataClient,
  payload: Record<string, unknown>,
  current: any,
  now: string,
): Promise<void> {
  const input = {
    id: NEWSROOM_SUMMARY_PAYLOAD_ID,
    ownerType: "newsroom",
    ownerId: "newsroom",
    payloadKind: "summary-snapshot",
    importRunId: normalizeOptionalString(parseJsonObject(payload.latestImportRun).id),
    createdAt: current?.createdAt ?? now,
    updatedAt: now,
  };
  if (current) {
    await requireDataResult(client.models.KnowledgeRawPayload.update(input), "update Newsroom summary snapshot");
  } else {
    await requireDataResult(client.models.KnowledgeRawPayload.create(input), "create Newsroom summary snapshot");
  }
  await putJsonModelPayload(
    client as any,
    { ownerKind: NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND, ownerId: NEWSROOM_SUMMARY_PAYLOAD_ID, importRunId: input.importRunId },
    "raw_payload",
    "summary-snapshot",
    payload,
    { filename: "summary-snapshot.json", now },
  );
}

async function readNewsroomSummaryPayload(client: DataClient): Promise<Record<string, unknown> | null> {
  return readJsonModelPayload(
    client as any,
    NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND,
    NEWSROOM_SUMMARY_PAYLOAD_ID,
    "raw_payload",
    "summary-snapshot",
  );
}

function parseJsonObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function numberRecord(value: unknown): Record<string, number> {
  const parsed = parseJsonObject(value);
  const result: Record<string, number> = {};
  for (const [key, entry] of Object.entries(parsed)) {
    const numeric = Number(entry);
    if (Number.isFinite(numeric)) result[key] = numeric;
  }
  return result;
}

function increment(target: Record<string, number>, key: string, delta: number): void {
  target[key] = Math.max(0, (target[key] ?? 0) + delta);
}

function buildCanonicalMessageInput(input: {
  id: string;
  messageKind: string;
  messageDomain: string;
  summary?: string | null;
  source?: string | null;
  authorSub?: string | null;
  authorLabel?: string | null;
  now: string;
}) {
  return {
    id: input.id,
    messageKind: input.messageKind,
    messageDomain: input.messageDomain,
    status: "active",
    summary: input.summary ?? null,
    source: input.source ?? "newsroom",
    importRunId: null,
    authorSub: input.authorSub ?? null,
    authorUserProfileId: null,
    authorLabel: input.authorLabel ?? null,
    responseTarget: "none",
    responseStatus: "COMPLETED",
    responseOwner: "papyrus-category-action",
    responseStartedAt: input.now,
    responseCompletedAt: input.now,
    responseError: null,
    createdAt: input.now,
    updatedAt: input.now,
    newsroomFeedKey: "messages",
  };
}

function normalizeRequiredString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${fieldName} is required.`);
  }
  return value.trim();
}

function normalizeOptionalString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function normalizeOptionalBoolean(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return null;
}

function normalizeOptionalPositiveInteger(value: unknown): number | null {
  if (value == null || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isInteger(numeric) && numeric > 0) return numeric;
  return null;
}

function normalizeStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return compactStringArray(value);
}

function compactStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => typeof entry === "string" ? entry.trim() : "")
    .filter(Boolean);
}

function deriveShortTitle(value: unknown): string {
  const words = String(value ?? "")
    .replace(/[_/|]+/g, " ")
    .replace(/[^\p{L}\p{N}\s&+-]/gu, "")
    .split(/\s+/)
    .map((word) => word.trim())
    .filter(Boolean);
  return words.length ? words.slice(0, 3).join(" ") : "Topic";
}

function getIdentitySub(event: CategoryActionEvent): string | null {
  const identity = event.identity as { sub?: unknown; username?: unknown } | null | undefined;
  return normalizeOptionalString(identity?.sub) ?? normalizeOptionalString(identity?.username);
}

function getIdentityLabel(event: CategoryActionEvent): string | null {
  const identity = event.identity as { claims?: Record<string, unknown>; username?: unknown } | null | undefined;
  const claims = identity?.claims ?? {};
  return normalizeOptionalString(claims.email)
    ?? normalizeOptionalString(claims.name)
    ?? normalizeOptionalString(identity?.username);
}

function semanticStateKey(kind: string, lineageId: string): string {
  return `${kind}#${lineageId}#current`;
}

function semanticVersionKey(kind: string, id: string): string {
  return `${kind}#${id}`;
}

function hashStable(value: unknown): string {
  return createHash("sha256").update(stableStringify(value)).digest("hex");
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (!value || typeof value !== "object") return JSON.stringify(value);
  return `{${Object.keys(value as Record<string, unknown>)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify((value as Record<string, unknown>)[key])}`)
    .join(",")}}`;
}

function safeId(value: unknown): string {
  return String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "unknown";
}
