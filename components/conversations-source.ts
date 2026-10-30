import type { MessageThreadRecord, ReferenceRecord } from "../lib/category-repository";
import type { ConversationMessage, ConversationViewer } from "../lib/conversation";
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
  /** Who is looking: their sub and whether they are an admin. Decides which Messages show Edit and Delete. */
  loadViewer: () => Promise<ConversationViewer>;
  /** Display names by profile id, in one request for a whole conversation. Profiles that cannot be read are simply absent. */
  loadAuthors: (profileIds: string[]) => Promise<Map<string, string>>;
  /** The author changes their own Message's text; rejects with the reason when the API refuses. */
  edit: (messageId: string, body: string) => Promise<ConversationMessage>;
  /** A soft delete: the Message stays, marked deleted. */
  remove: (messageId: string) => Promise<ConversationMessage>;
  post: (input: { thread: MessageThreadRecord; body: string; parentMessageId: string | null }) => Promise<ConversationMessage>;
  /** One thread by id, for a linked address whose thread is not on the pages read so far. Null when there is none. */
  loadThread: (threadId: string) => Promise<MessageThreadRecord | null>;
  /** Gives the conversation a new title; rejects with the reason when it cannot be saved. */
  rename: (thread: MessageThreadRecord, title: string) => Promise<MessageThreadRecord>;
  /** A new conversation about nothing but itself, with its own title and first message. */
  start: (title: string, body: string) => Promise<{ thread: MessageThreadRecord; message: ConversationMessage }>;
  loadReferences: (lineageIds: string[]) => Promise<Map<string, ConversationReferenceView>>;
  loadStories: (lineageIds: string[]) => Promise<Map<string, ConversationStoryView>>;
};
