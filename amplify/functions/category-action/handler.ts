import { InvokeCommand, LambdaClient } from "@aws-sdk/client-lambda";
import { createHash, randomUUID } from "node:crypto";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";
import { putJsonModelPayload, putTextModelPayload, readJsonModelPayload } from "../shared/model-payloads";
import { actingFor, buildEventTenantContext, currentTenantContext } from "../shared/tenant-context";
import { newsroomSummaryPayloadId, tenantScopedClient } from "../shared/tenant-scoped-client";
import { curationActorKind, referenceStarFields, referenceVoteFields, validatedCurationSectionId } from "../shared/reference-curation-metadata";
import {
  delegationExpiry,
  delegationRefusalMessage,
  delegationVerdict,
  newDelegationToken,
  PENDING_REQUEST_GRANTOR_SUB,
  type CurationDelegation,
} from "../shared/curation-delegation";
import {
  approveDelegation,
  delegationResult as flowDelegationResult,
  delegationStatus,
  denyDelegation,
  livePendingRequests,
  requestDelegation,
  type DelegationStore,
} from "../shared/curation-delegation-flow";
import { rejectionReasonCodeForWrittenReason } from "../../../lib/reference-policy";
import { referenceContentNeededKey, referenceFeedArrivalAt, referenceFeedKeys, referenceFeedStateKey, referenceMediumFeedKey, referenceMediumKeyPatch, referencePublicFeedKeys, referencePublicKeyPatch, starFeedKeyFor } from "../../../lib/reference-feed-keys";
import { claimGroups, hasEditorRights } from "../../../lib/staff-groups";
import {
  classifyCurationCaller,
  cliClientIdFromEnvironment,
  requireDelegationAgent,
  requireDelegationApprover,
  requireDelegationWithdrawer,
  type CurationCaller,
} from "../shared/curation-caller";
import { isStoryItemType } from "../../../lib/content-item-lifecycle";
import { linkMessageHashtags, type MessageHashtagStore } from "./message-hashtags";
import { createConceptLink, createReferenceLink, decideReferenceLink, describeEditorConcept, ensureEditorConcept, type ReferenceLinkStore } from "./reference-links";
import { applyKnowledgeReview, type KnowledgeReviewStore } from "./knowledge-review";
import { setStoryReferenceRole } from "./story-reference-role";
import { editOriginOfIdentity } from "../shared/edit-origin";
import { REFERENCE_FEED_KEY, REFERENCE_REVIEWED_FEED_KEY, SEMANTIC_RELATION_FEED_KEY, globalKey } from "../../../lib/tenant-knowledge-keys";

type ReviewHandler = Schema["reviewSteeringProposal"]["functionHandler"];
type ReferenceCurationHandler = Schema["reviewReferenceCuration"]["functionHandler"];
type CreateCurationDelegationHandler = Schema["createCurationDelegation"]["functionHandler"];
type RevokeCurationDelegationHandler = Schema["revokeCurationDelegation"]["functionHandler"];
type ListCurationDelegationsHandler = Schema["listCurationDelegations"]["functionHandler"];
type RequestCurationDelegationHandler = Schema["requestCurationDelegation"]["functionHandler"];
type ApproveCurationDelegationHandler = Schema["approveCurationDelegation"]["functionHandler"];
type DenyCurationDelegationHandler = Schema["denyCurationDelegation"]["functionHandler"];
type GetCurationDelegationStatusHandler = Schema["getCurationDelegationStatus"]["functionHandler"];
type RecordDelegatedCurationHandler = Schema["recordDelegatedCuration"]["functionHandler"];
type ReferenceStarsHandler = Schema["setReferenceStars"]["functionHandler"];
type ReferenceSectionHandler = Schema["setReferenceSection"]["functionHandler"];
type RecordDelegatedStarsHandler = Schema["recordDelegatedStars"]["functionHandler"];
type ItemStarsHandler = Schema["setItemStars"]["functionHandler"];
type ReferenceQualityHandler = Schema["setReferenceQualityRating"]["functionHandler"];
type ReferenceNoteHandler = Schema["createReferenceNote"]["functionHandler"];
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
type LinkMessageHashtagsHandler = Schema["linkMessageHashtags"]["functionHandler"];
type CreateReferenceLinkHandler = Schema["createReferenceLink"]["functionHandler"];
type DescribeConceptHandler = Schema["describeConcept"]["functionHandler"];
type CreateEditorConceptHandler = Schema["createEditorConcept"]["functionHandler"];
type DecideReferenceLinkHandler = Schema["decideReferenceLink"]["functionHandler"];
type SetStoryReferenceRoleHandler = Schema["setStoryReferenceRole"]["functionHandler"];
type CreateConceptLinkHandler = Schema["createConceptLink"]["functionHandler"];
type ApplyKnowledgeReviewHandler = Schema["applyKnowledgeReview"]["functionHandler"];
type CategoryActionEvent =
  | Parameters<LinkMessageHashtagsHandler>[0]
  | Parameters<CreateReferenceLinkHandler>[0]
  | Parameters<DecideReferenceLinkHandler>[0]
  | Parameters<SetStoryReferenceRoleHandler>[0]
  | Parameters<CreateConceptLinkHandler>[0]
  | Parameters<ApplyKnowledgeReviewHandler>[0]
  | Parameters<DescribeConceptHandler>[0]
  | Parameters<CreateEditorConceptHandler>[0]
  | Parameters<ReviewHandler>[0]
  | Parameters<ReferenceCurationHandler>[0]
  | Parameters<CreateCurationDelegationHandler>[0]
  | Parameters<RevokeCurationDelegationHandler>[0]
  | Parameters<ListCurationDelegationsHandler>[0]
  | Parameters<RequestCurationDelegationHandler>[0]
  | Parameters<ApproveCurationDelegationHandler>[0]
  | Parameters<DenyCurationDelegationHandler>[0]
  | Parameters<GetCurationDelegationStatusHandler>[0]
  | Parameters<RecordDelegatedCurationHandler>[0]
  | Parameters<RecordDelegatedStarsHandler>[0]
  | Parameters<ReferenceStarsHandler>[0]
  | Parameters<ItemStarsHandler>[0]
  | Parameters<ReferenceQualityHandler>[0]
  | Parameters<ReferenceNoteHandler>[0]
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

let clientPromise: Promise<DataClient> | null = null;

export const handler = async (event: CategoryActionEvent) => {
  const context = buildEventTenantContext(event);   // one context per call; a shared stack refuses before any read
  return actingFor(context, () => handleField(event));
};

