#!/usr/bin/env node
/**
 * infra/amplify-app-shell takes its deploy account and region from the site's own site.json `aws` block and
 * never defaults to one. Runs the real `cdk synth` with the local CDK binary (so ts-node type-checks the
 * stack: TS_NODE_TRANSPILE_ONLY is cleared) against a site file that records its account and one that does
 * not, and checks `npm run build` type-checks cleanly. Run `npm ci` in infra/amplify-app-shell first.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const shell = path.join(repo, "infra/amplify-app-shell");
const cdk = path.join(shell, "node_modules/.bin/cdk");
if (!fs.existsSync(cdk)) throw new Error("run `npm ci` in infra/amplify-app-shell first (the aws-cdk CLI is a devDependency)");

const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-app-shell-account-"));
const env = { ...process.env, TS_NODE_TRANSPILE_ONLY: "", CDK_DEFAULT_ACCOUNT: "", CDK_DEFAULT_REGION: "", CDK_DEFAULT_ENV: "", PAPYRUS_AWS_ACCOUNT_ID: "", PAPYRUS_EDGE_DISTRIBUTION_ARN: "" };
const synth = (site, name, extraEnvironment = {}) => {
  const out = path.join(work, `out-${name}`);
  const sitePath = path.join(work, `${name}.site.json`);
  fs.writeFileSync(sitePath, JSON.stringify(site));
  const result = spawnSync(cdk, ["synth", "-c", `site=${sitePath}`, "--output", out, "--quiet"], { cwd: shell, env: { ...env, ...extraEnvironment }, encoding: "utf8" });
  return { ...result, out };
};

try {
  const example = JSON.parse(fs.readFileSync(path.join(shell, "examples/p-apyr-us.site.json"), "utf8"));

  const withAccount = synth({ ...example, aws: { accountId: "712236451410", region: "us-east-1" } }, "with-account");
  assert.equal(withAccount.status, 0, `synth with an account failed:\n${withAccount.stderr}`);
  const manifest = JSON.parse(fs.readFileSync(path.join(withAccount.out, "manifest.json"), "utf8"));
  const stack = Object.values(manifest.artifacts).find((artifact) => artifact.type === "aws:cloudformation:stack");
  assert.equal(stack.environment, "aws://712236451410/us-east-1", "the stack deploys to the account in site.json");

  const otherAccount = synth({ ...example, aws: { accountId: "111111111111", region: "us-west-2" } }, "other-account");
  assert.equal(otherAccount.status, 0, otherAccount.stderr);
  const otherManifest = JSON.parse(fs.readFileSync(path.join(otherAccount.out, "manifest.json"), "utf8"));
  assert.equal(Object.values(otherManifest.artifacts).find((artifact) => artifact.type === "aws:cloudformation:stack").environment, "aws://111111111111/us-west-2");

  const { aws: _aws, ...withoutAws } = example;
  const withoutAccount = synth(withoutAws, "without-account");
  assert.notEqual(withoutAccount.status, 0, "synth without aws.accountId must fail");
  assert.match(withoutAccount.stderr, /does not say where it deploys/);
  assert.match(withoutAccount.stderr, /PAPYRUS_AWS_ACCOUNT_ID \(or aws\.accountId\) and aws\.region/);
  assert.equal(fs.existsSync(path.join(withoutAccount.out, "manifest.json")), false, "nothing is synthesized without an account");
  assert.equal(/335163751677/.test(withoutAccount.stderr), false, "no legacy account fallback");

  // The account may come from the deploy environment, so site.json carries no account id at all.
  const fromEnvironment = synth({ ...example, aws: { region: "us-east-1" } }, "from-environment", { PAPYRUS_AWS_ACCOUNT_ID: "111122223333" });
  assert.equal(fromEnvironment.status, 0, `synth with PAPYRUS_AWS_ACCOUNT_ID failed:\n${fromEnvironment.stderr}`);
  const environmentManifest = JSON.parse(fs.readFileSync(path.join(fromEnvironment.out, "manifest.json"), "utf8"));
  assert.equal(Object.values(environmentManifest.artifacts).find((artifact) => artifact.type === "aws:cloudformation:stack").environment, "aws://111122223333/us-east-1");
  const environmentOverLiteral = synth({ ...example, aws: { accountId: "123456789012", region: "us-east-1" } }, "environment-over-literal", { PAPYRUS_AWS_ACCOUNT_ID: "111122223333" });
  assert.equal(environmentOverLiteral.status, 0, environmentOverLiteral.stderr);
  const overManifest = JSON.parse(fs.readFileSync(path.join(environmentOverLiteral.out, "manifest.json"), "utf8"));
  assert.equal(Object.values(overManifest.artifacts).find((artifact) => artifact.type === "aws:cloudformation:stack").environment, "aws://111122223333/us-east-1", "the environment wins over aws.accountId");
  const template = JSON.parse(fs.readFileSync(path.join(fromEnvironment.out, fs.readdirSync(fromEnvironment.out).find((name) => name.endsWith(".template.json"))), "utf8"));
  const branchVariables = Object.values(template.Resources).filter((resource) => resource.Type === "AWS::Amplify::Branch").flatMap((resource) => resource.Properties.EnvironmentVariables.map((variable) => variable.Name));
  assert.ok(branchVariables.includes("PAPYRUS_AMPLIFY_APP_ID") && branchVariables.includes("PAPYRUS_COMPUTE_ROLE_ARN"), "the stack derives the owning app id and compute role for its branches");

  const withEdge = synth({ ...example, aws: { region: "us-east-1" } }, "with-edge", { PAPYRUS_AWS_ACCOUNT_ID: "111122223333", PAPYRUS_EDGE_DISTRIBUTION_ARN: "arn:aws:cloudfront::111122223333:distribution/EEXAMPLE12345" });
  assert.equal(withEdge.status, 0, withEdge.stderr);
  const edgeTemplate = JSON.parse(fs.readFileSync(path.join(withEdge.out, fs.readdirSync(withEdge.out).find((name) => name.endsWith(".template.json"))), "utf8"));
  const edgeVariables = Object.values(edgeTemplate.Resources).filter((resource) => resource.Type === "AWS::Amplify::Branch").flatMap((resource) => resource.Properties.EnvironmentVariables.map((variable) => variable.Name));
  assert.ok(edgeVariables.includes("PAPYRUS_EDGE_DISTRIBUTION_ARN"), "a stack deploy carries the edge distribution ARN through, so the branch keeps it");
  assert.equal(branchVariables.includes("PAPYRUS_EDGE_DISTRIBUTION_ARN"), false, "and adds nothing when the deploy environment has none");

  const regionless = synth({ ...example, aws: { accountId: "712236451410" } }, "regionless");
  assert.notEqual(regionless.status, 0, "synth without aws.region must fail");
  assert.match(regionless.stderr, /aws\.region/);

  const build = spawnSync("npm", ["run", "build"], { cwd: shell, env, encoding: "utf8" });
  assert.equal(build.status, 0, `npm run build must type-check cleanly:\n${build.stdout}${build.stderr}`);
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}

console.log("app-shell account tests passed");
