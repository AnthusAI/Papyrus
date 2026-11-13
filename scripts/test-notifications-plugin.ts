import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { schemaWithPlugins } from "../amplify/data/schema";
import { resolveNotificationsConfig, type NotificationsConfig } from "../amplify/plugins/notifications/config";
import {
  CADUCUS_REQUIREMENT,
  HANDLERS,
  NOTIFICATIONS_REQUIREMENTS,
  notificationsAlarmNames,
  notificationsPauseAlarmNames,
  notificationsEmailName,
  notificationsEnvironment,
  notificationsFunctionName,
  notificationsManifest,
  notificationsOperatorsParameterName,
  notificationsPlugin,
  overrideNotificationsCodeForTests,
} from "../amplify/plugins/notifications/papyrus.plugin";
import { KNOWN_PLUGINS, resolvePlugins } from "../amplify/plugins/registry";
import { wirePlugins } from "../amplify/plugins/wire";
import { readFileSync } from "node:fs";

const computeRoleArn = "arn:aws:iam::123456789012:role/AmplifyComputeRole-abc";
const account = "123456789012";
const base = {
  name: "notifications",
  siteId: "example",
  siteOrigin: "https://news.example.com",
  computeRoleArn,
  sendingDomain: "example.com",
  fromAddress: "notifications@example.com",
  fromName: "Example News",
  theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" },
  lists: [{ id: "stories", name: "New stories", description: "Every published story.", rule: { sections: ["News"] } }],
  consent: "I agree to get the emails I choose from Example News and can unsubscribe at any time.",
};
const refuses = (request: Record<string, unknown>, pattern: RegExp, message?: string) =>
  assert.throws(() => resolveNotificationsConfig(request as never), pattern, message);

// The manifest and the registry agree; it adds no model, operation, guest access, panel or static file.
assert.equal(KNOWN_PLUGINS.notifications, notificationsPlugin);
assert.deepEqual(notificationsManifest, {
  name: "notifications", contract: 1, models: [], queries: [], mutations: [], guest: { mutations: [] }, newsroomPanels: [], staticAssets: [],
});
assert.deepEqual(notificationsPlugin.schemaDefinitions(), {}, "no GraphQL models or operations, so no AppSync realtime");
assert.deepEqual(notificationsPlugin.functions(), {});
assert.equal(schemaWithPlugins(notificationsPlugin.schemaDefinitions()).transform().schema, schemaWithPlugins({}).transform().schema);

// Config: defaults, derived names and refusals that stop the synth.
const config = resolvePlugins([base])[0].config as NotificationsConfig;
assert.equal(config.configurationSet, "papyrus-example");
assert.equal(config.itemUrlStyle, "html");
assert.equal(config.basePath, "");
assert.equal(config.confirmWindowHours, 72, "the newsletter's promise to readers by default");
assert.equal(resolveNotificationsConfig({ ...base, confirmWindowHours: 24 } as never).confirmWindowHours, 24);
refuses({ ...base, confirmWindowHours: 1.5 }, /confirmWindowHours must be a whole number of hours/);
refuses({ ...base, consent: undefined }, /notifications plugin consent/, "the form's consent wording is required");
assert.deepEqual(config.lists, [{ id: "stories", name: "New stories", description: "Every published story.", rule: { sections: ["News"] }, approval: "admin" }]);
assert.equal(resolveNotificationsConfig({ ...base, lists: [{ ...base.lists[0], approval: "none" }] } as never).lists[0].approval, "none");
refuses({ ...base, siteId: "Bad Id" }, /notifications plugin siteId/);
refuses({ ...base, siteOrigin: "http://news.example.com" }, /notifications plugin siteOrigin/);
refuses({ ...base, fromAddress: "x@other.example" }, /notifications plugin fromAddress must be an address on example.com/);
refuses({ ...base, lists: [] }, /lists must be a list of 1 to 20 lists/);
refuses({ ...base, lists: [base.lists[0], base.lists[0]] }, /duplicate ids: stories/);
refuses({ ...base, lists: [{ ...base.lists[0], approval: "sometimes" }] }, /approval must be "admin" or "none"/);
refuses({ ...base, lists: [{ ...base.lists[0], kind: "alert" }] }, /unknown settings: kind/);
refuses({ ...base, theme: { ...base.theme, accent: "red;}" } }, /notifications plugin theme.accent/, "an unsafe theme stops the synth, worded for this plugin");
refuses({ ...base, extra: 1 }, /unknown settings: extra/);
{
  const previous = process.env.PAPYRUS_COMPUTE_ROLE_ARN;
  try {
    delete process.env.PAPYRUS_COMPUTE_ROLE_ARN;
    const { computeRoleArn: _omitted, ...withoutRole } = base;
    refuses(withoutRole, /notifications plugin computeRoleArn/);
  } finally {
    if (previous !== undefined) process.env.PAPYRUS_COMPUTE_ROLE_ARN = previous;
  }
}