async function handleField(event: CategoryActionEvent) {
  const fieldName = normalizeOptionalString(event.info?.fieldName) ?? normalizeOptionalString((event as { fieldName?: string | null }).fieldName);
  if (!fieldName) {
    throw new Error("Unsupported steering action: missing GraphQL field name.");
  }
  if (fieldName === "createReferenceLink") return createReferenceLinkAction(event as Parameters<CreateReferenceLinkHandler>[0]);
  if (fieldName === "createEditorConcept") return createEditorConceptAction(event as Parameters<CreateEditorConceptHandler>[0]);
  if (fieldName === "describeConcept") return describeConceptAction(event as Parameters<DescribeConceptHandler>[0]);
  if (fieldName === "createConceptLink") return createConceptLinkAction(event as Parameters<CreateConceptLinkHandler>[0]);
  if (fieldName === "applyKnowledgeReview") return applyKnowledgeReviewAction(event as Parameters<ApplyKnowledgeReviewHandler>[0]);
  if (fieldName === "decideReferenceLink") return decideReferenceLinkAction(event as Parameters<DecideReferenceLinkHandler>[0]);
  if (fieldName === "setStoryReferenceRole") return setStoryReferenceRoleAction(event as Parameters<SetStoryReferenceRoleHandler>[0]);
  if (fieldName === "linkMessageHashtags") return linkMessageHashtagsAction(event as Parameters<LinkMessageHashtagsHandler>[0]);
  if (fieldName === "reviewSteeringProposal") return reviewSteeringProposal(event as Parameters<ReviewHandler>[0]);
  if (fieldName === "reviewReferenceCuration") return reviewReferenceCuration(event as Parameters<ReferenceCurationHandler>[0]);
  if (fieldName === "createCurationDelegation") return createCurationDelegation(event as Parameters<CreateCurationDelegationHandler>[0]);
  if (fieldName === "revokeCurationDelegation") return revokeCurationDelegation(event as Parameters<RevokeCurationDelegationHandler>[0]);
  if (fieldName === "listCurationDelegations") return listCurationDelegations(event as Parameters<ListCurationDelegationsHandler>[0]);
  if (fieldName === "requestCurationDelegation") return requestCurationDelegationAction(event as Parameters<RequestCurationDelegationHandler>[0]);
  if (fieldName === "approveCurationDelegation") return approveCurationDelegationAction(event as Parameters<ApproveCurationDelegationHandler>[0]);
  if (fieldName === "denyCurationDelegation") return denyCurationDelegationAction(event as Parameters<DenyCurationDelegationHandler>[0]);
  if (fieldName === "getCurationDelegationStatus") return getCurationDelegationStatusAction(event as Parameters<GetCurationDelegationStatusHandler>[0]);
  if (fieldName === "recordDelegatedCuration") return recordDelegatedCuration(event as Parameters<RecordDelegatedCurationHandler>[0]);
  if (fieldName === "recordDelegatedStars") return recordDelegatedStars(event as Parameters<RecordDelegatedStarsHandler>[0]);
  if (fieldName === "setReferenceSection") return setReferenceSection(event as Parameters<ReferenceSectionHandler>[0]);
  if (fieldName === "setReferenceStars") return setReferenceStars(event as Parameters<ReferenceStarsHandler>[0]);
  if (fieldName === "setItemStars") return setItemStars(event as Parameters<ItemStarsHandler>[0]);
  if (fieldName === "setReferenceQualityRating") return setReferenceQualityRating(event as Parameters<ReferenceQualityHandler>[0]);
  if (fieldName === "createReferenceNote") return createReferenceNote(event as Parameters<ReferenceNoteHandler>[0]);
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
}

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

async function reviewReferenceCuration(
  event: Parameters<ReferenceCurationHandler>[0],
  delegation: { delegationId: string; relayedBy: string; instruction: string } | null = null,
) {
  if (!delegation && getIdentitySub(event)) requireEditorGroups(event, "accept, reject or rate");   // a person's session, CLI or Newsroom; operators on AWS credentials have no sub
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const action = normalizeReferenceCurationAction(event.arguments.action);
  const nextStatus = referenceCurationStatusForAction(action);
  const writtenReason = normalizeOptionalString(event.arguments.note);
  // A rejection needs a reason, and the editor's own sentence is one: with no reason code sent, the
  // words are read for the code they name, so the scope-training negatives keep arriving from the
  // surfaces that ask for words instead of a chip. Words that name no code are filed under "other".
  const reasonCode = normalizeReferenceRejectionReasonCode(event.arguments.reasonCode)
    ?? (action === "reject" ? rejectionReasonCodeForWrittenReason(writtenReason) : null);
  if (action === "reject" && !reasonCode) {
    throw new Error("A rejection needs a reason: say why in your own words, or send a reasonCode.");
  }
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const requestedSectionId = normalizeOptionalString(event.arguments.sectionId);
  const sectionRecord = requestedSectionId
    ? (await client.models.NewsroomSection.get({ id: requestedSectionId })).data ?? null
    : null;
  const sectionId = validatedCurationSectionId(requestedSectionId, action, sectionRecord);
  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const person = actorLabel ?? actorSub ?? "Papyrus newsroom";
  // A delegated vote already names the agent and the delegation; a direct one gets the plain `via` note.
  const actor = delegation ? person : withViaNote(person, event, normalizeOptionalString((event.arguments as { agentLabel?: string | null }).agentLabel));
  const note = writtenReason;
  const decisionRelationId = normalizeOptionalString(event.arguments.decisionRelationId);

  // The vote is recorded on the Reference itself: its status, who set it and the note, plus the details of the vote.
  // Messages come only from people, so a vote writes no Message and no comment relation.
  await requireDataResult(
    client.models.Reference.update({
      id: referenceId,
      curationStatus: nextStatus,
      curationStatusKey: `${normalizeRequiredString(reference.corpusId, "reference.corpusId")}#${nextStatus}`,
      curationStatusUpdatedAt: now,
      curationStatusUpdatedBy: actor,
      curationStatusReason: note,
      // An accept that names a section is that person's section choice, recorded like `setReferenceSection` records one (docs/reference-auto-section.md).
      ...(sectionId ? { curationSectionUpdatedAt: now, curationSectionUpdatedBy: actor, ...personSectionProvenance(delegation ? "human" : curationActorKind(event.identity)) } : {}),
      ...referenceVoteFields({
        // A signed-in editor or admin session votes as that person, from the CLI or the Newsroom: an agent acting through the session acts for them.
        actorKind: delegation ? "human" : curationActorKind(event.identity),
        reasonCode,
        sectionId,
        shareable: event.arguments.shareable ?? null,
        delegation,
        decisionRelationId,
      }),
      newsroomFeedKey: reference.newsroomFeedKey ?? globalKey(REFERENCE_FEED_KEY, currentTenantContext().tenantId),
      reviewedFeedKey: reviewedFeedKeyForStatus(nextStatus),
      // A vote moves the Reference between the unrated and rated feeds; its original prediction and arrival stay as they were.
      feedStateKey: referenceFeedStateKey({ ...reference, curationStatus: nextStatus }),
      ...referenceMediumKeyPatch(reference, { curationStatus: nextStatus }),
      ...referencePublicKeyPatch(reference, { curationStatus: nextStatus }),   // a vote moves the row into or out of the public index; names nothing for an ordinary row
      updatedAt: now,
    }),
    "update Reference curation status",
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
  };
}

function curationCaller(event: { identity?: unknown }): CurationCaller {
  return classifyCurationCaller(event.identity, cliClientIdFromEnvironment());
}

/**
 * Where a direct decision came from, as a plain note after the person's name ("Ryan via cli (Claude)"). It never gates anything: a signed-in
 * editor or admin session decides as that person whichever client it came from. The Newsroom and operator sessions get no note.
 */
function withViaNote(actor: string, event: { identity?: unknown }, agentLabel: string | null | undefined): string {
  const lane = curationCaller(event).lane;
  const via = lane === "cli-session" ? "cli" : lane === "unseparated-session" || lane === "unreadable-client-session" ? "signed-in" : null;
  if (!via) return actor;
  return `${actor} via ${via}${agentLabel ? ` (${agentLabel})` : ""}`;
}

/**
 * The person behind a delegation route that belongs to the Newsroom. Approving, creating and listing refuse the CLI client's sessions, so an
 * agent working in an editor's own session cannot approve its own request; denying and revoking only reduce what an agent may do, so the
 * session that asked may do them. Both check the editor and admin groups here as well as in the schema.
 */
