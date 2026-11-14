export const TENANT_ID_ENVIRONMENT_VARIABLE = "PAPYRUS_TENANT_ID";
export const TENANCY_MODE_ENVIRONMENT_VARIABLE = "PAPYRUS_TENANCY_MODE";

/** The only reader of PAPYRUS_TENANCY_MODE in TypeScript. Unset or anything but "shared" means a dedicated stack. */
export function isSharedStack(environment: Record<string, string | undefined> = process.env): boolean {
  return environment[TENANCY_MODE_ENVIRONMENT_VARIABLE]?.trim().toLowerCase() === "shared";
}


/** Models whose rows carry a `tenantId` and tenant-shaped keys (twin of TENANT_MODELS in src/papyrus_content/tenancy.py; scripts/test-function-tenant-context.ts checks both against the schema). */
export const TENANT_MODELS: ReadonlySet<string> = new Set([
  "Item", "PublishedItem", "MediaAsset", "PublishedMediaAsset", "NewsroomSection",
]);

/** Models that carry an optional `tenantId` and nothing else tenant-shaped (twin of TENANT_FIELD_MODELS in tenancy.py). */
export const TENANT_FIELD_MODELS: ReadonlySet<string> = new Set([
  "UserRoleAssignment", "Assignment", "AssignmentEvent", "ProcedureDefinition", "ProcedureVersion", "ProcedureRun",
  "Automation", "ReviewRequest", "ReviewReadMark", "StoryVariation", "ReviewRecipientRule", "KnowledgeCorpus",
  "KnowledgeImportRun", "KnowledgeRawPayload", "CurationDelegationRecord", "KnowledgeArtifact", "CategorySet", "Category",
  "CategoryKeyword", "LexicalSteeringRule", "SteeringProposal", "SteeringDecision", "Reference", "ReferenceAttachment",
  "SemanticNode", "Message", "MessageThread", "ModelAttachment", "SemanticRelationType", "SemanticRelation", "Tag", "ItemTag",
  "Edition", "EditionItem", "PublishedEdition", "PublishedEditionItem", "PublishedCategorySet", "PublishedCategory",
  "EditorialPolicy", "EditorialCheckSettings", "EditorialFeedback", "EditorialCheckRun", "Proposal", "ReaderProfile",
  "ReaderHandle", "ReaderVote", "ReaderFlag", "ReaderComment", "ReaderSubmission", "ReaderReport", "ModerationAction",
  "SignupEntry", "LocalizationRequest",
]);

const TENANT_KEY_SEPARATOR = "#";
const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;

export function validateTenantId(tenantId: string): string {
  if (!TENANT_ID_PATTERN.test(tenantId)) {
    throw new Error(`Tenant id "${tenantId}" must be lowercase letters, digits and hyphens, starting with a letter or digit.`);
  }
  return tenantId;
}

export function tenantIdFromEnvironment(environment: Record<string, string | undefined> = process.env): string | undefined {
  const configured = environment[TENANT_ID_ENVIRONMENT_VARIABLE]?.trim();
  return configured ? validateTenantId(configured) : undefined;
}

export function tenantScopedValue(tenantId: string | undefined, value: string): string {
  if (!tenantId) return value;
  const prefix = `${tenantId}${TENANT_KEY_SEPARATOR}`;
  return value.startsWith(prefix) ? value : `${prefix}${value}`;
}

export function rowBelongsToTenant(tenantId: string | undefined, row: { tenantId?: string | null } | null | undefined): boolean {
  if (!tenantId || !row) return true;
  return row.tenantId === tenantId;
}

/** The tenant a Prospectus publishing account maps to: its id as lowercase letters, digits and hyphens. */
export function tenantIdForProspectusAccount(accountId: string | null | undefined): string | undefined {
  const normalized = (accountId ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 63);
  return normalized ? validateTenantId(normalized) : undefined;
}
