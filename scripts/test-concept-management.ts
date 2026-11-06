import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  CONCEPT_LINK_KIND, createConceptLink, decideReferenceLink, describeEditorConcept, ensureEditorConcept, referenceLinkRelationId,
  type ReferenceLinkRow, type ReferenceLinkStore, type SemanticNodeRecord,
} from "../amplify/functions/category-action/reference-links";
import {
  applyKnowledgeReview, decodeReviewMarks, encodeReviewMarks, REVIEW_MARKER, stampedChangeReason, type KnowledgeReviewStore,
} from "../amplify/functions/category-action/knowledge-review";
import { editOriginOfIdentity } from "../amplify/functions/shared/edit-origin";
import { explanationByline, linkExplanationOf } from "../lib/reference-links";

const NOW = "2026-11-05T12:00:00Z";
const CLI_CLIENT = "cli-client-id";
const identity = (client: string, groups: string[] = ["editor"]) => ({ claims: { sub: "sub-1", aud: client, "cognito:groups": groups } });

function nodeRow(slug: string, extra: Record<string, unknown> = {}): SemanticNodeRecord & Record<string, unknown> {
  return {
    id: `semantic-node-editor_concept--${slug}-v1`, lineageId: `semantic-node-editor_concept--${slug}`, versionNumber: 1, versionState: "current",
    nodeKey: `editor_concept--${slug}`, nodeKind: "editor_concept", displayName: slug.replace(/-/g, " "), status: "accepted", aliases: [], ...extra,
  };
}

function conceptStore(nodes: Array<SemanticNodeRecord & Record<string, unknown>>) {
  const relations = new Map<string, ReferenceLinkRow>();
  const created: Array<Record<string, unknown>> = [];
  const updated: Array<Record<string, unknown>> = [];
  const store: ReferenceLinkStore & { updateSemanticNode(node: Record<string, unknown>): Promise<void> } = {
    getCurrentReference: async () => null,
    getSemanticNode: async (id) => nodes.find((node) => node.id === id || node.lineageId === id) ?? null,
    createSemanticNode: async (node) => {
      created.push(node);
      nodes.push(node as never);
      return true;
    },
    updateSemanticNode: async (node) => {
      updated.push(node);
    },
    getRelation: async (id) => relations.get(id) ?? null,
    putRelation: async (relation) => {
      relations.set(relation.id as string, { ...(relations.get(relation.id as string) ?? {}), ...relation } as ReferenceLinkRow);
    },
  };
  return { store, relations, created, updated };
}

const metadataOf = (row: ReferenceLinkRow) => JSON.parse(row.metadata as string) as Record<string, unknown>;

// --- 2. the name a person typed ---------------------------------------------------------------------------------------------

test("a concept keeps the capitalisation the person typed, and the key is still its lower-case slug", async () => {
  const { store, created } = conceptStore([]);
  const node = await ensureEditorConcept(store, "Information flow control", "sub-1", NOW, { displayName: "Information flow control", origin: "cli" });
  assert.equal(node.nodeKey, "editor_concept--information-flow-control");
  assert.equal((created[0] as { displayName: string }).displayName, "Information flow control");
  assert.equal((created[0] as { changeReason: string }).changeReason, "Invented by an editor with a hashtag (via cli)");
  const hyphen = await ensureEditorConcept(store, "Non-interference", "sub-1", NOW, { displayName: "Non-interference", origin: "cli" });
  assert.equal((hyphen as { displayName?: string }).displayName ?? (created[1] as { displayName: string }).displayName, "Non-interference");
});

test("without a name the concept reads as it always has, and a Newsroom origin leaves the reason as it was", async () => {
  const { store, created } = conceptStore([]);
  await ensureEditorConcept(store, "#Fake Website Networks", "sub-1", NOW, { origin: "newsroom" });
  assert.equal((created[0] as { displayName: string }).displayName, "fake website networks");
  assert.equal((created[0] as { changeReason: string }).changeReason, "Invented by an editor with a hashtag");
});

test("a name that is not the same words as the key is refused", async () => {
  const { store, created } = conceptStore([]);
  await assert.rejects(ensureEditorConcept(store, "Containment", "sub-1", NOW, { displayName: "Something else" }), /not the same words/);
  assert.equal(created.length, 0);
});

// --- 6. a link between two concepts ----------------------------------------------------------------------------------------

