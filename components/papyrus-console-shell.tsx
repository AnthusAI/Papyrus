"use client";

import type { BotAvatarState } from "anthus-vultus";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CheckIcon, UserIcon } from "lucide-react";
import { Md5 } from "@smithy/md5-js";
import { gsap } from "gsap";
import {
  createConsoleMessage,
  createConsoleThread,
  listConsoleMessagesByThread,
  listConsoleThreads,
  subscribeConsoleMessages,
  updateConsoleMessage,
  updateConsoleThread,
  type ConsoleChatMessage,
  type ConsoleChatThread,
} from "../lib/console-chat-client";
import { buildNewsroomKnowledgeQueryInput, type NewsroomKnowledgeQueryTarget } from "../lib/newsroom-knowledge-query-request";
import {
  CONSOLE_WEB_CONTEXT_MESSAGE_KIND,
  formatConsoleWebContextMessage,
  readConsoleWebUiFromMessageMetadata,
  webUiContextKey,
  type ConsoleWebContextEvent,
} from "../lib/console-web-context";
import { buildWebUiContext, extractNavigationIntent, type PapyrusWebUiContext } from "../lib/papyrus-web-locations";
import { runNewsroomKnowledgeQuery } from "./news-desk-taxonomy-client";
import { loadReaderSessionSnapshot, type ReaderSessionSnapshot } from "./reader-auth-state";
import {
  readLocalReaderSettings,
  resolveReaderSettings,
  subscribeReaderSettingsChanges,
  type ReaderMotionSetting,
} from "./reader-settings";
import { Conversation, ConversationContent, ConversationScrollButton } from "./ai-elements/conversation";
import { ModelSelector } from "./ai-elements/model-selector";
import { PromptInput, PromptInputBody, PromptInputFooter, type PromptInputMessage, PromptInputSubmit, PromptInputTextarea, PromptInputTools } from "./ai-elements/prompt-input";
import { Shimmer } from "./ai-elements/shimmer";
import { Suggestion, Suggestions } from "./ai-elements/suggestion";
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "./ai-elements/tool";
import { CONNECTION_STATE_CHANGE, ConnectionState } from "aws-amplify/data";
import { Hub } from "aws-amplify/utils";
import {
  type ComponentType,
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useStickToBottomContext } from "use-stick-to-bottom";

const CONSOLE_STARTER_SUGGESTIONS = [
  "Start a research assignment",
  "Start a reporting assignment",
  "Discuss a reference",
] as const;

const CONSOLE_THREAD_ANCHOR_KEY = "site#papyrus";
const CONSOLE_NEWSROOM_FEED_KEY = "consoleChat";
const CONSOLE_MESSAGE_KIND = "console_chat_turn";
const CONSOLE_TOOL_CALL_KIND = "console_tool_call";
const CONSOLE_TOOL_RESULT_KIND = "console_tool_result";
const CONSOLE_MESSAGE_DOMAIN = "conversation";
const CONSOLE_SEMANTIC_LAYER = "chat_detail";
const CONSOLE_SEARCH_VISIBILITY = "explicit";
const CONSOLE_RESPONSE_TARGET = process.env.NEXT_PUBLIC_PAPYRUS_CONSOLE_RESPONSE_TARGET?.trim() || "cloud";
const DEFAULT_CONSOLE_MODEL = process.env.NEXT_PUBLIC_PAPYRUS_CONSOLE_MODEL?.trim() || "gpt-5.4-mini";
const CONSOLE_SELECT_THREAD_EVENT = "papyrus:console-select-thread";
const ASSISTANT_AVATAR_SIZE_PX = 32;
const ASSISTANT_AVATAR_DEFAULT_SHADOW_COLOR = "rgb(var(--ink-solid-rgb) / var(--ink-display-alpha))";
const ASSISTANT_AVATAR_DEFAULT_LIGHT_COLOR = "rgb(var(--paper-rgb) / 1)";
const ASSISTANT_AVATAR_ERROR_SHADOW_COLOR = ASSISTANT_AVATAR_DEFAULT_SHADOW_COLOR;
const ASSISTANT_AVATAR_ERROR_LIGHT_COLOR = ASSISTANT_AVATAR_DEFAULT_LIGHT_COLOR;
type VultusBotAvatarProps = {
  ariaLabel?: string;
  lightColor?: string;
  neutralIdleMode?: "bored-random" | "static";
  shadowColor?: string;
  size?: number;
  state?: BotAvatarState;
  transitionDurationSeconds?: number;
};
const VULTUS_BOT_AVATAR_FALLBACK: ComponentType<VultusBotAvatarProps> = () => null;
const VultusBotAvatar = dynamic<VultusBotAvatarProps>(
  () => (
    import("anthus-vultus")
      .then((module) => module.BotAvatar as ComponentType<VultusBotAvatarProps>)
      .catch((error) => {
        console.error("[PapyrusConsole] Failed to load anthus-vultus BotAvatar", error);
        return VULTUS_BOT_AVATAR_FALLBACK;
      })
  ),
  { ssr: false },
);
const CONSOLE_MODEL_OPTIONS = [
  { value: "gpt-5.5", label: "GPT 5.5", provider: "openai" },
  { value: "gpt-5.4", label: "GPT 5.4", provider: "openai" },
  { value: "gpt-5.4-mini", label: "GPT 5.4 Mini", provider: "openai" },
  { value: "gpt-5.4-nano", label: "GPT 5.4 Nano", provider: "openai" },
] as const;

type PapyrusConsoleShellProps = {
  children: ReactNode;
};

type PapyrusConsoleContextValue = {
  open: boolean;
  openingReferenceChat: boolean;
  openConsole: () => void;
  shouldOfferConsole: boolean;
  startReferenceChat: (target: NewsroomKnowledgeQueryTarget) => Promise<void>;
  toggleOpen: () => void;
};

type DisplayConsoleMessage = ConsoleChatMessage & {
  pendingPlaceholder?: boolean;
};

type ConsoleToolTimelineEntry = {
  id: string;
  firstSequence: number;
  firstCreatedAt: string;
  messageKind: string;
  role: "TOOL";
  toolCallId: string;
  toolName: string;
  callMessage?: DisplayConsoleMessage;
  resultMessage?: DisplayConsoleMessage;
};

type ConsoleTimelineEntry =
  | { kind: "message"; id: string; message: DisplayConsoleMessage }
  | { kind: "tool"; id: string; tool: ConsoleToolTimelineEntry };

type AssistantAvatarTone = "default" | "error";
type ConsoleAuthorIdentity = {
  avatarHash: string | null;
  email: string | null;
  userProfileId: string | null;
};

const PapyrusConsoleContext = createContext<PapyrusConsoleContextValue | null>(null);

