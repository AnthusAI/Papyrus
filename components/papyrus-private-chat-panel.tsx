"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { connectNewsroomChat } from "../lib/newsroom-chat-client";
import { loadProspectusAccountState, selectProspectusAccount, type ProspectusAccountState } from "../lib/prospectus-account-client";
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
  const [accountState, setAccountState] = useState<ProspectusAccountState | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectionNotice, setConnectionNotice] = useState<string | null>(null);
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
    if (["sign_in_required", "chat_identity_connection_required", "publishing_account_required", "chat_account_access_denied"].includes(failure)) {
      const generation = ++identityGeneration.current;
      setChannel(null);
      setMessages([]);
      setAccountState(null);
      retryAttempt.current = null;
      setSending(false);
      setLoading(false);
      if (failure === "publishing_account_required") {
        const state = await loadProspectusAccountState(window.location.pathname);
        if (generation === identityGeneration.current) setAccountState(state);
      }
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
    const code = new URLSearchParams(window.location.search).get("sign_in_error");
    if (code) setConnectionNotice(code === "newsroom_identity_mismatch"
      ? "The selected Google account did not match your newsroom session. Connect again with the same account."
      : "The publishing-account connection did not complete. You can safely try again.");
    void openConversation();
    return () => { identityGeneration.current += 1; };
  }, [openConversation]);

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

  const connect = async () => {
    setConnecting(true);
    try {
      const returnUrl = new URL(window.location.href);
      returnUrl.searchParams.delete("sign_in_error");
      const target = await connectNewsroomChat(`${returnUrl.pathname}${returnUrl.search}${returnUrl.hash}`);
      window.location.assign(target);
    } catch (nextError) {
      setError(failureMessage(nextError));
      setConnecting(false);
    }
  };
  const chooseAccount = async (accountId: string) => {
    setConnecting(true);
    try {
      const result = await selectProspectusAccount(accountId);
      if ("error" in result) { setError(result.error); return; }
      setAccountState(null);
      await openConversation();
    } catch (nextError) { setError(failureMessage(nextError)); }
    finally { setConnecting(false); }
  };

  return <div className="papyrus-console__panel">
    <header className="papyrus-console__header">
      <p className="papyrus-console__header-label">Private chat</p>
      <button className="papyrus-console__close" onClick={onClose} type="button" aria-label="Close console">×</button>
    </header>
    {channel ? <p className="papyrus-console__empty" role="status">Private conversation for your selected Account.</p> : null}
    {!channel && !loading ? <div className="papyrus-console__empty" role="alert">
      {error === "chat_identity_connection_required" ? <>
        <strong>Connect your publishing account</strong>
        {connectionNotice ? <span>{connectionNotice}</span> : null}
        <span>Continue with the same Google account you use in the newsroom, then choose the Account for this private conversation.</span>
        <button className="papyrus-console__new-session" disabled={connecting} onClick={() => void connect()} type="button">{connecting ? "Connecting…" : "Connect publishing account"}</button>
      </> : accountState?.status === "signedIn" ? <>
        <strong>Choose your publishing Account</strong>
        {accountState.publishingAccounts.length === 0 ? <span>This identity has no publishing Account for this site. Ask the Account owner to confirm your existing access.</span> : accountState.publishingAccounts.map(account => <button className="papyrus-console__new-session" disabled={connecting} key={account.accountId} onClick={() => void chooseAccount(account.accountId)} type="button">{account.name ?? account.accountId}</button>)}
        {error !== "publishing_account_required" ? <span>{error}</span> : null}
      </> : <>
        <strong>Private chat could not be opened.</strong>
        <span>{error === "sign_in_required" ? "Your newsroom session has expired. Sign in from the account menu, then retry." : error}</span>
        <button className="papyrus-console__new-session" onClick={() => void openConversation()} type="button">Retry</button>
      </>}
    </div> : <PapyrusConsoleConversation
      messages={conversationMessages}
      isSending={sending || loading || !channel}
      isRunning={isWaitingForReply}
      onSendMessage={sendMessage}
      error={error}
      emptyState={loading ? <p className="papyrus-console__empty">Opening private conversation…</p> : (
        <p className="papyrus-console__empty">This conversation is private to your selected Account and editor session.</p>
      )}
    />}
  </div>;
}
