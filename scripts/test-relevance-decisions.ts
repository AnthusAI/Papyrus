import assert from "node:assert/strict";
import { curationActorKind, referenceVoteFields } from "../amplify/functions/shared/reference-curation-metadata";
import type { SemanticRelationRecord } from "../lib/category-repository";
import { awaitsEditorReview, currentRelevanceDecisions } from "../lib/relevance-decisions";

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
  cyclotronId: null,
  decidedAt: null,
  provenance: null,
});

// The monitoring router uses the same relation contract as the local relevance
// sweep (monitoring_router.lab_decision_records -> relevance_decision_records).
// Its provenance deliberately has no teaching counts or model rationale.
const sharedMetadata = {
  decisionId: "shared-decision-1", cyclotronId: "example-relevance", classifier: "example-relevance",
  label: "include", probabilities: {}, version: 7, fingerprint: "model-fingerprint",
  reviewReason: null, reviewDetail: null, propensity: null, decidedAt: "2026-10-23T10:00:00Z",
  question: null, labels: ["include", "exclude"], positiveLabel: "include", reviewControl: "thumbs",
  provenance: { system: "cyclotron-lab", accountId: "account-example", runId: "shared-run",
    bindingRevision: "binding-3", publicationId: "example", output: "example-relevance",
    decisionId: "shared-decision-1", fingerprint: "model-fingerprint", version: 7,
    labelSet: ["include", "exclude"], sourceId: "synthetic-source" },
};
const shared = currentRelevanceDecisions([relation({
  id: "shared-relation", classifierId: "example-relevance/example-relevance", modelVersion: "7",
  confidence: null, reviewRecommended: false, metadata: JSON.stringify(sharedMetadata),
})]).get("reference-a")!;
assert.equal(shared.confidence, null, "an omitted confidence is not guessed from the label");
assert.equal(shared.reviewDetail, null, "review selection detail is not invented as a rationale");
assert.equal(shared.provenance?.teachingLabels, null, "the router did not supply a teaching count");
assert.equal(shared.provenance?.primingExamples, null, "the router did not supply an example count");
assert.equal(shared.provenance?.system, "cyclotron-lab");
assert.equal(shared.provenance?.publicationId, "example");
assert.equal(shared.provenance?.output, "example-relevance");
assert.equal(shared.classifierId, "example-relevance/example-relevance");

for (const invalidVersion of [null, undefined, "", " ", "NaN", "-1", "1.5"]) {
  const value = currentRelevanceDecisions([relation({ modelVersion: invalidVersion,
    metadata: JSON.stringify({ ...sharedMetadata, version: null }) })]).get("reference-a")!;
  assert.equal(value.version, null, `unrecorded or invalid version ${String(invalidVersion)} stays unknown`);
}
for (const invalidConfidence of [NaN, Infinity, -0.1, 1.1]) {
  assert.equal(currentRelevanceDecisions([relation({ confidence: invalidConfidence })]).get("reference-a")!.confidence,
    null, "invalid probabilities are not displayed as confidence");
}
assert.equal(currentRelevanceDecisions([relation({ confidence: 0 })]).get("reference-a")!.confidence, 0);
for (const metadata of ["{}", JSON.stringify({ decisionId: "d", label: " " }),
  JSON.stringify({ decisionId: "d", label: 123 })]) {
  assert.equal(currentRelevanceDecisions([relation({ metadata })]).size, 0, "an incomplete row is not a prediction");
}
assert.equal(currentRelevanceDecisions([relation({ subjectKind: "item" })]).size, 0);
assert.equal(currentRelevanceDecisions([relation({ predicate: "site_decision_is", classifierId: "site/section-selector-test" })]).size,
  0, "Section selection is never presented as publication relevance");

// Pagination and realtime delivery may interleave current rows while an older
// row is being superseded. Read the newest recorded prediction independent of order.
const older = relation({ id: "older", importedAt: "2026-10-22T10:00:00Z" });
const newer = relation({ id: "newer", importedAt: "2026-10-23T10:00:00Z" });
for (const order of [[newer, older], [older, newer]]) {
  assert.equal(currentRelevanceDecisions(order).get("reference-a")!.decisionRelationId, "newer");
}

// An editor's vote records the decision it answered and whether its explanation may be shared, on the Reference.
assert.deepEqual(referenceVoteFields({
  actorKind: "human", reasonCode: "out_of_scope", decisionRelationId: "semantic-relation-1", shareable: true,
}), {
  curationActorKind: "human", curationReasonCode: "out_of_scope", curationSectionId: null, curationShareable: true,
  curationDelegation: null, curationDecisionRelationId: "semantic-relation-1",
});

// Without a decision there is nothing to share, and every field is still present so a new vote clears the last one.
assert.deepEqual(referenceVoteFields({ actorKind: "human" }), {
  curationActorKind: "human", curationReasonCode: null, curationSectionId: null, curationShareable: null,
  curationDelegation: null, curationDecisionRelationId: null,
});

// Only a user-pool sign-in is a human curation; no argument can claim it.
assert.equal(curationActorKind({ claims: { sub: "user-1", email: "editor@example.org" } }), "human");
assert.equal(curationActorKind({ claims: {} }), "agent");
assert.equal(curationActorKind({ userArn: "arn:aws:sts::1:assumed-role/agent" }), "agent");
assert.equal(curationActorKind(null), "agent");

// Needs review: a pending reference with a current suggestion, flagged by the cyclotron or not.
const suggested = currentRelevanceDecisions([relation({ reviewRecommended: false })]).get("reference-a");
assert.ok(suggested);
assert.equal(suggested.reviewRecommended, false);
assert.equal(awaitsEditorReview("pending", suggested), true);
assert.equal(awaitsEditorReview(undefined, suggested), true);
assert.equal(awaitsEditorReview("accepted", suggested), false);
assert.equal(awaitsEditorReview("rejected", suggested), false);
assert.equal(awaitsEditorReview("pending", undefined), false);

console.log("relevance decisions: ok");
