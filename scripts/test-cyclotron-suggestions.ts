import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { MessageRecord, SemanticRelationRecord } from "../lib/category-repository";
import {
  agreementStripState,
  curationForSuggestionChoice,
  latestShadowAgreement,
  parseShadowAgreement,
  provenanceSummary,
  referencesWithHumanLatestCuration,
  shadowAgreementPayloadId,
  stopReasonSentence,
} from "../lib/cyclotron-suggestions";
import { currentRelevanceDecisions } from "../lib/relevance-decisions";

function payload(overrides: Record<string, unknown> = {}) {
  return {
    schema: "cyclotron-shadow-agreement/v1", comparisons: 23, agreement: 0.87, precision: 0.9, recall: 0.82,
    confusion: {}, computedAt: "2026-10-18T09:00:00.000Z", positiveLabel: "include", ...overrides,
  };
}

function relation(metadata: Record<string, unknown>): SemanticRelationRecord {
  return {
    id: "relation-1", relationState: "current", predicate: "relevance_decision_is", subjectKind: "reference",
    subjectId: "reference-a-v1", subjectLineageId: "reference-a", objectKind: "semanticNode", objectId: "node-v1",
    objectLineageId: "node", confidence: 0.8, modelVersion: "4",
    metadata: JSON.stringify({ decisionId: "d1", label: "include", positiveLabel: "include", labels: ["include", "exclude"], ...metadata }),
  } as SemanticRelationRecord;
}

function curationMessage(id: string, lineageId: string, createdAt: string, actorKind?: string): MessageRecord {
  return {
    id, messageKind: "reference_curation", messageDomain: "commentary", status: "active", createdAt, updatedAt: createdAt,
    metadata: JSON.stringify({ referenceLineageId: lineageId, ...(actorKind ? { actorKind } : {}) }),
  } as MessageRecord;
}

