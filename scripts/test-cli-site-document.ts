import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { handleSiteDocument, type SiteOutputs } from "../lib/cli-site-document";

// Obviously made-up values: the bucket and pool of a fictional site.
const OUTPUTS: SiteOutputs = {
  storage: { bucket_name: "example-site-media-bucket" },
  auth: { identity_pool_id: "us-east-1:00000000-0000-4000-8000-000000000000" },
};

async function serve(environment: Parameters<typeof handleSiteDocument>[0] & object, outputs: SiteOutputs | null = null) {
  const response = handleSiteDocument(environment, () => outputs);
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
  async media_bucket_and_identity_pool() {
    const result = await serve({ PAPYRUS_TENANT_ID: "machines-on-machines", PAPYRUS_ENGINE_VERSION: "5.81.0" }, OUTPUTS);
    assert.deepEqual(result.body, {
      tenant_id: "machines-on-machines",
      papyrus_version: "5.81.0",
      media_bucket: "example-site-media-bucket",
      identity_pool_id: "us-east-1:00000000-0000-4000-8000-000000000000",
    });
    return result;
  },
  async no_outputs_file() {
    const result = await serve({ PAPYRUS_ENGINE_VERSION: "5.81.0" }, null);
    assert.deepEqual(result.body, { papyrus_version: "5.81.0" });
    return result;
  },
  async outputs_without_storage() {
    const result = await serve({ PAPYRUS_ENGINE_VERSION: "5.81.0" }, { auth: { identity_pool_id: OUTPUTS.auth?.identity_pool_id } });
    assert.deepEqual(result.body, { papyrus_version: "5.81.0", identity_pool_id: "us-east-1:00000000-0000-4000-8000-000000000000" });
    return result;
  },
  async malformed_outputs_values_are_left_out() {
    const result = await serve({ PAPYRUS_ENGINE_VERSION: "5.81.0" }, { storage: { bucket_name: "Not A Bucket!" }, auth: { identity_pool_id: "pool" } });
    assert.deepEqual(result.body, { papyrus_version: "5.81.0" });
    return result;
  },
  async console_url_is_the_console_origin_plus_the_newsroom_path() {
    const own = await serve({ PAPYRUS_SITE_ORIGIN: "https://news.example.test", PAPYRUS_CONSOLE_ORIGIN: "https://newsroom.news.example.test", newsroomBasePath: "/newsroom" });
    assert.deepEqual(own.body, { console_url: "https://newsroom.news.example.test/newsroom" });
    const same = await serve({ PAPYRUS_SITE_ORIGIN: "https://news.example.test", newsroomBasePath: "/newsroom" });
    assert.deepEqual(same.body, { console_url: "https://news.example.test/newsroom" }, "without a console host the console is on the site's own host");
    const root = await serve({ PAPYRUS_CONSOLE_ORIGIN: "https://newsroom.example.test", newsroomBasePath: "" });
    assert.deepEqual(root.body, { console_url: "https://newsroom.example.test" }, "a console-only host mounts the newsroom at its root");
    return own;
  },
  async console_url_is_left_out_when_the_origin_is_unknown_or_unsafe() {
    for (const environment of [{ newsroomBasePath: "/newsroom" }, { PAPYRUS_SITE_ORIGIN: "http://news.example.test", newsroomBasePath: "/newsroom" },
      { PAPYRUS_SITE_ORIGIN: "https://news.example.test/path?x=1", newsroomBasePath: "/newsroom" }, { PAPYRUS_SITE_ORIGIN: "https://user@news.example.test", newsroomBasePath: "/newsroom" },
      { PAPYRUS_SITE_ORIGIN: "https://news.example.test", newsroomBasePath: "/news room" }]) {
      const result = await serve(environment);
      assert.ok(!("console_url" in result.body), JSON.stringify(environment));
    }
    return {};
  },
  async unreadable_outputs_do_not_fail() {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), "site-document-"));
    const file = path.join(directory, "amplify_outputs.json");
    fs.writeFileSync(file, "{ not json");
    process.env.PAPYRUS_AMPLIFY_OUTPUTS = file;
    try {
      const response = handleSiteDocument({ PAPYRUS_ENGINE_VERSION: "5.81.0" });
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { papyrus_version: "5.81.0" });
    } finally {
      delete process.env.PAPYRUS_AMPLIFY_OUTPUTS;
      fs.rmSync(directory, { recursive: true, force: true });
    }
    return {};
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
