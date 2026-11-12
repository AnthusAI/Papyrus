import { type ClientSchema, a } from "@aws-amplify/backend";
import { assignmentAction } from "../functions/assignment-action/resource";
import { categoryAction } from "../functions/category-action/resource";
import { editorialChecksSchemaDefinitions } from "../functions/editorial-checks/schema";
import { automationViewSchemaDefinitions } from "../functions/automation-view/schema";
import { imageService } from "../functions/image-service/resource";
import { imageServiceSchemaDefinitions } from "../functions/image-service/schema";
import { proposalActionsSchemaDefinitions } from "../functions/proposal-actions/schema";
import { messageActionsSchemaDefinitions } from "./message-actions";
import { profileActionsSchemaDefinitions } from "./profile-actions";
import { monitoringViewSchemaDefinitions } from "../functions/monitoring-view/schema";
import { contentActions } from "../functions/content-actions/resource";
import { knowledgeQuery } from "../functions/knowledge-query/resource";
import { manageUserRole } from "../functions/manage-user-role/resource";
import { modelAttachmentUpload } from "../functions/model-attachment-upload/resource";
import { newsroomSummary } from "../functions/newsroom-summary/resource";
import { publicForms } from "../functions/public-forms/resource";
import { procedureAction } from "../functions/procedure-action/resource";
import { readerSettings } from "../functions/reader-settings/resource";
import { functionHandler } from "./function-handler";

const authoringOperations: ("read" | "create" | "update" | "delete")[] = [
  "read",
  "create",
  "update",
  "delete",
];
const contentWriteGroups = ["editor", "admin"];
const adminGroup = "admin";
const categoryWriteGroups = ["editor", "admin"];
const categoryAppendOnlyOperations: ("read" | "create")[] = ["read", "create"];
const modelWithoutSubscriptions = <Fields extends Parameters<typeof a.model>[0]>(fields: Fields) =>
  a.model(fields).disableOperations(["subscriptions"]);
const realtimeModel = <Fields extends Parameters<typeof a.model>[0]>(fields: Fields) => a.model(fields);

/**
 * Model groups a site may leave out of its data API. CloudFormation creates at most 2,500 resources in one stack
 * operation, nested stacks included, and the full model set exceeds that on a fresh create. A first deploy that
 * excludes groups fits; a second deploy without the exclusion adds the models as an ordinary update.
 *
 * A group may hold only models that no other model relates to (`hasMany`, `belongsTo`) and that no custom operation
 * returns, because leaving them out must leave a valid schema. `editions` is the exception: `Item.editionItems` is
 * dropped with it (see `buildBaseDefinitions`).
 */
export const OPTIONAL_MODEL_GROUPS = {
  editions: ["Edition", "EditionItem", "PublishedEdition", "PublishedEditionItem"],
  knowledge: ["KnowledgeArtifact", "KnowledgeCorpus", "KnowledgeImportRun", "KnowledgeRawPayload"],
  semantic: ["SemanticNode", "SemanticRelation", "SemanticRelationType"],
  review: ["ReviewRequest", "ReviewRecipientRule", "ReviewReadMark"],
  procedures: ["ProcedureDefinition", "ProcedureRun", "ProcedureVersion"],
  editorial: ["EditorialCheckRun", "EditorialFeedback", "EditorialPolicy", "EditorialCheckSettings"],
  steering: ["SteeringProposal", "SteeringDecision", "LexicalSteeringRule"],
  variations: ["StoryVariation"],
  tenancy: ["Tenant", "TenantMembership", "TenantDomain"],
} as const;

/**
 * The groups a bootstrap deploy leaves out (`PAPYRUS_BOOTSTRAP_STAGE=1`, docs/site-hosting.md). Every group is deferred,
 * so the first create of a brand-new site stays well under the CloudFormation per-operation limit.
 */
export const BOOTSTRAP_DEFERRED_GROUPS = Object.keys(OPTIONAL_MODEL_GROUPS) as OptionalModelGroup[];

export type OptionalModelGroup = keyof typeof OPTIONAL_MODEL_GROUPS;

/**
 * The groups to leave out of this synth: the site's `excludeModelGroups` plus, when the Amplify branch variable
 * `PAPYRUS_BOOTSTRAP_STAGE` is `1`, every deferred group. Unset (or any other value), nothing is added.
 */
/** True when the Amplify branch variable `PAPYRUS_BOOTSTRAP_STAGE` is exactly `1`: the first deploy of a new site. */
export function isBootstrapStage(environment: Record<string, string | undefined>): boolean {
  return (environment.PAPYRUS_BOOTSTRAP_STAGE ?? "").trim() === "1";
}

export function resolveExcludedModelGroups(
  configured: readonly string[] | undefined,
  environment: Record<string, string | undefined>,
): string[] {
  const groups = [...(configured ?? [])];
  if (isBootstrapStage(environment)) {
    for (const group of BOOTSTRAP_DEFERRED_GROUPS) if (!groups.includes(group)) groups.push(group);
  }
  return groups;
}

export function assertKnownModelGroups(groups: readonly string[]): asserts groups is readonly OptionalModelGroup[] {
  for (const group of groups) {
    if (!(group in OPTIONAL_MODEL_GROUPS)) {
      throw new Error(`Unknown model group "${group}"; known groups: ${Object.keys(OPTIONAL_MODEL_GROUPS).join(", ")}`);
    }
  }
}

