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
  ranking: {
    halfLifeHours: 48, risingWindowHours: 6, readerMinimum: 5, editorWeight: 0.5,
    combination: "blend", shrinkageK: 20, readerShareCap: 0.4, newAccountWeight: 1, risingMinimumAccountHours: 0,
  },
  snapshot: { schedule: false, intervalHours: 6, hypeMinimum: 5 },
  submissions: { perDay: 10, similarHours: 48, kinds: ["link"], itemType: "brief", section: "unsectioned" },
  subjects: { types: ["item", "submission"] },
  moderation: { mode: "human", preModeration: false, reportsPerDay: 20 },
  comments: { perHour: 30, editWindowMinutes: 10, maximumLength: 2000, maximumLinks: 3 },
  retirementPoll: false,
});

assert.deepEqual(resolveReaderSteeringConfig({ ...base, subjects: { types: ["item", "proposal", "story", "proposal"] } }).subjects.types, ["item", "proposal", "story"]);
assert.throws(() => resolveReaderSteeringConfig({ ...base, subjects: { types: ["person"] } }), /subjects\.types/, "an unknown subject type is refused");
assert.throws(() => resolveReaderSteeringConfig({ ...base, subjects: { types: [] } }), /subjects\.types/, "at least one subject type");
assert.throws(() => resolveReaderSteeringConfig({ ...base, subjects: { kinds: ["item"] } }), /Unknown reader-steering plugin subjects settings/);
assert.deepEqual((readerSteeringPlugin.publicSettings(resolveReaderSteeringConfig({ ...base, subjects: { types: ["item", "proposal"] } })) as { subjects: unknown }).subjects, { types: ["item", "proposal"] }, "the browser is told the enabled types");
assert.deepEqual(readerActionsSettings(resolveReaderSteeringConfig({ ...base, subjects: { types: ["proposal"] } }), false).subjects, { types: ["proposal"] }, "the actions function is told the enabled types");
assert.deepEqual(readerSnapshotSettings(resolveReaderSteeringConfig({ ...base, subjects: { types: ["proposal"] } })).subjects, { types: ["proposal"] }, "the snapshot is told the enabled types");

const tuned = resolveReaderSteeringConfig({ ...base, comments: { perHour: 5, editWindowMinutes: 0, maximumLinks: 0 } });
assert.deepEqual(tuned.comments, { perHour: 5, editWindowMinutes: 0, maximumLength: 2000, maximumLinks: 0 });

const withKinds = resolveReaderSteeringConfig({ ...base, submissions: { perDay: 20, kinds: ["article", "tool", "article"] } });
assert.deepEqual(withKinds.submissions, { perDay: 20, similarHours: 48, kinds: ["article", "tool"], itemType: "brief", section: "unsectioned" });
assert.deepEqual(resolveReaderSteeringConfig({ ...base, submissions: { itemType: "link", section: "tools" } }).submissions, { perDay: 10, similarHours: 48, kinds: ["link"], itemType: "link", section: "tools" });

