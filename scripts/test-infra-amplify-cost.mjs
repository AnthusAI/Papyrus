#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { budgetPlanCommands, deriveBudgetThreshold, planMonths } from "../packages/papyrus/src/amplify-cost-check.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cli = path.join(repo, "packages/papyrus/bin/papyrus-infra.mjs");
const fixtures = path.join(repo, "features_backend/fixtures/amplify-cost");

assert.deepEqual(planMonths({ months: 3, through: "2026-10", today: new Date("2026-10-31T12:00:00Z") }).map((entry) => [entry.month, entry.start, entry.end, entry.complete]), [
  ["2026-08", "2026-08-01", "2026-09-01", true],
  ["2026-09", "2026-09-01", "2026-10-01", true],
  ["2026-10", "2026-10-01", "2026-11-01", true],
]);
const withoutThrough = planMonths({ months: 3, today: new Date("2026-11-15T12:00:00Z") });
assert.deepEqual(withoutThrough.map((entry) => [entry.month, entry.complete]), [["2026-09", true], ["2026-10", true], ["2026-11", false]]);
assert.equal(planMonths({ months: 2, today: new Date("2026-01-10T00:00:00Z") })[0].month, "2025-12");

const rising = deriveBudgetThreshold([10, 12, 30, 70.77], 3);
const flat = deriveBudgetThreshold([20, 20, 20, 20], 3);
assert.equal(flat.threshold, 20);
assert.equal(flat.factor, 1);
assert.ok(rising.threshold > 70.77, "a rising history yields a threshold above the latest month's median");
assert.notEqual(rising.threshold, flat.threshold, "different histories give different thresholds");
assert.deepEqual(deriveBudgetThreshold([72.78], 3), { baseline: 72.78, factor: 1, growthRatios: [], threshold: 72.78, monthsUsed: 1 });
assert.equal(deriveBudgetThreshold([40, 50, 60], 3).baseline, 50);
assert.throws(() => deriveBudgetThreshold([], 3), /no completed months/);

const plan = budgetPlanCommands({ accountId: "111111111111", threshold: 123.45 });
assert.match(plan, /"Amount": "123.45"/);
assert.match(plan, /"Service": \[\s*"AWS Amplify"/);
assert.match(plan, /aws ssm get-parameter .*--name \/papyrus\/cost\/amplify-alert-email/);
assert.doesNotMatch(plan, /@/, "no email address appears in the plan");

const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-infra-cost-"));
try {
  const binDirectory = path.join(work, "bin");
  fs.mkdirSync(binDirectory);
  fs.copyFileSync(path.join(fixtures, "fake-aws.mjs"), path.join(binDirectory, "aws"));
  fs.chmodSync(path.join(binDirectory, "aws"), 0o755);
  const run = (scenarioName, extraArguments) => spawnSync("node", [cli, "cost", "amplify", ...extraArguments], {
    encoding: "utf8",
    env: { ...process.env, PATH: `${binDirectory}:${process.env.PATH}`, FAKE_AWS_SCENARIO: path.join(fixtures, `${scenarioName}.json`) },
  });

  const report = run("rising-history", ["--months", "3", "--through", "2026-10"]);
  assert.equal(report.status, 0, report.stderr);
  assert.match(report.stdout, /2026-10\s+111111111111\s+USE1-BuildDuration\s+7,076\.8\s+Minutes\s+70\.77/);
  assert.match(report.stdout, /2026-10\s+total\s+70\.97/);
  assert.match(report.stdout, /example-cms\s+21 min\s+2 builds/);
  assert.doesNotMatch(report.stdout, /quiet-site/);
  assert.match(report.stdout, /Budget threshold learned from 3 completed month\(s\) with spend/);
  assert.doesNotMatch(report.stdout, /aws budgets create-budget/, "the budget plan is only printed on request");

  const planned = run("rising-history", ["--months", "3", "--through", "2026-10", "--no-apps", "--plan-budget"]);
  assert.equal(planned.status, 0, planned.stderr);
  assert.doesNotMatch(planned.stdout, /Build minutes per app/);
  assert.match(planned.stdout, /aws budgets create-budget --account-id 111111111111/);
  const risingLimit = planned.stdout.match(/"Amount": "([\d.]+)"/)[1];
  const flatLimit = run("flat-history", ["--months", "3", "--through", "2026-10", "--no-apps", "--plan-budget"]).stdout.match(/"Amount": "([\d.]+)"/)[1];
  assert.notEqual(risingLimit, flatLimit);
  assert.equal(flatLimit, "20.20");

  const badMonths = run("flat-history", ["--months", "0"]);
  assert.notEqual(badMonths.status, 0);
  assert.match(badMonths.stderr, /--months must be a positive whole number/);
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
console.log("amplify cost: ok");
