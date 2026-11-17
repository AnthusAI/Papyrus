/**
 * Every always-on agent resource lives in one nested `agents` stack that a new site's first deploy leaves out
 * (amplify/agents/stack.ts). This checks the rule with a fixture piece (so it holds before any real piece lands) and
 * prints what each real piece costs, so the cost of every later slice is known before it merges.
 */
import assert from "node:assert/strict";
import { App, CfnResource, Stack } from "aws-cdk-lib";
import { CfnQueue } from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import { AGENT_PIECES } from "../amplify/agents/pieces";
import { AGENTS_STACK_NAME, addAgentsStack, countPieceResources, type AgentPiece } from "../amplify/agents/stack";
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
const prices = AGENT_PIECES.map((piece) => {
  const scratch = new Stack(new App(), "scratch");
  const construct = new Construct(scratch, piece.id);
  piece.add(construct);
  return { id: piece.id, resources: countPieceResources(construct) };
});
const total = prices.reduce((sum, price) => sum + price.resources, 0);
console.log(`agent pieces: ${prices.length === 0 ? "none yet" : prices.map((price) => `${price.id} ${price.resources}`).join(", ")}`);
console.log(`agents stack total: ${total} resources (deferred: not in the first deploy)`);

const { resources: firstStage, templates } = measureBootstrapStage();
assert.ok(!templates.some((name) => name.toLowerCase().includes(AGENTS_STACK_NAME)), "the first stage must not include the agents stack");
console.log(`first-deploy headroom: ${BOOTSTRAP_BUDGET - firstStage} of ${BOOTSTRAP_BUDGET} resources (first stage ${firstStage}); the agent resources do not use it`);
console.log("agents stack tests passed");
