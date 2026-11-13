import { readFileSync } from "node:fs";
import { join } from "node:path";

const SCHEMA_FILES = ["amplify/data/schema.ts", "amplify/data/resource.ts"];
// The deployed schema (schema.ts) and the typed schema (resource.ts) must agree
// for every model the Python authoring client reads with a fixed field list.
const MODEL_NAMES = [
  "Item", "PublishedItem", "StoryVariation", "SemanticNode", "SemanticRelation", "Reference", "Message",
  "Assignment", "KnowledgeRawPayload", "CurationDelegationRecord", "ModelAttachment", "MediaAsset", "PublishedMediaAsset", "NewsroomSection", "Automation", "ProcedureRun", "ReviewRequest", "ReviewReadMark", "ReviewRecipientRule",
];
const REQUIRED_FIELDS: Record<string, string[]> = {
  Item: ["bodyMarkus", "bodyIr", "aliases", "metadata", "tenantId", "tenantSlug", "headStageKey", "scheduledPublishAt", "scheduledBy", "scheduledAt", "scheduleState", "scheduleName"],
  PublishedItem: ["bodyMarkus", "bodyIr", "aliases", "metadata", "tenantId", "tenantSlug"],
  Message: ["editedAt", "deletedAt", "deletedBySub"],
  MediaAsset: ["tenantId"],
  PublishedMediaAsset: ["tenantId"],
  NewsroomSection: ["tenantId"],
};

// Indexes the References page reads through (features_backend/reference-feed-keys.feature): each must exist, with its sort key, in both files.
const REQUIRED_INDEXES = [
  'index("feedStateKey").sortKeys(["predictionSortKey"]).queryField("listReferencesByFeedStateAndPrediction")',
  'index("feedStateKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByFeedStateAndArrival")',
  'index("starFeedKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByStarFeedAndArrival")',
  'index("mediumFeedKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByMediumFeedAndArrival")',
  'index("contentNeededKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByContentNeededAndArrival")',
  // One row per story (features_backend/story-head-stage-index.feature): only the head row of a lineage carries headStageKey.
  'index("headStageKey").sortKeys(["updatedAt"]).queryField("listItemsByHeadStageAndUpdatedAt")',
  // The old stage index stays until every reader has moved (docs/plans/story-head-stage-index.md, step 7).
  'index("stage").sortKeys(["updatedAt"]).queryField("listItemsByStageAndUpdatedAt")',
  // Scheduled publishing (docs/scheduled-publishing.md): the sparse index of scheduled versions; the Item's tenth, and the only one in its deploy.
  'index("scheduleState").sortKeys(["scheduledPublishAt"]).queryField("listItemsByScheduleStateAndScheduledPublishAt")',
];

