import assert from "node:assert/strict";
import test from "node:test";
import {
  buildConversationTree,
  canDeleteMessage,
  canEditMessage,
  canRenameThread,
  messageAuthorName,
  conversationAnchorKey,
  conversationMessageId,
  conversationThreadId,
  conversationThreadKind,
  createWithSequenceRetry,
  findOrCreateThread,
  isSequenceConflict,
  messageCountLabel,
  nextConversationSequence,
  type ConversationMessage,
} from "../lib/conversation";

const message = (sequenceNumber: number, parentMessageId: string | null, authorLabel = "ada@example.test"): ConversationMessage => ({
  id: `m${sequenceNumber}`, parentMessageId, authorLabel, content: `text ${sequenceNumber}`, createdAt: `2026-10-29T10:0${sequenceNumber}:00Z`, sequenceNumber,
});

test("The anchor key names the thing the conversation is about", () => {
  assert.equal(conversationAnchorKey({ kind: "reference", lineageId: "ref-1" }), "reference#ref-1");
  assert.equal(conversationAnchorKey({ kind: "item", lineageId: " story-9 " }), "item#story-9");
  assert.equal(conversationAnchorKey({ kind: "none" }), null);
  assert.equal(conversationThreadKind({ kind: "reference", lineageId: "r" }), "reference_conversation");
  assert.equal(conversationThreadKind({ kind: "item", lineageId: "r" }), "story_conversation");
  assert.equal(conversationThreadKind({ kind: "none" }), "conversation");
  assert.equal(conversationThreadId({ kind: "reference", lineageId: "Ref 1" }), "message-thread-conversation-reference-ref-1");
  assert.throws(() => conversationThreadId({ kind: "none" }));
  assert.equal(conversationMessageId("message-thread-conversation-reference-ref-1", 7), "message-conversation-message-thread-conversation-reference-ref-1-0007");
});

test("The next sequence number is one past the highest in use", () => {
  assert.equal(nextConversationSequence([]), 1);
  assert.equal(nextConversationSequence([{ sequenceNumber: 1 }, { sequenceNumber: 4 }, { sequenceNumber: null }]), 5);
});

test("A refused duplicate id counts as a lost race", () => {
  assert.equal(isSequenceConflict(new Error("The conditional request failed")), true);
  assert.equal(isSequenceConflict([{ message: "ConditionalCheckFailedException" }]), true);
  assert.equal(isSequenceConflict(new Error("Not authorized")), false);
});

test("A create that loses the race for its sequence number retries with the next one", async () => {
  const stored = [{ sequenceNumber: 1 }, { sequenceNumber: 2 }];
  const tried: number[] = [];
  let racing = true;
  const result = await createWithSequenceRetry({
    list: async () => stored,
    create: async (sequenceNumber) => {
      tried.push(sequenceNumber);
      if (racing) { racing = false; stored.push({ sequenceNumber }); throw new Error("The conditional request failed"); }
      return `created ${sequenceNumber}`;
    },
  });
  assert.deepEqual(tried, [3, 4]);
  assert.deepEqual(result, { created: "created 4", sequenceNumber: 4 });
});

test("Another failure is not retried, and the retries are bounded", async () => {
  let calls = 0;
  await assert.rejects(createWithSequenceRetry({ list: async () => [], create: async () => { calls += 1; throw new Error("Not authorized"); } }), /Not authorized/);
  assert.equal(calls, 1);
  calls = 0;
  await assert.rejects(createWithSequenceRetry({ attempts: 3, list: async () => [], create: async () => { calls += 1; throw new Error("conditional"); } }), /conditional/);
  assert.equal(calls, 3);
});

