import assert from "node:assert/strict";
import { test } from "node:test";
import { hashtagsInMessageText } from "../lib/message-hashtags";
import { messageHasHashtag } from "../lib/post-message";
import { linkMessageHashtags, messageConceptRelationId, type MessageHashtagStore } from "../amplify/functions/category-action/message-hashtags";

const NOW = "2026-11-01T12:00:00Z";
const nodes = [
  { id: "n-voice-v2", lineageId: "n-voice", versionNumber: 2, nodeKey: "concept--voice-cloning" },
  { id: "n-task-translation", nodeKey: "task--translation" },
  { id: "n-concept-translation", nodeKey: "concept--translation" },
];

function fakeStore(message: Record<string, unknown> | null) {
  const relations = new Map<string, Record<string, unknown>>();
  const state = { message, metadataWrites: [] as Array<Record<string, unknown>> };
  const store: MessageHashtagStore = {
    getMessage: async () => (state.message as never),
    listAcceptedConceptNodes: async () => nodes,
    getRelation: async (id) => (relations.get(id) as never) ?? null,
    putRelation: async (relation) => void relations.set(relation.id as string, relation),
    setMessageMetadata: async (_id, metadata) => void state.metadataWrites.push(metadata),
  };
  return { store, relations, state };
}
const person = (content: string, extra: Record<string, unknown> = {}) => ({ id: "m1", content, authorSub: "sub-1", role: "human", status: "active", ...extra });

test("hashtags are read from the text the way people type them", () => {
  assert.deepEqual(hashtagsInMessageText("Look at #Voice-Cloning and #voice-cloning, then #translation."), ["voice-cloning", "translation"]);
  assert.deepEqual(hashtagsInMessageText("see https://example.com/page#section and a&#38; or ## and # alone"), []);
  assert.equal(messageHasHashtag("a #b"), true);
  assert.equal(messageHasHashtag("no tag"), false);
});

test("a matching hashtag becomes a current human related-to edge from the message to the concept", async () => {
  const { store, relations } = fakeStore(person("Thoughts on #voice-cloning"));
  const result = await linkMessageHashtags(store, { messageId: "m1", callerSub: "sub-1", now: NOW });
  assert.deepEqual(result, { ok: true, linkedNodeKeys: ["concept--voice-cloning"], unmatchedHashtags: [] });
  const row = relations.get(messageConceptRelationId("m1", "n-voice")) as Record<string, unknown>;
  assert.equal(row.predicate, "related_to");
  assert.equal(row.relationState, "current");
  assert.equal(row.subjectKind, "message");
  assert.equal(row.objectKind, "semanticNode");
  assert.equal(row.objectLineageId, "n-voice");
  assert.deepEqual(JSON.parse(row.metadata as string), { kind: "message.concept", provenance: "human", addedBy: "sub-1", addedAt: NOW });
});

test("an unknown or ambiguous hashtag is listed on the message and creates no concept or edge", async () => {
  const { store, relations, state } = fakeStore(person("#brand-new-idea and #translation"));
  const result = await linkMessageHashtags(store, { messageId: "m1", callerSub: "sub-1", now: NOW });
  assert.deepEqual(result.unmatchedHashtags, ["#brand-new-idea", "#translation"]);
  assert.equal(relations.size, 0);
  assert.deepEqual(state.metadataWrites, [{ unmatchedHashtags: ["#brand-new-idea", "#translation"] }]);
});

test("running twice leaves one edge and keeps who added it first", async () => {
  const { store, relations } = fakeStore(person("#voice-cloning"));
  await linkMessageHashtags(store, { messageId: "m1", callerSub: "sub-1", now: NOW });
  await linkMessageHashtags(store, { messageId: "m1", callerSub: "sub-1", now: "2026-11-02T00:00:00Z" });
  assert.equal(relations.size, 1);
  assert.equal(JSON.parse([...relations.values()][0].metadata as string).addedAt, NOW);
});

test("only the author's own person-written message is linked", async () => {
  const other = fakeStore(person("#voice-cloning"));
  await assert.rejects(linkMessageHashtags(other.store, { messageId: "m1", callerSub: "someone-else", now: NOW }), /Only the author/);
  const machine = fakeStore(person("#voice-cloning", { role: "assistant" }));
  assert.deepEqual(await linkMessageHashtags(machine.store, { messageId: "m1", callerSub: "sub-1", now: NOW }), { ok: true, linkedNodeKeys: [], unmatchedHashtags: [] });
  assert.equal(machine.relations.size, 0);
});

test("the relation id matches the Python writer's", () => {
  assert.equal(messageConceptRelationId("m1", "n-voice"), "reference-link-related_to-" + require("node:crypto").createHash("sha256").update('["m1","n-voice"]').digest("hex").slice(0, 16));
});
