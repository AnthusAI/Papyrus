const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const template = JSON.parse(fs.readFileSync(path.join(__dirname, "PapyrusChatDataCandidate.template.json"), "utf8"));
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
assert.equal(functions.length, 2);
assert.equal(eventMappings.length, 2);
assert.ok(eventMappings.every((mapping) => mapping.Properties.Enabled === false));
assert.ok(functions.every((fn) => fn.Properties.Runtime === "nodejs22.x"));
assert.ok(functions.some((fn) => fn.Properties.Handler === "run-worker.handler"));
assert.ok(functions.some((fn) => fn.Properties.Handler === "probe-worker.handler"));
assert.ok(policies.some((statement) => refersTo(statement.Resource, "PrivateMessagingAEAE53CD")));
assert.ok(policies.some((statement) => refersTo(statement.Resource, "PrivateConversationIndex81B3261A")));
assert.ok(policies.some((statement) => refersTo(statement.Resource, "PrivateSessionObjects8FA7D9DB")));
assert.ok(policies.every((statement) => JSON.stringify(statement.Resource) !== '"*"'));

const gateway = policyByName("PapyrusChatGatewayRole");
assertExactActions(statementsFor(gateway, "PrivateMessagingAEAE53CD"), [
  "dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:UpdateItem",
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
assert.ok(statementsFor(run, "amplify/shared/papyrus/OPENAI_API_KEY").some((statement) => actionList(statement).includes("ssm:GetParameter")), "only the run worker should read the configured model parameter");
assert.equal(template.Outputs.FeatureDefault.Value, "disabled; set PAPYRUS_PRIVATE_CHAT_ENABLED=true only after review");
console.log("PASS: Papyrus chat candidate resources, exact gateway/probe IAM scopes, model-secret isolation and disabled mappings");
