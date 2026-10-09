import type { SemanticRelationRecord } from "./category-repository";

export const RELEVANCE_RELATION = "relevance_decision_is";

/** The relevance cyclotron's current decision about one reference, as the References tab shows it. */
export type RelevanceDecisionView = {
  decisionRelationId: string;
  decisionId: string;
  label: string;
  confidence: number | null;
  version: number | null;
  /** True when the cyclotron sent this decision to review. */
  reviewRecommended: boolean;
  reviewReason: "program" | "audit" | null;
  reviewDetail: string | null;
  classes: string[];
};

function parseMetadata(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Current decisions keyed by reference lineage, from relations the Newsroom
 * already loads: no extra request per row.
 */
export function currentRelevanceDecisions(relations: SemanticRelationRecord[]): Map<string, RelevanceDecisionView> {
  const decisions = new Map<string, RelevanceDecisionView>();
  for (const relation of relations) {
    if (relation.predicate !== RELEVANCE_RELATION || relation.relationState !== "current") continue;
    const metadata = parseMetadata(relation.metadata);
    const probabilities = parseMetadata(metadata.probabilities);
    const reason = metadata.reviewReason === "program" || metadata.reviewReason === "audit" ? metadata.reviewReason : null;
    const version = Number(relation.modelVersion ?? metadata.version);
    decisions.set(relation.subjectLineageId, {
      decisionRelationId: relation.id,
      decisionId: String(metadata.decisionId ?? ""),
      label: String(metadata.label ?? ""),
      confidence: typeof relation.confidence === "number" ? relation.confidence : null,
      version: Number.isFinite(version) ? version : null,
      reviewRecommended: Boolean(relation.reviewRecommended),
      reviewReason: reason,
      reviewDetail: typeof metadata.reviewDetail === "string" ? metadata.reviewDetail : null,
      classes: Object.keys(probabilities),
    });
  }
  return decisions;
}
