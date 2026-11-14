/**
 * The shared tier's isolation layers, below the full backend synth (features_backend/shared-stack-bootstrap.feature does that):
 * names, settings, the key / boundary / concurrency pass, the alarms, the deny and its copy in the app shell. PPY-daf673.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { addSharedStackAlarms } from "../amplify/shared-stack/alarms";
import { addSharedStackDeny, isModelDataStack } from "../amplify/shared-stack/deny";
import { sharedStackBackendConfig } from "../amplify/shared-stack/define";
import { applySharedStackIsolation, RESOURCES_THAT_CANNOT_TAKE_THE_KEY } from "../amplify/shared-stack/isolation";
import {
  SHARED_DENY_POLICY_NAME,
  SHARED_DEPLOYMENT_VALUES,
  SHARED_FAMILY_PREFIX,
  isReservedDeployment,
  sharedStackDenyPolicyDocument,
  sharedTierPlan,
} from "../amplify/shared-stack/names";
import { sharedStackSettings, validateSharedStackSettings, type SharedStackSettings } from "../amplify/shared-stack/settings";
import { assertValidTenancyConfig, validateTenancyConfig } from "../amplify/site-backend-config";
import { siteCostAttribution, sharedStackCostAttribution } from "../amplify/cost-attribution";

const production = sharedTierPlan("production");
const staging = sharedTierPlan("staging");

// --- names: the two tiers never overlap, and no dedicated site can take a shared value -------------------------------------
for (const plan of [production, staging]) {
  assert.ok(plan.stackPrefix.startsWith(SHARED_FAMILY_PREFIX));
  assert.ok(plan.foundationStackName.startsWith(plan.stackPrefix));
  assert.ok(plan.rolePath.startsWith(`/${plan.stackPrefix}`) && plan.rolePath.endsWith("/"));
  assert.ok(plan.keyArnParameter.startsWith("/papyrus/shared/"));
}
assert.ok(!staging.stackPrefix.startsWith(production.stackPrefix) && !production.stackPrefix.startsWith(staging.stackPrefix));
assert.ok(!staging.rolePath.startsWith(production.rolePath) && !production.rolePath.startsWith(staging.rolePath));
assert.deepEqual([...SHARED_DEPLOYMENT_VALUES], ["shared-prod", "shared-staging"]);
for (const id of ["shared", "shared-prod", "shared-staging"]) assert.ok(isReservedDeployment(id), id);
assert.ok(!isReservedDeployment("shipped") && !isReservedDeployment("shared-prod2"));
assert.throws(() => siteCostAttribution({ PAPYRUS_COST_TAG_WAVE: "all", PAPYRUS_SITE_ID: "shared-prod" }, fs.mkdtempSync("/tmp/nosite-")), /shared tier/);
assert.deepEqual(sharedStackCostAttribution(staging), { account: "shared", app: "papyrus", deployment: "shared-staging", wave: Number.POSITIVE_INFINITY });

// --- the tenancy config names the tier ----------------------------------------------------------------------------------
assert.deepEqual(validateTenancyConfig({ mode: "shared", tier: "staging" }), []);
assert.equal(validateTenancyConfig({ mode: "shared" }).length, 1);
assert.equal(validateTenancyConfig({ mode: "shared", tier: "prod" }).length, 1);
assert.equal(validateTenancyConfig({ mode: "dedicated", tier: "staging" }).length, 1);
assert.deepEqual(validateTenancyConfig({ mode: "dedicated" }), []);
assert.throws(() => assertValidTenancyConfig({ mode: "shared" }), /tenancy\.tier/);
const config = sharedStackBackendConfig("staging");
assert.deepEqual(config.tenancy, { mode: "shared", tier: "staging" });
assert.equal(config.publication && config.publication.kind, "s3-projection");
assert.equal(config.publication && (config.publication as { projector?: string }).projector, undefined, "no site's projector on the shared stack");
assert.equal(config.publication && (config.publication as { staticDir?: string }).staticDir, undefined, "no site's static files on the shared stack");

// --- settings: from the file, never from the code; production waits for measured values -------------------------------------
const staged = sharedStackSettings("staging");
assert.ok(staged.reservedConcurrency.perFunction >= 1 && staged.reservedConcurrency.tierLimit >= staged.reservedConcurrency.perFunction);
assert.throws(() => sharedStackSettings("production"), /reserved concurrency[\s\S]*staging traffic/);
assert.throws(() => validateSharedStackSettings("staging", { ...staged, reservedConcurrency: { ...staged.reservedConcurrency, perFunction: 0 } }), /perFunction/);
assert.throws(() => validateSharedStackSettings("staging", { ...staged, alarms: { ...staged.alarms, concurrencyShareOfReserved: 1.5 } }), /concurrencyShareOfReserved/);
assert.throws(() => validateSharedStackSettings("staging", { ...staged, logRetentionDays: 0 }), /logRetentionDays/);
assert.match(fs.readFileSync(path.join(__dirname, "../amplify/shared-stack/settings.ts"), "utf8"), /staging traffic/, "the settings file says the numbers must come from staging traffic");

// --- the isolation pass, on a small stack shaped like the backend's pieces ----------------------------------------------------
function miniBackend(settings: SharedStackSettings, extraFunctions = 0) {
  const app = new App();
  const root = new Stack(app, "Root", { env: { account: "111122223333", region: "us-east-1" } });
  const data = new Stack(root, "Data");
  const role = new iam.Role(root, "FunctionRole", { assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com") });
  for (const id of ["papyrus-content-actions", "papyrus-image-service", ...Array.from({ length: extraFunctions }, (_, i) => `papyrus-extra-${i}`)]) {
    new lambda.Function(root, id, { runtime: lambda.Runtime.PYTHON_3_12, handler: "h.h", code: lambda.Code.fromInline("x"), role });
  }
  // CDK's own plumbing: a function that must not get reserved concurrency.
  new lambda.Function(root, "LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a", { runtime: lambda.Runtime.NODEJS_20_X, handler: "i.h", code: lambda.Code.fromInline("x") });
  new s3.Bucket(root, "Media");
  new sqs.Queue(root, "ProjectionDeadLetter");
  new dynamodb.Table(root, "Lease", { partitionKey: { name: "id", type: dynamodb.AttributeType.STRING } });
  const amplifyTables: Record<string, { sseSpecification: unknown }> = { Item: { sseSpecification: undefined }, Reference: { sseSpecification: undefined } };
  const backend = { stack: root, data: { resources: { cfnResources: { amplifyDynamoDbTables: amplifyTables } } } };
  const report = applySharedStackIsolation(backend, staging, settings);
  return { root, data, report, amplifyTables };
}

{
  const { root, report, amplifyTables } = miniBackend(staged);
  const template = Template.fromStack(root).toJSON();
  const resources = Object.values<any>(template.Resources);
  const key = JSON.stringify(template.Parameters.PapyrusSharedKmsKeyArn);
  assert.match(key, /AWS::SSM::Parameter::Value<String>/);
  assert.match(key, /\/papyrus\/shared\/staging\/kms-key-arn/);

  // Every role: the staging path, the staging boundary, and the key-use policy.
  const roles = resources.filter((r) => r.Type === "AWS::IAM::Role");
  assert.ok(roles.length >= 2);
  for (const role of roles) {
    assert.equal(role.Properties.Path, "/papyrus-shared-staging/");
    assert.match(JSON.stringify(role.Properties.PermissionsBoundary), /policy\/papyrus-shared-staging-boundary/);
    assert.ok(role.Properties.Policies.some((p: any) => p.PolicyName === "papyrus-shared-staging-key-use"));
  }
  // The tables, bucket, queue, and the function log groups take the key.
  for (const table of Object.values(amplifyTables)) assert.deepEqual(Object.keys(table.sseSpecification as object).sort(), ["kmsMasterKeyId", "sseEnabled", "sseType"]);
  const [lease] = resources.filter((r) => r.Type === "AWS::DynamoDB::Table");
  assert.equal(lease.Properties.SSESpecification.SSEType, "KMS");
  assert.ok(lease.Properties.SSESpecification.KMSMasterKeyId.Ref);
  const [bucket] = resources.filter((r) => r.Type === "AWS::S3::Bucket");
  assert.equal(bucket.Properties.BucketEncryption.ServerSideEncryptionConfiguration[0].ServerSideEncryptionByDefault.SSEAlgorithm, "aws:kms");
  assert.equal(bucket.Properties.BucketEncryption.ServerSideEncryptionConfiguration[0].BucketKeyEnabled, true);
  assert.match(JSON.stringify(bucket.Properties.BucketName), /papyrus-shared-staging/);
  const [queue] = resources.filter((r) => r.Type === "AWS::SQS::Queue");
  assert.ok(queue.Properties.KmsMasterKeyId.Ref && queue.Properties.SqsManagedSseEnabled === undefined);
  const functions = resources.filter((r) => r.Type === "AWS::Lambda::Function");
  const groups = resources.filter((r) => r.Type === "AWS::Logs::LogGroup");
  assert.equal(groups.length, functions.length, "every function has its own encrypted log group");
  for (const group of groups) {
    assert.ok(group.Properties.KmsKeyId.Ref);
    assert.equal(group.Properties.RetentionInDays, staged.logRetentionDays);
    assert.equal(group.DeletionPolicy, "Retain");
  }
  for (const fn of functions) {
    assert.match(fn.Properties.FunctionName, /^papyrus-shared-staging-/);
    assert.ok(groups.some((g) => g.Properties.LogGroupName === `/aws/lambda/${fn.Properties.FunctionName}`));
  }
  // Reserved concurrency from the settings; the CDK plumbing function has none.
  const reserved = functions.filter((f) => f.Properties.ReservedConcurrentExecutions !== undefined);
  assert.equal(reserved.length, 2);
  for (const fn of reserved) assert.equal(fn.Properties.ReservedConcurrentExecutions, staged.reservedConcurrency.perFunction);
  assert.equal(report.reservedTotal, 2 * staged.reservedConcurrency.perFunction);
  assert.equal(report.functions, 3);
}
{
  // An override names one function; the total may not pass the tier's limit.
  const withOverride: SharedStackSettings = { ...staged, reservedConcurrency: { ...staged.reservedConcurrency, overrides: { "papyrus-content-actions": 7 } } };
  const { root } = miniBackend(withOverride);
  const reserved = Object.values<any>(Template.fromStack(root).toJSON().Resources).filter((r) => r.Type === "AWS::Lambda::Function").map((f) => f.Properties.ReservedConcurrentExecutions).filter(Boolean).sort();
  assert.deepEqual(reserved, [staged.reservedConcurrency.perFunction, 7].sort());
  const tight: SharedStackSettings = { ...staged, reservedConcurrency: { ...staged.reservedConcurrency, perFunction: 2, tierLimit: 3 } };
  assert.throws(() => miniBackend(tight), /tierLimit of 3/);
}
assert.ok(RESOURCES_THAT_CANNOT_TAKE_THE_KEY.length >= 4 && RESOURCES_THAT_CANNOT_TAKE_THE_KEY.every((entry) => entry.reason.length > 20));

// --- alarms: named with the stack's prefix, thresholds from the settings --------------------------------------------------------
{
  const app = new App();
  const alarmStack = new Stack(app, "Alarms", { env: { account: "111122223333", region: "us-east-1" } });
  const tableNames = Array.from({ length: 7 }, (_, i) => `Model${i}-api-NONE`);
  const alarms = addSharedStackAlarms(alarmStack, staging, staged, {
    functions: [
      { functionName: "papyrus-shared-staging-content-actions-aaaa", reserved: 10 },
      { functionName: "papyrus-shared-staging-provider-bbbb" },
    ],
    appSyncApiId: "apiid",
    tableNames,
    projectionDeadLetterQueueName: "dlq",
  });
  const list = Object.values<any>(Template.fromStack(alarmStack).toJSON().Resources).filter((r) => r.Type === "AWS::CloudWatch::Alarm").map((r) => r.Properties);
  assert.equal(list.length, alarms.length);
  for (const alarm of list) assert.ok(alarm.AlarmName.startsWith("papyrus-shared-staging-"), alarm.AlarmName);
  const names = list.map((a) => a.AlarmName as string);
  for (const kind of ["errors", "throttles", "concurrency", "appsync-5xx", "appsync-4xx", "dynamodb-throttles", "projection-dlq"]) assert.ok(names.some((n) => n.startsWith(`papyrus-shared-staging-${kind}-`)), kind);
  assert.equal(names.filter((n) => n.includes("-concurrency-")).length, 1, "the plumbing function has no reserved share to alarm against");
  assert.equal(names.filter((n) => n.includes("-dynamodb-throttles-")).length, 2, "seven tables are grouped five to an alarm");
  assert.ok(!names.some((n) => n.includes("-purged-paths-")), "no purge alarm until the stack has a distribution");
  const concurrency = list.find((a) => a.AlarmName.includes("-concurrency-"));
  assert.equal(concurrency.Threshold, Math.ceil(10 * staged.alarms.concurrencyShareOfReserved));
  assert.equal(concurrency.Period, staged.alarms.periodMinutes * 60);
  for (const alarm of list) assert.equal(alarm.AlarmActions, undefined, "alarms reach the operator through the default-bus listener, not an action");
}
{
  const app = new App();
  const alarmStack = new Stack(app, "AlarmsWithEdge", { env: { account: "111122223333", region: "us-east-1" } });
  const alarms = addSharedStackAlarms(alarmStack, staging, staged, { functions: [], appSyncApiId: "apiid", tableNames: [], distributionId: "E123" });
  const purge = Object.values<any>(Template.fromStack(alarmStack).toJSON().Resources).map((r) => r.Properties).find((p) => p?.AlarmName?.includes("-purged-paths-"));
  assert.ok(purge && alarms.length === 3 && purge.Threshold === staged.alarms.purgedPathsPerWeek && purge.Period === 7 * 24 * 3600);
}

// --- the deny on dedicated roles: one inline policy per role, no new resource ------------------------------------------------------
{
  const build = (deny: boolean) => {
    const app = new App();
    const stack = new Stack(app, "Dedicated", { env: { account: "111122223333", region: "us-east-1" } });
    const model = new Stack(new Stack(stack, "PapyrusCmsApi"), "Item");
    new iam.Role(stack, "Fn", { assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"), inlinePolicies: { own: new iam.PolicyDocument({ statements: [new iam.PolicyStatement({ actions: ["s3:GetObject"], resources: ["*"] })] }) } });
    new iam.Role(stack, "Bare", { assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com") });
    new iam.Role(model, "TableRole", { assumedBy: new iam.ServicePrincipal("appsync.amazonaws.com") });
    if (deny) assert.equal(addSharedStackDeny(stack, (s) => isModelDataStack(s, new Set(["Item"]))), 2);
    return { stack, model };
  };
  const without = build(false);
  const withDeny = build(true);
  const t0 = Template.fromStack(without.stack).toJSON();
  const t1 = Template.fromStack(withDeny.stack).toJSON();
  assert.deepEqual(Object.keys(t1.Resources), Object.keys(t0.Resources), "the deny adds no resource");
  const strip = (template: any) => {
    const copy = JSON.parse(JSON.stringify(template));
    for (const resource of Object.values<any>(copy.Resources)) {
      if (resource.Type !== "AWS::IAM::Role") continue;
      resource.Properties.Policies = (resource.Properties.Policies ?? []).filter((p: any) => p.PolicyName !== SHARED_DENY_POLICY_NAME);
      if (resource.Properties.Policies.length === 0) delete resource.Properties.Policies;
    }
    return copy;
  };
  assert.deepEqual(strip(t1), t0, "removing the deny gives the template back");
  const denied = Object.values<any>(t1.Resources).filter((r) => r.Type === "AWS::IAM::Role" && r.Properties.Policies?.some((p: any) => p.PolicyName === SHARED_DENY_POLICY_NAME));
  assert.equal(denied.length, 2);
  const modelTemplate = Template.fromStack(withDeny.model).toJSON();
  assert.ok(!JSON.stringify(modelTemplate).includes(SHARED_DENY_POLICY_NAME), "a per-model data stack is left alone");
}

// --- the deny's content (the app shell's copy is checked by scripts/test-infra-shared-stack-deny.ts) ----------------------------------------------------------------------------
const deny = sharedStackDenyPolicyDocument();
assert.ok(deny.Statement.every((statement) => statement.Effect === "Deny"));
assert.deepEqual(deny.Statement[0].Condition, { StringEquals: { "aws:ResourceTag/anthus:deployment": ["shared-prod", "shared-staging"] } });

console.log("shared stack tests passed");
