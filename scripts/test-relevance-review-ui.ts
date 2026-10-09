import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createDemoCategorySteeringDashboard } from "../lib/category-repository";
import { REFERENCE_REJECTION_REASON_CODES } from "../lib/reference-policy";
import { curationForRelevanceReview, currentRelevanceDecisions } from "../lib/relevance-decisions";

async function main() {
// tsx compiles component JSX with the classic runtime outside Next.
(globalThis as { React?: typeof React }).React = React;
const { RELEVANCE_REVIEW_REASONS, ReferenceRelevanceReview, RelevanceReviewBody } = await import("../components/reference-relevance-review");

// Demo mode carries a fixture decision for its pending reference; no network is involved.
const dashboard = createDemoCategorySteeringDashboard();
const decisions = currentRelevanceDecisions(dashboard.semanticRelations);
const pending = dashboard.references.find((reference) => reference.curationStatus === "pending");
assert.ok(pending, "the demo has a pending reference");
const decision = decisions.get(pending.lineageId ?? pending.id);
assert.ok(decision, "the pending demo reference has a relevance decision");
assert.equal(decision.reviewControl, "thumbs");
assert.equal(decision.positiveLabel, "include");

// The editor sees the decision, its confidence and version, why it was sent, thumbs, and the shareable choice.
// The server render leaves the control to the browser (see the component's note).
assert.equal(renderToStaticMarkup(createElement(ReferenceRelevanceReview, {
  decision, onCurate: () => undefined, referenceLineageId: pending.lineageId ?? pending.id,
})), "");
const html = renderToStaticMarkup(createElement(RelevanceReviewBody, {
  decision, onCurate: () => undefined, referenceLineageId: pending.lineageId ?? pending.id,
}));
for (const text of [
  "Should this candidate source become a reference for this publication?",
  "82% sure · version 1",
  "Why you are seeing this: Every decision is reviewed while the cyclotron is onboarding.",
  "Yes · include",
  "No · exclude",
  "Submit review",
  "My explanation may be quoted publicly",
]) assert.ok(html.includes(text), `review control shows: ${text}`);

// Only Papyrus's existing reason codes; the ones not about relevance close the review without a label.
assert.deepEqual(RELEVANCE_REVIEW_REASONS.map((reason) => reason.code), [...REFERENCE_REJECTION_REASON_CODES]);
assert.deepEqual(RELEVANCE_REVIEW_REASONS.filter((reason) => !reason.noLabel).map((reason) => reason.code),
  ["out_of_scope", "policy_exclusion"]);

// A review becomes the existing curation mutation, carrying the decision it answered.
assert.deepEqual(curationForRelevanceReview(decision, { label: "include", reasonCode: null, explanation: " On our beat. ", shareable: true }),
  { action: "accept", reasonCode: null, note: "On our beat.", decisionRelationId: decision.decisionRelationId, shareable: true });
assert.deepEqual(curationForRelevanceReview(decision, { label: "exclude", reasonCode: "out_of_scope", explanation: null, shareable: false }),
  { action: "reject", reasonCode: "out_of_scope", note: null, decisionRelationId: decision.decisionRelationId, shareable: false });
assert.deepEqual(curationForRelevanceReview(decision, { label: null, reasonCode: "duplicate", explanation: "Already have it.", shareable: false }),
  { action: "reject", reasonCode: "duplicate", note: "Already have it.", decisionRelationId: decision.decisionRelationId, shareable: false });
assert.throws(() => curationForRelevanceReview(decision, { label: "exclude", reasonCode: null, explanation: null, shareable: false }), /reason code/);

console.log("relevance review ui: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