function requireSignedInPerson(event: { identity?: unknown }, route: "approver" | "withdrawer" = "approver"): { sub: string; label: string; isAdmin: boolean } {
  const caller = curationCaller(event);
  const person = route === "approver" ? requireDelegationApprover(caller) : requireDelegationWithdrawer(caller);
  const claims = (event.identity as { claims?: Record<string, unknown> }).claims ?? {};
  return {
    sub: normalizeRequiredString(person.sub, "identity.sub"),
    label: normalizeOptionalString(claims.email) ?? normalizeOptionalString(claims.name) ?? "Newsroom editor",
    isAdmin: person.groups.includes("admin"),
  };
}

/**
 * Delegations live in `CurationDelegationRecord`, a model that no signed-in session, group or identity-pool role can read or write: only this
 * Lambda (and the other `allow.resource` Lambdas) can. They used to be a JSON attachment on a `KnowledgeRawPayload`, which the editor groups
 * can write directly and attach files to, so a session could forge an approved delegation. Records from that old place are never read, so
 * every delegation made before this change is simply unknown and an agent asks again.
 */
function parseDelegationRow(row: { id?: string | null; grantorSub?: string | null; recordJson?: string | null } | null | undefined): CurationDelegation | null {
  if (!row?.recordJson) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(row.recordJson);
  } catch {
    return null;
  }
  const record = parsed as Partial<CurationDelegation> | null;
  // A row whose record names another id or grantor than the row itself is not one this Lambda wrote.
  if (!record || typeof record !== "object" || record.delegationId !== row.id || record.grantorSub !== row.grantorSub) return null;
  return record as CurationDelegation;
}

async function readCurationDelegation(client: DataClient, delegationId: string): Promise<CurationDelegation | null> {
  const result = await (client.models as any).CurationDelegationRecord.get({ id: delegationId });
  assertNoDataErrors(result.errors, "get curation delegation");
  return parseDelegationRow(result.data);
}

async function writeCurationDelegation(client: DataClient, delegation: CurationDelegation, now: string, created: boolean) {
  const input = {
    id: delegation.delegationId,
    grantorSub: delegation.grantorSub,
    recordJson: JSON.stringify(delegation),
    createdAt: delegation.createdAt,
    updatedAt: now,
  };
  const model = (client.models as any).CurationDelegationRecord;
  if (created) {
    await requireDataResult(model.create(input), "create curation delegation");
  } else {
    await requireDataResult(model.update(input), "update curation delegation");
  }
}

async function listDelegationsByGrantor(client: DataClient, grantorSub: string): Promise<CurationDelegation[]> {
  const found: CurationDelegation[] = [];
  let nextToken: string | null | undefined;
  do {
    const page: any = await (client.models as any).CurationDelegationRecord.listCurationDelegationRecordsByGrantor({ grantorSub }, { nextToken });
    assertNoDataErrors(page.errors, "list curation delegations");
    for (const row of page.data ?? []) {
      const delegation = parseDelegationRow(row);
      if (delegation) found.push(delegation);
    }
    nextToken = page.nextToken;
  } while (nextToken);
  return found;
}

function delegationResult(delegation: CurationDelegation, token: string | null) {
  return { ...flowDelegationResult(delegation, new Date().toISOString()), token };
}

async function listPendingCurationDelegations(client: DataClient): Promise<CurationDelegation[]> {
  return listDelegationsByGrantor(client, PENDING_REQUEST_GRANTOR_SUB);
}

function curationDelegationStore(client: DataClient): DelegationStore {
  return {
    read: (delegationId) => readCurationDelegation(client, delegationId),
    write: (delegation, now, created) => writeCurationDelegation(client, delegation, now, created),
    listPending: () => listPendingCurationDelegations(client),
  };
}

async function requestCurationDelegationAction(event: Parameters<RequestCurationDelegationHandler>[0]) {
  const caller = curationCaller(event);
  requireDelegationAgent(caller);
  const client = await getDataClient();
  return requestDelegation(
    curationDelegationStore(client),
    {
      delegationId: normalizeRequiredString(event.arguments.delegationId, "delegationId"),
      tokenHash: normalizeRequiredString(event.arguments.tokenHash, "tokenHash"),
      agentLabel: normalizeRequiredString(event.arguments.agentLabel, "agentLabel"),
      hours: event.arguments.hours,
      requestedBySub: caller.lane === "cli-session" ? caller.sub : null,
    },
    new Date().toISOString(),
  );
}

async function approveCurationDelegationAction(event: Parameters<ApproveCurationDelegationHandler>[0]) {
  const person = requireSignedInPerson(event);
  const client = await getDataClient();
  const now = new Date().toISOString();
  return { ...(await approveDelegation(curationDelegationStore(client), person, normalizeRequiredString(event.arguments.userCode, "userCode"), now)), token: null };
}

async function denyCurationDelegationAction(event: Parameters<DenyCurationDelegationHandler>[0]) {
  const person = requireSignedInPerson(event, "withdrawer");
  const client = await getDataClient();
  const now = new Date().toISOString();
  return { ...(await denyDelegation(curationDelegationStore(client), person, normalizeRequiredString(event.arguments.userCode, "userCode"), now)), token: null };
}

async function getCurationDelegationStatusAction(event: Parameters<GetCurationDelegationStatusHandler>[0]) {
  requireDelegationAgent(curationCaller(event));
  const client = await getDataClient();
  return delegationStatus(curationDelegationStore(client), normalizeRequiredString(event.arguments.delegationId, "delegationId"), new Date().toISOString());
}

async function createCurationDelegation(event: Parameters<CreateCurationDelegationHandler>[0]) {
  const person = requireSignedInPerson(event);
  const client = await getDataClient();
  const now = new Date().toISOString();
  const delegationId = `curation-delegation-${randomUUID()}`;
  const { token, tokenHash } = newDelegationToken(delegationId);
  const delegation: CurationDelegation = {
    delegationId,
    tokenHash,
    grantorSub: person.sub,
    grantorLabel: person.label,
    agentLabel: normalizeRequiredString(event.arguments.agentLabel, "agentLabel"),
    createdAt: now,
    expiresAt: delegationExpiry(now, event.arguments.hours),
    revokedAt: null,
  };
  await writeCurationDelegation(client, delegation, now, true);
  return delegationResult(delegation, token);
}

async function revokeCurationDelegation(event: Parameters<RevokeCurationDelegationHandler>[0]) {
  const person = requireSignedInPerson(event, "withdrawer");
  const client = await getDataClient();
  const delegation = await readCurationDelegation(client, normalizeRequiredString(event.arguments.delegationId, "delegationId"));
  if (!delegation) throw new Error("That delegation was not found.");
  if (delegation.grantorSub !== person.sub && delegation.grantorSub !== PENDING_REQUEST_GRANTOR_SUB && !person.isAdmin) throw new Error("Only the person who granted a delegation can revoke it.");
  const now = new Date().toISOString();
  const revoked = { ...delegation, revokedAt: delegation.revokedAt ?? now };
  await writeCurationDelegation(client, revoked, now, false);
  return delegationResult(revoked, null);
}

async function listCurationDelegations(event: Parameters<ListCurationDelegationsHandler>[0]) {
  const person = requireSignedInPerson(event);
  const client = await getDataClient();
  const delegations = await listDelegationsByGrantor(client, person.sub);
  const now = new Date().toISOString();
  delegations.push(...(await livePendingRequests(curationDelegationStore(client), now)));
  return delegations
    .sort((first, second) => second.createdAt.localeCompare(first.createdAt))
    .map((delegation) => delegationResult(delegation, null));
}

/**
 * The checks every relayed decision passes before anything is written, whatever it records: the caller is on an agent route (the CLI client's
 * editor session, or an operator on AWS credentials), and the token belongs to an approved, unexpired, unrevoked delegation granted to this agent
 * by the person named. A delegation lives in this site's backend only, so another site's token is unknown here.
 */
