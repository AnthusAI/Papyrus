"use client";

import { createContext, useContext, type ReactNode } from "react";
import { NO_VIEWER, canDeleteMessage, canEditMessage, type ConversationAnchor, type ConversationMessage, type ConversationViewer } from "../lib/conversation";

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
  /** Who is looking, and display names by profile id: what Edit, Delete and the author's name are decided from. */
  viewer: () => Promise<ConversationViewer>;
  authors: (profileIds: string[]) => Promise<Map<string, string>>;
  edit: (messageId: string, body: string) => Promise<ConversationMessage>;
  remove: (messageId: string, moderate: boolean) => Promise<ConversationMessage>;
};

const ConversationStoreContext = createContext<ConversationStore | null>(null);

export function ConversationStoreProvider({ store, children }: { store: ConversationStore; children: ReactNode }) {
  return <ConversationStoreContext.Provider value={store}>{children}</ConversationStoreContext.Provider>;
}

export function useConversationStore(): ConversationStore | null {
  return useContext(ConversationStoreContext);
}

/** A store that keeps everything in memory: the demo newsroom, and the tests. */
export function createMemoryConversationStore(authorLabel: string, seed: Record<string, ConversationMessage[]> = {}, who: { viewer?: ConversationViewer; profiles?: Record<string, string> } = {}): ConversationStore {
  const viewer = who.viewer ?? NO_VIEWER;
  const byAnchor = new Map<string, ConversationMessage[]>(Object.entries(seed));
  const keyOf = (anchor: ConversationAnchor) => `${anchor.kind}#${anchor.lineageId ?? ""}`;
  const change = (messageId: string, apply: (message: ConversationMessage) => ConversationMessage) => {
    for (const [key, list] of byAnchor) {
      const found = list.find((message) => message.id === messageId);
      if (!found) continue;
      const changed = apply(found);
      byAnchor.set(key, list.map((message) => (message.id === messageId ? changed : message)));
      return changed;
    }
    throw new Error("That message is not here.");
  };
  return {
    authorLabel,
    viewer: async () => viewer,
    authors: async (ids) => new Map(ids.filter((id) => who.profiles?.[id]).map((id) => [id, who.profiles![id]])),
    edit: async (messageId, body) => change(messageId, (message) => {
      if (!canEditMessage(viewer, message)) throw new Error("Only the author can edit a message.");
      return { ...message, content: body.trim(), editedAt: new Date().toISOString() };
    }),
    remove: async (messageId) => change(messageId, (message) => {
      if (!canDeleteMessage(viewer, message)) throw new Error("Only the author or an admin can delete a message.");
      return { ...message, content: "", deleted: true, deletedAt: new Date().toISOString() };
    }),
    load: async (anchor) => [...(byAnchor.get(keyOf(anchor)) ?? [])],
    append: async ({ anchor, body, parentMessageId }) => {
      const list = byAnchor.get(keyOf(anchor)) ?? [];
      const sequenceNumber = Math.max(0, ...list.map((message) => message.sequenceNumber)) + 1;
      const message: ConversationMessage = {
        id: `message-memory-${sequenceNumber}-${list.length}`,
        parentMessageId,
        authorLabel,
        authorSub: viewer.sub,
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
