const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
// scripts/test-data-table-recovery.ts synthesizes the data tables with and without the setting and compares the templates.
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-data-table-recovery.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};

Given("the data tables of a site backend", function () {});
When("the backend turns on point-in-time recovery", function () {});
for (const then of [
  "every data table has point-in-time recovery enabled",
  "no table is added, removed or replaced and only the recovery setting changes",
]) Then(then, async function () { assert.match(await run(), /data table recovery: ok/); });