async function main() {
  (globalThis as { React?: typeof React }).React = React;

  assert.equal(shadowAgreementPayloadId("Papyrus Relevance"), "knowledge-raw-payload-cyclotron-shadow-agreement-papyrus-relevance");
  assert.equal(parseShadowAgreement({ schema: "something-else" }), null);
  assert.equal(latestShadowAgreement([
    { json: payload({ comparisons: 11 }), updatedAt: "2026-10-17T00:00:00Z" },
    { json: payload({ comparisons: 23 }), updatedAt: "2026-10-18T00:00:00Z" },
    { json: { schema: "other" }, updatedAt: "2026-10-19T00:00:00Z" },
  ])?.comparisons, 23);

  // No payload hides the strip; under ten comparisons the figures are withheld; ten or more shows them.
  assert.deepEqual(agreementStripState(null), { kind: "hidden" });
  assert.deepEqual(agreementStripState(parseShadowAgreement(payload({ comparisons: 9 }))), {
    kind: "not_enough", comparisons: 9, needed: 10, computedAt: "2026-10-18T09:00:00.000Z", reason: null,
  });
  const measured = agreementStripState(parseShadowAgreement(payload({ comparisons: 10 })));
  assert.equal(measured.kind, "measured");

  // A disabled loop or a stopped sweep shows its reason first.
  const disabled = agreementStripState(parseShadowAgreement(payload({ enabled: false, comparisons: 3 })));
  assert.deepEqual(disabled, { kind: "stopped", reason: "disabled", measurement: null });
  const capped = agreementStripState(parseShadowAgreement(payload({ stoppedBecause: "daily decision cap" })));
  assert.equal(capped.kind, "stopped");
  assert.match(stopReasonSentence("daily decision cap"), /daily decision cap/);
  assert.match(stopReasonSentence("odd"), /stopped early: odd/);

  // Only a latest curation Message made by a person counts as a training label.
  const humanLabels = referencesWithHumanLatestCuration([
    curationMessage("m1", "human-ref", "2026-10-10T00:00:00Z", "human"),
    curationMessage("m2", "service-ref", "2026-10-10T00:00:00Z", "service"),
    curationMessage("m3", "unstamped-ref", "2026-10-10T00:00:00Z"),
    curationMessage("m4", "overwritten-ref", "2026-10-10T00:00:00Z", "human"),
    curationMessage("m5", "overwritten-ref", "2026-10-11T00:00:00Z", "service"),
    { ...curationMessage("m6", "other-kind-ref", "2026-10-10T00:00:00Z", "human"), messageKind: "ingestion_rationale" },
  ]);
  assert.deepEqual([...humanLabels], ["human-ref"]);

  // Agree does what the suggestion implies; overrule the opposite.
  const includeDecision = currentRelevanceDecisions([relation({})]).get("reference-a")!;
  const excludeDecision = currentRelevanceDecisions([relation({ label: "exclude" })]).get("reference-a")!;
  assert.equal(curationForSuggestionChoice(includeDecision, "agree").action, "accept");
  assert.equal(curationForSuggestionChoice(includeDecision, "overrule").action, "reject");
  assert.equal(curationForSuggestionChoice(excludeDecision, "agree").action, "reject");
  assert.equal(curationForSuggestionChoice(excludeDecision, "overrule").action, "accept");
  assert.equal(curationForSuggestionChoice(includeDecision, "agree").decisionRelationId, "relation-1");

  // Provenance reads as plain sentences with a short doctrine hash.
  const withProvenance = currentRelevanceDecisions([relation({
    decidedAt: "2026-10-17T08:30:00.000Z",
    provenance: { labelSet: ["include", "exclude"], doctrineFingerprint: "3f9c2a71d80b46e5", teachingFingerprint: "b71e04c9aa5d2f13", teachingLabels: 1, primingExamples: 6 },
  })]).get("reference-a")!;
  assert.deepEqual(provenanceSummary(withProvenance), {
    teachingLabelsSentence: "Taught by 1 label that editors set themselves",
    primingExamplesSentence: "6 priming examples supplied as starting examples",
    doctrineShortHash: "3f9c2a71",
    modelVersion: "version 4",
    decidedAt: "2026-10-17T08:30:00.000Z",
  });
  assert.equal(provenanceSummary(includeDecision), null);

  const { ReferenceSuggestionBlock, ReferenceSuggestionProvenance, CountsAsTrainingLabelNote } =
    await import("../components/reference-cyclotron-suggestion");
  const { ReferenceLiveAgreement } = await import("../components/reference-live-agreement");

  const block = renderToStaticMarkup(createElement(ReferenceSuggestionBlock, {
    decision: withProvenance, onCurate: () => undefined, referenceLineageId: "reference-a", settled: false, statusLabel: "Pending",
  }));
  for (const text of ["Suggestion", "never changes the status until an editor acts", "Agree (accept)", "Overrule (reject)"]) {
    assert.ok(block.includes(text), `suggestion shows: ${text}`);
  }
  assert.ok(!/decision/i.test(block.replace(/data-[a-z-]+/g, "")), "a suggestion is never worded as a decision");
  const settledBlock = renderToStaticMarkup(createElement(ReferenceSuggestionBlock, {
    decision: withProvenance, referenceLineageId: "reference-a", settled: true, statusLabel: "Accepted",
  }));
  assert.ok(!settledBlock.includes("Agree"), "a settled reference offers no Agree button");

  const provenanceMarkup = renderToStaticMarkup(createElement(ReferenceSuggestionProvenance, { decision: withProvenance }));
  for (const text of ["How this suggestion was made", "6 priming examples", "3f9c2a71", "version 4", "2026-10-17 08:30 UTC"]) {
    assert.ok(provenanceMarkup.includes(text), `provenance shows: ${text}`);
  }
  assert.ok(renderToStaticMarkup(createElement(CountsAsTrainingLabelNote, { referenceLineageId: "x" })).includes("Counts as a training label"));

  assert.equal(renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: null })), "");
  const few = renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: parseShadowAgreement(payload({ comparisons: 4 })) }));
  assert.ok(few.includes("Not enough comparisons yet") && !few.includes("87%"));
  const strip = renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: parseShadowAgreement(payload()) }));
  for (const text of ["87%", "90%", "82%", "23", "Computed 2026-10-18 09:00 UTC"]) {
    assert.ok(strip.includes(text), `strip shows: ${text}`);
  }
  const stopped = renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: parseShadowAgreement(payload({ enabled: false })) }));
  assert.ok(stopped.includes("switched off"));

  console.log("cyclotron suggestion helpers ok");
}

void main();
