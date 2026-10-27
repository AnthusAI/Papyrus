import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as iam from "aws-cdk-lib/aws-iam";
import { parseSiteConfig } from "../infra/amplify-app-shell/lib/site-config";
import { KnowledgeRunStack, knowledgeRunStackName } from "../infra/scheduled-jobs/lib/knowledge-pipeline";
import { KNOWLEDGE_STAGE_NAMES, resolveKnowledgeRunConfig } from "../infra/scheduled-jobs/lib/knowledge-run-config";
import { PROJECTION_LOCK_PARAMETER_NAME, PROJECTION_LOCK_TABLE_NAME, ProjectionLockStack } from "../infra/scheduled-jobs/lib/projection-lock-stack";
import { ScheduledContainerJob } from "../infra/scheduled-jobs/lib/scheduled-container-job";

const here = path.dirname(fileURLToPath(import.meta.url));
const examplePath = path.resolve(here, "../infra/amplify-app-shell/examples/shipped.site.json");
const readExample = (): any => JSON.parse(fs.readFileSync(examplePath, "utf8"));
const env = { account: "712236451410", region: "us-east-1" };

function knowledgeStack(change: (site: any) => void = () => {}, imageTag = "test") {
  const raw = readExample();
  change(raw);
  const config = resolveKnowledgeRunConfig(parseSiteConfig(raw));
  const app = new App();
  const stack = new KnowledgeRunStack(app, "KnowledgeRun", config, { env, imageTag });
  return { stack, template: Template.fromStack(stack), config };
}

/** The state machine definition with CloudFormation references replaced by "<ref>". */
function definitionOf(template: Template): any {
  const [machine] = Object.values(template.findResources("AWS::StepFunctions::StateMachine"));
  const definition = machine.Properties.DefinitionString;
  const text = typeof definition === "string"
    ? definition
    : (definition["Fn::Join"][1] as unknown[]).map((part) => (typeof part === "string" ? part : "<ref>")).join("");
  return JSON.parse(text);
}

function policyStatements(template: Template, roleLogicalIdPrefix: string): any[] {
  return Object.entries(template.findResources("AWS::IAM::Policy"))
    .filter(([id]) => id.startsWith(roleLogicalIdPrefix))
    .flatMap(([, resource]) => resource.Properties.PolicyDocument.Statement);
}

// The example opts in to monitor stories; the base stack here is the template without that optional step (it is tested below and per example).
const { stack, template, config } = knowledgeStack((site) => { delete site.knowledgeRun.monitorStories; });
const everything = JSON.stringify(template.toJSON());
const stages = [...KNOWLEDGE_STAGE_NAMES];

// Networking: public subnets only, no NAT, gateway endpoints, egress-only security group.
assert.equal(Object.keys(template.findResources("AWS::EC2::NatGateway")).length, 0);
assert.equal(Object.keys(template.findResources("AWS::EC2::EIP")).length, 0);
template.resourceCountIs("AWS::EC2::Subnet", 2);
for (const subnet of Object.values(template.findResources("AWS::EC2::Subnet"))) {
  assert.equal(subnet.Properties.MapPublicIpOnLaunch, true);
}
const endpointServices = Object.values(template.findResources("AWS::EC2::VPCEndpoint")).map((endpoint) => JSON.stringify(endpoint.Properties.ServiceName));
assert.equal(endpointServices.length, 2);
assert.ok(endpointServices.some((service) => service.endsWith('.s3"') || service.includes(".s3")), "S3 gateway endpoint");
assert.ok(endpointServices.some((service) => service.includes(".dynamodb")), "DynamoDB gateway endpoint");
for (const endpoint of Object.values(template.findResources("AWS::EC2::VPCEndpoint"))) {
  assert.equal(endpoint.Properties.VpcEndpointType, "Gateway");
}
assert.equal(Object.keys(template.findResources("AWS::EC2::SecurityGroupIngress")).length, 0);
for (const group of Object.values(template.findResources("AWS::EC2::SecurityGroup"))) {
  assert.equal(group.Properties.SecurityGroupIngress, undefined, "the task security group admits nothing");
  assert.equal(group.Properties.SecurityGroupEgress.length, 1);
}

// Stages: strict order, Fargate RunTask.sync, public IP, retries with backoff, timeouts, Fail on failure.
const definition = definitionOf(template);
assert.equal(definition.QueryLanguage, "JSONata");
assert.equal(definition.StartAt, stages[0]);
const taskStateNames = Object.keys(definition.States).filter((name) => definition.States[name].Type === "Task");
assert.deepEqual(taskStateNames, [...stages, "trend-drafts"], "task states exist in stage order, then the optional trend-drafts step");
stages.forEach((name, index) => {
  const state = definition.States[name];
  assert.match(state.Resource, /:states:::ecs:runTask\.sync$/);
  assert.equal(state.Arguments.LaunchType, "FARGATE");
  assert.equal(state.Arguments.NetworkConfiguration.AwsvpcConfiguration.AssignPublicIp, "ENABLED");
  assert.deepEqual(state.Arguments.Overrides.ContainerOverrides[0].Command, ["papyrus", "knowledge", "cloud-run", "--stage", name]);
  assert.equal(state.Arguments.Overrides.ContainerOverrides[0].Name, "job");
  assert.equal(state.TimeoutSeconds, 7200);
  assert.equal(state.Next, index + 1 < stages.length ? stages[index + 1] : "Run-trend-drafts");
  assert.equal(state.Retry.length, 1);
  assert.deepEqual(
    { ...state.Retry[0], ErrorEquals: undefined },
    { ErrorEquals: undefined, IntervalSeconds: 60, MaxAttempts: 2, BackoffRate: 2, JitterStrategy: "FULL" },
  );
  assert.ok(state.Retry[0].ErrorEquals.includes("States.TaskFailed"));
  assert.deepEqual(state.Catch, [{ ErrorEquals: ["States.ALL"], Next: `Failed-${name}` }]);
  assert.equal(definition.States[`Failed-${name}`].Type, "Fail");
});
assert.equal(stages[stages.length - 1], "projection", "projection is the last stage");
assert.equal(definition.States.Done.Type, "Succeed");
assert.equal(
  Object.entries<any>(definition.States).filter(([, state]) => state.Next === "projection").map(([name]) => name).join(),
  "wiki-sync",
  "only wiki-sync continues into projection",
);
assert.ok(
  stages.every((name) => definition.States[name].Catch[0].Next.startsWith("Failed-")),
  "a failed stage goes to a Fail state, never on to the next stage",
);