test("two concepts are linked with related_to, one row with the lower lineage id first, and the explanation is on it", async () => {
  const { store, relations } = conceptStore([nodeRow("containment"), nodeRow("confinement-problem")]);
  const made = await createConceptLink(store, {
    subjectLineageId: "semantic-node-editor_concept--containment", objectLineageId: "semantic-node-editor_concept--confinement-problem",
    note: "  Two sides of the same fence.  ", callerSub: "sub-1", now: NOW, origin: "cli",
  });
  assert.deepEqual([made.ok, made.outcome, made.relationState], [true, "created", "current"]);
  const row = relations.get(made.relationId)!;
  assert.equal(row.score, 1, "score sorts two indexes, so a null is refused by DynamoDB");
  assert.equal(row.predicate, "related_to");
  assert.equal(row.subjectKind, "semanticNode");
  assert.equal(row.objectKind, "semanticNode");
  assert.equal(row.subjectLineageId, "semantic-node-editor_concept--confinement-problem");
  assert.equal(row.objectLineageId, "semantic-node-editor_concept--containment");
  assert.equal(row.relationState, "current");
  assert.equal(row.newsroomFeedKey, "reference-links");
  assert.equal(row.subjectStateKey, "semanticNode#semantic-node-editor_concept--confinement-problem#current");
  assert.deepEqual(
    { kind: metadataOf(row).kind, provenance: metadataOf(row).provenance, note: metadataOf(row).note, decision: metadataOf(row).decision, decidedBy: metadataOf(row).decidedBy, addedBy: metadataOf(row).addedBy, confirmed: metadataOf(row).confirmed },
    { kind: CONCEPT_LINK_KIND, provenance: "human", note: "Two sides of the same fence.", decision: "accepted", decidedBy: "sub-1", addedBy: "sub-1", confirmed: true },
  );
  assert.deepEqual([metadataOf(row).addedVia, metadataOf(row).decidedVia], ["cli", "cli"]);
});

test("the row is the one the Python readers are tested against (scripts/fixtures/concept-link-row-vector.json)", async () => {
  const vector = JSON.parse(readFileSync("scripts/fixtures/concept-link-row-vector.json", "utf8"));
  const { store, relations } = conceptStore(vector.nodes);
  const result = await createConceptLink(store, vector.input);
  assert.deepEqual(result, vector.result);
  const row = relations.get(result.relationId)!;
  assert.deepEqual({ ...row, metadata: metadataOf(row) }, vector.row);
});

test("the same pair in the other order is the same link, and new words replace the old", async () => {
  const { store, relations } = conceptStore([nodeRow("containment"), nodeRow("confinement-problem")]);
  const first = await createConceptLink(store, { subjectLineageId: "semantic-node-editor_concept--containment", objectLineageId: "semantic-node-editor_concept--confinement-problem", note: "first words", callerSub: "sub-1", now: NOW, origin: "cli" });
  const second = await createConceptLink(store, { subjectLineageId: "semantic-node-editor_concept--confinement-problem", objectLineageId: "semantic-node-editor_concept--containment", note: "better words", callerSub: "sub-2", now: NOW, origin: "newsroom" });
  assert.deepEqual([first.outcome, second.outcome, relations.size, second.relationId], ["created", "updated", 1, first.relationId]);
  const meta = metadataOf(relations.get(first.relationId)!);
  assert.equal(meta.note, "better words");
  assert.equal(meta.addedBy, "sub-1");
  assert.equal(meta.addedVia, "cli");   // who made it first, and where, is not rewritten by a later edit
});

test("a link between concepts without its explanation, to itself, to a rejected or to a missing concept is refused in words", async () => {
  const { store, relations } = conceptStore([nodeRow("containment"), nodeRow("confinement-problem"), nodeRow("spam", { status: "rejected" })]);
  const base = { subjectLineageId: "semantic-node-editor_concept--containment", objectLineageId: "semantic-node-editor_concept--confinement-problem", callerSub: "sub-1", now: NOW };
  await assert.rejects(createConceptLink(store, { ...base, note: "   " }), /needs its explanation/);
  await assert.rejects(createConceptLink(store, { ...base, note: null }), /needs its explanation/);
  await assert.rejects(createConceptLink(store, { ...base, objectLineageId: base.subjectLineageId, note: "x" }), /cannot be linked to itself/);
  await assert.rejects(createConceptLink(store, { ...base, objectLineageId: "semantic-node-editor_concept--spam", note: "x" }), /was rejected/);
  await assert.rejects(createConceptLink(store, { ...base, objectLineageId: "semantic-node-editor_concept--nope", note: "x" }), /Concept not found/);
  assert.equal(relations.size, 0);
});

