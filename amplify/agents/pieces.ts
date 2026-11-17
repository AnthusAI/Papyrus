import type { AgentPiece } from "./stack";
import { wakeQueuePiece } from "./wake-queue";

/**
 * The agent pieces a site's `agents` stack holds. Each slice of docs/design/always-on-agents-architecture.md adds its
 * piece here (the wake queue, the schedule group and reconciler, the change feeds, the alarms) and nothing else:
 * `scripts/test-agents-stack.ts` prints what each costs against the first-deploy budget. The pieces are named after the
 * site, so they are built for one site's brand id.
 */
export function agentPieces(brandId: string): readonly AgentPiece[] {
  return [wakeQueuePiece(brandId)];
}
