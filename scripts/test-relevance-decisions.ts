import assert from "node:assert/strict";
import { referenceCurationMetadata } from "../amplify/functions/shared/reference-curation-metadata";
import type { SemanticRelationRecord } from "../lib/category-repository";
import { currentRelevanceDecisions } from "../lib/relevance-decisions";

function relation(overrides: Partial<SemanticRelationRecord>): SemanticRelationRecord {
  return {
    id: "semantic-relation-1",
    relationState: "current",
    predicate: "relevance_decision_is",
    subjectKind: "reference",
    subjectId: "reference-a-v1",
    subjectLineageId: "reference-a",
    objectKind: "semanticNode",
    objectId: "semantic-node-relevance-include-v1",
    objectLineageId: "semantic-node-relevance-include",
    confidence: 0.82,
    modelVersion: "3",
    reviewRecommended: true,
    metadata: JSON.stringify({
      decisionId: "decision-1",
      label: "include",
      probabilities: { include: 0.82, exclude: 0.18 },
      reviewReason: "audit",
      reviewDetail: "Random audit sample.",
    }),
    ...overrides,
  } as SemanticRelationRecord;
}

// The References tab reads the current decision for each reference from relations it already has.
const decisions = currentRelevanceDecisions([
  relation({}),
  relation({ id: "semantic-relation-old", relationState: "superseded", subjectLineageId: "reference-a" }),
  relation({ id: "semantic-relation-other", predicate: "quality_rating_is", subjectLineageId: "reference-b" }),
]);
assert.equal(decisions.size, 1);
assert.deepEqual(decisions.get("reference-a"), {
  decisionRelationId: "semantic-relation-1",
  decisionId: "decision-1",
  label: "include",
  confidence: 0.82,
  version: 3,
  reviewRecommended: true,
  reviewReason: "audit",
  reviewDetail: "Random audit sample.",
  classes: ["include", "exclude"],
  positiveLabel: null,
  question: null,
  reviewControl: "labels",
});

// An editor's review records the decision it answered and whether its explanation may be shared.
assert.deepEqual(referenceCurationMetadata({
  action: "reject", curationStatus: "rejected", reasonCode: "out_of_scope",
  referenceId: "reference-a-v1", referenceLineageId: "reference-a",
  decisionRelationId: "semantic-relation-1", shareable: true,
}), {
  action: "reject", curationStatus: "rejected", reasonCode: "out_of_scope", curationReasonCode: "out_of_scope",
  referenceId: "reference-a-v1", referenceLineageId: "reference-a",
  decisionRelationId: "semantic-relation-1", shareable: true,
});

// Without a decision the metadata is exactly what it was before.
assert.deepEqual(referenceCurationMetadata({
  action: "accept", curationStatus: "accepted", reasonCode: null,
  referenceId: "reference-a-v1", referenceLineageId: "reference-a",
}), {
  action: "accept", curationStatus: "accepted", reasonCode: null, curationReasonCode: null,
  referenceId: "reference-a-v1", referenceLineageId: "reference-a",
});

console.log("relevance decisions: ok");