export function PapyrusConsoleShell({ children }: PapyrusConsoleShellProps) {
  const pathname = usePathname();
  const [session, setSession] = useState<ReaderSessionSnapshot | null>(null);
  const [open, setOpen] = useState(false);
  const [openingReferenceChat, setOpeningReferenceChat] = useState(false);
  const isNewsroomPath = pathname === "/newsroom" || pathname.startsWith("/newsroom/");
  const canUseConsole = Boolean(session?.hasSession && session.groups.some((group) => group === "editor" || group === "admin"));
  const shouldOfferConsole = isNewsroomPath && canUseConsole;

  useEffect(() => {
    let active = true;
    void loadReaderSessionSnapshot()
      .then((snapshot) => {
        if (active) setSession(snapshot);
      })
      .catch(() => {
        if (active) setSession({ auth: { status: "signedOut", label: "Signed out" }, groups: [], hasSession: false });
      });
    try {
      setOpen(window.localStorage.getItem("papyrus:console-open") === "true");
    } catch {
      setOpen(false);
    }
    return () => {
      active = false;
    };
  }, []);

  const toggleOpen = useCallback(() => {
    setOpen((current) => {
      const next = !current;
      try {
        window.localStorage.setItem("papyrus:console-open", String(next));
      } catch {
        // Ignore storage failures.
      }
      return next;
    });
  }, []);

  const openConsole = useCallback(() => {
    setOpen(true);
    try {
      window.localStorage.setItem("papyrus:console-open", "true");
    } catch {
      // Ignore storage failures.
    }
  }, []);

  const startReferenceChat = useCallback(async (target: NewsroomKnowledgeQueryTarget) => {
    if (!canUseConsole) {
      throw new Error("Chat is only available to editor/admin sessions.");
    }
    if (openingReferenceChat) return;
    setOpeningReferenceChat(true);
    try {
      openConsole();
      const now = new Date().toISOString();
      const title = target.title?.trim() || "Reference";
      const summary = `Reference chat for ${title}`.slice(0, 180);
      const lineageId = target.anchor.lineageId ?? target.anchor.id;
      const thread = await createConsoleThread({
        id: `message-thread-console-${crypto.randomUUID()}`,
        threadKind: "console",
        status: "active",
        title: "Reference Chat",
        summary,
        primaryAnchorKind: "site",
        primaryAnchorId: "papyrus",
        primaryAnchorLineageId: "papyrus",
        primaryAnchorKey: CONSOLE_THREAD_ANCHOR_KEY,
        createdByLabel: session?.auth.label ?? "Papyrus editor",
        messageCount: 0,
        metadata: toAwsJson({
          console: {
            cache: "lambda-tmp-jit",
            model: DEFAULT_CONSOLE_MODEL,
            rawChatSearchVisibility: CONSOLE_SEARCH_VISIBILITY,
          },
          bootstrap: {
            mode: "reference_chat",
            anchor: target.anchor,
          },
        }),
        newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
        createdAt: now,
        updatedAt: now,
      });
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(CONSOLE_SELECT_THREAD_EVENT, { detail: { threadId: thread.id } }));
      }
      const pendingMessage = await createConsoleMessage({
        id: `message-console-assistant-${crypto.randomUUID()}`,
        threadId: thread.id,
        parentMessageId: null,
        sequenceNumber: 1,
        role: "ASSISTANT",
        messageKind: CONSOLE_MESSAGE_KIND,
        messageType: "MESSAGE",
        content: "",
        summary: "Thinking...",
        messageDomain: CONSOLE_MESSAGE_DOMAIN,
        status: "active",
        source: "papyrus-console",
        authorLabel: "Papyrus",
        semanticLayer: CONSOLE_SEMANTIC_LAYER,
        searchVisibility: CONSOLE_SEARCH_VISIBILITY,
        responseTarget: CONSOLE_RESPONSE_TARGET,
        responseStatus: "RUNNING",
        responseStartedAt: now,
        metadata: toAwsJson({
          model: DEFAULT_CONSOLE_MODEL,
          bootstrap: "reference-chat",
          anchor: target.anchor,
        }),
        createdAt: now,
        updatedAt: now,
        newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
      });
      await updateConsoleThread({
        id: thread.id,
        messageCount: 1,
        lastMessageId: pendingMessage.id,
        lastMessageAt: now,
        activeResponseMessageId: pendingMessage.id,
        updatedAt: now,
      });

      const tokenBudget = 1600;
      const request = buildNewsroomKnowledgeQueryInput(target, "", tokenBudget);
      const completedAt = new Date().toISOString();
      let markdown: string;
      try {
        const result = await withTimeout(
          runNewsroomKnowledgeQuery(request),
          45_000,
          "Reference context preload timed out.",
        );
        markdown = result.context?.text?.trim() ?? "";
        if (!markdown) throw new Error("knowledgeQuery returned no markdown context.");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        markdown = `Unable to preload reference context.\n\n${message}`;
      }
      let completedMessage: ConsoleChatMessage;
      try {
        completedMessage = await updateConsoleMessage({
          id: pendingMessage.id,
          content: markdown,
          summary: truncateConsoleSummary(markdown),
          responseStatus: "COMPLETED",
          responseCompletedAt: completedAt,
          updatedAt: completedAt,
        });
      } catch {
        completedMessage = await createConsoleMessage({
          id: `message-console-assistant-${crypto.randomUUID()}`,
          threadId: thread.id,
          parentMessageId: pendingMessage.id,
          sequenceNumber: 2,
          role: "ASSISTANT",
          messageKind: CONSOLE_MESSAGE_KIND,
          messageType: "MESSAGE",
          content: markdown,
          summary: truncateConsoleSummary(markdown),
          messageDomain: CONSOLE_MESSAGE_DOMAIN,
          status: "active",
          source: "papyrus-console",
          authorLabel: "Papyrus",
          semanticLayer: CONSOLE_SEMANTIC_LAYER,
          searchVisibility: CONSOLE_SEARCH_VISIBILITY,
          responseTarget: CONSOLE_RESPONSE_TARGET,
          responseStatus: "COMPLETED",
          responseCompletedAt: completedAt,
          metadata: toAwsJson({
            model: DEFAULT_CONSOLE_MODEL,
            bootstrap: "reference-chat",
            anchor: target.anchor,
          }),
          createdAt: completedAt,
          updatedAt: completedAt,
          newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
        });
      }
      await updateConsoleThread({
        id: thread.id,
        messageCount: 1,
        lastMessageId: completedMessage.id,
        lastMessageAt: completedAt,
        activeResponseMessageId: null,
        updatedAt: completedAt,
      });
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(CONSOLE_SELECT_THREAD_EVENT, { detail: { threadId: thread.id } }));
      }
    } finally {
      setOpeningReferenceChat(false);
    }
  }, [canUseConsole, openConsole, openingReferenceChat, session?.auth.label]);

  const consoleContext = useMemo<PapyrusConsoleContextValue>(() => ({
    open,
    openingReferenceChat,
    openConsole,
    shouldOfferConsole,
    startReferenceChat,
    toggleOpen,
  }), [open, openConsole, openingReferenceChat, shouldOfferConsole, startReferenceChat, toggleOpen]);

  return (
    <PapyrusConsoleContext.Provider value={consoleContext}>
      <div className={canUseConsole && open ? "papyrus-console-page papyrus-console-page--open" : "papyrus-console-page"}>
        {children}
      </div>
      {shouldOfferConsole ? (
        <aside className={open ? "papyrus-console papyrus-console--open" : "papyrus-console"} aria-label="Papyrus console">
          {open ? (
            canUseConsole
              ? <ConsolePanel actorEmail={session?.auth.status === "signedIn" ? (session.auth.email ?? null) : null} actorLabel={session?.auth.label ?? "Papyrus editor"} onClose={toggleOpen} />
              : <ConsoleAccessPanel onClose={toggleOpen} session={session} />
          ) : null}
        </aside>
      ) : null}
    </PapyrusConsoleContext.Provider>
  );
}

export function NewsroomConsoleProgressToggle() {
  const consoleContext = usePapyrusConsole();
  if (!consoleContext?.shouldOfferConsole || consoleContext.open) return null;

  return (
    <button
      type="button"
      className="edition-progress__button edition-progress__button--next edition-progress__button--console"
      aria-expanded={false}
      aria-label="Open console"
      onClick={consoleContext.toggleOpen}
      title="Open console"
    >
      <PapyrusConsoleChatIcon />
    </button>
  );
}

export function usePapyrusConsole(): PapyrusConsoleContextValue | null {
  return useContext(PapyrusConsoleContext);
}

function ConsoleAccessPanel({ onClose, session }: { onClose: () => void; session: ReaderSessionSnapshot | null }) {
  return (
    <div className="papyrus-console__panel papyrus-console__panel--access">
      <ConsolePanelHeader onClose={onClose} />
      <div className="papyrus-console__empty">
        <strong>Checking Newsroom credentials.</strong>
        <span>
          The Newsroom is visible, but this console is waiting for the client session groups.
          Refresh after the current deployment finishes if this does not resolve.
        </span>
        <span>Groups: {session?.groups.length ? session.groups.join(", ") : "none loaded"}</span>
      </div>
    </div>
  );
}

