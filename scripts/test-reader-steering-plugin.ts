import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { AttributeType, Table } from "aws-cdk-lib/aws-dynamodb";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { schemaWithPlugins } from "../amplify/data/schema";
import { KNOWN_PLUGINS, resolvePlugins } from "../amplify/plugins/registry";
import { resolveReaderSteeringConfig } from "../amplify/plugins/reader-steering/config";
import {
  interimSubjectsAllowedAtSynth,
  readerActionsSettings,
  readerSnapshotSettings,
  readerSteeringManifest,
  readerSteeringPlugin,
} from "../amplify/plugins/reader-steering/papyrus.plugin";
import { readerSteeringSchemaDefinitions } from "../amplify/plugins/reader-steering/schema";
import { wirePlugins } from "../amplify/plugins/wire";

const computeRoleArn = "arn:aws:iam::123456789012:role/AmplifyComputeRole-abc";
const base = { name: "reader-steering", computeRoleArn };

assert.equal(KNOWN_PLUGINS["reader-steering"], readerSteeringPlugin);
assert.throws(() => resolvePlugins(["reader-steering"]), /computeRoleArn/, "the compute role is required");
assert.throws(() => resolveReaderSteeringConfig({ ...base, computeRoleArn: "arn:aws:iam::123:role/x" }), /computeRoleArn/);
assert.throws(() => resolveReaderSteeringConfig({ ...base, computeRoleArn: "*" }), /computeRoleArn/);

const defaults = resolvePlugins([base])[0].config;
assert.deepEqual(defaults, {
  computeRoleArn,
  dimensions: [],
  limits: { actionsPerHour: 120, newAccountHours: 24, newAccountDivisor: 3 },
  reservedHandles: [],
  karma: { upvoteWeight: 1, usedItWeight: 2 },
  ranking: { halfLifeHours: 48, risingWindowHours: 6, readerMinimum: 5, editorWeight: 0.5 },
  snapshot: { schedule: false, intervalHours: 6, hypeMinimum: 5 },
  retirementPoll: false,
});

const shipped = resolveReaderSteeringConfig({
  ...base,
  dimensions: ["real", "useful", "notable", "novel", "real"],
  limits: { actionsPerHour: 60 },
  reservedHandles: ["shipped-team"],
  karma: { usedItWeight: 3 },
  snapshot: { schedule: true },
});
assert.deepEqual(shipped.dimensions, ["real", "useful", "notable", "novel"]);
assert.equal(shipped.limits.actionsPerHour, 60);
assert.equal(shipped.limits.newAccountHours, 24);
assert.equal(shipped.karma.usedItWeight, 3);
assert.equal(shipped.karma.upvoteWeight, 1);
assert.equal(shipped.snapshot.schedule, true);

const withHype = resolveReaderSteeringConfig({ ...base, dimensions: ["real", "useful", "notable", "novel"], hypeGap: { plus: ["notable", "novel"], minus: ["real", "useful"] } });
assert.deepEqual(withHype.hypeGap, { plus: ["notable", "novel"], minus: ["real", "useful"] });
assert.equal("hypeGap" in defaults, false, "no hypeGap configuration means no hype gap");
assert.deepEqual(JSON.parse(JSON.stringify(readerSnapshotSettings(withHype))).hypeGap, { plus: ["notable", "novel"], minus: ["real", "useful"] }, "the snapshot task gets the groups");
assert.equal("hypeGap" in readerSnapshotSettings(shipped), false);

