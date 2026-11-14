const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
// Each scenario's checks live in scripts/test-story-open-reads.ts (node:test, a fake backend that records every query).
const runTest = async (name) => {
  const { stdout } = await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "--test-name-pattern", name, "scripts/test-story-open-reads.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 });
  assert.match(stdout, /ℹ fail 0/, stdout);
  assert.doesNotMatch(stdout, /ℹ pass 0/, `no test matched ${name}`);
};
const step = (pattern, name) => Then(pattern, { timeout: 120_000 }, async function () { await runTest(name); });

Given("a story with three saved versions", function () {});
When("an editor opens its oldest version", function () {});
step("the console asks for the newest version with one indexed read of one row", "newest version with one indexed read");
step("it does not load the story's reporting trail to find it", "newest version with one indexed read");

Given("a story with one cited Reference in a site with thousands of other relations", function () {});
When("the References tab loads", function () {});
step("it shows the cited Reference with its role", "subject-state index, not a scan");
step("it read the relations keyed by the story and never paged through the relation table", "subject-state index, not a scan");
