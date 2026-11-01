import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createReferenceLink, decideReferenceLink, referenceLinkRelationId, type ReferenceLinkRow, type ReferenceLinkStore } from "../amplify/functions/category-action/reference-links";

type Vectors = {
  references: string[];
  node: { id: string; lineageId: string; versionNumber: number };
  cases: Array<{ name: string; steps: Array<Record<string, any>>; expectedRows: Record<string, Record<string, unknown>> }>;
};
const vectors: Vectors = JSON.parse(readFileSync("scripts/fixtures/reference-link-row-vectors.json", "utf8"));

function fakeStore() {
  const relations = new Map<string, ReferenceLinkRow>();
  const store: ReferenceLinkStore = {
    getCurrentReference: async (id) => (vectors.references.includes(id) ? { id: `${id}-v1`, lineageId: id, versionNumber: 1 } : null),
    getSemanticNode: async (id) => (id === vectors.node.lineageId ? vectors.node : null),
    getRelation: async (id) => relations.get(id) ?? null,
    putRelation: async (relation, existing) => {
      const id = relation.id as string;
      assert.equal(existing, relations.has(id));
      relations.set(id, { ...(relations.get(id) ?? {}), ...relation } as ReferenceLinkRow);
    },
  };
  return { store, relations };
}

for (const vectorCase of vectors.cases) {
  test(`byte-compatible with the Python writer: ${vectorCase.name}`, async () => {
    const { store, relations } = fakeStore();
    for (const step of vectorCase.steps) {
      if (step.op === "link") {
        await createReferenceLink(store, { subjectLineageId: step.a, objectKind: "reference", objectLineageId: step.b, predicate: step.predicate, note: step.note, callerSub: step.actor, now: step.now });
      } else if (step.op === "concept") {
        await createReferenceLink(store, { subjectLineageId: step.reference, objectKind: "semanticNode", objectLineageId: vectors.node.lineageId, predicate: "related_to", callerSub: step.actor, now: step.now });
      } else if (step.op === "suggest") {
        relations.set(step.seedRow.id, { ...step.seedRow, metadata: JSON.stringify(step.seedRow.metadata) });
      } else {
        const [predicate, ...ends] = step.relation as string[];
        const ordered = predicate === "related_to" ? [...ends].sort() : ends;
        await decideReferenceLink(store, { relationId: referenceLinkRelationId(predicate, ordered[0], ordered[1]), decision: step.decision === "accepted" ? "accept" : "reject", reasonCode: step.reasonCode, note: step.note, callerSub: step.actor, now: step.now });
      }
    }
    const rows = Object.fromEntries([...relations].map(([id, row]) => [id, { ...row, metadata: JSON.parse(row.metadata as string) }]));
    assert.deepEqual(rows, vectorCase.expectedRows);
  });
}

test("a second write of the same pair updates the one row and keeps who added it first", async () => {
  const { store, relations } = fakeStore();
  const first = await createReferenceLink(store, { subjectLineageId: "reference-a", objectKind: "reference", objectLineageId: "reference-b", predicate: "related_to", callerSub: "sub-1", now: "2026-11-01T12:00:00Z" });
  const second = await createReferenceLink(store, { subjectLineageId: "reference-b", objectKind: "reference", objectLineageId: "reference-a", predicate: "related_to", callerSub: "sub-2", now: "2026-11-02T12:00:00Z" });
  assert.deepEqual([first.outcome, second.outcome, relations.size], ["created", "updated", 1]);
  assert.equal(JSON.parse(relations.get(first.relationId)!.metadata as string).addedBy, "sub-1");
});

test("bad input is refused in words", async () => {
  const { store } = fakeStore();
  const base = { subjectLineageId: "reference-a", objectKind: "reference", objectLineageId: "reference-b", predicate: "related_to", callerSub: "sub-1", now: "2026-11-01T12:00:00Z" };
  await assert.rejects(createReferenceLink(store, { ...base, predicate: "mentions" }), /predicate must be one of/);
  await assert.rejects(createReferenceLink(store, { ...base, objectLineageId: "reference-a" }), /cannot be linked to itself/);
  await assert.rejects(createReferenceLink(store, { ...base, objectLineageId: "nope" }), /Reference not found/);
  await assert.rejects(createReferenceLink(store, { ...base, objectKind: "semanticNode", objectLineageId: "nope" }), /Concept not found/);
  await assert.rejects(createReferenceLink(store, { ...base, objectKind: "semanticNode", objectLineageId: vectors.node.lineageId, predicate: "cites" }), /related_to/);
  await assert.rejects(decideReferenceLink(store, { relationId: "missing", decision: "accept", callerSub: "sub-1", now: base.now }), /not found/);
  await assert.rejects(decideReferenceLink(store, { relationId: "missing", decision: "maybe", callerSub: "sub-1", now: base.now }), /accept or reject/);
});

test("only a reference or concept link can be decided", async () => {
  const { store, relations } = fakeStore();
  relations.set("quality-1", { id: "quality-1", relationState: "current", predicate: "quality_rating_is", subjectKind: "reference", subjectLineageId: "reference-a", objectKind: "semanticNode", objectLineageId: "q", metadata: "{}" });
  await assert.rejects(decideReferenceLink(store, { relationId: "quality-1", decision: "reject", callerSub: "sub-1", now: "2026-11-01T12:00:00Z" }), /not a reference link/);
});

test("only editors can call the three mutations", () => {
  const resource = readFileSync("amplify/data/resource.ts", "utf8");
  for (const name of ["createReferenceLink", "decideReferenceLink"]) {
    const block = resource.slice(resource.indexOf(`  ${name}: a`), resource.indexOf("handler(", resource.indexOf(`  ${name}: a`)));
    assert.match(block, /allow\.groups\(categoryWriteGroups\)/);
  }
  const suggest = resource.slice(resource.indexOf("  suggestReferenceLinks: a"), resource.indexOf("handler(", resource.indexOf("  suggestReferenceLinks: a")));
  assert.match(suggest, /allow\.groups\(contentWriteGroups\)/);
  assert.match(readFileSync("amplify/data/resource.ts", "utf8"), /const contentWriteGroups = \["editor", "admin"\]/);
});
