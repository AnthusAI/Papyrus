"use client";

import { BookmarkIcon, CheckIcon, ChevronRightIcon, ExternalLinkIcon, InboxIcon, LayoutGridIcon, ListIcon, Loader2Icon, MessageCircleIcon, MessageSquareIcon, MessageSquareTextIcon, MessagesSquareIcon, NewspaperIcon, PencilIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { MessageThreadRecord } from "../lib/category-repository";
import { NO_VIEWER, canRenameThread, conversationAge, conversationAuthorName, conversationPreviewLine, threadLastAuthorLabel, threadMetadataWithLastAuthor, type ConversationMessage, type ConversationViewer } from "../lib/conversation";
import { referenceDisplayTitle } from "../lib/newsroom-references";
import { referenceSourceHost } from "../lib/reference-preview";
import { CONVERSATION_SECTIONS, SECTION_EMPTY_COPY, createMergedThreadStream, sectionOfThreadKind, threadKindsForSection, type ConversationSection } from "../lib/conversation-feed";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { cn } from "@/lib/utils";
import { Composer, ConversationThread } from "./conversation-thread";
import { ListDetailLayout } from "./list-detail-layout";
import type { ConversationReferenceView, ConversationStoryView, ConversationsSource } from "./conversations-source";
import { FEED_GRID, FEED_SURFACE_PROPS, PILL, ReferenceCardHeader } from "./reference-feed";

const PAGE_SIZE = 12;
const LAYOUT_STORAGE_KEY = "papyrus:messages-layout";
const THREAD_PARAM = "thread";
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
function useThreadMessages(source: ConversationsSource, thread: MessageThreadRecord, seed: ConversationMessage[] | undefined, reloadKey: number, viewer: ConversationViewer, onSaved?: (message: ConversationMessage) => void) {
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
      onSaved?.(saved);
    } catch (failure) {
      setMessages((current) => current.filter((message) => message.id !== pendingId));
      throw failure instanceof Error ? failure : new Error("Your message could not be saved.");
    }
  }, [source, thread, onSaved]);
  // Display names come from the authors' profiles, one request for every author not yet asked about.
  const [names, setNames] = useState<ReadonlyMap<string, string>>(() => new Map());
  const asked = useRef(new Set<string>());
  useEffect(() => {
    const missing = [...new Set(messages.map((message) => message.authorUserProfileId).filter((id): id is string => Boolean(id) && !asked.current.has(id as string)))];
    if (!missing.length) return;
    missing.forEach((id) => asked.current.add(id));
    let active = true;
    source.loadAuthors(missing).then((loaded) => { if (active && loaded.size) setNames((current) => new Map([...current, ...loaded])); }).catch(() => undefined);
    return () => { active = false; };
  }, [messages, source]);
  const edit = useCallback(async (messageId: string, body: string) => {
    const saved = await source.edit(messageId, body);
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, ...saved } : message)));
  }, [source]);
  const remove = useCallback(async (messageId: string) => {
    // An admin deleting someone else's message moderates it; everyone else deletes their own.
    const target = messages.find((message) => message.id === messageId);
    const moderate = viewer.isAdmin && target?.authorSub !== viewer.sub;
    const saved = await source.remove(messageId, moderate);
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, ...saved } : message)));
  }, [source, messages, viewer]);
  return { messages, state, error, post, edit, remove, names, retry: () => setAttempt((current) => current + 1) };
}

/** Threads that open in the detail here. Forum threads and chats open their own views. */
function selectableKind(kind: string): boolean {
  const section = sectionOfThreadKind(kind);
  return section === "references" || section === "stories" || kind === "conversation";
}

const CONTROL_FIELD = "block w-full rounded-[var(--feed-radius-md,16px)] border-0 bg-[var(--feed-control)] px-3 py-2 text-sm font-normal leading-5 outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring";
const PILL_QUIET = cn(PILL, "text-muted-foreground hover:bg-[var(--feed-control)]/70 hover:text-foreground");

