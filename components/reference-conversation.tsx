"use client";

import { useEffect, useState } from "react";
import { ConversationThread } from "./conversation-thread";
import { useConversation } from "./use-conversation";

/**
 * The Messages about one Reference, under its review card. Shows nothing where no conversation store is provided.
 * `onCount` tells the feed how many Messages there are, so its card count follows what is written here.
 */
export function ReferenceConversation({ disabledReason = null, lineageId, onCount, referenceId, title }: {
  disabledReason?: string | null;
  lineageId: string;
  onCount?: (lineageId: string, count: number) => void;
  /** The Reference version's id, when it differs from the lineage id. */
  referenceId?: string;
  title?: string;
}) {
  const conversation = useConversation({ kind: "reference", lineageId, title, ...(referenceId ? { id: referenceId } : {}) });
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);
  const settled = conversation.messages.filter((message) => !message.pending).length;
  useEffect(() => {
    if (conversation.state === "ready") onCount?.(lineageId, settled);
  }, [conversation.state, lineageId, onCount, settled]);
  if (!conversation.available) return null;
  return (
    <div data-reference-conversation={lineageId}>
      <ConversationThread
        disabledReason={disabledReason}
        error={conversation.error}
        messages={conversation.messages}
        now={now}
        onPost={conversation.post}
        onRetry={conversation.retry}
        state={conversation.state}
      />
    </div>
  );
}
