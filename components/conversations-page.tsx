"use client";

import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { ConversationsView } from "./conversations-view";
import { createMemoryConversationsSource } from "./conversations-memory-source";
import { createNetworkConversationsSource } from "./conversations-network-source";

/** The Messages page: every conversation, from the backend (or kept in memory in the demo). */
export function ConversationsPage({ authorLabel, demo }: { authorLabel: string; demo: boolean }) {
  const router = useRouter();
  const source = useMemo(() => (demo ? createMemoryConversationsSource(authorLabel) : createNetworkConversationsSource(authorLabel)), [authorLabel, demo]);
  return <ConversationsView demo={demo} onNavigate={(href) => router.push(href)} source={source} />;
}