async function verifiedDelegation(
  event: { identity?: unknown; arguments: { delegationId: string; delegationToken: string; agentLabel: string; onBehalfOf: string; instruction: string } },
  client: DataClient,
  now: string,
) {
  requireDelegationAgent(curationCaller(event));
  const delegationId = normalizeRequiredString(event.arguments.delegationId, "delegationId");
  const agentLabel = normalizeRequiredString(event.arguments.agentLabel, "agentLabel");
  const delegation = await readCurationDelegation(client, delegationId);
  const verdict = delegationVerdict(delegation, {
    token: normalizeRequiredString(event.arguments.delegationToken, "delegationToken"),
    agentLabel,
    now,
  });
  if (!verdict.ok || !delegation) {
    throw new Error(delegationRefusalMessage(verdict.ok ? "unknown-token" : verdict.reason));
  }
  const instruction = normalizeRequiredString(event.arguments.instruction, "instruction").slice(0, 2000);
  const namedPerson = normalizeRequiredString(event.arguments.onBehalfOf, "onBehalfOf");
  if (namedPerson.toLowerCase() !== delegation.grantorLabel.toLowerCase()) {
    throw new Error(`That delegation was granted by ${delegation.grantorLabel}, not ${namedPerson}.`);
  }
  return { delegation, delegationId, agentLabel, instruction };
}

/**
 * A star rating the person gave, relayed by an agent under the delegation they approved. The rules are `setReferenceStars` (a whole number from
 * 1 to 5, or none to clear; the star partition and the arrival time are kept with it). Like a relayed vote it is the person's decision carried by
 * an agent, so it is filed as "<person> via <agent> (delegation <id>)", never as the person's own direct rating.
 */
async function recordDelegatedStars(event: Parameters<RecordDelegatedStarsHandler>[0]) {
  const client = await getDataClient();
  const now = new Date().toISOString();
  const { delegation, delegationId, agentLabel } = await verifiedDelegation(event, client, now);
  return writeReferenceStars(client, {
    referenceId: normalizeRequiredString(event.arguments.referenceId, "referenceId"),
    stars: normalizeReferenceStars(event.arguments.stars),
    actor: `${delegation.grantorLabel} via ${agentLabel} (delegation ${delegationId})`,
    now,
    acceptOnRating: (referenceId, stars) => reviewReferenceCuration({
      ...event,
      arguments: { referenceId, action: "accept", note: starsAcceptNote(stars), actorSub: delegation.grantorSub, actorLabel: delegation.grantorLabel },
    } as unknown as Parameters<ReferenceCurationHandler>[0], { delegationId, relayedBy: agentLabel, instruction: normalizeRequiredString(event.arguments.instruction, "instruction").slice(0, 2000) }),
  });
}

async function recordDelegatedCuration(event: Parameters<RecordDelegatedCurationHandler>[0]) {
  const client = await getDataClient();
  const now = new Date().toISOString();
  const { delegation, delegationId, agentLabel, instruction } = await verifiedDelegation(event, client, now);
  const onBehalfOfPerson = {
    ...event,
    arguments: {
      referenceId: event.arguments.referenceId,
      action: event.arguments.action,
      note: event.arguments.note,
      reasonCode: event.arguments.reasonCode,
      decisionRelationId: event.arguments.decisionRelationId,
      shareable: event.arguments.shareable,
      sectionId: event.arguments.sectionId,
      actorSub: delegation.grantorSub,
      actorLabel: delegation.grantorLabel,
    },
  } as unknown as Parameters<ReferenceCurationHandler>[0];
  return reviewReferenceCuration(onBehalfOfPerson, { delegationId, relayedBy: agentLabel, instruction });
}

/**
 * An editor's optional 1-5 star interest in a Reference. The rating sits on the Reference beside the latest vote (who, when), the newest rating
 * wins, and `stars: null` clears it. It never touches the curation status and is never a Cyclotron label: stars are editorial interest, not relevance.
 * It also keeps the Reference in the right star partition (`starFeedKey`, docs/reference-feed-indexes.md): cleared with the rating, and a Reference with
 * no `feedArrivalAt` gets one, because the star index sorts by it and a row without it is not in the index.
 */
async function setReferenceStars(event: Parameters<ReferenceStarsHandler>[0]) {
  if (getIdentitySub(event)) requireEditorGroups(event, "accept, reject or rate");
  const client = await getDataClient();
  const actor = withViaNote(
    normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event) ?? "Papyrus newsroom",
    event,
    normalizeOptionalString((event.arguments as { agentLabel?: string | null }).agentLabel),
  );
  return writeReferenceStars(client, {
    referenceId: normalizeRequiredString(event.arguments.referenceId, "referenceId"),
    stars: normalizeReferenceStars(event.arguments.stars),
    actor,
    now: new Date().toISOString(),
    // Rating a pending Reference is also accepting it, by the same person and session, through the ordinary accept path.
    acceptOnRating: (referenceId, stars) => reviewReferenceCuration({
      ...event,
      arguments: { referenceId, action: "accept", note: starsAcceptNote(stars), actorSub: event.arguments.actorSub, actorLabel: event.arguments.actorLabel },
    } as unknown as Parameters<ReferenceCurationHandler>[0]),
  });
}

/**
 * Changes only a Reference's Section (`curationSectionId`) and records who and when (`curationSectionUpdatedBy`, `curationSectionUpdatedAt`) and what kind of
 * actor it was (`curationSectionActorKind`). It leaves the vote alone: the status, who voted and when, the note, the vote's actor kind, the feedback and the
 * star rating are not written, so the Cyclotron's vote id is unchanged and nothing is re-handed-off. The home page's Reference stream already watches
 * `curationSectionId`, so the snapshot is re-triggered the way an accept does it (docs/home-page.md, Freshness). A Section can be set only on an accepted
 * Reference and must be an enabled `NewsroomSection`; an empty `sectionId` clears it. A signed-in session must be an editor or admin; an operator on AWS
 * credentials (the IAM lane, decided by IAM policy) is recorded by role session, never by a name it sends.
 *
 * Two lanes (docs/reference-auto-section.md):
 * - A person (or an operator): actor kind `human` (a signed-in session) or `agent` (AWS credentials). A person's choice, including a clear, owns the section
 *   from then on: the automatic lane never changes it. Setting the section the machine already chose makes it the person's.
 * - The machine (`decisionRelationId` given): the site cyclotron's current section-selector decision for this Reference names the section. Recorded as
 *   `auto:cyclotron`, actor kind `cyclotron`, with the calibration evidence as the reason and the decision as the relation id. It is refused quietly
 *   (`changed: false`, `skipped` says why) when a person set or cleared the section, and refused loudly when the decision does not name that section.
 */
