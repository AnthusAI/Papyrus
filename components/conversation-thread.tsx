"use client";

import { BanIcon, CheckIcon, Loader2Icon, MessageSquarePlusIcon, MessagesSquareIcon, PencilIcon, ReplyIcon, Trash2Icon, TriangleAlertIcon, CornerDownRightIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { latestMessages } from "../lib/conversation-feed";
import { buildConversationTree, canDeleteMessage, canEditMessage, conversationAge, messageAuthorName, type ConversationMessage, type ConversationViewer } from "../lib/conversation";
import { cn } from "@/lib/utils";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";
import type { ConversationState } from "./use-conversation";

/** The decision control's register: caption labels, md corners, a tone and never an outline. */
const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";
const PILL = "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-[var(--feed-radius-md,16px)] px-3.5 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]";
const PILL_PRIMARY = cn(PILL, "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]");
const PILL_QUIET = cn(PILL, "text-muted-foreground hover:bg-[var(--feed-control)]/70 hover:text-foreground");

/**
 * A box for writing a Message. The text clears the moment you post, so the Message shows at once; if the save fails the text comes
 * back (unless you have typed something new) with the reason, and nothing you wrote is lost.
 */
export function Composer({ autoFocus = false, buttonLabel, disabledReason, icon, label, onCancel, onSubmit, placeholder, postBlockedReason }: {
  autoFocus?: boolean;
  buttonLabel: string;
  disabledReason?: string | null;
  /** Something else the post needs first (a title): the box stays open for writing, the button waits, and the reason is said in words. */
  postBlockedReason?: string | null;
  icon: "post" | "reply";
  label: string;
  onCancel?: () => void;
  onSubmit: (body: string) => Promise<void>;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const Icon = icon === "post" ? MessageSquarePlusIcon : ReplyIcon;
  const canPost = !disabledReason && !postBlockedReason && draft.trim().length > 0;

  async function submit() {
    const text = draft.trim();
    if (!text || disabledReason || postBlockedReason) return;
    setDraft("");
    setError(null);
    try {
      await onSubmit(text);
      onCancel?.();
    } catch (failure) {
      setDraft((current) => current || text);
      setError(failure instanceof Error ? failure.message : "Your message could not be saved.");
    }
  }

  return (
    <div className="space-y-2" data-conversation-composer={icon}>
      <AutoGrowTextarea
        aria-label={label}
        autoFocus={autoFocus}
        className="block min-h-16 w-full rounded-[var(--feed-radius-md,16px)] border-0 bg-[var(--feed-control)] px-3 py-2 text-sm font-normal leading-5 outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring"
        disabled={Boolean(disabledReason)}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void submit(); } }}
        placeholder={placeholder}
        value={draft}
      />
      {error ? (
        <p className="flex items-start gap-1.5 text-sm text-destructive" data-conversation-error role="alert">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>Not posted: {error} Your text is kept here.</span>
        </p>
      ) : null}
      {disabledReason ? <p className="text-sm text-muted-foreground">{disabledReason}</p> : null}
      {postBlockedReason && draft.trim() ? <p className="text-sm text-muted-foreground" data-conversation-blocked>{postBlockedReason}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <button className={PILL_PRIMARY} data-conversation-post={icon} disabled={!canPost} onClick={() => void submit()} type="button">
          <Icon aria-hidden="true" className="size-4" />
          {buttonLabel}
        </button>
        {onCancel ? <button className={PILL_QUIET} onClick={onCancel} type="button">Cancel</button> : null}
      </div>
    </div>
  );
}

type Mode = "view" | "editing" | "confirming";

