"use client";

import { BookmarkIcon, ExternalLinkIcon, InboxIcon, Loader2Icon, MessageCircleIcon, MessageSquareTextIcon, MessagesSquareIcon, NewspaperIcon, TriangleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { MessageThreadRecord } from "../lib/category-repository";
import { conversationAge, messageCountLabel, type ConversationMessage } from "../lib/conversation";
import { CONVERSATION_SECTIONS, SECTION_EMPTY_COPY, createMergedThreadStream, sectionOfThreadKind, threadKindsForSection, type ConversationSection } from "../lib/conversation-feed";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { cn } from "@/lib/utils";
import { Composer, ConversationThread } from "./conversation-thread";
import type { ConversationReferenceView, ConversationStoryView, ConversationsSource } from "./conversations-source";
import { FEED_GRID, FEED_SURFACE_PROPS, PILL, ReferenceCardHeader } from "./reference-feed";

const PAGE_SIZE = 12;
/** A card shows this many of the newest messages; the rest are one button away. */
const LATEST_MESSAGES = 3;
const STALE_AFTER_MS = 60_000;
const CONSOLE_SELECT_THREAD_EVENT = "papyrus:console-select-thread";
const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";

const SECTION_ICONS = { all: InboxIcon, references: BookmarkIcon, stories: NewspaperIcon, chats: MessageCircleIcon, other: MessagesSquareIcon } as const;

type KindLabel = { icon: typeof BookmarkIcon; text: string };
function kindLabel(kind: string): KindLabel {
  switch (sectionOfThreadKind(kind)) {
    case "references": return { icon: BookmarkIcon, text: "Reference" };
    case "stories": return { icon: NewspaperIcon, text: "Story" };
    case "chats": return { icon: MessageCircleIcon, text: "Chat" };
    default: return kind === "edition_forum" || kind === "section_forum"
      ? { icon: MessagesSquareIcon, text: kind === "edition_forum" ? "Edition forum" : "Section forum" }
      : { icon: MessageSquareTextIcon, text: "Message" };
  }
}

/** One conversation's Messages: loaded once, shown at once when posted, taken back when the save fails. */
function useThreadMessages(source: ConversationsSource, thread: MessageThreadRecord, seed: ConversationMessage[] | undefined, reloadKey: number) {
  const [messages, setMessages] = useState<ConversationMessage[]>(seed ?? []);
  const [state, setState] = useState<"loading" | "ready" | "error">(seed ? "ready" : "loading");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const counter = useRef(0);
  useEffect(() => {
    let active = true;
    source.loadMessages(thread.id).then((loaded) => {
      if (!active) return;
      setMessages((current) => [...loaded, ...current.filter((message) => message.pending)]);
      setState("ready");
      setError(null);
    }).catch((failure) => {
      if (!active) return;
      setError(failure instanceof Error ? failure.message : "The conversation could not be loaded.");
      setState("error");
    });
    return () => { active = false; };
  }, [source, thread.id, reloadKey, attempt]);
  const post = useCallback(async (body: string, parentMessageId: string | null) => {
    counter.current += 1;
    const pendingId = `pending-${counter.current}`;
    const pending: ConversationMessage = { id: pendingId, parentMessageId, authorLabel: source.authorLabel, content: body.trim(), createdAt: new Date().toISOString(), sequenceNumber: Number.MAX_SAFE_INTEGER - 1000 + counter.current, pending: true };
    setMessages((current) => [...current, pending]);
    try {
      const saved = await source.post({ thread, body, parentMessageId });
      setMessages((current) => current.map((message) => (message.id === pendingId ? saved : message)));
    } catch (failure) {
      setMessages((current) => current.filter((message) => message.id !== pendingId));
      throw failure instanceof Error ? failure : new Error("Your message could not be saved.");
    }
  }, [source, thread]);
  return { messages, state, error, post, retry: () => setAttempt((current) => current + 1) };
}

function CardCaption({ kind, now, updatedAt }: { kind: string; now: number; updatedAt: string }) {
  const { icon: Icon, text } = kindLabel(kind);
  const age = conversationAge(updatedAt, now);
  return (
    <p className={cn(LABEL, "flex items-center justify-between gap-2 text-muted-foreground")} data-conversation-caption>
      <span className="inline-flex items-center gap-1.5"><Icon aria-hidden="true" className="size-3.5" />{text}</span>
      {age ? <span className="font-medium normal-case tracking-normal" data-conversation-activity>Active {age === "now" ? "now" : `${age} ago`}</span> : null}
    </p>
  );
}

/** The Reference a conversation is about, as an attachment under its messages: the standard header, no decision controls. */
function ReferenceAttachment({ href, now, onNavigate, thread, view }: { href: string; now: number; onNavigate?: (href: string) => void; thread: MessageThreadRecord; view: ConversationReferenceView | undefined }) {
  const open = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (!onNavigate || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(href);
  };
  return (
    <a
      aria-label={`Open the Reference: ${view?.reference.title ?? thread.title}`}
      className="flex flex-col overflow-hidden rounded-[var(--feed-radius-lg,10px)] bg-[var(--feed-footer)] text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
      data-conversation-attachment="reference"
      href={href}
      onClick={open}
    >
      {view ? <ReferenceCardHeader now={now} preview={view.preview} reference={view.reference} /> : (
        <span className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><BookmarkIcon aria-hidden="true" className="size-4" />{thread.title}<ExternalLinkIcon aria-hidden="true" className="size-4" /></span>
      )}
    </a>
  );
}

function ConversationCard({ demo, now, onNavigate, reloadKey, references, seed, source, stories, thread }: {
  demo: boolean;
  now: number;
  onNavigate?: (href: string) => void;
  reloadKey: number;
  references: ReadonlyMap<string, ConversationReferenceView>;
  seed: ConversationMessage[] | undefined;
  source: ConversationsSource;
  stories: ReadonlyMap<string, ConversationStoryView>;
  thread: MessageThreadRecord;
}) {
  const section = sectionOfThreadKind(thread.threadKind);
  const lineageId = thread.primaryAnchorLineageId ?? "";
  // Forum threads and chats keep their own detail views; every other conversation is read and answered right here.
  const inline = section === "references" || section === "stories" || thread.threadKind === "conversation";
  const messages = useThreadMessages(source, thread, seed, reloadKey);
  const story = stories.get(lineageId);
  const frame = "flex flex-col gap-3 rounded-[20px] bg-[var(--feed-card)] p-4";

  if (!inline) {
    const isChat = section === "chats";
    const href = getNewsroomNavHref(`/newsroom/forum/${encodeURIComponent(thread.id)}`, demo);
    return (
      <article className={frame} data-conversation-card={thread.id} data-conversation-kind={thread.threadKind}>
        <CardCaption kind={thread.threadKind} now={now} updatedAt={thread.updatedAt} />
        <h3 className="text-base font-semibold leading-snug" data-conversation-title>{thread.title}</h3>
        <p className="text-sm text-muted-foreground">{messageCountLabel(thread.messageCount ?? 0)}</p>
        {isChat ? (
          <button className={cn(PILL, "self-start bg-[var(--feed-control)] text-foreground")} data-conversation-open onClick={() => window.dispatchEvent(new CustomEvent(CONSOLE_SELECT_THREAD_EVENT, { detail: { threadId: thread.id } }))} type="button">
            <MessageCircleIcon aria-hidden="true" className="size-4" />Open chat
          </button>
        ) : (
          <a className={cn(PILL, "self-start bg-[var(--feed-control)] text-foreground")} data-conversation-open href={href} onClick={(event) => { if (onNavigate && !event.metaKey && !event.ctrlKey && event.button === 0) { event.preventDefault(); onNavigate(href); } }}>
            <MessagesSquareIcon aria-hidden="true" className="size-4" />Open thread
          </a>
        )}
      </article>
    );
  }

  return (
    <article className={frame} data-conversation-card={thread.id} data-conversation-kind={thread.threadKind}>
      <CardCaption kind={thread.threadKind} now={now} updatedAt={thread.updatedAt} />
      {section === "stories" ? (
        <div className="space-y-1 rounded-[var(--feed-radius-lg,10px)] bg-[var(--feed-footer)] p-3" data-conversation-story>
          <p className="text-base font-semibold leading-snug">{story?.title ?? thread.title}</p>
          <p className="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
            {story?.stage ? <span data-conversation-stage>Stage: {story.stage}</span> : null}
            <a className="inline-flex items-center gap-1 underline-offset-2 hover:underline" href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(lineageId)}`, demo)}>
              <ExternalLinkIcon aria-hidden="true" className="size-3.5" />Open the Story
            </a>
          </p>
        </div>
      ) : null}
      <ConversationThread
        error={messages.error}
        heading={`Messages in ${thread.title}`}
        hideHeading
        latest={LATEST_MESSAGES}
        messages={messages.messages}
        now={now}
        onPost={messages.post}
        onRetry={messages.retry}
        state={messages.state}
      />
      {section === "references" && lineageId ? (
        <ReferenceAttachment href={getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo)} now={now} onNavigate={onNavigate} thread={thread} view={references.get(lineageId)} />
      ) : null}
    </article>
  );
}

/**
 * Every conversation, newest activity first, as cards in a grid. Messages lead each card; the Reference or Story it is about is an
 * attachment under them. Sections are buttons. Reads page by page from the thread indexes: nothing is loaded that is not shown.
 */
export function ConversationsView({ demo = false, onNavigate, source }: {
  demo?: boolean;
  /** Open a link inside the app without a page load. Without it links are ordinary links. */
  onNavigate?: (href: string) => void;
  source: ConversationsSource;
}) {
  const [section, setSection] = useState<ConversationSection>("all");
  const [threads, setThreads] = useState<MessageThreadRecord[]>([]);
  const [seeds, setSeeds] = useState<Record<string, ConversationMessage[]>>({});
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [references, setReferences] = useState<ReadonlyMap<string, ConversationReferenceView>>(() => new Map());
  const [stories, setStories] = useState<ReadonlyMap<string, ConversationStoryView>>(() => new Map());
  const [reloadKey, setReloadKey] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const loadedAt = useRef(Date.now());
  const stream = useRef<ReturnType<typeof createMergedThreadStream<MessageThreadRecord>> | null>(null);
  const generation = useRef(0);

  const enrich = useCallback((page: MessageThreadRecord[]) => {
    const referenceIds = page.filter((thread) => thread.threadKind === "reference_conversation" && thread.primaryAnchorLineageId).map((thread) => thread.primaryAnchorLineageId!);
    const storyIds = page.filter((thread) => thread.threadKind === "story_conversation" && thread.primaryAnchorLineageId).map((thread) => thread.primaryAnchorLineageId!);
    if (referenceIds.length) void source.loadReferences(referenceIds).then((loaded) => setReferences((current) => new Map([...current, ...loaded]))).catch(() => undefined);
    if (storyIds.length) void source.loadStories(storyIds).then((loaded) => setStories((current) => new Map([...current, ...loaded]))).catch(() => undefined);
  }, [source]);

  useEffect(() => {
    const mine = ++generation.current;
    stream.current = createMergedThreadStream(threadKindsForSection(section), source.loadThreads);
    setLoading(true);
    setError(null);
    stream.current.next(PAGE_SIZE).then((page) => {
      if (generation.current !== mine) return;
      setThreads(page.items);
      setHasMore(page.hasMore);
      setLoading(false);
      loadedAt.current = Date.now();
      enrich(page.items);
    }).catch((failure) => {
      if (generation.current !== mine) return;
      setError(failure instanceof Error ? failure.message : "Conversations could not be loaded.");
      setLoading(false);
    });
  }, [enrich, section, source, reloadKey]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    // Nothing subscribes: the page catches up when it is looked at again.
    const refocus = () => { if (document.visibilityState !== "hidden" && Date.now() - loadedAt.current > STALE_AFTER_MS) setReloadKey((current) => current + 1); };
    window.addEventListener("focus", refocus);
    document.addEventListener("visibilitychange", refocus);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refocus); document.removeEventListener("visibilitychange", refocus); };
  }, []);

  const loadMore = async () => {
    if (!stream.current || loadingMore) return;
    const mine = generation.current;
    setLoadingMore(true);
    try {
      const page = await stream.current.next(PAGE_SIZE);
      if (generation.current !== mine) return;
      setThreads((current) => [...current, ...page.items.filter((thread) => !current.some((entry) => entry.id === thread.id))]);
      setHasMore(page.hasMore);
      enrich(page.items);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "More conversations could not be loaded.");
    } finally {
      setLoadingMore(false);
    }
  };

  const startConversation = async (body: string) => {
    const { thread, message } = await source.start(body);
    setSeeds((current) => ({ ...current, [thread.id]: [message] }));
    setThreads((current) => [thread, ...current.filter((entry) => entry.id !== thread.id)]);
  };

  const canStart = section === "all" || section === "other";
  return (
    <div className="@container space-y-5" data-conversations-view {...FEED_SURFACE_PROPS}>
      <div aria-label="Conversations" className="flex flex-wrap gap-1.5" data-conversation-sections role="group">
        {CONVERSATION_SECTIONS.map(({ key, label }) => {
          const Icon = SECTION_ICONS[key];
          const on = section === key;
          return (
            <button
              aria-pressed={on}
              className={cn(PILL, on ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "bg-[var(--feed-control)]/45 text-muted-foreground hover:bg-[var(--feed-control)]/70 hover:text-foreground")}
              data-conversation-section={key}
              key={key}
              onClick={() => setSection(key)}
              type="button"
            >
              <Icon aria-hidden="true" className="size-4" />
              {label}
            </button>
          );
        })}
      </div>

      {canStart ? (
        <section aria-label="New message" className="max-w-2xl space-y-2 rounded-[20px] bg-[var(--feed-card)] p-4" data-conversation-new>
          <h2 className={cn(LABEL, "text-muted-foreground")}>New message</h2>
          <Composer buttonLabel="Post" icon="post" label="New message" onSubmit={startConversation} placeholder="New message… (a thought that is not about any one Reference or Story)" />
        </section>
      ) : null}

      {loading ? <p className="flex items-center gap-1.5 text-sm text-muted-foreground" data-conversations-loading role="status"><Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Loading conversations</p> : null}
      {error ? (
        <p className="flex items-start gap-1.5 text-sm text-destructive" data-conversations-error role="alert">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>Conversations could not be loaded. {error}</span>
        </p>
      ) : null}
      {!loading && !error && !threads.length ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" data-conversations-empty>
          <InboxIcon aria-hidden="true" className="size-4" />
          {SECTION_EMPTY_COPY[section]}
        </p>
      ) : null}

      {threads.length ? (
        <div className={FEED_GRID} data-conversation-grid>
          {threads.map((thread) => (
            <ConversationCard demo={demo} key={thread.id} now={now} onNavigate={onNavigate} reloadKey={reloadKey} references={references} seed={seeds[thread.id]} source={source} stories={stories} thread={thread} />
          ))}
        </div>
      ) : null}
      {hasMore ? (
        <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-conversations-more disabled={loadingMore} onClick={() => void loadMore()} type="button">
          {loadingMore ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : null}
          Show more conversations
        </button>
      ) : null}
    </div>
  );
}