async function setReferenceSection(event: Parameters<ReferenceSectionHandler>[0]) {
  if (getIdentitySub(event)) requireEditorGroups(event, "set a section");
  const client = await getDataClient();
  const referenceId = normalizeRequiredString(event.arguments.referenceId, "referenceId");
  const requestedSectionId = normalizeOptionalString(event.arguments.sectionId);
  const decisionRelationId = normalizeOptionalString((event.arguments as { decisionRelationId?: string | null }).decisionRelationId);
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  const status = normalizeOptionalString(reference.curationStatus) ?? "pending";
  const previousSectionId = normalizeOptionalString(reference.curationSectionId);
  const previousKind = normalizeOptionalString((reference as { curationSectionActorKind?: string | null }).curationSectionActorKind);
  if (requestedSectionId && status !== "accepted") {
    throw new Error(`A section can be set only on an accepted Reference; this one is ${status}.`);
  }
  const sectionRecord = requestedSectionId
    ? (await client.models.NewsroomSection.get({ id: requestedSectionId })).data ?? null
    : null;
  const sectionId = validatedCurationSectionId(requestedSectionId, "accept", sectionRecord);
  const unchanged = { ok: true, referenceId, sectionId: previousSectionId, previousSectionId, changed: false, status, actorKind: previousKind };
  const now = new Date().toISOString();
  if (decisionRelationId) {
    // The automatic lane. A person who set or cleared the section owns it: never overwritten, never re-tagged.
    if (personOwnsSection(reference)) return { ...unchanged, skipped: "a person set or cleared this section" };
    if (!sectionId && previousKind !== "cyclotron") return { ...unchanged, skipped: "nothing to clear" };
    await requireSectionDecision(client, decisionRelationId, reference, sectionId);
    if (sectionId === previousSectionId && normalizeOptionalString((reference as { curationSectionDecisionRelationId?: string | null }).curationSectionDecisionRelationId) === decisionRelationId) {
      return unchanged;
    }
    await requireDataResult(
      client.models.Reference.update({
        id: referenceId, curationSectionId: sectionId, curationSectionUpdatedAt: now, curationSectionUpdatedBy: AUTO_SECTION_ACTOR,
        curationSectionActorKind: "cyclotron", curationSectionReason: normalizeOptionalString((event.arguments as { machineReason?: string | null }).machineReason)?.slice(0, 2000) ?? null,
        curationSectionDecisionRelationId: decisionRelationId,
      } as Parameters<typeof client.models.Reference.update>[0]),
      "update Reference section",
    );
    return { ok: true, referenceId, sectionId, previousSectionId, changed: true, status, actorKind: "cyclotron" };
  }
  const actorKind = curationActorKind(event.identity);
  if (sectionId === previousSectionId && previousKind !== "cyclotron" && (sectionId || previousKind)) return unchanged;
  const person = getIdentitySub(event)
    ? (getIdentityLabel(event) ?? getIdentitySub(event) ?? "Papyrus newsroom")
    : `Papyrus operator (${normalizeOptionalString(String((event.identity as { userArn?: unknown } | null | undefined)?.userArn ?? "").split("/").pop()) ?? "AWS credentials"})`;
  const actor = withViaNote(person, event, normalizeOptionalString((event.arguments as { agentLabel?: string | null }).agentLabel));
  await requireDataResult(
    client.models.Reference.update({
      id: referenceId, curationSectionId: sectionId, curationSectionUpdatedAt: now, curationSectionUpdatedBy: actor, ...personSectionProvenance(actorKind),
    } as Parameters<typeof client.models.Reference.update>[0]),
    "update Reference section",
  );
  return { ok: true, referenceId, sectionId, previousSectionId, changed: true, status, actorKind };
}

/** The signature of the automatic section lane, the same shape as the automatic accept's `auto:cyclotron`. */
const AUTO_SECTION_ACTOR = "auto:cyclotron";

/** The section provenance a person's (or operator's) choice leaves: their kind, and no machine reason or decision. */
function personSectionProvenance(actorKind: string): Record<string, unknown> {
  return { curationSectionActorKind: actorKind, curationSectionReason: null, curationSectionDecisionRelationId: null };
}

/**
 * True when a person (or an operator) set or cleared the section: someone other than the machine wrote it. A section recorded with an accept before the
 * actor kind existed has no kind and a section id, and is a person's too.
 */
function personOwnsSection(reference: Record<string, unknown>): boolean {
  const kind = normalizeOptionalString(reference.curationSectionActorKind as string | null | undefined);
  if (kind === "cyclotron") return false;
  return Boolean(kind || normalizeOptionalString(reference.curationSectionId as string | null | undefined) || normalizeOptionalString(reference.curationSectionUpdatedBy as string | null | undefined));
}

/** The automatic lane acts only on the site cyclotron's current section-selector decision for this Reference, and only for the section it chose. */
async function requireSectionDecision(client: DataClient, relationId: string, reference: Record<string, unknown>, sectionId: string | null) {
  const relation = (await client.models.SemanticRelation.get({ id: relationId })).data as Record<string, unknown> | null;
  const metadata = parseJsonObject(relation?.metadata);
  const classifierId = normalizeOptionalString(relation?.classifierId as string | null | undefined) ?? "";
  if (!relation || relation.predicate !== "site_decision_is" || relation.relationState !== "current"
      || relation.subjectLineageId !== (reference.lineageId ?? reference.id) || !classifierId.split("/").pop()?.startsWith("section-selector-")) {
    throw new Error(`Decision ${relationId} is not this Reference's current section-selector decision.`);
  }
  if (sectionId && metadata.label !== sectionId) {
    throw new Error(`Decision ${relationId} chose ${String(metadata.label)}, not ${sectionId}.`);
  }
}

function starsAcceptNote(stars: number): string {
  return `Accepted by rating it ${stars} of 5 stars.`;
}

async function writeReferenceStars(
  client: DataClient,
  input: {
    referenceId: string; stars: number | null; actor: string; now: string;
    acceptOnRating: (referenceId: string, stars: number) => Promise<{ status: string }>;
  },
) {
  const { referenceId, stars, actor, now } = input;
  const reference = await getRequiredRecord(client.models.Reference, referenceId, "Reference");
  await requireDataResult(
    client.models.Reference.update({
      id: referenceId,
      ...referenceStarFields(stars, actor, now),
      starFeedKey: starFeedKeyFor(normalizeOptionalString(reference.corpusId), stars),
      ...(normalizeOptionalString(reference.feedArrivalAt) ? {} : { feedArrivalAt: referenceFeedArrivalAt(reference as Parameters<typeof referenceFeedArrivalAt>[0]) }),
    }),
    "update Reference stars",
  );
  const status = normalizeOptionalString(reference.curationStatus) ?? "pending";
  // Any star on a pending Reference accepts it. An accepted or rejected one keeps its status, and clearing stars never changes it.
  if (stars !== null && status === "pending") {
    const accepted = await input.acceptOnRating(referenceId, stars);
    return { ok: true, referenceId, stars, status: accepted.status };
  }
  return { ok: true, referenceId, stars, status };
}

/**
 * An editor's optional 1-5 star rating of a Story (an Item lineage): what to publish, and later how to rank and feature it. Same rules as
 * `setReferenceStars`: separate from stage changes, the newest rating wins, `stars: null` clears it (and who and when), no reason needed.
 *
 * The rating sits on the lineage's newest version, because every new version is copied from it (`src/papyrus_content/item_stars.py`). It is a plain
 * update of that one row: it creates no version, never touches `stage`, `status`, `updatedAt` or the published copy, so rating a published Story
 * does not republish it. Stars are private editorial signals and are never copied to `PublishedItem` or any projection.
 */
