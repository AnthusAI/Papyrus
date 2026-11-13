import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { referenceFeedKeys, starFeedKeyFor, type ReferenceFeedKeyInput } from "../lib/reference-feed-keys";
import { corpusIdForKey, corpusKeyOf, globalKey, isCorpusId, keyTenant, ownCorpora, tenantCorpusId, TenantKeyError } from "../lib/tenant-knowledge-keys";

type TenantVector = {
  name: string;
  mode: "dedicated" | "shared";
  tenantId: string | null;
  environmentTenantId: string | null;
  call: "globalKey" | "corpusId" | "corpusIdForKey" | "corpusKeyOf" | "feedKeys" | "starFeedKey";
  input: unknown;
  key?: unknown;
  refused?: true;
};
const vectors = (JSON.parse(readFileSync(join(process.cwd(), "scripts/fixtures/reference-feed-key-vectors.json"), "utf8")) as { tenant: TenantVector[] }).tenant;

function run(vector: TenantVector): unknown {
  const environment: Record<string, string | undefined> = {};
  if (vector.mode === "shared") environment.PAPYRUS_TENANCY_MODE = "shared";
  if (vector.environmentTenantId) environment.PAPYRUS_TENANT_ID = vector.environmentTenantId;
  switch (vector.call) {
    case "globalKey": return globalKey(vector.input as string, vector.tenantId, environment);
    case "corpusId": return tenantCorpusId(vector.input as string, vector.tenantId, environment);
    case "corpusIdForKey": return corpusIdForKey(vector.input as string, vector.tenantId, environment);
    case "corpusKeyOf": return corpusKeyOf(vector.input as string);
    case "feedKeys": {
      const found = referenceFeedKeys(vector.input as ReferenceFeedKeyInput) as Record<string, unknown>;
      return Object.fromEntries(Object.entries(found).filter(([name]) => name in (vector.key as object)));
    }
    case "starFeedKey": {
      const { corpusId, stars } = vector.input as { corpusId: string; stars: number };
      return starFeedKeyFor(corpusId, stars);
    }
  }
}

for (const vector of vectors) {
  if (vector.refused) assert.throws(() => run(vector), Error, vector.name);
  else assert.deepEqual(run(vector), vector.key, vector.name);
}

// A shared stack with no tenant names what to pass, as the error the twin raises.
assert.throws(() => keyTenant(undefined, { PAPYRUS_TENANCY_MODE: "shared" }), (error: unknown) => error instanceof TenantKeyError && /PAPYRUS_TENANT_ID/.test(error.message));
// A dedicated stack never reads or validates a tenant, so a fixed tenant id changes nothing.
assert.equal(keyTenant("not a tenant", { PAPYRUS_TENANT_ID: "alpha" }), undefined);
assert.equal(globalKey("references", "alpha", { PAPYRUS_TENANT_ID: "alpha" }), "references");
console.log(`tenant knowledge key vectors: ${vectors.length} cases pass`);

// A shared stack keeps only the tenant's own corpus rows when it looks for its canonical corpus; a dedicated stack keeps every row.
const rows = [{ id: "alpha.knowledge-corpus-a" }, { id: "beta.knowledge-corpus-b" }];
assert.deepEqual(ownCorpora(rows, "alpha", { PAPYRUS_TENANCY_MODE: "shared" }), [{ id: "alpha.knowledge-corpus-a" }]);
assert.deepEqual(ownCorpora(rows, "alpha", {}), rows);
assert.throws(() => ownCorpora(rows, undefined, { PAPYRUS_TENANCY_MODE: "shared" }), TenantKeyError);
assert.equal(isCorpusId("alpha.knowledge-corpus-a") && isCorpusId("knowledge-corpus-a") && !isCorpusId("alpha.a"), true);
