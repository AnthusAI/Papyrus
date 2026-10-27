const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const templatePath = path.resolve(__dirname, process.argv[2] || "PapyrusChatDataCandidate.template.json");
const candidateConfiguration = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../../config/papyrus-chat-candidate.json"), "utf8"));
const modelKeyParameter = candidateConfiguration.modelKeyParameter;
const template = JSON.parse(fs.readFileSync(templatePath, "utf8"));
const resources = Object.values(template.Resources);
const ofType = (type) => resources.filter((resource) => resource.Type === type);
const eventMappings = ofType("AWS::Lambda::EventSourceMapping");
const functions = ofType("AWS::Lambda::Function");
const policyResources = ofType("AWS::IAM::Policy");
const policies = policyResources.map((resource) => resource.Properties.PolicyDocument.Statement).flat();
const actionList = (statement) => (Array.isArray(statement.Action) ? statement.Action : [statement.Action]).sort();
const refersTo = (value, logicalId) => JSON.stringify(value).includes(logicalId);
const statementsFor = (policy, logicalId) => policy.Properties.PolicyDocument.Statement.filter((statement) => refersTo(statement.Resource, logicalId));
const assertExactActions = (statements, expected, label) => {
  const actual = [...new Set(statements.flatMap(actionList))].sort();
  assert.deepEqual(actual, [...expected].sort(), `${label} actions`);
};
const policyByName = (prefix) => {
  const result = policyResources.find((policy) => policy.Properties.PolicyName.startsWith(prefix));
  assert.ok(result, `missing policy ${prefix}`);
  return result;
};
const roleIdByDescription = (description) => {
  const entry = Object.entries(template.Resources).find(([, resource]) => resource.Type === "AWS::IAM::Role" && resource.Properties.Description === description);
  assert.ok(entry, `missing role ${description}`);
  return entry[0];
};
const policyForRole = (roleLogicalId) => {
  const result = policyResources.find((policy) => (policy.Properties.Roles || []).some((role) => role.Ref === roleLogicalId));
  assert.ok(result, `missing role policy for ${roleLogicalId}`);
  return result;
};

assert.equal(ofType("AWS::DynamoDB::Table").length, 2);
assert.equal(ofType("AWS::S3::Bucket").length, 1);
assert.equal(ofType("AWS::SQS::Queue").length, 4);
assert.ok(policies.some((statement) => refersTo(statement.Resource, "PrivateMessagingAEAE53CD")));
assert.ok(policies.some((statement) => refersTo(statement.Resource, "PrivateConversationIndex81B3261A")));
assert.ok(policies.some((statement) => refersTo(statement.Resource, "PrivateSessionObjects8FA7D9DB")));
assert.ok(policies.every((statement) => JSON.stringify(statement.Resource) !== '"*"'));

if (path.basename(templatePath) === "PapyrusChatSyntheticAdapterTest.template.json") {
  const templateText = JSON.stringify(template);
  assert.equal(functions.length, 1, "synthetic mode must deploy only its manual test harness");
  assert.equal(eventMappings.length, 0, "synthetic mode must have no queue consumer mappings");
  assert.equal(ofType("AWS::Events::Rule").length, 0, "synthetic mode must have no EventBridge trigger");
  assert.equal(ofType("AWS::Scheduler::Schedule").length, 0, "synthetic mode must have no scheduled trigger");
  assert.equal(ofType("AWS::Lambda::Permission").length, 0, "synthetic mode must grant no external Lambda invocation permission");
  assert.ok(!Object.hasOwn(template.Parameters, "GatewayRoleArn"), "synthetic mode must not accept an arbitrary caller role");
  assert.ok(!Object.hasOwn(template.Parameters, "CmsComputeRoleArn"), "synthetic mode must not accept the production CMS role");
  assert.ok(!templateText.includes("amplify/shared/papyrus/OPENAI_API_KEY"), "synthetic mode must not name or grant the model secret");
  assert.ok(!templateText.includes(modelKeyParameter), "synthetic mode must not name or grant the site model secret");
  assert.equal(template.Outputs.SyntheticAdapterTestOnly.Value, "true");
  assert.equal(template.Outputs.SyntheticAdapterInvocation.Value, "Explicit Lambda Invoke only; no event source or schedule");
  assert.equal(template.Outputs.FeatureDefault.Value, "disabled; set PAPYRUS_PRIVATE_CHAT_ENABLED=true only after review");
  const role = Object.values(template.Resources).find((resource) => resource.Type === "AWS::IAM::Role" && resource.Properties.Description.startsWith("Synthetic adapter test only;"));
  assert.ok(role, "synthetic mode must create a dedicated test role");
  const gatewayPolicy = policyResources.find((policy) => (policy.Properties.Roles || []).some((entry) => refersTo(entry, Object.entries(template.Resources).find(([, resource]) => resource === role)[0])));
  assert.ok(gatewayPolicy, "synthetic test role must receive its isolated adapter permissions");
  assert.equal(ofType("AWS::IAM::Role").length, 1, "synthetic mode must contain only the dedicated test role");
  const harness = functions[0];
  const runtimeTemplate = JSON.parse(fs.readFileSync(path.join(__dirname, "PapyrusChatDataCandidate.template.json"), "utf8"));
  const runtimeFunction = Object.values(runtimeTemplate.Resources).find((resource) => resource.Type === "AWS::Lambda::Function" && resource.Properties.Handler === "run-worker.handler");
  assert.notEqual(harness.Properties.Code.S3Key, runtimeFunction.Properties.Code.S3Key, "synthetic tests must not share a bundle with runtime workers");
  assert.equal(harness.Properties.Handler, "synthetic-adapter-test.handler");
  assert.equal(harness.Properties.Runtime, "nodejs22.x");
  assert.ok(refersTo(harness.Properties.Role, Object.entries(template.Resources).find(([, resource]) => resource === role)[0]), "harness must use the dedicated synthetic role");
  assert.ok(!Object.hasOwn(harness.Properties.Environment.Variables, "OPENAI_API_KEY_PARAMETER"), "harness must not receive model configuration");
  assertExactActions(statementsFor(gatewayPolicy, "PrivateMessagingAEAE53CD"), [
    "dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:UpdateItem",
  ], "synthetic gateway messaging table");
  assertExactActions(statementsFor(gatewayPolicy, "PrivateConversationIndex81B3261A"), [
    "dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:Query",
  ], "synthetic gateway conversation index");
  assertExactActions(statementsFor(gatewayPolicy, "PrivateSessionObjects8FA7D9DB"), ["s3:GetObject", "s3:PutObject"], "synthetic adapter objects");
  assertExactActions(statementsFor(gatewayPolicy, "TurnRuns2149914B"), ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], "synthetic run queue");
  assertExactActions(statementsFor(gatewayPolicy, "TurnProbes3E4AFDA6"), ["sqs:SendMessage"], "synthetic probe queue");
  assert.ok(role.Properties.AssumeRolePolicyDocument.Statement.every((statement) => statement.Principal.Service === "lambda.amazonaws.com"), "synthetic role must only trust Lambda test harnesses");
  console.log("PASS: synthetic adapter template has an isolated manual harness, no production gateway/worker, no model secret or automatic trigger, and disabled feature");
  process.exit(0);
}

