import { itemChangeFeedPiece, type ItemChangeFeedSource } from "./item-change-feed";
import type { AgentPiece } from "./stack";
import { scheduleGroupPiece } from "./schedule-group";
import { wakeQueuePiece } from "./wake-queue";

/** What a site's backend gives the pieces that read its own resources. A piece whose source is absent is not added (a shared stack acts for no one tenant). */
export type AgentPieceSources = { itemChangeFeed?: ItemChangeFeedSource };

/**
 * The agent pieces a site's `agents` stack holds. Each slice of docs/design/always-on-agents-architecture.md adds its
 * piece here (the wake queue, the schedule group and reconciler, the change feeds, the alarms) and nothing else:
 * `scripts/test-agents-stack.ts` prints what each costs against the first-deploy budget. The pieces are named after the
 * site, so they are built for one site's brand id.
 */
export function agentPieces(brandId: string, sources: AgentPieceSources = {}): readonly AgentPiece[] {
  return [wakeQueuePiece(brandId), scheduleGroupPiece(brandId), ...(sources.itemChangeFeed ? [itemChangeFeedPiece(brandId, sources.itemChangeFeed)] : [])];
}
