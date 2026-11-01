const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

async function behaviour(name) {
  const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-sync-entry.ts", name], { cwd: path.resolve(__dirname, "../..") });
  return JSON.parse(result.stdout.trim().split("\n").pop()).behaviour;
}

When("the sync's command-line entry point runs for a site without the alexa plugin", { timeout: 120_000 }, async function () {
  this.passed = await behaviour("the build's sync entry point starts and skips a site without the plugin");
});
When("the by-hand sync script runs for a site without the alexa plugin", { timeout: 120_000 }, async function () {
  this.passed = await behaviour("the by-hand sync script starts too");
});
Then("it says it skipped and exits successfully", function () {
  assert.ok(this.passed);
});
