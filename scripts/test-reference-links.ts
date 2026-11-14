import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createReferenceLink, decideReferenceLink, referenceLinkRelationId, type ReferenceLinkRow, type ReferenceLinkStore } from "../amplify/functions/category-action/reference-links";
import { publishedAddedText, referenceDatesText } from "../lib/reference-links";

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
        await createReferenceLink(store, { subjectLineageId: step.reference, objectKind: "semanticNode", objectLineageId: vectors.node.lineageId, predicate: "tagged_with", callerSub: step.actor, now: step.now });
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
  await assert.rejects(createReferenceLink(store, { ...base, objectKind: "semanticNode", objectLineageId: vectors.node.lineageId, predicate: "cites" }), /tagged_with/);
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

test("publication precision shows as a month or a year, and createdAt is never the publication date", () => {
  assert.equal(publishedAddedText("2026-10-01T00:00:00Z", "2026-10-28T08:00:00Z", "month"), "published Oct 2026 · added 2026-10-28");
  assert.equal(publishedAddedText("2026-01-01T00:00:00Z", "2026-10-28T08:00:00Z", "year"), "published 2026 · added 2026-10-28");
  assert.equal(referenceDatesText({ sourcePublishedAt: null, createdAt: "2026-10-28T08:00:00Z" }), "published unknown · added 2026-10-28");
  assert.equal(referenceDatesText({ sourcePublishedAt: "2026-10-01T00:00:00Z", createdAt: "2026-10-28T08:00:00Z", metadata: JSON.stringify({ publicationDateResolution: { precision: "month" } }) }), "published Oct 2026 · added 2026-10-28");
});

// --- concepts an editor invents by typing a hashtag -------------------------------------------------------------------------------------------
import { conceptSlug, describeEditorConcept, editorConceptLineageId, ensureEditorConcept, EDITOR_CONCEPT_KIND } from "../amplify/functions/category-action/reference-links";

function conceptStore() {
  const nodes = new Map<string, any>();
  const { store, relations } = fakeStore();
  let creates = 0;
  const full = {
    ...store,
    getSemanticNode: async (id: string) => nodes.get(id) ?? store.getSemanticNode(id),
    createSemanticNode: async (node: Record<string, unknown>) => { creates += 1; if (nodes.has(node.lineageId as string)) return false; nodes.set(node.lineageId as string, node); return true; },
    updateSemanticNode: async (node: Record<string, unknown>) => { for (const [key, value] of nodes) if (value.id === node.id) nodes.set(key, { ...value, ...node }); },
  };
  return { store: full, nodes, relations, creates: () => creates };
}

test("a typed hashtag becomes the name part of the key: case folded, spaces and other characters one hyphen", () => {
  assert.equal(conceptSlug("#Fake Website  Networks"), "fake-website-networks");
  assert.equal(conceptSlug("  #fake_website/networks! "), "fake-website-networks");
  assert.equal(conceptSlug("#"), "");
});

test("typing a new hashtag makes the concept with its name, the editor concept kind, who made it and when, and a confirmed human link", async () => {
  const world = conceptStore();
  const result = await createReferenceLink(world.store, { subjectLineageId: vectors.references[0], objectKind: "semanticNode", objectLineageId: "ignored", predicate: "related_to", newConceptName: "Fake Website Networks", callerSub: "editor-1", now: "2026-11-02T12:00:00Z" });
  const lineage = editorConceptLineageId("fake-website-networks");
  const node = world.nodes.get(lineage);
  assert.deepEqual({ kind: node.nodeKind, key: node.nodeKey, name: node.displayName, status: node.status, by: node.versionCreatedBy, at: node.versionCreatedAt, description: node.description ?? null },
    { kind: EDITOR_CONCEPT_KIND, key: "editor_concept--fake-website-networks", name: "fake website networks", status: "accepted", by: "editor-1", at: "2026-11-02T12:00:00Z", description: null });
  const [row] = [...world.relations.values()];
  const metadata = JSON.parse(row.metadata as string);
  assert.equal(result.outcome, "created");
  assert.deepEqual({ state: row.relationState, predicate: row.predicate, object: row.objectLineageId, provenance: metadata.provenance, by: metadata.addedBy, decision: metadata.decision }, { state: "current", predicate: "tagged_with", object: lineage, provenance: "human", by: "editor-1", decision: "accepted" });
});

