/**
 * Every always-on agent resource lives in one nested `agents` stack that a new site's first deploy leaves out
 * (amplify/agents/stack.ts). This checks the rule with a fixture piece (so it holds before any real piece lands) and
 * prints what each real piece costs, so the cost of every later slice is known before it merges.
 */
import assert from "node:assert/strict";
import { App, CfnResource, Stack } from "aws-cdk-lib";
import { PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { CfnQueue } from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Template } from "aws-cdk-lib/assertions";
import { agentPieces } from "../amplify/agents/pieces";
import { ITEM_FEED_API_FIELDS, ITEM_STREAM_VIEW, type ItemChangeFeedSource } from "../amplify/agents/item-change-feed";
import { AGENTS_STACK_NAME, addAgentsStack, countPieceResources, type AgentPiece } from "../amplify/agents/stack";
import { FOLLOW_UP_ENTRY_PREFIX, SCHEDULE_GROUP_NAME_SUFFIX, SCHEDULER_ROLE_NAME_SUFFIX, allowFollowUpTimers, scheduleNames } from "../amplify/agents/schedule-group";
import {
  RUNNER_RECORDING_MARGIN_SECONDS,
  RUNNER_TIMEOUT_SECONDS,
  WAKE_DEAD_LETTER_QUEUE_NAME_SUFFIX,
  WAKE_MAXIMUM_RECEIVES,
  WAKE_QUEUE_NAME_PATTERN,
  WAKE_VISIBILITY_TIMEOUT_SECONDS,
  wakeQueueNames,
} from "../amplify/agents/wake-queue";
import { BOOTSTRAP_BUDGET, measureBootstrapStage } from "./bootstrap-stage-measure";

function stackFactory(): { createStack: (name: string) => Stack; created: Stack[] } {
  const app = new App();
  const created: Stack[] = [];
  return {
    created,
    createStack: (name) => {
      const stack = new Stack(app, name);
      created.push(stack);
      return stack;
    },
  };
}

/** A stand-in for a queue, its dead-letter queue and a third resource: three resources. */
const fixturePiece: AgentPiece = {
  id: "fixture",
  add(scope: Construct) {
    new CfnQueue(scope, "Queue");
    new CfnQueue(scope, "DeadLetters");
    new CfnQueue(scope, "Other");
  },
};

function resourceCount(stack: Stack): number {
  return stack.node.findAll().filter((node) => node instanceof CfnResource).length;
}

// The second deploy (no bootstrap variable) adds one stack named agents, holding each piece under its own construct.
const second = stackFactory();
const stack = addAgentsStack(second.createStack, [fixturePiece], false);
assert.ok(stack, "the agents stack exists outside the bootstrap stage when a piece exists");
assert.equal(stack.node.id, AGENTS_STACK_NAME);
assert.equal(second.created.length, 1, "one stack, not one per piece");
const fixtureConstruct = stack.node.findChild("fixture") as Construct;
assert.equal(countPieceResources(fixtureConstruct), 3);
assert.equal(resourceCount(stack), 3);
console.log(`fixture piece: ${countPieceResources(fixtureConstruct)} resources`);

// The first deploy (PAPYRUS_BOOTSTRAP_STAGE=1) creates nothing: no stack, and no piece runs.
const first = stackFactory();
let ran = false;
const probe: AgentPiece = { id: "probe", add: () => { ran = true; } };
assert.equal(addAgentsStack(first.createStack, [fixturePiece, probe], true), undefined);
assert.equal(first.created.length, 0, "the bootstrap stage creates no agents stack");
assert.equal(ran, false, "the bootstrap stage adds no agent resource anywhere");

// CloudFormation accepts no empty stack, so with no pieces there is no stack at all.
const none = stackFactory();
assert.equal(addAgentsStack(none.createStack, [], false), undefined);
assert.equal(none.created.length, 0);

// Two pieces may not share an id: the per-piece count would be wrong.
assert.throws(() => addAgentsStack(stackFactory().createStack, [fixturePiece, fixturePiece], false), /distinct ids/);