function relativeActivity(updatedAt: string, now: number): string {
  const age = conversationAge(updatedAt, now);
  return !age ? "" : age === "now" ? "just now" : `${age} ago`;
}

/** What a thread is attached to, as one small line: the Reference's source and headline, or the Story's title and stage. Nothing for an unattached thread. */
function AttachedLine({ lineageId, references, section, stories }: {
  lineageId: string;
  references: ReadonlyMap<string, ConversationReferenceView>;
  section: ReturnType<typeof sectionOfThreadKind>;
  stories: ReadonlyMap<string, ConversationStoryView>;
}) {
  if (section === "references") {
    const view = references.get(lineageId);
    if (!view) return null;
    const site = view.preview?.siteName ?? referenceSourceHost(view.reference);
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground" data-conversation-attached="reference">
        <BookmarkIcon aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="truncate">{site ? `${site} · ` : ""}{referenceDisplayTitle(view.reference)}</span>
      </span>
    );
  }
  if (section === "stories") {
    const story = stories.get(lineageId);
    if (!story) return null;
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground" data-conversation-attached="story">
        <NewspaperIcon aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="truncate">{story.title}{story.stage ? <> · <span data-conversation-stage>Stage: {story.stage}</span></> : null}</span>
      </span>
    );
  }
  return null;
}

/**
 * One conversation as a card (grid) or a line (list). The whole item is one control: a thread opens in the detail, a forum thread
 * opens its own view, a chat opens in the console. Nothing here reads messages: the title, the attachment, the count and the last
 * activity all come from the thread record and the batched headers.
 */
