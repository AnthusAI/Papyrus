"use client";

import { Loader2Icon, MessageSquarePlusIcon, MessagesSquareIcon, ReplyIcon, TriangleAlertIcon, CornerDownRightIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { latestMessages } from "../lib/conversation-feed";
import { buildConversationTree, conversationAge, conversationAuthorName, type ConversationMessage } from "../lib/conversation";
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
export function Composer({ autoFocus = false, buttonLabel, disabledReason, icon, label, onCancel, onSubmit, placeholder }: {
  autoFocus?: boolean;
  buttonLabel: string;
  disabledReason?: string | null;
  icon: "post" | "reply";
  label: string;
  onCancel?: () => void;
  onSubmit: (body: string) => Promise<void>;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const Icon = icon === "post" ? MessageSquarePlusIcon : ReplyIcon;
  const canPost = !disabledReason && draft.trim().length > 0;

  async function submit() {
    const text = draft.trim();
    if (!text || disabledReason) return;
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

function MessageBody({ answers, message, now, onReply, replying, tone }: {
  answers?: string | null;
  message: ConversationMessage;
  now: number;
  onReply: () => void;
  replying: boolean;
  tone: "root" | "reply";
}) {
  return (
    <div className={cn("space-y-1.5 rounded-[var(--feed-radius-md,16px)] p-3", tone === "root" ? "bg-[var(--feed-control)]" : "bg-[var(--feed-footer)]")} data-conversation-message={message.id} data-conversation-pending={message.pending || undefined}>
      <p className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="font-semibold" data-conversation-author>{conversationAuthorName(message.authorLabel)}</span>
        <span className="text-xs text-muted-foreground" data-conversation-age>
          {message.pending ? (
            <span className="inline-flex items-center gap-1"><Loader2Icon aria-hidden="true" className="size-3 animate-spin" />Sending</span>
          ) : conversationAge(message.createdAt, now)}
        </span>
      </p>
      {answers ? (
        <p className="flex items-center gap-1 text-xs text-muted-foreground" data-conversation-answers>
          <CornerDownRightIcon aria-hidden="true" className="size-3" />
          In reply to {answers}
        </p>
      ) : null}
      <p className="whitespace-pre-wrap break-words text-sm leading-5" data-conversation-content>{message.content}</p>
      {!message.pending ? (
        <button aria-expanded={replying} className={cn(PILL_QUIET, "-ml-3")} data-conversation-reply={message.id} onClick={onReply} type="button">
          <ReplyIcon aria-hidden="true" className="size-4" />
          Reply
        </button>
      ) : null}
    </div>
  );
}

/**
 * The Messages of one conversation, replies nested one level under their top-level Message, and a box to add another. It knows
 * nothing about where the Messages come from: the caller loads them and saves a post.
 */
export function ConversationThread({ disabledReason = null, error = null, heading = "Messages", hideHeading = false, latest, messages, now, onPost, onRetry, state = "ready" }: {
  disabledReason?: string | null;
  error?: string | null;
  heading?: string;
  /** Keep the heading for screen readers only (the Messages page labels the card itself). */
  hideHeading?: boolean;
  /** Show only the newest this-many top-level messages (with their replies), and say how many are held back. */
  latest?: number;
  messages: ReadonlyArray<ConversationMessage>;
  now: number;
  onPost: (body: string, parentMessageId: string | null) => Promise<void>;
  onRetry?: () => void;
  state?: ConversationState;
}) {
  const fullTree = useMemo(() => buildConversationTree(messages), [messages]);
  const [showAll, setShowAll] = useState(false);
  const { shown: tree, hidden: hiddenRoots } = latestMessages(fullTree, latest ?? Number.MAX_SAFE_INTEGER, showAll);
  const hiddenCount = hiddenRoots ? messages.length - tree.reduce((sum, root) => sum + 1 + root.replies.length, 0) : 0;
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const authorOf = (id: string) => conversationAuthorName(messages.find((message) => message.id === id)?.authorLabel);
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
            <MessageBody message={root.message} now={now} onReply={() => toggleReply(root.message.id)} replying={replyingTo === root.message.id} tone="root" />
            {root.replies.length || replyingTo === root.message.id ? (
              <ul className="ml-4 space-y-2" data-conversation-replies>
                {root.replies.map((reply) => (
                  <li key={reply.message.id}>
                    <MessageBody answers={reply.answers} message={reply.message} now={now} onReply={() => toggleReply(reply.message.id)} replying={replyingTo === reply.message.id} tone="reply" />
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