// The real pieces, each priced in a scratch stack.
const SAMPLE_BRAND = "sample-site";
const feedSource: ItemChangeFeedSource = {
  streamArn: "arn:aws:dynamodb:us-east-1:123456789012:table/Item-sample/stream/2026-01-01T00:00:00.000",
  graphqlUrl: "https://example123456789012345678.appsync-api.us-east-1.amazonaws.com/graphql",
  apiId: "exampleapiid",
  tenantId: "sample-tenant",
  bucketName: "sample-bucket",
  bucketArn: "arn:aws:s3:::sample-bucket",
};
const pieces = agentPieces(SAMPLE_BRAND, { itemChangeFeed: feedSource });
assert.deepEqual(agentPieces(SAMPLE_BRAND).map((piece) => piece.id), ["wake-queue", "schedule-group"], "a backend that gives no Item stream (shared, or the bootstrap stage) has no feed piece");
const prices = pieces.map((piece) => {
  const scratch = new Stack(new App(), "scratch");
  const construct = new Construct(scratch, piece.id);
  piece.add(construct);
  return { id: piece.id, resources: countPieceResources(construct) };
});
const total = prices.reduce((sum, price) => sum + price.resources, 0);
console.log(`agent pieces: ${prices.map((price) => `${price.id} ${price.resources}`).join(", ")}`);
console.log(`agents stack total: ${total} resources (deferred: not in the first deploy)`);

// The wake queue piece: what it creates, and the numbers it takes from the runner.
const wakeScratch = new Stack(new App(), "wake-scratch");
const wakePiece = pieces.find((piece) => piece.id === "wake-queue");
assert.ok(wakePiece, "the wake queue is an agent piece");
wakePiece.add(new Construct(wakeScratch, wakePiece.id));
const wakeTemplate = Template.fromStack(wakeScratch);
const names = wakeQueueNames(SAMPLE_BRAND);
assert.deepEqual(names, { queue: "papyrus-sample-site-agent-wakes.fifo", deadLetterQueue: "papyrus-sample-site-agent-wakes-dead-letters.fifo" });
wakeTemplate.resourceCountIs("AWS::SQS::Queue", 2);
wakeTemplate.resourceCountIs("AWS::Lambda::EventSourceMapping", 1);
wakeTemplate.resourceCountIs("AWS::CloudWatch::Alarm", 1);
wakeTemplate.hasResourceProperties("AWS::SQS::Queue", {
  QueueName: names.queue,
  FifoQueue: true,
  ContentBasedDeduplication: true,
  VisibilityTimeout: WAKE_VISIBILITY_TIMEOUT_SECONDS,
  MessageRetentionPeriod: 14 * 24 * 60 * 60,
  RedrivePolicy: { maxReceiveCount: WAKE_MAXIMUM_RECEIVES },
});
wakeTemplate.hasResourceProperties("AWS::SQS::Queue", { QueueName: names.deadLetterQueue, FifoQueue: true });
wakeTemplate.hasResourceProperties("AWS::Lambda::EventSourceMapping", { FunctionName: "papyrus-procedure-runner", BatchSize: 1, Enabled: true });
assert.equal(
  Object.values(wakeTemplate.findResources("AWS::Lambda::EventSourceMapping"))[0].Properties.ScalingConfig,
  undefined,
  "no maximum concurrency is invented here; it is the model provider's limit (slice B4)",
);
wakeTemplate.hasResourceProperties("AWS::CloudWatch::Alarm", { Threshold: 1, ComparisonOperator: "GreaterThanOrEqualToThreshold", Namespace: "AWS/SQS" });
assert.deepEqual(Object.keys(wakeTemplate.findResources("AWS::IAM::Role")), [], "the piece creates no role and no permission");
assert.deepEqual(Object.keys(wakeTemplate.findResources("AWS::IAM::Policy")), [], "the piece creates no IAM policy");
assert.equal(WAKE_VISIBILITY_TIMEOUT_SECONDS, RUNNER_TIMEOUT_SECONDS + RUNNER_RECORDING_MARGIN_SECONDS);

