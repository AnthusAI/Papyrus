import assert from "node:assert/strict";
import test from "node:test";
import { loadReferenceReviewDetails } from "../lib/reference-review-details";
import { referenceCurationMetadata } from "../amplify/functions/shared/reference-curation-metadata";
import { referencesWithHumanLatestCuration } from "../lib/cyclotron-suggestions";
import type { HydratedModelPayload, MessageRecord, SemanticRelationRecord } from "../lib/category-repository";

const relation = (id: string, createdAt: string) => ({id, predicate:"comment", relationState:"current", subjectKind:"message", subjectId:id,
  objectKind:"reference", objectLineageId:"reference-a", createdAt, metadata:JSON.stringify({messageKind:"reference_curation"})}) as SemanticRelationRecord;
const message = {id:"latest", messageKind:"reference_curation", createdAt:"2026-10-23T10:00:00Z", authorLabel:"An editor", metadata:null} as MessageRecord;
const metadata = referenceCurationMetadata({action:"accept", curationStatus:"accepted", reasonCode:null, referenceId:"reference-a-v1", referenceLineageId:"reference-a", actorKind:"human"});
const payload = {attachment:{id:"payload", role:"metadata", ownerKind:"message", ownerId:"latest"},json:metadata,error:null,text:JSON.stringify(metadata)} as HydratedModelPayload;

test("selected reference reads indexed predictions and the newest review's server metadata attachment", async () => {
  const reads: string[] = [];
  const prediction = {id:"prediction", predicate:"relevance_decision_is", relationState:"current", subjectKind:"reference", subjectLineageId:"reference-a"} as SemanticRelationRecord;
  const result = await loadReferenceReviewDetails("reference-a", {
    relations:async direction => { reads.push(direction); return direction === "outgoing" ? [prediction] : [relation("old","2026-10-22"),relation("latest","2026-10-23")]; },
    message:async id => { reads.push(id); return message; },
    payloads:async id => { reads.push(`metadata:${id}`); return [payload]; },
  });
  assert.deepEqual(result.relations, [prediction]);
  assert.deepEqual(result.messages[0].metadata, metadata);
  assert.equal(referencesWithHumanLatestCuration(result.messages).has("reference-a"), true);
  assert.deepEqual(reads.sort(), ["latest","metadata:latest","incoming","outgoing"].sort(), "no per-row message or attachment fanout");
});

test("unreadable review metadata is an error, and no review does not invent a human label", async () => {
  const deps = {relations:async () => [relation("latest","2026-10-23")], message:async () => message,
    payloads:async () => [{...payload, error:"Attachment access denied", json:null}]};
  await assert.rejects(loadReferenceReviewDetails("reference-a",deps), /Attachment access denied/);
  const empty = await loadReferenceReviewDetails("reference-a", {...deps, relations:async () => []});
  assert.deepEqual(empty.messages,[]);
  assert.equal(referencesWithHumanLatestCuration(empty.messages).size,0);
});

test("a latest review requires its metadata attachment and a matching reference lineage", async () => {
  const deps = {
    relations: async () => [relation("latest", "2026-10-23")],
    message: async () => ({ ...message, metadata }),
  };
  await assert.rejects(loadReferenceReviewDetails("reference-a", {
    ...deps,
    payloads: async () => [],
  }), /metadata could not be loaded/, "inline metadata cannot replace the required attachment");
  for (const json of [{}, { actorKind: "human" }, { ...metadata, referenceLineageId: "reference-b" }]) {
    await assert.rejects(loadReferenceReviewDetails("reference-a", {
      ...deps,
      payloads: async () => [{ ...payload, json }],
    }), /reference lineage/, "incomplete metadata must not leave an older human review apparently current");
  }
});

test("latest review reasons come from Messages and a later acceptance removes the prior rejection", async () => {
  const { latestReferenceReviewReasons } = await import("../lib/reference-review-details");
  const rejected = {...message, metadata:{...metadata,action:"reject",curationStatus:"rejected",reasonCode:"duplicate"}};
  assert.equal(latestReferenceReviewReasons([rejected]).get("reference-a"),"duplicate");
  const accepted = {...message,id:"newer",createdAt:"2026-10-24T10:00:00Z",metadata};
  assert.equal(latestReferenceReviewReasons([rejected,accepted]).has("reference-a"),false);
  const service = {...message,metadata:{...metadata,actorKind:"service"}};
  assert.equal(referencesWithHumanLatestCuration([service]).size,0,"a fetched service review is never relabeled human");
});

test("Section selection is preserved only from the latest recorded acceptance", async () => {
  const { latestReferenceReviewSections } = await import("../lib/reference-review-details");
  const selected = {...message,metadata:{...metadata,sectionId:"section-explicit"}};
  assert.equal(latestReferenceReviewSections([selected]).get("reference-a"),"section-explicit");
  const noSection = {...message,id:"newer",createdAt:"2026-10-24T10:00:00Z",metadata};
  assert.equal(latestReferenceReviewSections([selected,noSection]).size,0);
  const rejected = {...noSection,metadata:{...metadata,action:"reject",sectionId:"section-explicit"}};
  assert.equal(latestReferenceReviewSections([selected,rejected]).size,0);
});