for (const bad of [
  { dimensions: ["real", "notable"], hypeGap: { plus: ["notable"] } },
  { dimensions: ["real", "notable"], hypeGap: { plus: [], minus: ["real"] } },
  { dimensions: ["real", "notable"], hypeGap: { plus: ["notable"], minus: ["useful"] } },
  { dimensions: ["real", "notable"], hypeGap: { plus: ["notable", "real"], minus: ["real"] } },
  { dimensions: ["real", "notable"], hypeGap: { plus: ["notable"], minus: ["real"], extra: 1 } },
  { dimensions: ["real", "notable"], hypeGap: "notable" },
  { dimensions: ["Real"] },
  { dimensions: ["up"] },
  { dimensions: ["used-it"] },
  { dimensions: "real" },
  { dimensions: ["x".repeat(25)] },
  { limits: { actionsPerHour: 0 } },
  { limits: { actionsPerHour: 1.5 } },
  { limits: { burst: 5 } },
  { limits: [] },
  { karma: { upvoteWeight: -1 } },
  { ranking: { editorWeight: 2 } },
  { snapshot: { schedule: "yes" } },
  { snapshot: { intervalHours: 0 } },
  { reservedHandles: ["Bad Handle"] },
  { retirementPoll: true },
  { waf: true },
]) {
  assert.throws(() => resolveReaderSteeringConfig({ ...base, ...bad } as never), /reader-steering/, JSON.stringify(bad));
}

const definitions = readerSteeringSchemaDefinitions() as Record<string, unknown>;
assert.deepEqual(Object.keys(definitions).sort(), [...readerSteeringManifest.models].sort(), "the schema defines exactly the manifest's models");
assert.deepEqual(readerSteeringManifest.guest.mutations, [], "a guest can call nothing");
assert.deepEqual(readerSteeringManifest.mutations, []);

const schemaSource = JSON.stringify(Object.values(definitions).map((model) => (model as { data?: { authorization?: unknown } }).data?.authorization));
assert.equal(/guest|public|apiKey|private|custom/i.test(schemaSource), false, "no guest, API key or custom rule on any reader model");

const settings = readerActionsSettings(shipped, false);
assert.deepEqual(settings, {
  dimensions: ["real", "useful", "notable", "novel"],
  limits: shipped.limits,
  reservedHandles: ["shipped-team"],
  allowInterimSubjects: false,
  snapshotDebounceSeconds: 60,
});
assert.equal(readerSnapshotSettings(shipped).hypeMinimum, 5);
assert.equal(JSON.stringify(settings).includes(computeRoleArn), false, "the function settings do not carry the role");
assert.equal(interimSubjectsAllowedAtSynth({ SITE_ENV: "production" }), false);
assert.equal(interimSubjectsAllowedAtSynth({ SITE_ENV: "development", NODE_ENV: "production" }), false);
assert.equal(interimSubjectsAllowedAtSynth({}), false);
assert.equal(interimSubjectsAllowedAtSynth({ SITE_ENV: "development" }), true);
assert.deepEqual(readerSteeringPlugin.publicSettings(shipped), { contract: 1, dimensions: ["real", "useful", "notable", "novel"] });