function MessageBody({ answers, authorNames, message, now, onDelete, onEdit, onReply, replying, tone, viewer }: {
  answers?: string | null;
  authorNames?: ReadonlyMap<string, string>;
  message: ConversationMessage;
  now: number;
  onDelete?: (id: string) => Promise<void>;
  onEdit?: (id: string, body: string) => Promise<void>;
  onReply: () => void;
  replying: boolean;
  tone: "root" | "reply";
  viewer?: ConversationViewer;
}) {
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState(message.content);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canEdit = Boolean(onEdit) && canEditMessage(viewer, message);
  const canDelete = Boolean(onDelete) && canDeleteMessage(viewer, message);
  const frame = cn("space-y-1.5 rounded-[var(--feed-radius-md,16px)] p-3", tone === "root" ? "bg-[var(--feed-control)]" : "bg-[var(--feed-footer)]");

  if (message.deleted) {
    return (
      <div className={frame} data-conversation-message={message.id} data-conversation-deleted="true">
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground" data-conversation-content>
          <BanIcon aria-hidden="true" className="size-4" />
          Message deleted
        </p>
      </div>
    );
  }

  const stop = () => { setMode("view"); setError(null); setDraft(message.content); };
  async function save() {
    const text = draft.trim();
    if (!text) { setError("A message cannot be empty."); return; }
    if (text === message.content.trim()) { stop(); return; }
    setBusy(true);
    setError(null);
    try {
      await onEdit!(message.id, text);
      setMode("view");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The message could not be saved.");
    } finally {
      setBusy(false);
    }
  }
  async function confirmDelete() {
    setBusy(true);
    setError(null);
    try {
      await onDelete!(message.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The message could not be deleted.");
      setBusy(false);
    }
  }
  const failure = error ? (
    <p className="flex items-start gap-1.5 text-sm text-destructive" data-conversation-action-error role="alert">
      <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{mode === "editing" ? `Not saved: ${error} Your text is kept here.` : `Not deleted: ${error}`}</span>
    </p>
  ) : null;

  return (
    <div className={frame} data-conversation-message={message.id} data-conversation-pending={message.pending || undefined}>
      <p className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="font-semibold" data-conversation-author>{messageAuthorName(message, authorNames)}</span>
        <span className="text-xs text-muted-foreground" data-conversation-age>
          {message.pending ? (
            <span className="inline-flex items-center gap-1"><Loader2Icon aria-hidden="true" className="size-3 animate-spin" />Sending</span>
          ) : conversationAge(message.createdAt, now)}
        </span>
        {message.editedAt && !message.pending ? <span className="text-xs text-muted-foreground" data-conversation-edited>edited {conversationAge(message.editedAt, now) === "now" ? "just now" : `${conversationAge(message.editedAt, now)} ago`}</span> : null}
      </p>
      {answers ? (
        <p className="flex items-center gap-1 text-xs text-muted-foreground" data-conversation-answers>
          <CornerDownRightIcon aria-hidden="true" className="size-3" />
          In reply to {answers}
        </p>
      ) : null}
      {mode === "editing" ? (
        <div className="space-y-2" data-conversation-editing>
          <AutoGrowTextarea
            aria-label="Edit your message"
            autoFocus
            className="block min-h-16 w-full rounded-[var(--feed-radius-md,16px)] border-0 bg-[var(--feed-card)] px-3 py-2 text-sm font-normal leading-5 outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") stop(); else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void save(); } }}
            value={draft}
          />
          {failure}
          <div className="flex flex-wrap gap-2">
            <button className={PILL_PRIMARY} data-conversation-edit-save disabled={busy || !draft.trim()} onClick={() => void save()} type="button">
              {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <CheckIcon aria-hidden="true" className="size-4" />}Save
            </button>
            <button className={PILL_QUIET} data-conversation-edit-cancel disabled={busy} onClick={stop} type="button"><XIcon aria-hidden="true" className="size-4" />Cancel</button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm leading-5" data-conversation-content>{message.content}</p>
      )}
      {mode === "confirming" ? (
        <div className="space-y-2" data-conversation-confirm>
          <p className="flex items-center gap-1.5 text-sm font-medium"><Trash2Icon aria-hidden="true" className="size-4" />Delete this message?</p>
          {failure}
          <div className="flex flex-wrap gap-2">
            <button className={cn(PILL, "bg-[var(--feed-card)] font-semibold text-destructive")} data-conversation-delete-confirm disabled={busy} onClick={() => void confirmDelete()} type="button">
              {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <Trash2Icon aria-hidden="true" className="size-4" />}Delete
            </button>
            <button className={PILL_QUIET} data-conversation-delete-keep disabled={busy} onClick={stop} type="button"><XIcon aria-hidden="true" className="size-4" />Keep</button>
          </div>
        </div>
      ) : null}
      {mode === "view" && !message.pending ? (
        <div className="flex flex-wrap items-center gap-x-1">
          <button aria-expanded={replying} className={cn(PILL_QUIET, "-ml-3")} data-conversation-reply={message.id} onClick={onReply} type="button">
            <ReplyIcon aria-hidden="true" className="size-4" />
            Reply
          </button>
          {canEdit ? (
            <button className={PILL_QUIET} data-conversation-edit={message.id} onClick={() => { setDraft(message.content); setMode("editing"); }} type="button">
              <PencilIcon aria-hidden="true" className="size-4" />
              Edit
            </button>
          ) : null}
          {canDelete ? (
            <button className={PILL_QUIET} data-conversation-delete={message.id} onClick={() => setMode("confirming")} type="button">
              <Trash2Icon aria-hidden="true" className="size-4" />
              Delete
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The Messages of one conversation, replies nested one level under their top-level Message, and a box to add another. It knows
 * nothing about where the Messages come from: the caller loads them and saves a post.
 */
export function ConversationThread({ authorNames, disabledReason = null, error = null, heading = "Messages", hideHeading = false, latest, messages, now, onDelete, onEdit, onPost, onRetry, state = "ready", viewer }: {
  /** Display names by author profile id. */
  authorNames?: ReadonlyMap<string, string>;
  disabledReason?: string | null;
  error?: string | null;
  heading?: string;
  /** Keep the heading for screen readers only (the Messages page labels the card itself). */
  hideHeading?: boolean;
  /** Show only the newest this-many top-level messages (with their replies), and say how many are held back. */
  latest?: number;
  messages: ReadonlyArray<ConversationMessage>;
  now: number;
  /** Without these (or without a viewer) no Message offers Edit or Delete. */
  onDelete?: (messageId: string) => Promise<void>;
  onEdit?: (messageId: string, body: string) => Promise<void>;
  onPost: (body: string, parentMessageId: string | null) => Promise<void>;
  onRetry?: () => void;
  state?: ConversationState;
  viewer?: ConversationViewer;
}) {
  const fullTree = useMemo(() => buildConversationTree(messages, (message) => messageAuthorName(message, authorNames)), [messages, authorNames]);
  const [showAll, setShowAll] = useState(false);
  const { shown: tree, hidden: hiddenRoots } = latestMessages(fullTree, latest ?? Number.MAX_SAFE_INTEGER, showAll);
  const hiddenCount = hiddenRoots ? messages.length - tree.reduce((sum, root) => sum + 1 + root.replies.length, 0) : 0;
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const authorOf = (id: string) => { const found = messages.find((message) => message.id === id); return found ? messageAuthorName(found, authorNames) : "Someone"; };
  const toggleReply = (id: string) => setReplyingTo((current) => (current === id ? null : id));

  return (
    <section aria-label={heading} className="space-y-3" data-conversation-thread>
      <h3 className={cn(LABEL, "text-muted-foreground", hideHeading && "sr-only")}>{heading}</h3>
      {state === "loading" ? <p className="flex items-center gap-1.5 text-sm text-muted-foreground" data-conversation-loading><Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Loading messages</p> : null}
      {state === "error" ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert">
          <TriangleAlertIcon aria-hidden="true" className="size-4" />
          Messages could not be loaded. {error}
          {onRetry ? <button className={PILL_QUIET} onClick={onRetry} type="button">Try again</button> : null}
        </p>
      ) : null}
      {state === "ready" && !tree.length ? <p className="text-sm text-muted-foreground" data-conversation-empty>No messages yet. Write down what this made you think.</p> : null}
      {hiddenCount > 0 ? (
        <button className={cn(PILL_QUIET, "w-full bg-[var(--feed-control)]/45")} data-conversation-show-all onClick={() => setShowAll(true)} type="button">
          <MessagesSquareIcon aria-hidden="true" className="size-4" />
          Show all {messages.length} messages
        </button>
      ) : null}
      <ul className="space-y-3">
        {tree.map((root) => (
          <li className="space-y-2" key={root.message.id}>
            <MessageBody authorNames={authorNames} message={root.message} now={now} onDelete={onDelete} onEdit={onEdit} onReply={() => toggleReply(root.message.id)} replying={replyingTo === root.message.id} tone="root" viewer={viewer} />
            {root.replies.length || replyingTo === root.message.id ? (
              <ul className="ml-4 space-y-2" data-conversation-replies>
                {root.replies.map((reply) => (
                  <li key={reply.message.id}>
                    <MessageBody answers={reply.answers} authorNames={authorNames} message={reply.message} now={now} onDelete={onDelete} onEdit={onEdit} onReply={() => toggleReply(reply.message.id)} replying={replyingTo === reply.message.id} tone="reply" viewer={viewer} />
                    {replyingTo === reply.message.id ? (
                      <div className="mt-2">
                        <Composer autoFocus buttonLabel="Reply" disabledReason={disabledReason} icon="reply" label={`Reply to ${authorOf(reply.message.id)}`} onCancel={() => setReplyingTo(null)} onSubmit={(body) => onPost(body, reply.message.id)} placeholder={`Reply to ${authorOf(reply.message.id)}…`} />
                      </div>
                    ) : null}
                  </li>
                ))}
                {replyingTo === root.message.id ? (
                  <li>
                    <Composer autoFocus buttonLabel="Reply" disabledReason={disabledReason} icon="reply" label={`Reply to ${authorOf(root.message.id)}`} onCancel={() => setReplyingTo(null)} onSubmit={(body) => onPost(body, root.message.id)} placeholder={`Reply to ${authorOf(root.message.id)}…`} />
                  </li>
                ) : null}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
      <Composer buttonLabel="Post" disabledReason={disabledReason} icon="post" label="Add a message" onSubmit={(body) => onPost(body, null)} placeholder="Add a message…" />
    </section>
  );
}
