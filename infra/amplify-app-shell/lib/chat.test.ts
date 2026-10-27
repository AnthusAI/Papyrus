import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { App } from "aws-cdk-lib";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { PapyrusChatStack } from "./chat-stack";
import { parseSiteConfig, resolveChatLogGroupPrefix, resolveChatStackName, resolveStackName } from "./site-config";

// Executes infra/amplify-app-shell/features/per-site-private-chat.feature (run through scripts/test-infra-chat.ts).
const examples = path.resolve(__dirname, "../examples");
const example = (name: string, change: (config: any) => void = () => {}): any => {
  const config = JSON.parse(fs.readFileSync(path.join(examples, `${name}.site.json`), "utf8"));
  change(config);
  return config;
};
const siteNames = fs.readdirSync(examples).filter((name) => name.endsWith(".site.json")).map((name) => name.replace(/\.site\.json$/, ""));
const lambdaDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-chat-test-"));
for (const file of ["run-worker.js", "probe-worker.js"]) fs.writeFileSync(path.join(lambdaDirectory, file), "exports.handler = async () => ({});\n");

const resourcesOf = (template: any, type: string): any[] => Object.values<any>(template.Resources).filter((resource) => resource.Type === type);
function shellTemplate(raw: unknown): any {
  const config = parseSiteConfig(raw);
  const stack = new AmplifyAppShellStack(new App(), "Shell", config, { env: { account: "712236451410", region: "us-east-1" }, stackName: resolveStackName(config) });
  return JSON.parse(JSON.stringify((App.of(stack) as App).synth().getStackByName(stack.stackName).template));
}
function chatTemplate(raw: unknown): any {
  const config = parseSiteConfig(raw);
  const app = new App();
  const stack = new PapyrusChatStack(app, { config, env: { account: "712236451410", region: "us-east-1" }, lambdaAssetDirectory: lambdaDirectory });
  return JSON.parse(JSON.stringify(app.synth().getStackByName(stack.stackName).template));
}
const branchEnvironment = (template: any, branchName: string): Record<string, unknown> => {
  const branch = resourcesOf(template, "AWS::Amplify::Branch").find((resource) => resource.Properties.BranchName === branchName);
  return Object.fromEntries(branch.Properties.EnvironmentVariables.map((variable: any) => [variable.Name, variable.Value]));
};
const CHAT_NAMES = ["PAPYRUS_CHAT_MESSAGING_TABLE", "PAPYRUS_CHAT_CONVERSATIONS_TABLE", "PAPYRUS_CHAT_SESSION_BUCKET", "PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL", "PAPYRUS_CHAT_TURN_PROBES_QUEUE_URL", "PAPYRUS_CHAT_PRIVATE_BOT_ID", "PAPYRUS_CHAT_PRIVATE_BOT_NAME"];

