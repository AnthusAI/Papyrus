import assert from "node:assert/strict";
import test from "node:test";
import { classifyAddInput, closeMatchText, editorLinkedReferenceLineages, explanationByline, linkExplanationOf, publishedAddedText, relatedEdgeWords, relatedEntriesFromRelations, suggestFailureText, suggestSkippedText, symmetricSubjectFirst, type RelatedItem } from "../lib/reference-links";
import { isOpenSuggestion } from "../lib/link-suggestions";

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
  assert.deepEqual(editorLinkedReferenceLineages("c", rows), [{ relationId: "a", lineageId: "r1", explanation: null }]);
  assert.deepEqual(symmetricSubjectFirst("b", "a"), ["a", "b"]);
});

test("Linked by editors reads the tagged_with tag as well as the older related_to", () => {
  const rows = [
    { id: "t", relationState: "current", predicate: "tagged_with", subjectKind: "reference", subjectLineageId: "r1", objectKind: "semanticNode", objectLineageId: "c", metadata: { provenance: "human" } },
    { id: "o", relationState: "current", predicate: "related_to", subjectKind: "reference", subjectLineageId: "r2", objectKind: "semanticNode", objectLineageId: "c", metadata: { provenance: "human" } },
  ];
  assert.deepEqual(editorLinkedReferenceLineages("c", rows).map(found => found.relationId), ["t", "o"]);
});

test("An open suggestion to a concept is a tagged_with row or the older related_to; tagged_with between two References is not a suggestion", () => {
  const row = (predicate: string, objectKind: string) => ({ relationState: "suggested", predicate, subjectKind: "reference", objectKind });
  assert.equal(isOpenSuggestion(row("tagged_with", "semanticNode")), true);
  assert.equal(isOpenSuggestion(row("related_to", "semanticNode")), true);
  assert.equal(isOpenSuggestion(row("related_to", "reference")), true);
  assert.equal(isOpenSuggestion(row("tagged_with", "reference")), false);
  assert.equal(relatedEdgeWords("tagged_with", "outgoing"), "relates to");
});

test("A skip reason from the backend is shown in plain words, and an unknown one never leaks", () => {
  assert.equal(suggestSkippedText("no reference_summary vector is indexed for this Reference"), "Suggestions appear once this Reference has a summary.");
  assert.equal(suggestSkippedText("calibration_not_ready: kind=reference"), "No suggestions could be made for this Reference yet.");
  assert.equal(suggestSkippedText(null), "No suggestions could be made for this Reference yet.");
});

test("A failed Suggest more is plain: the missing knowledge index has its sentence, anything else is generic", () => {
  assert.equal(suggestFailureText(new Error("Suggestions need the knowledge index.")), "Suggestions need the knowledge index");
  assert.equal(suggestFailureText(new Error("GraphQL: Lambda:Unhandled at resolver suggestReferenceLinks")), "Suggestions could not be made right now. Try again in a moment.");
});

const link = (relationState: string, metadata: Record<string, unknown> | string) => ({ relationState, metadata });

test("An accepted or hand-made link carries the editor's words; a suggestion, a rejection, a machine link and blank words carry none", () => {
  const accepted = linkExplanationOf(link("current", { decision: "accepted", decidedBy: "sub-1", decidedAt: "2026-11-02T09:00:00Z", note: "  Both read the same filing.  " }));
  assert.deepEqual(accepted, { text: "Both read the same filing.", by: "editor", at: "2026-11-02" });
  assert.equal(explanationByline(accepted!), "Written by an editor on 2026-11-02");
  assert.deepEqual(linkExplanationOf(link("current", JSON.stringify({ provenance: "human", note: "By hand." }))), { text: "By hand.", by: "editor", at: null });
  assert.equal(explanationByline({ text: "x", by: "editor", at: null }), "Written by an editor");
  assert.equal(linkExplanationOf(link("suggested", { decision: "accepted", decidedBy: "sub-1", note: "Not yet decided." })), null);
  assert.equal(linkExplanationOf(link("rejected", { decision: "rejected", decidedBy: "sub-1", note: "Different harbour." })), null);
  assert.equal(linkExplanationOf(link("current", { decision: "accepted", decidedBy: "auto:vector", note: "A rule." })), null);
  assert.equal(linkExplanationOf(link("current", { decision: "accepted", decidedBy: "sub-1", note: "   " })), null);
  assert.equal(linkExplanationOf(link("current", "not json")), null);
});

test("Rows and the concept page's list carry the explanation of the link they came from", () => {
  const meta = { provenance: "human", decision: "accepted", decidedBy: "sub-1", decidedAt: "2026-11-01T00:00:00Z", note: "Same vendor." };
  const rows = [{ id: "a", relationState: "current", predicate: "related_to", subjectKind: "reference", subjectLineageId: "me", objectKind: "semanticNode", objectLineageId: "c1", metadata: meta }];
  const [entry] = relatedEntriesFromRelations({ referenceLineageId: "me", relations: rows, resolve: (kind, id) => item(kind, id) });
  assert.deepEqual(entry.explanation, { text: "Same vendor.", by: "editor", at: "2026-11-01" });
  assert.deepEqual(editorLinkedReferenceLineages("c1", rows), [{ relationId: "a", lineageId: "me", explanation: { text: "Same vendor.", by: "editor", at: "2026-11-01" } }]);
});
