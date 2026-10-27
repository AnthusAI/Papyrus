"use client";

import { CheckIcon, CircleCheckIcon, CircleXIcon, ClockIcon, ExternalLinkIcon, FileSearchIcon, FileTextIcon, FlagIcon, LockIcon, MessageSquarePlusIcon } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { draftPicture, requestCaption, sourceHost, type DraftItem, type RecentDecision, type RequestItem } from "../lib/notification-feed";
import { cannotMoveReason, type DraftChoice } from "../lib/review-drafts";
import { answerWords, formatWhen, modeLabel, nextText, steeringText, subjectHref, subjectLabel, type ReviewRequest } from "../lib/review-requests";
import type { ReferencePreview } from "../lib/reference-preview";
import { FEED_SURFACE_PROPS, FeedImage, PILL, SourceMark } from "./reference-feed";
import { RatingGrid } from "./review-rating-grid";

/** What the editor typed with an answer. */
export type DecisionExtras = { why: string; notThisKind: boolean };

const CHIP = "inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-2.5 text-xs font-medium text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-2 focus-visible:ring-ring";
const CARD = "flex flex-col overflow-hidden rounded-[20px] bg-[var(--feed-card)] text-card-foreground";
const PILL_BUTTON = cn(PILL, "min-h-9 bg-[var(--feed-control)] px-3.5 text-foreground hover:bg-[var(--feed-control)]/70");

