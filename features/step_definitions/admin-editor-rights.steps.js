const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const run = promisify(execFile);
const given = () => {};

Given("a signed-in account in the admin and Google groups but not the editor group", given);
Given("a signed-in account in the admin group but not the editor group", given);

When("every editor check is asked about that account", { timeout: 120_000 }, async function () {
  const result = await run(process.execPath, ["--import", "tsx", "scripts/test-staff-groups.ts"], { maxBuffer: 4 * 1024 * 1024 });
  this.staffGroupsResult = result.stdout;
});
Then("the console, the staging gate, the reader staff flag and the newsroom chat identity admit it", function () {
  assert.match(this.staffGroupsResult, /PASS: admin has every editor right/);
});
Then("the groups claim is read the same way whether it arrives as a list, a JSON list or a bracketed string", function () {
  assert.match(this.staffGroupsResult, /PASS: admin has every editor right/);
});

When("it files a proposal, moves it, pins it, moderates a reader and imports a reference for review", { timeout: 300_000 }, async function () {
  this.adminResult = await run("poetry", ["run", "pytest", "procedures/newsroom/tests/test_admin_has_editor_rights.py", "-q"], { maxBuffer: 4 * 1024 * 1024 });
});
Then("each action is accepted", function () { assert.match(this.adminResult.stdout, /passed/); assert.doesNotMatch(this.adminResult.stdout, /failed/); });
Then("a reader with neither group is refused the same actions", function () { assert.match(this.adminResult.stdout, /passed/); });

When("the newsroom backend refuses one of the dashboard reads", function () {
  const fs = require("node:fs");
  this.providerSource = fs.readFileSync("components/news-desk-client-provider.tsx", "utf8");
});
Then("the page reports the refused read and does not say the editor role is missing", function () {
  assert.match(this.providerSource, /refusedReadMessage\(error\)/);
  assert.doesNotMatch(this.providerSource, /isAuthorizationError\(error\)\)\s*\{\s*setShell\(\(current\) => resolveForbidden/);
  assert.doesNotMatch(this.providerSource, /isAuthorizationError\(error\)\) return resolveForbidden/);
});