async function setItemStars(event: Parameters<ItemStarsHandler>[0]) {
  if (getIdentitySub(event)) requireEditorGroups(event, "accept, reject or rate");
  const client = await getDataClient();
  const itemId = normalizeRequiredString(event.arguments.itemId, "itemId");
  const stars = normalizeReferenceStars(event.arguments.stars);
  const item = await getRequiredRecord(client.models.Item, itemId, "Item");
  if (!isStoryItemType(normalizeOptionalString(item.type) ?? "")) throw new Error("Only Stories can be rated.");
  const lineageId = normalizeOptionalString(item.lineageId) ?? itemId;
  const versions: Array<{ id: string; versionNumber?: number | null; versionState?: string | null; versionCreatedAt?: string | null }> = [];
  let nextToken: string | null | undefined;
  do {
    const page = await client.models.Item.listItemsByLineageAndVersion({ lineageId }, { limit: 200, nextToken });
    if (page.errors?.length) throw new Error(page.errors[0]?.message ?? "Could not read the Story's versions.");
    versions.push(...(page.data ?? []).filter(Boolean));
    nextToken = page.nextToken;
  } while (nextToken);
  // The working record, as `current_story_version` reads it: the row marked current (the most recently created if there are several), else the highest version.
  const marked = versions.filter((row) => row.versionState === "current");
  const pool = marked.length ? marked : versions;
  const newest = pool.length
    ? pool.reduce((best, row) => (`${row.versionCreatedAt ?? ""}|${String(row.versionNumber ?? 0).padStart(9, "0")}` > `${best.versionCreatedAt ?? ""}|${String(best.versionNumber ?? 0).padStart(9, "0")}` ? row : best))
    : { id: itemId };
  const now = new Date().toISOString();
  const actor = withViaNote(
    normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event) ?? "Papyrus newsroom",
    event,
    normalizeOptionalString((event.arguments as { agentLabel?: string | null }).agentLabel),
  );
  await requireDataResult(
    client.models.Item.update({ id: newest.id, ...referenceStarFields(stars, actor, now) }),
    "update Story stars",
  );
  await requestStoryStarsProjection(newest.id);
  return { ok: true, itemId: newest.id, lineageId, stars };
}

const STORY_STARS_PROJECTION_TASK = "story-stars";

/**
 * Tells the site's content-actions function that a Story's rating changed (one asynchronous invocation per rating, the Item version as the
 * only argument). It records the rating in the private rating store and re-renders the listing pages whose order the rating changed
 * (`src/papyrus_content/projection/story_stars_task.py`). Best effort: the rating is already saved, and a site with no projection (the
 * variable is unset) has no pages to refresh. A failed invocation is logged and the pages catch up the next time the Story is rated.
 */
async function requestStoryStarsProjection(itemId: string) {
  const functionName = (process.env.PAPYRUS_CONTENT_ACTIONS_FUNCTION ?? "").trim();
  if (!functionName) return;
  try {
    await new LambdaClient({}).send(
      new InvokeCommand({
        FunctionName: functionName,
        InvocationType: "Event",
        Payload: new TextEncoder().encode(JSON.stringify({ projectionTask: { task: STORY_STARS_PROJECTION_TASK, itemId, ...(currentTenantContext().tenantId ? { tenantId: currentTenantContext().tenantId } : {}) } })),
      }),
    );
  } catch (error) {
    console.error("Could not ask the site to refresh its listings after a Story rating", error);
  }
}

function normalizeReferenceStars(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isInteger(numeric) && numeric >= 1 && numeric <= 5) return numeric;
  throw new Error("stars must be an integer from 1 to 5, or empty to clear the rating.");
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
      newsroomFeedKey: reference.newsroomFeedKey ?? globalKey(REFERENCE_FEED_KEY, currentTenantContext().tenantId),
      reviewedFeedKey: reviewedFeedKeyForStatus(nextStatus),
      // A vote moves the Reference between the unrated and rated feeds; its original prediction and arrival stay as they were.
      feedStateKey: referenceFeedStateKey({ ...reference, curationStatus: nextStatus }),
      ...referenceMediumKeyPatch(reference, { curationStatus: nextStatus }),
      ...referencePublicKeyPatch(reference, { curationStatus: nextStatus }),
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

async function linkMessageHashtagsAction(event: Parameters<LinkMessageHashtagsHandler>[0]) {
  const client = await getDataClient();
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to link a message's hashtags.");
  const messageId = normalizeRequiredString(event.arguments.messageId, "messageId");
  const store: MessageHashtagStore = {
    getMessage: async (id) => {
      const response = await client.models.Message.get({ id });
      assertNoDataErrors(response.errors, "get Message");
      return response.data ?? null;
    },
    listAcceptedConceptNodes: async () => {
      const nodes: Array<{ id: string; lineageId?: string | null; versionNumber?: number | null; nodeKey: string }> = [];
      let nextToken: string | null | undefined;
      do {
        const page = await (client.models.SemanticNode as any).listSemanticNodesByVersionStateAndUpdatedAt({ versionState: "current" }, { limit: 500, nextToken });
        assertNoDataErrors(page.errors, "list SemanticNodes");
        for (const node of page.data ?? []) if (node.status === "accepted") nodes.push(node);
        nextToken = page.nextToken;
      } while (nextToken);
      return nodes;
    },
    getRelation: async (id) => {
      const response = await client.models.SemanticRelation.get({ id });
      assertNoDataErrors(response.errors, "get SemanticRelation");
      return response.data ?? null;
    },
    putRelation: async (relation, existing) => {
      const write = existing ? client.models.SemanticRelation.update(relation as any) : client.models.SemanticRelation.create({ ...relation, createdAt: relation.updatedAt } as any);
      await requireDataResult(write, "write message concept SemanticRelation");
    },
    setMessageMetadata: async (id, metadata) => {
      await requireDataResult(client.models.Message.update({ id, metadata: JSON.stringify(metadata) }), "update Message metadata");
    },
  };
  return linkMessageHashtags(store, { messageId, callerSub, now: new Date().toISOString() });
}

async function referenceLinkStore(): Promise<ReferenceLinkStore & { updateSemanticNode(node: Record<string, unknown>): Promise<void> }> {
  const client = await getDataClient();
  return {
    getCurrentReference: async (idOrLineageId) => {
      const direct = await client.models.Reference.get({ id: idOrLineageId });
      assertNoDataErrors(direct.errors, "get Reference");
      if (direct.data) return direct.data;
      const versions: Array<{ id: string; lineageId?: string | null; versionNumber?: number | null; versionState?: string | null }> = [];
      let nextToken: string | null | undefined;
      do {
        const page = await (client.models.Reference as any).listReferencesByLineageAndVersion({ lineageId: idOrLineageId }, { limit: 100, nextToken });
        assertNoDataErrors(page.errors, "list Reference versions");
        versions.push(...(page.data ?? []));
        nextToken = page.nextToken;
      } while (nextToken);
      const current = versions.filter((version) => version.versionState === "current");
      const candidates = current.length ? current : versions;
      return candidates.reduce<(typeof versions)[number] | null>((best, version) => (best === null || (version.versionNumber ?? 0) > (best.versionNumber ?? 0) ? version : best), null);
    },
    getSemanticNode: async (lineageId) => {
      const direct = await client.models.SemanticNode.get({ id: lineageId });
      assertNoDataErrors(direct.errors, "get SemanticNode");
      if (direct.data) return direct.data;
      const page = await (client.models.SemanticNode as any).listSemanticNodesByLineageAndVersion({ lineageId }, { limit: 100 });
      assertNoDataErrors(page.errors, "list SemanticNode versions");
      const versions: Array<{ id: string; lineageId?: string | null; versionNumber?: number | null; versionState?: string | null }> = page.data ?? [];
      const current = versions.filter((version) => version.versionState === "current");
      const candidates = current.length ? current : versions;
      return candidates.reduce<(typeof versions)[number] | null>((best, version) => (best === null || (version.versionNumber ?? 0) > (best.versionNumber ?? 0) ? version : best), null);
    },
    getRelation: async (id) => {
      const response = await client.models.SemanticRelation.get({ id });
      assertNoDataErrors(response.errors, "get SemanticRelation");
      return response.data ?? null;
    },
    createSemanticNode: async (node) => {
      const response = await client.models.SemanticNode.create(node as any);
      if (response.errors?.length) return false;   // the id exists (a second tap): the caller reads it back
      return true;
    },
    updateSemanticNode: async (node: Record<string, unknown>) => {
      await requireDataResult(client.models.SemanticNode.update(node as any), "update SemanticNode description");
    },
    putRelation: async (relation, existing) => {
      const write = existing ? client.models.SemanticRelation.update(relation as any) : client.models.SemanticRelation.create({ ...relation, createdAt: relation.updatedAt } as any);
      await requireDataResult(write, "write reference link SemanticRelation");
    },
  };
}