/** Pulsing placeholder cards in the shape of the real ones, on screen the moment the page opens. */
export function NotificationSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading what needs you" className="space-y-6" data-notification-skeleton role="status" {...FEED_SURFACE_PROPS}>
      <div className="space-y-3">
        <div className="h-8 w-2/3 max-w-md animate-pulse rounded-full bg-[var(--feed-control)]" />
        <div className="h-4 w-1/3 max-w-xs animate-pulse rounded-full bg-[var(--feed-control)]" />
      </div>
      <div className="flex gap-2">
        {[0, 1, 2, 3].map((index) => <div className="h-9 w-24 animate-pulse rounded-full bg-[var(--feed-control)]" key={index} />)}
      </div>
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: count }, (_, index) => (
          <div className={CARD} key={index}>
            <div className="aspect-[16/10] animate-pulse bg-[var(--feed-control)]" />
            <div className="space-y-3 p-5">
              <div className="h-3 w-1/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="h-5 w-11/12 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="h-5 w-2/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="h-3 w-1/2 animate-pulse rounded-full bg-[var(--feed-control)]" />
            </div>
            <div className="flex gap-2 bg-[var(--feed-footer)] p-3">
              <div className="h-12 flex-1 animate-pulse rounded-[16px] bg-[var(--feed-control)]" />
              <div className="h-12 flex-1 animate-pulse rounded-[16px] bg-[var(--feed-control)]" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function WhyField({ onChange, placeholder, readOnly, value }: { onChange: (value: string) => void; placeholder: string; readOnly: boolean; value: string }) {
  return (
    <textarea
      aria-label="Why? (optional)"
      className="block min-h-16 w-full resize-y rounded-[16px] bg-[var(--feed-control)] p-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      readOnly={readOnly}
      value={value}
    />
  );
}

export function DecidedLine({ choice, notThisKind, why }: { choice: DraftChoice; notThisKind?: boolean; why?: string | null }) {
  const Icon = choice === "accept" ? CircleCheckIcon : CircleXIcon;
  return (
    <p className="flex items-start gap-1.5 text-sm font-medium" data-draft-decided={choice}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="break-words">
        {choice === "accept" ? "Accepted" : "Rejected"}{choice === "reject" && notThisKind ? " as not this kind" : ""}
        {why ? <span className="font-normal text-muted-foreground">: {why}</span> : null}
      </span>
    </p>
  );
}

/**
 * The footer every decidable card shares: an optional full-width Why?, the shared Accept / Reject grid, and (on Reject) the one
 * question the AI learns from. Once decided it keeps the answer on screen, says in words that it is final here, and says where to change it.
 */
function DecisionFooter({ busy, decision, disabledReason, error, kind, lockedNote, onDecide, placeholder }: {
  busy: boolean;
  decision: { choice: DraftChoice; why?: string | null; notThisKind?: boolean } | null;
  disabledReason: string | null;
  error: string | null;
  kind: "story" | "thing";
  lockedNote: ReactNode;
  onDecide: (choice: DraftChoice, extras: DecisionExtras) => void;
  placeholder: string;
}) {
  const [why, setWhy] = useState("");
  const [notThisKind, setNotThisKind] = useState(false);
  const [pending, setPending] = useState<DraftChoice | null>(null);
  const locked = decision !== null;
  const choose = (choice: DraftChoice) => {
    if (locked || busy || disabledReason) return;
    setPending(choice);
    onDecide(choice, { why: why.trim(), notThisKind: choice === "reject" && notThisKind });
  };
  return (
    <div className="space-y-2.5 bg-[var(--feed-footer)] p-3" data-feed-actions {...(locked ? {} : { "data-review-controls": "" })}>
      {locked ? (
        <>
          <DecidedLine choice={decision.choice} notThisKind={decision.notThisKind} why={decision.why} />
          <RatingGrid
            answer={decision.choice} disabled disabledReason={null} feedback={{ phase: "saved" }} onChoose={() => undefined}
            prediction={{ state: "none" }} showPrediction={false} surface="footer"
          />
          <p className="text-xs text-muted-foreground" data-review-disabled-reason>{lockedNote}</p>
        </>
      ) : (
        <>
          <WhyField onChange={setWhy} placeholder={placeholder} readOnly={busy} value={why} />
          <div className="flex flex-wrap items-center gap-2" data-review-reasons>
            <button
              aria-disabled={busy || undefined}
              aria-pressed={notThisKind}
              className={cn(PILL, "min-h-8 px-3 text-xs", notThisKind ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "bg-[var(--feed-control)]/60 text-muted-foreground hover:text-foreground")}
              data-review-reason="not_this_kind"
              onClick={() => { if (!busy) setNotThisKind((current) => !current); }}
              type="button"
            >
              {notThisKind ? <CheckIcon aria-hidden="true" className="size-3.5" /> : null}
              {kind === "story" ? "Not this kind of story" : "Not this kind of thing"}
            </button>
            <span className="text-xs text-muted-foreground">Optional. Counts if you reject.</span>
          </div>
          <RatingGrid
            answer={busy ? pending : null}
            disabled={Boolean(disabledReason)}
            disabledReason={disabledReason}
            feedback={busy ? { phase: "saving" } : error ? { phase: "error", message: error } : { phase: "idle" }}
            onChoose={choose}
            prediction={{ state: "none" }}
            showPrediction={false}
            surface="footer"
          />
        </>
      )}
    </div>
  );
}

/** One AI story draft as a feed card: the cited source's picture, headline, dek, section, evidence, cited sources, then Accept or Reject. */
export function DraftCard({ busy, demo: _demo, error, item, onDecide, previews, session }: {
  busy: boolean;
  demo?: boolean;
  error: string | null;
  item: DraftItem;
  onDecide: (draftId: string, choice: DraftChoice, extras: DecisionExtras) => void;
  previews: ReadonlyMap<string, ReferencePreview>;
  /** Words for why answering is not possible yet (for example while the session is confirmed), or null. */
  session: string | null;
}) {
  const { view, decision, draftId, request } = item;
  const link = request.links.find((entry) => entry.id === draftId);
  if (!view) {
    return (
      <article aria-busy="true" className={CARD} data-draft-state="loading" data-review-draft={draftId} role="status" {...FEED_SURFACE_PROPS}>
        <div className="aspect-[16/10] animate-pulse bg-[var(--feed-control)]" />
        <div className="space-y-3 p-5">
          <p className="text-xs text-muted-foreground">{link?.label ?? "Draft"}: loading the draft…</p>
          <div className="h-5 w-11/12 animate-pulse rounded-full bg-[var(--feed-control)]" />
          <div className="h-5 w-2/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
        </div>
      </article>
    );
  }
  const picture = draftPicture(view, previews);
  const hasSource = view.sources.some((source) => source.url);
  const hold = cannotMoveReason(view);
  return (
    <article
      className={cn(CARD, decision && "opacity-95")}
      data-draft-decided-card={decision?.choice}
      data-draft-state={decision ? "decided" : "open"}
      data-review-draft={draftId}
      data-review-request={request.id}
      {...FEED_SURFACE_PROPS}
    >
      {hasSource ? <FeedImage host={picture.host} lead={false} name={picture.siteName ?? picture.host ?? "Source"} src={picture.imageUrl} /> : null}
      <div className="flex flex-1 flex-col gap-2.5 p-5">
        <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground" data-draft-kind>
          <FileTextIcon aria-hidden="true" className="size-3.5 shrink-0" />
          <span>AI {view.kindLabel.toLowerCase()}{view.section ? ` · Section: ${view.section}` : ""}</span>
        </p>
        <h3 className="break-words text-xl font-bold leading-[1.15] tracking-tight text-foreground" data-draft-headline>{view.headline}</h3>
        {view.dek ? <p className="line-clamp-4 break-words text-sm text-muted-foreground" data-draft-dek>{view.dek}</p> : null}
        {view.evidence.length ? (
          <p aria-label="Evidence" className="flex items-start gap-1.5 break-words text-xs" data-draft-evidence>
            <FileSearchIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            <span><span className="font-semibold">Evidence:</span> {view.evidence.join(" ")}</span>
          </p>
        ) : null}
        {view.sources.length ? (
          <ul aria-label="Sources" className="flex flex-wrap gap-1.5" data-draft-sources>
            {view.sources.map((source, index) => {
              const host = source.url ? sourceHost(source.url) : null;
              return (
                <li className="min-w-0 max-w-full" key={`${source.title}-${index}`}>
                  {source.url ? (
                    <a aria-label={`Source: ${source.title}${source.date ? ` (${source.date})` : ""}`} className={CHIP} data-draft-source href={source.url} rel="noreferrer" target="_blank" title={source.title}>
                      <SourceMark host={host} />
                      <span className="truncate">{host ?? source.title}</span>
                      <ExternalLinkIcon aria-hidden="true" className="size-3 shrink-0 opacity-60" />
                    </a>
                  ) : <span className={CHIP} data-draft-source><span className="truncate">{source.title}</span></span>}
                </li>
              );
            })}
            {view.moreSources ? <li className="self-center text-xs text-muted-foreground">and {view.moreSources} more in the full draft</li> : null}
          </ul>
        ) : null}
        <p className="mt-auto flex flex-wrap items-center justify-between gap-x-3 gap-y-1 pt-1 text-xs text-muted-foreground">
          <span data-draft-caption>{requestCaption(request)}</span>
          <Link className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline" data-draft-open href={view.href}>
            Open full draft<ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
          </Link>
        </p>
      </div>
      <DecisionFooter
        busy={busy}
        decision={decision}
        disabledReason={hold ?? session}
        error={error}
        kind="story"
        lockedNote={<>To change it, <Link className="text-primary underline underline-offset-4" href={view.href}>open the draft in Proposals</Link>.</>}
        onDecide={(choice, extras) => onDecide(draftId, choice, extras)}
        placeholder="Why? Optional. Your note teaches the AI."
      />
    </article>
  );
}

const MODE_ICON = { hard_gate: LockIcon, soft_review: ClockIcon, flag: FlagIcon } as const;

function AboutLine({ request, demo, titles, deleted, onOpen }: { request: ReviewRequest; demo: boolean; titles: Readonly<Record<string, string>>; deleted: ReadonlySet<string>; onOpen?: () => void }) {
  const href = subjectHref(request.subject, demo);
  if (request.subject.type === "batch") return null;
  const label = subjectLabel(request.subject, titles, deleted);
  return (
    <p className="break-words text-sm" data-review-about>
      About: {href ? <Link className="text-primary underline underline-offset-4" href={href} onClick={onOpen}>{label}</Link> : label}
    </p>
  );
}

/** A request decided as a whole: a hard gate, a soft review of something that is not a draft. */
export function RequestCard({ busy, demo, deleted, error, item, onAnswer, onOpen, session, titles }: {
  busy: boolean; demo: boolean; deleted: ReadonlySet<string>; error: string | null; item: RequestItem;
  onAnswer: (request: ReviewRequest, choice: DraftChoice, extras: DecisionExtras) => void;
  onOpen?: (requestId: string) => void; session: string | null; titles: Readonly<Record<string, string>>;
}) {
  const { request } = item;
  const Icon = MODE_ICON[request.mode];
  const answered = request.state === "answered" && request.answer;
  const choice: DraftChoice | null = answered ? (request.answer!.decision === "reject" || (request.answer!.decision === "feedback" && request.answer!.steer === "not_this_kind") ? "reject" : "accept") : null;
  const steering = steeringText(request);
  return (
    <article className={CARD} data-review-mode={request.mode} data-review-request={request.id} data-review-state={request.state} {...FEED_SURFACE_PROPS}>
      <div className="flex flex-1 flex-col gap-2.5 p-5">
        <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Icon aria-hidden="true" className="size-3.5 shrink-0" />
          <span>{modeLabel(request.mode)}{request.mode === "hard_gate" ? " · Waiting for you" : ""}</span>
        </p>
        <h3 className="break-words text-xl font-bold leading-[1.15] tracking-tight text-foreground">{request.reason}</h3>
        {request.ask ? <p className="break-words text-sm text-muted-foreground">{request.ask}</p> : null}
        <AboutLine deleted={deleted} demo={demo} onOpen={() => onOpen?.(request.id)} request={request} titles={titles} />
        <p className="text-sm" data-review-next>{nextText(request)}</p>
        {steering ? <p className="text-sm" data-review-steering>{steering}</p> : null}
        <p className="mt-auto pt-1 text-xs text-muted-foreground" data-draft-caption>{requestCaption(request)}</p>
      </div>
      <DecisionFooter
        busy={busy}
        decision={choice ? { choice, why: request.answer?.feedback ?? null, notThisKind: request.answer?.steer === "not_this_kind" } : null}
        disabledReason={session}
        error={error}
        kind="thing"
        lockedNote={answered ? `${answerWords(request.answer!, request)} by ${request.answer!.by}.` : ""}
        onDecide={(decided, extras) => onAnswer(request, decided, extras)}
        placeholder="Why? Optional. It is saved with your answer."
      />
    </article>
  );
}

/** A flag is information, not a question: a slim card with Acknowledge and an optional note. */
export function FlagCard({ busy, demo, deleted, error, item, onAcknowledge, onOpen, session, titles }: {
  busy: boolean; demo: boolean; deleted: ReadonlySet<string>; error: string | null; item: RequestItem;
  onAcknowledge: (request: ReviewRequest, note: string) => void;
  onOpen?: (requestId: string) => void; session: string | null; titles: Readonly<Record<string, string>>;
}) {
  const { request } = item;
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const done = request.state === "answered";
  return (
    <article className="flex flex-col gap-3 rounded-[20px] bg-[var(--feed-card)] p-4" data-review-mode="flag" data-review-request={request.id} data-review-state={request.state} {...FEED_SURFACE_PROPS}>
      <div className="flex flex-col gap-3">
        <div className="min-w-0 space-y-1">
          <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <FlagIcon aria-hidden="true" className="size-3.5 shrink-0" />For your information
          </p>
          <h3 className="break-words text-base font-semibold leading-snug text-foreground">{request.reason}</h3>
          <AboutLine deleted={deleted} demo={demo} onOpen={() => onOpen?.(request.id)} request={request} titles={titles} />
          <p className="text-xs text-muted-foreground" data-draft-caption>{requestCaption(request)} · {done && request.answer ? `${answerWords(request.answer, request)} by ${request.answer.by} on ${formatWhen(request.answer.at)}.` : "Nothing is waiting on this."}</p>
        </div>
        {done ? (
          <p className="inline-flex items-center gap-1.5 text-sm font-medium" data-flag-acknowledged><CircleCheckIcon aria-hidden="true" className="size-4" />Acknowledged</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button aria-expanded={noting} className={PILL_BUTTON} data-flag-note-toggle onClick={() => setNoting((current) => !current)} type="button">
              <MessageSquarePlusIcon aria-hidden="true" className="size-4" />Add a note
            </button>
            <button
              aria-disabled={busy || Boolean(session) || undefined}
              className={cn(PILL_BUTTON, "font-semibold", (busy || session) && "opacity-60")}
              data-flag-acknowledge
              onClick={() => { if (!busy && !session) onAcknowledge(request, note.trim()); }}
              type="button"
            >
              <CheckIcon aria-hidden="true" className="size-4" />Acknowledge
            </button>
          </div>
        )}
      </div>
      {noting && !done ? <WhyField onChange={setNote} placeholder="Why? Optional. Tell the step what to do differently." readOnly={busy} value={note} /> : null}
      <div aria-live="polite" className="empty:hidden text-xs text-muted-foreground" role="status">{busy ? "Saving…" : session && !done ? session : ""}</div>
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
    </article>
  );
}

/** The last few things the editor decided, as slim rows: what, when, and where to look again. */
export function RecentDecisions({ entries }: { entries: RecentDecision[] }) {
  if (!entries.length) return null;
  return (
    <ul aria-label="Recently decided" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" data-recent-decisions {...FEED_SURFACE_PROPS}>
      {entries.map((entry) => {
        const Icon = entry.choice === "reject" ? CircleXIcon : CircleCheckIcon;
        const body = (
          <>
            <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span className="min-w-0">
              <span className="block break-words text-sm font-medium leading-snug">{entry.title}</span>
              <span className="block text-xs text-muted-foreground">
                {entry.word}{entry.at ? ` · ${new Date(entry.at).toISOString().slice(0, 10)}` : ""}{entry.note ? ` · ${entry.note}` : ""}
              </span>
            </span>
          </>
        );
        return (
          <li data-recent-decision={entry.key} key={entry.key}>
            {entry.href ? (
              <Link className="flex items-start gap-2 rounded-[16px] bg-[var(--feed-card)] p-3 outline-none hover:bg-[var(--feed-control)] focus-visible:ring-2 focus-visible:ring-ring" href={entry.href}>{body}</Link>
            ) : <div className="flex items-start gap-2 rounded-[16px] bg-[var(--feed-card)] p-3">{body}</div>}
          </li>
        );
      })}
    </ul>
  );
}
