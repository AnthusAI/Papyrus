"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { NO_VIEWER, type ConversationAnchor, type ConversationMessage, type ConversationViewer } from "../lib/conversation";
import { useConversationStore } from "./conversation-context";

export type ConversationState = "loading" | "ready" | "error";

/**
 * One conversation's Messages. Posting shows the Message at once (marked pending) and swaps in the saved one; a failed save removes
 * it again and rejects, so the caller can give the typed text back.
 */
export function useConversation(anchor: ConversationAnchor) {
  const store = useConversationStore();
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [state, setState] = useState<ConversationState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const pendingCount = useRef(0);
  const anchorRef = useRef(anchor);
  anchorRef.current = anchor;
  const anchorKey = `${anchor.kind}#${anchor.lineageId ?? ""}`;

  useEffect(() => {
    if (!store) return;
    let active = true;
    setState("loading");
    setError(null);
    setMessages([]);
    store.load(anchorRef.current).then((loaded) => {
      if (!active) return;
      setMessages((current) => [...loaded, ...current.filter((message) => message.pending)]);
      setState("ready");
    }).catch((failure) => {
      if (!active) return;
      setError(failure instanceof Error ? failure.message : "The conversation could not be loaded.");
      setState("error");
    });
    return () => { active = false; };
  }, [store, anchorKey, attempt]);

  const retry = useCallback(() => setAttempt((current) => current + 1), []);

  const post = useCallback(async (body: string, parentMessageId: string | null) => {
    if (!store) throw new Error("Messages are not available here.");
    pendingCount.current += 1;
    const pendingId = `pending-${pendingCount.current}`;
    const pending: ConversationMessage = {
      id: pendingId,
      parentMessageId,
      authorLabel: store.authorLabel,
      content: body.trim(),
      createdAt: new Date().toISOString(),
      sequenceNumber: Number.MAX_SAFE_INTEGER - 1000 + pendingCount.current,
      pending: true,
    };
    setMessages((current) => [...current, pending]);
    try {
      const saved = await store.append({ anchor: anchorRef.current, body, parentMessageId });
      setMessages((current) => current.map((message) => (message.id === pendingId ? saved : message)));
    } catch (failure) {
      setMessages((current) => current.filter((message) => message.id !== pendingId));
      throw failure instanceof Error ? failure : new Error("Your message could not be saved.");
    }
  }, [store]);

  const [viewer, setViewer] = useState<ConversationViewer>(NO_VIEWER);
  useEffect(() => {
    if (!store) return;
    let active = true;
    store.viewer().then((loaded) => { if (active) setViewer(loaded); }).catch(() => undefined);
    return () => { active = false; };
  }, [store]);

  // Display names come from the authors' profiles: one request for every author not yet asked about.
  const [names, setNames] = useState<ReadonlyMap<string, string>>(() => new Map());
  const asked = useRef(new Set<string>());
  useEffect(() => {
    if (!store) return;
    const missing = [...new Set(messages.map((message) => message.authorUserProfileId).filter((id): id is string => Boolean(id) && !asked.current.has(id as string)))];
    if (!missing.length) return;
    missing.forEach((id) => asked.current.add(id));
    let active = true;
    store.authors(missing).then((loaded) => { if (active && loaded.size) setNames((current) => new Map([...current, ...loaded])); }).catch(() => undefined);
    return () => { active = false; };
  }, [messages, store]);

  const edit = useCallback(async (messageId: string, body: string) => {
    if (!store) throw new Error("Messages are not available here.");
    const saved = await store.edit(messageId, body);
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, ...saved } : message)));
  }, [store]);
  const remove = useCallback(async (messageId: string) => {
    if (!store) throw new Error("Messages are not available here.");
    const target = messages.find((message) => message.id === messageId);
    const moderate = viewer.isAdmin && target?.authorSub !== viewer.sub;
    const saved = await store.remove(messageId, moderate);
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, ...saved } : message)));
  }, [store, messages, viewer]);

  return { available: Boolean(store), messages, state, error, retry, post, edit, remove, viewer, names };
}

/** Message counts per Reference lineage, for the feed cards. A failed read just shows no counts. */
export function useReferenceMessageCounts(enabled: boolean) {
  const store = useConversationStore();
  const [counts, setCounts] = useState<ReadonlyMap<string, number>>(() => new Map());
  useEffect(() => {
    if (!store || !enabled) return;
    let active = true;
    store.counts().then((loaded) => { if (active) setCounts((current) => new Map([...loaded, ...current])); }).catch(() => undefined);
    return () => { active = false; };
  }, [store, enabled]);
  const setCount = useCallback((lineageId: string, count: number) => {
    setCounts((current) => (current.get(lineageId) === count || (count === 0 && !current.has(lineageId)) ? current : new Map(current).set(lineageId, count)));
  }, []);
  return { counts, setCount };
}
