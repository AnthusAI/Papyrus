import { type ClientSchema, a } from "@aws-amplify/backend";
import { assignmentAction } from "../functions/assignment-action/resource";
import { categoryAction } from "../functions/category-action/resource";
import { knowledgeQuery } from "../functions/knowledge-query/resource";
import { manageUserRole } from "../functions/manage-user-role/resource";
import { modelAttachmentUpload } from "../functions/model-attachment-upload/resource";
import { newsroomSummary } from "../functions/newsroom-summary/resource";
import { procedureAction } from "../functions/procedure-action/resource";
import { readerSettings } from "../functions/reader-settings/resource";

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

export const schema = a.schema({
  UserProfile: modelWithoutSubscriptions({
      id: a.id().required(),
      email: a.email(),
      displayName: a.string(),
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
    .authorization((allow) => [
      allow.owner(),
      allow.group(adminGroup),
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
    settings: a.json(),
  }),

  listUserDirectory: a
    .query()
    .returns(a.ref("UserDirectoryResult"))
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(a.handler.function(manageUserRole)),

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
    .handler(a.handler.function(manageUserRole)),

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
    .handler(a.handler.function(manageUserRole)),

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
    .handler(a.handler.function(manageUserRole)),

  getReaderSettings: a
    .query()
    .returns(a.ref("ReaderSettingsResult"))
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(readerSettings)),

  updateReaderSettings: a
    .mutation()
    .arguments({
      settings: a.json().required(),
    })
    .returns(a.ref("ReaderSettingsResult"))
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(readerSettings)),

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
    .handler(a.handler.function(categoryAction)),

  ReferenceCurationActionResult: a.customType({
    ok: a.boolean().required(),
    action: a.string().required(),
    referenceId: a.id().required(),
    status: a.string().required(),
    reasonCode: a.string(),
    messageId: a.id(),
    relationId: a.id(),
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
      note: a.string(),
      reasonCode: a.string(),
    })
    .returns(a.ref("ReferenceCurationActionResult"))
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
      allow.custom(),
    ])
    .handler(a.handler.function(categoryAction)),

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
      allow.custom(),
    ])
    .handler(a.handler.function(categoryAction)),

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
    .handler(a.handler.function(categoryAction)),

  promoteCategorySetDraft: a
    .mutation()
    .arguments({
      categorySetId: a.id().required(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("CategorySetDraftActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(a.handler.function(categoryAction)),

  discardCategorySetDraft: a
    .mutation()
    .arguments({
      categorySetId: a.id().required(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("CategorySetDraftActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(a.handler.function(categoryAction)),

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
    .handler(a.handler.function(categoryAction)),

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
    .handler(a.handler.function(categoryAction)),

  archiveDraftCategory: a
    .mutation()
    .arguments({
      categoryId: a.id().required(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("SteeringActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups)])
    .handler(a.handler.function(categoryAction)),

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
    .handler(a.handler.function(categoryAction)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(newsroomSummary)),

  knowledgeQuery: a
    .query()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(knowledgeQuery)),

  updateNewsroomSummary: a
    .mutation()
    .arguments({
      delta: a.json().required(),
      actorLabel: a.string(),
      reason: a.string(),
    })
    .returns(a.ref("NewsroomSummary"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(newsroomSummary)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(modelAttachmentUpload)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(modelAttachmentUpload)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(modelAttachmentUpload)),

  createModelAttachmentDownload: a
    .mutation()
    .arguments({
      attachmentId: a.id().required(),
    })
    .returns(a.ref("ModelAttachmentDownloadSlot"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(modelAttachmentUpload)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  listAssignmentQueue: a
    .query()
    .arguments({
      queueKey: a.string().required(),
      status: a.string(),
      limit: a.integer(),
    })
    .returns(a.ref("AssignmentContext").array().required())
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  getAssignmentContext: a
    .query()
    .arguments({
      assignmentId: a.id().required(),
    })
    .returns(a.ref("AssignmentContext"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  releaseAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  completeAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  cancelAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  reopenAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  retryImmediateAssignment: a
    .mutation()
    .arguments({
      assignmentId: a.id().required(),
      actorSub: a.string(),
      actorLabel: a.string(),
      note: a.string(),
    })
    .returns(a.ref("AssignmentActionResult"))
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(assignmentAction)),

  listNewsroomProcedureDefinitions: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(a.handler.function(procedureAction)),

  getNewsroomProcedureDefinition: a
    .query()
    .arguments({
      id: a.id(),
      procedureKey: a.string(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup), allow.custom()])
    .handler(a.handler.function(procedureAction)),

  saveNewsroomProcedureDefinition: a
    .mutation()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(a.handler.function(procedureAction)),

  saveNewsroomProcedureVersionDraft: a
    .mutation()
    .arguments({
      input: a.json().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(a.handler.function(procedureAction)),

  publishNewsroomProcedureVersion: a
    .mutation()
    .arguments({
      versionId: a.id().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.group(adminGroup)])
    .handler(a.handler.function(procedureAction)),

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
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(procedureAction)),

  getNewsroomProcedureRun: a
    .query()
    .arguments({
      id: a.id().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(procedureAction)),

  listNewsroomProcedureRunsByProcedure: a
    .query()
    .arguments({
      procedureId: a.id().required(),
    })
    .returns(a.json())
    .authorization((allow) => [allow.groups(categoryWriteGroups), allow.custom()])
    .handler(a.handler.function(procedureAction)),

  Assignment: modelWithoutSubscriptions({
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
      newsroomFeedKey: a.string(),
    })
    .secondaryIndexes((index) => [
      index("newsroomFeedKey").sortKeys(["createdAt"]).queryField("listAssignmentsByNewsroomFeedAndCreatedAt"),
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
      allow.authenticated("identityPool").to(authoringOperations),
      allow.custom().to(authoringOperations),
    ]),

  AssignmentEvent: modelWithoutSubscriptions({
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
    })
    .secondaryIndexes((index) => [
      index("assignmentId").sortKeys(["createdAt"]).queryField("listAssignmentEventsByAssignmentAndCreatedAt"),
      index("eventType").sortKeys(["createdAt"]).queryField("listAssignmentEventsByTypeAndCreatedAt"),
      index("queueKey").sortKeys(["createdAt"]).queryField("listAssignmentEventsByQueueAndCreatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(categoryAppendOnlyOperations),
      allow.custom().to(authoringOperations),
    ]),

  ProcedureDefinition: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  ProcedureVersion: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  ProcedureRun: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  NewsroomSection: modelWithoutSubscriptions({
      id: a.id().required(),
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
      visualGuidance: a.string(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
    })
    .secondaryIndexes((index) => [
      index("sortOrder").sortKeys(["id"]).queryField("listNewsroomSectionsBySortOrder"),
      index("type").sortKeys(["sortOrder"]).queryField("listNewsroomSectionsByTypeAndSortOrder"),
      index("enabledStatus").sortKeys(["sortOrder"]).queryField("listNewsroomSectionsByEnabledStatusAndSortOrder"),
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  KnowledgeCorpus: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  KnowledgeImportRun: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  KnowledgeRawPayload: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  KnowledgeArtifact: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  CategorySet: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  Category: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  CategoryKeyword: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  LexicalSteeringRule: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  SteeringProposal: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  SteeringDecision: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  Reference: realtimeModel({
      id: a.id().required(),
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
      newsroomFeedKey: a.string(),
      reviewedFeedKey: a.string(),
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
    ])
    .authorization((allow) => [
      allow.groups(categoryWriteGroups).to(["read"]),
      allow.custom().to(authoringOperations),
    ]),

  ReferenceAttachment: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  SemanticNode: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  Message: realtimeModel({
      id: a.id().required(),
      messageKind: a.string().required(),
      messageDomain: a.string().required(),
      status: a.string().required(),
      summary: a.string(),
      source: a.string(),
      importRunId: a.id(),
      authorSub: a.string(),
      authorUserProfileId: a.id(),
      authorLabel: a.string(),
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
      allow.groups(categoryWriteGroups).to(categoryAppendOnlyOperations),
      allow.custom().to(authoringOperations),
    ]),

  MessageThread: realtimeModel({
      id: a.id().required(),
      threadKind: a.string().required(),
      status: a.string().required(),
      title: a.string().required(),
      summary: a.string(),
      primaryAnchorKind: a.string(),
      primaryAnchorId: a.id(),
      primaryAnchorLineageId: a.id(),
      primaryAnchorKey: a.string(),
      createdBySub: a.string(),
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
      allow.authenticated("identityPool").to(authoringOperations),
      allow.custom().to(authoringOperations),
    ]),

  ModelAttachment: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  SemanticRelationType: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  SemanticRelation: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  Item: modelWithoutSubscriptions({
      id: a.id().required(),
      lineageId: a.id().required(),
      versionNumber: a.integer().required(),
      previousVersionId: a.id(),
      versionState: a.string().required(),
      versionCreatedAt: a.datetime().required(),
      versionCreatedBy: a.string(),
      changeReason: a.string(),
      contentHash: a.string(),
      type: a.string().required(),
      status: a.string().required(),
      typeStatus: a.string().required(),
      slug: a.string().required(),
      shortSlug: a.string(),
      section: a.string(),
      sectionStatus: a.string(),
      title: a.string(),
      headline: a.string(),
      deck: a.string(),
      body: a.string().array(),
      byline: a.string(),
      dateline: a.string(),
      publishedAt: a.datetime(),
      editionDate: a.string(),
      sortTitle: a.string(),
      pullQuotes: a.string().array(),
      layout: a.json(),
      editorial: a.json(),
      updatedAt: a.datetime(),
      tags: a.hasMany("ItemTag", "itemId"),
      mediaAssets: a.hasMany("MediaAsset", "itemId"),
      editionItems: a.hasMany("EditionItem", "itemId"),
    })
    .secondaryIndexes((index) => [
      index("lineageId").sortKeys(["versionNumber"]).queryField("listItemsByLineageAndVersion"),
      index("slug").queryField("itemBySlug"),
      index("typeStatus").sortKeys(["publishedAt"]).queryField("listItemsByTypeStatusAndPublishedAt"),
      index("sectionStatus").sortKeys(["publishedAt"]).queryField("listItemsBySectionStatusAndPublishedAt"),
      index("versionState").sortKeys(["updatedAt"]).queryField("listItemsByVersionStateAndUpdatedAt"),
    ])
    .authorization((allow) => [
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  Tag: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  ItemTag: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  MediaAsset: modelWithoutSubscriptions({
      id: a.id().required(),
      itemId: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  Edition: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  EditionItem: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.custom().to(authoringOperations),
    ]),

  PublishedItem: modelWithoutSubscriptions({
      id: a.id().required(),
      sourceItemId: a.id().required(),
      itemLineageId: a.id().required(),
      versionNumber: a.integer().required(),
      type: a.string().required(),
      status: a.string().required(),
      typeStatus: a.string().required(),
      slug: a.string().required(),
      shortSlug: a.string(),
      section: a.string(),
      sectionStatus: a.string(),
      title: a.string(),
      headline: a.string(),
      deck: a.string(),
      body: a.string().array(),
      byline: a.string(),
      dateline: a.string(),
      publishedAt: a.datetime(),
      editionDate: a.string(),
      sortTitle: a.string(),
      pullQuotes: a.string().array(),
      layout: a.json(),
      editorial: a.json(),
    })
    .secondaryIndexes((index) => [
      index("slug").queryField("publishedItemBySlug"),
      index("typeStatus").sortKeys(["publishedAt"]).queryField("listPublishedItemsByTypeStatusAndPublishedAt"),
      index("sectionStatus").sortKeys(["publishedAt"]).queryField("listPublishedItemsBySectionStatusAndPublishedAt"),
      index("itemLineageId").sortKeys(["versionNumber"]).queryField("listPublishedItemsByLineageAndVersion"),
    ])
    .authorization((allow) => [
      allow.publicApiKey().to(["read"]),
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  PublishedMediaAsset: modelWithoutSubscriptions({
      id: a.id().required(),
      sourceMediaAssetId: a.id().required(),
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
      allow.publicApiKey().to(["read"]),
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  PublishedEdition: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.publicApiKey().to(["read"]),
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  PublishedEditionItem: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.publicApiKey().to(["read"]),
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  PublishedCategorySet: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.publicApiKey().to(["read"]),
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),

  PublishedCategory: modelWithoutSubscriptions({
      id: a.id().required(),
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
      allow.publicApiKey().to(["read"]),
      allow.groups(contentWriteGroups),
      allow.custom().to(authoringOperations),
    ]),
}).authorization((allow) => [
  allow.resource(categoryAction),
  allow.resource(manageUserRole),
  allow.resource(modelAttachmentUpload),
  allow.resource(newsroomSummary),
  allow.resource(procedureAction),
]);

export type Schema = ClientSchema<typeof schema>;