async function createReferenceLinkAction(event: Parameters<CreateReferenceLinkHandler>[0]) {
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to link References.");
  return createReferenceLink(await referenceLinkStore(), {
    subjectLineageId: normalizeRequiredString(event.arguments.subjectLineageId, "subjectLineageId"),
    objectKind: normalizeRequiredString(event.arguments.objectKind, "objectKind"),
    objectLineageId: normalizeRequiredString(event.arguments.objectLineageId, "objectLineageId"),
    predicate: normalizeRequiredString(event.arguments.predicate, "predicate"),
    note: normalizeOptionalString(event.arguments.note),
    newConceptName: normalizeOptionalString(event.arguments.newConceptName),
    callerSub,
    now: new Date().toISOString(),
    origin: editOriginOfIdentity(event.identity),
  });
}

async function createEditorConceptAction(event: Parameters<CreateEditorConceptHandler>[0]) {
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to create a concept.");
  const node = await ensureEditorConcept((await referenceLinkStore()) as any, normalizeRequiredString(event.arguments.name, "name"), callerSub, new Date().toISOString(), {
    displayName: normalizeOptionalString(event.arguments.displayName),
    origin: editOriginOfIdentity(event.identity),
  });
  return { ok: true, lineageId: node.lineageId ?? node.id, nodeKey: node.nodeKey ?? null, displayName: (node as { displayName?: string | null }).displayName ?? null, nodeKind: node.nodeKind ?? null };
}

async function describeConceptAction(event: Parameters<DescribeConceptHandler>[0]) {
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to describe a concept.");
  return describeEditorConcept((await referenceLinkStore()) as any, {
    lineageId: normalizeRequiredString(event.arguments.lineageId, "lineageId"),
    description: normalizeOptionalString(event.arguments.description),
    callerSub,
    now: new Date().toISOString(),
    origin: editOriginOfIdentity(event.identity),
  });
}

async function decideReferenceLinkAction(event: Parameters<DecideReferenceLinkHandler>[0]) {
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to decide on a link.");
  return decideReferenceLink(await referenceLinkStore(), {
    relationId: normalizeRequiredString(event.arguments.relationId, "relationId"),
    decision: normalizeRequiredString(event.arguments.decision, "decision"),
    reasonCode: normalizeOptionalString(event.arguments.reasonCode),
    note: normalizeOptionalString(event.arguments.note),
    callerSub,
    now: new Date().toISOString(),
    origin: editOriginOfIdentity(event.identity),
  });
}

/** An editor changes a Story source's role (consulted to cited) on a model their token may not update: see story-reference-role.ts. */
async function setStoryReferenceRoleAction(event: Parameters<SetStoryReferenceRoleHandler>[0]) {
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to change a Story's source.");
  const claims = (event.identity as { claims?: Record<string, unknown> } | null | undefined)?.claims ?? {};
  const client = await getDataClient();
  return setStoryReferenceRole(
    {
      getRelation: async (id) => {
        const response = await client.models.SemanticRelation.get({ id });
        assertNoDataErrors(response.errors, "get SemanticRelation");
        return (response.data as any) ?? null;
      },
      updateRelation: async (patch) => {
        await requireDataResult(client.models.SemanticRelation.update(patch as any), "update Story source SemanticRelation");
      },
    },
    {
      relationId: normalizeRequiredString(event.arguments.relationId, "relationId"),
      role: normalizeRequiredString(event.arguments.role, "role"),
      callerGroups: claimGroups(claims["cognito:groups"]),
      citationKey: normalizeOptionalString(event.arguments.citationKey),
      note: normalizeOptionalString(event.arguments.note),
      actor: getIdentityLabel(event) ?? callerSub,
      now: new Date().toISOString(),
      origin: editOriginOfIdentity(event.identity),
    },
  );
}

async function createConceptLinkAction(event: Parameters<CreateConceptLinkHandler>[0]) {
  const callerSub = getIdentitySub(event);
  if (!callerSub) throw new Error("Sign in to link concepts.");
  requireEditorGroups(event, "link concepts");
  return createConceptLink(await referenceLinkStore(), {
    subjectLineageId: normalizeRequiredString(event.arguments.subjectLineageId, "subjectLineageId"),
    objectLineageId: normalizeRequiredString(event.arguments.objectLineageId, "objectLineageId"),
    note: normalizeOptionalString(event.arguments.note),
    callerSub,
    now: new Date().toISOString(),
    origin: editOriginOfIdentity(event.identity),
  });
}

/** The schema lets only the editor and admin groups call these routes; this repeats the check, so a rule loosened by mistake still does not open them. */
function requireEditorGroups(event: { identity?: unknown }, doing: string) {
  const claims = (event.identity as { claims?: Record<string, unknown> } | null | undefined)?.claims ?? {};
  if (!hasEditorRights(claimGroups(claims["cognito:groups"]))) throw new Error(`Only an editor or administrator can ${doing}.`);
}

async function applyKnowledgeReviewAction(event: Parameters<ApplyKnowledgeReviewHandler>[0]) {
  if (!getIdentitySub(event)) throw new Error("Sign in to review knowledge.");
  requireEditorGroups(event, "review knowledge");
  const client = await getDataClient();
  const store: KnowledgeReviewStore = {
    getNode: async (id) => {
      const response = await client.models.SemanticNode.get({ id });
      assertNoDataErrors(response.errors, "get SemanticNode");
      return (response.data as any) ?? null;
    },
    updateNode: async (patch) => {
      await requireDataResult(client.models.SemanticNode.update(patch as any), "update SemanticNode");
    },
    getRelation: async (id) => {
      const response = await client.models.SemanticRelation.get({ id });
      assertNoDataErrors(response.errors, "get SemanticRelation");
      return (response.data as any) ?? null;
    },
    updateRelation: async (patch) => {
      await requireDataResult(client.models.SemanticRelation.update(patch as any), "update SemanticRelation");
    },
  };
  return applyKnowledgeReview(store, { patches: event.arguments.patches, origin: editOriginOfIdentity(event.identity) });
}