function buildBaseDefinitions(excludedGroups: readonly OptionalModelGroup[] = []) {
const includeEditions = !excludedGroups.includes("editions");
const definitions = {
  UserProfile: modelWithoutSubscriptions({
      id: a.id().required(),
      email: a.email(),
      displayName: a.string(),
      publicHandle: a.string(),
      avatarUrl: a.url(),
      preferences: a.json(),
      settings: a.json(),
      status: a.string(),
      mergedIntoProfileId: a.id(),
      mergedAt: a.datetime(),
      mergedBy: a.string(),
      mergeReason: a.string(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("publicHandle").name("userProfilesByPublicHandle").queryField("userProfileByPublicHandle"),
    ])
    .authorization((allow) => [
      allow.owner(),
      allow.group(adminGroup),
    ]),

  PublicHandleClaim: modelWithoutSubscriptions({
      id: a.id().required(),
      ownerKind: a.string().required(),
      ownerId: a.string().required(),
      claimedAt: a.datetime().required(),
    })
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  UserIdentity: modelWithoutSubscriptions({
      id: a.id().required(),
      userProfileId: a.id().required(),
      cognitoSub: a.string().required(),
      provider: a.string(),
      email: a.email(),
      status: a.string().required(),
      linkedAt: a.datetime().required(),
      lastSeenAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("userProfileId").sortKeys(["linkedAt"]).queryField("listUserIdentitiesByProfileAndLinkedAt"),
      index("cognitoSub").queryField("userIdentityByCognitoSub"),
      index("email").sortKeys(["status"]).queryField("listUserIdentitiesByEmailAndStatus"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
    ]),

  UserRoleAssignment: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      userProfileId: a.id().required(),
      userSub: a.string(),
      email: a.email(),
      role: a.string().required(),
      status: a.string().required(),
      grantedBy: a.string().required(),
      grantedAt: a.datetime().required(),
      revokedAt: a.datetime(),
      notes: a.string(),
    })
    .secondaryIndexes((index) => [
      index("userProfileId").sortKeys(["role"]).queryField("listUserRoleAssignmentsByProfileAndRole"),
      index("userSub").sortKeys(["role"]).queryField("listUserRoleAssignmentsByUserAndRole"),
      index("role").sortKeys(["status"]).queryField("listUserRoleAssignmentsByRoleAndStatus"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
    ]),

  UserRoleMutationResult: a.customType({
    ok: a.boolean().required(),
    userProfileId: a.id(),
    userSub: a.string(),
    username: a.string(),
    role: a.string().required(),
    userSubs: a.string().array(),
    usernames: a.string().array(),
    activeRoles: a.string().array().required(),
  }),

  UserDirectoryIdentity: a.customType({
    id: a.id().required(),
    userProfileId: a.id().required(),
    cognitoSub: a.string().required(),
    provider: a.string(),
    email: a.email(),
    status: a.string().required(),
    linkedAt: a.datetime().required(),
    lastSeenAt: a.datetime(),
  }),

  UserDirectoryEntry: a.customType({
    userProfileId: a.id(),
    userSub: a.string(),
    username: a.string(),
    email: a.email(),
    displayName: a.string(),
    provider: a.string(),
    enabled: a.boolean(),
    cognitoStatus: a.string(),
    profileStatus: a.string(),
    mergedIntoProfileId: a.id(),
    identityStatus: a.string(),
    activeRoles: a.string().array().required(),
    identities: a.ref("UserDirectoryIdentity").array().required(),
  }),

  UserDirectoryResult: a.customType({
    entries: a.ref("UserDirectoryEntry").array().required(),
    profileCount: a.integer().required(),
    identityCount: a.integer().required(),
    cognitoUserCount: a.integer().required(),
  }),

  ReaderSettingsResult: a.customType({
    userProfileId: a.id().required(),
    publicHandle: a.string(),
    settings: a.json(),
  }),

  listUserDirectory: a
    .query()
    .returns(a.ref("UserDirectoryResult"))
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("manageUserRole", manageUserRole)),

  grantUserRole: a
    .mutation()
    .arguments({
      userProfileId: a.id(),
      userSub: a.string(),
      cognitoSubs: a.string().array(),
      role: a.string().required(),
    })
    .returns(a.ref("UserRoleMutationResult"))
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("manageUserRole", manageUserRole)),

  revokeUserRole: a
    .mutation()
    .arguments({
      userProfileId: a.id(),
      userSub: a.string(),
      cognitoSubs: a.string().array(),
      role: a.string().required(),
    })
    .returns(a.ref("UserRoleMutationResult"))
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("manageUserRole", manageUserRole)),

  mergeUserProfiles: a
    .mutation()
    .arguments({
      targetUserProfileId: a.id(),
      targetUserSub: a.string(),
      sourceUserProfileId: a.id(),
      sourceUserSub: a.string(),
      reason: a.string(),
    })
    .returns(a.ref("UserDirectoryEntry"))
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("manageUserRole", manageUserRole)),

  getReaderSettings: a
    .query()
    .returns(a.ref("ReaderSettingsResult"))
    .authorization((allow) => [allow.authenticated()])
    .handler(functionHandler("readerSettings", readerSettings)),

  updateReaderSettings: a
    .mutation()
    .arguments({
      settings: a.json().required(),
    })
    .returns(a.ref("ReaderSettingsResult"))
    .authorization((allow) => [allow.authenticated()])
    .handler(functionHandler("readerSettings", readerSettings)),

  SteeringActionResult: a.customType({
    ok: a.boolean().required(),
    action: a.string().required(),
    proposalId: a.id(),
    categorySetId: a.id(),
    categoryId: a.id(),
    decisionId: a.id(),
    status: a.string(),
  }),

  reviewSteeringProposal: a
    .mutation()
    .arguments({
      proposalId: a.id().required(),
      action: a.string().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
      displayName: a.string(),
      shortTitle: a.string(),
      subtitle: a.string(),
      description: a.string(),
      aliases: a.string().array(),
      seedItemIds: a.string().array(),
      holdoutItemIds: a.string().array(),
    })
    .returns(a.ref("SteeringActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  CurationDelegationResult: a.customType({
    ok: a.boolean().required(),
    delegationId: a.id().required(),
    token: a.string(),
    agentLabel: a.string().required(),
    grantorLabel: a.string(),
    expiresAt: a.datetime().required(),
    revokedAt: a.datetime(),
    state: a.string(),
    userCode: a.string(),
    requestedHours: a.integer(),
    pendingExpiresAt: a.datetime(),
    approvedAt: a.datetime(),
    deniedAt: a.datetime(),
  }),

  CurationDelegationRequestResult: a.customType({
    ok: a.boolean().required(),
    delegationId: a.id().required(),
    userCode: a.string().required(),
    pendingExpiresAt: a.datetime().required(),
    requestedHours: a.integer().required(),
  }),

  CurationDelegationStatusResult: a.customType({
    delegationId: a.id().required(),
    state: a.string().required(),
    expiresAt: a.datetime().required(),
    grantorLabel: a.string(),
  }),

  ReferenceCurationActionResult: a.customType({
    ok: a.boolean().required(),
    action: a.string().required(),
    referenceId: a.id().required(),
    status: a.string().required(),
    reasonCode: a.string(),
  }),

  ReferenceSectionActionResult: a.customType({
    ok: a.boolean().required(),
    referenceId: a.id().required(),
    sectionId: a.id(),
    previousSectionId: a.id(),
    changed: a.boolean().required(),
    status: a.string().required(),
  }),

  ReferenceStarsActionResult: a.customType({
    ok: a.boolean().required(),
    referenceId: a.id().required(),
    stars: a.integer(),
    status: a.string().required(),
  }),

  ItemStarsActionResult: a.customType({
    ok: a.boolean().required(),
    itemId: a.id().required(),
    lineageId: a.id().required(),
    stars: a.integer(),
  }),

  ReferenceQualityActionResult: a.customType({
    ok: a.boolean().required(),
    referenceId: a.id().required(),
    rating: a.integer().required(),
    status: a.string().required(),
    relationId: a.id(),
  }),

  CategorySetDraftActionResult: a.customType({
    ok: a.boolean().required(),
    action: a.string().required(),
    categorySetId: a.id().required(),
    sourceCategorySetId: a.id(),
    categoryCount: a.integer(),
    status: a.string(),
  }),

  TopicLabelActionResult: a.customType({
    ok: a.boolean().required(),
    action: a.string().required(),
    referenceId: a.id(),
    categoryId: a.id(),
    relationId: a.id(),
    sourceRelationId: a.id(),
    status: a.string(),
  }),

  reviewReferenceCuration: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      action: a.string().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      agentLabel: a.string(),
      note: a.string(),
      reasonCode: a.string(),
      decisionRelationId: a.id(),
      shareable: a.boolean(),
      sectionId: a.id(),
    })
    .returns(a.ref("ReferenceCurationActionResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  createCurationDelegation: a
    .mutation()
    .arguments({
      agentLabel: a.string().required(),
      hours: a.integer(),
    })
    .returns(a.ref("CurationDelegationResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  revokeCurationDelegation: a
    .mutation()
    .arguments({
      delegationId: a.id().required(),
    })
    .returns(a.ref("CurationDelegationResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  listCurationDelegations: a
    .query()
    .returns(a.ref("CurationDelegationResult").array())
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  requestCurationDelegation: a
    .mutation()
    .arguments({
      delegationId: a.id().required(),
      tokenHash: a.string().required(),
      agentLabel: a.string().required(),
      hours: a.integer(),
    })
    .returns(a.ref("CurationDelegationRequestResult"))
    .authorization((allow) => [
      allow.authenticated("identityPool"),
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  approveCurationDelegation: a
    .mutation()
    .arguments({
      userCode: a.string().required(),
    })
    .returns(a.ref("CurationDelegationResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  denyCurationDelegation: a
    .mutation()
    .arguments({
      userCode: a.string().required(),
    })
    .returns(a.ref("CurationDelegationResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  getCurationDelegationStatus: a
    .query()
    .arguments({
      delegationId: a.id().required(),
    })
    .returns(a.ref("CurationDelegationStatusResult"))
    .authorization((allow) => [
      allow.authenticated("identityPool"),
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  recordDelegatedCuration: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      action: a.string().required(),
      delegationId: a.id().required(),
      delegationToken: a.string().required(),
      agentLabel: a.string().required(),
      onBehalfOf: a.string().required(),
      instruction: a.string().required(),
      note: a.string(),
      reasonCode: a.string(),
      decisionRelationId: a.id(),
      shareable: a.boolean(),
      sectionId: a.id(),
    })
    .returns(a.ref("ReferenceCurationActionResult"))
    .authorization((allow) => [
      allow.authenticated("identityPool"),
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  // A star rating the person gave, relayed by an agent under a delegation they approved. Same agent routes as recordDelegatedCuration.
  recordDelegatedStars: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      stars: a.integer(),
      delegationId: a.id().required(),
      delegationToken: a.string().required(),
      agentLabel: a.string().required(),
      onBehalfOf: a.string().required(),
      instruction: a.string().required(),
    })
    .returns(a.ref("ReferenceStarsActionResult"))
    .authorization((allow) => [
      allow.authenticated("identityPool"),
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  setReferenceSection: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      sectionId: a.id(),
      agentLabel: a.string(),
    })
    .returns(a.ref("ReferenceSectionActionResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  setReferenceStars: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      stars: a.integer(),
      actorSub: a.string(),
      actorLabel: a.string(),
      agentLabel: a.string(),
    })
    .returns(a.ref("ReferenceStarsActionResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  setItemStars: a
    .mutation()
    .arguments({
      itemId: a.id().required(),
      stars: a.integer(),
      actorSub: a.string(),
      actorLabel: a.string(),
      agentLabel: a.string(),
    })
    .returns(a.ref("ItemStarsActionResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  setReferenceQualityRating: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      rating: a.integer().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("ReferenceQualityActionResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ])
    .handler(functionHandler("categoryAction", categoryAction)),

  createCategorySetDraft: a
    .mutation()
    .arguments({
      sourceCategorySetId: a.id().required(),
      displayName: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("CategorySetDraftActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  promoteCategorySetDraft: a
    .mutation()
    .arguments({
      categorySetId: a.id().required(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("CategorySetDraftActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  discardCategorySetDraft: a
    .mutation()
    .arguments({
      categorySetId: a.id().required(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("CategorySetDraftActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  createDraftCategory: a
    .mutation()
    .arguments({
      categorySetId: a.id().required(),
      parentCategoryKey: a.string(),
      displayName: a.string().required(),
      shortTitle: a.string(),
      subtitle: a.string(),
      description: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("SteeringActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  updateDraftCategory: a
    .mutation()
    .arguments({
      categoryId: a.id().required(),
      displayName: a.string(),
      shortTitle: a.string(),
      subtitle: a.string(),
      description: a.string(),
      parentCategoryKey: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("SteeringActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  archiveDraftCategory: a
    .mutation()
    .arguments({
      categoryId: a.id().required(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("SteeringActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  reviewReferenceTopicLabel: a
    .mutation()
    .arguments({
      referenceId: a.id().required(),
      categoryId: a.id().required(),
      action: a.string().required(),
      sourceRelationId: a.id(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("TopicLabelActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  NewsroomSummary: a.customType({
    generatedAt: a.datetime().required(),
    staleAt: a.datetime(),
    source: a.string(),
    latestImportRun: a.json(),
    counts: a.json().required(),
    facets: a.json(),
    assignmentStatusCounts: a.json().required(),
    assignmentTypeCounts: a.json().required(),
    referenceStatusCounts: a.json().required(),
    messageKindCounts: a.json().required(),
    messageDomainCounts: a.json().required(),
  }),

  getNewsroomSummary: a
    .query()
    .returns(a.ref("NewsroomSummary"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("newsroomSummary", newsroomSummary)),

  deriveMarkus: a
    .query()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  intakePendingReferences: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  intakeEmailSubmissionReferences: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  correctReferenceCapture: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  saveItemDraft: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  publishItem: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  moveStoryStage: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  setStoryStep: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  addStoryAgentNote: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  createStoryFromReference: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  MessageHashtagLinks: a.customType({
    ok: a.boolean().required(),
    linkedNodeKeys: a.string().array().required(),
    unmatchedHashtags: a.string().array().required(),
  }),

  linkMessageHashtags: a
    .mutation()
    .arguments({ messageId: a.id().required() })
    .returns(a.ref("MessageHashtagLinks"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  ReferenceLinkResult: a.customType({
    ok: a.boolean().required(),
    relationId: a.string().required(),
    relationState: a.string().required(),
    outcome: a.string(),
    decision: a.string(),
  }),

  createReferenceLink: a
    .mutation()
    .arguments({
      subjectLineageId: a.id().required(),
      objectKind: a.string().required(),
      objectLineageId: a.id().required(),
      predicate: a.string().required(),
      note: a.string(),
      newConceptName: a.string(),
    })
    .returns(a.ref("ReferenceLinkResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  DescribeConceptResult: a.customType({
    ok: a.boolean().required(),
    lineageId: a.string().required(),
    description: a.string(),
  }),

  describeConcept: a
    .mutation()
    .arguments({ lineageId: a.id().required(), description: a.string() })
    .returns(a.ref("DescribeConceptResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  CreateConceptResult: a.customType({
    ok: a.boolean().required(),
    lineageId: a.string().required(),
    nodeKey: a.string(),
    displayName: a.string(),
    nodeKind: a.string(),
  }),

  createEditorConcept: a
    .mutation()
    .arguments({ name: a.string().required(), displayName: a.string() })
    .returns(a.ref("CreateConceptResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  createConceptLink: a
    .mutation()
    .arguments({
      subjectLineageId: a.id().required(),
      objectLineageId: a.id().required(),
      note: a.string().required(),
    })
    .returns(a.ref("ReferenceLinkResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  KnowledgeReviewResult: a.customType({
    ok: a.boolean().required(),
    applied: a.integer().required(),
    origin: a.string().required(),
  }),

  applyKnowledgeReview: a
    .mutation()
    .arguments({ patches: a.json().required() })
    .returns(a.ref("KnowledgeReviewResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  decideReferenceLink: a
    .mutation()
    .arguments({
      relationId: a.id().required(),
      decision: a.string().required(),
      reasonCode: a.string(),
      note: a.string(),
    })
    .returns(a.ref("ReferenceLinkResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  StoryReferenceRoleResult: a.customType({
    ok: a.boolean().required(),
    relationId: a.string().required(),
    role: a.string().required(),
    previousRole: a.string(),
    citationKey: a.string(),
  }),

  /** An editor changes a Story source's role (consulted, cited, based_on). SemanticRelation stays append-only for the groups; this route changes only that one kind of row (story-reference-role.ts). */
  setStoryReferenceRole: a
    .mutation()
    .arguments({
      relationId: a.id().required(),
      role: a.string().required(),
      citationKey: a.string(),
      note: a.string(),
    })
    .returns(a.ref("StoryReferenceRoleResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("categoryAction", categoryAction)),

  suggestReferenceLinks: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  unpublishItem: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  requestStagingBuild: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  refreshSitePages: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(contentWriteGroups)])
    .handler(functionHandler("contentActions", contentActions)),

  knowledgeQuery: a
    .query()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("knowledgeQuery", knowledgeQuery)),

  // The References page search box: words and meaning together over every Reference, rated or not (docs/reference-search.md). Same Lambda as knowledgeQuery.
  searchReferences: a
    .query()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("knowledgeQuery", knowledgeQuery)),

  updateNewsroomSummary: a
    .mutation()
    .arguments({
      delta: a.json().required(),
      actorLabel: a.string(),
      reason: a.string(),
    })
    .returns(a.ref("NewsroomSummary"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("newsroomSummary", newsroomSummary)),

  ModelAttachmentUploadSlot: a.customType({
    ok: a.boolean().required(),
    uploadId: a.string().required(),
    attachmentId: a.id().required(),
    ownerKind: a.string().required(),
    ownerId: a.id().required(),
    role: a.string().required(),
    sortKey: a.string().required(),
    method: a.string().required(),
    uploadUrl: a.string().required(),
    storagePath: a.string().required(),
    mediaType: a.string().required(),
    byteSize: a.integer().required(),
    sha256: a.string(),
    expiresAt: a.datetime().required(),
    requiredHeaders: a.json(),
  }),

  ModelAttachmentDownloadSlot: a.customType({
    ok: a.boolean().required(),
    attachmentId: a.id().required(),
    method: a.string().required(),
    downloadUrl: a.string().required(),
    storagePath: a.string().required(),
    mediaType: a.string().required(),
    byteSize: a.integer().required(),
    sha256: a.string(),
    expiresAt: a.datetime().required(),
    requiredHeaders: a.json(),
  }),

  ModelAttachmentUploadAbortResult: a.customType({
    ok: a.boolean().required(),
    uploadId: a.string().required(),
    attachmentId: a.id().required(),
    storagePath: a.string().required(),
    status: a.string().required(),
  }),

  createModelAttachmentUpload: a
    .mutation()
    .arguments({
      ownerKind: a.string().required(),
      ownerId: a.id().required(),
      ownerLineageId: a.id(),
      ownerVersionNumber: a.integer(),
      ownerVersionKey: a.string(),
      role: a.string().required(),
      sortKey: a.string(),
      filename: a.string().required(),
      mediaType: a.string().required(),
      byteSize: a.integer().required(),
      sha256: a.string(),
      importRunId: a.id(),
      status: a.string(),
    })
    .returns(a.ref("ModelAttachmentUploadSlot"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("modelAttachmentUpload", modelAttachmentUpload)),

  completeModelAttachmentUpload: a
    .mutation()
    .arguments({
      uploadId: a.string().required(),
      ownerKind: a.string().required(),
      ownerId: a.id().required(),
      ownerLineageId: a.id(),
      ownerVersionNumber: a.integer(),
      ownerVersionKey: a.string(),
      role: a.string().required(),
      sortKey: a.string(),
      filename: a.string().required(),
      mediaType: a.string().required(),
      byteSize: a.integer().required(),
      sha256: a.string(),
      importRunId: a.id(),
      status: a.string(),
    })
    .returns(a.ref("ModelAttachment"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("modelAttachmentUpload", modelAttachmentUpload)),

  abortModelAttachmentUpload: a
    .mutation()
    .arguments({
      uploadId: a.string().required(),
      ownerKind: a.string().required(),
      ownerId: a.id().required(),
      ownerLineageId: a.id(),
      ownerVersionNumber: a.integer(),
      ownerVersionKey: a.string(),
      role: a.string().required(),
      sortKey: a.string(),
      filename: a.string().required(),
      mediaType: a.string().required(),
      byteSize: a.integer().required(),
      sha256: a.string(),
      importRunId: a.id(),
      status: a.string(),
    })
    .returns(a.ref("ModelAttachmentUploadAbortResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("modelAttachmentUpload", modelAttachmentUpload)),

  createModelAttachmentDownload: a
    .mutation()
    .arguments({
      attachmentId: a.id().required(),
    })
    .returns(a.ref("ModelAttachmentDownloadSlot"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("modelAttachmentUpload", modelAttachmentUpload)),

  AssignmentActionResult: a.customType({
    ok: a.boolean().required(),
    assignmentId: a.id(),
    eventId: a.id(),
    status: a.string(),
    action: a.string().required(),
    assigneeKey: a.string(),
    claimExpiresAt: a.datetime(),
  }),

  AssignmentTargetSummary: a.customType({
    kind: a.string().required(),
    id: a.id().required(),
    lineageId: a.id().required(),
    label: a.string(),
    detail: a.string(),
  }),

  AssignmentSummary: a.customType({
    id: a.id().required(),
    assignmentTypeKey: a.string().required(),
    queueKey: a.string().required(),
    queueStatusKey: a.string().required(),
    status: a.string().required(),
    priority: a.integer(),
    title: a.string().required(),
    summary: a.string(),
    assigneeType: a.string(),
    assigneeId: a.string(),
    assigneeKey: a.string(),
    claimedAt: a.datetime(),
    claimExpiresAt: a.datetime(),
    completedAt: a.datetime(),
    canceledAt: a.datetime(),
    corpusId: a.id(),
    categorySetId: a.id(),
    classifierId: a.string(),
    sectionId: a.id(),
    sectionKey: a.string(),
    sectionType: a.string(),
    sectionStatusKey: a.string(),
    sectionQueueStatusKey: a.string(),
    primaryFocusCategoryKey: a.string(),
    topicScopeCategoryKeys: a.string().array(),
    sourceSnapshotId: a.string(),
    importRunId: a.id(),
    createdBy: a.string(),
    createdAt: a.datetime().required(),
    updatedAt: a.datetime().required(),
  }),

  AssignmentEventSummary: a.customType({
    id: a.id().required(),
    assignmentId: a.id().required(),
    assignmentTypeKey: a.string().required(),
    queueKey: a.string().required(),
    eventType: a.string().required(),
    fromStatus: a.string(),
    toStatus: a.string(),
    actorSub: a.string(),
    actorLabel: a.string(),
    note: a.string(),
    createdAt: a.datetime().required(),
  }),

  AssignmentDoctrineSummary: a.customType({
    scope: a.string().required(),
    kind: a.string().required(),
    label: a.string().required(),
    slug: a.string().required(),
    body: a.string().array().required(),
    categoryKey: a.string(),
    categoryLineageId: a.id(),
  }),

  AssignmentContext: a.customType({
    editorialContext: a.json().required(),
    assignment: a.ref("AssignmentSummary"),
    doctrine: a.ref("AssignmentDoctrineSummary").array().required(),
    targets: a.ref("AssignmentTargetSummary").array().required(),
    events: a.ref("AssignmentEventSummary").array().required(),
  }),

  listAssignmentsForObject: a
    .query()
    .arguments({
      objectKind: a.string().required(),
      objectLineageId: a.id().required(),
      status: a.string(),
      limit: a.integer(),
    })
    .returns(a.ref("AssignmentContext").array().required())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  listAssignmentQueue: a
    .query()
    .arguments({
      queueKey: a.string().required(),
      status: a.string(),
      limit: a.integer(),
    })
    .returns(a.ref("AssignmentContext").array().required())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  getEditorialContext: a
    .query()
    .arguments({
      publicationKey: a.string().required(),
      sectionId: a.id(),
      storyLineageId: a.id(),
      assignmentId: a.id(),
      maxCharacters: a.integer(),
      optionalPublicationDoctrine: a.boolean(),
    })
    .returns(a.json().required())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  getAssignmentContext: a
    .query()
    .arguments({
      assignmentId: a.id().required(),
    })
    .returns(a.ref("AssignmentContext"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  claimAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      assigneeKey: a.string(),
      assigneeType: a.string(),
      assigneeId: a.string(),
      claimExpiresAt: a.datetime(),
      claimTtlSeconds: a.integer(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  releaseAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  completeAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  cancelAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  reopenAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  retryImmediateAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("assignmentAction", assignmentAction)),

  listNewsroomProcedureDefinitions: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("procedureAction", procedureAction)),

  getNewsroomProcedureDefinition: a
    .query()
    .arguments({
      id: a.id(),
      procedureKey: a.string(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("procedureAction", procedureAction)),

  saveNewsroomProcedureDefinition: a
    .mutation()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("procedureAction", procedureAction)),

  saveNewsroomProcedureVersionDraft: a
    .mutation()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("procedureAction", procedureAction)),

  publishNewsroomProcedureVersion: a
    .mutation()
    .arguments({
      versionId: a.id().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(functionHandler("procedureAction", procedureAction)),

  startNewsroomProcedureRun: a
    .mutation()
    .arguments({
      procedureId: a.id(),
      procedureKey: a.string(),
      procedureVersionId: a.id(),
      title: a.string(),
      summary: a.string(),
      input: a.json(),
      actorLabel: a.string(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("procedureAction", procedureAction)),

  getNewsroomProcedureRun: a
    .query()
    .arguments({
      id: a.id().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("procedureAction", procedureAction)),

  listNewsroomProcedureRunsByProcedure: a
    .query()
    .arguments({
      procedureId: a.id().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(functionHandler("procedureAction", procedureAction)),

  Assignment: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      assignmentTypeKey: a.string().required(),
      queueKey: a.string().required(),
      queueStatusKey: a.string().required(),
      status: a.string().required(),
      priority: a.integer(),
      title: a.string().required(),
      summary: a.string(),
      assigneeType: a.string(),
      assigneeId: a.string(),
      assigneeKey: a.string(),
      claimedAt: a.datetime(),
      claimExpiresAt: a.datetime(),
      completedAt: a.datetime(),
      canceledAt: a.datetime(),
      corpusId: a.id(),
      categorySetId: a.id(),
      classifierId: a.string(),
      sectionId: a.id(),
      sectionKey: a.string(),
      sectionType: a.string(),
      sectionStatusKey: a.string(),
      sectionQueueStatusKey: a.string(),
      primaryFocusCategoryKey: a.string(),
      topicScopeCategoryKeys: a.string().array(),
      sourceSnapshotId: a.string(),
      importRunId: a.id(),
      createdBy: a.string(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
      newsroomFeedKey: a.string(),
      itemLineageId: a.id(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["createdAt"]).queryField("listAssignmentsByNewsroomFeedAndCreatedAt"),
      index("itemLineageId").sortKeys(["createdAt"]).queryField("listAssignmentsByItemLineageAndCreatedAt"),
      index("queueStatusKey").sortKeys(["priority", "createdAt"]).queryField("listAssignmentsByQueueStatusAndPriority"),
      index("assignmentTypeKey").sortKeys(["status", "createdAt"]).queryField("listAssignmentsByTypeStatusAndCreatedAt"),
      index("status").sortKeys(["updatedAt"]).queryField("listAssignmentsByStatusAndUpdatedAt"),
      index("assigneeKey").sortKeys(["status", "updatedAt"]).queryField("listAssignmentsByAssigneeStatusAndUpdatedAt"),
      index("importRunId").sortKeys(["createdAt"]).queryField("listAssignmentsByImportRunAndCreatedAt"),
      index("sectionStatusKey").sortKeys(["priority", "createdAt"]).queryField("listAssignmentsBySectionStatusAndPriority"),
      index("sectionKey").sortKeys(["createdAt"]).queryField("listAssignmentsBySectionAndCreatedAt"),
      index("sectionQueueStatusKey").sortKeys(["priority", "createdAt"]).queryField("listAssignmentsBySectionQueueStatusAndPriority"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(categoryAppendOnlyOperations),
    ]),

  AssignmentEvent: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      assignmentId: a.id().required(),
      assignmentTypeKey: a.string().required(),
      queueKey: a.string().required(),
      eventType: a.string().required(),
      fromStatus: a.string(),
      toStatus: a.string(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
      createdAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("assignmentId").sortKeys(["createdAt"]).queryField("listAssignmentEventsByAssignmentAndCreatedAt"),
      index("eventType").sortKeys(["createdAt"]).queryField("listAssignmentEventsByTypeAndCreatedAt"),
      index("queueKey").sortKeys(["createdAt"]).queryField("listAssignmentEventsByQueueAndCreatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(categoryAppendOnlyOperations),
    ]),

  ProcedureDefinition: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      procedureKey: a.string().required(),
      title: a.string().required(),
      category: a.string().required(),
      description: a.string(),
      enabled: a.boolean().required(),
      enabledStatus: a.string().required(),
      currentVersionId: a.id(),
      createdBy: a.string(),
      createdAt: a.datetime().required(),
      updatedBy: a.string(),
      updatedAt: a.datetime().required(),
      newsroomFeedKey: a.string(),
    })
    .secondaryIndexes((index) => [
      index("procedureKey").sortKeys(["updatedAt"]).queryField("listProcedureDefinitionsByKeyAndUpdatedAt"),
      index("enabledStatus").sortKeys(["updatedAt"]).queryField("listProcedureDefinitionsByEnabledAndUpdatedAt"),
      index("newsroomFeedKey").sortKeys(["updatedAt"]).queryField("listProcedureDefinitionsByFeedAndUpdatedAt"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
    ]),

  ProcedureVersion: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      procedureId: a.id().required(),
      procedureKey: a.string().required(),
      versionNumber: a.integer().required(),
      status: a.string().required(),
      isCurrent: a.boolean().required(),
      label: a.string(),
      tactusSource: a.string().required(),
      parameterSchema: a.json().required(),
      defaults: a.json(),
      changelog: a.string(),
      createdBy: a.string(),
      createdAt: a.datetime().required(),
      updatedBy: a.string(),
      updatedAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("procedureId").sortKeys(["versionNumber"]).queryField("listProcedureVersionsByProcedureAndVersion"),
      index("procedureId").sortKeys(["createdAt"]).queryField("listProcedureVersionsByProcedureAndCreatedAt"),
      index("status").sortKeys(["updatedAt"]).queryField("listProcedureVersionsByStatusAndUpdatedAt"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
    ]),

  ProcedureRun: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      procedureId: a.id().required(),
      procedureKey: a.string().required(),
      procedureVersionId: a.id().required(),
      procedureVersionNumber: a.integer(),
      assignmentId: a.id(),
      runStatus: a.string().required(),
      requestedBy: a.string(),
      requestedAt: a.datetime().required(),
      startedAt: a.datetime(),
      finishedAt: a.datetime(),
      input: a.json(),
      normalizedInput: a.json(),
      resultSummary: a.string(),
      errorSummary: a.string(),
      output: a.json(),
      error: a.json(),
      attempt: a.integer(),
      newsroomFeedKey: a.string(),
      usage: a.json(),
      costUsd: a.float(),
    })
    .secondaryIndexes((index) => [
      index("procedureId").sortKeys(["requestedAt"]).queryField("listProcedureRunsByProcedureAndRequestedAt"),
      index("assignmentId").sortKeys(["requestedAt"]).queryField("listProcedureRunsByAssignmentAndRequestedAt"),
      index("runStatus").sortKeys(["requestedAt"]).queryField("listProcedureRunsByStatusAndRequestedAt"),
      index("newsroomFeedKey").sortKeys(["requestedAt"]).queryField("listProcedureRunsByFeedAndRequestedAt"),
    ])
    .authorization((allow) => [
      allow.group("editor").to(["read"]),
      allow.group(adminGroup).to(authoringOperations),
    ]),

  /** A named "when X happens, run procedure Y" (PPY-9ff95b). Step 1 mirrors the monitoring router's procedureTriggers and starts nothing itself. */
  Automation: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      title: a.string().required(),
      description: a.string(),
      enabled: a.boolean().required(),
      trigger: a.json().required(),
      procedureKey: a.string().required(),
      inputTemplate: a.json(),
      limits: a.json(),
      createdBy: a.string(),
      createdAt: a.datetime().required(),
      updatedBy: a.string(),
      updatedAt: a.datetime().required(),
    })
    .authorization((allow) => [
      allow.group("editor").to(["read", "create", "update"]),
      allow.group(adminGroup).to(authoringOperations),
    ]),

  /** A human review point raised by a step on any item (PPY-ab6a50). Review is not a story state. */
  ReviewRequest: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      subject: a.json().required(),
      mode: a.string().required(),
      reason: a.string().required(),
      ask: a.string(),
      raisedBy: a.string().required(),
      raisedAt: a.datetime().required(),
      deadline: a.datetime(),
      state: a.string().required(),
      answer: a.json(),
      links: a.json(),
      history: a.json(),
      appliedIn: a.json(),
      updatedAt: a.datetime().required(),
    })
    .authorization((allow) => [
      allow.group("editor").to(["read", "create", "update"]),
      allow.group(adminGroup).to(authoringOperations),
    ]),

  /** One user's read mark on one review request; id is "<userKey>#<requestId>". */
  ReviewReadMark: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      requestId: a.string().required(),
      userKey: a.string().required(),
      readAt: a.datetime().required(),
    })
    .authorization((allow) => [
      allow.groups(["editor", adminGroup]).to(["read", "create", "update"]),
    ]),

  /** One way a Story could connect to what the newsroom knows: its own point, wording and connections. Not a version: variations sit side by side and an editor chooses (docs/story-variations.md). */
  StoryVariation: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      storyLineageId: a.id().required(),
      variationNumber: a.integer().required(),
      status: a.string().required(),
      point: a.string().required(),
      headline: a.string().required(),
      deck: a.string(),
      bodyMarkus: a.string(),
      section: a.string(),
      connections: a.json(),
      origin: a.string().required(),
      basedOnVariationIds: a.id().array(),
      requestMessageId: a.id(),
      pointCheck: a.json(),
      runId: a.string(),
      model: a.string(),
      createdBy: a.string(),
      decidedBySub: a.string(),
      decidedByLabel: a.string(),
      decidedAt: a.datetime(),
      decisionReason: a.string(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("storyLineageId").sortKeys(["variationNumber"]).queryField("listStoryVariationsByStoryAndNumber"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups).to(["read", "create", "update"]),
    ]),

  /** Who is told about review requests: scope default, mode or automation. Changed by data, not code. */
  ReviewRecipientRule: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      scope: a.string().required(),
      key: a.string(),
      roles: a.string().array(),
      emails: a.string().array(),
      updatedBy: a.string(),
      updatedAt: a.datetime().required(),
    })
    .authorization((allow) => [
      allow.group("editor").to(["read"]),
      allow.group(adminGroup).to(authoringOperations),
    ]),

  NewsroomSection: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      title: a.string().required(),
      type: a.string().required(),
      editorialMission: a.string().required(),
      editorialPolicy: a.string().required(),
      enabled: a.boolean().required(),
      enabledStatus: a.string().required(),
      sortOrder: a.integer().required(),
      shortTitle: a.string().required(),
      defaultArticleTypes: a.string().array(),
      defaultPageBudget: a.integer(),
      assignmentGuidance: a.string(),
      killCriteria: a.string(),
      coreConcepts: a.json(),
      visualGuidance: a.string(),
      visualStyle: a.json(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("sortOrder").sortKeys(["id"]).queryField("listNewsroomSectionsBySortOrder"),
      index("tenantId").sortKeys(["sortOrder"]).queryField("listNewsroomSectionsByTenantAndSortOrder"),
      index("type").sortKeys(["sortOrder"]).queryField("listNewsroomSectionsByTypeAndSortOrder"),
      index("enabledStatus").sortKeys(["sortOrder"]).queryField("listNewsroomSectionsByEnabledStatusAndSortOrder"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  KnowledgeCorpus: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      name: a.string().required(),
      role: a.string().required(),
      itemCount: a.integer(),
      generatedAt: a.datetime(),
      latestImportRunId: a.id(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("role").sortKeys(["name"]).queryField("listKnowledgeCorporaByRoleAndName"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  KnowledgeImportRun: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      corpusId: a.id().required(),
      importKind: a.string().required(),
      corpusImportKindKey: a.string(),
      classifierId: a.string(),
      sourceSnapshotId: a.string(),
      status: a.string().required(),
      generatedAt: a.datetime(),
      importedAt: a.datetime().required(),
      itemCount: a.integer(),
      categoryCount: a.integer(),
      proposalCount: a.integer(),
      artifactCount: a.integer(),
      referenceCount: a.integer(),
      relationCount: a.integer(),
      warningCount: a.integer(),
    })
    .secondaryIndexes((index) => [
      index("corpusId").sortKeys(["importedAt"]).queryField("listKnowledgeImportRunsByCorpusAndImportedAt"),
      index("importKind").sortKeys(["importedAt"]).queryField("listKnowledgeImportRunsByKindAndImportedAt"),
      index("corpusImportKindKey").sortKeys(["importedAt"]).queryField("listKnowledgeImportRunsByCorpusKindAndImportedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  KnowledgeRawPayload: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      ownerType: a.string().required(),
      ownerId: a.id().required(),
      payloadKind: a.string().required(),
      importRunId: a.id(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("ownerId").sortKeys(["payloadKind"]).queryField("listKnowledgeRawPayloadsByOwnerAndKind"),
      index("importRunId").sortKeys(["ownerType"]).queryField("listKnowledgeRawPayloadsByImportRunAndOwner"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  // The curation delegations (an editor's permission for an agent to relay their decisions). Only the Lambdas granted by the schema's
  // `allow.resource` rules can write it; the admin group may read it. No session can create or change a record, so none can forge an approved
  // delegation (PPY-05f412). Never add a write rule here, and never move these records to a model editors can write.
  CurationDelegationRecord: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      grantorSub: a.string().required(),
      recordJson: a.string().required(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("grantorSub").sortKeys(["createdAt"]).queryField("listCurationDelegationRecordsByGrantor"),
    ])
    .authorization((allow) => [allow.groups([adminGroup]).to(["read"])]),

  KnowledgeArtifact: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      corpusId: a.id().required(),
      artifactKind: a.string().required(),
      artifactId: a.string().required(),
      snapshotId: a.string(),
      displayName: a.string(),
      createdAt: a.datetime(),
      importRunId: a.id(),
    })
    .secondaryIndexes((index) => [
      index("corpusId").sortKeys(["artifactKind"]).queryField("listKnowledgeArtifactsByCorpusAndKind"),
      index("artifactKind").sortKeys(["createdAt"]).queryField("listKnowledgeArtifactsByKindAndCreatedAt"),
      index("importRunId").sortKeys(["artifactKind"]).queryField("listKnowledgeArtifactsByImportRunAndKind"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  CategorySet: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      lineageId: a.id().required(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      corpusId: a.id().required(),
      classifierId: a.string().required(),
      displayName: a.string().required(),
      description: a.string(),
      status: a.string().required(),
      generatedAt: a.datetime(),
      categoryCount: a.integer(),
      importRunId: a.id(),
    })
    .secondaryIndexes((index) => [
      index("lineageId").sortKeys(["versionNumber"]).queryField("listCategorySetsByLineageAndVersion"),
      index("corpusId").sortKeys(["classifierId"]).queryField("listCategorySetsByCorpusAndClassifier"),
      index("status").sortKeys(["displayName"]).queryField("listCategorySetsByStatusAndName"),
      index("versionState").sortKeys(["generatedAt"]).queryField("listCategorySetsByVersionStateAndGeneratedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  Category: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      lineageId: a.id().required(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      categorySetId: a.id().required(),
      corpusId: a.id().required(),
      categoryKey: a.string().required(),
      parentCategoryId: a.id(),
      parentCategoryKey: a.string(),
      displayName: a.string().required(),
      shortTitle: a.string(),
      subtitle: a.string(),
      description: a.string(),
      aliases: a.string().array(),
      status: a.string().required(),
      seedItemIds: a.string().array(),
      holdoutItemIds: a.string().array(),
      rank: a.integer(),
      depth: a.integer(),
      isPinned: a.boolean(),
      importRunId: a.id(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("lineageId").sortKeys(["versionNumber"]).queryField("listCategoriesByLineageAndVersion"),
      index("categorySetId").sortKeys(["categoryKey"]).queryField("listCategoriesBySetAndKey"),
      index("parentCategoryId").sortKeys(["rank"]).queryField("listCategoriesByParentAndRank"),
      index("parentCategoryKey").sortKeys(["rank"]).queryField("listCategoriesByParentKeyAndRank"),
      index("corpusId").sortKeys(["displayName"]).queryField("listCategoriesByCorpusAndName"),
      index("status").sortKeys(["displayName"]).queryField("listCategoriesByStatusAndName"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  CategoryKeyword: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      categorySetId: a.id().required(),
      corpusId: a.id().required(),
      categoryKey: a.string().required(),
      categoryLineageId: a.id(),
      categoryId: a.id(),
      keyword: a.string().required(),
      normalizedKeyword: a.string().required(),
      weight: a.float(),
      rank: a.integer(),
      source: a.string().required(),
      sourceTopicId: a.string(),
      importRunId: a.id(),
      metadata: a.json(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("categorySetId").sortKeys(["categoryKey", "rank"]).queryField("listCategoryKeywordsBySetKeyAndRank"),
      index("categoryKey").sortKeys(["rank"]).queryField("listCategoryKeywordsByCategoryKeyAndRank"),
      index("normalizedKeyword").sortKeys(["categorySetId"]).queryField("listCategoryKeywordsByNormalizedKeywordAndSet"),
      index("importRunId").sortKeys(["rank"]).queryField("listCategoryKeywordsByImportRunAndRank"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  LexicalSteeringRule: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      ruleKind: a.string().required(),
      term: a.string().required(),
      normalizedTerm: a.string().required(),
      scope: a.string().required(),
      status: a.string().required(),
      corpusId: a.id(),
      classifierId: a.string(),
      categorySetId: a.id(),
      categoryKey: a.string(),
      note: a.string(),
      source: a.string(),
      createdBy: a.string(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("status").sortKeys(["normalizedTerm"]).queryField("listLexicalSteeringRulesByStatusAndTerm"),
      index("scope").sortKeys(["normalizedTerm"]).queryField("listLexicalSteeringRulesByScopeAndTerm"),
      index("categorySetId").sortKeys(["normalizedTerm"]).queryField("listLexicalSteeringRulesBySetAndTerm"),
      index("corpusId").sortKeys(["normalizedTerm"]).queryField("listLexicalSteeringRulesByCorpusAndTerm"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  SteeringProposal: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      categorySetId: a.id(),
      corpusId: a.id().required(),
      importRunId: a.id(),
      proposalKind: a.string().required(),
      steeringDomain: a.string().required(),
      status: a.string().required(),
      title: a.string().required(),
      summary: a.string(),
      categoryKey: a.string(),
      targetCategoryKey: a.string(),
      graphEntityId: a.string(),
      relationshipType: a.string(),
      displayName: a.string(),
      shortTitle: a.string(),
      subtitle: a.string(),
      description: a.string(),
      evidenceItemIds: a.string().array(),
      suggestedSeedItemIds: a.string().array(),
      suggestedHoldoutItemIds: a.string().array(),
      sourceSnapshotId: a.string(),
      proposedAt: a.datetime(),
      reviewedAt: a.datetime(),
      reviewedBy: a.string(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("status").sortKeys(["proposedAt"]).queryField("listSteeringProposalsByStatusAndProposedAt"),
      index("categorySetId").sortKeys(["status"]).queryField("listSteeringProposalsBySetAndStatus"),
      index("corpusId").sortKeys(["proposalKind"]).queryField("listSteeringProposalsByCorpusAndKind"),
      index("steeringDomain").sortKeys(["status"]).queryField("listSteeringProposalsByDomainAndStatus"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  SteeringDecision: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      proposalId: a.id().required(),
      categorySetId: a.id(),
      action: a.string().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
      selectedCategoryKey: a.string(),
      createdAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("proposalId").sortKeys(["createdAt"]).queryField("listSteeringDecisionsByProposalAndCreatedAt"),
      index("categorySetId").sortKeys(["createdAt"]).queryField("listSteeringDecisionsBySetAndCreatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(categoryAppendOnlyOperations),
    ]),

  Reference: realtimeModel({
      id: a.id().required(),
      tenantId: a.string(),
      lineageId: a.id().required(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      corpusId: a.id().required(),
      externalItemId: a.string().required(),
      title: a.string(),
      authors: a.string().array(),
      sourceUri: a.string(),
      storagePath: a.string(),
      mediaType: a.string(),
      byteSize: a.integer(),
      sha256: a.string(),
      sourcePublishedAt: a.string(),
      sourceUpdatedAt: a.string(),
      retrievedAt: a.string(),
      inboundCitationCount: a.integer(),
      outboundCitationCount: a.integer(),
      importRunId: a.id(),
      importedAt: a.datetime(),
      createdAt: a.datetime(),
      curationStatus: a.string(),
      curationStatusKey: a.string(),
      curationStatusUpdatedAt: a.datetime(),
      curationStatusUpdatedBy: a.string(),
      curationStatusReason: a.string(),
      curationReasonCode: a.string(),
      curationActorKind: a.string(),
      curationSectionId: a.string(),
      curationSectionUpdatedAt: a.datetime(),   // when and by whom the section was last set on its own (`setReferenceSection`); the vote's own fields do not move
      curationSectionUpdatedBy: a.string(),
      curationShareable: a.boolean(),
      curationDelegation: a.json(),
      curationDecisionRelationId: a.string(),
      // An editor's optional 1-5 star interest in this Reference: separate from the vote and from relevance (docs/reference-curation-pipeline.md). Latest rating wins; null when unrated.
      starRating: a.integer(),
      starRatedAt: a.datetime(),
      starRatedBy: a.string(),
      newsroomFeedKey: a.string(),
      reviewedFeedKey: a.string(),
      discoveredByMonitorId: a.string(),
      discoveryDetails: a.json(),
      discoveryRule: a.json(),
      // The References page reads the feed through two indexes (docs/reference-feed-indexes.md). `feedStateKey` is
      // "<corpusId>#unrated" or "<corpusId>#rated" for a current, not archived Reference (null otherwise: it is in no feed).
      // `predictionSortKey` orders Predictions, `feedArrivalAt` orders Newest. The prediction is the Cyclotron's ORIGINAL
      // P(accept), written once, and never rewritten by a vote.
      feedStateKey: a.string(),
      feedArrivalAt: a.datetime(),
      predictedAcceptProbability: a.float(),
      predictionDecidedAt: a.datetime(),
      predictionSortKey: a.string(),
      // "<corpusId>#stars#<n>" for a current, not archived Reference an editor has starred (null otherwise): one partition per star level,
      // read newest first by `feedArrivalAt` for the Quality sort and the minimum-stars filter.
      starFeedKey: a.string(),
      // How much of this Reference's content the newsroom holds: "full", "thin", "none" or "running". Empty means "none". A stored copy of the
      // capture rule in lib/reference-capture.ts (docs/reference-curation-pipeline.md), read by the Captured filter and the home page's list
      // of accepted References that still need a person to capture them. No index.
      captureState: a.string(),
      // What kind of thing the address is, by rule and only where certain (src/papyrus_content/reference_medium.py): "video" or empty. Separate from
      // the evidence level and the voice (PPY-f8ff49). `evidenceLevel` is "primary", "secondary", "aggregation" or "unknown"; the medium rule writes only
      // "aggregation" (a playlist address) and never replaces a value already there, and the decision model writes the same field later.
      // `playlistUrl` is the playlist a video address also names (a watch address with a list parameter), kept for following it later.
      medium: a.string(),
      evidenceLevel: a.string(),
      playlistUrl: a.string(),
      // "<corpusId>#<medium>#<pending|accepted|rejected>" for a current, not archived Reference that has a medium (null otherwise): the partition a
      // public videos page reads as "<corpusId>#video#accepted", newest first by `feedArrivalAt`. Sparse. Same corpus-per-site isolation as feedStateKey.
      mediumFeedKey: a.string(),
      // Why no automatic attempt can capture this Reference's content: "no_transcript", "unavailable" or "unsupported_platform" (a video; recorded by
      // `papyrus references capture-transcripts` through the capture action), else empty. It stays in the To capture queue for a person.
      captureReason: a.string(),
      // "<corpusId>#<medium>#needs_content#<pending|accepted|rejected>" while a current, not archived Reference with a medium has no captured content
      // (`captureState` not "full" or "running") and no `captureReason` (null otherwise): the partition the transcript worker reads as
      // "<corpusId>#video#needs_content#accepted", newest first by `feedArrivalAt`. Sparse: removed when the content arrives.
      contentNeededKey: a.string(),
      // The video's own thumbnail, copied into the media bucket by `papyrus references capture-thumbnails`: the site path of the copy
      // ("assets/reference-thumbnails/<hash>.jpg"), or "none" when the platform has no thumbnail (recorded so it is not asked again). Else empty.
      thumbnailPath: a.string(),
      // The public blocks of a site's pages (docs/plans/public-blocks-from-indexes.md, PPY-7f1e54). `publicFeedKey` and `publicOrderKey` are the partition and
      // sort key of the index a block will read (the index is a later, separate deploy): "<corpusId>#accepted" or "<corpusId>#recommended#<UTC day of arrival>",
      // sorted "p<P to six places>#<arrival>#<id>" ("n#..." for an accepted row nobody scored). Both are null (the attributes absent) unless the row can be public:
      // accepted, or pending with a stored prediction of at least 0.5. Written in each writer that changes a vote, a prediction or a version, never on a schedule.
      // `cardImage`, `cardSummary`, `cardSiteName` and `cardPageTitle` are what a card shows besides the row's own fields, copied from the preview when it is captured (a video's
      // picture is its own thumbnail copy): the address of the picture, the description scrubbed and not clipped, the site name scrubbed, and the title the page declared
      // for link previews (a Reference titled with its own address shows it, or a readable name made from the site name and the address, never the address).
      publicFeedKey: a.string(),
      publicOrderKey: a.string(),
      cardImage: a.string(),
      cardSummary: a.string(),
      cardSiteName: a.string(),
      cardPageTitle: a.string(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["createdAt"]).queryField("listReferencesByNewsroomFeedAndCreatedAt"),
      index("newsroomFeedKey").sortKeys(["importedAt"]).queryField("listReferencesByNewsroomFeedAndImportedAt"),
      index("lineageId").sortKeys(["versionNumber"]).queryField("listReferencesByLineageAndVersion"),
      index("corpusId").sortKeys(["externalItemId"]).queryField("listReferencesByCorpusAndExternalItem"),
      index("versionState").sortKeys(["updatedAt"]).queryField("listReferencesByVersionStateAndUpdatedAt"),
      index("importRunId").sortKeys(["externalItemId"]).queryField("listReferencesByImportRunAndExternalItem"),
      index("curationStatus").sortKeys(["curationStatusUpdatedAt"]).queryField("listReferencesByCurationStatusAndUpdatedAt"),
      index("curationStatusKey").sortKeys(["curationStatusUpdatedAt"]).queryField("listReferencesByCurationStatusKeyAndUpdatedAt"),
      index("reviewedFeedKey").sortKeys(["updatedAt"]).queryField("listReferencesByReviewedFeedAndUpdatedAt"),
      index("discoveredByMonitorId").sortKeys(["createdAt"]).queryField("listReferencesByMonitorAndCreatedAt"),
      index("feedStateKey").sortKeys(["predictionSortKey"]).queryField("listReferencesByFeedStateAndPrediction"),
      index("feedStateKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByFeedStateAndArrival"),
      index("starFeedKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByStarFeedAndArrival"),
      index("mediumFeedKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByMediumFeedAndArrival"),
      index("contentNeededKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByContentNeededAndArrival"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  ReferenceAttachment: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      referenceId: a.id().required(),
      referenceLineageId: a.id().required(),
      referenceVersionNumber: a.integer(),
      referenceVersionKey: a.string().required(),
      role: a.string().required(),
      sortKey: a.string().required(),
      storagePath: a.string(),
      sourceUri: a.string(),
      filename: a.string(),
      mediaType: a.string(),
      byteSize: a.integer(),
      sha256: a.string(),
      etag: a.string(),
      importRunId: a.id(),
      importedAt: a.datetime(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("referenceVersionKey").sortKeys(["sortKey"]).queryField("listReferenceAttachmentsByReferenceVersionAndSortKey"),
      index("referenceLineageId").sortKeys(["sortKey"]).queryField("listReferenceAttachmentsByReferenceLineageAndSortKey"),
      index("storagePath").queryField("referenceAttachmentByStoragePath"),
      index("importRunId").sortKeys(["sortKey"]).queryField("listReferenceAttachmentsByImportRunAndSortKey"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  SemanticNode: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      lineageId: a.id().required(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      nodeKey: a.string().required(),
      nodeKind: a.string().required(),
      corpusId: a.id(),
      categorySetId: a.id(),
      categoryLineageId: a.id(),
      categoryKey: a.string(),
      displayName: a.string(),
      description: a.string(),
      aliases: a.string().array(),
      authorityScore: a.float(),
      authorityRank: a.integer(),
      acceptedReferenceMentionCount: a.integer(),
      distinctSourceKindCount: a.integer(),
      relationCount: a.integer(),
      // The extractor's answer whether the concept deserves a page of its own: JSON {score, answer, documents, runId}. An editor's own decision is in changeReason.
      pageAnswer: a.string(),
      status: a.string().required(),
      importRunId: a.id(),
      createdAt: a.datetime(),
      newsroomFeedKey: a.string(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["createdAt"]).queryField("listSemanticNodesByNewsroomFeedAndCreatedAt"),
      index("lineageId").sortKeys(["versionNumber"]).queryField("listSemanticNodesByLineageAndVersion"),
      index("nodeKey").sortKeys(["versionNumber"]).queryField("listSemanticNodesByNodeKeyAndVersion"),
      index("corpusId").sortKeys(["nodeKey"]).queryField("listSemanticNodesByCorpusAndNodeKey"),
      index("importRunId").sortKeys(["nodeKey"]).queryField("listSemanticNodesByImportRunAndNodeKey"),
      index("versionState").sortKeys(["updatedAt"]).queryField("listSemanticNodesByVersionStateAndUpdatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  Message: realtimeModel({
      id: a.id().required(),
      tenantId: a.string(),
      messageKind: a.string().required(),
      messageDomain: a.string().required(),
      status: a.string().required(),
      summary: a.string(),
      source: a.string(),
      importRunId: a.id(),
      authorSub: a.string(),
      authorUserProfileId: a.id(),
      authorLabel: a.string(),
      authorKind: a.string().default("staff"),
      authorReaderId: a.string(),
      editedAt: a.datetime(),
      deletedAt: a.datetime(),
      deletedBySub: a.string(),
      threadId: a.id(),
      parentMessageId: a.id(),
      sequenceNumber: a.integer(),
      role: a.string(),
      messageType: a.string(),
      content: a.string(),
      semanticLayer: a.string(),
      searchVisibility: a.string(),
      responseTarget: a.string(),
      responseStatus: a.string(),
      responseOwner: a.string(),
      responseStartedAt: a.datetime(),
      responseCompletedAt: a.datetime(),
      responseError: a.string(),
      metadata: a.json(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
      newsroomFeedKey: a.string(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["createdAt"]).queryField("listMessagesByNewsroomFeedAndCreatedAt"),
      index("status").sortKeys(["createdAt"]).queryField("listMessagesByStatusAndCreatedAt"),
      index("messageKind").sortKeys(["createdAt"]).queryField("listMessagesByKindAndCreatedAt"),
      index("messageDomain").sortKeys(["createdAt"]).queryField("listMessagesByDomainAndCreatedAt"),
      index("authorSub").sortKeys(["createdAt"]).queryField("listMessagesByAuthorSubAndCreatedAt"),
      index("authorUserProfileId").sortKeys(["createdAt"]).queryField("listMessagesByAuthorProfileAndCreatedAt"),
      index("importRunId").sortKeys(["createdAt"]).queryField("listMessagesByImportRunAndCreatedAt"),
      index("threadId").sortKeys(["sequenceNumber"]).name("messagesByThreadSequence").queryField("listMessagesByThreadAndSequence"),
      index("threadId").sortKeys(["createdAt"]).name("messagesByThreadCreatedAt").queryField("listMessagesByThreadAndCreatedAt"),
      index("responseTarget").sortKeys(["responseStatus", "createdAt"]).name("messagesByResponseTargetStatusCreatedAt").queryField("listMessagesByResponseTargetStatusAndCreatedAt"),
      index("semanticLayer").sortKeys(["createdAt"]).name("messagesBySemanticLayerCreatedAt").queryField("listMessagesBySemanticLayerAndCreatedAt"),
      index("searchVisibility").sortKeys(["createdAt"]).name("messagesBySearchVisibilityCreatedAt").queryField("listMessagesBySearchVisibilityAndCreatedAt"),
    ])
    .authorization((allow) => [
      // Messages belong to their author, and the backend stamps the author: people read Messages here and write them only through
      // postMessage, editMessage, deleteOwnMessage and moderateMessage (message-actions.ts). Functions and IAM callers write directly.
      allow.group("editor").to(["read"]),
      allow.group(adminGroup).to(["read"]),
    ]),

  MessageThread: realtimeModel({
      id: a.id().required(),
      tenantId: a.string(),
      threadKind: a.string().required(),
      status: a.string().required(),
      // The title and the creator are set when a conversation is created and read afterwards; a title changes only through
      // renameThread (its creator or an admin), and the creator never changes.
      title: a.string().required().authorization((allow) => [allow.group("editor").to(["read", "create"]), allow.group(adminGroup).to(["read", "create"])]),
      summary: a.string(),
      primaryAnchorKind: a.string(),
      primaryAnchorId: a.id(),
      primaryAnchorLineageId: a.id(),
      primaryAnchorKey: a.string(),
      createdBySub: a.string().authorization((allow) => [allow.group("editor").to(["read", "create"]), allow.group(adminGroup).to(["read", "create"])]),
      createdByUserProfileId: a.id(),
      createdByLabel: a.string(),
      messageCount: a.integer(),
      lastMessageId: a.id(),
      lastMessageAt: a.datetime(),
      contextDigest: a.string(),
      activeResponseMessageId: a.id(),
      responseLockOwner: a.string(),
      responseLockExpiresAt: a.datetime(),
      metadata: a.json(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
      newsroomFeedKey: a.string(),
      // The section the conversation is filed under, set by an editor; empty means the anchor's own section (its Reference's or Story's).
      sectionId: a.id(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["updatedAt"]).queryField("listMessageThreadsByNewsroomFeedAndUpdatedAt"),
      index("threadKind").sortKeys(["updatedAt"]).queryField("listMessageThreadsByKindAndUpdatedAt"),
      index("status").sortKeys(["updatedAt"]).queryField("listMessageThreadsByStatusAndUpdatedAt"),
      index("primaryAnchorKey").sortKeys(["updatedAt"]).name("messageThreadsByAnchorUpdatedAt").queryField("listMessageThreadsByAnchorAndUpdatedAt"),
      index("createdBySub").sortKeys(["updatedAt"]).queryField("listMessageThreadsByCreatorAndUpdatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read", "create", "update"]),
    ]),

  ModelAttachment: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      ownerKind: a.string().required(),
      ownerId: a.id().required(),
      ownerLineageId: a.id(),
      ownerVersionNumber: a.integer(),
      ownerVersionKey: a.string(),
      role: a.string().required(),
      sortKey: a.string().required(),
      storagePath: a.string().required(),
      filename: a.string(),
      mediaType: a.string().required(),
      byteSize: a.integer(),
      sha256: a.string(),
      etag: a.string(),
      importRunId: a.id(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime(),
      status: a.string().required(),
    })
    .secondaryIndexes((index) => [
      index("ownerId").sortKeys(["role", "sortKey"]).queryField("listModelAttachmentsByOwnerRoleAndSortKey"),
      index("ownerVersionKey").sortKeys(["role", "sortKey"]).queryField("listModelAttachmentsByOwnerVersionRoleAndSortKey"),
      index("storagePath").queryField("modelAttachmentByStoragePath"),
      index("importRunId").sortKeys(["ownerKind", "role"]).queryField("listModelAttachmentsByImportRunKindAndRole"),
      index("role").sortKeys(["status", "createdAt"]).queryField("listModelAttachmentsByRoleStatusAndCreatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
    ]),

  SemanticRelationType: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      key: a.string().required(),
      label: a.string().required(),
      inverseLabel: a.string(),
      description: a.string(),
      domain: a.string().required(),
      status: a.string().required(),
      allowedSubjectKinds: a.string().array(),
      allowedObjectKinds: a.string().array(),
      isDirectional: a.boolean(),
      isSymmetric: a.boolean(),
      isTransitive: a.boolean(),
      contextPackTags: a.string().array(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("key").queryField("semanticRelationTypeByKey"),
      index("domain").sortKeys(["label"]).queryField("listSemanticRelationTypesByDomainAndLabel"),
      index("status").sortKeys(["label"]).queryField("listSemanticRelationTypesByStatusAndLabel"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
    ]),

  SemanticRelation: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      relationState: a.string().required(),
      predicate: a.string().required(),
      relationTypeId: a.id(),
      relationTypeKey: a.string(),
      relationDomain: a.string(),
      subjectKind: a.string().required(),
      subjectId: a.id().required(),
      subjectLineageId: a.id().required(),
      subjectVersionNumber: a.integer(),
      objectKind: a.string().required(),
      objectId: a.id().required(),
      objectLineageId: a.id().required(),
      objectVersionNumber: a.integer(),
      subjectStateKey: a.string().required(),
      objectStateKey: a.string().required(),
      objectSubjectStateKey: a.string().required(),
      predicateObjectStateKey: a.string().required(),
      subjectVersionKey: a.string().required(),
      objectVersionKey: a.string().required(),
      score: a.float(),
      confidence: a.float(),
      rank: a.integer(),
      classifierId: a.string(),
      modelVersion: a.string(),
      reviewRecommended: a.boolean(),
      sourceSnapshotId: a.string(),
      importRunId: a.id(),
      importedAt: a.datetime(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
      newsroomFeedKey: a.string(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["createdAt"]).queryField("listSemanticRelationsByNewsroomFeedAndCreatedAt"),
      index("subjectStateKey").sortKeys(["predicateObjectStateKey"]).queryField("listSemanticRelationsBySubjectState"),
      index("objectStateKey").sortKeys(["predicate"]).queryField("listSemanticRelationsByObjectState"),
      index("objectSubjectStateKey").sortKeys(["score"]).queryField("listSemanticRelationsByObjectSubjectStateAndScore"),
      index("predicateObjectStateKey").sortKeys(["score"]).queryField("listSemanticRelationsByPredicateObjectStateAndScore"),
      index("subjectVersionKey").sortKeys(["predicateObjectStateKey"]).queryField("listSemanticRelationsBySubjectVersion"),
      index("importRunId").sortKeys(["importedAt"]).queryField("listSemanticRelationsByImportRunAndImportedAt"),
      index("relationTypeKey").sortKeys(["importedAt"]).queryField("listSemanticRelationsByTypeAndImportedAt"),
      index("relationDomain").sortKeys(["importedAt"]).queryField("listSemanticRelationsByDomainAndImportedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(categoryAppendOnlyOperations),
    ]),

  Item: modelWithoutSubscriptions({
      id: a.id().required(),
      lineageId: a.id().required(),
      tenantId: a.string(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      type: a.string().required(),
      stage: a.string(),
      status: a.string().required(),
      typeStatus: a.string().required(),
      slug: a.string().required(),
      tenantSlug: a.string(),
      shortSlug: a.string(),
      section: a.string(),
      sectionStatus: a.string(),
      title: a.string(),
      headline: a.string(),
      deck: a.string(),
      body: a.string().array(),
      bodyMarkus: a.string(),
      bodyIr: a.json(),
      aliases: a.string().array(),
      metadata: a.json(),
      byline: a.string(),
      dateline: a.string(),
      publishedAt: a.datetime(),
      versionPublishedAt: a.datetime(),
      versionPublishedBy: a.string(),
      editionDate: a.string(),
      sortTitle: a.string(),
      pullQuotes: a.string().array(),
      layout: a.json(),
      editorial: a.json(),
      updatedAt: a.datetime(),
      starRating: a.integer(),
      starRatedAt: a.datetime(),
      starRatedBy: a.string(),
      /** The Item this one is a child of: a checklist step (type sub-task) names its Story's lineage here (docs/story-procedure.md). */
      parentLineageId: a.id(),
      /** Only the head row of a lineage carries this: its stage (tenant-prefixed on a tenant backend), so the head stage index holds one row per
       *  story; a superseded version has none (docs/plans/story-head-stage-index.md). */
      headStageKey: a.string(),
      tags: a.hasMany("ItemTag", "itemId"),
      mediaAssets: a.hasMany("MediaAsset", "itemId"),
      ...(includeEditions ? { editionItems: a.hasMany("EditionItem", "itemId") } : {}),
    })
    .secondaryIndexes((index) => [
      index("lineageId").sortKeys(["versionNumber"]).queryField("listItemsByLineageAndVersion"),
      index("slug").queryField("itemBySlug"),
      index("tenantSlug").queryField("itemByTenantSlug"),
      index("typeStatus").sortKeys(["publishedAt"]).queryField("listItemsByTypeStatusAndPublishedAt"),
      index("sectionStatus").sortKeys(["publishedAt"]).queryField("listItemsBySectionStatusAndPublishedAt"),
      index("versionState").sortKeys(["updatedAt"]).queryField("listItemsByVersionStateAndUpdatedAt"),
      index("stage").sortKeys(["updatedAt"]).queryField("listItemsByStageAndUpdatedAt"),
      index("headStageKey").sortKeys(["updatedAt"]).queryField("listItemsByHeadStageAndUpdatedAt"),
      index("parentLineageId").sortKeys(["sortTitle"]).queryField("listItemsByParentAndOrder"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
    ]),

  Tag: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      slug: a.string().required(),
      label: a.string().required(),
      type: a.string(),
      description: a.string(),
      items: a.hasMany("ItemTag", "tagId"),
    })
    .secondaryIndexes((index) => [
      index("slug").queryField("tagBySlug"),
      index("type").sortKeys(["label"]).queryField("listTagsByTypeAndLabel"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
    ]),

  ItemTag: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      itemId: a.id().required(),
      tagId: a.id().required(),
      itemType: a.string().required(),
      itemStatus: a.string().required(),
      tagSlug: a.string().required(),
      publishedAt: a.datetime(),
      item: a.belongsTo("Item", "itemId"),
      tag: a.belongsTo("Tag", "tagId"),
    })
    .secondaryIndexes((index) => [
      index("itemId").sortKeys(["tagSlug"]).queryField("listItemTagsByItemAndTag"),
      index("tagId").sortKeys(["publishedAt"]).queryField("listItemTagsByTagAndPublishedAt"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
    ]),

  MediaAsset: modelWithoutSubscriptions({
      id: a.id().required(),
      itemId: a.id().required(),
      tenantId: a.string(),
      type: a.string().required(),
      role: a.string().required(),
      sortKey: a.string().required(),
      storagePath: a.string(),
      externalUrl: a.string(),
      alt: a.string().required(),
      caption: a.string(),
      credit: a.string(),
      width: a.integer(),
      height: a.integer(),
      aspectRatio: a.float(),
      focalX: a.float(),
      focalY: a.float(),
      minHeight: a.integer(),
      preferredHeight: a.integer(),
      maxHeight: a.integer(),
      crop: a.string(),
      wrapsText: a.boolean(),
      metadata: a.json(),
      item: a.belongsTo("Item", "itemId"),
    })
    .secondaryIndexes((index) => [
      index("itemId").sortKeys(["sortKey"]).queryField("listMediaAssetsByItemAndSortKey"),
      index("role").sortKeys(["itemId"]).queryField("listMediaAssetsByRoleAndItem"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
    ]),

  Edition: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      lineageId: a.id().required(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      slug: a.string().required(),
      title: a.string().required(),
      status: a.string().required(),
      editionDate: a.string().required(),
      publishedAt: a.datetime(),
      description: a.string(),
      layoutPlan: a.json(),
      metadata: a.json(),
      items: a.hasMany("EditionItem", "editionId"),
    })
    .secondaryIndexes((index) => [
      index("lineageId").sortKeys(["versionNumber"]).queryField("listEditionsByLineageAndVersion"),
      index("slug").queryField("editionBySlug"),
      index("status").sortKeys(["editionDate"]).queryField("listEditionsByStatusAndEditionDate"),
      index("status").sortKeys(["publishedAt"]).queryField("listEditionsByStatusAndPublishedAt"),
      index("versionState").sortKeys(["publishedAt"]).queryField("listEditionsByVersionStateAndPublishedAt"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
    ]),

  EditionItem: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      editionId: a.id().required(),
      editionLineageId: a.id(),
      itemId: a.id().required(),
      itemLineageId: a.id(),
      placementKey: a.string().required(),
      sortKey: a.string().required(),
      pageNumber: a.integer(),
      priority: a.integer(),
      metadata: a.json(),
      edition: a.belongsTo("Edition", "editionId"),
      item: a.belongsTo("Item", "itemId"),
    })
    .secondaryIndexes((index) => [
      index("editionId").sortKeys(["sortKey"]).queryField("listEditionItemsByEditionAndSortKey"),
      index("itemId").sortKeys(["editionId"]).queryField("listEditionItemsByItemAndEdition"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
    ]),

  PublishedItem: modelWithoutSubscriptions({
      id: a.id().required(),
      sourceItemId: a.id().required(),
      itemLineageId: a.id().required(),
      tenantId: a.string(),
      versionNumber: a.integer().required(),
      type: a.string().required(),
      status: a.string().required(),
      typeStatus: a.string().required(),
      slug: a.string().required(),
      tenantSlug: a.string(),
      shortSlug: a.string(),
      section: a.string(),
      sectionStatus: a.string(),
      title: a.string(),
      headline: a.string(),
      deck: a.string(),
      body: a.string().array(),
      bodyMarkus: a.string(),
      bodyIr: a.json(),
      aliases: a.string().array(),
      metadata: a.json(),
      byline: a.string(),
      dateline: a.string(),
      publishedAt: a.datetime(),
      versionPublishedAt: a.datetime(),
      versionPublishedBy: a.string(),
      editionDate: a.string(),
      sortTitle: a.string(),
      pullQuotes: a.string().array(),
      layout: a.json(),
      editorial: a.json(),
    })
    .secondaryIndexes((index) => [
      index("slug").queryField("publishedItemBySlug"),
      index("tenantSlug").queryField("publishedItemByTenantSlug"),
      index("typeStatus").sortKeys(["publishedAt"]).queryField("listPublishedItemsByTypeStatusAndPublishedAt"),
      index("sectionStatus").sortKeys(["publishedAt"]).queryField("listPublishedItemsBySectionStatusAndPublishedAt"),
      index("itemLineageId").sortKeys(["versionNumber"]).queryField("listPublishedItemsByLineageAndVersion"),
    ])
    .authorization((allow) => [
      allow.guest().to(["read"]),
      allow.groups(contentWriteGroups),
    ]),

  PublishedMediaAsset: modelWithoutSubscriptions({
      id: a.id().required(),
      sourceMediaAssetId: a.id().required(),
      tenantId: a.string(),
      publishedItemId: a.id().required(),
      sourceItemId: a.id().required(),
      itemLineageId: a.id().required(),
      type: a.string().required(),
      role: a.string().required(),
      sortKey: a.string().required(),
      storagePath: a.string(),
      externalUrl: a.string(),
      alt: a.string().required(),
      caption: a.string(),
      credit: a.string(),
      width: a.integer(),
      height: a.integer(),
      aspectRatio: a.float(),
      focalX: a.float(),
      focalY: a.float(),
      minHeight: a.integer(),
      preferredHeight: a.integer(),
      maxHeight: a.integer(),
      crop: a.string(),
      wrapsText: a.boolean(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("publishedItemId").sortKeys(["sortKey"]).queryField("listPublishedMediaAssetsByItemAndSortKey"),
      index("role").sortKeys(["publishedItemId"]).queryField("listPublishedMediaAssetsByRoleAndItem"),
    ])
    .authorization((allow) => [
      allow.guest().to(["read"]),
      allow.groups(contentWriteGroups),
    ]),

  PublishedEdition: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      sourceEditionId: a.id().required(),
      editionLineageId: a.id().required(),
      versionNumber: a.integer().required(),
      slug: a.string().required(),
      title: a.string().required(),
      status: a.string().required(),
      editionDate: a.string().required(),
      publishedAt: a.datetime(),
      description: a.string(),
      layoutPlan: a.json(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("slug").queryField("publishedEditionBySlug"),
      index("status").sortKeys(["editionDate"]).queryField("listPublishedEditionsByStatusAndEditionDate"),
      index("status").sortKeys(["publishedAt"]).queryField("listPublishedEditionsByStatusAndPublishedAt"),
      index("editionLineageId").sortKeys(["versionNumber"]).queryField("listPublishedEditionsByLineageAndVersion"),
    ])
    .authorization((allow) => [
      allow.guest().to(["read"]),
      allow.groups(contentWriteGroups),
    ]),

  PublishedEditionItem: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      publishedEditionId: a.id().required(),
      publishedItemId: a.id().required(),
      sourceEditionItemId: a.id().required(),
      sourceEditionId: a.id().required(),
      sourceItemId: a.id().required(),
      editionLineageId: a.id().required(),
      itemLineageId: a.id().required(),
      placementKey: a.string().required(),
      sortKey: a.string().required(),
      pageNumber: a.integer(),
      priority: a.integer(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("publishedEditionId").sortKeys(["sortKey"]).queryField("listPublishedEditionItemsByEditionAndSortKey"),
      index("publishedItemId").sortKeys(["publishedEditionId"]).queryField("listPublishedEditionItemsByItemAndEdition"),
    ])
    .authorization((allow) => [
      allow.guest().to(["read"]),
      allow.groups(contentWriteGroups),
    ]),

  PublishedCategorySet: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      sourceCategorySetId: a.id().required(),
      categorySetLineageId: a.id().required(),
      versionNumber: a.integer().required(),
      corpusId: a.id().required(),
      classifierId: a.string().required(),
      displayName: a.string().required(),
      description: a.string(),
      status: a.string().required(),
      generatedAt: a.datetime(),
      publishedAt: a.datetime(),
      categoryCount: a.integer(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("status").sortKeys(["displayName"]).queryField("listPublishedCategorySetsByStatusAndName"),
      index("classifierId").sortKeys(["displayName"]).queryField("listPublishedCategorySetsByClassifierAndName"),
      index("categorySetLineageId").sortKeys(["versionNumber"]).queryField("listPublishedCategorySetsByLineageAndVersion"),
    ])
    .authorization((allow) => [
      allow.guest().to(["read"]),
      allow.groups(contentWriteGroups),
    ]),

  PublishedCategory: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string(),
      sourceCategoryId: a.id().required(),
      publishedCategorySetId: a.id().required(),
      categoryLineageId: a.id().required(),
      categorySetLineageId: a.id().required(),
      versionNumber: a.integer().required(),
      corpusId: a.id().required(),
      categoryKey: a.string().required(),
      parentCategoryId: a.id(),
      parentCategoryKey: a.string(),
      displayName: a.string().required(),
      shortTitle: a.string(),
      subtitle: a.string(),
      description: a.string(),
      aliases: a.string().array(),
      status: a.string().required(),
      seedItemIds: a.string().array(),
      holdoutItemIds: a.string().array(),
      rank: a.integer(),
      depth: a.integer(),
      isPinned: a.boolean(),
      metadata: a.json(),
    })
    .secondaryIndexes((index) => [
      index("publishedCategorySetId").sortKeys(["categoryKey"]).queryField("listPublishedCategoriesBySetAndKey"),
      index("parentCategoryId").sortKeys(["rank"]).queryField("listPublishedCategoriesByParentAndRank"),
      index("parentCategoryKey").sortKeys(["rank"]).queryField("listPublishedCategoriesByParentKeyAndRank"),
      index("categoryKey").sortKeys(["publishedCategorySetId"]).queryField("listPublishedCategoriesByKeyAndSet"),
    ])
    .authorization((allow) => [
      allow.guest().to(["read"]),
      allow.groups(contentWriteGroups),
    ]),
  /** A tenant: one publication on a shared stack, id = the site id. Operators write; its own admin reads (PPY-31c45c). Group "tenancy". */
  Tenant: modelWithoutSubscriptions({
      id: a.id().required(),
      accountId: a.string().required(),
      displayName: a.string().required(),
      state: a.string().required(),
      stateKey: a.string().required(),
      plan: a.string(),
      entitlements: a.json(),
      createdAt: a.datetime().required(),
      stateChangedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("accountId").queryField("listTenantsByAccount"),
      index("stateKey").queryField("listTenantsByStateKey"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
      allow.ownerDefinedIn("id").identityClaim("papyrus_tenant_admin").to(["read"]),
    ]),

  /** Who belongs to a tenant and in what role; id = "<tenant>#<userSub>" (PPY-31c45c). Group "tenancy". */
  TenantMembership: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string().required(),
      userSub: a.string().required(),
      userProfileId: a.id(),
      role: a.string().required(),
      status: a.string().required(),
      grantedBy: a.string(),
      grantedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("userSub").queryField("listTenantMembershipsByUserSub"),
      index("tenantId").queryField("listTenantMembershipsByTenant"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
      allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_admin").to(["read"]),
    ]),

  /** A hostname served for a tenant; id = the lowercase hostname, so it can belong to one tenant only (PPY-31c45c). Group "tenancy". */
  TenantDomain: modelWithoutSubscriptions({
      id: a.id().required(),
      tenantId: a.string().required(),
      kind: a.string().required(),
      status: a.string().required(),
      verification: a.json(),
      certificateRef: a.string(),
    })
    .secondaryIndexes((index) => [
      index("tenantId").queryField("listTenantDomainsByTenant"),
    ])
    .authorization((allow) => [
      allow.group(adminGroup),
      allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_admin").to(["read"]),
    ]),

  ...editorialChecksSchemaDefinitions,
  ...monitoringViewSchemaDefinitions,
  ...automationViewSchemaDefinitions,
  ...imageServiceSchemaDefinitions,
  ...proposalActionsSchemaDefinitions,
  ...messageActionsSchemaDefinitions,
  ...profileActionsSchemaDefinitions,
};
const mutableDefinitions = definitions as Record<string, unknown>;
for (const group of excludedGroups) {
  for (const modelName of OPTIONAL_MODEL_GROUPS[group]) delete mutableDefinitions[modelName];
}
return definitions;
}

export function baseModelNames(excludedGroups: readonly OptionalModelGroup[] = []): string[] {
  return Object.keys(buildBaseDefinitions(excludedGroups));
}

const baseDefinitions = buildBaseDefinitions();

/** Schema-level function grants shared by every deployed schema, with or without plugins, so none can drop one. */
function functionGrants(allow: any) {
  return [
    allow.resource(assignmentAction).to(["query", "mutate"]),
    allow.resource(categoryAction),
    allow.resource(contentActions),
    allow.resource(imageService).to(["query", "mutate"]),
    allow.resource(manageUserRole),
    allow.resource(modelAttachmentUpload),
    allow.resource(newsroomSummary),
    allow.resource(procedureAction),
    allow.resource(publicForms).to(["mutate"]),
  ];
}

/**
 * Pick a rule set by tenancy mode (docs/multi-tenancy.md). Not used yet: a later change passes the shared
 * stack's rules (no guest reads, no global group rules) through here so dedicated sites keep today's.
 */
export function rulesForTenancyMode<T>(mode: "dedicated" | "shared", rules: { dedicated: T; shared: T }): T {
  return mode === "shared" ? rules.shared : rules.dedicated;
}

export const schema = a.schema(baseDefinitions).authorization(functionGrants);

/** The deployed schema of a site that enables plugins: the base definitions plus what each plugin contributes (docs/plugins.md). */
export function schemaWithPlugins(pluginDefinitions: Record<string, any>) {
  return a.schema({ ...baseDefinitions, ...pluginDefinitions } as typeof baseDefinitions).authorization(functionGrants);
}

/** The schema of a site that leaves optional model groups out of its first deploy. */
export function schemaExcludingGroups(excludedGroups: readonly OptionalModelGroup[], pluginDefinitions: Record<string, any> = {}) {
  const definitions = buildBaseDefinitions(excludedGroups) as unknown as typeof baseDefinitions;
  return a.schema({ ...definitions, ...pluginDefinitions } as typeof baseDefinitions).authorization(functionGrants);
}

export type Schema = ClientSchema<typeof schema>;
