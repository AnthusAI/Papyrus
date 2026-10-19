#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveCdkAccount, resolveCdkEnvironment, resolveCdkRegion } from "../packages/papyrus/src/cdk-environment.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const legacyAccount = ["3351", "6375", "1236", "77"].join("");
const resolvedAccount = "712236451410";
const neverCalled = () => assert.fail("STS must not be queried when an account is already known");

assert.equal(resolveCdkAccount({ explicitAccount: "111111111111", environment: { CDK_DEFAULT_ACCOUNT: "222222222222" }, lookupCallerAccount: neverCalled }), "111111111111", "--account wins over CDK_DEFAULT_ACCOUNT");
assert.equal(resolveCdkAccount({ environment: { CDK_DEFAULT_ACCOUNT: "222222222222" }, lookupCallerAccount: neverCalled }), "222222222222");
assert.equal(resolveCdkAccount({ environment: {}, lookupCallerAccount: () => resolvedAccount }), resolvedAccount, "STS is used when nothing else is set");

assert.throws(
  () => resolveCdkAccount({ environment: {}, lookupCallerAccount: () => { throw new Error("Unable to locate credentials"); } }),
  (error) => /cannot determine the AWS account/.test(error.message) && /Unable to locate credentials/.test(error.message) && !error.message.includes(legacyAccount),
);
assert.throws(() => resolveCdkAccount({ environment: {}, lookupCallerAccount: () => undefined }), /cannot determine the AWS account/);
assert.throws(() => resolveCdkAccount({ environment: {}, lookupCallerAccount: () => "not-an-account" }), /cannot determine the AWS account/);

assert.equal(resolveCdkRegion({ explicitRegion: "eu-west-1", environment: { AWS_REGION: "us-west-2" } }), "eu-west-1");
assert.equal(resolveCdkRegion({ environment: { AWS_REGION: "us-west-2", AWS_DEFAULT_REGION: "us-west-1", CDK_DEFAULT_REGION: "eu-west-2" } }), "us-west-2");
assert.equal(resolveCdkRegion({ environment: { AWS_DEFAULT_REGION: "us-west-1", CDK_DEFAULT_REGION: "eu-west-2" } }), "us-west-1");
assert.equal(resolveCdkRegion({ environment: { CDK_DEFAULT_REGION: "eu-west-2" } }), "eu-west-2");
assert.equal(resolveCdkRegion({ environment: {} }), "us-east-1");

assert.deepEqual(resolveCdkEnvironment({ environment: {}, lookupCallerAccount: () => resolvedAccount }), { account: resolvedAccount, region: "us-east-1" });

const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-infra-cdk-environment-"));
try {
  const binDirectory = path.join(work, "bin");
  fs.mkdirSync(binDirectory);
  const fakeAws = (body) => fs.writeFileSync(path.join(binDirectory, "aws"), `#!/usr/bin/env node\n${body}\n`, { mode: 0o755 });
  const environmentWithFakeAws = { ...process.env, PATH: `${binDirectory}:${process.env.PATH}`, AWS_REGION: "", AWS_DEFAULT_REGION: "", CDK_DEFAULT_REGION: "" };
  const runResolver = (script, environment) =>
    execFileSync("node", ["--input-type=module", "-e", script], { encoding: "utf8", env: environment, cwd: repo });
  const moduleUrl = new URL("../packages/papyrus/src/cdk-environment.mjs", import.meta.url).href;
  const resolveScript = `import { resolveCdkEnvironment } from ${JSON.stringify(moduleUrl)}; try { console.log(JSON.stringify(resolveCdkEnvironment({}))); } catch (error) { console.log("ERROR " + error.message); }`;

  fakeAws(`const a = process.argv.slice(2).join(" "); if (a.startsWith("sts get-caller-identity")) process.stdout.write(JSON.stringify({ Account: "${resolvedAccount}" }));`);
  assert.deepEqual(JSON.parse(runResolver(resolveScript, { ...environmentWithFakeAws, CDK_DEFAULT_ACCOUNT: "" })), { account: resolvedAccount, region: "us-east-1" });

  fakeAws(`process.stderr.write("Unable to locate credentials"); process.exit(255);`);
  assert.match(runResolver(resolveScript, { ...environmentWithFakeAws, CDK_DEFAULT_ACCOUNT: "" }), /^ERROR cannot determine the AWS account.*Unable to locate credentials/);
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}

const cliSource = fs.readFileSync(path.join(repo, "packages/papyrus/bin/papyrus-infra.mjs"), "utf8");
const moduleSource = fs.readFileSync(path.join(repo, "packages/papyrus/src/cdk-environment.mjs"), "utf8");
for (const source of [cliSource, moduleSource]) assert.equal(source.includes(legacyAccount), false, "no hard-coded legacy account remains");
assert.equal((cliSource.match(/resolveEnvironmentOrExit\(\)/g) ?? []).length, 2, "both stacks resolve the environment through the shared resolver");

console.log("papyrus-infra cdk environment tests passed");
