import fs from "node:fs";
import path from "node:path";
import YAML from "yaml";
import { createEmptyCategorySteeringDashboard } from "./category-dashboard";
import { applyPilobolusDemoDashboardContent } from "./newsroom-demo-dashboard";
import { getNewsroomDemoProfile, isPilobolusDemoBrand } from "./newsroom-demo-profile";
import { resolveSiteBrandId, type SiteBrandId } from "./site-brand";

export { createEmptyCategorySteeringDashboard };

export type CategorySteeringCorpus = {
  id: string;
  name: string;
  role: string;
  itemCount?: number | null;
  generatedAt?: string | null;
  latestImportRunId?: string | null;
};

export type CategorySteeringImportRun = {
  id: string;
  corpusId: string;
  importKind: string;
  classifierId?: string | null;
  status: string;
  importedAt: string;
  itemCount?: number | null;
  categoryCount?: number | null;
  proposalCount?: number | null;
  referenceCount?: number | null;
  relationCount?: number | null;
  warningCount?: number | null;
};

export type CategorySteeringCategorySet = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
  versionState?: string | null;
  corpusId: string;
  classifierId: string;
  displayName: string;
  description?: string | null;
  status: string;
  generatedAt?: string | null;
  categoryCount?: number | null;
  importRunId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  nodeCount?: number | null;
  rootCount?: number | null;
};

export type CategorySteeringCategory = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
  previousVersionId?: string | null;
  versionState?: string | null;
  versionCreatedAt?: string | null;
  versionCreatedBy?: string | null;
  changeReason?: string | null;
  contentHash?: string | null;
  categorySetId: string;
  corpusId: string;
  categoryKey: string;
  parentCategoryId?: string | null;
  parentCategoryKey?: string | null;
  displayName: string;
  shortTitle?: string | null;
  subtitle?: string | null;
  description?: string | null;
  aliases?: Array<string | null> | null;
  status: string;
  seedItemIds?: Array<string | null> | null;
  holdoutItemIds?: Array<string | null> | null;
  rank?: number | null;
  depth?: number | null;
  isPinned?: boolean | null;
  importRunId?: string | null;
  updatedAt?: string | null;
};

export type CategorySteeringCategoryTree = CategorySteeringCategorySet;

export type CategorySteeringCategoryTreeNode = CategorySteeringCategory;

export type CategoryKeywordRecord = {
  id: string;
  categorySetId: string;
  corpusId: string;
  categoryKey: string;
  categoryLineageId?: string | null;
  categoryId?: string | null;
  keyword: string;
  normalizedKeyword: string;
  weight?: number | null;
  rank?: number | null;
  source: string;
  sourceTopicId?: string | null;
  importRunId?: string | null;
  metadata?: unknown;
  createdAt: string;
  updatedAt?: string | null;
};

export type LexicalSteeringRuleRecord = {
  id: string;
  ruleKind: string;
  term: string;
  normalizedTerm: string;
  scope: string;
  status: string;
  corpusId?: string | null;
  classifierId?: string | null;
  categorySetId?: string | null;
  categoryKey?: string | null;
  note?: string | null;
  source?: string | null;
  createdBy?: string | null;
  createdAt: string;
  updatedAt?: string | null;
  metadata?: unknown;
};

export type NewsroomSectionType = "canonical" | "floating" | "rotating";

export type NewsroomSectionRecord = {
  id: string;
  title: string;
  shortTitle: string;
  type: NewsroomSectionType;
  editorialMission: string;
  editorialPolicy: string;
  enabled: boolean;
  enabledStatus?: string | null;
  sortOrder: number;
  defaultArticleTypes?: Array<string | null> | null;
  defaultPageBudget?: number | null;
  assignmentGuidance?: string | null;
  killCriteria?: string | null;
  visualGuidance?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type ProcedureDefinitionRecord = {
  id: string;
  procedureKey: string;
  title: string;
  category: string;
  description?: string | null;
  enabled: boolean;
  enabledStatus?: string | null;
  currentVersionId?: string | null;
  createdBy?: string | null;
  createdAt?: string | null;
  updatedBy?: string | null;
  updatedAt?: string | null;
  newsroomFeedKey?: string | null;
};

export type ProcedureVersionRecord = {
  id: string;
  procedureId: string;
  procedureKey: string;
  versionNumber: number;
  status: string;
  isCurrent: boolean;
  label?: string | null;
  tactusSource: string;
  parameterSchema?: unknown;
  defaults?: unknown;
  changelog?: string | null;
  createdBy?: string | null;
  createdAt?: string | null;
  updatedBy?: string | null;
  updatedAt?: string | null;
};

export type ProcedureRunRecord = {
  id: string;
  procedureId: string;
  procedureKey: string;
  procedureVersionId: string;
  procedureVersionNumber?: number | null;
  assignmentId?: string | null;
  runStatus: string;
  requestedBy?: string | null;
  requestedAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  input?: unknown;
  normalizedInput?: unknown;
  resultSummary?: string | null;
  errorSummary?: string | null;
  output?: unknown;
  error?: unknown;
  attempt?: number | null;
  newsroomFeedKey?: string | null;
};

const DEFAULT_NEWSROOM_SECTIONS_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-newsroom-sections.yml");
const NEWSROOM_SECTION_TYPES = new Set<NewsroomSectionType>(["canonical", "floating", "rotating"]);
type NewsroomSectionSeedRow = Omit<NewsroomSectionRecord, "sortOrder" | "enabled" | "enabledStatus" | "createdAt" | "updatedAt"> & {
  enabled: boolean;
  sortOrder: number;
};
const newsroomSectionSeedRowsCache = new Map<string, NewsroomSectionSeedRow[]>();

export type SteeringProposal = {
  id: string;
  categorySetId?: string | null;
  corpusId: string;
  proposalKind: string;
  steeringDomain: string;
  status: string;
  title: string;
  summary?: string | null;
  categoryKey?: string | null;
  targetCategoryKey?: string | null;
  graphEntityId?: string | null;
  relationshipType?: string | null;
  displayName?: string | null;
  shortTitle?: string | null;
  subtitle?: string | null;
  description?: string | null;
  evidenceItemIds?: Array<string | null> | null;
  suggestedSeedItemIds?: Array<string | null> | null;
  suggestedHoldoutItemIds?: Array<string | null> | null;
  sourceSnapshotId?: string | null;
  proposedAt?: string | null;
  reviewedAt?: string | null;
  reviewedBy?: string | null;
  updatedAt?: string | null;
};

export type CategorySteeringProposal = SteeringProposal;

export type KnowledgeArtifact = {
  id: string;
  corpusId: string;
  artifactKind: string;
  artifactId: string;
  snapshotId?: string | null;
  displayName?: string | null;
  createdAt?: string | null;
};

export type CategorySteeringArtifact = KnowledgeArtifact;

export type ReferenceRecord = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
  previousVersionId?: string | null;
  versionState?: string | null;
  versionCreatedAt?: string | null;
  versionCreatedBy?: string | null;
  changeReason?: string | null;
  contentHash?: string | null;
  corpusId: string;
  externalItemId: string;
  title?: string | null;
  authors?: Array<string | null> | null;
  sourceUri?: string | null;
  storagePath?: string | null;
  mediaType?: string | null;
  byteSize?: number | null;
  sha256?: string | null;
  sourcePublishedAt?: string | null;
  sourceUpdatedAt?: string | null;
  retrievedAt?: string | null;
  inboundCitationCount?: number | null;
  outboundCitationCount?: number | null;
  importRunId?: string | null;
  importedAt?: string | null;
  createdAt?: string | null;
  curationStatus?: string | null;
  curationStatusKey?: string | null;
  curationStatusUpdatedAt?: string | null;
  curationStatusUpdatedBy?: string | null;
  curationStatusReason?: string | null;
  newsroomFeedKey?: string | null;
  reviewedFeedKey?: string | null;
  metadata?: unknown;
  updatedAt?: string | null;
};