// Scenario: a site with chat enabled gets the chat environment and a data stack
{
  const raw = example("anth-us");
  assert.equal(raw.chat.modelKeyParameter, "/papyrus/shipped/openai-api-key");
  const config = parseSiteConfig(raw);
  assert.equal(resolveChatStackName(config), "papyrus-chat-anth-us");
  const production = branchEnvironment(shellTemplate(raw), "main");
  assert.equal(production.PAPYRUS_PRIVATE_CHAT_ENABLED, "true");
  assert.deepEqual(production.PAPYRUS_CHAT_MESSAGING_TABLE, { "Fn::ImportValue": "papyrus-chat-anth-us:MessagingTableName" });
  assert.deepEqual(production.PAPYRUS_CHAT_SESSION_BUCKET, { "Fn::ImportValue": "papyrus-chat-anth-us:SessionBucketName" });
  assert.deepEqual(production.PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL, { "Fn::ImportValue": "papyrus-chat-anth-us:TurnRunsQueueUrl" });
  assert.equal(production.PAPYRUS_CHAT_PRIVATE_BOT_ID, "papyrus-private-assistant");

  const chat = chatTemplate(raw);
  assert.equal(resourcesOf(chat, "AWS::DynamoDB::Table").length, 2);
  const [bucket] = resourcesOf(chat, "AWS::S3::Bucket");
  assert.equal(bucket.Properties.VersioningConfiguration.Status, "Enabled");
  assert.equal(bucket.Properties.PublicAccessBlockConfiguration.BlockPublicPolicy, true);
  assert.equal(resourcesOf(chat, "AWS::SQS::Queue").length, 4);
  assert.equal(resourcesOf(chat, "AWS::Lambda::Function").length, 2);
  const mappings = resourcesOf(chat, "AWS::Lambda::EventSourceMapping");
  assert.equal(mappings.length, 2);
  assert.ok(mappings.every((mapping) => mapping.Properties.Enabled === true));
  for (const key of ["MessagingTableName", "ConversationIndexTableName", "SessionBucketName", "TurnRunsQueueUrl", "TurnProbesQueueUrl"]) {
    assert.equal(chat.Outputs[key].Export.Name, `papyrus-chat-anth-us:${key}`);
  }
  assert.deepEqual(Object.keys(chat.Parameters).filter((name) => name !== "BootstrapVersion").sort(), ["GatewayRoleArn", "PrivateAssistantBotId", "PrivateAssistantBotName"]);

  // Only the run worker may read the model key parameter; the gateway policy never names it.
  const parameterGrants = resourcesOf(chat, "AWS::IAM::Policy").filter((policy) => JSON.stringify(policy.Properties.PolicyDocument).includes("openai-api-key"));
  assert.equal(parameterGrants.length, 1);
  assert.ok(parameterGrants[0].Properties.Roles.some((role: any) => JSON.stringify(role).includes("RunWorkerRole")));
  assert.equal(JSON.stringify(chat).split("/papyrus/shipped/openai-api-key").length - 1, 3, "the parameter appears in the run worker grant, the run worker environment and one output only");
  const gateway = resourcesOf(chat, "AWS::IAM::Policy").find((policy) => policy.Properties.Roles.some((role: any) => JSON.stringify(role).includes("GatewayRoleArn")));
  assert.ok(gateway, "the gateway policy attaches to the role named by GatewayRoleArn");
  const gatewayActions = gateway.Properties.PolicyDocument.Statement.flatMap((statement: any) => [statement.Action].flat());
  assert.ok(!gatewayActions.some((action: string) => action.startsWith("ssm:") || action.endsWith("*")), "the gateway has no SSM access and no wildcard action");
}

// Scenario: the staging branch never gets private chat
{
  const staging = branchEnvironment(shellTemplate(example("p-apyr-us")), "staging");
  assert.equal(staging.PAPYRUS_PRIVATE_CHAT_ENABLED, "false");
  assert.deepEqual(CHAT_NAMES.filter((name) => name in staging), []);
}

// Scenario: a site without chat gets neither
{
  const withoutBlock = example("anth-us", (config) => delete config.chat);
  const disabled = example("anth-us", (config) => (config.chat.enabled = false));
  for (const raw of [withoutBlock, disabled]) {
    const production = branchEnvironment(shellTemplate(raw), "main");
    assert.equal(production.PAPYRUS_PRIVATE_CHAT_ENABLED, "false");
    assert.deepEqual(CHAT_NAMES.filter((name) => name in production), []);
    assert.equal(resolveChatStackName(parseSiteConfig(raw)), undefined);
    assert.throws(() => chatTemplate(raw), /does not enable chat/);
  }
}

// Scenario: the chat block cannot be contradicted by hand-set variables
assert.throws(() => parseSiteConfig(example("anth-us", (config) => (config.cms.environment.PAPYRUS_PRIVATE_CHAT_ENABLED = "false"))), /cms\.environment\.PAPYRUS_PRIVATE_CHAT_ENABLED/);
assert.throws(() => parseSiteConfig(example("anth-us", (config) => (config.cms.environment.PAPYRUS_CHAT_SESSION_BUCKET = "x"))), /cms\.environment\.PAPYRUS_CHAT_SESSION_BUCKET/);
// Without chat, the existing hand-managed flag keeps working.
assert.equal(branchEnvironment(shellTemplate(example("anth-us", (config) => { delete config.chat; config.cms.environment.PAPYRUS_PRIVATE_CHAT_ENABLED = "true"; })), "main").PAPYRUS_PRIVATE_CHAT_ENABLED, "true");