function ThreadItem({ demo, mode, now, onNavigate, onSelect, references, selected, stories, thread }: {
  demo: boolean;
  mode: "grid" | "list";
  now: number;
  onNavigate?: (href: string) => void;
  onSelect: (threadId: string) => void;
  references: ReadonlyMap<string, ConversationReferenceView>;
  selected: boolean;
  stories: ReadonlyMap<string, ConversationStoryView>;
  thread: MessageThreadRecord;
}) {
  const section = sectionOfThreadKind(thread.threadKind);
  const { icon: KindIcon, text: kindText } = kindLabel(thread.threadKind);
  const lineageId = thread.primaryAnchorLineageId ?? "";
  const author = threadLastAuthorLabel(thread.metadata);
  const when = relativeActivity(thread.lastMessageAt ?? thread.updatedAt, now);
  const activity = [author ? conversationAuthorName(author) : null, when].filter(Boolean).join(" · ");
  const preview = (thread.summary ?? "").trim();
  const count = thread.messageCount ?? 0;
  const control = "rounded-[var(--feed-radius-lg,10px)] text-left outline-none after:absolute after:inset-0 after:rounded-[20px] focus-visible:after:ring-[3px] focus-visible:after:ring-ring";
  const opensElsewhere = !selectableKind(thread.threadKind);
  const titleControl = (() => {
    if (section === "chats") {
      return <button className={control} data-conversation-open onClick={() => window.dispatchEvent(new CustomEvent(CONSOLE_SELECT_THREAD_EVENT, { detail: { threadId: thread.id } }))} type="button">{thread.title}</button>;
    }
    if (opensElsewhere) {
      const href = getNewsroomNavHref(`/newsroom/forum/${encodeURIComponent(thread.id)}`, demo);
      return <a className={control} data-conversation-open href={href} onClick={(event) => { if (onNavigate && !event.metaKey && !event.ctrlKey && event.button === 0) { event.preventDefault(); onNavigate(href); } }}>{thread.title}</a>;
    }
    return <button aria-current={selected ? "true" : undefined} className={control} data-conversation-open onClick={() => onSelect(thread.id)} type="button">{thread.title}</button>;
  })();
  const tone = selected ? "bg-[var(--feed-control)]" : "bg-[var(--feed-card)] hover:bg-[var(--feed-control)]/60";
  const countBadge = (
    <span aria-label={`${count} ${count === 1 ? "message" : "messages"}`} className="inline-flex shrink-0 items-center gap-1 text-sm text-muted-foreground" data-conversation-count>
      <MessageSquareIcon aria-hidden="true" className="size-4" />
      {count}
    </span>
  );
  const marker = selected ? (
    <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-foreground" data-conversation-selected><ChevronRightIcon aria-hidden="true" className="size-3.5" />Open</span>
  ) : opensElsewhere ? (
    <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><ExternalLinkIcon aria-hidden="true" className="size-3.5" />{section === "chats" ? "Open chat" : "Open thread"}</span>
  ) : null;

  if (mode === "list") {
    return (
      <article className={cn("relative flex min-w-0 items-center gap-3 rounded-[var(--feed-radius-lg,10px)] px-3 py-2.5 transition-colors", tone)} data-conversation-card={thread.id} data-conversation-kind={thread.threadKind} data-conversation-mode="list">
        <KindIcon aria-label={kindText} className="size-4 shrink-0 text-muted-foreground" role="img" />
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold" data-conversation-title>{titleControl}</h3>
        <span className="hidden min-w-0 max-w-[40%] shrink @[44rem]:flex"><AttachedLine lineageId={lineageId} references={references} section={section} stories={stories} /></span>
        {countBadge}
        {activity ? <span className="hidden shrink-0 truncate text-xs text-muted-foreground @[30rem]:inline" data-conversation-activity>{activity}</span> : null}
        {marker}
      </article>
    );
  }
  return (
    <article className={cn("relative flex flex-col gap-2 rounded-[20px] p-4 transition-colors", tone)} data-conversation-card={thread.id} data-conversation-kind={thread.threadKind} data-conversation-mode="grid">
      <p className={cn(LABEL, "flex items-center justify-between gap-2 text-muted-foreground")} data-conversation-caption>
        <span className="inline-flex items-center gap-1.5"><KindIcon aria-hidden="true" className="size-3.5" />{kindText}</span>
        {marker}
      </p>
      <h3 className="text-base font-semibold leading-snug" data-conversation-title>{titleControl}</h3>
      <AttachedLine lineageId={lineageId} references={references} section={section} stories={stories} />
      {preview ? <p className="line-clamp-2 text-sm text-muted-foreground" data-conversation-preview>{preview}</p> : null}
      <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        {countBadge}
        {activity ? <span className="min-w-0 truncate text-xs text-muted-foreground" data-conversation-activity>{activity}</span> : null}
      </p>
    </article>
  );
}

/** The Reference a conversation is about, under its title: the standard header, no decision controls, and a link to the Reference. */
function ReferenceAttachment({ href, now, onNavigate, thread, view }: { href: string; now: number; onNavigate?: (href: string) => void; thread: MessageThreadRecord; view: ConversationReferenceView | undefined }) {
  const open = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (!onNavigate || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(href);
  };
  return (
    <a
      aria-label={`Open the Reference: ${view ? referenceDisplayTitle(view.reference) : thread.title}`}
      className="flex flex-col overflow-hidden rounded-[var(--feed-radius-lg,10px)] bg-[var(--feed-footer)] text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
      data-conversation-attachment="reference"
      href={href}
      onClick={open}
    >
      {view ? <ReferenceCardHeader now={now} preview={view.preview} reference={view.reference} /> : (
        <span className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><BookmarkIcon aria-hidden="true" className="size-4" />Open the Reference<ExternalLinkIcon aria-hidden="true" className="size-4" /></span>
      )}
    </a>
  );
}

