import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import vm from "node:vm";
import { schemaWithPlugins } from "../amplify/data/schema";
import { resolveNewsletterConfig, type NewsletterConfig } from "../amplify/plugins/newsletter/config";
import {
  newsletterEnvironment,
  newsletterKeyParameterName,
  newsletterManifest,
  newsletterPlugin,
  overrideNewsletterCodeForTests,
} from "../amplify/plugins/newsletter/papyrus.plugin";
import { NEWSLETTER_MUTATIONS, NEWSLETTER_OPERATION_GROUPS, NEWSLETTER_QUERIES, newsletterSchemaDefinitions } from "../amplify/plugins/newsletter/schema";
import {
  SEND_MAX_RECEIVE_COUNT,
  WORKER_TIMEOUT_SECONDS,
  newsletterFunctionName,
  newsletterSendQueueName,
  newsletterWorkerName,
  postalAddressParameterArns,
} from "../amplify/plugins/newsletter/sending";
import { SECURE_STRING_PARAMETER_HANDLER_SOURCE } from "../amplify/plugins/newsletter/secure-string-parameter";
import { KNOWN_PLUGINS, resolvePlugins } from "../amplify/plugins/registry";
import { wirePlugins } from "../amplify/plugins/wire";
import { pluginSettings } from "../lib/plugin-settings";

const computeRoleArn = "arn:aws:iam::123456789012:role/AmplifyComputeRole-abc";
const account = "123456789012";
const base = {
  name: "newsletter",
  siteId: "example",
  siteOrigin: "https://news.example.com",
  computeRoleArn,
  sendingDomain: "example.com",
  fromAddress: "newsletter@example.com",
  fromName: "Example News",
  theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" },
  lists: [
    {
      id: "weekly", name: "Weekly roundup", description: "The week in review.", kind: "roundup",
      schedule: { draft: "cron(0 13 ? * FRI *)", timezone: "America/New_York" }, archivePath: "/roundup/",
    },
    { id: "alerts-x", name: "Alerts", description: "Breaking items.", kind: "alert", rule: { sections: ["Security"], tags: ["breaking"] } },
  ],
};
const with_ = (changes: Record<string, unknown>) => ({ ...base, ...changes });
const refuses = (request: Record<string, unknown>, pattern: RegExp, message?: string) =>
  assert.throws(() => resolveNewsletterConfig(request as never), pattern, message);