export type ReferenceAttachmentRecord = {
  id: string;
  referenceId: string;
  referenceLineageId: string;
  referenceVersionNumber?: number | null;
  referenceVersionKey: string;
  role: string;
  sortKey: string;
  storagePath?: string | null;
  sourceUri?: string | null;
  filename?: string | null;
  mediaType?: string | null;
  byteSize?: number | null;
  sha256?: string | null;
  etag?: string | null;
  importRunId?: string | null;
  importedAt?: string | null;
  metadata?: unknown;
};

export type ModelAttachmentRecord = {
  id: string;
  ownerKind: string;
  ownerId: string;
  ownerLineageId?: string | null;
  ownerVersionNumber?: number | null;
  ownerVersionKey?: string | null;
  role: string;
  sortKey: string;
  storagePath: string;
  filename?: string | null;
  mediaType: string;
  byteSize?: number | null;
  sha256?: string | null;
  etag?: string | null;
  importRunId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  status?: string | null;
};

export type HydratedModelPayload = {
  attachment: ModelAttachmentRecord;
  text: string | null;
  json: unknown | null;
  error: string | null;
};

export type SemanticNodeRecord = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
  previousVersionId?: string | null;
  versionState?: string | null;
  versionCreatedAt?: string | null;
  versionCreatedBy?: string | null;
  changeReason?: string | null;
  contentHash?: string | null;
  nodeKey: string;
  nodeKind: string;
  corpusId?: string | null;
  categorySetId?: string | null;
  categoryLineageId?: string | null;
  categoryKey?: string | null;
  displayName?: string | null;
  description?: string | null;
  aliases?: Array<string | null> | null;
  authorityScore?: number | null;
  authorityRank?: number | null;
  acceptedReferenceMentionCount?: number | null;
  distinctSourceKindCount?: number | null;
  relationCount?: number | null;
  status: string;
  importRunId?: string | null;
  createdAt?: string | null;
  newsroomFeedKey?: string | null;
  updatedAt?: string | null;
};

export type SemanticRelationRecord = {
  id: string;
  relationState: string;
  predicate: string;
  relationTypeId?: string | null;
  relationTypeKey?: string | null;
  relationDomain?: string | null;
  subjectKind: string;
  subjectId: string;
  subjectLineageId: string;
  subjectVersionNumber?: number | null;
  objectKind: string;
  objectId: string;
  objectLineageId: string;
  objectVersionNumber?: number | null;
  subjectStateKey: string;
  objectStateKey: string;
  objectSubjectStateKey: string;
  predicateObjectStateKey: string;
  subjectVersionKey: string;
  objectVersionKey: string;
  score?: number | null;
  confidence?: number | null;
  rank?: number | null;
  classifierId?: string | null;
  modelVersion?: string | null;
  reviewRecommended?: boolean | null;
  sourceSnapshotId?: string | null;
  importRunId?: string | null;
  importedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  newsroomFeedKey?: string | null;
  metadata?: unknown;
};

export type MessageRecord = {
  id: string;
  messageKind: string;
  messageDomain: string;
  status: string;
  summary?: string | null;
  source?: string | null;
  importRunId?: string | null;
  authorSub?: string | null;
  authorUserProfileId?: string | null;
  authorLabel?: string | null;
  threadId?: string | null;
  parentMessageId?: string | null;
  sequenceNumber?: number | null;
  role?: string | null;
  messageType?: string | null;
  content?: string | null;
  semanticLayer?: string | null;
  searchVisibility?: string | null;
  responseTarget?: string | null;
  responseStatus?: string | null;
  responseOwner?: string | null;
  responseStartedAt?: string | null;
  responseCompletedAt?: string | null;
  responseError?: string | null;
  createdAt: string;
  updatedAt: string;
  newsroomFeedKey?: string | null;
  body?: string | null;
  metadata?: unknown;
};

export type MessageThreadRecord = {
  id: string;
  threadKind: string;
  status: string;
  title: string;
  summary?: string | null;
  primaryAnchorKind?: string | null;
  primaryAnchorId?: string | null;
  primaryAnchorLineageId?: string | null;
  primaryAnchorKey?: string | null;
  createdBySub?: string | null;
  createdByUserProfileId?: string | null;
  createdByLabel?: string | null;
  messageCount?: number | null;
  lastMessageId?: string | null;
  lastMessageAt?: string | null;
  contextDigest?: string | null;
  activeResponseMessageId?: string | null;
  responseLockOwner?: string | null;
  responseLockExpiresAt?: string | null;
  metadata?: unknown;
  createdAt: string;
  updatedAt: string;
  newsroomFeedKey?: string | null;
};

export type AssignmentRecord = {
  id: string;
  assignmentTypeKey: string;
  queueKey: string;
  queueStatusKey: string;
  status: string;
  priority?: number | null;
  title: string;
  summary?: string | null;
  brief?: string | null;
  instructions?: string | null;
  assigneeType?: string | null;
  assigneeId?: string | null;
  assigneeKey?: string | null;
  claimedAt?: string | null;
  claimExpiresAt?: string | null;
  completedAt?: string | null;
  canceledAt?: string | null;
  corpusId?: string | null;
  categorySetId?: string | null;
  classifierId?: string | null;
  sectionId?: string | null;
  sectionKey?: string | null;
  sectionType?: string | null;
  sectionStatusKey?: string | null;
  sectionQueueStatusKey?: string | null;
  primaryFocusCategoryKey?: string | null;
  topicScopeCategoryKeys?: Array<string | null> | null;
  sourceSnapshotId?: string | null;
  importRunId?: string | null;
  createdBy?: string | null;
  createdAt: string;
  updatedAt: string;
  newsroomFeedKey?: string | null;
  metadata?: unknown;
};

export type AssignmentEventRecord = {
  id: string;
  assignmentId: string;
  assignmentTypeKey: string;
  queueKey: string;
  eventType: string;
  fromStatus?: string | null;
  toStatus?: string | null;
  actorSub?: string | null;
  actorLabel?: string | null;
  note?: string | null;
  createdAt: string;
  metadata?: unknown;
};

export type EditionSlotRecord = {
  id: string;
  editionId: string;
  sectionKey: string;
  slotRank: number;
  targetType: "article" | "brief" | string;
  targetLengthBand?: string | null;
  minImageAssets?: number | null;
  status: "open" | "assigned" | "selected" | "briefed" | "filled" | "killed" | string;
  selectedAssignmentId?: string | null;
  metadata?: unknown;
  createdAt: string;
  updatedAt: string;
};

export type EditionRecord = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
  versionState?: string | null;
  slug?: string | null;
  title?: string | null;
  status?: string | null;
  editionDate?: string | null;
  publishedAt?: string | null;
  updatedAt?: string | null;
};

export type UserIdentityRecord = {
  id: string;
  userProfileId: string;
  cognitoSub: string;
  provider?: string | null;
  email?: string | null;
  status: string;
  linkedAt: string;
  lastSeenAt?: string | null;
};

export type UserDirectoryEntry = {
  userProfileId?: string | null;
  userSub?: string | null;
  username?: string | null;
  email?: string | null;
  displayName?: string | null;
  provider?: string | null;
  enabled?: boolean | null;
  cognitoStatus?: string | null;
  profileStatus?: string | null;
  mergedIntoProfileId?: string | null;
  identityStatus?: string | null;
  activeRoles: Array<string | null>;
  identities: UserIdentityRecord[];
};

export type DoctrineRecord = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
  versionState?: string | null;
  versionCreatedAt?: string | null;
  versionCreatedBy?: string | null;
  type: string;
  status: string;
  typeStatus: string;
  slug: string;
  title?: string | null;
  headline?: string | null;
  body?: Array<string | null> | null;
  editorial?: string | Record<string, unknown> | null;
  updatedAt?: string | null;
};

