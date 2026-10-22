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

const { stack, template, config } = knowledgeStack();
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
assert.deepEqual(taskStateNames, stages, "task states exist in stage order");
stages.forEach((name, index) => {
  const state = definition.States[name];
  assert.match(state.Resource, /:states:::ecs:runTask\.sync$/);
  assert.equal(state.Arguments.LaunchType, "FARGATE");
  assert.equal(state.Arguments.NetworkConfiguration.AwsvpcConfiguration.AssignPublicIp, "ENABLED");
  assert.deepEqual(state.Arguments.Overrides.ContainerOverrides[0].Command, ["papyrus", "knowledge", "cloud-run", "--stage", name]);
  assert.equal(state.Arguments.Overrides.ContainerOverrides[0].Name, "job");
  assert.equal(state.TimeoutSeconds, 7200);
  assert.equal(state.Next, index + 1 < stages.length ? stages[index + 1] : "Done");
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
  Object.entries<any>(definition.States).filter(([, state]) => state.Type === "Task").every(([, state]) => state.Catch[0].Next.startsWith("Failed-")),
  "a failed stage goes to a Fail state, never on to the next stage",
);

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
  "AWS_REGION", "HF_HOME", "HF_HUB_OFFLINE", "KNOWLEDGE_ALLOW_TEST_FAILURE", "KNOWLEDGE_AUTHORING_ROLE_ARN", "KNOWLEDGE_BEATS_CONFIG",
  "KNOWLEDGE_CONCEPT_KINDS", "KNOWLEDGE_LEDGER_TABLE", "KNOWLEDGE_OPENAI_KEY_PARAMETER", "KNOWLEDGE_PUBLICATION", "KNOWLEDGE_SITE_BRANCH",
  "KNOWLEDGE_SITE_REPO", "KNOWLEDGE_STATE_BUCKET", "KNOWLEDGE_STATIC_SUBDIR", "PAPYRUS_EDGE_DISTRIBUTION_ID", "PAPYRUS_PROJECTION_LOCK_TABLE",
  "PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS", "PAPYRUS_PUBLICATION_KIND", "PAPYRUS_REDIRECTS_KVS_ARN", "PAPYRUS_SITE_BUCKET",
].sort());
assert.equal(staticEnvironment.PAPYRUS_PROJECTION_LOCK_TABLE, PROJECTION_LOCK_TABLE_NAME);
assert.equal(staticEnvironment.PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS, "1800");
assert.equal(staticEnvironment.KNOWLEDGE_CONCEPT_KINDS, "task,technique,concept,model_family");
assert.equal(staticEnvironment.KNOWLEDGE_AUTHORING_ROLE_ARN, "arn:aws:iam::712236451410:role/shipped-papyrus-authoring");
assert.equal(staticEnvironment.PAPYRUS_PUBLICATION_KIND, "s3-projection");

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
template.hasResourceProperties("AWS::CloudWatch::Alarm", {
  MetricName: "ExecutionsSucceeded",
  Namespace: "AWS/States",
  Statistic: "Sum",
  Period: 86400,
  EvaluationPeriods: 8,
  DatapointsToAlarm: 8,
  Threshold: 1,
  ComparisonOperator: "LessThanThreshold",
  TreatMissingData: "breaching",
  AlarmActions: [{ Ref: Match.stringLikeRegexp("^JobAlarmTopic") }],
});

// Schedule and its role.
template.hasResourceProperties("AWS::Scheduler::Schedule", {
  ScheduleExpression: "cron(0 5 ? * MON *)",
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
  "ssm:GetParameter", "sts:AssumeRole", "cloudfront:CreateInvalidation", "cloudfront:DescribeKeyValueStore",
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
assert.deepEqual(statementBySid("AssumeAuthoringRole").Resource, "arn:aws:iam::712236451410:role/shipped-papyrus-authoring");
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
    authoringRoleArn: "arn:aws:iam::712236451410:role/custom-role",
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
rejects((block) => { block.environment = { "1BAD": "x" }; }, /knowledgeRun\.environment\.1BAD is not a valid environment variable name/);
rejects((block) => { block.openAiKeyParameter = "no-slash"; }, /knowledgeRun\.openAiKeyParameter is invalid/);
assert.throws(() => resolveKnowledgeRunConfig(parseSiteConfig((() => { const raw = readExample(); delete raw.knowledgeRun; return raw; })())), /has no knowledgeRun block/);
assert.throws(() => resolveKnowledgeRunConfig(parseSiteConfig((() => { const raw = readExample(); delete raw.aws; return raw; })())), /needs aws\.accountId and aws\.region/);

console.log("scheduled job synth: ok");
