"use client";

import { useMemo, type ReactNode } from "react";
import { ChatRuntime, type ChatMessage, type MessagePresentation } from "chatticus/chat-react";

/** Editorial console data adapted to the shared presentation without exposing GraphQL or auth. */
export type ConsoleConversationMessage = {
  id: string;
  role: string | null | undefined;
  text: string;
  createdAt?: string;
  pending?: boolean;
  failed?: boolean;
  error?: string | null;
  context?: boolean;
};

/** Normalize host records; Papyrus keeps thread ownership, persistence and response state. */
export function consoleConversationMessages(messages: readonly ConsoleConversationMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role === "USER" ? "user" : "assistant",
    content: [{ type: "text", text: message.failed ? message.error || "Responder failed" : message.text }],
    createdAt: message.createdAt ? new Date(message.createdAt) : undefined,
    status: message.failed ? { type: "incomplete", reason: "error" } : message.pending ? { type: "running" } : undefined,
    metadata: { custom: {
      authorLabel: message.context ? "Page context" : undefined,
      failed: message.failed,
      isStreaming: message.pending,
      isStreamingShell: message.pending && !message.text,
      createdAt: message.createdAt,
    } },
  }));
}

/** Controlled newsroom adapter for the reusable Chatticus transcript and composer. */
export function PapyrusConsoleConversation({ messages, isSending, isRunning, onSendMessage, presentation, composerActions, emptyState, error }: {
  messages: readonly ConsoleConversationMessage[];
  isSending: boolean;
  isRunning: boolean;
  onSendMessage: (text: string) => Promise<void>;
  presentation?: MessagePresentation;
  composerActions?: ReactNode;
  emptyState?: ReactNode;
  error?: string | null;
}) {
  const sharedMessages = useMemo(() => consoleConversationMessages(messages), [messages]);
  return <div className="papyrus-console-conversation" data-reply-running={isRunning || undefined}>
    {/* Papyrus routes can accept another editor message while the current reply runs.
        The pending assistant message carries its own running status for display. */}
    <ChatRuntime messages={sharedMessages} isRunning={false} isSendDisabled={isSending}
      onSendMessage={onSendMessage} presentation={presentation}
      threadProps={{ composerPlaceholder: "Write a message...", composerActions, emptyState, streamError: error }} />
  </div>;
}