async function createReferenceNote(event: Parameters<ReferenceNoteHandler>[0]) {
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
  const messageId = `message-reference-note-${safeId(referenceLineageId)}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const relationId = `semantic-relation-${hashStable([
    `message#${messageId}`,
    "note_about",
    `reference#${referenceId}`,
  ]).slice(0, 24)}`;

  await requireDataResult(
    client.models.Message.create({
      ...buildCanonicalMessageInput({
        id: messageId,
        messageKind: "note",
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
    "create note Message",
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
      kind: "reference.note.created",
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
      predicate: "note_about",
      ...semanticRelationTypeFieldsForPredicate("note_about"),
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
      predicateObjectStateKey: `note_about#${semanticStateKey("reference", referenceLineageId)}`,
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
      newsroomFeedKey: globalKey(SEMANTIC_RELATION_FEED_KEY, currentTenantContext().tenantId),
      metadata: JSON.stringify({
        kind: "reference.note",
        summary,
        actor,
      }),
    }),
    "create note_about relation",
  );
  await updateNewsroomSummaryForSemanticRelationDelta(
    client,
    {
      relationTypeKey: "note_about",
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
        feedStateKey: null,   // a superseded version is in no feed
        ...(current.mediumFeedKey ? { mediumFeedKey: null } : {}),   // nor in a medium list
        ...(current.contentNeededKey ? { contentNeededKey: null } : {}),   // nor in the list of videos waiting for content
        ...(current.publicFeedKey ? { publicFeedKey: null, publicOrderKey: null } : {}),   // nor in the public index
        updatedAt: now,
      }),
      "supersede current Reference version",
    );
  }

  const movedPublicKeys = referencePublicFeedKeys({
    id: nextReferenceId,
    corpusId: targetCorpusId,
    curationStatus,
    versionState: "current",
    predictedAcceptProbability: typeof current.predictedAcceptProbability === "number" ? current.predictedAcceptProbability : null,
    createdAt: normalizeOptionalString(current.createdAt) ?? now,
    importedAt: normalizeOptionalString(current.importedAt),
    retrievedAt: normalizeOptionalString(current.retrievedAt),
    sourcePublishedAt: normalizeOptionalString(current.sourcePublishedAt),
  });
  const movedContentKey = current.medium
    ? referenceContentNeededKey({ id: nextReferenceId, corpusId: targetCorpusId, curationStatus, versionState: "current", medium: current.medium, captureState: current.captureState, captureReason: current.captureReason })
    : null;

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
      ...(current.starRating ? { starRating: current.starRating, starRatedAt: current.starRatedAt, starRatedBy: current.starRatedBy, starFeedKey: starFeedKeyFor(targetCorpusId, current.starRating) } : {}),
      ...(current.captureState ? { captureState: current.captureState } : {}),
      ...(current.captureReason ? { captureReason: current.captureReason } : {}),
      ...(current.thumbnailPath ? { thumbnailPath: current.thumbnailPath } : {}),
      ...(current.medium ? { medium: current.medium } : {}),
      ...(current.evidenceLevel ? { evidenceLevel: current.evidenceLevel } : {}),
      ...(current.playlistUrl ? { playlistUrl: current.playlistUrl } : {}),
      ...(current.cardImage ? { cardImage: current.cardImage } : {}),   // the card copies come from the preview, which is read by lineage, so they move with the Reference
      ...(current.cardSummary ? { cardSummary: current.cardSummary } : {}),
      ...(current.cardSiteName ? { cardSiteName: current.cardSiteName } : {}),
      ...(current.cardPageTitle ? { cardPageTitle: current.cardPageTitle } : {}),
      curationStatus,
      curationStatusKey: `${targetCorpusId}#${curationStatus}`,
      curationStatusUpdatedAt: normalizeOptionalString(current.curationStatusUpdatedAt) ?? now,
      curationStatusUpdatedBy: normalizeOptionalString(current.curationStatusUpdatedBy) ?? actor,
      curationStatusReason: normalizeOptionalString(current.curationStatusReason),
      curationReasonCode: normalizeOptionalString(current.curationReasonCode),
      curationActorKind: normalizeOptionalString(current.curationActorKind),
      curationSectionId: normalizeOptionalString(current.curationSectionId),
      curationSectionUpdatedAt: normalizeOptionalString(current.curationSectionUpdatedAt),
      curationSectionUpdatedBy: normalizeOptionalString(current.curationSectionUpdatedBy),
      curationSectionActorKind: normalizeOptionalString((current as { curationSectionActorKind?: string | null }).curationSectionActorKind),
      curationSectionReason: normalizeOptionalString((current as { curationSectionReason?: string | null }).curationSectionReason),
      curationSectionDecisionRelationId: normalizeOptionalString((current as { curationSectionDecisionRelationId?: string | null }).curationSectionDecisionRelationId),
      curationShareable: typeof current.curationShareable === "boolean" ? current.curationShareable : null,
      curationDelegation: current.curationDelegation ?? null,
      curationDecisionRelationId: normalizeOptionalString(current.curationDecisionRelationId),
      newsroomFeedKey: normalizeOptionalString(current.newsroomFeedKey) ?? globalKey(REFERENCE_FEED_KEY, currentTenantContext().tenantId),
      reviewedFeedKey: normalizeOptionalString(current.reviewedFeedKey) ?? reviewedFeedKeyForStatus(curationStatus),
      predictedAcceptProbability: typeof current.predictedAcceptProbability === "number" ? current.predictedAcceptProbability : null,
      predictionDecidedAt: normalizeOptionalString(current.predictionDecidedAt),
      ...referenceFeedKeys({
        id: nextReferenceId,
        corpusId: targetCorpusId,
        curationStatus,
        versionState: "current",
        predictedAcceptProbability: typeof current.predictedAcceptProbability === "number" ? current.predictedAcceptProbability : null,
        createdAt: normalizeOptionalString(current.createdAt) ?? now,
        importedAt: normalizeOptionalString(current.importedAt),
        retrievedAt: normalizeOptionalString(current.retrievedAt),
        sourcePublishedAt: normalizeOptionalString(current.sourcePublishedAt),
      }),
      ...(current.medium ? { mediumFeedKey: referenceMediumFeedKey({ id: nextReferenceId, corpusId: targetCorpusId, curationStatus, versionState: "current", medium: current.medium }) } : {}),
      ...(movedPublicKeys.publicFeedKey ? movedPublicKeys : {}),   // sparse too: no explicit null on a new row
      ...(movedContentKey ? { contentNeededKey: movedContentKey } : {}),   // never an explicit null on a new row: that is not a missing index key attribute
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
      newsroomFeedKey: globalKey(SEMANTIC_RELATION_FEED_KEY, currentTenantContext().tenantId),
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
  if (predicate === "note_about") {
    return {
      relationTypeId: "semantic-relation-type-note-about",
      relationTypeKey: "note_about",
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
    newsroomFeedKey: globalKey(SEMANTIC_RELATION_FEED_KEY, currentTenantContext().tenantId),
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
    newsroomFeedKey: globalKey(SEMANTIC_RELATION_FEED_KEY, currentTenantContext().tenantId),
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
  const response = await client.models.KnowledgeRawPayload.get({ id: newsroomSummaryPayloadId(currentTenantContext()) });
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
  return tenantScopedClient(await clientPromise, currentTenantContext());
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
  return status === "pending" ? null : globalKey(REFERENCE_REVIEWED_FEED_KEY, currentTenantContext().tenantId);
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

/** A supplied reason code, validated. Whether a rejection has a reason at all is the caller's rule. */
function normalizeReferenceRejectionReasonCode(value: unknown): string | null {
  const normalized = normalizePolicyToken(value);
  if (!normalized) return null;
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
  const response = await client.models.KnowledgeRawPayload.get({ id: newsroomSummaryPayloadId(currentTenantContext()) });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const payload = normalizeSummaryPayload(await readNewsroomSummaryPayload(client), input.now);
  payload.generatedAt = input.now;
  payload.staleAt = new Date(Date.parse(input.now) + SUMMARY_STALE_AFTER_MS).toISOString();
  payload.source = "incremental";
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
  await upsertNewsroomSummaryPayload(client, payload, response.data, input.now);
}

async function updateNewsroomSummaryForReferenceStatus(
  client: DataClient,
  input: { corpusId: string | null; previousStatus: string; nextStatus: string; now: string },
): Promise<void> {
  const response = await client.models.KnowledgeRawPayload.get({ id: newsroomSummaryPayloadId(currentTenantContext()) });
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
    id: newsroomSummaryPayloadId(currentTenantContext()),
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
    { ownerKind: NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND, ownerId: newsroomSummaryPayloadId(currentTenantContext()), importRunId: input.importRunId },
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
    newsroomSummaryPayloadId(currentTenantContext()),
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
