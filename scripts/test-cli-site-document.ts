import assert from "node:assert/strict";
import { handleSiteDocument } from "../lib/cli-site-document";

async function serve(environment: { PAPYRUS_TENANT_ID?: string; PAPYRUS_ENGINE_VERSION?: string }) {
  const response = handleSiteDocument(environment);
  return { status: response.status, cache: response.headers.get("cache-control"), body: await response.json() as Record<string, unknown> };
}

const behaviours: Record<string, () => Promise<unknown>> = {
  async tenant_and_version() {
    const result = await serve({ PAPYRUS_TENANT_ID: "machines-on-machines", PAPYRUS_ENGINE_VERSION: "5.81.0" });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, { tenant_id: "machines-on-machines", papyrus_version: "5.81.0" });
    assert.equal(result.cache, "public, max-age=300");
    return result;
  },
  async no_tenant() {
    const result = await serve({ PAPYRUS_ENGINE_VERSION: "5.81.0" });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, { papyrus_version: "5.81.0" });
    assert.ok(!("tenant_id" in result.body), "a site with no tenant publishes none");
    return result;
  },
  async blank_tenant() {
    const result = await serve({ PAPYRUS_TENANT_ID: "  ", PAPYRUS_ENGINE_VERSION: "5.81.0" });
    assert.deepEqual(result.body, { papyrus_version: "5.81.0" });
    return result;
  },
  async invalid_values_are_left_out() {
    const result = await serve({ PAPYRUS_TENANT_ID: "Not A Tenant", PAPYRUS_ENGINE_VERSION: "latest" });
    assert.deepEqual(result.body, {});
    return result;
  },
};

async function main() {
  const requested = process.argv[2];
  if (requested) {
    if (!behaviours[requested]) throw new Error(`unknown behaviour ${requested}`);
    console.log(JSON.stringify(await behaviours[requested]()));
    return;
  }
  for (const run of Object.values(behaviours)) await run();
  console.log("cli-site-document ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
