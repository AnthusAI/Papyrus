"use client";

import { useMemo, type ReactNode } from "react";
import { ConversationStoreProvider, createMemoryConversationStore, type ConversationStore } from "./conversation-context";
import { appendConversationMessage, deleteConversationMessage, editConversationMessage, loadConversationMessages, loadConversationViewer, loadReferenceConversationCounts, loadUserProfileNames } from "./news-desk-taxonomy-client";

function networkConversationStore(authorLabel: string): ConversationStore {
  return {
    authorLabel,
    load: loadConversationMessages,
    append: async ({ anchor, body, parentMessageId }) => (await appendConversationMessage({ anchor, body, parentMessageId })).message,
    counts: loadReferenceConversationCounts,
    viewer: loadConversationViewer,
    authors: loadUserProfileNames,
    edit: editConversationMessage,
    remove: (messageId, moderate) => deleteConversationMessage(messageId, moderate),
  };
}

/** Gives the newsroom its conversations: saved to the backend, or kept in memory in the demo. */
export function ConversationProvider({ authorLabel, demo, children }: { authorLabel: string; demo: boolean; children: ReactNode }) {
  const store = useMemo(() => (demo ? createMemoryConversationStore(authorLabel) : networkConversationStore(authorLabel)), [authorLabel, demo]);
  return <ConversationStoreProvider store={store}>{children}</ConversationStoreProvider>;
}
