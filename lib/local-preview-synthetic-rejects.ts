import type { RelevanceDecisionView } from "./relevance-decisions";

/** Strong Reject confidences, strongest first, for the preview's made-up predictions. */
const SYNTHETIC_REJECT_CONFIDENCE = [0.95, 0.91, 0.87, 0.83, 0.79, 0.75, 0.71, 0.67];

/**
 * Local preview only. A young corpus can have no Reject predictions at all, so the Reject end of the feed cannot be reviewed on real
 * data. `?feedSynthRejects=N` turns the N weakest Accept predictions of pending items into made-up Rejects, and the page says so
 * in a banner. Never reachable outside local preview.
 */
export function chooseSyntheticRejects(
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined,
  pendingLineageIds: ReadonlySet<string>,
  count: number,
): string[] {
  return [...(decisions ?? new Map()).entries()]
    .filter(([lineageId, decision]) => pendingLineageIds.has(lineageId) && decision.label === (decision.positiveLabel ?? "include"))
    .sort((left, right) => (left[1].confidence ?? 0) - (right[1].confidence ?? 0))
    .slice(0, Math.max(0, Math.min(count, SYNTHETIC_REJECT_CONFIDENCE.length)))
    .map(([lineageId]) => lineageId);
}

/** Applies the chosen ids, weakest first getting the lowest of the made-up confidences. The choice is made once, so rating a card never moves it. */
export function withSyntheticRejects(
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined,
  chosen: readonly string[],
): { decisions: Map<string, RelevanceDecisionView>; changed: number } {
  const result = new Map(decisions ?? []);
  let changed = 0;
  chosen.forEach((lineageId, index) => {
    const decision = result.get(lineageId);
    if (!decision) return;
    result.set(lineageId, {
      ...decision,
      label: decision.classes.find((label) => label !== (decision.positiveLabel ?? "include")) ?? "exclude",
      confidence: SYNTHETIC_REJECT_CONFIDENCE[index],
    });
    changed += 1;
  });
  return { decisions: result, changed };
}
