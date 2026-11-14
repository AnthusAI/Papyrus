import type { MessageThreadRecord } from "../lib/category-repository";
import { NO_VIEWER, canDeleteMessage, canEditMessage, conversationPreviewLine, threadMetadataWithLastAuthor, type ConversationMessage, type ConversationViewer } from "../lib/conversation";
import type { ConversationReferenceView, ConversationStoryView, ConversationsSource } from "./conversations-source";

export type MemoryConversation = { thread: MessageThreadRecord; messages: ConversationMessage[] };

/** A source that keeps everything in memory: the demo newsroom (starting empty) and the tests (starting with fixtures). */
export function createMemoryConversationsSource(authorLabel: string, seed: {
  conversations?: MemoryConversation[];
  references?: Record<string, ConversationReferenceView>;
  stories?: Record<string, ConversationStoryView>;
  pageSize?: number;
  /** Who is looking. A Message they post carries their sub. */
  viewer?: ConversationViewer;
  /** The viewer's own profile id, recorded on what they post. */
  viewerProfileId?: string;
  /** Display names by profile id. */
  profiles?: Record<string, string>;
} = {}): ConversationsSource & { conversations: MemoryConversation[] } {
  const conversations = [...(seed.conversations ?? [])];
  const pageSize = seed.pageSize ?? 20;
  const viewer = seed.viewer ?? NO_VIEWER;
  const find = (messageId: string) => {
    for (const entry of conversations) {
      const message = entry.messages.find((candidate) => candidate.id === messageId);
      if (message) return { entry, message };
    }
    throw new Error("That message is not here.");
  };
  let started = 0;
  return {
    authorLabel,
    conversations,
    loadThreads: async (threadKind, nextToken) => {
      const all = conversations.map((entry) => entry.thread).filter((thread) => thread.threadKind === threadKind).sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
      const start = nextToken ? Number(nextToken) : 0;
      return { items: all.slice(start, start + pageSize), nextToken: start + pageSize < all.length ? String(start + pageSize) : null };
    },
    loadViewer: async () => viewer,
    loadAuthors: async (ids) => new Map(ids.filter((id) => seed.profiles?.[id]).map((id) => [id, seed.profiles![id]])),
    edit: async (messageId, body) => {
      const { entry, message } = find(messageId);
      if (!canEditMessage(viewer, message)) throw new Error("Only the author can edit a message.");
      const edited = { ...message, content: body.trim(), editedAt: new Date().toISOString() };
      entry.messages = entry.messages.map((candidate) => (candidate.id === messageId ? edited : candidate));
      return edited;
    },
    remove: async (messageId) => {
      const { entry, message } = find(messageId);
      if (!canDeleteMessage(viewer, message)) throw new Error("Only the author or an admin can delete a message.");
      const removed = { ...message, content: "", deleted: true, deletedAt: new Date().toISOString() };
      entry.messages = entry.messages.map((candidate) => (candidate.id === messageId ? removed : candidate));
      return removed;
    },
    loadMessages: async (threadId) => [...(conversations.find((entry) => entry.thread.id === threadId)?.messages ?? [])],
    post: async ({ thread, body, parentMessageId }) => {
      const entry = conversations.find((candidate) => candidate.thread.id === thread.id);
      if (!entry) throw new Error("That conversation is not here.");
      const sequenceNumber = Math.max(0, ...entry.messages.map((message) => message.sequenceNumber)) + 1;
      const message: ConversationMessage = { id: `${thread.id}-m${sequenceNumber}`, parentMessageId, authorLabel, authorSub: viewer.sub, authorUserProfileId: seed.viewerProfileId ?? null, content: body.trim(), createdAt: new Date().toISOString(), sequenceNumber };
      entry.messages.push(message);
      entry.thread = { ...entry.thread, messageCount: entry.messages.length, lastMessageAt: message.createdAt, updatedAt: message.createdAt, summary: conversationPreviewLine(message.content), metadata: threadMetadataWithLastAuthor(entry.thread.metadata, authorLabel) };
      return message;
    },
    loadThread: async (threadId) => conversations.find((entry) => entry.thread.id === threadId)?.thread ?? null,
    rename: async (thread, title) => {
      const entry = conversations.find((candidate) => candidate.thread.id === thread.id);
      if (!entry) throw new Error("That conversation is not here.");
      entry.thread = { ...entry.thread, title: title.trim() };
      return entry.thread;
    },
    start: async (title, body) => {
      started += 1;
      const now = new Date().toISOString();
      const thread: MessageThreadRecord = { id: `message-thread-conversation-new-${started}`, threadKind: "conversation", status: "active", title: title.trim(), createdBySub: viewer.sub, summary: conversationPreviewLine(body), metadata: threadMetadataWithLastAuthor(null, authorLabel), createdByLabel: authorLabel, messageCount: 1, lastMessageAt: now, createdAt: now, updatedAt: now };
      const message: ConversationMessage = { id: `${thread.id}-m1`, parentMessageId: null, authorLabel, authorSub: viewer.sub, authorUserProfileId: seed.viewerProfileId ?? null, content: body.trim(), createdAt: now, sequenceNumber: 1 };
      conversations.push({ thread, messages: [message] });
      return { thread, message };
    },
    loadReferences: async (ids) => new Map(ids.filter((id) => seed.references?.[id]).map((id) => [id, seed.references![id]])),
    loadStories: async (ids) => new Map(ids.filter((id) => seed.stories?.[id]).map((id) => [id, seed.stories![id]])),
  };
}