test("The thread is found when it exists, created when it does not, and a lost create race uses the winner's", async () => {
  let creates = 0;
  assert.equal(await findOrCreateThread({ find: async () => "existing", create: async () => { creates += 1; return "new"; } }), "existing");
  assert.equal(creates, 0);
  assert.equal(await findOrCreateThread({ find: async () => null, create: async () => { creates += 1; return "new"; } }), "new");
  assert.equal(creates, 1);
  let finds = 0;
  assert.equal(await findOrCreateThread({
    find: async () => (finds += 1) === 1 ? null : "winner",
    create: async () => { throw new Error("The conditional request failed"); },
  }), "winner");
  await assert.rejects(findOrCreateThread({ find: async () => null, create: async () => { throw new Error("Not authorized"); } }), /Not authorized/);
});

test("Replies nest one level under their top-level message", () => {
  const tree = buildConversationTree([message(1, null), message(2, "m1", "grace@example.test"), message(4, null), message(3, "m2")]);
  assert.deepEqual(tree.map((root) => root.message.id), ["m1", "m4"]);
  assert.deepEqual(tree[0].replies.map((reply) => reply.message.id), ["m2", "m3"]);
  assert.deepEqual(tree[0].replies.map((reply) => reply.answers), [null, "grace"], "a reply to a reply says who it answers");
  assert.deepEqual(tree[1].replies, []);
});

test("A reply whose parent is missing is kept as a top-level message", () => {
  const tree = buildConversationTree([message(2, "gone")]);
  assert.deepEqual(tree.map((root) => root.message.id), ["m2"]);
});

test("The message count is said in words", () => {
  assert.equal(messageCountLabel(1), "1 message");
  assert.equal(messageCountLabel(3), "3 messages");
});

test("Only the author edits a message; the author or an admin deletes it; a deleted or unsent one offers neither", () => {
  const mine = { ...message(1, null), authorSub: "sub-me" };
  const theirs = { ...message(2, null), authorSub: "sub-them" };
  const me = { sub: "sub-me", isAdmin: false };
  const admin = { sub: "sub-root", isAdmin: true };
  assert.equal(canEditMessage(me, mine), true);
  assert.equal(canEditMessage(me, theirs), false);
  assert.equal(canEditMessage(admin, theirs), false, "an admin does not edit someone else's message");
  assert.equal(canDeleteMessage(me, mine), true);
  assert.equal(canDeleteMessage(me, theirs), false);
  assert.equal(canDeleteMessage(admin, theirs), true, "an admin removes anyone's");
  assert.equal(canEditMessage(me, { ...mine, deleted: true }), false);
  assert.equal(canDeleteMessage(admin, { ...theirs, deleted: true }), false);
  assert.equal(canDeleteMessage(me, { ...mine, pending: true }), false);
  assert.equal(canEditMessage(undefined, mine), false);
  assert.equal(canEditMessage({ sub: null, isAdmin: false }, { ...mine, authorSub: null }), false, "no sub, no ownership");
});

test("Only a thread's creator or an admin renames it", () => {
  assert.equal(canRenameThread({ sub: "sub-me", isAdmin: false }, { createdBySub: "sub-me" }), true);
  assert.equal(canRenameThread({ sub: "sub-me", isAdmin: false }, { createdBySub: "sub-them" }), false);
  assert.equal(canRenameThread({ sub: "sub-me", isAdmin: false }, { createdBySub: null }), false);
  assert.equal(canRenameThread({ sub: "sub-root", isAdmin: true }, { createdBySub: "sub-them" }), true);
});

test("The author's name is the saved label (their display name), then a readable profile name, then the email's first part", () => {
  const names = new Map([["profile-1", "Ada Lovelace"]]);
  assert.equal(messageAuthorName({ authorLabel: "Ada L.", authorUserProfileId: "profile-1" }, names), "Ada L.", "a display name saved with the message wins");
  assert.equal(messageAuthorName({ authorLabel: "ada@example.test", authorUserProfileId: "profile-1" }, names), "Ada Lovelace", "an older message saved an email: a readable profile name is better");
  assert.equal(messageAuthorName({ authorLabel: "ada@example.test", authorUserProfileId: "profile-2" }, names), "ada");
  assert.equal(messageAuthorName({ authorLabel: "", authorUserProfileId: null }), "Someone");
});