// The manifest, the registry and the schema agree; the plugin opens nothing to guests and adds no model to the content API.
assert.equal(KNOWN_PLUGINS.newsletter, newsletterPlugin);
assert.deepEqual(newsletterManifest.guest.mutations, [], "no guest access");
assert.deepEqual(newsletterManifest.models, []);
const operations = [...NEWSLETTER_QUERIES, ...NEWSLETTER_MUTATIONS].sort();
assert.deepEqual(operations, [
  "newsletterApproveIssue", "newsletterCancelIssue", "newsletterCreateDraft", "newsletterErase", "newsletterExport",
  "newsletterIssue", "newsletterIssueDeliveries", "newsletterIssues", "newsletterOverview", "newsletterPreview",
  "newsletterResume", "newsletterStopIssue", "newsletterSubscribers", "newsletterTestSend",
]);
assert.deepEqual([...(newsletterManifest.queries ?? []), ...newsletterManifest.mutations].sort(), operations);
assert.deepEqual(Object.keys(newsletterSchemaDefinitions()).sort(), operations, "the plugin defines operations and no model");
assert.deepEqual(Object.keys(newsletterPlugin.schemaDefinitions()).sort(), operations);
assert.deepEqual(Object.keys(newsletterPlugin.functions()), ["newsletterOps"]);
assert.deepEqual(newsletterManifest.staticAssets, ["_plugins/papyrus-newsletter@1.js"]);
const withPlugin = schemaWithPlugins(newsletterPlugin.schemaDefinitions()).transform().schema;
const withoutPlugins = schemaWithPlugins({}).transform().schema;
assert.notEqual(withPlugin, withoutPlugins);
for (const name of operations) {
  const groups = NEWSLETTER_OPERATION_GROUPS[name];
  assert.ok(groups, `${name} has a group rule`);
  const line = withPlugin.split("\n").find((entry) => entry.includes(`${name}(`));
  assert.ok(line, `${name} is in the schema`);
  assert.match(line, /input: AWSJSON/);
  assert.match(line, /: AWSJSON/);
  assert.match(line, /@function\(/, `${name} is handled by the operations function`);
  for (const group of groups) assert.match(line, new RegExp(`"${group}"`), `${name} admits ${group}`);
  assert.ok(!/@aws_(api_key|iam)/.test(line) && !line.includes("@aws_cognito_user_pools(cognito_groups: [\"user"), `${name} is closed to guests`);
}
// Approving, cancelling, stopping, and everything that shows a full address or changes subscriber data or the pause is admin only.
for (const name of [
  "newsletterApproveIssue", "newsletterCancelIssue", "newsletterStopIssue",
  "newsletterSubscribers", "newsletterExport", "newsletterErase", "newsletterResume",
]) {
  assert.deepEqual(NEWSLETTER_OPERATION_GROUPS[name], ["admin"], `${name} is admin only`);
  const line = withPlugin.split("\n").find((entry) => entry.includes(`${name}(`)) ?? "";
  assert.ok(!line.includes('"editor"'), `${name} does not admit editors`);
}
for (const name of [
  "newsletterIssues", "newsletterIssue", "newsletterPreview", "newsletterTestSend", "newsletterCreateDraft",
  "newsletterOverview", "newsletterIssueDeliveries",
]) {
  assert.deepEqual(NEWSLETTER_OPERATION_GROUPS[name], ["editor", "admin"]);
}
assert.deepEqual(withoutPlugins.includes("newsletter"), false);

// Config: defaults and derived names.
const config = resolvePlugins([base])[0].config as NewsletterConfig;
assert.equal(config.configurationSet, "papyrus-example");
assert.equal(config.eventTopicName, "papyrus-newsletter-events-example");
assert.equal(config.instantAlerts, false);
assert.equal(config.itemUrlStyle, "html");
assert.equal(resolveNewsletterConfig(with_({ itemUrlStyle: "directory" })).itemUrlStyle, "directory");
assert.equal(config.lists[0].kind === "roundup" && config.lists[0].issueType, "newsletter_issue");
assert.deepEqual(config.lists[1].kind === "alert" && config.lists[1].approval, "admin");
assert.equal(resolveNewsletterConfig(with_({ configurationSet: "custom-set", eventTopicName: "custom-topic" })).configurationSet, "custom-set");
assert.equal(resolveNewsletterConfig(with_({ configurationSet: "custom-set", eventTopicName: "custom-topic" })).eventTopicName, "custom-topic");
assert.equal(newsletterKeyParameterName("example"), "/papyrus/example/newsletter-key");

// Config validation errors.
refuses({ name: "newsletter" }, /siteId/);
refuses(with_({ siteId: "Bad Id" }), /siteId/);
refuses(with_({ siteOrigin: "http://news.example.com" }), /siteOrigin/);
refuses(with_({ siteOrigin: "https://news.example.com/path" }), /siteOrigin/);
refuses(with_({ siteOrigin: undefined }), /siteOrigin/);
refuses(with_({ computeRoleArn: "*" }), /computeRoleArn/);
refuses(with_({ computeRoleArn: undefined }), /computeRoleArn/);
refuses(with_({ sendingDomain: "News Example" }), /sendingDomain/);
refuses(with_({ fromAddress: "newsletter@example.org" }), /fromAddress must be an address on example.com/);
refuses(with_({ fromAddress: ["newsletter", "sub.example.com"].join("@") }), /fromAddress/);
refuses(with_({ fromAddress: "News <newsletter@example.com>" }), /fromAddress/);
refuses(with_({ fromAddress: "a@b@example.com" }), /fromAddress/);
refuses(with_({ fromName: "" }), /fromName/);
refuses(with_({ fromName: "Two\nLines" }), /fromName/);
refuses(with_({ instantAlerts: "yes" }), /instantAlerts must be a boolean/);
refuses(with_({ theme: undefined }), /theme must be an object/);
refuses(with_({ theme: { accent: "#fff", text: "#000" } }), /theme.background/);
refuses(with_({ theme: { ...base.theme, accent: "red; background:url(x)" } }), /theme.accent/);
refuses(with_({ theme: { ...base.theme, logoUrl: "http://x.test/logo.png" } }), /logoUrl must be an https URL/);
refuses(with_({ theme: { ...base.theme, extra: "x" } }), /unknown settings: extra/);
refuses(with_({ webhook: "https://x.test" }), /unknown settings: webhook/);
refuses(with_({ configurationSet: "bad name" }), /configurationSet/);
refuses(with_({ lists: [] }), /lists must be a list of 1 to 20/);
refuses(with_({ lists: undefined }), /lists must be a list/);
refuses(with_({ lists: [base.lists[0], { ...base.lists[1], id: "weekly" }] }), /duplicate ids: weekly/);
refuses(with_({ lists: [{ ...base.lists[0], id: "Weekly" }] }), /lists\[0\].id/);
refuses(with_({ lists: [{ ...base.lists[0], kind: "digest" }] }), /kind must be "roundup" or "alert"/);
refuses(with_({ lists: [{ ...base.lists[0], name: "" }] }), /lists\[0\].name is required/);
refuses(with_({ lists: [{ ...base.lists[0], schedule: { draft: "0 13 * * FRI", timezone: "America/New_York" } }] }), /schedule.draft/);
refuses(with_({ lists: [{ ...base.lists[0], schedule: { draft: "cron(0 13 ? * FRI *)", timezone: "Mars/Olympus" } }] }), /IANA time zone/);
refuses(with_({ lists: [{ ...base.lists[0], schedule: undefined }] }), /schedule must be an object/);
refuses(with_({ lists: [{ ...base.lists[0], archivePath: "roundup" }] }), /archivePath/);
refuses(with_({ lists: [{ ...base.lists[0], archivePath: "/news/roundup/" }] }), /archivePath/, "one path segment: it is also the item section");
refuses(with_({ itemUrlStyle: "flat" }), /itemUrlStyle must be one of html, directory, clean/);
refuses(with_({ lists: [{ ...base.lists[0], archivePath: undefined }] }), /archivePath/);
refuses(with_({ lists: [{ ...base.lists[0], issueType: "Not Valid" }] }), /issueType/);
refuses(with_({ lists: [{ ...base.lists[0], rule: {} }] }), /unknown settings: rule/);
refuses(with_({ lists: [{ ...base.lists[1], schedule: {} }] }), /unknown settings: schedule/);
refuses(with_({ lists: [base.lists[0], { ...base.lists[0], id: "other" }] }), /different archivePath/);
refuses(with_({ lists: [{ ...base.lists[1], rule: { sections: [] } }] }), /rule.sections must be a list of 1 to 50/);
refuses(with_({ lists: [{ ...base.lists[1], rule: { colours: ["red"] } }] }), /unknown settings: colours/);
refuses(with_({ lists: [{ ...base.lists[1], approval: "sometimes" }] }), /approval must be "admin" or "none"/);

// Approval "none" is refused unless the site opted in to instant alerts.
const instant = { ...base.lists[1], approval: "none" };
refuses(with_({ lists: [instant] }), /instantAlerts: true/);
refuses(with_({ lists: [instant], instantAlerts: false }), /instantAlerts: true/);
const allowed = resolveNewsletterConfig(with_({ lists: [instant], instantAlerts: true }));
assert.equal(allowed.instantAlerts, true);
assert.equal(allowed.lists[0].kind === "alert" && allowed.lists[0].approval, "none");

// What is published to amplify_outputs.json: names and the theme, never the key, the role or the table.
const published = newsletterPlugin.publicSettings(config);
assert.deepEqual(published, {
  contract: 1,
  fromName: "Example News",
  lists: [
    { id: "weekly", name: "Weekly roundup", description: "The week in review.", kind: "roundup", issueType: "newsletter_issue", archivePath: "/roundup/" },
    { id: "alerts-x", name: "Alerts", description: "Breaking items.", kind: "alert" },
  ],
  theme: base.theme,
});
for (const secret of [computeRoleArn, "newsletter-key", "newsletter@example.com", "cron(", "Security"]) {
  assert.ok(!JSON.stringify(published).includes(secret), `the public settings do not carry ${secret}`);
}
assert.equal(pluginSettings({ custom: { papyrusPlugins: { newsletter: published } } }, "newsletter"), published);

// The function environment.
const environment = newsletterEnvironment(config, "table-name", "/papyrus/example/newsletter-key");
assert.deepEqual(Object.keys(environment).sort(), [
  "ALARM_NAMES", "CONFIGURATION_SET", "FROM_ADDRESS", "FROM_NAME", "INSTANT_ALERTS", "ITEM_URL_STYLE", "KEY_PARAMETER", "LISTS_JSON", "SENDING_DOMAIN", "SITE_ID",
  "SITE_ORIGIN", "TABLE_NAME", "THEME_JSON",
]);
assert.equal(environment.SITE_ORIGIN, "https://news.example.com");
assert.equal(environment.ITEM_URL_STYLE, "html");
assert.deepEqual(JSON.parse(environment.LISTS_JSON), [
  {
    id: "weekly", name: "Weekly roundup", description: "The week in review.", kind: "roundup",
    issueType: "newsletter_issue", archivePath: "/roundup/", timezone: "America/New_York",
  },
  {
    id: "alerts-x", name: "Alerts", description: "Breaking items.", kind: "alert",
    rule: { sections: ["Security"], tags: ["breaking"] }, approval: "admin",
  },
]);
assert.ok(!environment.LISTS_JSON.includes("cron("), "schedules stay out of the environment");

// A site without plugins touches nothing.
wirePlugins(new Proxy({}, { get: () => assert.fail("a site without plugins must not touch the backend") }), [], undefined as never);

// Synthesis. The Python asset is a pip install, so the test uses inline code in its place.
overrideNewsletterCodeForTests(Code.fromInline("def handler(event, context): pass"));
function synthesize(settings: NewsletterConfig = config) {
  const app = new App();
  const awsEnvironment = { account, region: "us-east-1" };
  const outputs: unknown[] = [];
  const stacks: Stack[] = [];
  const dataStack = new Stack(app, "Data", { env: awsEnvironment });
  const operations = new Function(dataStack, "NewsletterOps", {
    runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x"),
  });
  const backend = {
    newsletterOps: { resources: { lambda: operations } },
    data: { resources: { tables: {}, graphqlApi: { apiId: "api" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://x.test/graphql" } } } },
    createStack: (name: string) => {
      const stack = new Stack(app, name, { env: awsEnvironment });
      stacks.push(stack);
      return stack;
    },
    addOutput: (value: unknown) => outputs.push(value),
  };
  const contentActions = new Function(dataStack, "ContentActions", {
    runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x"),
  });
  wirePlugins(backend, [{ plugin: newsletterPlugin, config: settings }], contentActions);
  return { template: Template.fromStack(stacks[0]), operationsTemplate: Template.fromStack(dataStack), outputs, stacks, contentActions };
}

const { template, operationsTemplate, outputs, stacks, contentActions } = synthesize();
assert.deepEqual(stacks.map((stack) => stack.node.id), ["newsletter"], "one stack for the plugin");
template.resourceCountIs("AWS::DynamoDB::Table", 1);
template.hasResource("AWS::DynamoDB::Table", {
  Properties: {
    BillingMode: "PAY_PER_REQUEST",
    KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }, { AttributeName: "sk", KeyType: "RANGE" }],
    TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true },
    SSESpecification: { SSEEnabled: true, SSEType: "KMS", KMSMasterKeyId: Match.anyValue() },
    PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: false },
    GlobalSecondaryIndexes: Match.arrayWith([
      Match.objectLike({
        IndexName: "byList",
        KeySchema: [{ AttributeName: "gsiList", KeyType: "HASH" }, { AttributeName: "sk", KeyType: "RANGE" }],
      }),
      Match.objectLike({ IndexName: "byHid", KeySchema: [{ AttributeName: "gsiHid", KeyType: "HASH" }], Projection: { ProjectionType: "KEYS_ONLY" } }),
    ]),
  },
  DeletionPolicy: "Retain",
  UpdateReplacePolicy: "Retain",
});
template.hasResource("AWS::KMS::Key", { Properties: { EnableKeyRotation: true }, DeletionPolicy: "Retain", UpdateReplacePolicy: "Retain" });
template.hasResourceProperties("Custom::SecureStringParameter", { ParameterName: "/papyrus/example/newsletter-key", Length: "64" });
template.hasResource("Custom::SecureStringParameter", { DeletionPolicy: "Retain" });
assert.ok(!JSON.stringify(template.toJSON()).match(/secretsmanager/i), "no Secrets Manager secret");

