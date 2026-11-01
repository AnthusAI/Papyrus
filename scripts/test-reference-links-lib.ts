import assert from "node:assert/strict";
import test from "node:test";
import { classifyAddInput, closeMatchText, editorLinkedReferenceLineages, publishedAddedText, relatedEdgeWords, relatedEntriesFromRelations, symmetricSubjectFirst, type RelatedItem } from "../lib/reference-links";

const item = (kind: "concept" | "reference", lineageId: string): RelatedItem => ({ kind, lineageId, title: lineageId, hashtag: null, nodeKey: null, nodeKind: null, host: null, sourceUri: null, sourcePublishedAt: null, addedAt: null });

test("Both dates always show, and an unknown publication date says so", () => {
  assert.equal(publishedAddedText("2026-10-27T09:00:00Z", "2026-10-28T08:15:00Z"), "published 2026-10-27 · added 2026-10-28");
  assert.equal(publishedAddedText(null, "2026-10-28T08:15:00Z"), "published unknown · added 2026-10-28");
});

test("The Add box tells a hashtag from a link from a title", () => {
  assert.deepEqual(classifyAddInput("  #voice"), { mode: "concept", query: "voice" });
  assert.equal(classifyAddInput("https://example.org/a").mode, "link");
  assert.equal(classifyAddInput("harbour dredging").mode, "title");
  assert.equal(classifyAddInput("   ").mode, "none");
});

test("Rows are read from both ends, rejected rows are left out, and the match is words", () => {
  const rows = [
    { id: "a", relationState: "current", predicate: "related_to", subjectKind: "reference", subjectLineageId: "me", objectKind: "semanticNode", objectLineageId: "c1", metadata: JSON.stringify({ provenance: "human" }) },
    { id: "b", relationState: "suggested", predicate: "related_to", subjectKind: "reference", subjectLineageId: "other", objectKind: "reference", objectLineageId: "me", score: 0.8123 },
    { id: "c", relationState: "rejected", predicate: "related_to", subjectKind: "reference", subjectLineageId: "me", objectKind: "reference", objectLineageId: "z" },
    { id: "d", relationState: "current", predicate: "cites", subjectKind: "reference", subjectLineageId: "me", objectKind: "reference", objectLineageId: "q" },
  ];
  const entries = relatedEntriesFromRelations({ referenceLineageId: "me", relations: rows, resolve: (kind, id) => (id === "z" ? null : item(kind, id)) });
  assert.deepEqual(entries.map(entry => [entry.relationId, entry.state, entry.direction, entry.item.kind]), [["a", "current", "outgoing", "concept"], ["b", "suggested", "incoming", "reference"], ["d", "current", "outgoing", "reference"]]);
  assert.equal(closeMatchText(entries[1].similarity), "close match 0.81");
  assert.equal(relatedEdgeWords("cites", "incoming"), "cited by");
});

test("Linked by editors keeps only current human related_to rows from References", () => {
  const rows = [
    { id: "a", relationState: "current", predicate: "related_to", subjectKind: "reference", subjectLineageId: "r1", objectKind: "semanticNode", objectLineageId: "c", metadata: { provenance: "human" } },
    { id: "b", relationState: "current", predicate: "mentions", subjectKind: "reference", subjectLineageId: "r2", objectKind: "semanticNode", objectLineageId: "c" },
    { id: "c", relationState: "current", predicate: "related_to", subjectKind: "reference", subjectLineageId: "r3", objectKind: "semanticNode", objectLineageId: "c", metadata: { provenance: "suggested" } },
  ];
  assert.deepEqual(editorLinkedReferenceLineages("c", rows), [{ relationId: "a", lineageId: "r1" }]);
  assert.deepEqual(symmetricSubjectFirst("b", "a"), ["a", "b"]);
});
