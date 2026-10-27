"use client";

import { Hub } from "aws-amplify/utils";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PapyrusConsoleConversation, type ConsoleConversationMessage } from "./papyrus-console-conversation";
import {
  listPapyrusPrivateChatMessages,
  openPapyrusPrivateChat,
  sendPapyrusPrivateChatMessage,
  type PapyrusPrivateChatChannel,
  type PapyrusPrivateChatMessage,
} from "../lib/papyrus-private-chat-client";

const REFRESH_MS = 2_000;

function toConsoleMessages(messages: readonly PapyrusPrivateChatMessage[]): ConsoleConversationMessage[] {
  return messages.map((message) => ({
    id: message.message_id,
    role: message.author_kind === "human" ? "USER" : "ASSISTANT",
    text: message.body,
    createdAt: message.created_at,
  }));
}

function failureMessage(error: unknown): string {
  return error instanceof Error && error.message.trim() ? error.message : "Private chat is unavailable.";
}

export function PapyrusPrivateChatPanel({ onClose }: { onClose: () => void }) {
  const [channel, setChannel] = useState<PapyrusPrivateChatChannel | null>(null);
  const [messages, setMessages] = useState<PapyrusPrivateChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const identityGeneration = useRef(0);
  const retryAttempt = useRef<{ text: string; key: string } | null>(null);
  const isWaitingForReply = messages.length > 0 && messages[messages.length - 1].author_kind === "human" &&
    messages[messages.length - 1].addressed_to_bot_id !== null;
  const conversationMessages = useMemo(() => {
    const current = toConsoleMessages(messages);
    if (!isWaitingForReply) return current;
    const last = messages[messages.length - 1];
    return [...current, {
      id: `pending-reply:${last.message_id}`,
      role: "ASSISTANT",
      text: "",
      pending: true,
    }];
  }, [isWaitingForReply, messages]);

  const handleFailure = useCallback(async (nextError: unknown) => {
    const failure = failureMessage(nextError);
    setError(failure);
    if (["sign_in_required", "chat_account_access_denied"].includes(failure)) {
      ++identityGeneration.current;
      setChannel(null);
      setMessages([]);
      retryAttempt.current = null;
      setSending(false);
      setLoading(false);
    }
  }, []);

  const refreshMessages = useCallback(async (channelId: string, generation: number) => {
    const next = await listPapyrusPrivateChatMessages(channelId);
    if (generation === identityGeneration.current) setMessages(next);
  }, []);

  const openConversation = useCallback(async () => {
    const generation = ++identityGeneration.current;
    setLoading(true);
    setError(null);
    setChannel(null);
    setMessages([]);
    try {
      const nextChannel = await openPapyrusPrivateChat();
      if (generation !== identityGeneration.current) return;
      setChannel(nextChannel);
      await refreshMessages(nextChannel.channel_id, generation);
    } catch (nextError) {
      if (generation === identityGeneration.current) await handleFailure(nextError);
    } finally {
      if (generation === identityGeneration.current) setLoading(false);
    }
  }, [handleFailure, refreshMessages]);

  useEffect(() => {
    void openConversation();
    return () => { identityGeneration.current += 1; };
  }, [openConversation]);

  useEffect(() => Hub.listen("auth", ({ payload }) => {
    if (["signedOut", "signedIn", "tokenRefresh_failure"].includes(payload.event)) {
      void handleFailure(new Error("sign_in_required"));
    }
  }), [handleFailure]);

  useEffect(() => {
    if (!channel || !isWaitingForReply) return;
    let active = true;
    const generation = identityGeneration.current;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        await refreshMessages(channel.channel_id, generation);
      } catch (nextError) {
        if (active && generation === identityGeneration.current) await handleFailure(nextError);
        return;
      }
      if (active) timer = setTimeout(poll, REFRESH_MS);
    };
    timer = setTimeout(poll, REFRESH_MS);
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [channel, handleFailure, isWaitingForReply, refreshMessages]);

  const sendMessage = useCallback(async (text: string) => {
    if (!channel || !text.trim() || sending) return;
    const generation = identityGeneration.current;
    const attempt = retryAttempt.current?.text === text
      ? retryAttempt.current
      : { text, key: globalThis.crypto.randomUUID() };
    retryAttempt.current = attempt;
    setSending(true);
    setError(null);
    try {
      const result = await sendPapyrusPrivateChatMessage(channel.channel_id, text, attempt.key);
      if (generation !== identityGeneration.current) return;
      setMessages((current) => current.some((message) => message.message_id === result.message.message_id)
        ? current
        : [...current, result.message]);
      retryAttempt.current = null;
    } catch (nextError) {
      if (generation === identityGeneration.current) await handleFailure(nextError);
    } finally {
      if (generation === identityGeneration.current) setSending(false);
    }
  }, [channel, handleFailure, sending]);

  return <div className="papyrus-console__panel">
    <header className="papyrus-console__header">
      <p className="papyrus-console__header-label">Private chat</p>
      <button className="papyrus-console__close" onClick={onClose} type="button" aria-label="Close console">×</button>
    </header>
    {channel ? <p className="papyrus-console__empty" role="status">Private conversation for this newsroom.</p> : null}
    {!channel && !loading ? <div className="papyrus-console__access" role="alert">
      <strong>Private chat could not be opened.</strong>
      <span>{error === "sign_in_required" ? "Your newsroom session has expired. Return to the newsroom and sign in from the account menu, then retry." : error === "chat_account_access_denied" ? "Your access to this conversation has changed. Retry to check your current access." : error}</span>
      <button className="papyrus-console__new-session" onClick={() => void openConversation()} type="button">Retry</button>
      <button className="papyrus-console__new-session" onClick={onClose} type="button">Back to newsroom</button>
    </div> : <PapyrusConsoleConversation
      messages={conversationMessages}
      isSending={sending || loading || !channel}
      isRunning={isWaitingForReply}
      onSendMessage={sendMessage}
      error={error}
      emptyState={loading ? <p className="papyrus-console__empty">Opening private conversation…</p> : (
        <p className="papyrus-console__empty">This conversation is private to you in this newsroom.</p>
      )}
    />}
  </div>;
}