type FunctionResource = {
  Properties: {
    FunctionName?: string; Handler: string; Timeout: number; MemorySize: number; Architectures: string[];
    ReservedConcurrentExecutions?: number; Environment?: { Variables: Record<string, unknown> };
  };
};
const functions = Object.values(template.findResources("AWS::Lambda::Function")) as FunctionResource[];
const newsletter = functions.filter((entry) => entry.Properties.Handler === "papyrus_content.newsletter.handler.handler");
assert.equal(newsletter.length, 1, "one newsletter function");
assert.equal(newsletter[0].Properties.FunctionName, newsletterFunctionName("example"));
assert.equal(newsletter[0].Properties.Timeout, 120);
assert.equal(newsletter[0].Properties.MemorySize, 512);
assert.deepEqual(newsletter[0].Properties.Architectures, ["arm64"]);
const variables = newsletter[0].Properties.Environment?.Variables ?? {};
assert.equal(variables.ALARM_NAMES, "papyrus-newsletter-example-bounce-rate,papyrus-newsletter-example-complaint-rate");
for (const name of [
  "TABLE_NAME", "KEY_PARAMETER", "SITE_ID", "SITE_ORIGIN", "SENDING_DOMAIN", "FROM_ADDRESS", "FROM_NAME", "CONFIGURATION_SET", "LISTS_JSON", "THEME_JSON",
  "ITEM_URL_STYLE", "FUNCTION_ARN", "SCHEDULER_ROLE_ARN", "QUEUE_URL", "CONTENT_ACTIONS_FUNCTION", "PAPYRUS_GRAPHQL_ENDPOINT",
]) {
  assert.ok(name in variables, `${name} is set`);
}
assert.equal(variables.KEY_PARAMETER, "/papyrus/example/newsletter-key");
assert.equal(variables.CONFIGURATION_SET, "papyrus-example");
assert.equal(variables.PAPYRUS_GRAPHQL_ENDPOINT, "https://x.test/graphql");
assert.match(JSON.stringify(variables.FUNCTION_ARN), /:function:papyrus-newsletter-example/, "the schedules target the function by its fixed name");