function ConsolePanel({ actorEmail, actorLabel, onClose }: { actorEmail: string | null; actorLabel: string; onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [thread, setThread] = useState<ConsoleChatThread | null>(null);
  const [threads, setThreads] = useState<ConsoleChatThread[]>([]);
  const [messages, setMessages] = useState<ConsoleChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_CONSOLE_MODEL);
  const [motionSetting, setMotionSetting] = useState<ReaderMotionSetting>("standard");
  const [authorIdentity, setAuthorIdentity] = useState<ConsoleAuthorIdentity>({ avatarHash: null, email: null, userProfileId: null });
  const [fallbackAvatarHash, setFallbackAvatarHash] = useState<string | null>(null);
  const hasLoadedRef = useRef(false);
  const activeThreadIdRef = useRef<string | null>(null);
  const threadRef = useRef<ConsoleChatThread | null>(null);
  const handledNavigationMessageIdsRef = useRef<Set<string>>(new Set());

  const currentWebPath = useMemo(() => {
    const path = pathname ?? "/newsroom";
    const query = searchParams.toString();
    return query ? `${path}?${query}` : path;
  }, [pathname, searchParams]);

  const currentWebUi = useMemo(() => buildWebUiContext(currentWebPath), [currentWebPath]);
  const currentWebUiKey = useMemo(() => webUiContextKey(currentWebUi), [currentWebUi]);
  const recordingContextRef = useRef<string | null>(null);
  const [hydratedThreadId, setHydratedThreadId] = useState<string | null>(null);

  useEffect(() => {
    for (const message of messages) {
      if (message.messageKind !== CONSOLE_TOOL_RESULT_KIND) continue;
      if (handledNavigationMessageIdsRef.current.has(message.id)) continue;
      const metadata = readAwsJsonObject(message.metadata);
      const navigation = extractNavigationIntent(readNestedValue(metadata, ["toolResultJson"]));
      if (!navigation) continue;
      handledNavigationMessageIdsRef.current.add(message.id);
      if (currentWebPath !== navigation.webPath) {
        router.push(navigation.webPath);
      }
    }
  }, [currentWebPath, messages, router]);

  useEffect(() => {
    setMotionSetting(readLocalReaderSettings().motion);
    return subscribeReaderSettingsChanges((settings) => {
      setMotionSetting(settings.motion);
    });
  }, []);

  useEffect(() => {
    let active = true;
    void resolveReaderSettings()
      .then((resolution) => {
        if (!active) return;
        setAuthorIdentity({
          avatarHash: resolution.avatarHash ?? null,
          email: resolution.email ?? actorEmail ?? null,
          userProfileId: resolution.userProfileId ?? null,
        });
      })
      .catch(() => {
        if (!active) return;
        setAuthorIdentity({ avatarHash: null, email: actorEmail ?? null, userProfileId: null });
      });
    return () => {
      active = false;
    };
  }, [actorEmail]);

  useEffect(() => {
    let active = true;
    if (!actorEmail) {
      setFallbackAvatarHash(null);
      return () => {
        active = false;
      };
    }
    void computeAvatarHashFromEmail(actorEmail)
      .then((hash) => {
        if (active) setFallbackAvatarHash(hash);
      })
      .catch(() => {
        if (active) setFallbackAvatarHash(null);
      });
    return () => {
      active = false;
    };
  }, [actorEmail]);

  const effectiveAuthorIdentity = useMemo<ConsoleAuthorIdentity>(() => ({
    avatarHash: authorIdentity.avatarHash ?? fallbackAvatarHash,
    email: authorIdentity.email ?? actorEmail ?? null,
    userProfileId: authorIdentity.userProfileId,
  }), [actorEmail, authorIdentity.avatarHash, authorIdentity.email, authorIdentity.userProfileId, fallbackAvatarHash]);

  const sortedMessages = useMemo(() => (
    [...messages].sort((left, right) => (left.sequenceNumber ?? 0) - (right.sequenceNumber ?? 0) || left.createdAt.localeCompare(right.createdAt))
  ), [messages]);

  const mergeMessage = useCallback((message: ConsoleChatMessage) => {
    setMessages((current) => upsertConsoleMessage(current, message));
  }, []);

  const appendConsoleWebContextMessage = useCallback(async (
    activeThread: ConsoleChatThread,
    webUi: PapyrusWebUiContext,
    event: ConsoleWebContextEvent,
  ) => {
    const { visibleContent, agentInstructions, summary } = formatConsoleWebContextMessage(webUi, event);
    const sequenceNumber = (activeThread.messageCount ?? 0) + 1;
    const now = new Date().toISOString();
    const messageMetadata = {
      console: {
        webUi,
        contextEvent: event,
        agentInstructions,
      },
    };
    const message: ConsoleChatMessage = {
      id: `message-console-context-${crypto.randomUUID()}`,
      threadId: activeThread.id,
      parentMessageId: activeThread.lastMessageId ?? null,
      sequenceNumber,
      role: "SYSTEM",
      messageKind: CONSOLE_WEB_CONTEXT_MESSAGE_KIND,
      messageType: "MESSAGE",
      content: visibleContent,
      summary,
      responseStatus: "COMPLETED",
      responseCompletedAt: now,
      metadata: messageMetadata,
      createdAt: now,
    };
    mergeMessage(message);
    const persisted = await createConsoleMessage({
      ...message,
      messageDomain: CONSOLE_MESSAGE_DOMAIN,
      status: "active",
      source: "papyrus-console",
      authorLabel: actorLabel,
      semanticLayer: CONSOLE_SEMANTIC_LAYER,
      searchVisibility: CONSOLE_SEARCH_VISIBILITY,
      responseTarget: CONSOLE_RESPONSE_TARGET,
      metadata: toAwsJson(messageMetadata),
      updatedAt: now,
      newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
    });
    mergeMessage({ ...message, ...persisted });
    await updateConsoleThread({
      id: activeThread.id,
      messageCount: sequenceNumber,
      lastMessageId: persisted.id,
      lastMessageAt: now,
      updatedAt: now,
    });
    setThread((current) => current?.id === activeThread.id ? {
      ...current,
      messageCount: sequenceNumber,
      lastMessageId: persisted.id,
      lastMessageAt: now,
      updatedAt: now,
    } : current);
    recordingContextRef.current = webUiContextKey(webUi);
    return persisted;
  }, [actorLabel, mergeMessage]);

  const recordWebContextIfNeeded = useCallback(async (
    activeThread: ConsoleChatThread,
    webUi: PapyrusWebUiContext,
    event: ConsoleWebContextEvent,
  ) => {
    const nextKey = webUiContextKey(webUi);
    if (!nextKey || recordingContextRef.current === nextKey) return;
    const lastContextMessage = [...sortedMessages].reverse().find((entry) => entry.messageKind === CONSOLE_WEB_CONTEXT_MESSAGE_KIND);
    const lastRecorded = lastContextMessage
      ? readConsoleWebUiFromMessageMetadata(readAwsJsonObject(lastContextMessage.metadata))
      : null;
    if (lastRecorded && webUiContextKey(lastRecorded) === nextKey) {
      recordingContextRef.current = nextKey;
      return;
    }
    await appendConsoleWebContextMessage(activeThread, webUi, event);
  }, [appendConsoleWebContextMessage, sortedMessages]);

  useEffect(() => {
    threadRef.current = thread;
  }, [thread]);

  useEffect(() => {
    recordingContextRef.current = null;
  }, [thread?.id]);

  useEffect(() => {
    if (!thread?.id || hydratedThreadId !== thread.id || !currentWebUi.papyrusLocationUri) return;
    const hasPriorContext = sortedMessages.some((entry) => entry.messageKind === CONSOLE_WEB_CONTEXT_MESSAGE_KIND);
    void recordWebContextIfNeeded(
      thread,
      currentWebUi,
      hasPriorContext ? "navigation" : "session_start",
    ).catch((error) => {
      console.error("[PapyrusConsole] Unable to record web UI context", error);
    });
  }, [currentWebUi, currentWebUiKey, hydratedThreadId, recordWebContextIfNeeded, sortedMessages, thread]);

  const loadMessages = useCallback(async (threadId: string) => {
    setHydratedThreadId(null);
    const nextMessages = await listConsoleMessagesByThread(threadId);
    setMessages(nextMessages);
    setHydratedThreadId(threadId);
  }, []);

  const loadThreads = useCallback(async () => {
    return listConsoleThreads(CONSOLE_THREAD_ANCHOR_KEY, 25);
  }, []);

  const resolveActiveThread = useCallback((
    recentThreads: ConsoleChatThread[],
    currentThread: ConsoleChatThread | null,
  ): ConsoleChatThread | null => {
    const preferredId = activeThreadIdRef.current ?? currentThread?.id ?? null;
    if (preferredId) {
      const match = recentThreads.find((entry) => entry.id === preferredId);
      if (match) return match;
      if (currentThread?.id === preferredId) return currentThread;
    }
    const fallback = recentThreads[0] ?? null;
    if (fallback) activeThreadIdRef.current = fallback.id;
    return fallback;
  }, []);

  const loadThread = useCallback(async () => {
    const initialLoad = !hasLoadedRef.current;
    if (initialLoad) setLoading(true);
    setError(null);
    try {
      const recentThreads = await loadThreads();
      const nextThread = resolveActiveThread(recentThreads, threadRef.current);
      setThreads(recentThreads);
      setThread(nextThread);
      setSelectedModel(resolveThreadModel(nextThread));
      if (nextThread) {
        await loadMessages(nextThread.id);
      } else {
        setMessages([]);
      }
    } catch (nextError) {
      const normalizedError = formatUnknownConsoleError(nextError);
      console.error("[PapyrusConsole] Unable to load console thread", normalizedError, nextError);
      if (initialLoad) setError(normalizedError);
    } finally {
      hasLoadedRef.current = true;
      if (initialLoad) setLoading(false);
    }
  }, [loadMessages, loadThreads, resolveActiveThread]);

  useEffect(() => {
    void loadThread();
  }, [loadThread]);

  useEffect(() => {
    if (!thread?.id) return;
    const activeThreadId = thread.id;
    const unsubscribe = subscribeConsoleMessages(
      activeThreadId,
      (message) => {
        if (message.threadId && message.threadId !== activeThreadIdRef.current) return;
        mergeMessage(message);
      },
      (nextError) => {
        console.warn("[PapyrusConsole] Console message subscription failed", nextError);
      },
    );
    return unsubscribe;
  }, [mergeMessage, thread?.id]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onSelectThread = (event: Event) => {
      const detail = (event as CustomEvent<{ threadId?: string }>).detail;
      const threadId = detail?.threadId?.trim();
      if (!threadId) return;
      activeThreadIdRef.current = threadId;
      const currentMatch = threads.find((entry) => entry.id === threadId) ?? null;
      if (currentMatch) {
        setThread(currentMatch);
        setSelectedModel(resolveThreadModel(currentMatch));
        void loadMessages(threadId);
        return;
      }
      void loadThread();
    };
    window.addEventListener(CONSOLE_SELECT_THREAD_EVENT, onSelectThread as EventListener);
    return () => {
      window.removeEventListener(CONSOLE_SELECT_THREAD_EVENT, onSelectThread as EventListener);
    };
  }, [loadMessages, loadThread, threads]);

  useEffect(() => {
    let previousState: ConnectionState | null = null;
    const unsubscribe = Hub.listen("api", ({ payload }) => {
      if (payload.event !== CONNECTION_STATE_CHANGE) return;
      const data = payload.data as { connectionState?: ConnectionState } | undefined;
      const nextState = data?.connectionState;
      if (previousState && previousState !== ConnectionState.Connected && nextState === ConnectionState.Connected) {
        const activeThreadId = activeThreadIdRef.current;
        if (activeThreadId) void loadMessages(activeThreadId);
      }
      previousState = nextState ?? previousState;
    });
    return () => unsubscribe();
  }, [loadMessages]);

  const selectThread = useCallback((threadId: string) => {
    activeThreadIdRef.current = threadId;
    const nextThread = threads.find((entry) => entry.id === threadId) ?? null;
    setThread(nextThread);
    setSelectedModel(resolveThreadModel(nextThread));
    setMessages([]);
    setHydratedThreadId(null);
    if (nextThread) void loadMessages(nextThread.id);
  }, [loadMessages, threads]);

  async function createNewThread(): Promise<ConsoleChatThread> {
    const now = new Date().toISOString();
    const nextThread: ConsoleChatThread = {
      id: `message-thread-console-${crypto.randomUUID()}`,
      threadKind: "console",
      status: "active",
      title: "Papyrus Console",
      summary: "General editor console thread for Papyrus.",
      primaryAnchorKind: "site",
      primaryAnchorId: "papyrus",
      primaryAnchorLineageId: "papyrus",
      primaryAnchorKey: CONSOLE_THREAD_ANCHOR_KEY,
      createdByLabel: actorLabel,
      messageCount: 0,
      metadata: toAwsJson({
        console: {
          cache: "lambda-tmp-jit",
          model: selectedModel,
          rawChatSearchVisibility: CONSOLE_SEARCH_VISIBILITY,
        },
      }),
      newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
      createdAt: now,
      updatedAt: now,
    };
    activeThreadIdRef.current = nextThread.id;
    setThread(nextThread);
    setThreads((current) => [nextThread, ...current]);
    setMessages([]);
    setHydratedThreadId(null);
    const created = await createConsoleThread(nextThread);
    activeThreadIdRef.current = created.id;
    setThread(created);
    setSelectedModel(resolveThreadModel(created));
    setThreads((current) => [created, ...current.filter((entry) => entry.id !== created.id)]);
    setHydratedThreadId(created.id);
    if (currentWebUi.papyrusLocationUri) {
      await recordWebContextIfNeeded(created, currentWebUi, "session_start");
    }
    return created;
  }

  async function ensureThread(): Promise<ConsoleChatThread> {
    return thread ?? createNewThread();
  }

  async function submitMessage(content: string) {
    if (!content || sending) return;
    setSending(true);
    setError(null);
    try {
      const activeThread = await ensureThread();
      const previousMessage = sortedMessages[sortedMessages.length - 1] ?? null;
      const previousSequenceNumber = previousMessage?.sequenceNumber ?? activeThread.messageCount ?? 0;
      const sequenceNumber = previousSequenceNumber + 1;
      const now = new Date().toISOString();
      const messageMetadata = {
        model: selectedModel,
        previousSequenceNumber,
        previousMessageId: previousMessage?.id ?? null,
        previousContextDigest: activeThread.contextDigest ?? null,
        cacheHint: "lambda-tmp-jit",
        console: {
          author: {
            avatarHash: effectiveAuthorIdentity.avatarHash,
            email: effectiveAuthorIdentity.email,
            userProfileId: effectiveAuthorIdentity.userProfileId,
          },
          webUi: currentWebUi,
        },
      };
      const message: ConsoleChatMessage = {
        id: `message-console-user-${crypto.randomUUID()}`,
        threadId: activeThread.id,
        parentMessageId: previousMessage?.id ?? null,
        sequenceNumber,
        role: "USER",
        messageKind: CONSOLE_MESSAGE_KIND,
        messageType: "MESSAGE",
        content,
        summary: truncateConsoleSummary(content),
        responseStatus: "PENDING",
        authorUserProfileId: effectiveAuthorIdentity.userProfileId,
        metadata: messageMetadata,
        createdAt: now,
      };
      mergeMessage(message);
      const persistedMessage = await createConsoleMessage({
        ...message,
        messageDomain: CONSOLE_MESSAGE_DOMAIN,
        status: "active",
        source: "papyrus-console",
        authorLabel: actorLabel,
        authorUserProfileId: effectiveAuthorIdentity.userProfileId,
        semanticLayer: CONSOLE_SEMANTIC_LAYER,
        searchVisibility: CONSOLE_SEARCH_VISIBILITY,
        responseTarget: CONSOLE_RESPONSE_TARGET,
        metadata: toAwsJson(messageMetadata),
        updatedAt: now,
        newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
      });
      mergeMessage({ ...message, ...persistedMessage });
      await updateConsoleThread({
        id: activeThread.id,
        messageCount: sequenceNumber,
        lastMessageId: message.id,
        lastMessageAt: now,
        updatedAt: now,
      });
      setThread((current) => current ? {
        ...current,
        messageCount: sequenceNumber,
        lastMessageId: message.id,
        lastMessageAt: now,
        updatedAt: now,
      } : current);
    } catch (nextError) {
      console.error("[PapyrusConsole] Unable to send console message", nextError);
      setError(nextError instanceof Error ? nextError.message : "Unable to send console message.");
    } finally {
      setSending(false);
    }
  }

  async function sendMessage(message: PromptInputMessage) {
    const content = message.text.trim();
    if (!content) return;
    setDraft("");
    await submitMessage(content);
  }

  function handleSuggestionClick(suggestion: string) {
    if (sending) return;
    void submitMessage(suggestion);
  }

  const handleModelChange = useCallback((nextModel: string) => {
    setSelectedModel(nextModel);
    const activeThread = threadRef.current;
    if (!activeThread) return;
    const metadata = readAwsJsonObject(activeThread.metadata) ?? {};
    const nextMetadata = {
      ...metadata,
      console: {
        ...(readNestedObject(metadata, "console") ?? {}),
        model: nextModel,
      },
    };
    const now = new Date().toISOString();
    void updateConsoleThread({
      id: activeThread.id,
      metadata: toAwsJson(nextMetadata),
      updatedAt: now,
    })
      .then((updated) => {
        setThread(updated);
        setThreads((current) => current.map((entry) => (
          entry.id === updated.id ? updated : entry
        )));
      })
      .catch((nextError) => {
        console.error("[PapyrusConsole] Unable to update console thread model", nextError);
        setError(nextError instanceof Error ? nextError.message : "Unable to update console model.");
      });
  }, []);

  const latestAwaitingAssistantUserMessage = [...sortedMessages]
    .reverse()
    .find((message) => (
      message.role === "USER"
      && isAwaitingAssistantStatus(message.responseStatus)
      && !sortedMessages.some((candidate) => (
        candidate.role === "ASSISTANT"
        && isResponderMessageForPendingUser(candidate, message)
      ))
    ));
  const pendingUserResponse = Boolean(latestAwaitingAssistantUserMessage);
  const pendingAssistantResponse = sortedMessages.some((message, index) => {
    if (message.role !== "ASSISTANT" || message.responseStatus !== "RUNNING") return false;
    return !sortedMessages.slice(index + 1).some((candidate) => (
      candidate.role === "ASSISTANT"
      && candidate.threadId === message.threadId
      && candidate.responseStatus === "COMPLETED"
      && (candidate.parentMessageId === message.id || (candidate.sequenceNumber ?? 0) > (message.sequenceNumber ?? 0))
    ));
  });
  const pending = pendingUserResponse || pendingAssistantResponse;
  useEffect(() => {
    if (!thread?.id || !pending) return;
    let cancelled = false;
    let timer: number | null = null;

    const refresh = async () => {
      if (cancelled) return;
      try {
        await loadMessages(thread.id);
      } catch (nextError) {
        console.warn("[PapyrusConsole] Pending message refresh failed", nextError);
      } finally {
        if (!cancelled) timer = window.setTimeout(refresh, 1200);
      }
    };

    timer = window.setTimeout(refresh, 1200);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [loadMessages, pending, thread?.id]);

  const displayMessages = useMemo<DisplayConsoleMessage[]>(() => {
    if (!latestAwaitingAssistantUserMessage) return sortedMessages;
    return [
      ...sortedMessages,
      {
        id: `pending-assistant-placeholder-${latestAwaitingAssistantUserMessage.id}`,
        threadId: latestAwaitingAssistantUserMessage.threadId,
        parentMessageId: latestAwaitingAssistantUserMessage.id,
        sequenceNumber: (latestAwaitingAssistantUserMessage.sequenceNumber ?? sortedMessages.length) + 1,
        role: "ASSISTANT",
        messageKind: CONSOLE_MESSAGE_KIND,
        messageType: "MESSAGE",
        content: "",
        summary: "Thinking...",
        responseStatus: "RUNNING",
        createdAt: latestAwaitingAssistantUserMessage.createdAt,
        pendingPlaceholder: true,
      },
    ];
  }, [latestAwaitingAssistantUserMessage, sortedMessages]);
  const timelineEntries = useMemo<ConsoleTimelineEntry[]>(() => {
    const groupedTools = new Map<string, ConsoleToolTimelineEntry>();
    const entries: ConsoleTimelineEntry[] = [];

    for (const message of displayMessages) {
      const isToolMessage = message.messageKind === CONSOLE_TOOL_CALL_KIND || message.messageKind === CONSOLE_TOOL_RESULT_KIND;
      if (!isToolMessage) {
        entries.push({ kind: "message", id: message.id, message });
        continue;
      }
      const metadata = readAwsJsonObject(message.metadata);
      const toolCallId = readNestedString(metadata, ["toolCallId"]);
      const toolName = readNestedString(metadata, ["toolName"]);
      if (!toolCallId) {
        entries.push({ kind: "message", id: message.id, message });
        continue;
      }

      const existing = groupedTools.get(toolCallId);
      if (!existing) {
        const firstSequence = typeof message.sequenceNumber === "number" ? message.sequenceNumber : Number.MAX_SAFE_INTEGER;
        const next: ConsoleToolTimelineEntry = {
          id: `tool-timeline-${toolCallId}`,
          firstSequence,
          firstCreatedAt: message.createdAt,
          messageKind: message.messageKind ?? CONSOLE_TOOL_CALL_KIND,
          role: "TOOL",
          toolCallId,
          toolName: toolName ?? "execute_tactus",
          callMessage: message.messageKind === CONSOLE_TOOL_CALL_KIND ? message : undefined,
          resultMessage: message.messageKind === CONSOLE_TOOL_RESULT_KIND ? message : undefined,
        };
        groupedTools.set(toolCallId, next);
        entries.push({ kind: "tool", id: next.id, tool: next });
        continue;
      }

      if (!existing.toolName && toolName) existing.toolName = toolName;
      if (message.messageKind === CONSOLE_TOOL_CALL_KIND) existing.callMessage = message;
      if (message.messageKind === CONSOLE_TOOL_RESULT_KIND) existing.resultMessage = message;
      const sequence = typeof message.sequenceNumber === "number" ? message.sequenceNumber : Number.MAX_SAFE_INTEGER;
      if (sequence < existing.firstSequence || (sequence === existing.firstSequence && message.createdAt < existing.firstCreatedAt)) {
        existing.firstSequence = sequence;
        existing.firstCreatedAt = message.createdAt;
      }
    }

    return entries;
  }, [displayMessages]);
  const isSupersededRunningAssistantMessage = useCallback((
    message: DisplayConsoleMessage,
    _trimmedContent: string,
  ) => (
    message.role === "ASSISTANT"
    && message.responseStatus === "RUNNING"
    && sortedMessages.some((candidate) => (
      candidate.role === "ASSISTANT"
      && candidate.threadId === message.threadId
      && candidate.responseStatus === "COMPLETED"
      && (candidate.parentMessageId === message.id || (candidate.sequenceNumber ?? 0) > (message.sequenceNumber ?? 0))
    ))
  ), [sortedMessages]);
  const latestVisibleAvatarAnchorId = useMemo(() => {
    let latestAgentEntryId: string | null = null;
    for (const entry of timelineEntries) {
      if (entry.kind === "tool") {
        latestAgentEntryId = entry.id;
        continue;
      }
      const content = (entry.message.content ?? "").trim();
      if (isSupersededRunningAssistantMessage(entry.message, content)) continue;
      const isAgentRole = entry.message.role === "ASSISTANT" || entry.message.role === "TOOL";
      if (isAgentRole) latestAgentEntryId = entry.id;
    }
    return latestAgentEntryId;
  }, [isSupersededRunningAssistantMessage, timelineEntries]);
  const streamingAutoStickSignal = useMemo(() => {
    const activeStreamingAssistant = [...displayMessages]
      .reverse()
      .find((message) => message.role === "ASSISTANT" && message.responseStatus === "RUNNING");
    if (!activeStreamingAssistant) return null;
    return [
      activeStreamingAssistant.id,
      activeStreamingAssistant.pendingPlaceholder ? "placeholder" : "message",
      (activeStreamingAssistant.content ?? "").length,
      activeStreamingAssistant.updatedAt ?? activeStreamingAssistant.createdAt,
    ].join(":");
  }, [displayMessages]);

  return (
    <div className="papyrus-console__panel">
      <ConsolePanelHeader onClose={onClose} />
      <div className="papyrus-console__sessions">
        <select
          aria-label="Console chat session"
          className="papyrus-console__session-select"
          onChange={(event) => selectThread(event.target.value)}
          value={thread?.id ?? ""}
        >
          {!thread ? <option value="">No session selected</option> : null}
          {threads.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {formatConsoleThreadOption(entry)}
            </option>
          ))}
        </select>
        {sortedMessages.length > 0 ? (
          <button
            className="papyrus-console__new-session"
            disabled={sending}
            onClick={() => void createNewThread().catch((nextError) => {
              console.error("[PapyrusConsole] Unable to create console thread", nextError);
              setError(nextError instanceof Error ? nextError.message : "Unable to create console thread.");
            })}
            type="button"
          >
            New chat
          </button>
        ) : null}
      </div>
      <Conversation className="papyrus-console__conversation" resize={pending ? "instant" : "smooth"}>
        <ConsoleStreamingAutoStick active={pending} streamSignal={streamingAutoStickSignal} />
        <ConversationContent
          aria-live="polite"
          className="papyrus-console__body"
          scrollClassName="papyrus-console__scrollport"
          role="log"
        >
          {loading && !sortedMessages.length ? <p className="papyrus-console__empty">Loading conversation…</p> : null}
          {timelineEntries.map((entry) => {
            if (entry.kind === "tool") {
              const showAssistantAvatar = entry.id === latestVisibleAvatarAnchorId;
              const assistantAvatar = showAssistantAvatar
                ? resolveAssistantAvatarPresentation(entry.tool, motionSetting === "low", pending)
                : null;
              return (
                <ConsoleToolTimelineRow key={entry.id}>
                  <ConsoleToolMessageContent tool={entry.tool} />
                  {assistantAvatar ? (
                    <span className="papyrus-console-message__assistant-avatar" data-tone={assistantAvatar.tone}>
                      <VultusBotAvatar
                        ariaLabel={assistantAvatar.ariaLabel}
                        lightColor={assistantAvatar.tone === "error" ? ASSISTANT_AVATAR_ERROR_LIGHT_COLOR : ASSISTANT_AVATAR_DEFAULT_LIGHT_COLOR}
                        neutralIdleMode={assistantAvatar.neutralIdleMode}
                        shadowColor={assistantAvatar.tone === "error" ? ASSISTANT_AVATAR_ERROR_SHADOW_COLOR : ASSISTANT_AVATAR_DEFAULT_SHADOW_COLOR}
                        size={ASSISTANT_AVATAR_SIZE_PX}
                        state={assistantAvatar.state}
                        transitionDurationSeconds={0.35}
                      />
                    </span>
                  ) : null}
                </ConsoleToolTimelineRow>
              );
            }

            const message = entry.message;
            const isWebContextMessage = message.messageKind === CONSOLE_WEB_CONTEXT_MESSAGE_KIND;
            const content = (message.content ?? "").trim();
            const summary = (message.summary ?? "").trim();
            const sanitizedSummary = sanitizeConsoleSummary(summary);
            const isSupersededRunningAssistant = isSupersededRunningAssistantMessage(message, content);
            const showAssistantAvatar = entry.id === latestVisibleAvatarAnchorId;
            const assistantAvatar = showAssistantAvatar
              ? resolveAssistantAvatarPresentation(message, motionSetting === "low", pending)
              : null;
            const userAvatarHash = message.role === "USER" ? readConsoleAuthorAvatarHash(message) : null;
            const userAuthorEmail = message.role === "USER" ? readConsoleAuthorEmail(message) : null;
            const shouldShowThinking = (
              message.pendingPlaceholder
              || (message.role === "ASSISTANT" && message.responseStatus === "RUNNING" && !content && !isSupersededRunningAssistant)
            );
            if (isSupersededRunningAssistant) return null;

            return (
              <ConsoleChatMessageRow
                key={message.id}
                role={isWebContextMessage ? "CONTEXT" : message.role}
              >
                <div className={message.role === "ASSISTANT" ? "papyrus-console-message__markdown" : undefined}>
                  {message.role === "USER" ? <ConsoleUserAvatar authorEmail={userAuthorEmail} avatarHash={userAvatarHash} /> : null}
                  {isWebContextMessage ? (
                    <p className="papyrus-console-message__context-label">Page context</p>
                  ) : null}
                  {shouldShowThinking ? (
                    <Shimmer className="papyrus-console__thinking-shimmer">Thinking...</Shimmer>
                  ) : <ConsoleChatMessageContent role={message.role} text={content || sanitizedSummary} />}
                </div>
                {message.responseStatus === "FAILED" ? <span className="papyrus-console-message__error">{message.responseError ?? "Responder failed"}</span> : null}
                {assistantAvatar ? (
                  <span className="papyrus-console-message__assistant-avatar" data-tone={assistantAvatar.tone}>
                    <VultusBotAvatar
                      ariaLabel={assistantAvatar.ariaLabel}
                      lightColor={assistantAvatar.tone === "error" ? ASSISTANT_AVATAR_ERROR_LIGHT_COLOR : ASSISTANT_AVATAR_DEFAULT_LIGHT_COLOR}
                      neutralIdleMode={assistantAvatar.neutralIdleMode}
                      shadowColor={assistantAvatar.tone === "error" ? ASSISTANT_AVATAR_ERROR_SHADOW_COLOR : ASSISTANT_AVATAR_DEFAULT_SHADOW_COLOR}
                      size={ASSISTANT_AVATAR_SIZE_PX}
                      state={assistantAvatar.state}
                      transitionDurationSeconds={0.35}
                    />
                  </span>
                ) : null}
              </ConsoleChatMessageRow>
            );
          })}
        </ConversationContent>
        <ConversationScrollButton
          aria-label="Scroll to latest message"
          className="papyrus-console__scroll-bottom"
        />
      </Conversation>
      {!loading && !sortedMessages.length ? (
        <div className="papyrus-console__suggestions papyrus-console-ui">
          <Suggestions>
            {CONSOLE_STARTER_SUGGESTIONS.map((suggestion) => (
              <Suggestion
                disabled={sending}
                key={suggestion}
                onClick={handleSuggestionClick}
                suggestion={suggestion}
              />
            ))}
          </Suggestions>
        </div>
      ) : null}
      {error ? <p className="papyrus-console__error">{error}</p> : null}
      <PromptInput className="papyrus-console__composer" onSubmit={(message) => void sendMessage(message)}>
        <PromptInputBody>
          <PromptInputTextarea
            aria-label="Console message"
            disabled={sending}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Write a message..."
            rows={3}
            value={draft}
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <ModelSelector
              aria-label="Console model"
              disabled={sending}
              onValueChange={handleModelChange}
              options={CONSOLE_MODEL_OPTIONS.map((option) => ({
                value: option.value,
                label: option.label,
              }))}
              value={selectedModel}
            />
          </PromptInputTools>
          <PromptInputSubmit
            disabled={!draft.trim() || sending}
            status={pending ? "streaming" : "ready"}
          />
        </PromptInputFooter>
      </PromptInput>
    </div>
  );
}

