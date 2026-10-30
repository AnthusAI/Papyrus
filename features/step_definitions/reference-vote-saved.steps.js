const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
// scripts/test-reference-review-api.ts runs the real curation handler and passes its responses through the newsroom's check.
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-reference-review-api.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};

Given("a pending Reference in the newsroom", function () {});
for (const when of [
  "an editor accepts it without writing why",
  "an editor accepts it and writes why",
  "the save response names another Reference, or says it was not saved",
]) When(when, function () {});
for (const then of [
  "the newsroom reports the accept as saved",
  "no Message and no relation were written",
  "the newsroom says the vote was not saved",
]) Then(then, async function () { assert.match(await run(), /fail 0/); });