test("a concept link can be decided like any other link, and the decision says where it was made", async () => {
  const { store, relations } = conceptStore([nodeRow("containment"), nodeRow("confinement-problem")]);
  const made = await createConceptLink(store, { subjectLineageId: "semantic-node-editor_concept--containment", objectLineageId: "semantic-node-editor_concept--confinement-problem", note: "w", callerSub: "sub-1", now: NOW, origin: "newsroom" });
  const rejected = await decideReferenceLink(store, { relationId: made.relationId, decision: "reject", reasonCode: "wrong", note: "no", callerSub: "sub-2", now: NOW, origin: "cli" });
  assert.deepEqual([rejected.relationState, rejected.decision], ["rejected", "rejected"]);
  const meta = metadataOf(relations.get(made.relationId)!);
  assert.deepEqual([meta.decidedBy, meta.decidedVia, meta.addedVia], ["sub-2", "cli", "newsroom"]);
  assert.equal(referenceLinkRelationId("related_to", "a", "b").startsWith("reference-link-related_to-"), true);
});

// --- 4. a description nobody has accepted ----------------------------------------------------------------------------------

test("describing a concept anew keeps the other review marks and drops the acceptance of the description it replaces", async () => {
  const accepted = encodeReviewMarks({ acceptedBy: { actor: "human", name: null, on: "2026-11-01" }, descriptionEditedBy: { actor: "human", name: null, on: "2026-11-01", via: "cli" }, rejectedBy: null });
  const { store, updated } = conceptStore([nodeRow("containment", { changeReason: accepted, description: "old" })]);
  await describeEditorConcept(store, { lineageId: "semantic-node-editor_concept--containment", description: "New words.", callerSub: "sub-1", now: NOW, origin: "cli" });
  const marks = decodeReviewMarks((updated[0] as { changeReason: string }).changeReason);
  assert.equal(marks.descriptionEditedBy, null);
  assert.deepEqual(marks.acceptedBy, { actor: "human", name: null, on: "2026-11-01" });
  const plain = conceptStore([nodeRow("containment")]);
  await describeEditorConcept(plain.store, { lineageId: "semantic-node-editor_concept--containment", description: "New words.", callerSub: "sub-1", now: NOW, origin: "cli" });
  assert.equal((plain.updated[0] as { changeReason: string }).changeReason, "Described by an editor (via cli)");
});

// --- 3. the review patches --------------------------------------------------------------------------------------------------

function reviewStore(node: Record<string, unknown>, relation?: Record<string, unknown>) {
  const nodes = new Map<string, Record<string, unknown>>([[node.id as string, { ...node }]]);
  const relations = new Map<string, Record<string, unknown>>(relation ? [[relation.id as string, { ...relation }]] : []);
  const writes: Array<[string, Record<string, unknown>]> = [];
  const store: KnowledgeReviewStore = {
    getNode: async (id) => (nodes.get(id) as never) ?? null,
    updateNode: async (patch) => {
      writes.push(["node", patch]);
      nodes.set(patch.id as string, { ...nodes.get(patch.id as string), ...patch });
    },
    getRelation: async (id) => (relations.get(id) as never) ?? null,
    updateRelation: async (patch) => {
      writes.push(["relation", patch]);
    },
  };
  return { store, nodes, writes };
}

const person = { actor: "human", name: "Ryan", on: "2026-11-05" };
const node = nodeRow("containment");

test("a rename and an alias are written, and the node keeps its key", async () => {
  const { store, nodes, writes } = reviewStore(node);
  const answer = await applyKnowledgeReview(store, {
    origin: "cli",
    patches: [
      { modelName: "SemanticNode", expected: { id: node.id, displayName: "Containment", aliases: ["containment"], updatedAt: NOW } },
      { modelName: "SemanticNode", expected: { id: node.id, aliases: ["containment", "boxing"], changeReason: encodeReviewMarks({ acceptedBy: null, descriptionEditedBy: null, rejectedBy: null, aliasedBy: person }), updatedAt: NOW } },
    ],
  });
  assert.deepEqual(answer, { ok: true, applied: 2, origin: "cli" });
  assert.equal(writes.length, 2);
  assert.equal(nodes.get(node.id)!.displayName, "Containment");
  assert.equal(nodes.get(node.id)!.nodeKey, "editor_concept--containment");
  assert.deepEqual(decodeReviewMarks(nodes.get(node.id)!.changeReason).aliasedBy, { ...person, via: "cli" });
});

