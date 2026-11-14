/**
 * Every dedicated site's app shell carries the shared-stack deny and differs from the shell without it by that policy alone
 * (features_backend/shared-stack-bootstrap.feature). Run by scripts/test-infra-shared-stack-deny.ts, in this package's own harness style.
 *
 *   node --import tsx infra/amplify-app-shell/lib/shared-stack-deny.test.ts           asserts
 *   node --import tsx infra/amplify-app-shell/lib/shared-stack-deny.test.ts --json    prints the facts as JSON
 */
import fs from "node:fs";
import assert from "node:assert/strict";
import path from "node:path";
import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
// The backend's copy lives outside this package's rootDir, so it is read at run time.
const { sharedStackDenyPolicyDocument: backendDeny, SHARED_DENY_POLICY_NAME } = require("../../../amplify/shared-stack/names") as {
  sharedStackDenyPolicyDocument: () => unknown;
  SHARED_DENY_POLICY_NAME: string;
};
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { sharedStackDenyPolicyDocument as shellDeny } from "./shared-stack-deny";
import { parseSiteConfig } from "./site-config";

export type AppShellDenyFacts = {
  roles: number;
  rolesWithTheDeny: number;
  sameResources: boolean;
  onlyDifferenceIsTheDeny: boolean;
  denyEqualsTheBackendsDeny: boolean;
};

export function appShellDenyFacts(example = "shipped"): AppShellDenyFacts {
  const examples = path.resolve(__dirname, "../examples");
  const site = parseSiteConfig(JSON.parse(fs.readFileSync(path.join(examples, `${example}.site.json`), "utf8")));
  const env = { account: "111122223333", region: "us-east-1" };
  // The same construct id in both, because a custom resource provider's description carries it.
  const plain = Template.fromStack(new AmplifyAppShellStack(new App(), "Shell", site, { env }, { sharedStackDeny: false })).toJSON();
  const withDeny = Template.fromStack(new AmplifyAppShellStack(new App(), "Shell", site, { env })).toJSON();
  const roles = Object.values<any>(withDeny.Resources).filter((resource) => resource.Type === "AWS::IAM::Role");
  const denies = (role: any) => (role.Properties.Policies ?? []).filter((policy: any) => policy.PolicyName === SHARED_DENY_POLICY_NAME);
  const stripped = JSON.parse(JSON.stringify(withDeny));
  for (const resource of Object.values<any>(stripped.Resources)) {
    if (resource.Type !== "AWS::IAM::Role") continue;
    resource.Properties.Policies = (resource.Properties.Policies ?? []).filter((policy: any) => policy.PolicyName !== SHARED_DENY_POLICY_NAME);
    if (resource.Properties.Policies.length === 0) delete resource.Properties.Policies;
  }
  return {
    roles: roles.length,
    rolesWithTheDeny: roles.filter((role) => denies(role).length === 1).length,
    sameResources: JSON.stringify(Object.keys(withDeny.Resources)) === JSON.stringify(Object.keys(plain.Resources)),
    onlyDifferenceIsTheDeny: JSON.stringify(stripped) === JSON.stringify(plain),
    denyEqualsTheBackendsDeny: roles.every((role) => JSON.stringify(denies(role)[0]?.PolicyDocument) === JSON.stringify(backendDeny())) && JSON.stringify(shellDeny()) === JSON.stringify(backendDeny()),
  };
}

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(appShellDenyFacts()));
} else {
  const names = fs.readdirSync(path.resolve(__dirname, "../examples")).filter((file) => file.endsWith(".site.json")).map((file) => file.replace(".site.json", ""));
  for (const name of names) {
    const facts = appShellDenyFacts(name);
    assert.ok(facts.roles >= 1 && facts.rolesWithTheDeny === facts.roles, `${name}: every role carries the deny`);
    assert.ok(facts.sameResources, `${name}: the shell gains no resource`);
    assert.ok(facts.onlyDifferenceIsTheDeny, `${name}: the shell differs only by the deny`);
    assert.ok(facts.denyEqualsTheBackendsDeny, `${name}: the deny is the backend's deny`);
  }
  console.log(`shared stack deny: ${names.length} app shells ok`);
}