export type AnalysisProfileSummary = {
  key: string;
  title: string;
  description: string;
  scope: string;
  defaultMode: string;
  corpusKey?: string | null;
  classifierId?: string | null;
  configurationName?: string | null;
  biblicus: {
    extractor?: string | null;
    configurations: string[];
  };
  defaults: Record<string, unknown>;
  allowedOverrides: string[];
  expectedOutputs: string[];
};

export type NewsroomSummaryRecord = {
  generatedAt: string;
  staleAt?: string | null;
  source?: string | null;
  latestImportRun?: CategorySteeringImportRun | null;
  counts: Record<string, number>;
  facets?: NewsroomSummaryFacets | null;
  assignmentStatusCounts: Record<string, number>;
  assignmentTypeCounts: Record<string, number>;
  referenceStatusCounts: Record<string, number>;
  messageKindCounts: Record<string, number>;
  messageDomainCounts: Record<string, number>;
};

export type NewsroomSummaryFacets = {
  assignments?: {
    byStatus?: Record<string, number>;
    byType?: Record<string, number>;
    bySection?: Record<string, number>;
    statusByType?: Record<string, Record<string, number>>;
    statusBySection?: Record<string, Record<string, number>>;
    typeBySection?: Record<string, Record<string, number>>;
  };
  messages?: {
    byKind?: Record<string, number>;
    byDomain?: Record<string, number>;
    byStatus?: Record<string, number>;
    domainByKind?: Record<string, Record<string, number>>;
  };
  references?: {
    byCurationStatus?: Record<string, number>;
    byCorpus?: Record<string, number>;
    statusByCorpus?: Record<string, Record<string, number>>;
  };
  semanticNodes?: {
    byNodeKind?: Record<string, number>;
    byStatus?: Record<string, number>;
    byCorpus?: Record<string, number>;
    byCategorySet?: Record<string, number>;
  };
  semanticRelations?: {
    byRelationTypeKey?: Record<string, number>;
    byRelationDomain?: Record<string, number>;
    bySubjectKind?: Record<string, number>;
    byObjectKind?: Record<string, number>;
  };
  imports?: {
    byCorpus?: Record<string, number>;
  };
};

export type CategorySteeringDashboard = {
  isDemo?: boolean;
  isPublicSkeleton?: boolean;
  summaryStatus?: "loading" | "missing" | "ready";
  summary?: NewsroomSummaryRecord | null;
  canManageUsers?: boolean;
  canonicalCorpusId?: string | null;
  canonicalCategorySetId?: string | null;
  userDirectory: UserDirectoryEntry[];
  corpora: CategorySteeringCorpus[];
  importRuns: CategorySteeringImportRun[];
  categorySets: CategorySteeringCategorySet[];
  categorys: CategorySteeringCategory[];
  categoryTrees: CategorySteeringCategoryTree[];
  categoryNodes: CategorySteeringCategoryTreeNode[];
  categoryKeywords: CategoryKeywordRecord[];
  lexicalSteeringRules: LexicalSteeringRuleRecord[];
  proposals: CategorySteeringProposal[];
  artifacts: CategorySteeringArtifact[];
  references: ReferenceRecord[];
  referenceAttachments: ReferenceAttachmentRecord[];
  semanticNodes: SemanticNodeRecord[];
  messages: MessageRecord[];
  semanticRelations: SemanticRelationRecord[];
  assignments: AssignmentRecord[];
  assignmentEvents: AssignmentEventRecord[];
  editionSlots: EditionSlotRecord[];
  doctrineRecords: DoctrineRecord[];
  newsroomSections: NewsroomSectionRecord[];
  procedureDefinitions: ProcedureDefinitionRecord[];
  procedureVersions: ProcedureVersionRecord[];
  procedureRuns: ProcedureRunRecord[];
  loadError?: string | null;
};

const DEFAULT_ANALYSIS_PROFILES_PATH = path.join(process.cwd(), "corpora", "papyrus-analysis-profiles.yml");
const DEFAULT_STEERING_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-steering.yml");

export async function loadAnalysisProfileSummaries(filepath = DEFAULT_ANALYSIS_PROFILES_PATH): Promise<AnalysisProfileSummary[]> {
  try {
    const parsed = YAML.parse(fs.readFileSync(filepath, "utf8")) as {
      schemaVersion?: number;
      profiles?: Array<Record<string, unknown>>;
    } | null;
    if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.profiles)) return [];
    return parsed.profiles.map((entry) => ({
      key: stringValue(entry.key),
      title: stringValue(entry.title) || stringValue(entry.key),
      description: stringValue(entry.description),
      scope: stringValue(entry.scope),
      defaultMode: stringValue(entry.defaultMode),
      corpusKey: stringValue(entry.corpusKey) || null,
      classifierId: stringValue(entry.classifierId) || null,
      configurationName: stringValue(entry.configurationName) || null,
      biblicus: {
        extractor: stringValue(objectValue(entry.biblicus).extractor) || null,
        configurations: stringArray(objectValue(entry.biblicus).configurations),
      },
      defaults: objectValue(entry.defaults),
      allowedOverrides: stringArray(entry.allowedOverrides),
      expectedOutputs: stringArray(entry.expectedOutputs),
    })).filter((profile) => profile.key && profile.scope && profile.defaultMode);
  } catch {
    return [];
  }
}

export async function loadConfiguredCorpusSummaries(filepath = DEFAULT_STEERING_CONFIG_PATH): Promise<CategorySteeringCorpus[]> {
  try {
    const parsed = YAML.parse(fs.readFileSync(filepath, "utf8")) as {
      corpora?: Array<Record<string, unknown>>;
    } | null;
    if (!parsed || !Array.isArray(parsed.corpora)) return [];
    return parsed.corpora.map((entry) => {
      const key = stringValue(entry.key) || stringValue(entry.name);
      const name = stringValue(entry.name) || key;
      return {
        id: knowledgeCorpusIdFromKey(key),
        name,
        role: stringValue(entry.role) || "source",
      };
    }).filter((corpus) => corpus.id && corpus.name);
  } catch {
    return [];
  }
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function nullableStringValue(value: unknown): string | null {
  const normalized = stringValue(value);
  return normalized || null;
}

function integerValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : null;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(stringValue).filter(Boolean) : [];
}