/** The conversation's title, with a Rename button that opens an input in place. A refused save says why and keeps what was typed. */
function ThreadTitle({ canRename, onRename, thread }: { canRename: boolean; onRename: (title: string) => Promise<void>; thread: MessageThreadRecord }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(thread.title);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const next = draft.trim();
    if (!next) { setError("A title cannot be empty."); return; }
    if (next === thread.title) { setEditing(false); return; }
    setSaving(true);
    setError(null);
    try {
      await onRename(next);
      setEditing(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The title could not be saved.");
    } finally {
      setSaving(false);
    }
  };
  const cancel = () => { setEditing(false); setError(null); setDraft(thread.title); };

  if (!editing) {
    return (
      <div className="flex items-start justify-between gap-2" data-conversation-heading>
        <h2 className="min-w-0 break-words text-xl font-bold leading-snug tracking-tight" data-conversation-detail-title>{thread.title}</h2>
        {canRename ? (
          <button className={cn(PILL_QUIET, "shrink-0")} data-conversation-rename onClick={() => { setDraft(thread.title); setEditing(true); }} type="button">
            <PencilIcon aria-hidden="true" className="size-4" />Rename
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-2" data-conversation-heading>
      <input
        aria-label="Conversation title"
        autoFocus
        className={CONTROL_FIELD}
        data-conversation-rename-input
        maxLength={120}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void save(); } else if (event.key === "Escape") cancel(); }}
        value={draft}
      />
      {error ? (
        <p className="flex items-start gap-1.5 text-sm text-destructive" data-conversation-rename-error role="alert">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>Not renamed: {error} Your text is kept here.</span>
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button className={cn(PILL, "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]")} data-conversation-rename-save disabled={saving || !draft.trim()} onClick={() => void save()} type="button">
          {saving ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <CheckIcon aria-hidden="true" className="size-4" />}Save
        </button>
        <button className={PILL_QUIET} data-conversation-rename-cancel onClick={cancel} type="button"><XIcon aria-hidden="true" className="size-4" />Cancel</button>
      </div>
    </div>
  );
}

/** One conversation opened: its own title, what it is about, and every message with its replies. Messages are read only now. */
function ThreadDetail({ demo, now, onNavigate, onPosted, onRename, reloadKey, references, seed, source, stories, thread, viewer }: {
  demo: boolean;
  now: number;
  onNavigate?: (href: string) => void;
  onPosted: (thread: MessageThreadRecord, message: ConversationMessage) => void;
  onRename: (thread: MessageThreadRecord, title: string) => Promise<void>;
  reloadKey: number;
  references: ReadonlyMap<string, ConversationReferenceView>;
  seed: ConversationMessage[] | undefined;
  source: ConversationsSource;
  stories: ReadonlyMap<string, ConversationStoryView>;
  thread: MessageThreadRecord;
  viewer: ConversationViewer;
}) {
  const section = sectionOfThreadKind(thread.threadKind);
  const lineageId = thread.primaryAnchorLineageId ?? "";
  const story = stories.get(lineageId);
  const saved = useCallback((message: ConversationMessage) => onPosted(thread, message), [onPosted, thread]);
  const messages = useThreadMessages(source, thread, seed, reloadKey, viewer, saved);
  const { icon: KindIcon, text: kindText } = kindLabel(thread.threadKind);
  return (
    <div className="space-y-4" data-conversation-detail={thread.id}>
      <p className={cn(LABEL, "inline-flex items-center gap-1.5 text-muted-foreground")}><KindIcon aria-hidden="true" className="size-3.5" />{kindText}</p>
      <ThreadTitle canRename={canRenameThread(viewer, thread)} onRename={(title) => onRename(thread, title)} thread={thread} />
      {section === "references" && lineageId ? (
        <ReferenceAttachment href={getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo)} now={now} onNavigate={onNavigate} thread={thread} view={references.get(lineageId)} />
      ) : null}
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
        authorNames={messages.names}
        error={messages.error}
        heading={`Messages in ${thread.title}`}
        hideHeading
        messages={messages.messages}
        now={now}
        onDelete={messages.remove}
        onEdit={messages.edit}
        onPost={messages.post}
        onRetry={messages.retry}
        state={messages.state}
        viewer={viewer}
      />
    </div>
  );
}

/** The New message box: a required title and the first message. */
function NewConversation({ onStart }: { onStart: (title: string, body: string) => Promise<void> }) {
  const [title, setTitle] = useState("");
  return (
    <section aria-label="New message" className="max-w-2xl space-y-2 rounded-[20px] bg-[var(--feed-card)] p-4" data-conversation-new>
      <h2 className={cn(LABEL, "text-muted-foreground")}>New message</h2>
      <input
        aria-label="Title"
        className={CONTROL_FIELD}
        data-conversation-new-title
        maxLength={120}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Title (required)"
        required
        value={title}
      />
      <Composer
        buttonLabel="Post"
        icon="post"
        label="New message"
        onSubmit={async (body) => { await onStart(title.trim(), body); setTitle(""); }}
        placeholder="The first message… (a thought that is not about any one Reference or Story)"
        postBlockedReason={title.trim() ? null : "Add a title to post."}
      />
    </section>
  );
}

function readLayoutPreference(): "grid" | "list" {
  try { return window.localStorage.getItem(LAYOUT_STORAGE_KEY) === "list" ? "list" : "grid"; } catch { return "grid"; }
}
function writeLayoutPreference(mode: "grid" | "list") {
  try { window.localStorage.setItem(LAYOUT_STORAGE_KEY, mode); } catch { /* remembered for this visit only */ }
}
function readSelectedThread(): string | null {
  try { return new URLSearchParams(window.location.search).get(THREAD_PARAM) || null; } catch { return null; }
}
function writeSelectedThread(threadId: string | null) {
  try {
    const url = new URL(window.location.href);
    if (threadId) url.searchParams.set(THREAD_PARAM, threadId); else url.searchParams.delete(THREAD_PARAM);
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  } catch { /* the address stays as it is */ }
}

/**
 * Every conversation, newest activity first, like a web forum: each thread is one card (grid) or one line (list) with its own title.
 * Opening one shows its whole conversation: beside the list from 1024px, in its place (with Back) below it. The address holds the
 * selection (`?thread=`). Sections are buttons. Reads are one page of thread records plus one batch of headers; messages are read
 * only for the open thread.
 */
export function ConversationsView({ demo = false, onNavigate, source }: {
  demo?: boolean;
  /** Open a link inside the app without a page load. Without it links are ordinary links. */
  onNavigate?: (href: string) => void;
  source: ConversationsSource;
}) {
  const [section, setSection] = useState<ConversationSection>("all");
  const [mode, setMode] = useState<"grid" | "list">("grid");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fetched, setFetched] = useState<MessageThreadRecord | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [viewer, setViewer] = useState<ConversationViewer>(NO_VIEWER);
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
    let active = true;
    source.loadViewer().then((loaded) => { if (active) setViewer(loaded); }).catch(() => undefined);
    return () => { active = false; };
  }, [source]);

  // Preferences and the address are read in the browser only, after the first render.
  useEffect(() => {
    setMode(readLayoutPreference());
    setSelectedId(readSelectedThread());
    const onPop = () => setSelectedId(readSelectedThread());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

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

  // A linked thread that is not on the pages read so far is read by its id.
  const inList = selectedId ? threads.find((thread) => thread.id === selectedId) : undefined;
  useEffect(() => {
    if (!selectedId || loading || inList || fetched?.id === selectedId) return;
    let active = true;
    const dropSelection = (message: string) => { setNotice(message); setSelectedId(null); writeSelectedThread(null); };
    source.loadThread(selectedId).then((thread) => {
      if (!active) return;
      if (thread && selectableKind(thread.threadKind)) { setFetched(thread); enrich([thread]); return; }
      dropSelection("That conversation could not be found.");
    }).catch((failure) => {
      if (active) dropSelection(`That conversation could not be opened. ${failure instanceof Error ? failure.message : ""}`.trim());
    });
    return () => { active = false; };
  }, [enrich, fetched?.id, inList, loading, selectedId, source]);

  const selected = selectedId ? (inList ?? (fetched?.id === selectedId ? fetched : undefined)) : undefined;
  const openable = selected && selectableKind(selected.threadKind) ? selected : undefined;

  const select = (threadId: string | null) => { setNotice(null); setSelectedId(threadId); writeSelectedThread(threadId); };
  const chooseMode = (next: "grid" | "list") => { setMode(next); writeLayoutPreference(next); };

  const patchThread = useCallback((id: string, change: (thread: MessageThreadRecord) => MessageThreadRecord, moveToTop = false) => {
    setFetched((current) => (current?.id === id ? change(current) : current));
    setThreads((current) => {
      const index = current.findIndex((thread) => thread.id === id);
      if (index < 0) return current;
      const changed = change(current[index]);
      return moveToTop ? [changed, ...current.filter((_, at) => at !== index)] : current.map((thread, at) => (at === index ? changed : thread));
    });
  }, []);

  const onPosted = useCallback((thread: MessageThreadRecord, message: ConversationMessage) => {
    patchThread(thread.id, (current) => ({
      ...current,
      messageCount: (current.messageCount ?? 0) + 1,
      lastMessageAt: message.createdAt,
      updatedAt: message.createdAt,
      summary: conversationPreviewLine(message.content),
      metadata: threadMetadataWithLastAuthor(current.metadata, source.authorLabel),
    }), true);
  }, [patchThread, source.authorLabel]);

  const rename = async (thread: MessageThreadRecord, title: string) => {
    const saved = await source.rename(thread, title);
    patchThread(thread.id, (current) => ({ ...current, title: saved.title }));
  };

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

  const startConversation = async (title: string, body: string) => {
    const { thread, message } = await source.start(title, body);
    setSeeds((current) => ({ ...current, [thread.id]: [message] }));
    setThreads((current) => [thread, ...current.filter((entry) => entry.id !== thread.id)]);
  };

  const canStart = section === "all" || section === "other";
  const list = (
    <div className="@container space-y-5" data-conversations-list>
      <div className="flex flex-wrap items-center justify-between gap-3">
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
        <div aria-label="Layout" className="flex gap-1.5" data-conversation-layouts role="group">
          {([["grid", "Grid", LayoutGridIcon], ["list", "List", ListIcon]] as const).map(([key, label, Icon]) => (
            <button
              aria-pressed={mode === key}
              className={cn(PILL, mode === key ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "bg-[var(--feed-control)]/45 text-muted-foreground hover:bg-[var(--feed-control)]/70 hover:text-foreground")}
              data-conversation-layout={key}
              key={key}
              onClick={() => chooseMode(key)}
              type="button"
            >
              <Icon aria-hidden="true" className="size-4" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {canStart ? <NewConversation onStart={startConversation} /> : null}

      {notice ? (
        <p className="flex items-start gap-1.5 text-sm text-muted-foreground" data-conversations-notice role="status">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{notice}</span>
        </p>
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
        <div className={mode === "grid" ? FEED_GRID : "flex flex-col gap-2"} data-conversation-grid={mode === "grid" ? "" : undefined} data-conversation-lines={mode === "list" ? "" : undefined}>
          {threads.map((thread) => (
            <ThreadItem demo={demo} key={thread.id} mode={mode} now={now} onNavigate={onNavigate} onSelect={select} references={references} selected={thread.id === openable?.id} stories={stories} thread={thread} />
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

  return (
    <div data-conversations-view data-conversations-mode={mode} {...FEED_SURFACE_PROPS}>
      <ListDetailLayout
        backLabel="Messages"
        detail={openable ? (
          <ThreadDetail demo={demo} key={openable.id} now={now} onNavigate={onNavigate} onPosted={onPosted} onRename={rename} reloadKey={reloadKey} references={references} seed={seeds[openable.id]} source={source} stories={stories} thread={openable} viewer={viewer} />
        ) : null}
        list={list}
        onBack={() => select(null)}
        open={Boolean(openable)}
      />
    </div>
  );
}
