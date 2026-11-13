/**
 * How each index partition field of the schema relates to tenants (PPY-cd5926). Declared once here, checked against the schema by
 * scripts/generate-tenant-key-inventory.ts and scripts/test-tenant-key-inventory.ts: a field named here that no index partitions on any more
 * fails the check, and so does an index whose partition field is not named here, so a new index cannot ship unclassified.
 *
 * A field is classified by what its stored value is, not by its model:
 *
 *   tenant-prefixed  the stored value already starts with `<tenant>#` (or is the tenant id itself). Only the five tenant models are written this
 *                    way (src/papyrus_content/tenancy.py: TENANT_SCOPED_INDEX_FIELDS, TENANT_SLUG_FIELD) plus `tenantId` on the tenancy records.
 *   corpus-prefixed  the stored value is a corpus id or starts with `<corpusId>#`. Tenant-safe once corpus ids are unique across tenants. A
 *                    partition holds one corpus; `corpusId` itself is spread over the tenant's own corpora (spread `parent`, below).
 *   record-id        the stored value is, or is built from, another record's id. Tenant-safe because ids are unique, but one partition holds the
 *                    rows of one record, so it cannot list a tenant.
 *   global           any value shared across tenants: a constant, an enum, a slug, a person, a free-form key.
 *
 * `spread` is how many partitions one tenant's rows fall into: `one` (a constant or the tenant id), `closed` (a fixed set the caller can name, such
 * as a status), `parent` (one partition per record of a parent model the tenant owns, named in `parent`: a corpus id is one partition per
 * KnowledgeCorpus), `open` (a value per record, slug, person or key). A tenant can be listed by an index whose class is tenant-prefixed or global and
 * whose spread is one or closed: query its single partition, or each value of its closed set, with the tenant prefix on. An index whose spread is
 * `parent` lists a tenant when the parent model can be listed by tenant: list the tenant's parents, then query one partition per parent.
 */
export type KeyClass = "tenant-prefixed" | "corpus-prefixed" | "record-id" | "global";
export type Spread = "one" | "closed" | "parent" | "open";
/** `parent` names the model whose records are the partitions; it is set exactly when `spread` is `parent`. */
export type FieldClass = { class: KeyClass; spread: Spread; parent?: string };

export const KEY_CLASSES: KeyClass[] = ["tenant-prefixed", "corpus-prefixed", "record-id", "global"];

const tenantPrefixed = (spread: Spread): FieldClass => ({ class: "tenant-prefixed", spread });
const corpus: FieldClass = { class: "corpus-prefixed", spread: "open" };
const perCorpus: FieldClass = { class: "corpus-prefixed", spread: "parent", parent: "KnowledgeCorpus" };
const recordId: FieldClass = { class: "record-id", spread: "open" };
const constant: FieldClass = { class: "global", spread: "one" };
const closed: FieldClass = { class: "global", spread: "closed" };
const open: FieldClass = { class: "global", spread: "open" };

export const PARTITION_FIELD_CLASSES: Record<string, FieldClass> = {
  // tenant-prefixed: "<tenant>#..." written by the client (tenancy.py), or the tenant id itself.
  tenantId: tenantPrefixed("one"),
  typeStatus: tenantPrefixed("closed"),
  headStageKey: tenantPrefixed("closed"),
  sectionStatus: tenantPrefixed("open"),
  tenantSlug: tenantPrefixed("open"),
  languageGroupId: tenantPrefixed("open"),   // the primary Story's lineage id (src/papyrus_content/item_language.py)

  // corpus-prefixed: "<corpusId>" or "<corpusId>#..." (src/papyrus_content/reference_feed_keys.py and the knowledge import keys).
  // The corpus id itself: one partition per corpus, and a tenant's corpora are its own KnowledgeCorpus rows.
  corpusId: perCorpus,
  corpusImportKindKey: corpus,
  curationStatusKey: corpus,
  feedStateKey: corpus,
  starFeedKey: corpus,
  mediumFeedKey: corpus,
  contentNeededKey: corpus,

  // record-id: another record's id, alone or inside a composite such as "reference#<lineage>#current".
  accountId: recordId,
  assignmentId: recordId,
  authorUserProfileId: recordId,
  categorySetId: recordId,
  categorySetLineageId: recordId,
  documentId: recordId,
  discoveredByMonitorId: recordId,
  editionId: recordId,
  editionLineageId: recordId,
  importRunId: recordId,
  itemId: recordId,
  itemLineageId: recordId,
  lineageId: recordId,
  objectStateKey: recordId,
  objectSubjectStateKey: recordId,
  ownerId: recordId,
  ownerVersionKey: recordId,
  parentCategoryId: recordId,
  parentLineageId: recordId,
  predicateObjectStateKey: recordId,
  primaryAnchorKey: recordId,
  procedureId: recordId,
  proposalId: recordId,
  publishedCategorySetId: recordId,
  publishedEditionId: recordId,
  publishedItemId: recordId,
  readerId: recordId,
  referenceLineageId: recordId,
  referenceVersionKey: recordId,
  storyLineageId: recordId,
  subjectStateKey: recordId,
  subjectVersionKey: recordId,
  tagId: recordId,
  target: recordId,
  threadId: recordId,
  userProfileId: recordId,

  // global, one partition: a constant.
  newsroomFeedKey: constant,
  reviewedFeedKey: constant,

  // global, closed set: an enum or a fixed list of kinds.
  artifactKind: closed,
  assignmentTypeKey: closed,
  curationStatus: closed,
  domain: closed,
  enabledStatus: closed,
  eventType: closed,
  importKind: closed,
  messageDomain: closed,
  messageKind: closed,
  moderation: closed,
  relationDomain: closed,
  relationTypeKey: closed,
  responseTarget: closed,
  role: closed,
  runStatus: closed,
  scheduleState: closed,
  scope: closed,
  searchVisibility: closed,
  semanticLayer: closed,
  stage: closed,
  state: closed,
  stateKey: closed,
  status: closed,
  steeringDomain: closed,
  threadKind: closed,
  type: closed,
  versionState: closed,

  // global, open: a slug, a person, a name or a composite of keys, shared by every tenant that uses the same text.
  assigneeKey: open,
  authorSub: open,
  categoryKey: open,
  classifierId: open,
  cognitoSub: open,
  createdBySub: open,
  email: open,
  form: open,
  grantorSub: open,
  key: open,
  nodeKey: open,
  normalizedKeyword: open,
  parentCategoryKey: open,
  procedureKey: open,
  publicHandle: open,
  queueKey: open,
  queueStatusKey: open,
  sectionKey: open,
  sectionQueueStatusKey: open,
  sectionStatusKey: open,
  slug: open,
  sortOrder: open,
  storagePath: open,
  userSub: open,
};