// The queue's numbers are the runner's own, read from where the runner states them.
const root = path.resolve(import.meta.dirname, "..");
const runnerTemplate = readFileSync(path.join(root, "infra/procedures/papyrus-procedure-runner.yaml"), "utf8");
assert.equal(Number(/^ {6}Timeout: (\d+)$/m.exec(runnerTemplate)?.[1]), RUNNER_TIMEOUT_SECONDS, "RUNNER_TIMEOUT_SECONDS is the runner template's Timeout");
const runnerSource = readFileSync(path.join(root, "src/papyrus_content/procedure_runner.py"), "utf8");
assert.equal(Number(/^SECONDS_KEPT_FOR_RECORDING = (\d+)/m.exec(runnerSource)?.[1]), RUNNER_RECORDING_MARGIN_SECONDS, "RUNNER_RECORDING_MARGIN_SECONDS is the runner's recording margin");
assert.equal(Number(/^MAX_TIMEOUT_SECONDS = (\d+)/m.exec(runnerSource)?.[1]) + RUNNER_RECORDING_MARGIN_SECONDS, RUNNER_TIMEOUT_SECONDS, "the runner's longest procedure plus its recording margin is the Lambda's limit");

// The runner's role reads every site's wake queue by the name pattern, one statement, and cannot read a dead-letter queue.
const statement = /- Sid: ReadWakeQueues\n([\s\S]*?)\n {14}- Sid: /.exec(runnerTemplate)?.[1] ?? "";
assert.match(statement, /Action: \[sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes\]/);
assert.ok(statement.includes(`:${WAKE_QUEUE_NAME_PATTERN}"`), "the runner's statement names the queue pattern the stack uses");
const patternMatches = (name: string) => new RegExp(`^${WAKE_QUEUE_NAME_PATTERN.replace(/[.]/g, "\\.").replace(/\*/g, "[a-z0-9-]*")}$`).test(name);
assert.ok(patternMatches(names.queue), "a site's wake queue matches the pattern");
assert.ok(!patternMatches(names.deadLetterQueue), "a site's dead-letter queue does not match the pattern");
assert.ok(names.deadLetterQueue.endsWith(WAKE_DEAD_LETTER_QUEUE_NAME_SUFFIX));
// The same names the Python senders build (src/papyrus_content/agent_wakes_test.py asserts these three).
assert.equal(wakeQueueNames("Machines.On Machines").queue, "papyrus-machines-on-machines-agent-wakes.fifo");
assert.equal(wakeQueueNames("x".repeat(80)).queue, `papyrus-${"x".repeat(40)}-agent-wakes.fifo`);
assert.ok(wakeQueueNames("x".repeat(80)).deadLetterQueue.length <= 80, "the longest queue name fits the FIFO limit of 80 characters");
assert.throws(() => wakeQueueNames("---"), /brand id/);