// Caducus is pinned exactly; the requirement file the bundler installs says the same.
assert.equal(CADUCUS_REQUIREMENT, "caducus[notify]==0.3.0");
assert.ok(NOTIFICATIONS_REQUIREMENTS.includes(CADUCUS_REQUIREMENT));
const requirements = readFileSync(new URL("../amplify/plugins/notifications/function/requirements.txt", import.meta.url), "utf8").split("\n");
assert.ok(requirements.includes(CADUCUS_REQUIREMENT), "requirements.txt pins the same Caducus");

// Environment: names, theme and lists, no secrets.
const environment = notificationsEnvironment(config, { table: "t", operators: notificationsOperatorsParameterName("example"), key: "/k" });
assert.equal(environment.SITE_ID, "example");
assert.equal(environment.OPERATORS_PARAMETER, "/papyrus/example/notifications/operators");
assert.deepEqual(JSON.parse(environment.THEME_JSON), base.theme);
assert.deepEqual(JSON.parse(environment.LISTS_JSON), config.lists);
assert.equal(environment.CONSENT, base.consent);
assert.equal(environment.CONFIRM_WINDOW_SECONDS, "259200");
assert.equal((notificationsPlugin.publicSettings(config) as { consent: string }).consent, base.consent, "the subscribe form shows the stored wording");
assert.ok(!JSON.stringify(environment).includes("@example.com") || environment.FROM_ADDRESS === "notifications@example.com");

// A site without plugins touches nothing.
wirePlugins(new Proxy({}, { get: () => assert.fail("a site without plugins must not touch the backend") }), [], undefined as never);

// Synthesis. The Python asset is a pip install, so the test uses inline code in its place.
overrideNotificationsCodeForTests(Code.fromInline("def handler(event, context): pass"));
function synthesize(settings: NotificationsConfig = config) {
  const app = new App();
  const awsEnvironment = { account, region: "us-east-1" };
  const outputs: unknown[] = [];
  const stacks: Stack[] = [];
  const dataStack = new Stack(app, "Data", { env: awsEnvironment });
  const backend = {
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
  wirePlugins(backend, [{ plugin: notificationsPlugin, config: settings }], contentActions);
  return { template: Template.fromStack(stacks[0]), dataTemplate: Template.fromStack(dataStack), outputs, stacks };
}

const { template, dataTemplate, outputs, stacks } = synthesize();
assert.deepEqual(stacks.map((stack) => stack.node.id), ["notifications"], "one stack, and only where the plugin is enabled");

// The table: retained, customer-managed key, TTL, byRecipient and byList, no point-in-time recovery.
template.resourceCountIs("AWS::DynamoDB::Table", 1);
template.hasResource("AWS::DynamoDB::Table", {
  DeletionPolicy: "Retain",
  Properties: {
    TableName: "papyrus-notifications-example",
    BillingMode: "PAY_PER_REQUEST",
    KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }, { AttributeName: "sk", KeyType: "RANGE" }],
    TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true },
    SSESpecification: { SSEEnabled: true, SSEType: "KMS", KMSMasterKeyId: Match.anyValue() },
    PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: false },
    GlobalSecondaryIndexes: [
      {
        IndexName: "byRecipient",
        KeySchema: [{ AttributeName: "recipientKey", KeyType: "HASH" }, { AttributeName: "queuedAt", KeyType: "RANGE" }],
        Projection: { ProjectionType: "ALL" },
      },
      { IndexName: "byList", KeySchema: [{ AttributeName: "gsiList", KeyType: "HASH" }], Projection: { ProjectionType: "KEYS_ONLY" } },
    ],
  },
});
template.hasResource("AWS::KMS::Key", { DeletionPolicy: "Retain", Properties: { EnableKeyRotation: true } });
template.resourceCountIs("Custom::SecureStringParameter", 1);
template.hasResourceProperties("Custom::SecureStringParameter", { ParameterName: "/papyrus/example/notifications/recipient-key" });

