import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { MessageRecord, SemanticRelationRecord } from "../lib/category-repository";
import {
  agreementStripState,
  dailyCapWords,
  delegatedCurationsByReference,
  delegationShortId,
  loopStateWords,
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
  const few = agreementStripState(parseShadowAgreement(payload({ comparisons: 9 })));
  assert.equal(few.kind, "not_enough");
  assert.equal(agreementStripState(parseShadowAgreement(payload({ comparisons: 10 }))).kind, "measured");

  // The loop object says on or off, the last sweep, the cap, and why it stopped.
  const loop = { enabled: false, stoppedBecause: "disabled", lastSweepAt: "2026-10-18T10:00:00Z", maxDecisionsPerDay: null };
  const stopped = agreementStripState(parseShadowAgreement(payload({ loop })));
  assert.ok(stopped.kind !== "hidden");
  {
    assert.deepEqual(stopped.loop, loop);
    assert.match(stopped.stopReasonSentence ?? "", /switched off/);
    assert.equal(loopStateWords(stopped.loop!), "Suggestions off");
    assert.equal(dailyCapWords(stopped.loop!), "No daily limit");
  }
  assert.equal(dailyCapWords({ ...loop, maxDecisionsPerDay: 50 }), "Daily limit 50 decisions");
  assert.equal(parseShadowAgreement(payload())?.loop, null);
  assert.match(stopReasonSentence("daily decision cap"), /daily limit/);
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

  // A delegated curation names the agent, the person, the quoted instruction and a short delegation id.
  const delegatedMessage = {
    ...curationMessage("m7", "delegated-ref", "2026-10-12T00:00:00Z", "human"), authorLabel: "Maya Okafor",
    metadata: JSON.stringify({ referenceLineageId: "delegated-ref", actorKind: "human", attestation: "delegated", relayedBy: "newsroom-reporter",
      delegationId: "curation-delegation-9b1f6c24-5d0e", instruction: "Reject it." }),
  } as MessageRecord;
  const delegations = delegatedCurationsByReference([delegatedMessage, curationMessage("m8", "human-ref", "2026-10-12T00:00:00Z", "human")]);
  assert.deepEqual([...delegations.keys()], ["delegated-ref"]);
  assert.deepEqual(delegations.get("delegated-ref"), {
    agent: "newsroom-reporter", person: "Maya Okafor", instruction: "Reject it.",
    delegationId: "curation-delegation-9b1f6c24-5d0e", delegationShortId: "9b1f6c24", countsAsTrainingLabel: true,
  });
  assert.equal(delegationShortId("curation-delegation-abcdef0123"), "abcdef01");
  assert.equal(delegatedCurationsByReference([delegatedMessage, curationMessage("m9", "delegated-ref", "2026-10-13T00:00:00Z", "service")]).size, 0);

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
    teachingLabelsSentence: "Based on 1 decision that editors made themselves",
    primingExamplesSentence: "6 example references supplied as starting examples",
    doctrineShortHash: "3f9c2a71",
    modelVersion: "revision 4",
    decidedAt: "2026-10-17T08:30:00.000Z",
  });
  assert.equal(provenanceSummary(includeDecision), null);
  const sharedProvenance = currentRelevanceDecisions([relation({
    provenance: { system: "cyclotron-lab", publicationId: "example", output: "example-relevance", labelSet: ["include", "exclude"] },
  })]).get("reference-a")!;
  assert.equal(provenanceSummary(sharedProvenance)?.teachingLabelsSentence, null, "an unrecorded teaching count is not zero");
  assert.equal(provenanceSummary(sharedProvenance)?.primingExamplesSentence, null, "an unrecorded example count is not zero");

  const { ReferenceSuggestionBlock, ReferenceSuggestionProvenance, CountsAsTrainingLabelNote, DelegatedCurationNote } =
    await import("../components/reference-cyclotron-suggestion");
  const { ReferenceLiveAgreement } = await import("../components/reference-live-agreement");

  const block = renderToStaticMarkup(createElement(ReferenceSuggestionBlock, {
    decision: withProvenance, onCurate: () => undefined, referenceLineageId: "reference-a", settled: false, statusLabel: "Pending",
  }));
  for (const text of ["Publication prediction", "never changes the status until an editor acts", "Agree (accept)", "Overrule (reject)"]) {
    assert.ok(block.includes(text), `suggestion shows: ${text}`);
  }
  assert.ok(!/decision/i.test(block.replace(/data-[a-z-]+/g, "")), "a suggestion is never worded as a decision");
  const settledBlock = renderToStaticMarkup(createElement(ReferenceSuggestionBlock, {
    decision: withProvenance, referenceLineageId: "reference-a", settled: true, statusLabel: "Accepted",
  }));
  assert.ok(!settledBlock.includes("Agree"), "a settled reference offers no Agree button");

  const provenanceMarkup = renderToStaticMarkup(createElement(ReferenceSuggestionProvenance, { decision: withProvenance }));
  for (const text of ["How this suggestion was made", "6 example references", "3f9c2a71", "revision 4", "2026-10-17 08:30 UTC"]) {
    assert.ok(provenanceMarkup.includes(text), `provenance shows: ${text}`);
  }
  const sharedMarkup = renderToStaticMarkup(createElement(ReferenceSuggestionProvenance, { decision: sharedProvenance }));
  assert.ok(sharedMarkup.includes("Shared publication classifier"));
  assert.ok(!sharedMarkup.includes("0 decisions") && !sharedMarkup.includes("0 example references"));
  assert.ok(renderToStaticMarkup(createElement(CountsAsTrainingLabelNote, { referenceLineageId: "x" })).includes("Recorded as an editor"));

  const delegatedMarkup = renderToStaticMarkup(createElement(DelegatedCurationNote, { delegated: delegations.get("delegated-ref")!, referenceLineageId: "delegated-ref" }));
  for (const text of ["Decided by newsroom-reporter on behalf of Maya Okafor", "Reject it.", "Delegation 9b1f6c24", "Recorded as Maya Okafor"]) {
    assert.ok(delegatedMarkup.includes(text), `delegated note shows: ${text}`);
  }

  assert.equal(renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: null })), "");
  const fewMarkup = renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: parseShadowAgreement(payload({ comparisons: 4 })) }));
  assert.ok(fewMarkup.includes("Not enough decisions yet") && !fewMarkup.includes("87%"));
  const strip = renderToStaticMarkup(createElement(ReferenceLiveAgreement, {
    agreement: parseShadowAgreement(payload({ loop: { enabled: true, stoppedBecause: "daily decision cap", lastSweepAt: "2026-10-18T10:00:00Z", maxDecisionsPerDay: 50 } })),
  }));
  for (const text of ["87%", "90%", "82%", "23", "Updated 2026-10-18 09:00 UTC", "Suggestions on", "Last checked 2026-10-18 10:00 UTC", "Daily limit 50 decisions", "reached the daily limit"]) {
    assert.ok(strip.includes(text), `strip shows: ${text}`);
  }
  const off = renderToStaticMarkup(createElement(ReferenceLiveAgreement, { agreement: parseShadowAgreement(payload({ loop })) }));
  assert.ok(off.includes("Suggestions off") && off.includes("switched off"));

  console.log("cyclotron suggestion helpers ok");
}

void main();