// The optional trend-drafts step: off by default, after projection, and a failure never fails the run.
const trendParameters = template.toJSON().Parameters;
assert.equal(trendParameters.TrendDraftsEnabled.Default, "false");
assert.deepEqual(trendParameters.TrendDraftsEnabled.AllowedValues, ["true", "false"]);
assert.equal(trendParameters.TrendDraftsEndpoint.Default, "");
assert.equal(trendParameters.TrendDraftsSnapshotUrl.Default, "");
const trendGate = definition.States["Run-trend-drafts"];
assert.equal(trendGate.Type, "Choice");
assert.equal(definition.States.projection.Next, "Run-trend-drafts", "the step runs only after projection has published the snapshot");
assert.equal(trendGate.Choices.length, 1);
assert.equal(trendGate.Choices[0].Next, "trend-drafts");
assert.equal(trendGate.Default, "Done", "disabled: the run ends as before");
assert.match(trendGate.Choices[0].Condition, /^\{% '.*' = 'true' %\}$/);
const trendState = definition.States["trend-drafts"];
assert.deepEqual(trendState.Arguments.Overrides.ContainerOverrides[0].Command, ["python", "/opt/papyrus-jobs/trend_drafts.py"]);
assert.equal(trendState.Next, "Done");
assert.deepEqual(trendState.Catch, [{ ErrorEquals: ["States.ALL"], Next: "Done" }], "a failure is swallowed, not a Fail state");
assert.equal(trendState.Retry[0].MaxAttempts, 0);
assert.equal(definition.States["Failed-trend-drafts"], undefined);
assert.ok(
  trendState.Arguments.Overrides.ContainerOverrides[0].Environment.some((entry: any) => entry.Name === "TREND_DRAFTS_ENDPOINT"),
  "the endpoint reaches the step",
);
assert.ok(!everything.includes("sk-"), "no key anywhere in the template");

