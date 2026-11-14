import assert from "node:assert/strict";
import test from "node:test";
import { latestReferenceReviewReasons, latestReferenceReviewSections, loadReferenceReviewDetails } from "../lib/reference-review-details";
import { referencesWithHumanLatestCuration } from "../lib/cyclotron-suggestions";
import type { ReferenceRecord, SemanticRelationRecord } from "../lib/category-repository";

const prediction = { id: "prediction", predicate: "relevance_decision_is", relationState: "current", subjectKind: "reference", subjectLineageId: "reference-a" } as SemanticRelationRecord;
const otherPrediction = { ...prediction, id: "other", subjectLineageId: "reference-b" } as SemanticRelationRecord;
const reference = (fields: Partial<ReferenceRecord> = {}) => ({
  id: "reference-a-v1", lineageId: "reference-a", versionNumber: 1, versionState: "current", corpusId: "corpus", externalItemId: "a",
  curationStatus: "accepted", curationActorKind: "human", ...fields,
}) as ReferenceRecord;

test("the selected reference reads only its indexed predictions; its vote is already on the Reference", async () => {
  const reads: string[] = [];
  const result = await loadReferenceReviewDetails("reference-a", {
    relations: async direction => { reads.push(direction); return [prediction, otherPrediction]; },
  });
  assert.deepEqual(result.relations, [prediction]);
  assert.deepEqual(reads, ["outgoing"], "no Message, attachment or incoming-relation read");
});

test("a Reference with no recorded vote does not invent a human label", () => {
  assert.equal(referencesWithHumanLatestCuration([reference({ curationActorKind: null })]).size, 0);
  assert.equal(referencesWithHumanLatestCuration([reference({ curationActorKind: "agent" })]).size, 0, "an agent vote is never relabeled human");
  assert.equal(referencesWithHumanLatestCuration([reference()]).has("reference-a"), true);
});

test("review reasons come from the Reference's latest vote and a later acceptance removes the prior rejection", () => {
  const rejected = reference({ curationStatus: "rejected", curationReasonCode: "duplicate" });
  assert.equal(latestReferenceReviewReasons([rejected]).get("reference-a"), "duplicate");
  const accepted = reference({ curationStatus: "accepted", curationReasonCode: null });
  assert.equal(latestReferenceReviewReasons([accepted]).has("reference-a"), false);
  assert.equal(latestReferenceReviewReasons([reference({ curationStatus: "rejected", curationReasonCode: "duplicate", curationActorKind: null })]).size, 0);
});

test("Section selection is read only from the latest recorded acceptance", () => {
  assert.equal(latestReferenceReviewSections([reference({ curationSectionId: "section-explicit" })]).get("reference-a"), "section-explicit");
  assert.equal(latestReferenceReviewSections([reference()]).size, 0);
  assert.equal(latestReferenceReviewSections([reference({ curationStatus: "rejected", curationSectionId: "section-explicit" })]).size, 0);
});