// Four Python arm64 functions with the right handlers, names and timeouts.
const functions = template.findResources("AWS::Lambda::Function");
const ours = Object.values(functions).filter((entry) => (entry as { Properties: { Handler?: string } }).Properties.Handler?.startsWith("papyrus_content."));
assert.equal(ours.length, 5, "router, email, flush, SES events, and the pause (no newsletter on this site)");
for (const [handler, name] of [
  [HANDLERS.router, notificationsFunctionName("example")],
  [HANDLERS.email, notificationsEmailName("example")],
  [HANDLERS.flush, "papyrus-notifications-flush-example"],
  [HANDLERS.sesEvents, "papyrus-notifications-ses-example"],
  [HANDLERS.pause, "papyrus-notifications-pause-example"],
] as const) {
  template.hasResourceProperties("AWS::Lambda::Function", {
    Handler: handler, FunctionName: name, Runtime: "python3.12", Architectures: ["arm64"],
    Environment: { Variables: Match.objectLike({ SITE_ID: "example", TABLE_NAME: Match.anyValue(), THEME_JSON: JSON.stringify(base.theme) }) },
  });
}
template.hasResourceProperties("AWS::Lambda::Function", { FunctionName: notificationsEmailName("example"), ReservedConcurrentExecutions: 1 });
template.hasResourceProperties("AWS::Lambda::Function", {
  FunctionName: notificationsFunctionName("example"),
  DeadLetterConfig: { TargetArn: Match.anyValue() },
});