function knowledgeCorpusIdFromKey(corpusKey: string): string {
  const safeKey = String(corpusKey || "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "unknown";
  return `knowledge-corpus-${safeKey}`;
}

export async function loadCategorySteeringDashboard(): Promise<CategorySteeringDashboard> {
  const proposals = await loadServerSteeringProposals();
  if (proposals.length === 0) return createEmptyCategorySteeringDashboard();
  return {
    ...createEmptyCategorySteeringDashboard(),
    isPublicSkeleton: false,
    proposals: sortProposals(proposals),
    loadError: null,
  };
}

const SERVER_STEERING_PROPOSALS_QUERY = `
  query ListSteeringProposals($limit: Int, $nextToken: String) {
    listSteeringProposals(limit: $limit, nextToken: $nextToken) {
      items {
        id
        categorySetId
        corpusId
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

async function loadServerSteeringProposals(): Promise<CategorySteeringProposal[]> {
  const endpoint = process.env.PAPYRUS_GRAPHQL_ENDPOINT;
  const jwt = process.env.PAPYRUS_GRAPHQL_JWT;
  if (!endpoint || !jwt) return [];

  const items: CategorySteeringProposal[] = [];
  let nextToken: string | null = null;

  for (let page = 0; page < 20; page += 1) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        Authorization: `Bearer ${jwt}`,
      },
      body: JSON.stringify({
        query: SERVER_STEERING_PROPOSALS_QUERY,
        variables: { limit: 500, nextToken },
      }),
      cache: "no-store",
    });
    if (!response.ok) return [];
    const payload = await response.json() as {
      data?: { listSteeringProposals?: { items?: Array<CategorySteeringProposal | null> | null; nextToken?: string | null } | null } | null;
      errors?: Array<{ message?: string }> | null;
    };
    if (payload.errors?.length) return [];
    const connection = payload.data?.listSteeringProposals;
    if (!connection) return [];
    items.push(...(connection.items ?? []).filter(Boolean) as CategorySteeringProposal[]);
    nextToken = connection.nextToken ?? null;
    if (!nextToken) break;
  }

  return items;
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

function selectCanonicalCategorySet(corpora: CategorySteeringCorpus[], categorySets: CategorySteeringCategorySet[]): CategorySteeringCategorySet | null {
  const canonicalCorpus = selectCanonicalCorpus(corpora);
  const candidates = categorySets.filter((categorySet) => categorySet.status !== "deprecated");
  const canonicalCandidates = canonicalCorpus ? candidates.filter((categorySet) => categorySet.corpusId === canonicalCorpus.id) : candidates;
  return canonicalCandidates[0] ?? candidates[0] ?? null;
}

function selectCanonicalCorpus(corpora: CategorySteeringCorpus[]): CategorySteeringCorpus | null {
  return corpora.find((corpus) => corpus.role === "canonical")
    ?? corpora.find((corpus) => corpus.role === "authority")
    ?? corpora[0]
    ?? null;
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

function defaultNewsroomSections(importedAt: string, sectionsConfigPath = DEFAULT_NEWSROOM_SECTIONS_CONFIG_PATH): NewsroomSectionRecord[] {
  return loadNewsroomSectionSeedRows(sectionsConfigPath).map((row, index) => ({
    ...row,
    enabledStatus: "enabled",
    sortOrder: Number.isInteger(row.sortOrder) && row.sortOrder > 0 ? row.sortOrder : index + 1,
    createdAt: importedAt,
    updatedAt: importedAt,
  }));
}

function loadNewsroomSectionSeedRows(sectionsConfigPath = DEFAULT_NEWSROOM_SECTIONS_CONFIG_PATH) {
  const cached = newsroomSectionSeedRowsCache.get(sectionsConfigPath);
  if (cached) return cached;
  const parsed = YAML.parse(fs.readFileSync(sectionsConfigPath, "utf8")) as {
    schemaVersion?: number;
    sections?: Array<Record<string, unknown>>;
  };
  if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.sections)) {
    throw new Error(`Invalid newsroom section seed file: ${sectionsConfigPath}`);
  }
  const rows = parsed.sections.map((entry, index) => normalizeNewsroomSectionSeedRow(entry, index, sectionsConfigPath));
  newsroomSectionSeedRowsCache.set(sectionsConfigPath, rows);
  return rows;
}

function normalizeNewsroomSectionSeedRow(
  entry: Record<string, unknown>,
  index: number,
  sectionsConfigPath: string,
): Omit<NewsroomSectionRecord, "enabledStatus" | "createdAt" | "updatedAt"> {
  const id = stringValue(entry.id);
  if (!id) throw new Error(`Newsroom section at index ${index} is missing id in ${sectionsConfigPath}`);
  const title = stringValue(entry.title);
  if (!title) throw new Error(`Newsroom section '${id}' is missing title in ${sectionsConfigPath}`);
  const shortTitle = stringValue(entry.shortTitle);
  if (!shortTitle) throw new Error(`Newsroom section '${id}' is missing shortTitle in ${sectionsConfigPath}`);
  const rawType = stringValue(entry.type).toLowerCase() as NewsroomSectionType;
  if (!NEWSROOM_SECTION_TYPES.has(rawType)) {
    throw new Error(`Newsroom section '${id}' has unsupported type '${stringValue(entry.type)}' in ${sectionsConfigPath}`);
  }
  const type = rawType === "rotating" ? "floating" : rawType;
  const editorialMission = stringValue(entry.editorialMission);
  const editorialPolicy = stringValue(entry.editorialPolicy);
  if (!editorialMission || !editorialPolicy) {
    throw new Error(`Newsroom section '${id}' requires editorialMission and editorialPolicy in ${sectionsConfigPath}`);
  }
  return {
    id,
    title,
    shortTitle,
    type,
    editorialMission,
    editorialPolicy,
    enabled: typeof entry.enabled === "boolean" ? entry.enabled : true,
    sortOrder: integerValue(entry.sortOrder) ?? index + 1,
    defaultArticleTypes: stringArray(entry.defaultArticleTypes),
    defaultPageBudget: integerValue(entry.defaultPageBudget),
    assignmentGuidance: nullableStringValue(entry.assignmentGuidance),
    killCriteria: nullableStringValue(entry.killCriteria),
    visualGuidance: nullableStringValue(entry.visualGuidance),
  };
}

export function createDemoCategorySteeringDashboard(
  brandId: SiteBrandId = resolveSiteBrandId(),
  newsroomSectionsConfigPath = DEFAULT_NEWSROOM_SECTIONS_CONFIG_PATH,
): CategorySteeringDashboard {
  const importedAt = "2026-05-16T12:00:00.000Z";
  const profile = getNewsroomDemoProfile(brandId);
  const pilobolus = isPilobolusDemoBrand(brandId);
  const corpusId = "knowledge-corpus-demo-canonical";
  const sourceCorpusId = "knowledge-corpus-demo-source";
  const categorySetId = "category-set-demo-canonical";
  const sourceCategorySetId = "category-set-demo-source";
  const referenceHistoryOneLineageId = "reference-knowledge-corpus-demo-source-history-001";
  const referenceHistoryTwoLineageId = "reference-knowledge-corpus-demo-source-history-002";
  const referenceHistoryOneId = `${referenceHistoryOneLineageId}-v1`;
  const referenceHistoryTwoId = `${referenceHistoryTwoLineageId}-v1`;
  const assignmentHistoryOneId = "assignment-demo-reference-intake-history-001";
  const assignmentHistoryTwoId = "assignment-demo-reference-intake-history-002";
  const assignmentReportingId = "assignment-demo-reporting-news-001";
  const reportingPacketMessageId = "message-demo-reporting-news-001-context";
  const scalingCategoryLineageId = "category-category-set-demo-canonical-category-foundation-model-scaling";
  const historyCategoryLineageId = "category-category-set-demo-source-category-symbolic-connectionist-history";

  const dashboard: CategorySteeringDashboard = {
    isDemo: true,
    summary: null,
    canManageUsers: true,
    canonicalCorpusId: corpusId,
    canonicalCategorySetId: categorySetId,
    userDirectory: [
      {
        userProfileId: "user-profile-demo-editor",
        userSub: "demo-editor-sub",
        username: "demo-editor",
        email: "editor@example.com",
        displayName: "Demo Editor",
        provider: "google",
        enabled: true,
        cognitoStatus: "CONFIRMED",
        identityStatus: "active",
        activeRoles: ["editor"],
        identities: [
          {
            id: "user-identity-demo-editor-google",
            userProfileId: "user-profile-demo-editor",
            cognitoSub: "demo-editor-sub",
            provider: "google",
            email: "editor@example.com",
            status: "active",
            linkedAt: importedAt,
            lastSeenAt: importedAt,
          },
          {
            id: "user-identity-demo-editor-alt",
            userProfileId: "user-profile-demo-editor",
            cognitoSub: "demo-editor-alt-sub",
            provider: "google",
            email: "editor.alt@example.com",
            status: "active",
            linkedAt: importedAt,
            lastSeenAt: importedAt,
          },
        ],
      },
      {
        userProfileId: "user-profile-demo-reader",
        userSub: "demo-reader-sub",
        username: "demo-reader",
        email: "reader@example.com",
        displayName: "Demo Reader",
        provider: "google",
        enabled: true,
        cognitoStatus: "CONFIRMED",
        identityStatus: "active",
        activeRoles: [],
        identities: [
          {
            id: "user-identity-demo-reader-google",
            userProfileId: "user-profile-demo-reader",
            cognitoSub: "demo-reader-sub",
            provider: "google",
            email: "reader@example.com",
            status: "active",
            linkedAt: importedAt,
            lastSeenAt: importedAt,
          },
        ],
      },
    ],
    corpora: [
      {
        id: corpusId,
        name: profile.canonicalCorpusName,
        role: "canonical",
        itemCount: 3,
        latestImportRunId: "knowledge-import-demo-steering",
      },
      {
        id: sourceCorpusId,
        name: profile.sourceCorpusName,
        role: "source",
        itemCount: 2,
        latestImportRunId: "knowledge-import-demo-projection",
      },
    ],
    importRuns: [
      {
        id: "knowledge-import-demo-steering",
        corpusId,
        importKind: "steering-export",
        classifierId: "demo-canonical-classifier",
        status: "imported",
        importedAt,
        itemCount: 3,
        categoryCount: 1,
        proposalCount: 5,
        referenceCount: 3,
        relationCount: 0,
        warningCount: 0,
      },
      {
        id: "knowledge-import-demo-projection",
        corpusId: sourceCorpusId,
        importKind: "topic-projection",
        classifierId: "demo-canonical-classifier",
        status: "imported",
        importedAt,
        itemCount: 2,
        categoryCount: 0,
        proposalCount: 0,
        referenceCount: 2,
        relationCount: 2,
        warningCount: 0,
      },
    ],
    categorySets: [
      {
        id: categorySetId,
        lineageId: categorySetId,
        versionNumber: 1,
        versionState: "current",
        corpusId,
        classifierId: "demo-canonical-classifier",
        displayName: "Canonical Demo Categories",
        description: "Accepted category set imported from Biblicus artifacts.",
        status: "accepted",
        generatedAt: importedAt,
        categoryCount: 1,
        importRunId: "knowledge-import-demo-steering",
      },
      {
        id: sourceCategorySetId,
        lineageId: sourceCategorySetId,
        versionNumber: 1,
        versionState: "current",
        corpusId: sourceCorpusId,
        classifierId: "demo-source-classifier",
        displayName: "Source Demo Categories",
        description: "Local category set discovered inside the source corpus.",
        status: "accepted",
        generatedAt: importedAt,
        categoryCount: 1,
        importRunId: "knowledge-import-demo-projection",
      },
    ],
    categorys: [
      {
        id: "category-foundation-model-scaling",
        categorySetId,
        corpusId,
        categoryKey: "category.foundation-model-scaling",
        displayName: pilobolus ? "Ensemble Movement Studies" : "Foundation Model Scaling",
        subtitle: pilobolus
          ? "Rehearsal notes, ensemble patterns, and field documentation"
          : "Capability curves, benchmark saturation, and training-compute effects",
        description: pilobolus
          ? "Movement research, rehearsal capture, and ensemble coordination notes from the Pilobolus field program."
          : "Research on model size, data mixtures, compute budgets, and emergent benchmark behavior.",
        aliases: pilobolus ? ["ensemble work", "movement studies"] : ["scaling laws", "compute scaling"],
        status: "accepted",
        seedItemIds: ["research-001", "research-002"],
        holdoutItemIds: ["research-003"],
        rank: 1,
        isPinned: true,
        updatedAt: importedAt,
      },
      {
        id: "category-symbolic-connectionist-history",
        categorySetId: sourceCategorySetId,
        corpusId: sourceCorpusId,
        categoryKey: "category.symbolic-connectionist-history",
        displayName: pilobolus ? "Rehearsal Archive" : "Symbolic And Connectionist History",
        subtitle: pilobolus
          ? "Season logs, tour notes, and creative process records"
          : "Shifts between rule systems, neural nets, and hybrid AI programs",
        description: pilobolus
          ? "Historical rehearsal logs, tour documentation, and creative-process notes for Pilobolus editions."
          : "Historical coverage of symbolic AI, neural network winters, and later hybrid systems.",
        aliases: pilobolus ? ["tour archive", "season notes"] : ["AI winters", "connectionism"],
        status: "accepted",
        seedItemIds: ["history-001"],
        holdoutItemIds: ["history-002"],
        rank: 2,
        isPinned: false,
        updatedAt: importedAt,
      },
    ],
    categoryTrees: [
      {
        id: categorySetId,
        lineageId: categorySetId,
        versionNumber: 1,
        versionState: "current",
        corpusId,
        classifierId: "demo-canonical-classifier",
        displayName: "Canonical Demo Category Tree",
        description: "Accepted category tree imported from Biblicus category artifacts.",
        status: "accepted",
        generatedAt: importedAt,
        categoryCount: 3,
        nodeCount: 3,
        rootCount: 1,
        importRunId: "knowledge-import-demo-steering",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
    ],
    categoryNodes: [
      {
        id: "category-demo-foundation-model-scaling",
        corpusId,
        categorySetId,
        categoryKey: "category.foundation-model-scaling",
        parentCategoryKey: null,
        displayName: "Foundation Model Scaling",
        subtitle: "Capability curves, benchmark saturation, and training-compute effects",
        description: "Accepted root category for model size, data mixtures, compute budgets, and emergent benchmark behavior.",
        status: "accepted",
        seedItemIds: ["research-001", "research-002"],
        holdoutItemIds: ["research-003"],
        rank: 1,
        depth: 0,
        importRunId: "knowledge-import-demo-steering",
        updatedAt: importedAt,
      },
      {
        id: "category-demo-agent-memory",
        corpusId,
        categorySetId,
        categoryKey: "category.agent-memory",
        parentCategoryKey: "category.foundation-model-scaling",
        displayName: "Agent Memory",
        subtitle: "Retrieval, persistence, and episodic context for agent systems",
        description: "Accepted subcategory covering long-running memory, retrieval augmentation, and context persistence in agent workflows.",
        status: "accepted",
        seedItemIds: ["research-001"],
        holdoutItemIds: [],
        rank: 1,
        depth: 1,
        importRunId: "knowledge-import-demo-steering",
        updatedAt: importedAt,
      },
      {
        id: "category-demo-benchmark-saturation",
        corpusId,
        categorySetId,
        categoryKey: "category.benchmark-saturation",
        parentCategoryKey: "category.foundation-model-scaling",
        displayName: "Benchmark Saturation",
        subtitle: "Evaluation plateaus, leakage, and capability measurement stress",
        description: "Accepted subcategory covering benchmark exhaustion and the need for new evaluation signals.",
        status: "accepted",
        seedItemIds: ["research-002"],
        holdoutItemIds: ["research-003"],
        rank: 2,
        depth: 1,
        importRunId: "knowledge-import-demo-steering",
        updatedAt: importedAt,
      },
    ],
    categoryKeywords: [
      {
        id: "category-keyword-demo-scaling-001",
        categorySetId,
        corpusId,
        categoryKey: "category.foundation-model-scaling",
        categoryLineageId: scalingCategoryLineageId,
        categoryId: "category-demo-foundation-model-scaling",
        keyword: "scaling laws",
        normalizedKeyword: "scaling laws",
        weight: 0.92,
        rank: 1,
        source: "accepted-category-tree",
        sourceTopicId: "category.foundation-model-scaling",
        importRunId: "knowledge-import-demo-steering",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
      {
        id: "category-keyword-demo-scaling-002",
        categorySetId,
        corpusId,
        categoryKey: "category.foundation-model-scaling",
        categoryLineageId: scalingCategoryLineageId,
        categoryId: "category-demo-foundation-model-scaling",
        keyword: "et",
        normalizedKeyword: "et",
        weight: 0.41,
        rank: 2,
        source: "accepted-category-tree",
        sourceTopicId: "category.foundation-model-scaling",
        importRunId: "knowledge-import-demo-steering",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
      {
        id: "category-keyword-demo-memory-001",
        categorySetId,
        corpusId,
        categoryKey: "category.agent-memory",
        categoryLineageId: "category-category-set-demo-canonical-category-agent-memory",
        categoryId: "category-demo-agent-memory",
        keyword: "agent memory",
        normalizedKeyword: "agent memory",
        weight: 0.87,
        rank: 1,
        source: "steering-proposal",
        sourceTopicId: "category-proposal-demo-create-category",
        importRunId: "knowledge-import-demo-steering",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
    ],
    lexicalSteeringRules: [
      {
        id: "lexical-rule-demo-et",
        ruleKind: "ignored_keyword",
        term: "et",
        normalizedTerm: "et",
        scope: "publication",
        status: "active",
        note: "Citation/header noise from et al.",
        source: "papyrus-lexical-steering.yml",
        createdBy: "papyrus-config",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
      {
        id: "lexical-rule-demo-al",
        ruleKind: "ignored_keyword",
        term: "al",
        normalizedTerm: "al",
        scope: "publication",
        status: "active",
        note: "Citation/header noise from et al.",
        source: "papyrus-lexical-steering.yml",
        createdBy: "papyrus-config",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
    ],
    proposals: [
      {
        id: "category-proposal-demo-rename",
        categorySetId,
        corpusId,
        proposalKind: "rename-category",
        steeringDomain: "category",
        status: "proposed",
        title: "Rename scaling category",
        summary: "Several seed items use foundation model scaling terminology more consistently than generic scaling laws.",
        categoryKey: "category.foundation-model-scaling",
        displayName: "Foundation Model Scaling",
        subtitle: "Capability curves, benchmark saturation, and training-compute effects",
        evidenceItemIds: ["research-001", "research-002"],
        suggestedSeedItemIds: ["research-001"],
        proposedAt: importedAt,
      },
      {
        id: "category-proposal-demo-relationship",
        categorySetId,
        corpusId,
        proposalKind: "relationship-proposal",
        steeringDomain: "graph",
        status: "proposed",
        title: "Link scaling category to benchmark entity",
        summary: "Evidence suggests the category should relate to the benchmark-saturation entity.",
        categoryKey: "category.foundation-model-scaling",
        graphEntityId: "graph-entity-benchmark-saturation",
        relationshipType: "influences",
        evidenceItemIds: ["research-002"],
        proposedAt: importedAt,
      },
      {
        id: "category-proposal-demo-create-category",
        categorySetId,
        corpusId,
        proposalKind: "create-category",
        steeringDomain: "category",
        status: "proposed",
        title: "Create agent memory subcategory",
        summary: "Discovery found a possible child category under the foundation model scaling area.",
        categoryKey: "category.agent-memory",
        targetCategoryKey: "category.foundation-model-scaling",
        relationshipType: "subcategory_of",
        displayName: "Agent Memory",
        description: "Candidate subcategory covering memory, retrieval, and persistence in agent systems.",
        evidenceItemIds: ["research-001"],
        proposedAt: importedAt,
      },
      {
        id: "category-proposal-demo-ontology-relationship",
        categorySetId,
        corpusId,
        proposalKind: "add-ontology-relationship",
        steeringDomain: "graph",
        status: "proposed",
        title: "Add ontology assertion",
        summary: "The evidence supports a historical context relationship between two category nodes.",
        categoryKey: "category.symbolic-connectionist-history",
        targetCategoryKey: "category.agent-memory",
        graphEntityId: "assertion-agent-memory-history",
        relationshipType: "historical_context_for",
        evidenceItemIds: ["history-001"],
        proposedAt: importedAt,
      },
      {
        id: "category-proposal-demo-seeds",
        categorySetId,
        corpusId,
        proposalKind: "seed-change",
        steeringDomain: "category",
        status: "deferred",
        title: "Add history article as holdout",
        summary: "The item is useful as a negative example for modern scaling categories.",
        categoryKey: "category.foundation-model-scaling",
        suggestedHoldoutItemIds: ["history-002"],
        evidenceItemIds: ["history-002"],
        proposedAt: importedAt,
      },
    ],
    artifacts: [
      {
        id: "knowledge-artifact-demo-category-set",
        corpusId,
        artifactKind: "accepted-category-set",
        artifactId: "s3://papyrus-demo/accepted-category-set.json",
        snapshotId: "snapshot-demo-category-set",
        displayName: "Accepted Category Set JSON",
        createdAt: importedAt,
      },
    ],
    references: [
      {
        id: referenceHistoryOneId,
        lineageId: referenceHistoryOneLineageId,
        versionNumber: 1,
        versionState: "current",
        corpusId: sourceCorpusId,
        externalItemId: "history-001",
        title: "Symbolic And Connectionist History Reader",
        sourceUri: "s3://papyrus-demo/corpora/history/history-001.md",
        storagePath: "corpora/history/history-001.md",
        mediaType: "text/markdown",
        sha256: "demo-history-001",
        importRunId: "knowledge-import-demo-projection",
        importedAt,
        curationStatus: "accepted",
        curationStatusKey: `${sourceCorpusId}#accepted`,
        curationStatusUpdatedAt: importedAt,
        curationStatusUpdatedBy: "demo-import",
      },
      {
        id: referenceHistoryTwoId,
        lineageId: referenceHistoryTwoLineageId,
        versionNumber: 1,
        versionState: "current",
        corpusId: sourceCorpusId,
        externalItemId: "history-002",
        title: "Foundation Model Scaling Retrospective",
        sourceUri: "s3://papyrus-demo/corpora/history/history-002.md",
        storagePath: "corpora/history/history-002.md",
        mediaType: "text/markdown",
        sha256: "demo-history-002",
        importRunId: "knowledge-import-demo-projection",
        importedAt,
        curationStatus: "pending",
        curationStatusKey: `${sourceCorpusId}#pending`,
        curationStatusUpdatedAt: importedAt,
        curationStatusUpdatedBy: "demo-import",
      },
    ],
    referenceAttachments: [
      {
        id: "reference-attachment-demo-history-001-source",
        referenceId: referenceHistoryOneId,
        referenceLineageId: referenceHistoryOneLineageId,
        referenceVersionNumber: 1,
        referenceVersionKey: `reference#${referenceHistoryOneId}`,
        role: "source",
        sortKey: "001-source",
        storagePath: "corpora/history/history-001.md",
        sourceUri: "s3://papyrus-demo/corpora/history/history-001.md",
        filename: "history-001.md",
        mediaType: "text/markdown",
        sha256: "demo-history-001",
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "reference-attachment-demo-history-002-source",
        referenceId: referenceHistoryTwoId,
        referenceLineageId: referenceHistoryTwoLineageId,
        referenceVersionNumber: 1,
        referenceVersionKey: `reference#${referenceHistoryTwoId}`,
        role: "source",
        sortKey: "001-source",
        storagePath: "corpora/history/history-002.md",
        sourceUri: "s3://papyrus-demo/corpora/history/history-002.md",
        filename: "history-002.md",
        mediaType: "text/markdown",
        sha256: "demo-history-002",
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "reference-attachment-demo-history-001-extracted-text",
        referenceId: referenceHistoryOneId,
        referenceLineageId: referenceHistoryOneLineageId,
        referenceVersionNumber: 1,
        referenceVersionKey: `reference#${referenceHistoryOneId}`,
        role: "extracted_text",
        sortKey: "900-extracted-text",
        storagePath: "corpora/history/extracted/pipeline/snapshot-demo-history/text/history-001.txt",
        filename: "history-001.txt",
        mediaType: "text/plain",
        sha256: "demo-history-001-extracted-text",
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "reference-attachment-demo-history-002-deepgram",
        referenceId: referenceHistoryTwoId,
        referenceLineageId: referenceHistoryTwoLineageId,
        referenceVersionNumber: 1,
        referenceVersionKey: `reference#${referenceHistoryTwoId}`,
        role: "deepgram",
        sortKey: "002-deepgram",
        storagePath: "corpora/history/history-002.deepgram.json",
        filename: "history-002.deepgram.json",
        mediaType: "application/json",
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
    ],
    semanticNodes: [
      {
        id: "semantic-node-graph-entity-benchmark-saturation-v1",
        lineageId: "semantic-node-graph-entity-benchmark-saturation",
        versionNumber: 1,
        versionState: "current",
        nodeKey: "graph-entity-benchmark-saturation",
        nodeKind: "entity",
        corpusId,
        displayName: "Benchmark Saturation",
        status: "accepted",
        importRunId: "knowledge-import-demo-steering",
        updatedAt: importedAt,
      },
      {
        id: "semantic-node-comment-ingestion-rationale-v1",
        lineageId: "semantic-node-comment-ingestion-rationale",
        versionNumber: 1,
        versionState: "current",
        nodeKey: "comment.ingestion_rationale",
        nodeKind: "commentConcept",
        corpusId: sourceCorpusId,
        displayName: "Ingestion Rationale",
        status: "accepted",
        importRunId: "knowledge-import-demo-projection",
        updatedAt: importedAt,
      },
    ],
    messages: [
      {
        id: "message-demo-history-002-rationale",
        messageKind: "ingestion_rationale",
        messageDomain: "commentary",
        status: "active",
        body: "Imported as a useful holdout against modern scaling coverage.",
        summary: "Holdout ingestion rationale",
        source: "biblicus-import",
        importRunId: "knowledge-import-demo-projection",
        createdAt: importedAt,
        updatedAt: importedAt,
      },
      {
        id: reportingPacketMessageId,
        messageKind: "reporting_context_packet",
        messageDomain: "assignment_work",
        status: "active",
        body: "Context packet for a section-ready News candidate. Editors can select, merge, brief, hold, or kill this packet without creating reader copy.",
        summary: "Reporting context packet: model-release accountability angle",
        source: "procedures/newsroom/reporter.tac",
        importRunId: "knowledge-import-demo-projection",
        authorLabel: "newsroom-reporter",
        createdAt: importedAt,
        updatedAt: importedAt,
        metadata: {
          kind: "reporting.context_packet.created",
          assignmentId: assignmentReportingId,
          reporting: {
            sectionKey: "news",
            editionId: "edition-demo-planning-v1",
            candidateRank: 1,
            editorRecommendation: "hold",
            recommendedAngle: "Focus on accountability for model-release claims.",
            acceptedReferenceIds: [referenceHistoryTwoId],
            proposedReferences: [],
            riskFlags: ["Avoid promotional framing."],
            coverageGaps: ["Need a second independent source."],
            openQuestions: ["Which users are affected first?"],
            copywriterBrief: "Use accepted evidence and recent desk memory before drafting.",
          },
        },
      },
    ],
    assignments: [
      {
        id: assignmentReportingId,
        assignmentTypeKey: "reporting.edition-candidate",
        queueKey: "edition:edition-demo:section:news:lane:reporting",
        queueStatusKey: "edition:edition-demo:section:news:lane:reporting#open",
        status: "open",
        priority: 20,
        title: "News reporting candidate 1: Model release accountability",
        summary: "Create reporting context for a candidate News article; do not create a draft Item until editor selection.",
        brief: "Report a section-ready candidate for News, option 1.",
        instructions: "Return a private reporting context packet only. Distinguish accepted references from proposed references.",
        corpusId,
        categorySetId,
        classifierId: "demo-canonical-classifier",
        sectionId: "news",
        sectionKey: "news",
        sectionType: "canonical",
        sectionStatusKey: "news#open",
        sectionQueueStatusKey: "news#edition:edition-demo:section:news:lane:reporting#open",
        primaryFocusCategoryKey: "category.foundation-model-scaling",
        topicScopeCategoryKeys: ["category.foundation-model-scaling"],
        importRunId: "knowledge-import-demo-projection",
        createdBy: "papyrus-content-cli",
        createdAt: importedAt,
        updatedAt: importedAt,
        metadata: {
          editionId: "edition-demo-planning-v1",
          editionSlug: "edition-demo",
          sectionKey: "news",
          sectionTitle: "News",
          candidateRank: 1,
          slotTarget: { sectionKey: "news", slots: 1, candidateRank: 1 },
          expectedOutput: "Private reporting context packet for editor selection and copywriting, not reader copy.",
        },
      },
      {
        id: assignmentHistoryOneId,
        assignmentTypeKey: "curation.reference-intake",
        queueKey: `curation.reference-intake#${sourceCorpusId}`,
        queueStatusKey: `curation.reference-intake#${sourceCorpusId}#open`,
        status: "open",
        priority: 40,
        title: "Curate reference: Symbolic And Connectionist History Reader",
        brief: "Review this knowledge-base reference and add durable curation notes or semantic links.",
        instructions: "Inspect linked private corpus attachments; write findings as messages, semantic relations, or proposals.",
        corpusId: sourceCorpusId,
        categorySetId,
        classifierId: "demo-canonical-classifier",
        importRunId: "knowledge-import-demo-projection",
        createdBy: "biblicus-import",
        createdAt: importedAt,
        updatedAt: importedAt,
        metadata: { referenceLineageId: referenceHistoryOneLineageId, externalItemId: "history-001" },
      },
      {
        id: assignmentHistoryTwoId,
        assignmentTypeKey: "curation.reference-intake",
        queueKey: `curation.reference-intake#${sourceCorpusId}`,
        queueStatusKey: `curation.reference-intake#${sourceCorpusId}#claimed`,
        status: "claimed",
        priority: 50,
        title: "Curate reference: Foundation Model Scaling Retrospective",
        brief: "Review this reference because it has a review-recommended category projection.",
        instructions: "Check whether the weak scaling classification deserves a message, proposal, or relation.",
        assigneeType: "agent",
        assigneeId: "archivist-demo",
        assigneeKey: "agent#archivist-demo",
        claimedAt: importedAt,
        corpusId: sourceCorpusId,
        categorySetId,
        classifierId: "demo-canonical-classifier",
        importRunId: "knowledge-import-demo-projection",
        createdBy: "biblicus-import",
        createdAt: importedAt,
        updatedAt: importedAt,
        metadata: { referenceLineageId: referenceHistoryTwoLineageId, externalItemId: "history-002" },
      },
    ],
    assignmentEvents: [
      {
        id: "assignment-event-demo-history-002-claimed",
        assignmentId: assignmentHistoryTwoId,
        assignmentTypeKey: "curation.reference-intake",
        queueKey: `curation.reference-intake#${sourceCorpusId}`,
        eventType: "claim",
        fromStatus: "open",
        toStatus: "claimed",
        actorLabel: "archivist-demo",
        createdAt: importedAt,
      },
    ],
    editionSlots: [
      {
        id: "edition-slot-demo-news-01",
        editionId: "edition-demo-weekly-v1",
        sectionKey: "news",
        slotRank: 1,
        targetType: "article",
        targetLengthBand: "standard",
        minImageAssets: 1,
        status: "open",
        selectedAssignmentId: null,
        metadata: { source: "demo" },
        createdAt: importedAt,
        updatedAt: importedAt,
      },
    ],
    newsroomSections: defaultNewsroomSections(importedAt, newsroomSectionsConfigPath),
    procedureDefinitions: [],
    procedureVersions: [],
    procedureRuns: [],
    doctrineRecords: [
      {
        id: "item-editorial-doctrine-mission-v1",
        lineageId: "item-editorial-doctrine-mission",
        versionNumber: 1,
        versionState: "current",
        versionCreatedAt: importedAt,
        versionCreatedBy: "demo-editor",
        type: "doctrine",
        status: "private",
        typeStatus: "doctrine#private",
        slug: "editorial-doctrine-mission",
        title: "Editorial Mission",
        body: [
          "Papyrus publishes bounded editions that help readers understand what changed, why it matters, and what remains uncertain.",
          "Coverage should be accurate, source-disciplined, and legible about evidence quality and editorial judgment.",
        ],
        editorial: { kind: "mission" },
        updatedAt: importedAt,
      },
      {
        id: "item-editorial-doctrine-policy-v1",
        lineageId: "item-editorial-doctrine-policy",
        versionNumber: 1,
        versionState: "current",
        versionCreatedAt: importedAt,
        versionCreatedBy: "demo-editor",
        type: "doctrine",
        status: "private",
        typeStatus: "doctrine#private",
        slug: "editorial-doctrine-policy",
        title: "Editorial Policy",
        body: [
          "Publication doctrine is the global inclusion standard; desk doctrine sets local source priorities and framing.",
          "News reporting should prioritize current, journalistic, and official sources; desk workflows may use academic research as background unless a desk policy explicitly makes research the primary evidence class.",
          "High-risk domains, including health-related claims, require stricter sourcing, explicit uncertainty handling, and clear separation between verified facts and interpretation.",
        ],
        editorial: { kind: "policy" },
        updatedAt: importedAt,
      },
    ],
    semanticRelations: [
      {
        id: "semantic-relation-demo-reporting-context-comment",
        relationState: "current",
        predicate: "comment",
        relationTypeKey: "comment",
        relationDomain: "commentary",
        subjectKind: "message",
        subjectId: reportingPacketMessageId,
        subjectLineageId: reportingPacketMessageId,
        objectKind: "assignment",
        objectId: assignmentReportingId,
        objectLineageId: assignmentReportingId,
        subjectStateKey: `message#${reportingPacketMessageId}#current`,
        objectStateKey: `assignment#${assignmentReportingId}#current`,
        objectSubjectStateKey: `assignment#${assignmentReportingId}#current#message`,
        predicateObjectStateKey: `comment#assignment#${assignmentReportingId}#current`,
        subjectVersionKey: `message#${reportingPacketMessageId}`,
        objectVersionKey: `assignment#${assignmentReportingId}`,
        rank: 1,
        reviewRecommended: false,
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "semantic-relation-demo-assignment-history-001",
        relationState: "current",
        predicate: "requests_work_on",
        subjectKind: "assignment",
        subjectId: assignmentHistoryOneId,
        subjectLineageId: assignmentHistoryOneId,
        objectKind: "reference",
        objectId: referenceHistoryOneId,
        objectLineageId: referenceHistoryOneLineageId,
        objectVersionNumber: 1,
        subjectStateKey: `assignment#${assignmentHistoryOneId}#current`,
        objectStateKey: `reference#${referenceHistoryOneLineageId}#current`,
        objectSubjectStateKey: `reference#${referenceHistoryOneLineageId}#current#assignment`,
        predicateObjectStateKey: `requests_work_on#reference#${referenceHistoryOneLineageId}#current`,
        subjectVersionKey: `assignment#${assignmentHistoryOneId}`,
        objectVersionKey: `reference#${referenceHistoryOneId}`,
        rank: 1,
        reviewRecommended: true,
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "semantic-relation-demo-assignment-history-002",
        relationState: "current",
        predicate: "requests_work_on",
        subjectKind: "assignment",
        subjectId: assignmentHistoryTwoId,
        subjectLineageId: assignmentHistoryTwoId,
        objectKind: "reference",
        objectId: referenceHistoryTwoId,
        objectLineageId: referenceHistoryTwoLineageId,
        objectVersionNumber: 1,
        subjectStateKey: `assignment#${assignmentHistoryTwoId}#current`,
        objectStateKey: `reference#${referenceHistoryTwoLineageId}#current`,
        objectSubjectStateKey: `reference#${referenceHistoryTwoLineageId}#current#assignment`,
        predicateObjectStateKey: `requests_work_on#reference#${referenceHistoryTwoLineageId}#current`,
        subjectVersionKey: `assignment#${assignmentHistoryTwoId}`,
        objectVersionKey: `reference#${referenceHistoryTwoId}`,
        rank: 1,
        reviewRecommended: true,
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "semantic-relation-demo-history-001",
        relationState: "current",
        predicate: "classified_as",
        subjectKind: "reference",
        subjectId: referenceHistoryOneId,
        subjectLineageId: referenceHistoryOneLineageId,
        subjectVersionNumber: 1,
        objectKind: "category",
        objectId: `${historyCategoryLineageId}-v1`,
        objectLineageId: historyCategoryLineageId,
        objectVersionNumber: 1,
        subjectStateKey: `reference#${referenceHistoryOneLineageId}#current`,
        objectStateKey: `category#${historyCategoryLineageId}#current`,
        objectSubjectStateKey: `category#${historyCategoryLineageId}#current#reference`,
        predicateObjectStateKey: `classified_as#category#${historyCategoryLineageId}#current`,
        subjectVersionKey: `reference#${referenceHistoryOneId}`,
        objectVersionKey: `category#${historyCategoryLineageId}-v1`,
        score: 0.91,
        rank: 1,
        classifierId: "demo-canonical-classifier",
        reviewRecommended: false,
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "semantic-relation-demo-history-002",
        relationState: "current",
        predicate: "classified_as",
        subjectKind: "reference",
        subjectId: referenceHistoryTwoId,
        subjectLineageId: referenceHistoryTwoLineageId,
        subjectVersionNumber: 1,
        objectKind: "category",
        objectId: `${scalingCategoryLineageId}-v1`,
        objectLineageId: scalingCategoryLineageId,
        objectVersionNumber: 1,
        subjectStateKey: `reference#${referenceHistoryTwoLineageId}#current`,
        objectStateKey: `category#${scalingCategoryLineageId}#current`,
        objectSubjectStateKey: `category#${scalingCategoryLineageId}#current#reference`,
        predicateObjectStateKey: `classified_as#category#${scalingCategoryLineageId}#current`,
        subjectVersionKey: `reference#${referenceHistoryTwoId}`,
        objectVersionKey: `category#${scalingCategoryLineageId}-v1`,
        score: 0.58,
        rank: 1,
        classifierId: "demo-canonical-classifier",
        reviewRecommended: true,
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
      {
        id: "semantic-relation-demo-message-history-002-rationale",
        relationState: "current",
        predicate: "comment",
        relationTypeId: "semantic-relation-type-comment",
        relationTypeKey: "comment",
        relationDomain: "commentary",
        subjectKind: "message",
        subjectId: "message-demo-history-002-rationale",
        subjectLineageId: "message-demo-history-002-rationale",
        subjectVersionNumber: 1,
        objectKind: "reference",
        objectId: referenceHistoryTwoId,
        objectLineageId: referenceHistoryTwoLineageId,
        objectVersionNumber: 1,
        subjectStateKey: "message#message-demo-history-002-rationale#current",
        objectStateKey: `reference#${referenceHistoryTwoLineageId}#current`,
        objectSubjectStateKey: `reference#${referenceHistoryTwoLineageId}#current#message`,
        predicateObjectStateKey: `comment#reference#${referenceHistoryTwoLineageId}#current`,
        subjectVersionKey: "message#message-demo-history-002-rationale",
        objectVersionKey: `reference#${referenceHistoryTwoId}`,
        rank: 1,
        reviewRecommended: false,
        importRunId: "knowledge-import-demo-projection",
        importedAt,
      },
    ],
    loadError: null,
  };

  if (pilobolus) {
    return applyPilobolusDemoDashboardContent(dashboard, profile);
  }

  return dashboard;
}