function truncateConsoleSummary(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > 180 ? `${normalized.slice(0, 179)}…` : normalized;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error(message));
    }, timeoutMs);
    promise.then(
      (value) => {
        window.clearTimeout(timeout);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

function upsertConsoleMessage(messages: ConsoleChatMessage[], message: ConsoleChatMessage): ConsoleChatMessage[] {
  const index = messages.findIndex((entry) => entry.id === message.id);
  const next = index >= 0
    ? messages.map((entry, currentIndex) => (
      currentIndex === index
        ? mergeConsoleMessage(entry, message)
        : entry
    ))
    : [...messages, message];
  return next.sort((left, right) => (left.sequenceNumber ?? 0) - (right.sequenceNumber ?? 0) || left.createdAt.localeCompare(right.createdAt));
}

function mergeConsoleMessage(previous: ConsoleChatMessage, incoming: ConsoleChatMessage): ConsoleChatMessage {
  const merged = { ...previous } as Record<string, unknown>;
  for (const [key, value] of Object.entries(incoming)) {
    if (value !== undefined && value !== null) merged[key] = value;
  }
  return merged as ConsoleChatMessage;
}

function isConsoleMessageAfter(message: ConsoleChatMessage, anchor: ConsoleChatMessage): boolean {
  if (message.id === anchor.id) return false;
  if (typeof message.sequenceNumber === "number" && typeof anchor.sequenceNumber === "number") {
    return message.sequenceNumber > anchor.sequenceNumber;
  }
  return message.createdAt >= anchor.createdAt;
}

function isResponderMessageForPendingUser(message: ConsoleChatMessage, pendingUser: ConsoleChatMessage): boolean {
  if (message.id === pendingUser.id) return false;
  if (message.parentMessageId && message.parentMessageId === pendingUser.id) return true;
  if (isConsoleMessageAfter(message, pendingUser)) return true;
  if (
    typeof message.sequenceNumber === "number"
    && typeof pendingUser.sequenceNumber === "number"
    && message.sequenceNumber === pendingUser.sequenceNumber
  ) {
    return message.createdAt >= pendingUser.createdAt;
  }
  return false;
}

function isAwaitingAssistantStatus(status: string | null | undefined): boolean {
  return status === "PENDING" || status === "RUNNING";
}

function sanitizeConsoleSummary(summary: string): string {
  const lowered = summary.trim().toLowerCase();
  if (!lowered) return "";
  if (lowered === "thinking...") return "";
  if (lowered.endsWith("responding.")) return "";
  return summary;
}

function readConsoleAuthorAvatarHash(message: ConsoleChatMessage): string | null {
  const metadata = readAwsJsonObject(message.metadata);
  return (
    readNestedString(metadata, ["console", "author", "avatarHash"])
    ?? readNestedString(metadata, ["author", "avatarHash"])
  );
}

function readConsoleAuthorEmail(message: ConsoleChatMessage): string | null {
  const metadata = readAwsJsonObject(message.metadata);
  return (
    readNestedString(metadata, ["console", "author", "email"])
    ?? readNestedString(metadata, ["author", "email"])
  );
}

function gravatarUrlFromHash(hash: string, size: number): string {
  const normalized = hash.trim().toLowerCase();
  return `https://www.gravatar.com/avatar/${encodeURIComponent(normalized)}?s=${size}&d=404`;
}

async function computeAvatarHashFromEmail(email: string): Promise<string | null> {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return null;
  return computeMd5Hex(normalized);
}

async function computeMd5Hex(value: string): Promise<string> {
  const md5 = new Md5();
  md5.update(new TextEncoder().encode(value));
  const digest = await md5.digest();
  return Array.from(digest)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function ConsoleUserAvatar({ authorEmail, avatarHash }: { authorEmail: string | null; avatarHash: string | null }) {
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => {
    setImageFailed(false);
  }, [avatarHash]);
  const imageUrl = avatarHash ? gravatarUrlFromHash(avatarHash, 64) : null;
  const showImage = Boolean(imageUrl && !imageFailed);
  const tooltip = authorEmail ?? "Email unavailable";

  return (
    <span
      aria-label={`Message author email: ${tooltip}`}
      className="papyrus-console-message__user-avatar"
      role="img"
      title={tooltip}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="papyrus-console-message__user-avatar-image"
          onError={() => setImageFailed(true)}
          src={imageUrl ?? undefined}
        />
      ) : (
        <UserIcon className="papyrus-console-message__user-avatar-icon" size={14} strokeWidth={2} />
      )}
    </span>
  );
}

