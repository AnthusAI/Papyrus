import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { defineBackend } from "@aws-amplify/backend";
import { Template } from "aws-cdk-lib/assertions";
import { applyCognitoDomainPrefix, defineSiteAuth } from "../amplify/auth/resource";
import { manageUserRole } from "../amplify/functions/manage-user-role/resource";

const REQUESTED_PREFIX = "papyrus-prefix-test";

function synthesizeUserPoolDomain(backendName: string, apply: boolean): string {
  process.env.CDK_CONTEXT_JSON = JSON.stringify({
    "amplify-backend-name": backendName,
    "amplify-backend-namespace": "prefixtest",
    "amplify-backend-type": "branch",
  });
  const authConfig = {
    redirectUrls: ["http://localhost:3000/"],
    cognitoDomainPrefix: REQUESTED_PREFIX,
    applyCognitoDomainPrefix: apply,
  };
  const backend = defineBackend({ auth: defineSiteAuth(authConfig), manageUserRole });
  if (apply) {
    applyCognitoDomainPrefix(backend.auth.stack, REQUESTED_PREFIX);
  }
  const domains = Object.values(Template.fromStack(backend.auth.stack).findResources("AWS::Cognito::UserPoolDomain"));
  assert.equal(domains.length, 1, "exactly one user pool domain");
  return (domains[0] as { Properties: { Domain: string } }).Properties.Domain;
}

function synthesizeInChildProcess(backendName: string, apply: boolean): string {
  const child = spawnSync(process.execPath, [...process.execArgv, process.argv[1], "child", backendName, String(apply)], {
    encoding: "utf8",
    env: process.env,
  });
  assert.equal(child.status, 0, child.stderr.slice(-2000));
  const marker = /DOMAIN=(\S+)/.exec(child.stdout);
  assert.ok(marker, `child printed no domain: ${child.stdout.slice(-500)}`);
  return marker[1];
}

if (process.argv[2] === "child") {
  console.log(`DOMAIN=${synthesizeUserPoolDomain(process.argv[3], process.argv[4] === "true")}`);
  process.exit(0);
}

const generatedDomain = synthesizeInChildProcess("notapplied", false);
assert.notEqual(generatedDomain, REQUESTED_PREFIX, "without opt-in the Amplify-generated domain is kept");
assert.match(generatedDomain, /^[0-9a-f]{20}$/, "generated domain is the Amplify backend hash");
assert.equal(synthesizeInChildProcess("notapplied", false), generatedDomain, "generated domain is stable for a backend id");

const appliedDomain = synthesizeInChildProcess("applied", true);
assert.equal(appliedDomain, REQUESTED_PREFIX, "with opt-in the requested prefix is the user pool domain");

console.log("cognito domain prefix tests passed");