// Scenario: chat needs a CMS and a model key parameter
assert.throws(() => parseSiteConfig(example("anth-us", (config) => delete config.chat.modelKeyParameter)), /chat\.modelKeyParameter/);
assert.throws(() => parseSiteConfig(example("anth-us", (config) => (config.chat.modelKeyParameter = "not-a-path"))), /chat\.modelKeyParameter/);
assert.throws(() => parseSiteConfig(example("anth-us", (config) => (config.chat.enabled = "yes"))), /chat\.enabled/);
assert.throws(() => parseSiteConfig(example("anth-us", (config) => (config.chat.extra = 1))), /chat\.extra/);
assert.throws(() => parseSiteConfig(example("anth-us", (config) => (config.chat.workerCodeS3Key = "abc"))), /chat\.workerCodeS3Key/);
assert.throws(() => parseSiteConfig({ siteId: "reader-only", repository: "https://github.com/example/x", brand: "x", frontend: "markus-static", papyrusVersion: "5.42.1", hostedZoneId: "Z10285921B1G7MVRV06W9", reader: { domainName: "x.example.test", buildCommand: "npm run build", baseDirectory: "out" }, chat: { enabled: true, modelKeyParameter: "/papyrus/x/openai-api-key" } }), /chat\.enabled.*requires cms/);
assert.throws(() => new PapyrusChatStack(new App(), { config: parseSiteConfig(example("p-apyr-us", (config) => delete config.chat.workerCodeS3Key)), env: { account: "712236451410", region: "us-east-1" } }), /bundle the chat workers first/);

// Scenario: two sites in one account do not share chat storage or log groups
{
  const enabled = siteNames.map((name) => parseSiteConfig(example(name))).filter((config) => config.chat?.enabled);
  assert.deepEqual(enabled.map((config) => config.siteId).sort(), ["anth-us", "dataparade", "distinctive", "p-apyr-us", "pilobol-us", "shipped", "threat-intelligence"], "every Papyrus site example enables chat");
  const names = enabled.map((config) => resolveChatStackName(config));
  const prefixes = enabled.map((config) => resolveChatLogGroupPrefix(config));
  assert.equal(new Set(names).size, names.length, "stack names are unique");
  assert.equal(new Set(prefixes).size, prefixes.length, "worker log group prefixes are unique");
  for (const config of enabled) {
    assert.ok(/^\/(papyrus\/[a-z0-9-]+\/openai-api-key|amplify\/shared\/[a-z0-9]+\/OPENAI_API_KEY)$/.test(config.chat!.modelKeyParameter), `${config.siteId} reuses an existing model key parameter`);
  }
}

// Scenario: the activated p.apyr.us stack is adopted without replacing anything
{
  const activated = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../shared-chat-runtime/cdk/PapyrusChatDataCandidate.template.json"), "utf8"));
  const generated = chatTemplate(example("p-apyr-us"));
  assert.equal(resolveChatStackName(parseSiteConfig(example("p-apyr-us"))), "PapyrusChatDataCandidate");
  const normalize = (resource: any) => {
    const copy = JSON.parse(JSON.stringify(resource));
    delete copy.Metadata;
    const statements = copy.Properties?.PolicyDocument?.Statement;
    if (statements) copy.Properties.PolicyDocument.Statement = [...statements].sort((a: any, b: any) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    return copy;
  };
  assert.deepEqual(Object.keys(generated.Resources).sort(), Object.keys(activated.Resources).sort(), "no resource is added, removed or renamed (a changed logical id would replace it)");
  for (const [logicalId, resource] of Object.entries<any>(activated.Resources)) {
    const expected = normalize(resource);
    // The activated template is the reviewed candidate; the queue mappings were enabled live afterwards.
    if (resource.Type === "AWS::Lambda::EventSourceMapping") expected.Properties.Enabled = true;
    assert.deepEqual(normalize(generated.Resources[logicalId]), expected, `${logicalId} is unchanged`);
  }
  for (const key of Object.keys(activated.Outputs)) {
    assert.deepEqual({ ...generated.Outputs[key], Export: undefined }, { ...activated.Outputs[key], Export: undefined, ...(key === "FeatureDefault" ? { Value: generated.Outputs[key].Value } : {}) }, `output ${key} keeps its value`);
  }
  assert.deepEqual(Object.keys(generated.Outputs).sort(), Object.keys(activated.Outputs).sort());
}

console.log("per-site private chat infra tests passed");