// Only the CMS compute role may invoke it directly; SNS (the SES event topic and the alarm topic) may invoke it from those topics only.
const permissions = Object.values(template.findResources("AWS::Lambda::Permission")) as Array<{ Properties: { Principal: string; Action: string; SourceArn?: unknown } }>;
const direct = permissions.filter((entry) => entry.Properties.Principal !== "sns.amazonaws.com");
assert.deepEqual(direct.map((entry) => [entry.Properties.Principal, entry.Properties.Action]), [[computeRoleArn, "lambda:InvokeFunction"]]);
const fromSns = permissions.filter((entry) => entry.Properties.Principal === "sns.amazonaws.com");
assert.equal(fromSns.length, 2, "two topics may invoke it");
assert.ok(fromSns.every((entry) => entry.Properties.Action === "lambda:InvokeFunction" && entry.Properties.SourceArn !== undefined));
assert.ok(fromSns.some((entry) => JSON.stringify(entry.Properties.SourceArn).includes("papyrus-newsletter-events-example")), "the SES event topic, by literal name");
assert.ok(fromSns.some((entry) => JSON.stringify(entry.Properties.SourceArn).includes("AlarmTopic")), "the alarm topic");

// The subscriptions and the alarms.
template.resourceCountIs("AWS::SNS::Subscription", 2);
const subscriptions = Object.values(template.findResources("AWS::SNS::Subscription")) as Array<{ Properties: { Protocol: string; TopicArn: unknown } }>;
assert.ok(subscriptions.every((entry) => entry.Properties.Protocol === "lambda"));
assert.ok(subscriptions.some((entry) => JSON.stringify(entry.Properties.TopicArn).includes(":sns:us-east-1:123456789012:papyrus-newsletter-events-example")), "subscribed to the sending stack's topic");
template.hasResourceProperties("AWS::SNS::Topic", { TopicName: "papyrus-newsletter-alarms-example" });
template.resourceCountIs("AWS::CloudWatch::Alarm", 2);
for (const [name, metricName, threshold] of [
  ["papyrus-newsletter-example-bounce-rate", "Bounce", 0.04],
  ["papyrus-newsletter-example-complaint-rate", "Complaint", 0.0008],
] as const) {
  template.hasResourceProperties("AWS::CloudWatch::Alarm", {
    AlarmName: name,
    Threshold: threshold,
    ComparisonOperator: "GreaterThanThreshold",
    EvaluationPeriods: 1,
    TreatMissingData: "notBreaching",
    AlarmActions: [Match.anyValue()],
    Metrics: Match.arrayWith([
      Match.objectLike({ Expression: "IF(sent >= 50, FILL(events, 0) / sent, 0)", ReturnData: true }),
      Match.objectLike({ Id: "sent", MetricStat: Match.objectLike({ Metric: Match.objectLike({ MetricName: "Send" }) }) }),
      Match.objectLike({
        Id: "events",
        MetricStat: Match.objectLike({
          Period: 86400,
          Stat: "Sum",
          Metric: Match.objectLike({ Namespace: "AWS/SES", MetricName: metricName, Dimensions: [{ Name: "ses:configuration-set", Value: "papyrus-example" }] }),
        }),
      }),
    ]),
  });
}
assert.ok(JSON.stringify(template.findResources("AWS::CloudWatch::Alarm")).includes("AlarmTopic"), "alarms notify the alarm topic");

