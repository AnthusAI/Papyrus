/**
 * The one builder of the keys the knowledge models carry their tenant in (PPY-ce6207). Python twin: src/papyrus_content/tenant_knowledge_keys.py;
 * both are tested against the `tenant` cases of scripts/fixtures/reference-feed-key-vectors.json.
 *
 * A DEDICATED stack never changes a key, even with a fixed tenant id. A SHARED stack puts the tenant in front of a global key value
 * (`<tenant>#references`) and makes a corpus id `<tenant>.<corpus>`; keys that start with a corpus id are tenant-safe from there. A shared
 * stack asked for a key with no tenant throws: nothing defaults to a tenant, and nothing falls back to the unprefixed key.
 * Writers and readers both build through these functions.
 */
import { isSharedStack, tenantIdFromEnvironment, validateTenantId } from "./tenant-keys";

export const CORPUS_SEPARATOR = ".";
export const KNOWLEDGE_CORPUS_PREFIX = "knowledge-corpus-";
const TENANT_KEY_SEPARATOR = "#";
const TENANT_CORPUS = /^[a-z0-9][a-z0-9-]{0,62}\.(?=knowledge-corpus-)/;

export const REFERENCE_FEED_KEY = "references";
export const REFERENCE_REVIEWED_FEED_KEY = "references#reviewed";
export const SEMANTIC_NODE_FEED_KEY = "semanticNodes";
export const SEMANTIC_RELATION_FEED_KEY = "semanticRelations";
export const REFERENCE_LINK_FEED_KEY = "reference-links";

type Environment = Record<string, string | undefined>;

export class TenantKeyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TenantKeyError";
  }
}

/** The tenant that prefixes keys on this stack: undefined on a dedicated stack (keys never change), the validated tenant on a shared one. */
export function keyTenant(tenantId?: string | null, environment: Environment = process.env): string | undefined {
  if (!isSharedStack(environment)) return undefined;
  const tenant = tenantId || tenantIdFromEnvironment(environment);
  if (!tenant) {
    throw new TenantKeyError("A shared stack builds no knowledge key without a tenant: name the tenant (the call's tenant context or PAPYRUS_TENANT_ID).");
  }
  return validateTenantId(tenant);
}

/** A key value that is the same for every tenant today (a feed name), as this stack stores it: `<tenant>#<value>` on a shared stack. */
export function globalKey(value: string, tenantId?: string | null, environment: Environment = process.env): string {
  const tenant = keyTenant(tenantId, environment);
  if (tenant === undefined) return value;
  const prefix = `${tenant}${TENANT_KEY_SEPARATOR}`;
  return value.startsWith(prefix) ? value : `${prefix}${value}`;
}

/** A corpus id as this stack stores it: unchanged on a dedicated stack, `<tenant>.<corpus id>` on a shared one. */
export function tenantCorpusId(corpusId: string, tenantId?: string | null, environment: Environment = process.env): string {
  const tenant = keyTenant(tenantId, environment);
  if (tenant === undefined) return corpusId;
  const prefix = `${tenant}${CORPUS_SEPARATOR}`;
  return corpusId.startsWith(prefix) ? corpusId : `${prefix}${corpusId}`;
}

/** The corpus key a stored corpus id names: the tenant and `knowledge-corpus-` removed. Pure: needs no mode. */
export function corpusKeyOf(corpusId: string): string {
  const bare = corpusId.replace(TENANT_CORPUS, "");
  return bare.startsWith(KNOWLEDGE_CORPUS_PREFIX) ? bare.slice(KNOWLEDGE_CORPUS_PREFIX.length) : bare;
}

/** The stored corpus id of a corpus key: `knowledge-corpus-<key>`, tenant-prefixed on a shared stack. */
export function corpusIdForKey(corpusKey: string, tenantId?: string | null, environment: Environment = process.env): string {
  return tenantCorpusId(`${KNOWLEDGE_CORPUS_PREFIX}${corpusKey}`, tenantId, environment);
}

/** The corpus rows that belong to this stack's tenant: every row on a dedicated stack, only `<tenant>.<corpus id>` rows on a shared one. */
export function ownCorpora<Row extends { id?: string | null }>(rows: Row[], tenantId?: string | null, environment: Environment = process.env): Row[] {
  const tenant = keyTenant(tenantId, environment);
  if (tenant === undefined) return rows;
  const prefix = `${tenant}${CORPUS_SEPARATOR}`;
  return rows.filter((row) => (row.id ?? "").startsWith(prefix));
}

/** True for a stored corpus id in either form (so a command can tell an id from a key). */
export function isCorpusId(value: string): boolean {
  return value.replace(TENANT_CORPUS, "").startsWith(KNOWLEDGE_CORPUS_PREFIX);
}