function resolveAssistantAvatarPresentation(
  entry: DisplayConsoleMessage | ConsoleToolTimelineEntry,
  forceLowMotion: boolean,
  hasActiveResponse: boolean,
): { ariaLabel: string; neutralIdleMode?: "bored-random" | "static"; state: BotAvatarState; tone: AssistantAvatarTone } {
  const failedState = resolveConsoleEntryFailedState(entry);
  if (forceLowMotion) {
    return {
      ariaLabel: "Assistant avatar in low-motion mode",
      neutralIdleMode: "static",
      state: "neutral",
      tone: failedState ? "error" : "default",
    };
  }

  if (failedState) {
    return {
      ariaLabel: "Assistant avatar in error state",
      neutralIdleMode: "static",
      state: "neutral",
      tone: "error",
    };
  }
  if (isToolTimelineEntry(entry) && hasActiveResponse) {
    const toolHasResult = isToolTimelineResultAvailable(entry);
    if (toolHasResult) {
      return {
        ariaLabel: "Assistant avatar while handling tool results",
        state: "toolResponse",
        tone: "default",
      };
    }
    return {
      ariaLabel: "Assistant avatar while calling tools",
      state: "toolCalling",
      tone: "default",
    };
  }
  if (isToolTimelineEntry(entry)) return {
    ariaLabel: "Assistant avatar in neutral state",
    state: "neutral",
    tone: "default",
  };

  const trimmedContent = (entry.content ?? "").trim();
  if (entry.responseStatus === "RUNNING" && !hasActiveResponse) {
    return {
      ariaLabel: "Assistant avatar in neutral state",
      state: "neutral",
      tone: "default",
    };
  }
  if (entry.pendingPlaceholder || (entry.responseStatus === "RUNNING" && !trimmedContent)) {
    return {
      ariaLabel: "Assistant avatar while thinking",
      state: "thinking",
      tone: "default",
    };
  }
  if (entry.responseStatus === "RUNNING" && trimmedContent) {
    return {
      ariaLabel: "Assistant avatar while speaking",
      state: "speakingOpen",
      tone: "default",
    };
  }
  return {
    ariaLabel: "Assistant avatar in neutral state",
    state: "neutral",
    tone: "default",
  };
}