test("an editor's page decision is stamped as made through the CLI, keeps the other marks, and handing it back removes it", () => {
  const stored = encodeReviewMarks({ acceptedBy: person, descriptionEditedBy: null, rejectedBy: null });
  const taken = encodeReviewMarks({ acceptedBy: person, descriptionEditedBy: null, rejectedBy: null, pageTakenBy: person });
  const written = stampedChangeReason(taken, stored, "cli");
  const marks = decodeReviewMarks(written);
  assert.deepEqual(marks.pageTakenBy, { ...person, via: "cli" });
  assert.deepEqual(marks.acceptedBy, person);
  const back = decodeReviewMarks(stampedChangeReason(stored, written, "cli"));
  assert.equal(back.pageTakenBy, undefined);
  assert.equal(back.pageGivenBy, undefined);
});

test("a person's accept from the CLI is stamped as made through the CLI, whatever the call says, and an earlier stamp is kept", () => {
  const forged = encodeReviewMarks({ acceptedBy: { ...person, via: "newsroom" }, descriptionEditedBy: null, rejectedBy: null });
  assert.deepEqual(decodeReviewMarks(stampedChangeReason(forged, undefined, "cli")).acceptedBy, { ...person, via: "cli" });
  const stored = encodeReviewMarks({ acceptedBy: { ...person, via: "newsroom" }, descriptionEditedBy: null, rejectedBy: null });
  const again = encodeReviewMarks({ acceptedBy: person, descriptionEditedBy: { actor: "human", name: "Ryan", on: "2026-11-05" }, rejectedBy: null });
  const marks = decodeReviewMarks(stampedChangeReason(again, stored, "cli"));
  assert.deepEqual(marks.acceptedBy, { ...person, via: "newsroom" });   // unchanged: it was made in the Newsroom and still says so
  assert.deepEqual(marks.descriptionEditedBy, { ...person, via: "cli" });   // new in this call: made through the CLI
});

test("a review may not change what it does not review, and nothing is written when one change is refused", async () => {
  const link = { id: "rel-1", metadata: JSON.stringify({ kind: "reference.link", decision: "accepted", decidedBy: "sub-9", confirmed: false }) };
  const refused: Array<[unknown, RegExp]> = [
    [{ modelName: "SemanticNode", expected: { id: node.id, nodeKind: "person" } }, /does not change nodeKind/],
    [{ modelName: "SemanticNode", expected: { id: node.id, nodeKey: "x--y" } }, /does not change nodeKey/],
    [{ modelName: "SemanticNode", expected: { id: node.id, status: "deleted" } }, /status must be one of/],
    [{ modelName: "SemanticNode", expected: { id: node.id, changeReason: "free text" } }, /review marks/],
    [{ modelName: "SemanticNode", expected: { id: node.id, changeReason: encodeReviewMarks({ madeUpBy: person }) } }, /madeUpBy/],
    [{ modelName: "SemanticNode", expected: { id: node.id, changeReason: encodeReviewMarks({ acceptedBy: { actor: "robot", on: "2026-11-05" } }) } }, /not a reviewer/],
    [{ modelName: "SemanticNode", expected: { id: node.id, aliases: ["someone@example.test"] } }, /email address/],
    [{ modelName: "SemanticNode", expected: { id: node.id, displayName: "   " } }, /must be words/],
    [{ modelName: "SemanticNode", expected: { id: "no-such-node", displayName: "X" } }, /No SemanticNode/],
    [{ modelName: "Reference", expected: { id: "r", title: "x" } }, /not Reference/],
    [{ modelName: "SemanticRelation", expected: { id: "rel-1", predicate: "cites" } }, /does not change predicate/],
    [{ modelName: "SemanticRelation", expected: { id: "rel-1", metadata: JSON.stringify({ kind: "reference.link", decision: "rejected", decidedBy: "sub-9" }) } }, /does not change decision/],
    [{ modelName: "SemanticRelation", expected: { id: "no-such", metadata: "{}" } }, /No SemanticRelation/],
  ];
  for (const [patch, message] of refused) {
    const { store, writes } = reviewStore(node, link);
    await assert.rejects(applyKnowledgeReview(store, { origin: "cli", patches: [{ modelName: "SemanticNode", expected: { id: node.id, displayName: "Fine" } }, patch] }), message);
    assert.equal(writes.length, 0, `nothing written when ${JSON.stringify(patch)} is refused`);
  }
  const { store } = reviewStore(node);
  await assert.rejects(applyKnowledgeReview(store, { origin: "cli", patches: [] }), /nothing to apply/);
  await assert.rejects(applyKnowledgeReview(store, { origin: "cli", patches: Array.from({ length: 201 }, () => ({})) }), /at most 200/);
});

