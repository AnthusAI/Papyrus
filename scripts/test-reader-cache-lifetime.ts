import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { READER_PAGE_REVALIDATE_SECONDS } from "../lib/reader-cache-lifetime";
import {
  REVALIDATE_DISTRIBUTION_IDS_ENV,
  revalidateDistributionEnvironment,
  revalidateInvalidationStatement,
  validateRevalidateDistributionIds,
} from "../amplify/revalidate-invalidation-settings";
import { addInvalidationPathAlarm, WEEKLY_INVALIDATION_PATH_THRESHOLD } from "../amplify/publication/invalidation-alarm";
import { READER_EXPIRE_TIME_SECONDS } from "../packages/papyrus/src/with-papyrus.mjs";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";

function routeFiles(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(directory, entry.name);
    return entry.isDirectory() ? routeFiles(full) : /\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

const declared = routeFiles("app").flatMap((file) => {
  const match = /export const revalidate = (\S+);/.exec(fs.readFileSync(file, "utf8"));
  return match ? [{ file, value: match[1] }] : [];
});
assert.ok(declared.length >= 7, "the reader routes declare a revalidate");
for (const { file, value } of declared) {
  assert.equal(value, String(READER_PAGE_REVALIDATE_SECONDS), `${file} must revalidate every ${READER_PAGE_REVALIDATE_SECONDS} s`);
}

assert.equal(READER_EXPIRE_TIME_SECONDS, 2 * READER_PAGE_REVALIDATE_SECONDS, "stale-while-revalidate equals the page lifetime");
assert.deepEqual(validateRevalidateDistributionIds(undefined, undefined), []);
assert.deepEqual(validateRevalidateDistributionIds(["E2QW8WOFWQT0H4"], "https://reader.example"), []);
assert.match(validateRevalidateDistributionIds(["E2QW8WOFWQT0H4"], undefined).join("|"), /requires revalidateBaseUrl/);
assert.match(validateRevalidateDistributionIds([], "https://reader.example").join("|"), /non-empty/);
assert.match(validateRevalidateDistributionIds(["arn:aws:cloudfront::1:distribution/E1"], "https://r").join("|"), /not a CloudFront distribution id/);
assert.deepEqual(revalidateDistributionEnvironment(["EAAAAAAAAA", "EBBBBBBBBB"]), { [REVALIDATE_DISTRIBUTION_IDS_ENV]: "EAAAAAAAAA,EBBBBBBBBB" });
assert.deepEqual(revalidateInvalidationStatement({ partition: "aws", account: "111122223333", distributionIds: ["EAAAAAAAAA", "EBBBBBBBBB"] }), {
  actions: ["cloudfront:CreateInvalidation"],
  resources: [
    "arn:aws:cloudfront::111122223333:distribution/EAAAAAAAAA",
    "arn:aws:cloudfront::111122223333:distribution/EBBBBBBBBB",
  ],
});

const stack = new Stack(new App(), "AlarmHarness");
addInvalidationPathAlarm(stack, "Alarm", "EAAAAAAAAA");
Template.fromStack(stack).hasResourceProperties("AWS::CloudWatch::Alarm", {
  Threshold: WEEKLY_INVALIDATION_PATH_THRESHOLD,
  Period: 604800,
  Dimensions: [{ Name: "DistributionId", Value: "EAAAAAAAAA" }],
});
console.log("reader cache lifetime ok");
