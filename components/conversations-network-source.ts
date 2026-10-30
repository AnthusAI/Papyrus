import { referencePreviewsByLineage } from "../lib/reference-preview";
import {
  appendConversationMessage,
  loadConversationThreadMessages,
  loadConversationThreadPage,
  loadReferenceAttachmentsForLineageId,
  loadReferenceRecordByLineageId,
  loadStoryHeaders,
  startUnattachedConversation,
} from "./news-desk-taxonomy-client";
import type { ConversationReferenceView, ConversationsSource } from "./conversations-source";

const PAGE_SIZE = 20;

/** The newsroom's own source: the MessageThread and Message models. A Reference that cannot be read is left out, and its card shows only the messages. */
export function createNetworkConversationsSource(authorLabel: string): ConversationsSource {
  return {
    authorLabel,
    loadThreads: (threadKind, nextToken) => loadConversationThreadPage(threadKind, nextToken, PAGE_SIZE),
    loadMessages: loadConversationThreadMessages,
    post: async ({ thread, body, parentMessageId }) => {
      const anchor = thread.primaryAnchorLineageId && (thread.primaryAnchorKind === "reference" || thread.primaryAnchorKind === "item")
        ? { kind: thread.primaryAnchorKind, lineageId: thread.primaryAnchorLineageId, title: thread.title } as const
        : { kind: "none" } as const;
      return (await appendConversationMessage({ anchor, body, parentMessageId, thread })).message;
    },
    start: startUnattachedConversation,
    loadReferences: async (lineageIds) => {
      const views = new Map<string, ConversationReferenceView>();
      await Promise.all([...new Set(lineageIds)].map(async (lineageId) => {
        try {
          const [reference, attachments] = await Promise.all([loadReferenceRecordByLineageId(lineageId), loadReferenceAttachmentsForLineageId(lineageId).catch(() => [])]);
          if (reference) views.set(lineageId, { reference, preview: referencePreviewsByLineage(attachments).get(lineageId) });
        } catch { /* left out */ }
      }));
      return views;
    },
    loadStories: loadStoryHeaders,
  };
}