assert.deepEqual(resolveReaderSteeringConfig({ ...base, moderation: { mode: "off" } }).moderation, { mode: "off", preModeration: false, reportsPerDay: 20 });
assert.deepEqual(
  resolveReaderSteeringConfig({ ...base, moderation: { mode: "ai", ai: { apiKeyParameter: "/papyrus/shipped/openai-api-key" } } }).moderation,
  { mode: "ai", preModeration: false, reportsPerDay: 20, ai: { model: "gpt-6-luna", apiKeyParameter: "/papyrus/shipped/openai-api-key" } },
);
assert.equal(resolveReaderSteeringConfig({ ...base, moderation: { mode: "ai", ai: { apiKeyParameter: "/papyrus/shipped/openai-api-key", model: "gpt-6-luna-2" } } }).moderation.ai?.model, "gpt-6-luna-2");
assert.deepEqual(resolveReaderSteeringConfig({ ...base, moderation: { preModeration: true, reportsPerDay: 5 } }).moderation, { mode: "human", preModeration: true, reportsPerDay: 5 });

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
assert.equal(shipped.ranking.combination, "blend", "a site that does not ask keeps the blend");
const shrinking = resolveReaderSteeringConfig({ ...base, ranking: { combination: "shrinkage" } }).ranking;
assert.deepEqual(
  [shrinking.combination, shrinking.shrinkageK, shrinking.readerShareCap, shrinking.newAccountWeight, shrinking.risingMinimumAccountHours],
  ["shrinkage", 20, 0.4, 1 / 3, 24],
  "shrinkage turns on the adopted defaults",
);
const tunedRanking = resolveReaderSteeringConfig({ ...base, ranking: { combination: "shrinkage", shrinkageK: 10, readerShareCap: 0.5, newAccountWeight: 0.5, risingMinimumAccountHours: 0 } }).ranking;
assert.deepEqual([tunedRanking.shrinkageK, tunedRanking.readerShareCap, tunedRanking.newAccountWeight, tunedRanking.risingMinimumAccountHours], [10, 0.5, 0.5, 0]);
assert.equal(readerSnapshotSettings(resolveReaderSteeringConfig({ ...base, ranking: { combination: "shrinkage" } })).limits.newAccountHours, 24, "the snapshot task learns the new-account age");
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
  { ranking: { combination: "wilson" } },
  { ranking: { shrinkageK: 0 } },
  { ranking: { readerShareCap: 1.5 } },
  { ranking: { newAccountWeight: -1 } },
  { ranking: { risingMinimumAccountHours: -1 } },
  { snapshot: { schedule: "yes" } },
  { snapshot: { intervalHours: 0 } },
  { reservedHandles: ["Bad Handle"] },
  { retirementPoll: true },
  { retirementPoll: true, snapshot: { schedule: false } },
  { retirementPoll: "yes" },
  { waf: true },
  { submissions: { perDay: 0 } },
  { submissions: { perDay: 1.5 } },
  { submissions: { similarHours: 0 } },
  { submissions: { kinds: ["Bad Kind"] } },
  { submissions: { kinds: "article" } },
  { submissions: { burst: 1 } },
  { submissions: [] },
  { comments: { perHour: 0 } },
  { comments: { editWindowMinutes: -1 } },
  { comments: { maximumLength: 0 } },
  { comments: { maximumLinks: 1.5 } },
  { comments: { threads: 2 } },
  { comments: "yes" },
  { moderation: { mode: "auto" } },
  { moderation: { mode: "ai" } },
  { moderation: { mode: "ai", ai: {} } },
  { moderation: { mode: "ai", ai: { apiKeyParameter: "/papyrus/shipped/other-key" } } },
  { moderation: { mode: "ai", ai: { apiKeyParameter: "/amplify/shipped/openai-api-key" } } },
  { moderation: { mode: "ai", ai: { apiKeyParameter: "/papyrus/../openai-api-key" } } },
  { moderation: { mode: "ai", ai: { apiKeyParameter: "/papyrus/shipped/openai-api-key", model: "GPT 6" } } },
  { moderation: { mode: "ai", ai: { apiKeyParameter: "/papyrus/shipped/openai-api-key", key: "sk-secret" } } },
  { moderation: { mode: "human", ai: { apiKeyParameter: "/papyrus/shipped/openai-api-key" } } },
  { moderation: { mode: "off", preModeration: true } },
  { moderation: { preModeration: "yes" } },
  { moderation: { reportsPerDay: 0 } },
  { moderation: { trust: true } },
  { moderation: "human" },
  { submissions: { itemType: "Brief Item" } },
  { submissions: { section: 3 } },
]) {
  assert.throws(() => resolveReaderSteeringConfig({ ...base, ...bad } as never), /reader-steering/, JSON.stringify(bad));
}

const definitions = readerSteeringSchemaDefinitions() as Record<string, unknown>;
assert.deepEqual(
  Object.keys(definitions).sort(),
  [...readerSteeringManifest.models, ...readerSteeringManifest.mutations, "ModerationReceipt", "ProposalReceipt"].sort(),
  "the schema defines exactly the manifest's models and mutations, plus the receipt types",
);
assert.deepEqual(readerSteeringManifest.guest.mutations, [], "a guest can call nothing");
assert.deepEqual(readerSteeringManifest.mutations, ["moderateReader", "fileProposal", "transitionProposal"]);
assert.deepEqual(readerSteeringManifest.newsroomPanels, [{ id: "moderation", label: "Moderation" }]);

const schemaSource = JSON.stringify(
  Object.entries(definitions)
    .filter(([name]) => readerSteeringManifest.models.includes(name))
    .map(([, model]) => (model as { data?: { authorization?: unknown } }).data?.authorization),
);
assert.equal(/guest|public|apiKey|private|custom/i.test(schemaSource), false, "no guest, API key or custom rule on any reader model");