test("a client that still sends related_to for a concept writes the same tagged_with row, and a legacy row for the pair is updated in place", async () => {
  const world = conceptStore();
  const base = { subjectLineageId: vectors.references[0], objectKind: "semanticNode", objectLineageId: vectors.node.lineageId, callerSub: "editor-1", now: "2026-11-02T12:00:00Z" };
  world.nodes.set(vectors.node.lineageId, vectors.node);
  const made = await createReferenceLink(world.store, { ...base, predicate: "related_to" });
  assert.equal(world.relations.get(made.relationId)?.predicate, "tagged_with");
  assert.equal(made.relationId, referenceLinkRelationId("tagged_with", vectors.references[0], vectors.node.lineageId));
  await assert.rejects(createReferenceLink(world.store, { ...base, objectKind: "reference", objectLineageId: vectors.references[1], predicate: "tagged_with" }), /tags a Reference with a concept/);
  const legacy = conceptStore();
  legacy.nodes.set(vectors.node.lineageId, vectors.node);
  const legacyId = referenceLinkRelationId("related_to", vectors.references[0], vectors.node.lineageId);
  legacy.relations.set(legacyId, { id: legacyId, predicate: "related_to", relationState: "suggested", metadata: JSON.stringify({ kind: "reference.concept", provenance: "suggested" }) } as ReferenceLinkRow);
  const kept = await createReferenceLink(legacy.store, { ...base, predicate: "tagged_with" });
  assert.equal(kept.relationId, legacyId);
  assert.equal(legacy.relations.size, 1);
});

test("a double tap, or the same name typed later, makes one concept and one link", async () => {
  const world = conceptStore();
  const input = { subjectLineageId: vectors.references[0], objectKind: "semanticNode", objectLineageId: "x", predicate: "related_to", newConceptName: "#fake-website-networks", callerSub: "editor-1", now: "2026-11-02T12:00:00Z" };
  await createReferenceLink(world.store, input);
  await createReferenceLink(world.store, { ...input, newConceptName: "FAKE website NETWORKS" });
  assert.equal(world.nodes.size, 1);
  assert.equal(world.relations.size, 1);
});

test("only a concept an editor made can be described, and the words are kept with who wrote them", async () => {
  const world = conceptStore();
  await ensureEditorConcept(world.store, "fake website networks", "editor-1", "2026-11-02T12:00:00Z");
  const lineage = editorConceptLineageId("fake-website-networks");
  const done = await describeEditorConcept(world.store, { lineageId: lineage, description: "  Sites made to look like news.  ", callerSub: "editor-2", now: "2026-11-02T13:00:00Z" });
  assert.equal(done.description, "Sites made to look like news.");
  assert.equal(world.nodes.get(lineage).versionCreatedBy, "editor-2");
  world.nodes.set("semantic-node-generated", { id: "semantic-node-generated-v1", lineageId: "semantic-node-generated", nodeKind: "model" });
  await assert.rejects(describeEditorConcept(world.store, { lineageId: "semantic-node-generated", description: "x", callerSub: "editor-2", now: "2026-11-02T13:00:00Z" }), /Only a concept an editor made/);
});

// --- the concept the command line makes must be the concept the hashtag box makes ----------------------------------------------------------------
type EditorConceptCase = { name: string; actor: string; now: string; slug: string; node: Record<string, unknown> | null };
const editorConceptVectors: { cases: EditorConceptCase[] } = JSON.parse(readFileSync("scripts/fixtures/editor-concept-vectors.json", "utf8"));

for (const vector of editorConceptVectors.cases) {
  test(`byte-compatible with the Python editor concept writer: ${vector.name.slice(0, 40)}`, async () => {
    assert.equal(conceptSlug(vector.name), vector.slug);
    const world = conceptStore();
    if (vector.node === null) {
      await assert.rejects(ensureEditorConcept(world.store, vector.name, vector.actor, vector.now), /needs a name/);
      return;
    }
    await ensureEditorConcept(world.store, vector.name, vector.actor, vector.now);
    assert.deepEqual(world.nodes.get(vector.node.lineageId as string), vector.node);
  });
}
