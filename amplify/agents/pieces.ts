import type { AgentPiece } from "./stack";

/**
 * The agent pieces a site's `agents` stack holds. Each slice of docs/design/always-on-agents-architecture.md adds its
 * piece here (the wake queue, the schedule group and reconciler, the change feeds, the alarms) and nothing else:
 * `scripts/test-agents-stack.ts` prints what each costs against the first-deploy budget. No piece exists yet, so
 * no `agents` stack is created yet.
 */
export const AGENT_PIECES: readonly AgentPiece[] = [];
