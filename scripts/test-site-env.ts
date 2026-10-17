import assert from "node:assert/strict";
import {
  analyticsAllowed,
  assertContentSourceMatchesEnv,
  getContentSource,
  getSiteEnv,
  isIndexable,
  showStagingBanner,
} from "../lib/site-env";

type Case = { env: Record<string, string | undefined>; siteEnv: string };

const siteEnvCases: Case[] = [
  { env: {}, siteEnv: "development" },
  { env: { SITE_ENV: "" }, siteEnv: "development" },
  { env: { SITE_ENV: "development" }, siteEnv: "development" },
  { env: { SITE_ENV: "staging" }, siteEnv: "staging" },
  { env: { SITE_ENV: "staging", AWS_BRANCH: "main" }, siteEnv: "staging" },
  { env: { SITE_ENV: "production" }, siteEnv: "production" },
  { env: { SITE_ENV: "production", AWS_BRANCH: "main" }, siteEnv: "production" },
  { env: { SITE_ENV: "production", AWS_BRANCH: "staging" }, siteEnv: "staging" },
  { env: { SITE_ENV: "production", AWS_BRANCH: "develop" }, siteEnv: "staging" },
];

for (const { env, siteEnv } of siteEnvCases) {
  assert.equal(getSiteEnv(env), siteEnv, JSON.stringify(env));
  assert.equal(isIndexable(env), siteEnv === "production", `isIndexable ${JSON.stringify(env)}`);
  assert.equal(analyticsAllowed(env), siteEnv === "production", `analytics ${JSON.stringify(env)}`);
  assert.equal(showStagingBanner(env), siteEnv === "staging", `banner ${JSON.stringify(env)}`);
}

assert.throws(() => getSiteEnv({ SITE_ENV: "prod" }), /SITE_ENV must be one of/);
assert.throws(() => getContentSource({ PAPYRUS_CONTENT_SOURCE: "draft" }), /PAPYRUS_CONTENT_SOURCE must be one of/);
assert.equal(getContentSource({}), "published");
assert.equal(getContentSource({ PAPYRUS_CONTENT_SOURCE: "drafts" }), "drafts");

assertContentSourceMatchesEnv({});
assertContentSourceMatchesEnv({ SITE_ENV: "production" });
assertContentSourceMatchesEnv({ SITE_ENV: "production", PAPYRUS_CONTENT_SOURCE: "published" });
assertContentSourceMatchesEnv({ SITE_ENV: "staging", PAPYRUS_CONTENT_SOURCE: "published" });
assertContentSourceMatchesEnv({ SITE_ENV: "staging", PAPYRUS_CONTENT_SOURCE: "drafts" });
assert.throws(
  () => assertContentSourceMatchesEnv({ SITE_ENV: "production", PAPYRUS_CONTENT_SOURCE: "drafts" }),
  /requires SITE_ENV=staging/,
);
assert.throws(
  () => assertContentSourceMatchesEnv({ SITE_ENV: "development", PAPYRUS_CONTENT_SOURCE: "drafts" }),
  /requires SITE_ENV=staging/,
);
assert.throws(
  () => assertContentSourceMatchesEnv({ PAPYRUS_CONTENT_SOURCE: "drafts" }),
  /requires SITE_ENV=staging/,
);

console.log("site-env tests passed");