// Queues: the email queue and both dead letter queues, each dead letter queue watched by an alarm with no action.
template.resourceCountIs("AWS::SQS::Queue", 3);
template.hasResourceProperties("AWS::SQS::Queue", {
  QueueName: "papyrus-notifications-example-email",
  RedrivePolicy: { maxReceiveCount: 3, deadLetterTargetArn: Match.anyValue() },
  SqsManagedSseEnabled: true,
});
template.hasResourceProperties("AWS::Lambda::EventSourceMapping", { FunctionResponseTypes: ["ReportBatchItemFailures"], BatchSize: 10 });
const alarmNames = notificationsAlarmNames("example");
template.resourceCountIs("AWS::CloudWatch::Alarm", 4);
for (const alarmName of Object.values(alarmNames)) {
  template.hasResourceProperties("AWS::CloudWatch::Alarm", {
    AlarmName: alarmName, Namespace: "AWS/SQS", MetricName: "ApproximateNumberOfMessagesVisible", Threshold: 1,
    ComparisonOperator: "GreaterThanOrEqualToThreshold", TreatMissingData: "notBreaching",
  });
}
// Without the newsletter plugin the site gets the newsletter's two rate alarms under its own names, and a pause.
for (const [alarmName, threshold] of [[notificationsPauseAlarmNames("example").bounce, 0.04], [notificationsPauseAlarmNames("example").complaint, 0.0008]] as const) {
  template.hasResourceProperties("AWS::CloudWatch::Alarm", { AlarmName: alarmName, Threshold: threshold, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching" });
}
assert.deepEqual(Object.values(notificationsPauseAlarmNames("example")), ["papyrus-notifications-example-bounce-rate", "papyrus-notifications-example-complaint-rate"], "python pause.alarm_names");
template.hasResourceProperties("AWS::Events::Rule", {
  EventPattern: {
    source: ["aws.cloudwatch"],
    "detail-type": ["CloudWatch Alarm State Change"],
    detail: { alarmName: Object.values(notificationsPauseAlarmNames("example")), state: { value: ["ALARM"] } },
  },
});
assert.match(JSON.stringify(template.findResources("AWS::IAM::Policy")), /ses:PutConfigurationSetSendingOptions/);
for (const entry of Object.values(template.findResources("AWS::CloudWatch::Alarm"))) {
  const properties = (entry as { Properties: Record<string, unknown> }).Properties;
  assert.equal(properties.AlarmActions, undefined, "no alarm listener per site: the operator piece reads every alarm");
}

// Rules: a minute schedule for the flush, and SES events of this site's configuration set only for mail Caducus tagged.
template.hasResourceProperties("AWS::Events::Rule", { ScheduleExpression: "rate(1 minute)" });
template.hasResourceProperties("AWS::Events::Rule", {
  EventPattern: {
    source: ["aws.ses"],
    detail: { mail: { tags: { "ses:configuration-set": ["papyrus-example"], delivery: [{ exists: true }], site: ["example"] } } },
  },
});
assert.ok(!JSON.stringify(template.toJSON()).match(/"(open|click|Open|Click)"/), "open and click events are never enabled");

// IAM: sending only from the configured address through this site's identity and set; the operators and key parameters only.
const policies = JSON.stringify(template.findResources("AWS::IAM::Policy"));
assert.match(policies, /ses:SendEmail/);
// The SES v2 GetAccount API is authorised by ses:GetAccount; sesv2:GetAccount does not exist and the email function was denied (found 2026-11-10 on Machines on Machines).
assert.match(policies, /"ses:GetAccount"/);
assert.doesNotMatch(policies, /sesv2:/);
assert.match(policies, /"ses:FromAddress":"notifications@example.com"/);
assert.match(policies, /identity\/example.com/);
assert.match(policies, /configuration-set\/papyrus-example/);
assert.match(policies, /parameter\/papyrus\/example\/notifications\/operators/);
assert.match(policies, /types\/Query\/fields\/getPublishedItem/);
assert.ok(!/types\/Mutation/.test(policies), "the functions never write to the content API");
assert.ok(!/"ses:\*"|"sqs:\*"|"dynamodb:\*"/.test(policies));

// Only the CMS role may invoke the router (a resource policy); no principal "*".
template.hasResourceProperties("AWS::Lambda::Permission", {
  FunctionName: Match.anyValue(), Action: "lambda:InvokeFunction", Principal: computeRoleArn,
});
assert.ok(!/"Principal":"\*"/.test(JSON.stringify(template.findResources("AWS::Lambda::Permission"))));

// The publish path: the content-actions function learns the router's name and may invoke that one function.
const contentActionsFunctions = Object.values(dataTemplate.findResources("AWS::Lambda::Function")) as Array<{ Properties: { Environment?: { Variables?: Record<string, string> } } }>;
assert.ok(contentActionsFunctions.some((entry) => entry.Properties.Environment?.Variables?.PAPYRUS_NOTIFICATIONS_FUNCTION === "papyrus-notifications-example"));
assert.ok(contentActionsFunctions.some((entry) => entry.Properties.Environment?.Variables?.PAPYRUS_PLUGINS === "notifications"));
assert.match(JSON.stringify(dataTemplate.findResources("AWS::IAM::Policy")), /function:papyrus-notifications-example/);

// Outputs: public settings (no secrets) and the function the routes invoke.
assert.equal(outputs.length, 2);
const published = (outputs[1] as { custom: { papyrusPlugins: { notifications: Record<string, unknown> } } }).custom.papyrusPlugins.notifications;
assert.deepEqual(Object.keys(published).sort(), ["basePath", "consent", "contract", "fromName", "lists", "theme"]);
assert.deepEqual(published.lists, [{ id: "stories", name: "New stories", description: "Every published story." }]);
assert.ok(!JSON.stringify(published).includes("computeRoleArn"));
assert.deepEqual(Object.keys((outputs[0] as { custom: { notifications: object } }).custom.notifications), ["actionsFunction"]);

// A site that also has the newsletter plugin: the newsletter owns the rate alarms and the pause, so none is added here.
{
  const app = new App();
  const awsEnvironment = { account, region: "us-east-1" };
  const stacks: Stack[] = [];
  const dataStack = new Stack(app, "Data", { env: awsEnvironment });
  const backend = {
    data: { resources: { tables: {}, graphqlApi: { apiId: "api" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://x.test/graphql" } } } },
    createStack: (name: string) => {
      const stack = new Stack(app, name, { env: awsEnvironment });
      stacks.push(stack);
      return stack;
    },
    addOutput: () => undefined,
  };
  const contentActions = new Function(dataStack, "ContentActions", {
    runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x"),
  });
  const newsletterStub = { manifest: { name: "newsletter" }, publicSettings: () => ({}), wire: () => undefined } as never;
  wirePlugins(backend, [{ plugin: newsletterStub, config: {} }, { plugin: notificationsPlugin, config }], contentActions);
  const withNewsletter = Template.fromStack(stacks[0]);
  withNewsletter.resourceCountIs("AWS::CloudWatch::Alarm", 2);
  assert.ok(!JSON.stringify(withNewsletter.toJSON()).includes("papyrus-notifications-pause-example"));
  assert.ok(!JSON.stringify(withNewsletter.toJSON()).includes("PutConfigurationSetSendingOptions"));
}

// Two sites do not share: a different site id gives different names and parameters, and no cross-reference.
const other = synthesize(resolveNotificationsConfig({ ...base, siteId: "other", sendingDomain: "other.example", fromAddress: "notifications@other.example", siteOrigin: "https://other.example" }));
assert.match(JSON.stringify(other.template.toJSON()), /papyrus-notifications-other/);
assert.ok(!JSON.stringify(other.template.toJSON()).includes("papyrus-notifications-example"));

console.log("notifications plugin ok");
