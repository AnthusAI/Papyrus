"use client";

import { useState, useSyncExternalStore } from "react";
import { ReviewControl, type ReviewReason } from "cyclotron/components/review-control";
import { isScopeTrainingNegativeReason, REFERENCE_REJECTION_REASON_CODES } from "../lib/reference-policy";
import {
  curationForRelevanceReview,
  type RelevanceCuration,
  type RelevanceDecisionView,
} from "../lib/relevance-decisions";

/**
 * Papyrus's existing rejection reasons, unchanged. Reasons that are not about
 * relevance (a duplicate, an unavailable source) close the review without
 * teaching the cyclotron.
 */
export const RELEVANCE_REVIEW_REASONS: ReviewReason[] = REFERENCE_REJECTION_REASON_CODES.map((code) => ({
  code,
  text: code.charAt(0).toUpperCase() + code.slice(1).replaceAll("_", " "),
  ...(isScopeTrainingNegativeReason(code) ? {} : { noLabel: true }),
}));

const subscribeNever = () => () => undefined;

/**
 * Rendered in the browser only: Cyclotron ui-v0.2.0's ReviewControl uses
 * React's useId, which this page's server and client trees number differently.
 * Remove the gate once the package uses ids derived from the item and decision.
 */
export function ReferenceRelevanceReview(props: Parameters<typeof RelevanceReviewBody>[0]) {
  const inBrowser = useSyncExternalStore(subscribeNever, () => true, () => false);
  return inBrowser ? <RelevanceReviewBody {...props} /> : null;
}

export function RelevanceReviewBody({
  disabled,
  decision,
  onCurate,
  referenceLineageId,
}: {
  disabled?: boolean;
  decision: RelevanceDecisionView;
  onCurate: (curation: RelevanceCuration) => void;
  referenceLineageId: string;
}) {
  const [shareable, setShareable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const classes = decision.classes.length ? decision.classes : [decision.label];
  return (
    <section aria-label="Relevance review" className="space-y-2" data-reference-relevance-review={referenceLineageId}>
      <ReviewControl
        decision={{
          decisionId: decision.decisionId,
          label: decision.label,
          confidence: decision.confidence,
          classes,
          version: decision.version ?? undefined,
        }}
        disabled={disabled}
        itemId={referenceLineageId}
        mode={decision.reviewControl === "thumbs" && classes.length === 2 ? "thumbs" : "labels"}
        onReview={(review) => {
          try {
            setError(null);
            onCurate(curationForRelevanceReview(decision, { ...review, shareable }));
          } catch (failure) {
            setError(failure instanceof Error ? failure.message : String(failure));
          }
        }}
        positiveLabel={decision.positiveLabel ?? undefined}
        question={decision.question ?? undefined}
        reasons={RELEVANCE_REVIEW_REASONS}
        reviewReason={decision.reviewRecommended ? decision.reviewDetail ?? undefined : undefined}
      />
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <input
          checked={shareable}
          disabled={disabled}
          onChange={(event) => setShareable(event.target.checked)}
          type="checkbox"
        />
        My explanation may be quoted publicly (for the Cyclotron example page)
      </label>
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
    </section>
  );
}