// The optional monitor-stories step: absent unless the site opts in with knowledgeRun.monitorStories, then off by default, after trend-drafts, never failing the run.
assert.equal(definition.States["monitor-stories"], undefined, "no monitorStories block: no step");
assert.equal(definition.States["Run-monitor-stories"], undefined);
assert.equal(trendParameters.MonitorStoriesEnabled, undefined, "no monitorStories block: the template has no extra parameter");
assert.ok(!("MONITOR_STORIES_LIMIT" in Object.fromEntries(
  (Object.values(template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
)));
{
  const withStories = knowledgeStack((site) => { site.knowledgeRun.monitorStories = { limit: 2 }; });
  const storiesDefinition = definitionOf(withStories.template);
  const storiesParameters = withStories.template.toJSON().Parameters;
  assert.equal(storiesParameters.MonitorStoriesEnabled.Default, "false");
  assert.deepEqual(storiesParameters.MonitorStoriesEnabled.AllowedValues, ["true", "false"]);
  assert.equal(storiesDefinition.States["trend-drafts"].Next, "Run-monitor-stories", "the step comes after trend-drafts");
  assert.deepEqual(storiesDefinition.States["trend-drafts"].Catch, [{ ErrorEquals: ["States.ALL"], Next: "Run-monitor-stories" }]);
  assert.equal(storiesDefinition.States["Run-trend-drafts"].Default, "Run-monitor-stories", "trend drafts off: straight on to the next optional step");
  const storiesGate = storiesDefinition.States["Run-monitor-stories"];
  assert.equal(storiesGate.Type, "Choice");
  assert.equal(storiesGate.Choices.length, 1);
  assert.equal(storiesGate.Choices[0].Next, "monitor-stories");
  assert.equal(storiesGate.Default, "Done", "disabled: the run ends as before");
  assert.match(storiesGate.Choices[0].Condition, /^\{% '.*' = 'true' %\}$/);
  const storiesState = storiesDefinition.States["monitor-stories"];
  assert.deepEqual(storiesState.Arguments.Overrides.ContainerOverrides[0].Command, ["python", "/opt/papyrus-jobs/monitor_stories.py"]);
  assert.equal(storiesState.Next, "Done");
  assert.deepEqual(storiesState.Catch, [{ ErrorEquals: ["States.ALL"], Next: "Done" }], "a failure is swallowed, not a Fail state");
  assert.equal(storiesState.Retry[0].MaxAttempts, 0);
  assert.equal(storiesDefinition.States["Failed-monitor-stories"], undefined);
  assert.ok(storiesState.Arguments.Overrides.ContainerOverrides[0].Environment.some((entry: any) => entry.Name === "MONITOR_STORIES_ENDPOINT"), "the endpoint reaches the step");
  const storiesEnvironment = Object.fromEntries(
    (Object.values(withStories.template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
  );
  assert.equal(storiesEnvironment.MONITOR_STORIES_LIMIT, "2");
  assert.equal(storiesEnvironment.KNOWLEDGE_LEDGER_TABLE !== undefined, true, "the step finds the ledger table it writes its cost row to");
  assert.equal(knowledgeStack((site) => { site.knowledgeRun.monitorStories = {}; }).config.monitorStories?.limit, 3, "the default is three a run");
}

// Execution input contract: JSONata expressions over the execution context, per stage.
const environmentOverrides = Object.fromEntries(
  definition.States["snapshot"].Arguments.Overrides.ContainerOverrides[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
);
assert.match(environmentOverrides.KNOWLEDGE_PUBLICATION, /^\{% \$exists\(\$states\.context\.Execution\.Input\.publication\) \? .* : 'shipped' %\}$/);
assert.equal(environmentOverrides.KNOWLEDGE_EXECUTION_NAME, "{% $states.context.Execution.Name %}");
assert.equal(environmentOverrides.KNOWLEDGE_EXECUTION_START, "{% $states.context.Execution.StartTime %}");
assert.match(environmentOverrides.KNOWLEDGE_FAIL_STAGE, /Execution\.Input\.failStage.* : '' %\}$/);

// State machine type, logging, tracing.
template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
  StateMachineType: "STANDARD",
  LoggingConfiguration: { Level: "ERROR" },
  TracingConfiguration: { Enabled: false },
});
template.hasResourceProperties("AWS::Logs::LogGroup", { RetentionInDays: 30 });

// Task definition: one ARM64 Graviton definition, 4 vCPU / 16 GB / 40 GiB, container "job", awslogs, static env.
template.resourceCountIs("AWS::ECS::TaskDefinition", 1);
template.hasResourceProperties("AWS::ECS::TaskDefinition", {
  Cpu: "4096",
  Memory: "16384",
  EphemeralStorage: { SizeInGiB: 40 },
  RuntimePlatform: { CpuArchitecture: "ARM64", OperatingSystemFamily: "LINUX" },
  RequiresCompatibilities: ["FARGATE"],
  ContainerDefinitions: [Match.objectLike({ Name: "job", LogConfiguration: Match.objectLike({ LogDriver: "awslogs" }) })],
});
const taskDefinition = Object.values(template.findResources("AWS::ECS::TaskDefinition"))[0];
const staticEnvironment = Object.fromEntries(taskDefinition.Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]));
assert.deepEqual(Object.keys(staticEnvironment).sort(), [
  "AWS_REGION", "HF_HOME", "HF_HUB_OFFLINE", "KNOWLEDGE_ALLOW_TEST_FAILURE", "KNOWLEDGE_BEATS_CONFIG", "KNOWLEDGE_CONTENT_ACTIONS_FUNCTION", "KNOWLEDGE_AMPLIFY_APP_ID", "PAPYRUS_PLUGINS",
  "KNOWLEDGE_APPSYNC_API_ID", "KNOWLEDGE_CONCEPT_KINDS", "KNOWLEDGE_LEDGER_TABLE", "KNOWLEDGE_MONITOR_SOURCES", "KNOWLEDGE_MONITOR_SUGGESTIONS", "KNOWLEDGE_OPENAI_KEY_PARAMETER", "KNOWLEDGE_PUBLICATION", "KNOWLEDGE_SITE_BRANCH",
  "KNOWLEDGE_SITE_REPO", "KNOWLEDGE_STATE_BUCKET", "KNOWLEDGE_STATIC_SUBDIR", "PAPYRUS_EDGE_DISTRIBUTION_ID", "PAPYRUS_PROJECTION_LOCK_TABLE",
  "PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS", "PAPYRUS_PUBLICATION_KIND", "PAPYRUS_REDIRECTS_KVS_ARN", "PAPYRUS_SITE_BUCKET", "TREND_DRAFTS_MAX_AGE_DAYS",
].sort());
assert.equal(staticEnvironment.TREND_DRAFTS_MAX_AGE_DAYS, "1", "the trend-drafts step accepts a snapshot one day older than the execution by default");
const withTrendKnobs = knowledgeStack((site) => { site.knowledgeRun.trendWindowDays = 14; site.knowledgeRun.trendSnapshotMaxAgeDays = 3; site.knowledgeRun.trendCooldownDays = 0; });
const trendEnvironment = Object.fromEntries(
  (Object.values(withTrendKnobs.template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
);
assert.ok(!("TREND_DRAFTS_WINDOW_DAYS" in trendEnvironment), "trendWindowDays is retired: accepted, no variable");
assert.equal(trendEnvironment.TREND_DRAFTS_MAX_AGE_DAYS, "3");
assert.ok(!("TREND_DRAFTS_COOLDOWN_DAYS" in trendEnvironment), "trendCooldownDays is retired: accepted, no variable");
assert.equal(staticEnvironment.PAPYRUS_PROJECTION_LOCK_TABLE, PROJECTION_LOCK_TABLE_NAME);
assert.equal(staticEnvironment.PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS, "1800");
assert.equal(staticEnvironment.KNOWLEDGE_MONITOR_SOURCES, "huggingface,routed");
assert.equal(staticEnvironment.KNOWLEDGE_CONCEPT_KINDS, "task,technique,concept,model_family");
const withoutMonitors = knowledgeStack((site) => { delete site.knowledgeRun.monitorSources; delete site.knowledgeRun.monitorWeeks; delete site.knowledgeRun.monitorSuggestions; });
const plainEnvironment = Object.fromEntries(
  (Object.values(withoutMonitors.template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
);
assert.ok(!("KNOWLEDGE_MONITOR_SOURCES" in plainEnvironment), "monitor records are opt-in: no source set, no variable");
assert.ok(!("KNOWLEDGE_MONITOR_WEEKS" in staticEnvironment), "no monitorWeeks in the example config: no variable, so every record counts (all history)");
const withMonitors = knowledgeStack((site) => { site.knowledgeRun.monitorSources = ["huggingface"]; site.knowledgeRun.monitorWeeks = 26; site.knowledgeRun.monitorSuggestions = 5; });
const monitorEnvironment = Object.fromEntries(
  (Object.values(withMonitors.template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
);
assert.equal(monitorEnvironment.KNOWLEDGE_MONITOR_SOURCES, "huggingface");
assert.equal(monitorEnvironment.KNOWLEDGE_MONITOR_WEEKS, "26");
assert.equal(monitorEnvironment.KNOWLEDGE_MONITOR_SUGGESTIONS, "5");
const withRouted = knowledgeStack((site) => { site.knowledgeRun.monitorSources = ["routed"]; });
const routedEnvironment = Object.fromEntries(
  (Object.values(withRouted.template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
);
assert.equal(routedEnvironment.KNOWLEDGE_MONITOR_SOURCES, "routed", "routed References are a monitor source of their own");
assert.ok(!("KNOWLEDGE_AUTHORING_ROLE_ARN" in staticEnvironment), "the task role signs AppSync itself; there is no role to assume");
assert.equal(staticEnvironment.PAPYRUS_PUBLICATION_KIND, "s3-projection");
assert.equal(staticEnvironment.PAPYRUS_PLUGINS, "newsletter,reader-steering", "the plugin list comes from site config");
assert.equal(staticEnvironment.KNOWLEDGE_AMPLIFY_APP_ID, "dkycd9pntgo6d");
assert.equal(staticEnvironment.KNOWLEDGE_CONTENT_ACTIONS_FUNCTION, "amplify-dkycd9pntgo6d-mai-papyruscontentactionsE8B-p01l4veHquVE");

// ECR repository.
template.hasResourceProperties("AWS::ECR::Repository", {
  RepositoryName: "papyrus-scheduled-jobs/knowledge-run",
  ImageScanningConfiguration: { ScanOnPush: true },
  ImageTagMutability: "IMMUTABLE",
  LifecyclePolicy: { LifecyclePolicyText: Match.stringLikeRegexp('"countNumber":10') },
});
assert.ok(JSON.stringify(taskDefinition.Properties.ContainerDefinitions[0].Image).endsWith(`"/",{"Ref":"JobRepositoryB1C7F3D3"},":test"]]}`), "image tag comes from context");
assert.ok(
  JSON.stringify(knowledgeStack(() => {}, "placeholder").template.toJSON()).includes(':placeholder"'),
  "a placeholder tag synthesizes",
);

// State bucket and ledger.
template.hasResourceProperties("AWS::S3::Bucket", {
  VersioningConfiguration: { Status: "Enabled" },
  BucketEncryption: { ServerSideEncryptionConfiguration: [{ ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } }] },
  PublicAccessBlockConfiguration: { BlockPublicAcls: true, BlockPublicPolicy: true, IgnorePublicAcls: true, RestrictPublicBuckets: true },
  LifecycleConfiguration: {
    Rules: [
      Match.objectLike({ NoncurrentVersionExpiration: { NoncurrentDays: 90 }, Status: "Enabled" }),
      Match.objectLike({ Prefix: "runs/", ExpirationInDays: 120, Status: "Enabled" }),
    ],
  },
});
template.hasResource("AWS::S3::Bucket", { DeletionPolicy: "Retain", UpdateReplacePolicy: "Retain" });
template.hasResourceProperties("AWS::S3::BucketPolicy", {
  PolicyDocument: { Statement: Match.arrayWith([Match.objectLike({ Effect: "Deny", Condition: { Bool: { "aws:SecureTransport": "false" } } })]) },
});
template.hasResourceProperties("AWS::DynamoDB::Table", {
  BillingMode: "PAY_PER_REQUEST",
  KeySchema: [{ AttributeName: "publication", KeyType: "HASH" }, { AttributeName: "runKey", KeyType: "RANGE" }],
  PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
  TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true },
});
template.hasResource("AWS::DynamoDB::Table", { DeletionPolicy: "Retain", UpdateReplacePolicy: "Retain" });

// Alarms and SNS. The address comes from an SSM parameter reference, never inline.
const subscription = Object.values(template.findResources("AWS::SNS::Subscription"))[0];
assert.equal(subscription.Properties.Protocol, "email");
assert.ok(subscription.Properties.Endpoint.Ref, "the endpoint is a reference");
const parameter = template.toJSON().Parameters[subscription.Properties.Endpoint.Ref];
assert.equal(parameter.Type, "AWS::SSM::Parameter::Value<String>");
assert.equal(parameter.Default, "/papyrus/shipped/knowledge-run/alarm-email");
assert.ok(!everything.includes("@"), "no e-mail address anywhere in the template");
template.hasResourceProperties("AWS::CloudWatch::Alarm", {
  ComparisonOperator: "GreaterThanOrEqualToThreshold",
  Threshold: 1,
  EvaluationPeriods: 1,
  TreatMissingData: "notBreaching",
  AlarmActions: [{ Ref: Match.stringLikeRegexp("^JobAlarmTopic") }],
  Metrics: Match.arrayWith([
    Match.objectLike({ Expression: "FILL(failed, 0) + FILL(aborted, 0) + FILL(timedOut, 0)" }),
    Match.objectLike({ MetricStat: Match.objectLike({ Metric: Match.objectLike({ MetricName: "ExecutionsFailed" }), Period: 300 }) }),
    Match.objectLike({ MetricStat: Match.objectLike({ Metric: Match.objectLike({ MetricName: "ExecutionsAborted" }) }) }),
    Match.objectLike({ MetricStat: Match.objectLike({ Metric: Match.objectLike({ MetricName: "ExecutionsTimedOut" }) }) }),
  ]),
});
// Missed week: CloudWatch cannot look back 8 days, so a daily watchdog publishes the days since the last success.
template.hasResourceProperties("AWS::CloudWatch::Alarm", {
  MetricName: "DaysSinceLastSuccess",
  Namespace: "Papyrus/ScheduledJob",
  Dimensions: [{ Name: "Job", Value: "knowledge-run" }, { Name: "Publication", Value: "shipped" }],
  Statistic: "Maximum",
  Period: 86400,
  EvaluationPeriods: 1,
  Threshold: 8,
  ComparisonOperator: "GreaterThanOrEqualToThreshold",
  TreatMissingData: "breaching",
  AlarmActions: [{ Ref: Match.stringLikeRegexp("^JobAlarmTopic") }],
});
template.hasResourceProperties("AWS::Lambda::Function", { Runtime: "python3.12", Architectures: ["arm64"], Environment: { Variables: Match.objectLike({ JOB: "knowledge-run", PUBLICATION: "shipped" }) } });
template.hasResourceProperties("AWS::Events::Rule", { ScheduleExpression: "cron(17 12 * * ? *)" });
// boto3 names the Step Functions client "stepfunctions" ("states" is the IAM prefix, not a boto3 service); the first deploy had it wrong.
const watchdog: any = Object.values(template.findResources("AWS::Lambda::Function")).find((fn: any) => fn.Properties.Description?.startsWith("Publishes the days since"));
assert.ok(watchdog, "the watchdog function exists");
assert.match(watchdog.Properties.Code.ZipFile, /boto3\.client\("stepfunctions"\)/);
assert.doesNotMatch(watchdog.Properties.Code.ZipFile, /boto3\.client\("states"\)/);
const watchdogStatements = policyStatements(template, "JobMissedWeekWatchdogServiceRoleDefaultPolicy");
assert.deepEqual(watchdogStatements.map((statement: any) => statement.Action).sort(), ["cloudwatch:PutMetricData", "states:ListExecutions"]);

// Schedule and its role.
template.hasResourceProperties("AWS::Scheduler::Schedule", {
  ScheduleExpression: "cron(0 5 * * ? *)",
  ScheduleExpressionTimezone: "UTC",
  State: "ENABLED",
  FlexibleTimeWindow: { Mode: "OFF" },
  Target: Match.objectLike({ Input: '{"publication":"shipped"}', Arn: { Ref: Match.stringLikeRegexp("^JobStateMachine") } }),
});
const scheduleStatements = policyStatements(template, "JobScheduleRoleDefaultPolicy");
assert.equal(scheduleStatements.length, 1);
assert.deepEqual(scheduleStatements[0].Action, "states:StartExecution");
assert.ok(scheduleStatements[0].Resource.Ref.startsWith("JobStateMachine"));
assert.equal(knowledgeStack((site) => { site.knowledgeRun.scheduleState = "DISABLED"; site.knowledgeRun.schedule = "cron(0 6 ? * TUE *)"; }).template
  .findResources("AWS::Scheduler::Schedule")["JobSchedule08391582"].Properties.State, "DISABLED");

// Task role: least privilege, SSM and not Secrets Manager.
const taskStatements = policyStatements(template, "JobTaskRoleDefaultPolicy");
const allowedActions = new Set([
  "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:ListBucket", "s3:GetBucketLocation",
  "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
  "ssm:GetParameter", "appsync:GraphQL", "lambda:GetFunctionConfiguration", "amplify:ListJobs", "cloudfront:CreateInvalidation", "cloudfront:DescribeKeyValueStore",
  "cloudfront-keyvaluestore:DescribeKeyValueStore", "cloudfront-keyvaluestore:GetKey", "cloudfront-keyvaluestore:ListKeys",
  "cloudfront-keyvaluestore:PutKey", "cloudfront-keyvaluestore:DeleteKey", "cloudfront-keyvaluestore:UpdateKeys",
]);
for (const statement of taskStatements) {
  const actions = ([] as string[]).concat(statement.Action);
  for (const action of actions) assert.ok(allowedActions.has(action), `unexpected task role action ${action}`);
  assert.ok(!actions.some((action) => action.includes("*")), "no wildcard actions");
  assert.equal(statement.Effect, "Allow");
  assert.notEqual(statement.Resource, "*", `${statement.Sid} must name its resources`);
  assert.ok(!([] as string[]).concat(statement.Resource).includes("*"));
}
const statementBySid = (sid: string) => taskStatements.find((statement) => statement.Sid === sid);
assert.deepEqual(statementBySid("ProjectionLockTable").Action, ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]);
assert.deepEqual(statementBySid("ProjectionLockTable").Resource, "arn:aws:dynamodb:us-east-1:712236451410:table/papyrus-projection-locks");
assert.deepEqual(statementBySid("ReadParameters").Resource, [
  `arn:aws:ssm:us-east-1:712236451410:parameter${PROJECTION_LOCK_PARAMETER_NAME}`,
  "arn:aws:ssm:us-east-1:712236451410:parameter/papyrus/shipped/openai-api-key",
]);
assert.deepEqual(statementBySid("SignAppSyncRequests").Resource, [
  "arn:aws:appsync:us-east-1:712236451410:apis/6sw6454pozbgvdgm233gqkxsxu/types/Query/fields/*",
  "arn:aws:appsync:us-east-1:712236451410:apis/6sw6454pozbgvdgm233gqkxsxu/types/Mutation/fields/*",
]);
assert.deepEqual(
  statementBySid("ReadContentActionsConfiguration").Resource,
  "arn:aws:lambda:us-east-1:712236451410:function:amplify-dkycd9pntgo6d-mai-papyruscontentactionsE8B-p01l4veHquVE",
);
assert.deepEqual(statementBySid("ReadContentActionsConfiguration").Action, "lambda:GetFunctionConfiguration");
assert.deepEqual(statementBySid("ReadDeployedCommit").Resource, [
  "arn:aws:amplify:us-east-1:712236451410:apps/dkycd9pntgo6d/branches/main",
  "arn:aws:amplify:us-east-1:712236451410:apps/dkycd9pntgo6d/branches/main/jobs/*",
]);
assert.deepEqual(statementBySid("SiteBucketObjects").Resource, `arn:aws:s3:::${config.siteBucket}/*`);
assert.deepEqual(statementBySid("SiteBucketList").Resource, `arn:aws:s3:::${config.siteBucket}`);
assert.deepEqual(statementBySid("InvalidateEdge").Resource, "arn:aws:cloudfront::712236451410:distribution/EUQZ249T4OKXH");
assert.deepEqual(statementBySid("RedirectsKeyValueStore").Resource, config.redirectsKvsArn);
assert.ok(!everything.toLowerCase().includes("secretsmanager"), "SSM only: no Secrets Manager anywhere");
template.hasResourceProperties("AWS::IAM::Role", {
  AssumeRolePolicyDocument: { Statement: [Match.objectLike({ Principal: { Service: "ecs-tasks.amazonaws.com" } })] },
});

// Outputs, tags, termination protection, stack name.
assert.deepEqual(
  Object.keys(template.toJSON().Outputs).sort(),
  ["AlarmTopicArn", "ClusterName", "LedgerTableName", "RepositoryUri", "StateBucketName", "StateMachineArn", "TaskDefinitionArn"],
);
assert.equal(stack.terminationProtection, true);
assert.equal(stack.stackName, "papyrus-scheduled-job-knowledge-run-shipped");
assert.equal(knowledgeRunStackName("shipped"), "papyrus-scheduled-job-knowledge-run-shipped");
for (const type of ["AWS::S3::Bucket", "AWS::DynamoDB::Table", "AWS::StepFunctions::StateMachine", "AWS::ECS::Cluster", "AWS::ECR::Repository", "AWS::SNS::Topic", "AWS::CloudWatch::Alarm", "AWS::EC2::VPC"]) {
  for (const [id, resource] of Object.entries<any>(template.findResources(type))) {
    const tags = Object.fromEntries((resource.Properties.Tags ?? []).map((tag: any) => [tag.Key, tag.Value]));
    assert.equal(tags.Project, "Papyrus", `${id} tagged Project`);
    assert.equal(tags.Publication, "shipped", `${id} tagged Publication`);
  }
}

// The lock table lives in its own stack with an SSM parameter holding its name.
const lockApp = new App();
const lockStack = new ProjectionLockStack(lockApp, "ProjectionLock", { env });
const lockTemplate = Template.fromStack(lockStack);
assert.equal(lockStack.stackName, "papyrus-projection-lock");
assert.equal(lockStack.terminationProtection, true);
lockTemplate.resourceCountIs("AWS::DynamoDB::Table", 1);
lockTemplate.hasResourceProperties("AWS::DynamoDB::Table", {
  TableName: "papyrus-projection-locks",
  KeySchema: [{ AttributeName: "publication", KeyType: "HASH" }],
  BillingMode: "PAY_PER_REQUEST",
  TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true },
});
lockTemplate.hasResource("AWS::DynamoDB::Table", { DeletionPolicy: "Retain", UpdateReplacePolicy: "Retain" });
lockTemplate.hasResourceProperties("AWS::SSM::Parameter", {
  Name: "/papyrus/projection-lock/table-name",
  Type: "String",
  Value: { Ref: Match.stringLikeRegexp("^LockTable") },
});
assert.equal(Object.keys(template.findResources("AWS::DynamoDB::Table")).length, 1, "the job stack holds only the ledger table");
assert.ok(!everything.includes('"TableName":"papyrus-projection-locks"'));

// Failure injection input is only an environment value; stage and size overrides come from config.
const resized = knowledgeStack((site) => {
  Object.assign(site.knowledgeRun, { vCpu: 8, memoryMiB: 32768, ephemeralStorageGiB: 100, stageTimeouts: { "topic-model": 14400 } });
});
resized.template.hasResourceProperties("AWS::ECS::TaskDefinition", { Cpu: "8192", Memory: "32768", EphemeralStorage: { SizeInGiB: 100 } });
assert.equal(definitionOf(resized.template).States["topic-model"].TimeoutSeconds, 14400);
assert.equal(definitionOf(resized.template).States["corpus-sync"].TimeoutSeconds, 7200);
const customised = knowledgeStack((site) => {
  Object.assign(site.knowledgeRun, {
    openAiKeyParameter: "/papyrus/other/key",
    alarmEmailParameter: "/papyrus/other/alarm",
    environment: { EXTRA_FLAG: "1", HF_HOME: "/elsewhere" },
  });
});
const customStatements = policyStatements(customised.template, "JobTaskRoleDefaultPolicy");
assert.ok(JSON.stringify(customStatements).includes("parameter/papyrus/other/key"));
assert.ok(JSON.stringify(customised.template.toJSON().Parameters).includes("/papyrus/other/alarm"));
const customEnvironment = Object.fromEntries(
  Object.values<any>(customised.template.findResources("AWS::ECS::TaskDefinition"))[0].Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]),
);
assert.equal(customEnvironment.EXTRA_FLAG, "1");
assert.equal(customEnvironment.HF_HOME, "/opt/hf", "computed variables win over the free-form map");

// Generality: a different pipeline with per-stage sizes, retry and environment synthesizes with the same construct.
{
  const app = new App();
  const other = new Stack(app, "Other", { env });
  new ScheduledContainerJob(other, "Job", {
    jobId: "trend-story",
    publication: "demo",
    pipeline: {
      stages: [
        { name: "gather", command: ["python", "gather.py"] },
        { name: "render", command: ["python", "render.py"], vCpu: 2, memoryMiB: 8192, ephemeralStorageGiB: 30, timeoutSeconds: 900, retry: { maxAttempts: 5 }, environment: { MODE: "fast" } },
      ],
    },
    imageTag: "x",
    defaultSize: { vCpu: 4, memoryMiB: 16384, ephemeralStorageGiB: 40 },
    defaultStageTimeoutSeconds: 3600,
    schedule: { expression: "cron(0 7 ? * FRI *)", state: "ENABLED" },
    scheduleInput: { publication: "demo" },
    environment: {},
    stateBucketEnvVar: "JOB_STATE_BUCKET",
    ledgerTableEnvVar: "JOB_LEDGER_TABLE",
    taskPolicyStatements: [new iam.PolicyStatement({ actions: ["ssm:GetParameter"], resources: ["arn:aws:ssm:us-east-1:712236451410:parameter/demo/key"] })],
    alarmEmailParameter: "/demo/alarm",
  });
  const otherTemplate = Template.fromStack(other);
  otherTemplate.resourceCountIs("AWS::ECS::TaskDefinition", 2);
  otherTemplate.hasResourceProperties("AWS::ECR::Repository", { RepositoryName: "papyrus-scheduled-jobs/trend-story" });
  const otherDefinition = definitionOf(otherTemplate);
  assert.equal(otherDefinition.States.gather.Next, "render");
  assert.equal(otherDefinition.States.gather.TimeoutSeconds, 3600);
  assert.equal(otherDefinition.States.render.TimeoutSeconds, 900);
  assert.equal(otherDefinition.States.render.Retry[0].MaxAttempts, 5);
  assert.equal(otherDefinition.States.render.Next, "Done");
  assert.notEqual(otherDefinition.States.gather.Arguments.TaskDefinition, otherDefinition.States.render.Arguments.TaskDefinition);
  assert.equal(Object.keys(otherTemplate.findResources("AWS::EC2::NatGateway")).length, 0);
  assert.throws(() => new ScheduledContainerJob(new Stack(new App(), "Empty", { env }), "Job", { ...({} as any), pipeline: { stages: [] } }), /at least one stage/);
}

// Configuration validation names the offending field.
const rejects = (change: (block: any) => void, pattern: RegExp) => {
  const raw = readExample();
  change(raw.knowledgeRun);
  assert.throws(() => resolveKnowledgeRunConfig(parseSiteConfig(raw)), pattern);
};
rejects((block) => { block.surprise = 1; }, /knowledgeRun\.surprise is not a known field/);
rejects((block) => { delete block.siteBucket; }, /knowledgeRun\.siteBucket must be a non-empty string/);
rejects((block) => { block.redirectsKvsArn = "arn:aws:cloudfront::1:distribution/x"; }, /knowledgeRun\.redirectsKvsArn is invalid/);
rejects((block) => { block.edgeDistributionId = "nope"; }, /knowledgeRun\.edgeDistributionId is invalid/);
rejects((block) => { block.vCpu = 3; }, /knowledgeRun\.vCpu must be one of/);
rejects((block) => { block.memoryMiB = 4096; }, /knowledgeRun\.memoryMiB must be at least/);
rejects((block) => { block.ephemeralStorageGiB = 10; }, /knowledgeRun\.ephemeralStorageGiB must be an integer from 21 to 200/);
rejects((block) => { block.scheduleState = "PAUSED"; }, /knowledgeRun\.scheduleState must be "ENABLED" or "DISABLED"/);
rejects((block) => { block.schedule = "every monday"; }, /knowledgeRun\.schedule is invalid/);
rejects((block) => { block.stageTimeouts = { bogus: 60 }; }, /knowledgeRun\.stageTimeouts\.bogus is not a stage/);
rejects((block) => { block.stageTimeouts = { snapshot: 5 }; }, /knowledgeRun\.stageTimeouts\.snapshot must be an integer/);
rejects((block) => { block.conceptKinds = []; }, /knowledgeRun\.conceptKinds must be a non-empty array/);
rejects((block) => { block.monitorSources = []; }, /knowledgeRun\.monitorSources must be a non-empty array/);
rejects((block) => { block.monitorSources = ["rss"]; }, /knowledgeRun\.monitorSources names an unsupported source "rss"/);
rejects((block) => { block.monitorSuggestions = 21; }, /knowledgeRun\.monitorSuggestions must be an integer from 0 to 20/);
rejects((block) => { block.trendSnapshotMaxAgeDays = 8; }, /knowledgeRun\.trendSnapshotMaxAgeDays must be an integer from 0 to 7/);
rejects((block) => { block.monitorStories = { limit: 0 }; }, /knowledgeRun\.monitorStories\.limit must be an integer from 1 to 20/);
rejects((block) => { block.monitorStories = { limit: 21 }; }, /knowledgeRun\.monitorStories\.limit must be an integer from 1 to 20/);
rejects((block) => { block.monitorStories = { sources: ["hn"] }; }, /knowledgeRun\.monitorStories\.sources is not a known field/);
rejects((block) => { block.monitorStories = 3; }, /knowledgeRun\.monitorStories must be an object/);
rejects((block) => { block.monitorWeeks = 0; }, /knowledgeRun\.monitorWeeks must be an integer from 1 to 260/);
rejects((block) => { block.environment = { "1BAD": "x" }; }, /knowledgeRun\.environment\.1BAD is not a valid environment variable name/);
rejects((block) => { block.corpusKey = "Not A Key"; }, /knowledgeRun\.corpusKey is invalid/);
rejects((block) => { block.corpusKey = ""; }, /knowledgeRun\.corpusKey must be a non-empty string/);
rejects((block) => { block.openAiKeyParameter = "no-slash"; }, /knowledgeRun\.openAiKeyParameter is invalid/);
assert.throws(() => resolveKnowledgeRunConfig(parseSiteConfig((() => { const raw = readExample(); delete raw.knowledgeRun; return raw; })())), /has no knowledgeRun block/);
assert.throws(() => resolveKnowledgeRunConfig(parseSiteConfig((() => { const raw = readExample(); delete raw.aws; return raw; })())), /needs aws\.accountId and aws\.region/);

// Any site: a corpus key of its own, shared SSM parameters, and Shipped unchanged by all of it.
const environmentOf = (built: { template: Template }): Record<string, string> =>
  Object.fromEntries((Object.values(built.template.findResources("AWS::ECS::TaskDefinition"))[0] as any).Properties.ContainerDefinitions[0].Environment.map((entry: any) => [entry.Name, entry.Value]));
assert.ok(!("KNOWLEDGE_CORPUS_KEY" in staticEnvironment), "Shipped names no corpus key: the tasks find the corpus by the siteId, as before");
assert.equal(config.corpusKey, undefined);
assert.equal(staticEnvironment.KNOWLEDGE_APPSYNC_API_ID, "6sw6454pozbgvdgm233gqkxsxu", "the stage can seed config/amplify_outputs.json from the API id");
const withCorpusKey = knowledgeStack((site) => { delete site.knowledgeRun.monitorStories; site.knowledgeRun.corpusKey = "ai-ml-research"; });
const corpusEnvironment = environmentOf(withCorpusKey);
assert.equal(withCorpusKey.config.corpusKey, "ai-ml-research");
assert.equal(corpusEnvironment.KNOWLEDGE_CORPUS_KEY, "ai-ml-research");
assert.equal(corpusEnvironment.KNOWLEDGE_PUBLICATION, "shipped", "state, ledger and alarms stay keyed by the siteId");
assert.deepEqual(
  Object.keys(corpusEnvironment).filter((name) => !(name in staticEnvironment)),
  ["KNOWLEDGE_CORPUS_KEY"],
  "a corpus key adds one variable and changes nothing else",
);
assert.equal(withCorpusKey.stack.stackName, stack.stackName);
const withoutCorpusKey = environmentOf(knowledgeStack((site) => { delete site.knowledgeRun.monitorStories; delete site.knowledgeRun.corpusKey; }));
assert.deepEqual(withoutCorpusKey, staticEnvironment, "Shipped's task environment is what it was");
{
  const base = knowledgeStack();
  assert.deepEqual(base.template.toJSON(), knowledgeStack((site) => { site.knowledgeRun.corpusKey = undefined; }).template.toJSON(), "an absent corpus key leaves the template untouched");
}

// A site may name any existing SSM parameter for the OpenAI key and the alarm address, and several sites may share them.
const sharedKey = "/papyrus/shared/openai-api-key";
const sharedAlarm = "/papyrus/shared/knowledge-run/alarm-email";
const sharedFor = (siteId: string) => knowledgeStack((site) => {
  site.siteId = siteId;
  site.knowledgeRun.openAiKeyParameter = sharedKey;
  site.knowledgeRun.alarmEmailParameter = sharedAlarm;
});
for (const siteId of ["shipped", "p-apyr-us"]) {
  const shared = sharedFor(siteId);
  assert.equal(shared.config.openAiKeyParameter, sharedKey);
  assert.equal(environmentOf(shared).KNOWLEDGE_OPENAI_KEY_PARAMETER, sharedKey);
  const readParameters = shared.template.toJSON();
  assert.match(JSON.stringify(readParameters), /parameter\/papyrus\/shared\/openai-api-key/, "the task role may read the shared key, and only that parameter");
  assert.ok(!JSON.stringify(readParameters).includes(`/papyrus/${siteId}/openai-api-key`), "the per-site default name is not granted");
  const alarmParameter = Object.values(shared.template.findParameters("*")).find((entry: any) => entry.Type === "AWS::SSM::Parameter::Value<String>") as any;
  assert.equal(alarmParameter.Default, sharedAlarm);
  assert.equal(shared.stack.stackName, knowledgeRunStackName(siteId), "each site still has a stack and an alarm topic of its own");
}

// Every site's example config carries a daily, staggered knowledge run that files routed records and monitor-story drafts.
const SHIPPED_KEY = "/papyrus/shipped/openai-api-key";
const SHIPPED_ALARM = "/papyrus/shipped/knowledge-run/alarm-email";
const siteExpectations: Record<string, { hour: number; key: string; corpusKey?: string; distribution?: string }> = {
  shipped: { hour: 5, key: SHIPPED_KEY },
  "anth-us": { hour: 6, key: SHIPPED_KEY },
  "threat-intelligence": { hour: 7, key: "/amplify/shared/d12wnrx15qbcc2/OPENAI_API_KEY" },
  distinctive: { hour: 8, key: "/amplify/shared/d2xke8ygmrzqpp/OPENAI_API_KEY" },
  "pilobol-us": { hour: 9, key: SHIPPED_KEY },
  "p-apyr-us": { hour: 10, key: "/papyrus/p-apyr-us/openai-api-key", corpusKey: "ai-ml-research", distribution: "E2EM0JLBC2W9WW" },
  dataparade: { hour: 11, key: "/amplify/shared/d35q7zv4zad2we/OPENAI_API_KEY", corpusKey: "data-parade" },
};
const exampleDirectory = path.dirname(examplePath);
const seenHours = new Set<number>();
for (const [siteId, expected] of Object.entries(siteExpectations)) {
  const site = JSON.parse(fs.readFileSync(path.join(exampleDirectory, `${siteId}.site.json`), "utf8"));
  const resolved = resolveKnowledgeRunConfig(parseSiteConfig(site));
  assert.equal(resolved.publication, siteId);
  assert.equal(resolved.schedule, `cron(0 ${expected.hour} * * ? *)`, `${siteId} runs daily at its own hour`);
  assert.ok(!seenHours.has(expected.hour), `${siteId}: no two sites share an hour`);
  seenHours.add(expected.hour);
  assert.ok(resolved.monitorSources?.includes("routed"), `${siteId} counts routed monitor records`);
  assert.equal(resolved.monitorWeeks, undefined, `${siteId} sets no monitorWeeks: all history counts`);
  assert.deepEqual(resolved.monitorStories, { limit: 3 });
  assert.equal(resolved.openAiKeyParameter, expected.key);
  assert.equal(resolved.alarmEmailParameter, SHIPPED_ALARM);
  assert.equal(resolved.corpusKey, expected.corpusKey);
  if (expected.distribution) assert.equal(resolved.edgeDistributionId, expected.distribution);
  const built = new KnowledgeRunStack(new App(), `KnowledgeRun-${siteId}`, resolved, { env, imageTag: "test" });
  assert.equal(built.stackName, knowledgeRunStackName(siteId));
  assert.equal(Object.keys(Template.fromStack(built).toJSON().Resources).length, 41, `${siteId}: the same 41 resources as Shipped (42 with the CDK metadata a synth adds)`);
}

console.log("scheduled job synth: ok");
