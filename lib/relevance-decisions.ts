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
  positiveLabel: string | null;
  question: string | null;
  /** Thumbs for a two-class decision with a positive label; per-class buttons otherwise. */
  reviewControl: "thumbs" | "labels";
  cyclotronId: string | null;
};

/** What an editor submits from the review control. */
export type RelevanceReview = {
  label: string | null;
  reasonCode: string | null;
  explanation: string | null;
  shareable: boolean;
};

/** The existing curation action an editor's review becomes. */
export type RelevanceCuration = {
  action: "accept" | "reject";
  reasonCode: string | null;
  note: string | null;
  decisionRelationId: string;
  shareable: boolean;
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
      classes: Array.isArray(metadata.labels) && metadata.labels.length
        ? metadata.labels.map(String)
        : Object.keys(probabilities),
      positiveLabel: typeof metadata.positiveLabel === "string" ? metadata.positiveLabel : null,
      question: typeof metadata.question === "string" ? metadata.question : null,
      reviewControl: metadata.reviewControl === "thumbs" ? "thumbs" : "labels",
      cyclotronId: typeof metadata.cyclotronId === "string" ? metadata.cyclotronId : null,
    });
  }
  return decisions;
}

/**
 * Map a review to the existing curation mutation. The positive label accepts;
 * any other label, or a review without a label, rejects with the reason code,
 * which the existing scope-training rule turns back into a cyclotron label
 * (out_of_scope and policy_exclusion) or none.
 */
export function curationForRelevanceReview(decision: RelevanceDecisionView, review: RelevanceReview): RelevanceCuration {
  const accepted = review.label !== null && review.label === decision.positiveLabel;
  if (!accepted && !review.reasonCode) {
    throw new Error("A review that does not accept the reference needs a reason code.");
  }
  return {
    action: accepted ? "accept" : "reject",
    reasonCode: accepted ? null : review.reasonCode,
    note: review.explanation?.trim() || null,
    decisionRelationId: decision.decisionRelationId,
    shareable: review.shareable,
  };
}