test("accepting an entity confirms its mention links, and an older version of a node is not reviewed", async () => {
  const link = { id: "rel-2", metadata: JSON.stringify({ kind: "reference.mention", confirmed: false }) };
  const { store, writes } = reviewStore(node, link);
  await applyKnowledgeReview(store, { origin: "cli", patches: [{ modelName: "SemanticRelation", expected: { id: "rel-2", metadata: JSON.stringify({ kind: "reference.mention", confirmed: true, confirmedBy: person }), updatedAt: NOW } }] });
  assert.equal(JSON.parse(writes[0][1].metadata as string).confirmed, true);
  const old = reviewStore({ ...node, versionState: "superseded" });
  await assert.rejects(applyKnowledgeReview(old.store, { origin: "cli", patches: [{ modelName: "SemanticNode", expected: { id: node.id, displayName: "X" } }] }), /not the current version/);
});

// --- honest labelling -------------------------------------------------------------------------------------------------------

test("where a decision was made comes from the token's client, never from the request", () => {
  const clients = { web: "web-client", cli: CLI_CLIENT, mcp: "mcp-client" };
  assert.equal(editOriginOfIdentity(identity(CLI_CLIENT), clients), "cli");
  assert.equal(editOriginOfIdentity(identity("web-client"), clients), "newsroom");
  assert.equal(editOriginOfIdentity(identity("other-client"), clients), "signed-in");
  assert.equal(editOriginOfIdentity(identity("web-client"), { ...clients, cli: null }), "signed-in");
  assert.equal(editOriginOfIdentity({ userArn: "arn:aws:sts::123:assumed-role/x/y", accountId: "123" }, clients), "operator");
  assert.equal(editOriginOfIdentity({ claims: {} }, clients), "signed-in");
  assert.equal(editOriginOfIdentity(undefined, clients), "signed-in");
  assert.equal(editOriginOfIdentity({ claims: { sub: "sub-1", "cognito:groups": ["editor"] } }, clients), "signed-in");
});

test("the console says when the words were written through the CLI, and says nothing new about the others", () => {
  const row = (extra: Record<string, unknown>) => ({ relationState: "current", metadata: JSON.stringify({ decision: "accepted", decidedBy: "sub-1", decidedAt: "2026-11-05T12:00:00Z", note: "Why", ...extra }) });
  assert.equal(explanationByline(linkExplanationOf(row({ decidedVia: "cli" }))!), "Written by an editor on 2026-11-05 through the CLI");
  assert.equal(explanationByline(linkExplanationOf(row({ decidedVia: "newsroom" }))!), "Written by an editor on 2026-11-05");
  assert.equal(explanationByline(linkExplanationOf(row({}))!), "Written by an editor on 2026-11-05");
});

// --- the schema -------------------------------------------------------------------------------------------------------------

for (const file of ["amplify/data/resource.ts", "amplify/data/schema.ts"]) {
  test(`${file}: the new routes are for the editor and admin groups only, and the data models stay read-only to them`, () => {
    const source = readFileSync(file, "utf8");
    for (const name of ["createConceptLink", "applyKnowledgeReview", "createEditorConcept"]) {
      const start = source.indexOf(`  ${name}: a`);
      assert.ok(start > 0, `${name} is declared`);
      const block = source.slice(start, source.indexOf(".handler(", start));
      assert.match(block, /allow\.groups\(categoryWriteGroups\)/);
      assert.doesNotMatch(block, /allow\.(authenticated|guest|publicApiKey|owner)/);
    }
    assert.match(source, /createEditorConcept: a\s+\.mutation\(\)\s+\.arguments\(\{ name: a\.string\(\)\.required\(\), displayName: a\.string\(\) \}\)/);
    assert.match(source, /createConceptLink: a[\s\S]*?note: a\.string\(\)\.required\(\)/);
    if (file.endsWith("resource.ts")) {
      const start = source.indexOf("  SemanticNode: a\n");
      const rules = source.slice(source.indexOf(".authorization(", start), source.indexOf("\n    ]),", source.indexOf(".authorization(", start)));
      assert.match(rules, /allow\.groups\(categoryWriteGroups\)\.to\(\["read"\]\)/);
      assert.doesNotMatch(rules, /create|update|delete/);
    }
  });
}

test("the handler checks the editor groups again on the two routes that write the graph", () => {
  const source = readFileSync("amplify/functions/category-action/handler.ts", "utf8");
  assert.match(source, /async function createConceptLinkAction[\s\S]*?requireEditorGroups\(event, "link concepts"\)/);
  assert.match(source, /async function applyKnowledgeReviewAction[\s\S]*?requireEditorGroups\(event, "review knowledge"\)/);
  assert.match(source, /fieldName === "createConceptLink"/);
  assert.match(source, /fieldName === "applyKnowledgeReview"/);
  assert.equal(REVIEW_MARKER, "papyrus-knowledge-review@1:");
});