function resolveConsoleEntryFailedState(entry: DisplayConsoleMessage | ConsoleToolTimelineEntry): boolean {
  if (!isToolTimelineEntry(entry)) return entry.responseStatus === "FAILED";
  if (!entry.resultMessage) return false;
  const metadata = readAwsJsonObject(entry.resultMessage.metadata);
  const toolResult = readNestedValue(metadata, ["toolResultJson"]);
  if (toolResult && typeof toolResult === "object" && !Array.isArray(toolResult)) {
    const toolResultObject = toolResult as Record<string, unknown>;
    if (toolResultObject.ok === false) return true;
    if (toolResultObject.error) return true;
  }
  const markdown = entry.resultMessage.content?.toLowerCase() ?? "";
  return /(^|\n)-\s*ok:\s*false\b/.test(markdown);
}

function isToolTimelineEntry(entry: DisplayConsoleMessage | ConsoleToolTimelineEntry): entry is ConsoleToolTimelineEntry {
  return typeof (entry as ConsoleToolTimelineEntry).toolCallId === "string";
}

function isToolTimelineResultAvailable(entry: ConsoleToolTimelineEntry): boolean {
  return Boolean(entry.resultMessage);
}

function ConsoleToolMessageContent({ tool }: { tool: ConsoleToolTimelineEntry }) {
  const callMessage = tool.callMessage;
  const resultMessage = tool.resultMessage;
  const callMetadata = readAwsJsonObject(callMessage?.metadata);
  const resultMetadata = readAwsJsonObject(resultMessage?.metadata);
  const toolState: "input-available" | "output-available" | "output-error" = resultMessage
    ? (resolveConsoleEntryFailedState(tool) ? "output-error" : "output-available")
    : "input-available";
  const toolInput = (
    readNestedValue(callMetadata, ["arguments"])
    ?? callMessage?.content
    ?? null
  );
  const toolResultOutput = resultMessage
    ? (
      readNestedValue(resultMetadata, ["toolResultJson"])
      ?? resultMessage.content
      ?? null
    )
    : null;
  const toolErrorText = toolState === "output-error" && resultMessage
    ? (
      readNestedString(resultMetadata, ["toolResultJson", "error", "message"])
      ?? readNestedString(resultMetadata, ["toolResultJson", "error"])
      ?? resultMessage.content
      ?? "Tool error"
    )
    : undefined;

  return (
    <div className="papyrus-console-tool-row__content">
      <Tool>
        <ToolHeader
          state={toolState}
          toolName={tool.toolName}
          type={`tool-${tool.toolName}`}
        />
        <ToolContent>
          <ToolInput input={toolInput} />
          <ToolOutput
            errorText={toolErrorText}
            output={toolState === "output-error" ? undefined : formatToolOutputText(toolResultOutput)}
          />
        </ToolContent>
      </Tool>
    </div>
  );
}

