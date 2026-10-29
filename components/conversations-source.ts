import type { MessageThreadRecord, ReferenceRecord } from "../lib/category-repository";
import type { ConversationMessage } from "../lib/conversation";
import type { PagedThreads } from "../lib/conversation-feed";
import type { ReferencePreview } from "../lib/reference-preview";

/** A Reference as the Messages page shows it: the record and the page's preview picture, when it has one. */
export type ConversationReferenceView = { reference: ReferenceRecord; preview: ReferencePreview | undefined };
export type ConversationStoryView = { title: string; stage: string | null };

/**
 * Where the Messages page reads and writes. The newsroom's is in conversations-network-source.ts; the tests give it an in-memory one.
 * Every read is a page or a batch, so a page of conversations never costs one request per card per render.
 */
export type ConversationsSource = {
  authorLabel: string;
  /** One page of the conversation threads of one kind, newest activity first. */
  loadThreads: (threadKind: string, nextToken: string | null) => Promise<PagedThreads<MessageThreadRecord>>;
  loadMessages: (threadId: string) => Promise<ConversationMessage[]>;
  post: (input: { thread: MessageThreadRecord; body: string; parentMessageId: string | null }) => Promise<ConversationMessage>;
  /** A new conversation about nothing but itself. */
  start: (body: string) => Promise<{ thread: MessageThreadRecord; message: ConversationMessage }>;
  loadReferences: (lineageIds: string[]) => Promise<Map<string, ConversationReferenceView>>;
  loadStories: (lineageIds: string[]) => Promise<Map<string, ConversationStoryView>>;
};