const settings = readerActionsSettings(shipped, false);
assert.deepEqual(settings, {
  dimensions: ["real", "useful", "notable", "novel"],
  limits: shipped.limits,
  reservedHandles: ["shipped-team"],
  submissions: shipped.submissions,
  subjects: shipped.subjects,
  comments: shipped.comments,
  moderation: shipped.moderation,
  allowInterimSubjects: false,
  snapshotDebounceSeconds: 60,
});
assert.equal(readerSnapshotSettings(shipped).hypeMinimum, 5);
assert.equal(JSON.stringify(settings).includes(computeRoleArn), false, "the function settings do not carry the role");
assert.equal(interimSubjectsAllowedAtSynth({ SITE_ENV: "production" }), false);
assert.equal(interimSubjectsAllowedAtSynth({ SITE_ENV: "development", NODE_ENV: "production" }), false);
assert.equal(interimSubjectsAllowedAtSynth({}), false);
assert.equal(interimSubjectsAllowedAtSynth({ SITE_ENV: "development" }), true);
assert.deepEqual(readerSteeringPlugin.publicSettings(shipped), { contract: 1, dimensions: ["real", "useful", "notable", "novel"], subjects: { types: ["item", "submission"] }, moderation: { mode: "human" } });

function synthesize(config = shipped, environment: Record<string, string> = {}) {
  const app = new App();
  const awsEnvironment = { account: "123456789012", region: "us-east-1" };
  const stack = new Stack(app, "Data", { env: awsEnvironment });
  const lambdaFor = (id: string) => new Function(stack, id, { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x") });
  const readerLambda = lambdaFor("ReaderActions");
  new Table(stack, "PapyrusReaderRateWindows", { partitionKey: { name: "pk", type: AttributeType.STRING } });
  const contentActions = lambdaFor("ContentActions");
  const tables = Object.fromEntries(
    ["ReaderProfile", "ReaderHandle", "ReaderVote", "ReaderFlag", "ReaderSubmission", "ReaderComment", "ReaderReport", "ModerationAction", "Proposal", "Item", "PublishedItem"].map((name) => [name, new Table(stack, name, { partitionKey: { name: "id", type: AttributeType.STRING } })]),
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
for (const name of ["PAPYRUS_READER_PROFILE_TABLE", "PAPYRUS_READER_HANDLE_TABLE", "PAPYRUS_READER_VOTE_TABLE", "PAPYRUS_READER_FLAG_TABLE", "PAPYRUS_READER_SUBMISSION_TABLE", "PAPYRUS_READER_COMMENT_TABLE", "PAPYRUS_READER_REPORT_TABLE", "PAPYRUS_READER_ACTION_TABLE", "PAPYRUS_READER_ITEM_TABLE", "PAPYRUS_READER_PUBLISHED_ITEM_TABLE", "PAPYRUS_READER_SNAPSHOT_FUNCTION_ARN", "PAPYRUS_READER_SCHEDULER_ROLE_ARN"]) {
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
const debounceStatements = debounceTemplates.flatMap((candidate) => [...Object.values(candidate.findResources("AWS::IAM::Policy")), ...Object.values(candidate.findResources("AWS::IAM::ManagedPolicy"))]).flatMap(
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

// The retirement poll: off by default; when on, the scheduled run asks for it and the backend can reach the CMS route.
assert.deepEqual(JSON.parse(rule.Properties.Targets[0].Input), { projectionTask: { task: "reader-snapshot" } }, "no poll unless the site enables it");
const pollConfig = resolveReaderSteeringConfig({ ...base, dimensions: ["real"], snapshot: { schedule: true }, retirementPoll: true });
assert.equal(pollConfig.retirementPoll, true);
const pollEnvironment = { PAPYRUS_SITE_ORIGIN: "https://reader.example.test", PAPYRUS_READER_POLL_SECRET_PARAMETER: "/papyrus/reader/reader-poll-secret", SITE_ENV: "production" };
assert.throws(() => synthesize(pollConfig, { SITE_ENV: "production" }), /PAPYRUS_READER_POLL_SECRET_PARAMETER/, "no poll without the secret parameter and origin");
assert.throws(() => synthesize(pollConfig, { ...pollEnvironment, PAPYRUS_SITE_ORIGIN: "http://reader.example.test" }), /https origin/);
const polled = synthesize(pollConfig, pollEnvironment);
const polledRule = eventRules(polled)[0] as { Properties: { Targets: Array<{ Input: string }> } };
assert.deepEqual(JSON.parse(polledRule.Properties.Targets[0].Input), { projectionTask: { task: "reader-snapshot", retirementPoll: true } }, "only the scheduled run polls");
const polledFunctions = Object.values(polled.template.findResources("AWS::Lambda::Function")).map((resource) => (resource as { Properties: { Environment?: { Variables: Record<string, string> } } }).Properties.Environment?.Variables ?? {});
const polledVariables = polledFunctions.find((variables) => variables.PAPYRUS_READER_SNAPSHOT_SETTINGS) as Record<string, string>;
assert.equal(polledVariables.PAPYRUS_READER_POLL_URL, "https://reader.example.test");
assert.equal(polledVariables.PAPYRUS_READER_POLL_SECRET_PARAMETER, "/papyrus/reader/reader-poll-secret");
assert.ok(polledVariables.PAPYRUS_READER_RATE_TABLE, "the cursor lives in the rate table");
assert.equal(JSON.parse(polledVariables.PAPYRUS_READER_SNAPSHOT_SETTINGS).retirementPoll, true);
// CDK moves statements that no longer fit the inline size limit into an overflow managed policy on the same role; both count.
const statementsOf = (template: Template, rolePrefix: string) =>
  [...Object.values(template.findResources("AWS::IAM::Policy")), ...Object.values(template.findResources("AWS::IAM::ManagedPolicy"))]
    .filter((policy) => ((policy as { Properties: { Roles: Array<{ Ref: string }> } }).Properties.Roles ?? []).some((role) => role.Ref.startsWith(rolePrefix)))
    .flatMap((policy) => (policy as { Properties: { PolicyDocument: { Statement: Array<{ Action: string | string[]; Resource: unknown }> } } }).Properties.PolicyDocument.Statement);
const actionsOn = (statements: ReturnType<typeof statementsOf>, table: string) =>
  statements.filter((statement) => JSON.stringify(statement.Resource).includes(table)).flatMap((statement) => ([] as string[]).concat(statement.Action));
const polledStatements = statementsOf(polled.template, "ContentActionsServiceRole");
const secretReads = polledStatements.filter((statement) => ([] as string[]).concat(statement.Action).includes("ssm:GetParameter"));
assert.equal(secretReads.length, 1);
assert.match(JSON.stringify(secretReads[0].Resource), /parameter\/papyrus\/reader\/reader-poll-secret/, "the read is scoped to the one parameter");
assert.equal(actionsOn(polledStatements, "ReaderVote").includes("dynamodb:DeleteItem"), true, "the poll may delete votes");
assert.equal(actionsOn(polledStatements, "ReaderHandle").includes("dynamodb:DeleteItem"), true, "the poll may free handles");
assert.equal(actionsOn(polledStatements, "PapyrusReaderRateWindows").includes("dynamodb:PutItem"), true, "the poll keeps its cursor in the rate table");
const unpolled = synthesize({ ...shipped, snapshot: { ...shipped.snapshot, schedule: true } }, { SITE_ENV: "production" });
const unpolledStatements = statementsOf(unpolled.template, "ContentActionsServiceRole");
assert.equal(unpolledStatements.some((statement) => ([] as string[]).concat(statement.Action).includes("ssm:GetParameter")), false, "no secret read without the poll");
assert.equal(actionsOn(unpolledStatements, "ReaderVote").includes("dynamodb:DeleteItem"), false, "the snapshot alone never deletes votes");
assert.equal(actionsOn(unpolledStatements, "ReaderHandle").length, 0, "the snapshot alone never touches handles");

console.log("reader steering plugin ok");



// AI moderation: the key is read from one SSM SecureString, nothing else is opened, and nothing else changes without it.
const KEY_PARAMETER = "/papyrus/shipped/openai-api-key";
const aiConfig = resolveReaderSteeringConfig({ ...base, dimensions: ["real"], moderation: { mode: "ai", ai: { apiKeyParameter: KEY_PARAMETER } } });
const aiRun = synthesize(aiConfig, { SITE_ENV: "production" });
const readerStatements = statementsOf(aiRun.template, "ReaderActions");
const keyReads = readerStatements.filter((statement) => ([] as string[]).concat(statement.Action).some((action) => action.startsWith("ssm:")));
assert.equal(keyReads.length, 1, "reader-actions reads exactly one parameter");
assert.deepEqual(([] as string[]).concat(keyReads[0].Action), ["ssm:GetParameter"], "read only");
assert.match(JSON.stringify(keyReads[0].Resource), /parameter\/papyrus\/shipped\/openai-api-key"/, "the one named parameter, no wildcard");
assert.equal(JSON.stringify(keyReads[0].Resource).includes("*"), false);
assert.equal(readerStatements.some((statement) => ([] as string[]).concat(statement.Action).some((action) => action.startsWith("secretsmanager:"))), false, "secrets live in SSM SecureString, never Secrets Manager");
const readerInvokes = readerStatements.filter((statement) => ([] as string[]).concat(statement.Action).includes("lambda:InvokeFunction"));
assert.equal(readerInvokes.length, 1, "reader-actions may invoke exactly one function");
assert.match(JSON.stringify(readerInvokes[0].Resource), /ContentActions/, "content-actions, to request the snapshot");
const schedulerStatements = Object.values(aiRun.template.findResources("AWS::IAM::Policy")).filter((policy) =>
  ((policy as { Properties: { Roles: Array<{ Ref: string }> } }).Properties.Roles ?? []).some((role) => role.Ref.startsWith("ReaderSnapshotSchedulerRole")))
  .flatMap((policy) => (policy as { Properties: { PolicyDocument: { Statement: Array<{ Action: string | string[]; Resource: unknown }> } } }).Properties.PolicyDocument.Statement);
assert.equal(schedulerStatements.filter((statement) => JSON.stringify(statement.Resource).includes("ReaderActions")).length, 1, "the scheduler role may also invoke reader-actions for the AI review");
assert.equal(schedulerStatements.filter((statement) => JSON.stringify(statement.Resource).includes("ContentActions")).length, 1, "and still content-actions for the snapshot");
const aiSettings = JSON.parse(Object.values(aiRun.template.findResources("AWS::Lambda::Function")).map((resource) => (resource as { Properties: { Environment?: { Variables: Record<string, string> } } }).Properties.Environment?.Variables?.PAPYRUS_READER_SETTINGS).find(Boolean) as string);
assert.deepEqual(aiSettings.moderation.ai, { model: "gpt-6-luna", apiKeyParameter: KEY_PARAMETER }, "the function learns the parameter name, never a key");
assert.equal(JSON.stringify(aiRun.template.toJSON()).includes("sk-"), false);
const humanRun = statementsOf(synthesize(shipped, { SITE_ENV: "production" }).template, "ReaderActions");
assert.equal(humanRun.some((statement) => ([] as string[]).concat(statement.Action).some((action) => action.startsWith("ssm:"))), false, "no key access without AI mode");
assert.equal(humanRun.some((statement) => ([] as string[]).concat(statement.Action).includes("lambda:InvokeFunction")), false);
assert.equal(readerSteeringPlugin.publicSettings(aiConfig).moderation && (readerSteeringPlugin.publicSettings(aiConfig).moderation as { mode: string }).mode, "ai");
assert.equal(JSON.stringify(readerSteeringPlugin.publicSettings(aiConfig)).includes("openai-api-key"), false, "the parameter name is not published to the browser");

const transformed = schemaWithPlugins(readerSteeringSchemaDefinitions()).transform().schema;
for (const model of readerSteeringManifest.models) {
  const declaration = new RegExp(`type ${model} @model[^\\n]*`).exec(transformed);
  assert.ok(declaration, `${model} is a model in the deployed schema`);
  assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)/.test(declaration[0]), false, `${model} has no guest, API key or IAM rule: ${declaration[0]}`);
  assert.match(declaration[0], /groups: \["editor"\]|groups: \["admin"\]/);
}
const mutationStart = transformed.indexOf("moderateReader(");
assert.ok(mutationStart > 0, "moderateReader is in the deployed schema");
const mutation = transformed.slice(mutationStart, mutationStart + 400).split("\n\n")[0];
assert.match(mutation, /@function/);
assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)|guest/.test(mutation), false, `moderateReader is open to groups only: ${mutation}`);
assert.match(mutation, /groups: \["editor"\]/);
assert.match(mutation, /groups: \["admin"\]/);
for (const name of ["fileProposal", "transitionProposal"]) {
  const start = transformed.indexOf(`${name}(`);
  assert.ok(start > 0, `${name} is in the deployed schema`);
  const proposalMutation = transformed.slice(start, start + 400).split("\n\n")[0];
  assert.match(proposalMutation, /@function/);
  assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)|guest/.test(proposalMutation), false, `${name} is open to groups only: ${proposalMutation}`);
  assert.match(proposalMutation, /groups: \["editor"\]/);
  assert.match(proposalMutation, /groups: \["admin"\]/);
}
console.log("reader steering schema ok");
