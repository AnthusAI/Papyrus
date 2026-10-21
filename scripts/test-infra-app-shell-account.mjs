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
const env = { ...process.env, TS_NODE_TRANSPILE_ONLY: "", CDK_DEFAULT_ACCOUNT: "", CDK_DEFAULT_REGION: "", CDK_DEFAULT_ENV: "" };
const synth = (site, name) => {
  const out = path.join(work, `out-${name}`);
  const sitePath = path.join(work, `${name}.site.json`);
  fs.writeFileSync(sitePath, JSON.stringify(site));
  const result = spawnSync(cdk, ["synth", "-c", `site=${sitePath}`, "--output", out, "--quiet"], { cwd: shell, env, encoding: "utf8" });
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
  assert.match(withoutAccount.stderr, /aws\.accountId and aws\.region/);
  assert.equal(fs.existsSync(path.join(withoutAccount.out, "manifest.json")), false, "nothing is synthesized without an account");
  assert.equal(/335163751677/.test(withoutAccount.stderr), false, "no legacy account fallback");

  const regionless = synth({ ...example, aws: { accountId: "712236451410" } }, "regionless");
  assert.notEqual(regionless.status, 0, "synth without aws.region must fail");
  assert.match(regionless.stderr, /aws\.region/);

  const build = spawnSync("npm", ["run", "build"], { cwd: shell, env, encoding: "utf8" });
  assert.equal(build.status, 0, `npm run build must type-check cleanly:\n${build.stdout}${build.stderr}`);
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}

console.log("app-shell account tests passed");