// The schedule group piece (slice C1): the group, the role the scheduler assumes and the alarm on a dropped tick. Nothing else, and no entry: the deploy step makes those.
const scheduleScratch = new Stack(new App(), "schedule-scratch", { env: { account: "123456789012", region: "us-east-1" } });
const schedulePiece = pieces.find((piece) => piece.id === "schedule-group");
assert.ok(schedulePiece, "the schedule group is an agent piece");
schedulePiece.add(new Construct(scheduleScratch, schedulePiece.id));
const scheduleTemplate = Template.fromStack(scheduleScratch);
const scheduleSiteNames = scheduleNames(SAMPLE_BRAND);
assert.deepEqual(scheduleSiteNames, { group: "papyrus-sample-site-agent-schedules", role: "papyrus-sample-site-agent-scheduler" });
scheduleTemplate.resourceCountIs("AWS::Scheduler::ScheduleGroup", 1);
scheduleTemplate.resourceCountIs("AWS::Scheduler::Schedule", 0);
scheduleTemplate.resourceCountIs("AWS::IAM::Role", 1);
scheduleTemplate.resourceCountIs("AWS::IAM::Policy", 0);
scheduleTemplate.resourceCountIs("AWS::CloudWatch::Alarm", 1);
scheduleTemplate.hasResourceProperties("AWS::Scheduler::ScheduleGroup", { Name: scheduleSiteNames.group });
scheduleTemplate.hasResourceProperties("AWS::IAM::Role", {
  RoleName: scheduleSiteNames.role,
  AssumeRolePolicyDocument: {
    Statement: [{ Action: "sts:AssumeRole", Effect: "Allow", Principal: { Service: "scheduler.amazonaws.com" }, Condition: { StringEquals: { "aws:SourceAccount": "123456789012" } } }],
  },
});
// The role's one permission: send to this site's wake queue. Read the policy back from the template, so the test names every statement the role has.
const schedulerRole = Object.values(scheduleTemplate.findResources("AWS::IAM::Role"))[0];
const inlinePolicies = schedulerRole.Properties.Policies as { PolicyName: string; PolicyDocument: { Statement: unknown[] } }[];
assert.equal(inlinePolicies.length, 1, "the scheduler role has exactly one inline policy");
assert.deepEqual(inlinePolicies[0].PolicyDocument.Statement, [
  { Action: "sqs:SendMessage", Effect: "Allow", Resource: { "Fn::Join": ["", ["arn:", { Ref: "AWS::Partition" }, `:sqs:us-east-1:123456789012:${names.queue}`]] } },
]);
assert.equal(schedulerRole.Properties.ManagedPolicyArns, undefined, "no managed policy is attached to the scheduler role");
scheduleTemplate.hasResourceProperties("AWS::CloudWatch::Alarm", { Namespace: "AWS/Scheduler", MetricName: "InvocationDroppedCount", Threshold: 1, Dimensions: [{ Name: "ScheduleGroup", Value: scheduleSiteNames.group }] });
// The names the Python reconciler builds (src/papyrus_content/agent_definitions/schedules.py) and these are the same text.
const schedulesSource = readFileSync(path.join(root, "src/papyrus_content/agent_definitions/schedules.py"), "utf8");
assert.ok(schedulesSource.includes(`GROUP_PREFIX, GROUP_SUFFIX = "papyrus-", "${SCHEDULE_GROUP_NAME_SUFFIX}"`), "the reconciler names the group as the stack does");
assert.ok(schedulesSource.includes(`ROLE_SUFFIX = "${SCHEDULER_ROLE_NAME_SUFFIX}"`), "the reconciler names the role as the stack does");
assert.equal(scheduleNames("Machines.On Machines").group, "papyrus-machines-on-machines-agent-schedules");
assert.ok(scheduleNames("x".repeat(80)).group.length <= 64 && scheduleNames("x".repeat(80)).role.length <= 64, "the longest group and role names fit the 64-character limit");
assert.throws(() => scheduleNames("---"), /brand id/);