function synthesize(config = shipped, environment: Record<string, string> = {}) {
  const app = new App();
  const awsEnvironment = { account: "123456789012", region: "us-east-1" };
  const stack = new Stack(app, "Data", { env: awsEnvironment });
  const lambdaFor = (id: string) => new Function(stack, id, { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x") });
  const readerLambda = lambdaFor("ReaderActions");
  const contentActions = lambdaFor("ContentActions");
  const tables = Object.fromEntries(
    ["ReaderProfile", "ReaderHandle", "ReaderVote", "PublishedItem"].map((name) => [name, new Table(stack, name, { partitionKey: { name: "id", type: AttributeType.STRING } })]),
  );
  const outputs: unknown[] = [];
  const backend = {
    readerActions: { resources: { lambda: readerLambda } },
    data: { resources: { tables, graphqlApi: { apiId: "api" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://x.test/graphql" } } } },
    createStack: (name: string) => new Stack(app, name, { env: awsEnvironment }),
    addOutput: (value: unknown) => outputs.push(value),
  };
  const previous = { ...process.env };
  Object.assign(process.env, environment);
  try {
    wirePlugins(backend, [{ plugin: readerSteeringPlugin, config }], contentActions);
  } finally {
    for (const key of Object.keys(environment)) if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
  }
  return { template: Template.fromStack(stack), outputs, stacks: app.node.children.filter((child): child is Stack => child instanceof Stack) };
}

const { template, outputs } = synthesize(shipped, { SITE_ENV: "production" });
template.hasResourceProperties("AWS::Lambda::Permission", {
  Action: "lambda:InvokeFunction",
  Principal: computeRoleArn,
  FunctionName: Match.anyValue(),
});
const permissions = Object.values(template.findResources("AWS::Lambda::Permission")) as Array<{ Properties: { Principal: string; Action: string } }>;
assert.deepEqual(permissions.filter((permission) => permission.Properties.Principal === computeRoleArn).length, 1, "the compute role may invoke one function");
assert.equal(permissions.filter((permission) => permission.Properties.Principal === "*").length, 0, "nothing is invokable by everyone");
const readerEnvironments = Object.values(template.findResources("AWS::Lambda::Function")).map((resource) => (resource as { Properties: { Environment?: { Variables: Record<string, string> } } }).Properties.Environment?.Variables ?? {});
const readerVariables = readerEnvironments.find((variables) => variables.PAPYRUS_READER_SETTINGS) as Record<string, string>;
assert.ok(readerVariables, "the function gets its settings");
for (const name of ["PAPYRUS_READER_PROFILE_TABLE", "PAPYRUS_READER_HANDLE_TABLE", "PAPYRUS_READER_VOTE_TABLE", "PAPYRUS_READER_PUBLISHED_ITEM_TABLE", "PAPYRUS_READER_SNAPSHOT_FUNCTION_ARN", "PAPYRUS_READER_SCHEDULER_ROLE_ARN"]) {
  assert.ok(name in readerVariables, `${name} is set`);
}
assert.equal(JSON.parse(readerVariables.PAPYRUS_READER_SETTINGS).allowInterimSubjects, false, "a production synth refuses interim subjects");
assert.equal(readerEnvironments.filter((variables) => variables.PAPYRUS_READER_SNAPSHOT_SETTINGS).length, 1, "content-actions gets the snapshot settings");
const published = outputs.map((output) => (output as { custom: Record<string, { actionsFunction?: unknown }> }).custom.readerSteering).filter(Boolean);
assert.equal(published.length, 1, "the function name is published for the CMS routes");
assert.ok(published[0].actionsFunction);

const statements = Object.values(template.findResources("AWS::IAM::Policy")).flatMap(
  (policy) => (policy as { Properties: { PolicyDocument: { Statement: Array<{ Action: string | string[]; Resource: unknown }> } } }).Properties.PolicyDocument.Statement,
);
const writeActions = /^dynamodb:(PutItem|UpdateItem|DeleteItem|BatchWriteItem)$/;
const writesPublishedItems = statements.some((statement) => {
  const actions = ([] as string[]).concat(statement.Action);
  return actions.some((action) => writeActions.test(action)) && JSON.stringify(statement.Resource).includes("PublishedItem");
});
assert.equal(writesPublishedItems, false, "reader-actions only reads PublishedItem");
template.resourceCountIs("AWS::WAFv2::WebACL", 0);

function eventRules(result: ReturnType<typeof synthesize>) {
  return result.stacks.flatMap((stack) => Object.values(Template.fromStack(stack).findResources("AWS::Events::Rule")));
}
assert.equal(eventRules(synthesize({ ...shipped, snapshot: { ...shipped.snapshot, schedule: false } })).length, 0, "no schedule unless the site enables it");
const scheduled = eventRules(synthesize({ ...shipped, snapshot: { ...shipped.snapshot, schedule: true, intervalHours: 6 } }));
assert.equal(scheduled.length, 1, "one rule when the site enables the schedule");
const rule = scheduled[0] as { Properties: { ScheduleExpression: string; Targets: Array<{ Input: string }> } };
assert.equal(rule.Properties.ScheduleExpression, "rate(6 hours)");
assert.deepEqual(JSON.parse(rule.Properties.Targets[0].Input), { projectionTask: { task: "reader-snapshot" } });

// Reserved concurrency: none unless the site sets it.
const reservedValues = (result: ReturnType<typeof synthesize>) =>
  Object.values(result.template.findResources("AWS::Lambda::Function")).map((resource) => (resource as { Properties: { ReservedConcurrentExecutions?: number } }).Properties.ReservedConcurrentExecutions);
assert.deepEqual(reservedValues(synthesize(shipped)).filter((value) => value !== undefined), [], "no reserved concurrency by default");
assert.deepEqual(reservedValues(synthesize({ ...shipped, reservedConcurrency: 3 })).filter((value) => value !== undefined), [3], "a site may reserve some");
for (const bad of [0, -1, 1.5, "10", null]) {
  assert.throws(() => resolveReaderSteeringConfig({ name: "reader-steering", computeRoleArn, reservedConcurrency: bad }), /reservedConcurrency/, `rejects ${JSON.stringify(bad)}`);
}
assert.equal("reservedConcurrency" in resolveReaderSteeringConfig({ name: "reader-steering", computeRoleArn }), false);

// Trailing-edge debounce: a scheduler role, exactly-scoped permissions, no direct invoke of content-actions.
const debounceTemplates = synthesize(shipped).stacks.map((stack) => Template.fromStack(stack));
const schedulerRoles = debounceTemplates.flatMap((candidate) => Object.values(candidate.findResources("AWS::IAM::Role"))).filter((role) =>
  JSON.stringify((role as { Properties: { AssumeRolePolicyDocument: unknown } }).Properties.AssumeRolePolicyDocument).includes("scheduler.amazonaws.com"));
assert.equal(schedulerRoles.length, 1, "one role for the Scheduler to assume");
const debounceStatements = debounceTemplates.flatMap((candidate) => Object.values(candidate.findResources("AWS::IAM::Policy"))).flatMap(
  (policy) => (policy as { Properties: { PolicyDocument: { Statement: Array<{ Action: string | string[]; Resource: unknown }> } } }).Properties.PolicyDocument.Statement,
);
const createSchedule = debounceStatements.filter((statement) => ([] as string[]).concat(statement.Action).includes("scheduler:CreateSchedule"));
assert.equal(createSchedule.length, 1);
assert.match(JSON.stringify(createSchedule[0].Resource), /schedule\/default\/papyrus-reader-snapshot-\*/, "only this feature's schedules");
const passRole = debounceStatements.filter((statement) => ([] as string[]).concat(statement.Action).includes("iam:PassRole"));
assert.equal(passRole.length, 1, "reader-actions may pass exactly the scheduler role");
assert.equal(JSON.stringify(passRole[0].Resource).includes("*"), false);
assert.equal(
  debounceStatements.some((statement) => ([] as string[]).concat(statement.Action).includes("lambda:InvokeFunction") && JSON.stringify(statement.Resource).includes("ReaderActions")),
  false,
);

const development = synthesize(shipped, { SITE_ENV: "development" });
const developmentSettings = Object.values(development.template.findResources("AWS::Lambda::Function"))
  .map((resource) => (resource as { Properties: { Environment?: { Variables: Record<string, string> } } }).Properties.Environment?.Variables?.PAPYRUS_READER_SETTINGS)
  .find(Boolean) as string;
assert.equal(JSON.parse(developmentSettings).allowInterimSubjects, true, "a development synth allows interim subjects");

console.log("reader steering plugin ok");


const transformed = schemaWithPlugins(readerSteeringSchemaDefinitions()).transform().schema;
for (const model of readerSteeringManifest.models) {
  const declaration = new RegExp(`type ${model} @model[^\\n]*`).exec(transformed);
  assert.ok(declaration, `${model} is a model in the deployed schema`);
  assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)/.test(declaration[0]), false, `${model} has no guest, API key or IAM rule: ${declaration[0]}`);
  assert.match(declaration[0], /groups: \["editor"\]|groups: \["admin"\]/);
}
console.log("reader steering schema ok");