// The send queue: a dead letter queue after three receives, and a visibility timeout of six times the worker timeout.
template.resourceCountIs("AWS::SQS::Queue", 2);
template.hasResourceProperties("AWS::SQS::Queue", {
  QueueName: newsletterSendQueueName("example"),
  VisibilityTimeout: WORKER_TIMEOUT_SECONDS * 6,
  RedrivePolicy: { maxReceiveCount: SEND_MAX_RECEIVE_COUNT, deadLetterTargetArn: Match.anyValue() },
  SqsManagedSseEnabled: true,
});
template.hasResourceProperties("AWS::SQS::Queue", { QueueName: `${newsletterSendQueueName("example")}-dlq`, MessageRetentionPeriod: 14 * 24 * 60 * 60 });
assert.equal(SEND_MAX_RECEIVE_COUNT, 3);

// The worker: its own function on the same package, one message at a time, concurrency 1, fed by the queue.
const worker = functions.filter((entry) => entry.Properties.Handler === "papyrus_content.newsletter.worker.handler");
assert.equal(worker.length, 1, "one send worker");
assert.equal(worker[0].Properties.FunctionName, newsletterWorkerName("example"));
assert.equal(worker[0].Properties.ReservedConcurrentExecutions, 1);
assert.equal(worker[0].Properties.Timeout, WORKER_TIMEOUT_SECONDS);
assert.ok(WORKER_TIMEOUT_SECONDS * 6 >= worker[0].Properties.Timeout * 6, "visibility timeout is at least six times the function timeout");
for (const name of ["TABLE_NAME", "KEY_PARAMETER", "QUEUE_URL", "CONTENT_ACTIONS_FUNCTION", "SITE_ID", "LISTS_JSON"]) {
  assert.ok(name in (worker[0].Properties.Environment?.Variables ?? {}), `the worker has ${name}`);
}
template.resourceCountIs("AWS::Lambda::EventSourceMapping", 1);
template.hasResourceProperties("AWS::Lambda::EventSourceMapping", { BatchSize: 1 });