// The Item change feed piece (slice B2): the function, its role and policy and the stream mapping. No queue, no alarm, no table.
const feedScratch = new Stack(new App(), "feed-scratch", { env: { account: "123456789012", region: "us-east-1" } });
const feedPiece = pieces.find((piece) => piece.id === "item-change-feed");
assert.ok(feedPiece, "the Item change feed is an agent piece");
const feedConstruct = new Construct(feedScratch, feedPiece.id);
feedPiece.add(feedConstruct);
assert.equal(countPieceResources(feedConstruct), 4, "the feed is a function, its role and policy, and one stream mapping");
console.log(`item change feed piece: ${countPieceResources(feedConstruct)} resources (function, role, policy, stream mapping)`);
const feedTemplate = Template.fromStack(feedScratch);
feedTemplate.resourceCountIs("AWS::Lambda::Function", 1);
feedTemplate.resourceCountIs("AWS::Lambda::EventSourceMapping", 1);
feedTemplate.resourceCountIs("AWS::SQS::Queue", 0);
feedTemplate.resourceCountIs("AWS::CloudWatch::Alarm", 0);
feedTemplate.resourceCountIs("AWS::DynamoDB::Table", 0);
feedTemplate.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
  EventSourceArn: feedSource.streamArn,
  StartingPosition: "LATEST",
  FunctionResponseTypes: ["ReportBatchItemFailures"],
  FilterCriteria: { Filters: [{ Pattern: JSON.stringify({ eventName: ["INSERT", "MODIFY"] }) }] },
});
feedTemplate.hasResourceProperties("AWS::Lambda::Function", {
  Environment: { Variables: { PAPYRUS_AGENT_PUBLICATION_ID: SAMPLE_BRAND, PAPYRUS_TENANT_ID: "sample-tenant", PAPYRUS_SITE_BUCKET: "sample-bucket", PAPYRUS_GRAPHQL_AUTH: "iam", PAPYRUS_GRAPHQL_ENDPOINT: feedSource.graphqlUrl } },
});
assert.equal(ITEM_STREAM_VIEW, "NEW_AND_OLD_IMAGES", "the feed compares the old and new image to tell a board move from any other update");
const feedPolicy = JSON.stringify(Object.values(feedTemplate.findResources("AWS::IAM::Policy")));
for (const field of ITEM_FEED_API_FIELDS) assert.ok(feedPolicy.includes(`types/${field}`), `it may call ${field}`);
assert.ok(feedPolicy.includes("sample-bucket/tenants/sample-tenant/site/listeners/*"), "it reads the listener index's objects of its own tenant and nothing else in the bucket");
assert.ok(feedPolicy.includes(names.queue) && feedPolicy.includes("sqs:SendMessage") && feedPolicy.includes("sqs:GetQueueUrl"), "it puts wakes on its own site's queue");
for (const forbidden of ["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem", "dynamodb:PutItem", "sqs:ReceiveMessage", "sqs:DeleteMessage", "lambda:Invoke", "Mutation/fields", "Query/fields/list", "Query/fields/*", "s3:PutObject", "s3:ListBucket"]) {
  assert.ok(!feedPolicy.includes(forbidden), `the feed must not hold ${forbidden}`);
}
// The names the Python feed reads are the ones the piece sets.
const feedSourceText = readFileSync(path.join(root, "src/papyrus_content/item_change_feed.py"), "utf8");
for (const variable of ["PAPYRUS_AGENT_PUBLICATION_ID", "PAPYRUS_TENANT_ID", "PAPYRUS_SITE_BUCKET", "PAPYRUS_GRAPHQL_ENDPOINT"]) assert.ok(feedSourceText.includes(`"${variable}"`), `the feed reads ${variable}`);
assert.ok(readFileSync(path.join(root, "src/papyrus_content/agent_listeners.py"), "utf8").includes('KIND = "listeners"'), "the index kind the policy reads (tenants/<tenant>/site/listeners/) is the kind the deploy writes");

