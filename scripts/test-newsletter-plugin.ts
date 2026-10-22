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
import { newsletterSchemaDefinitions } from "../amplify/plugins/newsletter/schema";
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

// The manifest, the registry and the schema agree; the plugin opens nothing to guests and adds nothing to the content API.
assert.equal(KNOWN_PLUGINS.newsletter, newsletterPlugin);
assert.deepEqual(newsletterManifest.guest.mutations, [], "no guest access");
assert.deepEqual(newsletterManifest.models, []);
assert.deepEqual(newsletterManifest.mutations, []);
assert.deepEqual(Object.keys(newsletterSchemaDefinitions()), [], "the plugin defines no models or operations");
assert.deepEqual(newsletterPlugin.schemaDefinitions(), {});
assert.deepEqual(newsletterPlugin.functions(), {});
assert.deepEqual(newsletterManifest.staticAssets, ["_plugins/papyrus-newsletter@1.js"]);
const withPlugin = schemaWithPlugins(newsletterPlugin.schemaDefinitions()).transform().schema;
const withoutPlugins = schemaWithPlugins({}).transform().schema;
assert.equal(withPlugin, withoutPlugins, "the GraphQL schema is the same with the plugin");

// Config: defaults and derived names.
const config = resolvePlugins([base])[0].config as NewsletterConfig;
assert.equal(config.configurationSet, "papyrus-example");
assert.equal(config.eventTopicName, "papyrus-newsletter-events-example");
assert.equal(config.instantAlerts, false);
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
    { id: "weekly", name: "Weekly roundup", description: "The week in review.", kind: "roundup" },
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
  "ALARM_NAMES", "CONFIGURATION_SET", "FROM_ADDRESS", "FROM_NAME", "KEY_PARAMETER", "LISTS_JSON", "SENDING_DOMAIN", "SITE_ID", "SITE_ORIGIN", "TABLE_NAME", "THEME_JSON",
]);
assert.equal(environment.SITE_ORIGIN, "https://news.example.com");
assert.deepEqual(JSON.parse(environment.LISTS_JSON), published.lists);
assert.ok(!environment.LISTS_JSON.includes("cron("), "schedules stay out of the environment until a story needs them");

// A site without plugins touches nothing.
wirePlugins(new Proxy({}, { get: () => assert.fail("a site without plugins must not touch the backend") }), [], undefined as never);

// Synthesis. The Python asset is a pip install, so the test uses inline code in its place.
overrideNewsletterCodeForTests(Code.fromInline("def handler(event, context): pass"));
function synthesize(settings: NewsletterConfig = config) {
  const app = new App();
  const awsEnvironment = { account, region: "us-east-1" };
  const outputs: unknown[] = [];
  const stacks: Stack[] = [];
  const backend = {
    data: { resources: { tables: {}, graphqlApi: { apiId: "api" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://x.test/graphql" } } } },
    createStack: (name: string) => {
      const stack = new Stack(app, name, { env: awsEnvironment });
      stacks.push(stack);
      return stack;
    },
    addOutput: (value: unknown) => outputs.push(value),
  };
  const contentActions = new Function(new Stack(app, "Data", { env: awsEnvironment }), "ContentActions", {
    runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x"),
  });
  wirePlugins(backend, [{ plugin: newsletterPlugin, config: settings }], contentActions);
  return { template: Template.fromStack(stacks[0]), outputs, stacks, contentActions };
}

const { template, outputs, stacks, contentActions } = synthesize();
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

const functions = Object.values(template.findResources("AWS::Lambda::Function")) as Array<{
  Properties: { Handler: string; Timeout: number; MemorySize: number; Architectures: string[]; Environment?: { Variables: Record<string, unknown> } };
}>;
const newsletter = functions.filter((entry) => entry.Properties.Handler === "papyrus_content.newsletter.handler.handler");
assert.equal(newsletter.length, 1, "one newsletter function");
assert.equal(newsletter[0].Properties.Timeout, 30);
assert.equal(newsletter[0].Properties.MemorySize, 512);
assert.deepEqual(newsletter[0].Properties.Architectures, ["arm64"]);
const variables = newsletter[0].Properties.Environment?.Variables ?? {};
assert.equal(variables.ALARM_NAMES, "papyrus-newsletter-example-bounce-rate,papyrus-newsletter-example-complaint-rate");
for (const name of ["TABLE_NAME", "KEY_PARAMETER", "SITE_ID", "SITE_ORIGIN", "SENDING_DOMAIN", "FROM_ADDRESS", "FROM_NAME", "CONFIGURATION_SET", "LISTS_JSON", "THEME_JSON"]) {
  assert.ok(name in variables, `${name} is set`);
}
assert.equal(variables.KEY_PARAMETER, "/papyrus/example/newsletter-key");
assert.equal(variables.CONFIGURATION_SET, "papyrus-example");

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

// IAM: table and key, the one parameter, SES on this identity and configuration set from this address only.
const statements = Object.values(template.findResources("AWS::IAM::Policy")).flatMap(
  (policy) => (policy as { Properties: { PolicyDocument: { Statement: Array<{ Action: string | string[]; Resource: unknown; Condition?: unknown; Effect: string }> } } }).Properties.PolicyDocument.Statement,
);
const ses = statements.filter((statement) => ([] as string[]).concat(statement.Action).includes("ses:SendEmail"));
assert.equal(ses.length, 1);
assert.deepEqual(ses[0].Action, ["ses:SendEmail", "ses:SendRawEmail"]);
assert.deepEqual(ses[0].Condition, { StringEquals: { "ses:FromAddress": "newsletter@example.com" } });
const sesResources = JSON.stringify(ses[0].Resource);
assert.match(sesResources, new RegExp(`:ses:us-east-1:${account}:identity/example.com`));
assert.match(sesResources, new RegExp(`:ses:us-east-1:${account}:configuration-set/papyrus-example`));
const ssm = statements.filter((statement) => ([] as string[]).concat(statement.Action).includes("ssm:GetParameter") && !([] as string[]).concat(statement.Action).includes("ssm:PutParameter"));
assert.equal(ssm.length, 1);
assert.match(JSON.stringify(ssm[0].Resource), /parameter\/papyrus\/example\/newsletter-key/);
assert.ok(
  statements.some((statement) => ([] as string[]).concat(statement.Action).some((action) => action.startsWith("kms:Decrypt")) && JSON.stringify(statement.Resource).includes("Key")),
  "the function can decrypt the table key",
);
const wildcards = statements.filter((statement) => statement.Resource === "*");
assert.deepEqual(wildcards.map((statement) => statement.Action), ["ses:DeleteSuppressedDestination"], "the one action IAM cannot scope to a resource");
const sending = statements.filter((statement) => ([] as string[]).concat(statement.Action).includes("ses:PutConfigurationSetSendingOptions"));
assert.equal(sending.length, 1);
assert.match(JSON.stringify(sending[0].Resource), /configuration-set\/papyrus-example/, "pausing is limited to the site's own configuration set");
assert.ok(!JSON.stringify(sending[0].Resource).includes("identity"));

// Not yet built here: no queue, schedule or send worker.
for (const type of ["AWS::SQS::Queue", "AWS::Scheduler::Schedule", "AWS::Events::Rule"]) {
  template.resourceCountIs(type, 0);
}
assert.equal(functions.filter((entry) => entry.Properties.Handler?.includes("send")).length, 0);

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
