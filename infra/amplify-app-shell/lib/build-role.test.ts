import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { App } from "aws-cdk-lib";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { parseSiteConfig, resolveStackName } from "./site-config";

// Executes infra/amplify-app-shell/features/build-role-scope.feature (run through scripts/test-infra-build-role.ts).
const examples = path.resolve(__dirname, "../examples");
const example = (name: string, change: (config: any) => void = () => {}): any => {
  const config = JSON.parse(fs.readFileSync(path.join(examples, `${name}.site.json`), "utf8"));
  change(config);
  return config;
};
const siteNames = fs.readdirSync(examples).filter((name) => name.endsWith(".site.json")).map((name) => name.replace(/\.site\.json$/, ""));
const resourcesOf = (template: any, type: string): any[] => Object.values<any>(template.Resources).filter((resource) => resource.Type === type);
function shellTemplate(raw: unknown): any {
  const config = parseSiteConfig(raw);
  const stack = new AmplifyAppShellStack(new App(), "Shell", config, { env: { account: "712236451410", region: "us-east-1" }, stackName: resolveStackName(config) });
  return JSON.parse(JSON.stringify((App.of(stack) as App).synth().getStackByName(stack.stackName).template));
}
const buildRoleOf = (template: any): any => resourcesOf(template, "AWS::IAM::Role").find((role) => /Backend deploy and staging build service role/.test(role.Properties.Description));
const managedPolicyNames = (role: any): string[] => (role.Properties.ManagedPolicyArns ?? []).map((arn: any) => JSON.stringify(arn));
const grantsPolicyOf = (template: any): any => resourcesOf(template, "AWS::IAM::Policy").find((policy) => policy.Properties.Roles?.some((role: any) => role.Ref === Object.keys(template.Resources).find((key) => template.Resources[key] === buildRoleOf(template))));
const statementsOf = (policy: any): any[] => [policy.Properties.PolicyDocument.Statement].flat();
const asList = (value: any): any[] => [value].flat();

// Scenario: a site that does not set cms.buildRole keeps the administrator build role
for (const name of siteNames) {
  const template = shellTemplate(example(name));
  const role = buildRoleOf(template);
  if (!role) continue;
  assert.ok(managedPolicyNames(role).some((arn) => arn.includes("AdministratorAccess")), `${name} keeps AdministratorAccess by default`);
  assert.ok(/AdministratorAccess: documented risk/.test(role.Properties.Description), `${name} still says it is a documented risk`);
  assert.equal(grantsPolicyOf(template), undefined, `${name} gets no scoped grants by default`);
}

// Scenario: a scoped build role has no administrator policy
const scopedTemplate = shellTemplate(example("machines-on-machines", (config) => { config.cms.buildRole = "scoped"; }));
const scopedRole = buildRoleOf(scopedTemplate);
assert.ok(scopedRole, "the scoped site still has its build role");
assert.ok(managedPolicyNames(scopedRole).some((arn) => arn.includes("AmplifyBackendDeployFullAccess")));
assert.ok(!managedPolicyNames(scopedRole).some((arn) => /AdministratorAccess|PowerUserAccess|IAMFullAccess/.test(arn)));
assert.ok(!JSON.stringify(scopedTemplate).includes("AdministratorAccess"), "no administrator policy anywhere in the scoped site's stack");
assert.ok(/scoped/.test(scopedRole.Properties.Description) && !/documented risk/.test(scopedRole.Properties.Description));

// Scenario: the scoped role is granted what the build commands use, for this site only
const grants = grantsPolicyOf(scopedTemplate);
assert.ok(grants, "the scoped grants are a policy on the build role");
const grantedStatements = statementsOf(grants);
const bySid = (sid: string) => grantedStatements.find((statement) => statement.Sid === sid);
for (const sid of ["ReadThisSitesParameters", "WakeQueueAddress", "ListSchedules", "SiteScheduleGroupEntries", "PassTheSchedulerRoleToTheSchedulerOnly", "SignAppSyncAuthoringRequests", "ReadWriteMediaAndPreview"]) {
  assert.ok(bySid(sid), `the scoped build role has ${sid}`);
}
assert.ok(JSON.stringify(bySid("ReadThisSitesParameters").Resource).includes("parameter/papyrus/machines-on-machines/*"));
assert.deepEqual(bySid("PassTheSchedulerRoleToTheSchedulerOnly").Condition, { StringEquals: { "iam:PassedToService": "scheduler.amazonaws.com" } });
for (const statement of grantedStatements.filter((candidate) => candidate.Effect === "Allow")) {
  assert.ok(!asList(statement.Action).some((action: string) => action === "*" || action === "iam:*" || action === "sts:*"), `${statement.Sid} allows no wildcard over identity services`);
}

// Scenario: the scoped build role can never change the pipeline's own roles or stacks
const roleDeny = bySid("DenyChangesToThePipelinesOwnRoles");
const stackDeny = bySid("DenyChangesToThePipelinesOwnStacks");
assert.equal(roleDeny.Effect, "Deny");
assert.equal(stackDeny.Effect, "Deny");
const roleDenyResources = JSON.stringify(roleDeny.Resource);
for (const prefix of ["papyrus-pipeline-", "papyrus-stack-", "papyrus-shared-"]) assert.ok(roleDenyResources.includes(`role/${prefix}*`), `denies roles ${prefix}*`);
const stackDenyResources = JSON.stringify(stackDeny.Resource);
for (const name of ["papyrus-stack-pipeline", "papyrus-pipeline-approver"]) assert.ok(stackDenyResources.includes(`stack/${name}/`), `denies stack ${name}`);
assert.ok(asList(roleDeny.Action).includes("iam:*") && asList(roleDeny.Action).includes("sts:AssumeRole"));

// Scenario: a value other than administrator or scoped is refused
for (const bad of ["admin", "none", true, 1, ""]) {
  assert.throws(() => parseSiteConfig(example("machines-on-machines", (config) => { config.cms.buildRole = bad; })), /cms\.buildRole.*"administrator" or "scoped"/, `cms.buildRole ${JSON.stringify(bad)} is refused`);
}

// Scenario: the two kinds differ only in the build role and its grants
const administratorTemplate = shellTemplate(example("machines-on-machines"));
const withoutRoleAndGrants = (template: any) => {
  const role = buildRoleOf(template);
  const roleKey = Object.keys(template.Resources).find((key) => template.Resources[key] === role);
  const grantsKey = Object.keys(template.Resources).find((key) => template.Resources[key] === grantsPolicyOf(template));
  const remaining = { ...template.Resources };
  delete remaining[roleKey!];
  if (grantsKey) delete remaining[grantsKey];
  return Object.keys(remaining).sort();
};
assert.deepEqual(withoutRoleAndGrants(scopedTemplate).filter((key) => !key.startsWith("ScopedBuildRoleGrants")), withoutRoleAndGrants(administratorTemplate));

console.log("build-role scope: all scenarios passed");