assert.equal(functions.length, 2);
assert.equal(eventMappings.length, 2);
assert.ok(eventMappings.every((mapping) => mapping.Properties.Enabled === false));
assert.ok(functions.every((fn) => fn.Properties.Runtime === "nodejs22.x"));
assert.ok(functions.some((fn) => fn.Properties.Handler === "run-worker.handler"));
assert.ok(functions.some((fn) => fn.Properties.Handler === "probe-worker.handler"));

const gateway = policyByName("PapyrusChatGatewayRole");
assertExactActions(statementsFor(gateway, "PrivateMessagingAEAE53CD"), [
  "dynamodb:BatchGetItem", "dynamodb:ConditionCheckItem", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:UpdateItem",
], "gateway messaging table");
assertExactActions(statementsFor(gateway, "PrivateConversationIndex81B3261A"), [
  "dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:Query",
], "gateway conversation index");
assertExactActions(statementsFor(gateway, "PrivateSessionObjects8FA7D9DB"), ["s3:GetObject"], "gateway transcript objects");
assert.ok(!gateway.Properties.PolicyDocument.Statement.some((statement) => actionList(statement).includes("ssm:GetParameter")), "gateway must not read the model secret");

const probeRoleId = roleIdByDescription("Private Papyrus chat deadline/recovery worker.");
const probe = policyForRole(probeRoleId);
assertExactActions(statementsFor(probe, "PrivateMessagingAEAE53CD"), [
  "dynamodb:BatchGetItem", "dynamodb:DeleteItem", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:UpdateItem",
], "probe messaging table");
assertExactActions(statementsFor(probe, "PrivateConversationIndex81B3261A"), [
  "dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:Query",
], "probe conversation index");

const runRoleId = roleIdByDescription("Private Papyrus computerless chat run worker.");
const run = policyForRole(runRoleId);
const ownershipChecks = policies.filter((statement) => actionList(statement).includes("dynamodb:ConditionCheckItem"));
assert.deepEqual(ownershipChecks, [
  { Action: "dynamodb:ConditionCheckItem", Resource: { "Fn::GetAtt": ["PrivateMessagingAEAE53CD", "Arn"] }, Effect: "Allow" },
  { Action: "dynamodb:ConditionCheckItem", Resource: { "Fn::GetAtt": ["PrivateConversationIndex81B3261A", "Arn"] }, Effect: "Allow" },
], "only the two runtime ownership checks are permitted, without indexes or wildcard resources");
assert.ok(gateway.Properties.PolicyDocument.Statement.includes(ownershipChecks[0]));
assert.ok(run.Properties.PolicyDocument.Statement.includes(ownershipChecks[1]));
assertExactActions(statementsFor(run, modelKeyParameter.slice(1)), ["ssm:GetParameter"], "site-scoped run-worker model key");
const modelKeyReaders = policies.filter((statement) => actionList(statement).includes("ssm:GetParameter"));
assert.equal(modelKeyReaders.length, 1, "only one policy statement may read any model-key parameter");
assert.ok(JSON.stringify(modelKeyReaders[0].Resource).includes(modelKeyParameter.slice(1)), "the model-key read must target only the configured site parameter");
const runFunction = functions.find((fn) => fn.Properties.Handler === "run-worker.handler");
assert.equal(runFunction.Properties.Environment.Variables.OPENAI_API_KEY_PARAMETER, modelKeyParameter);
assert.equal(template.Outputs.FeatureDefault.Value, "disabled; set PAPYRUS_PRIVATE_CHAT_ENABLED=true only after review");
console.log("PASS: Papyrus chat candidate resources, exact gateway/probe IAM scopes, model-secret isolation and disabled mappings");