// The follow-up timers' permission (slice C2): a function that sets due times may create, update and delete `follow-up-*` entries in this site's group, and pass the
// scheduler role to the scheduler service. It adds no resource (two statements on the function's own role) and never reaches the reconciler's `agent-*` entries,
// another site's group or the default group (scheduled publishing's).
assert.equal(FOLLOW_UP_ENTRY_PREFIX, "follow-up-");
assert.ok(schedulesSource.includes("ENTRY_PREFIX = \"agent-\""), "the reconciler's entries are agent-*");
assert.ok(readFileSync(path.join(root, "src/papyrus_content/follow_up_timers.py"), "utf8").includes(`ENTRY_PREFIX = "${FOLLOW_UP_ENTRY_PREFIX}"`), "the Python helper names its entries as the policy says");
const followUpStack = new Stack(new App(), "follow-up-scratch", { env: { account: "123456789012", region: "us-east-1" } });
const followUpFunction = new LambdaFunction(followUpStack, "Setter", { runtime: Runtime.NODEJS_20_X, handler: "index.handler", code: Code.fromInline("exports.handler = async () => {}") });
// A site function already has its default policy (it logs, it reads its table); the scratch one gets one statement so the count shows only what the permission adds.
followUpFunction.addToRolePolicy(new PolicyStatement({ actions: ["logs:PutLogEvents"], resources: ["*"] }));
const resourcesBefore = resourceCount(followUpStack);
allowFollowUpTimers(followUpFunction, SAMPLE_BRAND);
assert.equal(resourceCount(followUpStack), resourcesBefore, "the permission adds no resource");
const followUpTemplate = Template.fromStack(followUpStack);
const followUpStatements = (Object.values(followUpTemplate.findResources("AWS::IAM::Policy"))[0].Properties.PolicyDocument.Statement as { Action: string | string[]; Resource: unknown; Condition?: unknown }[]);
const manageEntries = followUpStatements.find((statement) => [statement.Action].flat().includes("scheduler:CreateSchedule"));
assert.deepEqual([manageEntries!.Action].flat().sort(), ["scheduler:CreateSchedule", "scheduler:DeleteSchedule", "scheduler:UpdateSchedule"]);
assert.deepEqual(manageEntries!.Resource, { "Fn::Join": ["", ["arn:", { Ref: "AWS::Partition" }, `:scheduler:us-east-1:123456789012:schedule/${scheduleSiteNames.group}/follow-up-*`]] });
const passRole = followUpStatements.find((statement) => [statement.Action].flat().includes("iam:PassRole"));
assert.deepEqual(passRole!.Resource, { "Fn::Join": ["", ["arn:", { Ref: "AWS::Partition" }, `:iam::123456789012:role/${scheduleSiteNames.role}`]] });
assert.deepEqual(passRole!.Condition, { StringEquals: { "iam:PassedToService": "scheduler.amazonaws.com" } });
assert.ok(!followUpStatements.some((statement) => JSON.stringify(statement).includes("scheduler:Get") || JSON.stringify(statement).includes("scheduler:List")), "the function reads no entry");
console.log("follow-up timers permission: 2 statements, 0 resources");


// The first stage is measured with a tenant id set (the feed's source), so it proves the feed and the Item stream are left out when they could be there.
const { resources: firstStage, templates } = measureBootstrapStage(true, { PAPYRUS_TENANT_ID: "sample-tenant" });
assert.ok(!templates.some((name) => name.toLowerCase().includes(AGENTS_STACK_NAME)), "the first stage must not include the agents stack");
assert.ok(!templates.some((name) => name.toLowerCase().includes("item-change-feed")), "the first stage must not include the Item change feed");
// The second deploy (the whole backend, no bootstrap variable) holds the agents stack with every piece, as the real backend builds it.
// A site with a tenant id (the feed's source) as the real backend builds it: the Item stream is on and the feed is in the stack.
const later = measureBootstrapStage(false, { PAPYRUS_TENANT_ID: "sample-tenant" });
const agentTemplates = later.templates.filter((name) => name.toLowerCase().includes(AGENTS_STACK_NAME));
assert.equal(agentTemplates.length, 1, `the second deploy has exactly one agents stack; found ${agentTemplates.join(", ") || "none"}`);
assert.equal(later.resourcesByTemplate[agentTemplates[0]], total, "the agents stack holds exactly the pieces' resources and nothing else");
console.log(`second deploy: agents stack ${later.resourcesByTemplate[agentTemplates[0]]} resources of ${later.resources} in all (an ordinary update; the 2,500 limit is for a first deploy)`);
console.log(`first-deploy headroom: ${BOOTSTRAP_BUDGET - firstStage} of ${BOOTSTRAP_BUDGET} resources (first stage ${firstStage}); the agent resources do not use it`);
console.log("agents stack tests passed");
