/**
 * Every always-on agent resource lives in one nested `agents` stack that a new site's first deploy leaves out
 * (amplify/agents/stack.ts). This checks the rule with a fixture piece (so it holds before any real piece lands) and
 * prints what each real piece costs, so the cost of every later slice is known before it merges.
 */
import assert from "node:assert/strict";
import { App, CfnResource, Stack } from "aws-cdk-lib";
import { CfnQueue } from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Template } from "aws-cdk-lib/assertions";
import { agentPieces } from "../amplify/agents/pieces";
import { AGENTS_STACK_NAME, addAgentsStack, countPieceResources, type AgentPiece } from "../amplify/agents/stack";
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
const pieces = agentPieces(SAMPLE_BRAND);
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

const { resources: firstStage, templates } = measureBootstrapStage();
assert.ok(!templates.some((name) => name.toLowerCase().includes(AGENTS_STACK_NAME)), "the first stage must not include the agents stack");
// The second deploy (the whole backend, no bootstrap variable) holds the agents stack with every piece, as the real backend builds it.
const later = measureBootstrapStage(false);
const agentTemplates = later.templates.filter((name) => name.toLowerCase().includes(AGENTS_STACK_NAME));
assert.equal(agentTemplates.length, 1, `the second deploy has exactly one agents stack; found ${agentTemplates.join(", ") || "none"}`);
assert.equal(later.resourcesByTemplate[agentTemplates[0]], total, "the agents stack holds exactly the pieces' resources and nothing else");
console.log(`second deploy: agents stack ${later.resourcesByTemplate[agentTemplates[0]]} resources of ${later.resources} in all (an ordinary update; the 2,500 limit is for a first deploy)`);
console.log(`first-deploy headroom: ${BOOTSTRAP_BUDGET - firstStage} of ${BOOTSTRAP_BUDGET} resources (first stage ${firstStage}); the agent resources do not use it`);
console.log("agents stack tests passed");