// One scheduler role and one draft schedule per roundup list, in the list's time zone, naming the task.
template.resourceCountIs("AWS::Scheduler::Schedule", 1);
template.hasResourceProperties("AWS::Scheduler::Schedule", {
  ScheduleExpression: "cron(0 13 ? * FRI *)",
  ScheduleExpressionTimezone: "America/New_York",
  FlexibleTimeWindow: { Mode: "OFF" },
  Target: Match.objectLike({ Input: JSON.stringify({ task: "assemble-roundup", listId: "weekly" }), Arn: Match.anyValue(), RoleArn: Match.anyValue() }),
});
template.hasResourceProperties("AWS::IAM::Role", {
  AssumeRolePolicyDocument: { Statement: [Match.objectLike({ Principal: { Service: "scheduler.amazonaws.com" } })] },
});

// IAM, statement by statement.
type Statement = { Action: string | string[]; Resource: unknown; Condition?: unknown; Effect: string };
const statements = Object.values(template.findResources("AWS::IAM::Policy")).flatMap(
  (policy) => (policy as { Properties: { PolicyDocument: { Statement: Statement[] } } }).Properties.PolicyDocument.Statement,
);
const actionsOf = (statement: Statement) => ([] as string[]).concat(statement.Action);
const ses = statements.filter((statement) => actionsOf(statement).includes("ses:SendEmail"));
assert.equal(ses.length, 2, "the function and the worker may send");
for (const statement of ses) {
  assert.deepEqual(statement.Action, ["ses:SendEmail", "ses:SendRawEmail"]);
  assert.deepEqual(statement.Condition, { StringEquals: { "ses:FromAddress": "newsletter@example.com" } });
  const resources = JSON.stringify(statement.Resource);
  assert.match(resources, new RegExp(`:ses:us-east-1:${account}:identity/example.com`));
  assert.match(resources, new RegExp(`:ses:us-east-1:${account}:configuration-set/papyrus-example`));
}
const ssm = statements.filter((statement) => actionsOf(statement).includes("ssm:GetParameter") && !actionsOf(statement).includes("ssm:PutParameter"));
const ssmResources = ssm.map((statement) => JSON.stringify(statement.Resource));
assert.equal(ssm.length, 3, "key (function), postal address (function), key (worker)");
assert.equal(ssmResources.filter((entry) => entry.includes("parameter/papyrus/example/newsletter-key")).length, 2);
const postal = ssm.find((statement) => JSON.stringify(statement.Resource).includes("postal-address"));
assert.ok(postal);
const postalResources = (postal.Resource as unknown[]).map((entry) => JSON.stringify(entry));
assert.equal(postalResources.length, 2, "exactly the two postal address parameters");
assert.ok(postalResources.some((entry) => entry.endsWith(`:ssm:us-east-1:${account}:parameter/papyrus/example/email/postal-address"]]}`)));
assert.ok(postalResources.some((entry) => entry.endsWith(`:ssm:us-east-1:${account}:parameter/papyrus/email/postal-address"]]}`)));
assert.deepEqual(postalAddressParameterArns(new Stack(new App(), "X", { env: { account, region: "us-east-1" } }), "example").length, 2);
const scheduler = statements.find((statement) => actionsOf(statement).some((action) => action.startsWith("scheduler:")));
assert.ok(scheduler);
assert.deepEqual(scheduler.Action, ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule"]);
assert.ok(JSON.stringify(scheduler.Resource).endsWith(`:scheduler:us-east-1:${account}:schedule/default/papyrus-nl-example-*"]]}`));
const passRole = statements.find((statement) => actionsOf(statement).includes("iam:PassRole"));
assert.ok(passRole);
assert.deepEqual(passRole.Condition, { StringEquals: { "iam:PassedToService": "scheduler.amazonaws.com" } });
assert.doesNotMatch(JSON.stringify(passRole.Resource), /\*/, "PassRole names the one scheduler role");
const appsync = statements.find((statement) => actionsOf(statement).includes("appsync:GraphQL"));
assert.ok(appsync);
assert.deepEqual(
  (appsync.Resource as unknown[]).map((entry) => JSON.stringify(entry).split("/types/")[1].replace(/"\]\]\}$/, "")).sort(),
  ["Mutation/fields/createItem", "Mutation/fields/updateItem", "Query/fields/getItem", "Query/fields/getPublishedItem", "Query/fields/listPublishedItems"],
  "five content API fields and no others",
);
assert.ok(
  statements.some((statement) => actionsOf(statement).includes("sqs:SendMessage")),
  "the function and the worker can queue",
);
assert.ok(statements.some((statement) => actionsOf(statement).includes("sqs:ReceiveMessage")), "the worker consumes the queue");
const getAccount = statements.filter((statement) => actionsOf(statement).includes("sesv2:GetAccount"));
assert.equal(getAccount.length, 1);
assert.deepEqual(getAccount[0].Action, "sesv2:GetAccount");
assert.ok(
  statements.some((statement) => actionsOf(statement).some((action) => action.startsWith("kms:Decrypt")) && JSON.stringify(statement.Resource).includes("Key")),
  "the function can decrypt the table key",
);
const wildcards = statements.filter((statement) => statement.Resource === "*");
assert.deepEqual(
  wildcards.map((statement) => statement.Action).sort(),
  ["ses:DeleteSuppressedDestination", "sesv2:GetAccount"],
  "the two actions IAM cannot scope to a resource: lifting a suppression and reading the send rate",
);
const sending = statements.filter((statement) => actionsOf(statement).includes("ses:PutConfigurationSetSendingOptions"));
assert.equal(sending.length, 1);
assert.match(JSON.stringify(sending[0].Resource), /configuration-set\/papyrus-example/, "pausing is limited to the site's own configuration set");
assert.ok(!JSON.stringify(sending[0].Resource).includes("identity"));
const invokes = statements.filter((statement) => actionsOf(statement).includes("lambda:InvokeFunction"));
assert.ok(invokes.length >= 3, "the scheduler role, and the function and worker invoking content-actions");

// The AppSync operations function and the content-actions function (to announce a publish) may each invoke the newsletter function and nothing else.
const operationsStatements = Object.values(operationsTemplate.findResources("AWS::IAM::Policy")).flatMap(
  (policy) => (policy as { Properties: { PolicyDocument: { Statement: Statement[] } } }).Properties.PolicyDocument.Statement,
);
assert.equal(operationsStatements.length, 2);
for (const statement of operationsStatements) {
  assert.deepEqual(statement.Action, "lambda:InvokeFunction");
  assert.ok(JSON.stringify(statement.Resource).endsWith(`:lambda:us-east-1:${account}:function:papyrus-newsletter-example"]]}`));
}
const operationsEnvironment = Object.values(operationsTemplate.findResources("AWS::Lambda::Function")).map(
  (entry) => (entry as FunctionResource).Properties.Environment?.Variables ?? {},
);
assert.ok(operationsEnvironment.some((value) => value.NEWSLETTER_FUNCTION_NAME === "papyrus-newsletter-example"));

// Alerts: the function knows each alert list's rule and approval, and whether instant alerts are allowed.
assert.equal(variables.INSTANT_ALERTS, "false");
const listsInEnvironment = JSON.parse(String(variables.LISTS_JSON)) as Array<Record<string, unknown>>;
const alertList = listsInEnvironment.find((entry) => entry.kind === "alert");
assert.ok(alertList && "rule" in alertList && alertList.approval === "admin", "alert lists carry rule and approval");
assert.ok(!("rule" in listsInEnvironment.find((entry) => entry.kind === "roundup")!), "roundup lists carry no rule");

// The content-actions function is told the newsletter function's name and may invoke exactly that function.
const contentActionsResources = Object.values(operationsTemplate.findResources("AWS::Lambda::Function")) as FunctionResource[];
assert.ok(
  contentActionsResources.some((entry) => entry.Properties.Environment?.Variables?.PAPYRUS_NEWSLETTER_FUNCTION === "papyrus-newsletter-example"),
  "content-actions gets PAPYRUS_NEWSLETTER_FUNCTION",
);
const invokeStatements = Object.entries(operationsTemplate.findResources("AWS::IAM::Policy")).filter(([id]) => id.startsWith("ContentActions")).flatMap(
  ([, policy]) => ((policy as any).Properties.PolicyDocument.Statement as Array<{ Action: unknown; Resource: unknown }>),
).filter((statement) => JSON.stringify(statement.Action).includes("lambda:InvokeFunction") && JSON.stringify(statement.Resource).includes("papyrus-newsletter-example"));
assert.equal(invokeStatements.length, 1, "one invoke grant for the newsletter function");
assert.ok(!JSON.stringify(invokeStatements[0].Resource).includes("*"), "the grant names the one function");
assert.ok(!JSON.stringify(template.toJSON()).includes("PAPYRUS_NEWSLETTER_FUNCTION"), "the variable lives on content-actions, not the newsletter stack");

// A site with only alert lists schedules nothing.
const alertsOnly = resolveNewsletterConfig(with_({ lists: [base.lists[1]] }));
synthesize(alertsOnly).template.resourceCountIs("AWS::Scheduler::Schedule", 0);

// The CMS routes find the function from the outputs.
const output = outputs.map((value) => (value as { custom: Record<string, { actionsFunction?: unknown }> }).custom.newsletter).filter(Boolean);
assert.equal(output.length, 1);
assert.ok(output[0].actionsFunction);
assert.equal(contentActions.node.id, "ContentActions");

// The key generator creates once, never overwrites, never returns or logs the value.
(async () => {
  const exported: Record<string, any> = {};
  const logs: unknown[] = [];
  vm.runInNewContext(SECURE_STRING_PARAMETER_HANDLER_SOURCE, {
    exports: exported,
    require: (name: string) => (name === "node:crypto" ? require("node:crypto") : assert.fail(`unexpected require ${name}`)),
    console: { log: (...parts: unknown[]) => logs.push(parts), error: (...parts: unknown[]) => logs.push(parts) },
  });
  const puts: Array<Record<string, unknown>> = [];
  class Put { constructor(public input: Record<string, unknown>) {} }
  const ssm = (error?: string) => ({
    send: async (command: Put) => {
      puts.push(command.input);
      if (error) throw Object.assign(new Error(error), { name: error });
      return {};
    },
  });
  const properties = { ParameterName: "/papyrus/example/newsletter-key", Description: "d", Length: "64" };
  const created = await exported.createHandler(ssm(), Put)({ RequestType: "Create", ResourceProperties: properties });
  assert.deepEqual(JSON.parse(JSON.stringify(created)), { PhysicalResourceId: "/papyrus/example/newsletter-key" });
  assert.equal(puts[0].Type, "SecureString");
  assert.equal(puts[0].Overwrite, false);
  assert.match(String(puts[0].Value), /^[A-Za-z0-9]{64}$/);
  assert.ok(!JSON.stringify(created).includes(String(puts[0].Value)));
  await exported.createHandler(ssm("ParameterAlreadyExists"), Put)({ RequestType: "Update", ResourceProperties: properties, PhysicalResourceId: "x" });
  const before = puts.length;
  await exported.createHandler(ssm(), Put)({ RequestType: "Delete", ResourceProperties: properties, PhysicalResourceId: "x" });
  assert.equal(puts.length, before, "delete touches nothing");
  assert.deepEqual(logs, []);
  console.log("newsletter plugin ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