function extractFieldNames(source: string, modelName: string): Set<string> {
  const startPattern = new RegExp(`^  ${modelName}: `, "m");
  const startMatch = startPattern.exec(source);
  if (!startMatch) {
    throw new Error(`model ${modelName} not found`);
  }
  const rest = source.slice(startMatch.index);
  // The fields end where the model's indexes or, for a model without indexes, its authorization rules begin.
  const ends = [rest.indexOf(".secondaryIndexes"), rest.indexOf(".authorization")].filter((index) => index !== -1);
  const block = ends.length === 0 ? rest : rest.slice(0, Math.min(...ends));
  const names = new Set<string>();
  for (const match of block.matchAll(/^\s{6}(?:\.\.\.\(\w+ \? \{ )?(\w+): a\./gm)) {
    names.add(match[1]);
  }
  return names;
}

let failed = false;
for (const modelName of MODEL_NAMES) {
  const perFile = SCHEMA_FILES.map((file) =>
    extractFieldNames(readFileSync(join(process.cwd(), file), "utf8"), modelName),
  );
  const [first, second] = perFile;
  const onlyFirst = [...first].filter((name) => !second.has(name));
  const onlySecond = [...second].filter((name) => !first.has(name));
  if (onlyFirst.length || onlySecond.length) {
    failed = true;
    console.error(`${modelName} drift: only in ${SCHEMA_FILES[0]}: ${onlyFirst}; only in ${SCHEMA_FILES[1]}: ${onlySecond}`);
  }
  for (const field of REQUIRED_FIELDS[modelName] ?? []) {
    for (let index = 0; index < perFile.length; index += 1) {
      if (!perFile[index].has(field)) {
        failed = true;
        console.error(`${modelName} missing ${field} in ${SCHEMA_FILES[index]}`);
      }
    }
  }
  console.log(`${modelName}: ${first.size} fields in schema.ts, ${second.size} in resource.ts`);
}
for (const file of SCHEMA_FILES) {
  const source = readFileSync(join(process.cwd(), file), "utf8");
  for (const declaration of REQUIRED_INDEXES) {
    if (!source.includes(declaration)) {
      failed = true;
      console.error(`Reference is missing ${declaration} in ${file}`);
    }
  }
}
// Custom queries and mutations: the deployed schema (schema.ts) must carry every one the typed schema (resource.ts) declares, or the client
// calls a field the site's API does not have (createReferenceLink and three more shipped only in resource.ts in 5.69.0). The four below
// were already only in resource.ts before this check existed; deciding whether to deploy or delete them is its own change.
const KNOWN_TYPED_ONLY_OPERATIONS = new Set(["createReferenceNote", "getReferenceCurationStatus", "moveReferenceCorpus", "startReferenceCuration"]);
function operationNames(source: string): Set<string> {
  return new Set([...source.matchAll(/^  (\w+): a\s*\n\s*\.(?:mutation|query)\(\)/gm)].map((match) => match[1]));
}
const [deployedOperations, typedOperations] = SCHEMA_FILES.map((file) => operationNames(readFileSync(join(process.cwd(), file), "utf8")));
const missingOperations = [...typedOperations].filter((name) => !deployedOperations.has(name) && !KNOWN_TYPED_ONLY_OPERATIONS.has(name));
if (missingOperations.length) {
  failed = true;
  console.error(`operations declared in ${SCHEMA_FILES[1]} but not deployed by ${SCHEMA_FILES[0]}: ${missingOperations.join(", ")}`);
}
console.log(`operations: ${deployedOperations.size} in schema.ts, ${typedOperations.size} in resource.ts`);

// Every tenant-owned model carries an optional tenantId (features_backend/tenant-field-everywhere.feature, PPY-94d609); the global identity
// models do not. Models declared by a function or plugin schema are shared by both files, so each declaration is read where it lives.
const TENANT_FIELD_SOURCES = [
  ...SCHEMA_FILES,
  "amplify/functions/editorial-checks/schema.ts",
  "amplify/functions/proposal-actions/schema.ts",
  "amplify/plugins/reader-steering/schema.ts",
  "amplify/plugins/signup/schema.ts",
];
const TENANT_FIELD_MODELS = [
  "UserRoleAssignment", "Assignment", "AssignmentEvent", "ProcedureDefinition", "ProcedureVersion", "ProcedureRun", "Automation",
  "ReviewRequest", "ReviewReadMark", "StoryVariation", "ReviewRecipientRule", "KnowledgeCorpus", "KnowledgeImportRun",
  "KnowledgeRawPayload", "CurationDelegationRecord", "KnowledgeArtifact", "CategorySet", "Category", "CategoryKeyword",
  "LexicalSteeringRule", "SteeringProposal", "SteeringDecision", "Reference", "ReferenceAttachment", "SemanticNode", "Message",
  "MessageThread", "ModelAttachment", "SemanticRelationType", "SemanticRelation", "Tag", "ItemTag", "Edition", "EditionItem",
  "PublishedEdition", "PublishedEditionItem", "PublishedCategorySet", "PublishedCategory", "EditorialPolicy",
  "EditorialCheckSettings", "EditorialFeedback", "EditorialCheckRun", "Proposal", "ReaderProfile", "ReaderHandle", "ReaderVote",
  "ReaderFlag", "ReaderComment", "ReaderSubmission", "ReaderReport", "ModerationAction", "SignupEntry",
];
const GLOBAL_IDENTITY_MODELS = ["UserProfile", "UserIdentity", "PublicHandleClaim"];
function modelDeclarations(modelName: string): { file: string; block: string }[] {
  const found: { file: string; block: string }[] = [];
  for (const file of TENANT_FIELD_SOURCES) {
    const source = readFileSync(join(process.cwd(), file), "utf8");
    const start = new RegExp(`^\\s*${modelName}: (?:a\\s*\\.model|modelWithoutSubscriptions|realtimeModel)\\(`, "m").exec(source);
    if (!start) continue;
    const rest = source.slice(start.index);
    const end = rest.search(/^\s*\}\)/m);
    found.push({ file, block: rest.slice(0, end === -1 ? rest.length : end) });
  }
  return found;
}
for (const modelName of TENANT_FIELD_MODELS) {
  const declarations = modelDeclarations(modelName);
  if (!declarations.length) {
    failed = true;
    console.error(`${modelName} is not declared in any schema file`);
  }
  for (const { file, block } of declarations) {
    if (!/^\s+tenantId: a\.string\(\),/m.test(block)) {
      failed = true;
      console.error(`${modelName} has no optional tenantId in ${file}`);
    }
  }
}
for (const modelName of GLOBAL_IDENTITY_MODELS) {
  for (const { file, block } of modelDeclarations(modelName)) {
    if (/tenantId:/.test(block)) {
      failed = true;
      console.error(`${modelName} is a global identity model and must not carry tenantId (${file})`);
    }
  }
}
console.log(`tenantId: ${TENANT_FIELD_MODELS.length} tenant-owned models checked`);
// The tenancy models (features_backend/tenant-records.feature, PPY-31c45c): new tables with all their indexes, in both files, and in the
// optional "tenancy" group. No existing table gains an index with them.
const TENANCY_MODELS: Record<string, { fields: string[]; indexes: string[] }> = {
  Tenant: {
    fields: ["id", "accountId", "displayName", "state", "stateKey", "plan", "entitlements", "createdAt", "stateChangedAt"],
    indexes: ['index("accountId").queryField("listTenantsByAccount")', 'index("stateKey").queryField("listTenantsByStateKey")'],
  },
  TenantMembership: {
    fields: ["id", "tenantId", "userSub", "userProfileId", "role", "status", "grantedBy", "grantedAt"],
    indexes: ['index("userSub").queryField("listTenantMembershipsByUserSub")', 'index("tenantId").queryField("listTenantMembershipsByTenant")'],
  },
  TenantDomain: {
    fields: ["id", "tenantId", "kind", "status", "verification", "certificateRef"],
    indexes: ['index("tenantId").queryField("listTenantDomainsByTenant")'],
  },
  SiteDocument: {
    fields: ["id", "tenantId", "kind", "currentVersion", "s3Key", "sha256", "schemaVersion", "updatedBy", "updatedAt"],
    indexes: [],
  },
  SiteDocumentVersion: {
    fields: ["id", "tenantId", "documentId", "version", "s3Key", "sha256", "createdBy", "createdAt", "note"],
    indexes: ['index("documentId").sortKeys(["version"]).queryField("listSiteDocumentVersionsByDocument")'],
  },
};
for (const [modelName, expected] of Object.entries(TENANCY_MODELS)) {
  for (const file of SCHEMA_FILES) {
    const source = readFileSync(join(process.cwd(), file), "utf8");
    const names = [...extractFieldNames(source, modelName)].sort();
    if (JSON.stringify(names) !== JSON.stringify([...expected.fields].sort())) {
      failed = true;
      console.error(`${modelName} fields in ${file} are ${names}; expected ${expected.fields}`);
    }
    for (const declaration of expected.indexes) {
      if (!source.includes(declaration)) {
        failed = true;
        console.error(`${modelName} is missing ${declaration} in ${file}`);
      }
    }
  }
}
if (!failed) console.log("tenancy indexes ok");

if (failed) {
  process.exit(1);
}
console.log("schema parity ok");
