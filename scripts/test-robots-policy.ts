import assert from "node:assert/strict";
import { buildRobots } from "../lib/robots-policy";
import { getSiteBrand } from "../lib/site-brand";

const readerBrand = getSiteBrand();
const newsroomBrand = { ...readerBrand, rootRoute: { kind: "newsroom" as const }, newsroomBasePath: "" };

const disallowAll = { rules: { userAgent: "*", disallow: "/" } };
const allowAll = { rules: { userAgent: "*", allow: "/" } };

assert.deepEqual(buildRobots({ SITE_ENV: "staging" }, readerBrand), disallowAll);
assert.deepEqual(buildRobots({ SITE_ENV: "development" }, readerBrand), disallowAll);
assert.deepEqual(buildRobots({}, readerBrand), disallowAll);
assert.deepEqual(buildRobots({ SITE_ENV: "production", AWS_BRANCH: "staging" }, readerBrand), disallowAll);
assert.deepEqual(buildRobots({ SITE_ENV: "production" }, readerBrand), allowAll);
assert.deepEqual(buildRobots({ SITE_ENV: "production", AWS_BRANCH: "main" }, readerBrand), allowAll);
assert.deepEqual(buildRobots({ SITE_ENV: "staging" }, newsroomBrand), disallowAll);
assert.deepEqual(buildRobots({ SITE_ENV: "production" }, newsroomBrand), disallowAll);

console.log("robots policy tests passed");
