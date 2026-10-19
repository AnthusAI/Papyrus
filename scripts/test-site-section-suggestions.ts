import assert from "node:assert/strict";
import type { SemanticRelationRecord } from "../lib/category-repository";
import { createLocalPreviewSectionFixtures } from "../lib/local-preview-section-fixtures";
import { currentSectionSuggestions, parseSiteSectionAgreement, sectionAgreementIsMeasured, siteCyclotronIdOf } from "../lib/site-section-suggestions";

function relation(overrides: Partial<SemanticRelationRecord>): SemanticRelationRecord {
  return {
    id: "relation-1",
    relationState: "current",
    predicate: "site_decision_is",
    subjectKind: "reference",
    subjectId: "reference-a-v1",
    subjectLineageId: "reference-a",
    objectKind: "semanticNode",
    objectId: "node-v1",
    objectLineageId: "node",
    classifierId: "site-cyclotron/section-selector-1a2b",
    confidence: 0.7,
    metadata: JSON.stringify({ cyclotronId: "site-cyclotron", label: "science", probabilities: { science: 0.7, politics: 0.2, sports: 0.1 }, decidedAt: "2026-10-18T05:00:00Z" }),
    ...overrides,
  } as SemanticRelationRecord;
}

const suggestions = currentSectionSuggestions([
  relation({}),
  relation({ id: "relation-fit", classifierId: "site-cyclotron/section-fit-science", subjectLineageId: "reference-b" }),
  relation({ id: "relation-old", relationState: "superseded", subjectLineageId: "reference-c" }),
  relation({ id: "relation-other", predicate: "relevance_decision_is", subjectLineageId: "reference-d" }),
]);
assert.deepEqual([...suggestions.keys()], ["reference-a"]);
const suggestion = suggestions.get("reference-a");
assert.equal(suggestion?.sectionId, "science");
assert.equal(suggestion?.cyclotronId, "site-cyclotron");
assert.deepEqual(suggestion?.probabilities.map((entry) => entry.sectionId), ["science", "politics", "sports"]);
assert.equal(siteCyclotronIdOf(suggestions), "site-cyclotron");

const agreement = parseSiteSectionAgreement({
  schema: "cyclotron-shadow-agreement/v1",
  computedAt: "2026-10-18T09:00:00Z",
  comparisons: 12,
  selectorAccuracy: 0.75,
  classifiers: {
    "section-selector-1a2b": { comparisons: 12, correct: 9, agreement: 0.75 },
    "section-fit-science": { comparisons: 12, agreement: 0.9, precision: 0.8, recall: 0.7 },
    "section-fit-politics": { comparisons: 3, agreement: 1, precision: 1, recall: 1 },
  },
});
assert.equal(agreement?.selectorAccuracy, 0.75);
assert.deepEqual(agreement?.sections.map((entry) => entry.sectionId), ["science", "politics"]);
assert.equal(sectionAgreementIsMeasured(agreement?.sections[0]), true);
assert.equal(sectionAgreementIsMeasured(agreement?.sections[1]), false);
assert.equal(sectionAgreementIsMeasured(undefined), false);
assert.equal(parseSiteSectionAgreement({ schema: "other" }), null);
assert.equal(parseSiteSectionAgreement({ schema: "cyclotron-shadow-agreement/v1", comparisons: 4 }), null);

const fixtures = createLocalPreviewSectionFixtures([{ id: "ref-1", lineageId: "ref-1" } as never, { id: "ref-2" } as never], ["a", "b", "c"]);
assert.equal(currentSectionSuggestions(fixtures.relations).size, 2);
assert.equal(fixtures.agreement?.sections.length, 3);
assert.deepEqual(createLocalPreviewSectionFixtures([], ["only"]), { relations: [], agreement: null });
console.log("site section suggestions: ok");