function ConsoleToolTimelineRow({ children }: { children: ReactNode }) {
  const rowRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const row = rowRef.current;
    if (!row || prefersReducedMotion()) return;
    const tween = gsap.fromTo(
      row,
      { autoAlpha: 0, y: 8 },
      { autoAlpha: 1, y: 0, duration: 0.16, ease: "power2.out", overwrite: "auto" },
    );
    return () => {
      tween.kill();
      gsap.killTweensOf(row);
    };
  }, []);

  return (
    <article className="papyrus-console-tool-row" ref={rowRef}>
      {children}
    </article>
  );
}

function formatToolOutputText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function ConsoleChatMessageContent({ role, text }: { role: string | null | undefined; text: string }) {
  const blocks = useMemo(() => parseConsoleMarkdownBlocks(text), [text]);
  if (role !== "ASSISTANT") return text;
  return (
    <>
      {blocks.map((block, index) => renderConsoleMarkdownBlock(block, index))}
    </>
  );
}

type ConsoleMarkdownBlock =
  | { type: "code"; text: string }
  | { type: "heading"; depth: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; text: string };

function parseConsoleMarkdownBlocks(text: string): ConsoleMarkdownBlock[] {
  const blocks: ConsoleMarkdownBlock[] = [];
  const lines = text.split(/\r?\n/);
  let paragraph: string[] = [];
  let list: string[] = [];
  let listOrdered = false;
  let code: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ type: "paragraph", text: paragraph.join(" ").trim() });
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    blocks.push({ type: "list", ordered: listOrdered, items: list });
    list = [];
  };

  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        blocks.push({ type: "code", text: code.join("\n") });
        code = [];
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", depth: heading[1].length, text: heading[2].trim() });
      continue;
    }
    const bullet = /^([-*+])\s+(.+)$/.exec(trimmed);
    if (bullet) {
      flushParagraph();
      if (!list.length) listOrdered = false;
      list.push(bullet[2].trim());
      continue;
    }
    const ordered = /^\d+[.)]\s+(.+)$/.exec(trimmed);
    if (ordered) {
      flushParagraph();
      if (!list.length) listOrdered = true;
      list.push(ordered[1].trim());
      continue;
    }
    flushList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  if (code.length) blocks.push({ type: "code", text: code.join("\n") });
  return blocks;
}

