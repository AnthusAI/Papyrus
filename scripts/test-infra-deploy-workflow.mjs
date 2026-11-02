#!/usr/bin/env node
/**
 * The reusable Amplify deploy workflow works out its app and role from repository-variable inputs
 * (AMPLIFY_APP_ID, AWS_ACCOUNT_ID), still accepts a literal app id and role ARN, and fails with a message that
 * names the variable when one is missing. The deploy example carries no ids at all. Runs the workflow's own
 * first step in bash, with the inputs as environment variables.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workflow = parse(fs.readFileSync(path.join(repo, ".github/workflows/amplify-deploy.yml"), "utf8"));
const step = workflow.jobs.deploy.steps.find((candidate) => candidate.id === "target");
assert.ok(step, "the deploy job has a step that works out the app and the role");

const exampleAccount = "111122223333";
const otherAccount = "123456789012"; // AWS documentation example account
function runStep(inputs) {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-deploy-workflow-"));
  try {
    const output = path.join(work, "output");
    fs.writeFileSync(output, "");
    const result = spawnSync("bash", ["-c", step.run], {
      encoding: "utf8",
      env: { PATH: process.env.PATH, GITHUB_OUTPUT: output, APP_ID: "", ACCOUNT_ID: "", ROLE_NAME: "", ROLE_TO_ASSUME: "", ...inputs },
    });
    return { ...result, output: fs.readFileSync(output, "utf8") };
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

const fromVariables = runStep({ APP_ID: "dexample", ACCOUNT_ID: exampleAccount, ROLE_NAME: "example-github-deploy" });
assert.equal(fromVariables.status, 0, fromVariables.stderr);
assert.equal(fromVariables.output.trim(), `role=arn:aws:iam::${exampleAccount}:role/example-github-deploy`);

const literalRole = runStep({ APP_ID: "dexample", ROLE_TO_ASSUME: `arn:aws:iam::${otherAccount}:role/legacy`, ACCOUNT_ID: exampleAccount, ROLE_NAME: "ignored" });
assert.equal(literalRole.status, 0, "a caller that still passes a role ARN keeps working");
assert.equal(literalRole.output.trim(), `role=arn:aws:iam::${otherAccount}:role/legacy`, "the literal role ARN wins");

const noApp = runStep({ ACCOUNT_ID: exampleAccount, ROLE_NAME: "example-github-deploy" });
assert.notEqual(noApp.status, 0);
assert.match(noApp.stdout, /AMPLIFY_APP_ID/, "an unset AMPLIFY_APP_ID variable is named");

const noAccount = runStep({ APP_ID: "dexample", ROLE_NAME: "example-github-deploy" });
assert.notEqual(noAccount.status, 0);
assert.match(noAccount.stdout, /AWS_ACCOUNT_ID/, "an unset AWS_ACCOUNT_ID variable is named");

const badAccount = runStep({ APP_ID: "dexample", ACCOUNT_ID: "12345", ROLE_NAME: "example-github-deploy" });
assert.notEqual(badAccount.status, 0);
assert.match(badAccount.stdout, /12-digit/);

for (const file of ["infra/amplify-app-shell/examples/deploy-on-merge.workflow.yml", ".github/workflows/amplify-deploy.yml"]) {
  const text = fs.readFileSync(path.join(repo, file), "utf8");
  assert.equal(/\b\d{12}\b/.test(text.replace(/\b111122223333\b/g, "")), false, `${file} carries no account id`);
  assert.equal(/\bd[a-z0-9]{12,13}\b/.test(text), false, `${file} carries no app id`);
}
const example = fs.readFileSync(path.join(repo, "infra/amplify-app-shell/examples/deploy-on-merge.workflow.yml"), "utf8");
assert.match(example, /app-id: \$\{\{ vars\.AMPLIFY_APP_ID \}\}/);
assert.match(example, /aws-account-id: \$\{\{ vars\.AWS_ACCOUNT_ID \}\}/);

console.log("infra deploy workflow tests passed");
