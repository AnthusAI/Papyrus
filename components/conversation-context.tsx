"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { ConversationAnchor, ConversationMessage } from "../lib/conversation";

/**
 * Where conversations are read and written. The newsroom provides the network one; a demo or a test provides the in-memory one. A
 * component that finds no store shows no conversation at all.
 */
export type ConversationStore = {
  /** Who the optimistic Message says wrote it, until the saved one replaces it. */
  authorLabel: string;
  load: (anchor: ConversationAnchor) => Promise<ConversationMessage[]>;
  append: (input: { anchor: ConversationAnchor; body: string; parentMessageId: string | null }) => Promise<ConversationMessage>;
  /** Message counts by Reference lineage, for the feed cards. */
  counts: () => Promise<Map<string, number>>;
};

const ConversationStoreContext = createContext<ConversationStore | null>(null);

export function ConversationStoreProvider({ store, children }: { store: ConversationStore; children: ReactNode }) {
  return <ConversationStoreContext.Provider value={store}>{children}</ConversationStoreContext.Provider>;
}

export function useConversationStore(): ConversationStore | null {
  return useContext(ConversationStoreContext);
}

/** A store that keeps everything in memory: the demo newsroom, and the tests. */
export function createMemoryConversationStore(authorLabel: string, seed: Record<string, ConversationMessage[]> = {}): ConversationStore {
  const byAnchor = new Map<string, ConversationMessage[]>(Object.entries(seed));
  const keyOf = (anchor: ConversationAnchor) => `${anchor.kind}#${anchor.lineageId ?? ""}`;
  return {
    authorLabel,
    load: async (anchor) => [...(byAnchor.get(keyOf(anchor)) ?? [])],
    append: async ({ anchor, body, parentMessageId }) => {
      const list = byAnchor.get(keyOf(anchor)) ?? [];
      const sequenceNumber = Math.max(0, ...list.map((message) => message.sequenceNumber)) + 1;
      const message: ConversationMessage = {
        id: `message-memory-${sequenceNumber}-${list.length}`,
        parentMessageId,
        authorLabel,
        content: body.trim(),
        createdAt: new Date().toISOString(),
        sequenceNumber,
      };
      byAnchor.set(keyOf(anchor), [...list, message]);
      return message;
    },
    counts: async () => new Map([...byAnchor].filter(([key]) => key.startsWith("reference#")).map(([key, list]) => [key.slice("reference#".length), list.length])),
  };
}
