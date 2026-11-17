import { NestedStack, type Stack } from "aws-cdk-lib";
import { CfnResource } from "aws-cdk-lib";
import { Construct } from "constructs";

/**
 * Every always-on agent resource of a site (the wake queue and its dead-letter queue, the schedule group, the
 * reconciler, the change feeds, their alarms) lives in ONE nested stack named `agents`.
 *
 * Why one stack: a brand-new site's first deploy may create at most 2,500 resources in one CloudFormation operation,
 * nested stacks included, and the first stage is held under 2,000 (`scripts/test-bootstrap-stage.ts`). The agent
 * resources are not models, so they cannot join an optional model group; instead the whole stack is left out of the
 * bootstrap stage (`PAPYRUS_BOOTSTRAP_STAGE=1`) exactly as `reproject-on-deploy` is, and the second deploy adds it as an
 * ordinary update. Existing sites are not under the first-deploy limit.
 *
 * Each piece is a named unit with its own construct, so `scripts/test-agents-stack.ts` can price it before it merges.
 * The stack exists only when there is at least one piece: CloudFormation does not accept an empty stack, and a
 * placeholder resource would cost a resource for nothing.
 */
export type AgentPiece = {
  /** Stable construct id; also the name in the per-piece count (for example `wake-queue`). */
  id: string;
  /** Adds this piece's resources under `scope`, a construct of the `agents` stack. */
  add(scope: Construct): void;
};

export const AGENTS_STACK_NAME = "agents";

/** The `agents` stack is created whenever the stage is not the bootstrap stage and at least one piece exists. */
export function shouldCreateAgentsStack(pieces: readonly AgentPiece[], bootstrapStage: boolean): boolean {
  return !bootstrapStage && pieces.length > 0;
}

/**
 * Creates the `agents` stack with `createStack` (the Amplify backend's `createStack`) and adds every piece under its
 * own construct. Returns the stack, or undefined when the stage defers it or there is nothing to add.
 */
export function addAgentsStack(
  createStack: (name: string) => Stack,
  pieces: readonly AgentPiece[],
  bootstrapStage: boolean,
): Stack | undefined {
  const ids = pieces.map((piece) => piece.id);
  if (new Set(ids).size !== ids.length) throw new Error(`Agent pieces must have distinct ids; got ${ids.join(", ")}`);
  if (!shouldCreateAgentsStack(pieces, bootstrapStage)) return undefined;
  const stack = createStack(AGENTS_STACK_NAME);
  for (const piece of pieces) piece.add(new Construct(stack, piece.id));
  return stack;
}

/** The CloudFormation resources a construct adds to its stack (nested stacks count separately and are not included). */
export function countPieceResources(piece: Construct): number {
  return piece.node.findAll().filter((node) => node instanceof CfnResource && !(node instanceof NestedStack)).length;
}