function renderConsoleMarkdownBlock(block: ConsoleMarkdownBlock, index: number): ReactNode {
  const key = `${block.type}-${index}`;
  if (block.type === "code") return <pre className="papyrus-console-message__code" key={key}>{block.text}</pre>;
  if (block.type === "list") {
    if (block.ordered) {
      return (
        <ol key={key}>
          {block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderConsoleInlineMarkdown(item)}</li>)}
        </ol>
      );
    }
    return (
      <ul key={key}>
        {block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderConsoleInlineMarkdown(item)}</li>)}
      </ul>
    );
  }
  if (block.type === "heading") {
    if (block.depth <= 1) return <h3 key={key}>{renderConsoleInlineMarkdown(block.text)}</h3>;
    if (block.depth === 2) return <h4 key={key}>{renderConsoleInlineMarkdown(block.text)}</h4>;
    return <h5 key={key}>{renderConsoleInlineMarkdown(block.text)}</h5>;
  }
  return <p key={key}>{renderConsoleInlineMarkdown(block.text)}</p>;
}

function renderConsoleInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={`${match.index}-code`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`${match.index}-strong`}>{token.slice(2, -2)}</strong>);
    } else {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (linkMatch) {
        nodes.push(
          <a href={linkMatch[2]} key={`${match.index}-link`} rel="noreferrer noopener" target="_blank">
            {linkMatch[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function ConsoleChatMessageRow({
  role,
  children,
}: {
  role: string | null | undefined;
  children: ReactNode;
}) {
  const rowRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const row = rowRef.current;
    if (!row || prefersReducedMotion()) return;
    const tween = gsap.fromTo(
      row,
      { autoAlpha: 0, y: 8 },
      { autoAlpha: 1, y: 0, duration: 0.16, ease: "power2.out", overwrite: "auto" },
    );
    return () => {
      tween.kill();
      gsap.killTweensOf(row);
    };
  }, []);

  return (
    <article
      className={
        role === "USER"
          ? "papyrus-console-message papyrus-console-message--user"
          : role === "CONTEXT"
            ? "papyrus-console-message papyrus-console-message--context"
            : "papyrus-console-message papyrus-console-message--assistant"
      }
      ref={rowRef}
    >
      {children}
    </article>
  );
}

function ConsoleStreamingAutoStick({ active, streamSignal }: { active: boolean; streamSignal: string | null }) {
  const { scrollRef, scrollToBottom } = useStickToBottomContext();
  const previousSignalRef = useRef<string | null>(null);

  const snapToBottom = useCallback(() => {
    void scrollToBottom({ animation: "instant" });
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;
    scrollElement.scrollTop = Math.max(0, scrollElement.scrollHeight - scrollElement.clientHeight);
  }, [scrollRef, scrollToBottom]);

  useEffect(() => {
    if (!active || !streamSignal) return;
    if (previousSignalRef.current === streamSignal) return;
    previousSignalRef.current = streamSignal;

    snapToBottom();
    const frame = window.requestAnimationFrame(() => {
      snapToBottom();
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [active, snapToBottom, streamSignal]);

  useEffect(() => {
    if (!active) return;
    let frame = 0;
    const pin = () => {
      snapToBottom();
      frame = window.requestAnimationFrame(pin);
    };
    pin();
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [active, snapToBottom]);

  useEffect(() => {
    if (!active) previousSignalRef.current = null;
  }, [active]);

  return null;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function formatConsoleThreadOption(thread: ConsoleChatThread): string {
  const stamp = thread.lastMessageAt ?? thread.updatedAt ?? thread.createdAt;
  const date = stamp ? new Date(stamp) : null;
  const suffix = date && Number.isFinite(date.getTime())
    ? ` — ${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
    : "";
  return `${thread.title || "Papyrus Console"}${suffix}`;
}

function resolveThreadModel(thread: ConsoleChatThread | null): string {
  const metadata = readAwsJsonObject(thread?.metadata);
  const model =
    readNestedString(metadata, ["console", "model"])
    ?? readNestedString(metadata, ["model"]);
  return isSupportedConsoleModel(model) ? model : DEFAULT_CONSOLE_MODEL;
}

function isSupportedConsoleModel(model: unknown): model is string {
  return typeof model === "string" && CONSOLE_MODEL_OPTIONS.some((option) => option.value === model);
}

function readNestedObject(value: Record<string, unknown> | null, key: string): Record<string, unknown> | null {
  if (!value) return null;
  const candidate = value[key];
  return candidate && typeof candidate === "object" && !Array.isArray(candidate)
    ? candidate as Record<string, unknown>
    : null;
}

function readNestedString(value: Record<string, unknown> | null, path: string[]): string | null {
  let cursor: unknown = value;
  for (const key of path) {
    if (!cursor || typeof cursor !== "object" || Array.isArray(cursor)) return null;
    cursor = (cursor as Record<string, unknown>)[key];
  }
  return typeof cursor === "string" && cursor.trim() ? cursor.trim() : null;
}

function readNestedValue(value: Record<string, unknown> | null, path: string[]): unknown {
  let cursor: unknown = value;
  for (const key of path) {
    if (!cursor || typeof cursor !== "object" || Array.isArray(cursor)) return null;
    cursor = (cursor as Record<string, unknown>)[key];
  }
  return cursor ?? null;
}

function readAwsJsonObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  return null;
}

function ConsolePanelHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="papyrus-console__header">
      <p className="papyrus-console__header-label">Chat</p>
      <button className="papyrus-console__close" onClick={onClose} type="button" aria-label="Close console">
        <LucideXIcon />
      </button>
    </header>
  );
}

function LucideXIcon() {
  return (
    <svg
      aria-hidden="true"
      className="papyrus-console__close-icon news-desk-search-mark__icon"
      fill="none"
      focusable="false"
      height="18"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="18"
    >
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  );
}

export function PapyrusConsoleChatIcon() {
  return (
    <svg
      aria-hidden="true"
      className="papyrus-console__icon news-desk-search-mark__icon"
      fill="none"
      focusable="false"
      height="18"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="18"
    >
      <path d="M14 9a2 2 0 0 1-2 2H6.5L3 14V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2Z" />
      <path d="M18 9h1a2 2 0 0 1 2 2v9l-3.5-3H12a2 2 0 0 1-2-2v-1" />
    </svg>
  );
}

function toAwsJson(value: unknown): string {
  return JSON.stringify(value ?? {});
}

function formatUnknownConsoleError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  try {
    const text = JSON.stringify(error);
    if (text && text !== "{}") return text;
  } catch {
    // Ignore serialization failures.
  }
  return "Unable to load console thread.";
}
