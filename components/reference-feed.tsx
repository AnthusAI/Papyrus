"use client";

import { CheckCheckIcon, CircleDashedIcon, ClockIcon, InfoIcon, Loader2Icon, MessageSquareIcon, SparklesIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import { REFERENCE_REJECTION_REASON_CODES, isAutoAccepted, normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import {
  referenceDisplayTime,
  type FeedItem,
  type FeedShow,
  type FeedSort,
} from "../lib/reference-feed-ranking";
import { dekAddsInformation, isCardStyleImage, referenceDek, referenceSourceHost, formatFeedAge, type ReferencePreview } from "../lib/reference-preview";
import { referenceDisplayTitle } from "../lib/newsroom-references";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { cn } from "@/lib/utils";
import { predictionFromDecision, type ReviewChoice } from "./reference-review-card";
import { DecisionControl } from "./decision-control";
import { CaptureBadge } from "./reference-capture-panel";
import { AutoAcceptedBadge } from "./auto-accepted-badge";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import type { CaptureStatus } from "../lib/reference-capture";
import { messageCountLabel } from "../lib/conversation";

/**
 * Flat surfaces, no borders: the page tone, a card tone one step away from it, a footer tone, and a control tone for chips and
 * pills. The tones (`--feed-card`, `--feed-footer`, `--feed-control`) are mixed from the publication theme's own paper and ink in
 * newsroom-organizer.css, per light or dark mode, so they follow the brand.
 */
export const FEED_SURFACE_STYLE = {} as CSSProperties;

/** Spread on every feed surface: the tone variables, and the hook the newsroom stylesheet uses to allow round corners here. */
export const FEED_SURFACE_PROPS = { "data-feed-surface": "", style: FEED_SURFACE_STYLE } as const;

export const REASON_LABELS: Record<ReferenceRejectionReasonCode, string> = {
  out_of_scope: "Out of scope",
  policy_exclusion: "Policy exclusion",
  duplicate: "Duplicate",
  low_quality: "Low quality",
  unavailable: "Unavailable",
  provenance: "Provenance",
  other: "Other",
};

const SORTS: Array<{ key: FeedSort; label: string; Icon: typeof SparklesIcon }> = [
  { key: "best", label: "Best bets", Icon: SparklesIcon },
  { key: "newest", label: "Newest", Icon: ClockIcon },
];
const SHOWS: Array<{ key: FeedShow; label: string; Icon: typeof SparklesIcon }> = [
  { key: "unrated", label: "Unrated only", Icon: CircleDashedIcon },
  { key: "all", label: "Include rated", Icon: CheckCheckIcon },
];

export const PILL = "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-full px-3.5 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring";

export type ReferenceFeedProps = {
  /** Read-only reason shown in words when answering is not possible yet (for example while the session is confirmed). */
  disabledReason?: string | null;
  /** True while the first read is in flight: cards are skeletons. */
  loading?: boolean;
  /** How many Messages each Reference has, by lineage id. A card with none shows no count. */
  messageCounts?: ReadonlyMap<string, number>;
  now: number;
  onOpen: (lineageId: string) => void;
  onRate: (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) => Promise<void> | void;
  onVisitRated: (lineageId: string) => void;
  onSortChange: (sort: FeedSort) => void;
  onShowChange: (show: FeedShow) => void;
  /** The visible list, already ordered by the chosen sort and filtered by the chosen Show. */
  items: FeedItem[];
  /** How many References already have an answer, for the empty text. */
  ratedCount: number;
  sort: FeedSort;
  show: FeedShow;
  predictionLoading?: boolean;
  previews: ReadonlyMap<string, ReferencePreview>;
  selectedLineageId?: string;
  /** Capture status per Reference lineage, for the small badge on each card. Optional. */
  captures?: ReadonlyMap<string, CaptureStatus>;
  /** The large lead card, if any. */
  leadId?: string;
  /** Scrolls the grid to a card, deliberately (Previous / Next). A new nonce is a new request; selecting alone never scrolls. */
  scrollTarget?: { id: string; nonce: number } | null;
  /** A rating store shared with the detail pane, so a vote or reason in either shows in both. Optional. */
  ratings?: RatingController;
  /** True when the cards are a saved copy that is being refreshed. */
  stale?: boolean;
  visitRated: ReadonlySet<string>;
  /** Paging: more References can be read. The next page loads when the last cards come near the viewport, or from the Load more button. */
  hasMore?: boolean;
  /** A page is being read: a row of skeleton cards, in the shape of the final cards, sits under the last card. */
  loadingMore?: boolean;
  /** Why the last page could not be read, in words. */
  loadError?: string | null;
  onLoadMore?: () => void;
};

/** Columns follow the width the feed has (a container query, not the screen), so they stay put while a detail pane holds its place beside it. */
/** A selected card: a thick ring drawn outside it on every side (a box-shadow, so it takes no layout space and covers nothing inside
 *  the card). The grid's gap leaves room for it between cards. The fallback keeps the ring if a theme has no --primary. */
export const SELECTED_RING = { boxShadow: "0 0 0 4px var(--primary, currentColor)" } as const;

export const FEED_GRID = "grid grid-cols-[repeat(auto-fill,minmax(17rem,1fr))] gap-5";
const GRID = FEED_GRID;
/** The lead spans two columns only where there are at least two to span (two 17rem columns and the gap). */
const LEAD_SPAN = "@[36rem]:col-span-2";

/** Pulsing placeholder cards: the page shell is on screen at once, with no "checking" screen in front of it. */
export function ReferenceFeedSkeleton({ count = 6, row = false }: { count?: number; /** A single row at the end of a loaded feed: one card on a phone, one row of cards where there is room. No lead. */ row?: boolean }) {
  return (
    <div aria-busy="true" aria-label={row ? "Loading more references" : "Loading references"} className={cn("@container", GRID)} data-reference-feed-skeleton={row ? "more" : ""} role="status" {...FEED_SURFACE_PROPS}>
      {Array.from({ length: count }, (_, index) => (
        <div className={cn("overflow-hidden rounded-[20px] bg-[var(--feed-card)]", !row && index === 0 && LEAD_SPAN, row && index > 0 && "hidden @[36rem]:block")} key={index}>
          <div className={cn("animate-pulse bg-[var(--feed-control)]", !row && index === 0 ? "aspect-[2/1]" : "aspect-[16/10]")} />
          <div className="space-y-3 p-5">
            <div className="h-3 w-1/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
            <div className="h-5 w-11/12 animate-pulse rounded-full bg-[var(--feed-control)]" />
            <div className="h-5 w-2/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
            <div className="h-3 w-1/4 animate-pulse rounded-full bg-[var(--feed-control)]" />
          </div>
          <div className="flex gap-2 bg-[var(--feed-footer)] p-3">
            <div className="h-10 flex-1 animate-pulse rounded-full bg-[var(--feed-control)]" />
            <div className="h-10 flex-1 animate-pulse rounded-full bg-[var(--feed-control)]" />
          </div>
        </div>
      ))}
    </div>
  );
}

function hueOf(name: string): number {
  let hash = 5381;
  for (const character of name) hash = ((hash << 5) + hash + character.charCodeAt(0)) | 0;
  return Math.abs(hash) % 360;
}

/** A small mark for a source: its own icon (found on the server, see lib/source-icon.ts) on a light tile when there is one, else its first letter. */
export function SourceMark({ host, size = "sm" }: { host: string | null; size?: "sm" | "lg" }) {
  const [failed, setFailed] = useState(false);
  const box = size === "lg" ? "size-16 rounded-2xl text-3xl" : "size-5 rounded-md text-[0.65rem]";
  const letter = (host ?? "?")[0];
  return (
    <span aria-hidden="true" className={cn("inline-flex shrink-0 items-center justify-center overflow-hidden bg-white font-bold uppercase text-neutral-700", box)} data-feed-source-mark>
      {host && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img alt="" className={size === "lg" ? "size-10 object-contain" : "size-3.5 object-contain"} loading="lazy" onError={() => setFailed(true)} src={`/api/newsroom/source-icon?host=${encodeURIComponent(host)}`} />
      ) : letter}
    </span>
  );
}

/** For a page with no usable preview picture: a soft gradient from the source's name, its mark large and centred, its name beneath. */
function FallbackTile({ host, name }: { host: string | null; name: string }) {
  const hue = hueOf(host ?? name);
  return (
    <div
      className="flex size-full flex-col items-center justify-center gap-3 p-4 text-white"
      data-feed-image-fallback
      style={{ background: `linear-gradient(135deg, oklch(0.6 0.1 ${hue}), oklch(0.42 0.11 ${(hue + 45) % 360}))` }}
    >
      <SourceMark host={host} size="lg" />
      <span className="max-w-full truncate text-sm font-semibold tracking-wide opacity-90">{name}</span>
    </div>
  );
}

/**
 * Full-bleed lazy image in a fixed frame: a soft pulse until it loads, the fallback tile when it never does.
 * Photos fill the frame (cover). A text card (a repository social card, or a 2:1 picture) is shown whole instead: the frame takes
 * the picture's own ratio and the picture is contained, so no words are cut off at the edges.
 */
export function FeedImage({ host, lead, name, src }: { host: string | null; lead: boolean; name: string; src: string | null }) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">(src ? "loading" : "failed");
  const [ratio, setRatio] = useState<number | null>(null);
  const ref = useRef<HTMLImageElement | null>(null);
  const measure = (element: HTMLImageElement) => { if (element.naturalWidth > 0 && element.naturalHeight > 0) setRatio(element.naturalWidth / element.naturalHeight); };
  useEffect(() => { setState(src ? "loading" : "failed"); setRatio(null); }, [src]);
  useEffect(() => {
    // A cached image can finish before React attaches onLoad.
    const element = ref.current;
    if (element?.complete && element.naturalWidth > 0) { setState("loaded"); measure(element); }
  }, [src]);
  // The frame is decided before the picture loads (from its address), so loading never moves the cards around. A picture found to be
  // a 2:1 text card afterwards is contained inside the same frame instead of changing it.
  const hostCard = isCardStyleImage(src, null);
  const card = hostCard || isCardStyleImage(src, ratio);
  return (
    <div
      className={cn("relative w-full overflow-hidden bg-[var(--feed-control)]", !hostCard && (lead ? "aspect-[16/10] @[36rem]:aspect-[2/1] @[60rem]:aspect-[21/9]" : "aspect-[16/10]"))}
      data-feed-image
      data-feed-image-fit={card ? "contain" : "cover"}
      data-feed-image-state={state}
      style={hostCard ? { aspectRatio: "2" } : undefined}
    >
      {state === "loading" ? <div aria-hidden="true" className="absolute inset-0 animate-pulse bg-[var(--feed-footer)] blur-sm" data-feed-image-placeholder /> : null}
      {src && state !== "failed" ? (
        // The source site chose this picture; an <img> keeps it out of our image optimizer and out of its referrer log.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className={cn("absolute inset-0 size-full transition-opacity duration-500", card ? "object-contain" : "object-cover", state === "loaded" ? "opacity-100" : "opacity-0")}
          decoding="async"
          loading="lazy"
          onError={() => setState("failed")}
          onLoad={(event) => { setState("loaded"); measure(event.currentTarget); }}
          ref={ref}
          referrerPolicy="no-referrer"
          src={src}
        />
      ) : null}
      {state === "failed" ? <FallbackTile host={host} name={name} /> : null}
    </div>
  );
}

/**
 * The standard Reference header: its picture, source, headline, dek and age. The feed card wraps it in the button that opens the
 * Reference, and the Messages page shows it under a conversation as the thing the conversation is about. No decision controls.
 */
export function ReferenceCardHeader({ capture, lead = false, messageCount = 0, now, preview, reference, titleId }: {
  capture?: CaptureStatus | undefined;
  lead?: boolean;
  messageCount?: number;
  now: number;
  preview: ReferencePreview | undefined;
  reference: ReferenceRecord;
  titleId?: string;
}) {
  const host = referenceSourceHost(reference);
  const site = preview?.siteName ?? host ?? "Unknown source";
  const title = referenceDisplayTitle(reference);
  const dek = referenceDek(reference, preview);
  const showDek = dekAddsInformation(title, dek, preview?.imageUrl ?? null);
  const time = referenceDisplayTime(reference);
  const age = formatFeedAge(time, now);
  return (
    <>
        <FeedImage host={host} lead={lead} name={site} src={preview?.imageUrl ?? null} />
        <span className={cn("flex flex-1 flex-col gap-2.5", lead ? "p-5 @[36rem]:p-7" : "p-5")}>
          <span className="flex items-center gap-2 text-xs font-medium text-muted-foreground" data-feed-source>
            <SourceMark host={host} />
            <span className="truncate">{site}</span>
          </span>
          <span className={cn("font-bold leading-[1.15] tracking-tight text-foreground", lead ? "line-clamp-3 text-2xl @[36rem]:text-3xl @[60rem]:text-4xl" : "line-clamp-3 text-xl")} data-feed-title id={titleId}>
            {title}
          </span>
          {showDek ? <span className={cn("text-muted-foreground", lead ? "line-clamp-3 text-base" : "line-clamp-2 text-sm")} data-feed-dek>{dek}</span> : null}
          <span className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-xs text-muted-foreground">
            <span>
              {age ? <time dateTime={new Date(time ?? now).toISOString()} title={new Date(time ?? now).toLocaleString()}>{age}</time> : null}
              {age && host ? <span aria-hidden="true"> · </span> : null}
              {host}
            </span>
            {capture ? <CaptureBadge status={capture} /> : null}
            {messageCount > 0 ? (
              <span aria-label={messageCountLabel(messageCount)} className="inline-flex items-center gap-1 tabular-nums" data-feed-message-count={messageCount} role="img">
                <MessageSquareIcon aria-hidden="true" className="size-3.5" />
                {messageCount}
              </span>
            ) : null}
            {isAutoAccepted(reference) ? <AutoAcceptedBadge actor={reference.curationStatusUpdatedBy} reason={reference.curationStatusReason} /> : null}
          </span>
        </span>
    </>
  );
}

export function FeedCard({
  capture,
  messageCount = 0,
  decision,
  disabledReason,
  item,
  lead,
  now,
  onOpen,
  onRate,
  predictionLoading,
  preview,
  ratings,
  selected,
  visitRated,
}: {
  /** Optional: the capture badge. */
  capture?: CaptureStatus | undefined;
  /** Optional: how many Messages this Reference has. */
  messageCount?: number;
  decision: RelevanceDecisionView | undefined;
  disabledReason: string | null;
  item: FeedItem;
  lead: boolean;
  now: number;
  onOpen: () => void;
  onRate: ReferenceFeedProps["onRate"];
  predictionLoading: boolean;
  preview: ReferencePreview | undefined;
  /** Optional: a shared rating store. Without it the card keeps its own. */
  ratings?: RatingController | undefined;
  selected: boolean;
  visitRated: boolean;
}) {
  const { reference } = item;
  const titleId = useId();
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const answer: ReviewChoice | null = status === "accepted" ? "accept" : status === "rejected" ? "reject" : null;
  // Rating state lives in a store: the shared one when given (so the detail pane and this card stay in step), else a private one.
  const local = useRatingStore({
    save: async (_id, choice, detail) => { await onRate(reference, choice, detail.reasonCode); },
    saved: () => answer,
    seed: () => ({ note: "", reasonCode: null }),
  });
  const store = ratings ?? local;
  const rating = store.get(item.lineageId);
  const chosen = rating.pending ?? answer;
  const host = referenceSourceHost(reference);
  const site = preview?.siteName ?? host ?? "Unknown source";
  const title = referenceDisplayTitle(reference);
  const dek = referenceDek(reference, preview);
  const showDek = dekAddsInformation(title, dek, preview?.imageUrl ?? null);
  const time = referenceDisplayTime(reference);
  const age = formatFeedAge(time, now);
  const feedback = rating.feedback.phase === "idle" && visitRated && answer ? { phase: "saved" as const } : rating.feedback;
  const reasonLabel = answer === "reject" && rating.reasonCode ? REASON_LABELS[rating.reasonCode] : null;

  return (
    <article
      aria-labelledby={titleId}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "relative flex flex-col overflow-hidden rounded-[20px] text-card-foreground transition-[background-color,box-shadow] duration-200",
        selected ? "bg-[var(--feed-control)]" : "bg-[var(--feed-card)]",
        lead && LEAD_SPAN,
      )}
      data-feed-card={item.lineageId}
      data-feed-lead={lead || undefined}
      data-feed-rated={answer ?? undefined}
      data-feed-selected={selected || undefined}
      style={selected ? SELECTED_RING : undefined}
      data-feed-visit-rated={visitRated || undefined}
      data-newsroom-card-id={item.lineageId}
    >
      <button
        aria-label={`Open: ${title}`}
        className="flex flex-1 flex-col text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        data-feed-open
        onClick={onOpen}
        type="button"
      >
        <ReferenceCardHeader capture={capture} lead={lead} messageCount={messageCount} now={now} preview={preview} reference={reference} titleId={titleId} />
      </button>

      <div className="relative bg-[var(--feed-footer)] px-4 pb-4 pt-3" data-feed-actions>
        <DecisionControl
          answer={chosen}
          decided={answer}
          disabled={Boolean(disabledReason)}
          disabledReason={disabledReason}
          feedback={feedback}
          needsReason={rating.askReason}
          note={reasonLabel ? `Reason: ${reasonLabel}` : null}
          onChoose={(choice) => { if (!disabledReason) store.choose(item.lineageId, choice); }}
          onReasonChange={(text) => store.setNote(item.lineageId, text)}
          onReasonCommit={() => { if (!disabledReason) store.commitNote(item.lineageId); }}
          prediction={decision ? predictionFromDecision(decision) : predictionLoading ? { state: "loading" } : { state: "none" }}
          reason={rating.note ?? ""}
          reasonRequiredFor="reject"
          statusOverlay
        />
      </div>
    </article>
  );
}

/** The plain-words recipe. */
function RankingPopover() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) { if (event.key === "Escape") setOpen(false); return; }
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className="relative" ref={root}>
      <button
        aria-controls={panelId}
        aria-expanded={open}
        aria-label="How this feed is ranked"
        className={cn(PILL, "text-muted-foreground hover:text-foreground", open && "bg-[var(--feed-card)] text-foreground")}
        data-feed-ranking-info
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <InfoIcon aria-hidden="true" className="size-4" />
        <span className="hidden sm:inline">How this feed is ranked</span>
        <span className="sr-only sm:hidden">Ranking</span>
      </button>
      {open ? (
        <div
          aria-label="How this feed is ranked"
          className="fixed inset-x-4 bottom-24 z-30 max-h-[70dvh] space-y-3 overflow-y-auto rounded-3xl bg-popover p-6 text-sm text-popover-foreground shadow-2xl sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:mt-2 sm:w-[24rem]"
          data-feed-ranking-panel
          id={panelId}
          role="dialog"
        >
          <p className="text-base font-bold">A feed run by algorithms you control</p>
          <ol className="list-decimal space-y-2.5 pl-5">
            <li><strong>Best bets</strong> puts the items the Cyclotron is most sure you will Accept first. It goes by confidence alone: an Accept at 90% ranks above an Accept at 60%, and the ones it expects you to Reject most surely come last. Items with no prediction sit in the middle. Age does not change this order.</li>
            <li><strong>Newest</strong> puts the items that arrived most recently first.</li>
            <li><strong>Unrated only</strong> shows items nobody has answered yet. <strong>Include rated</strong> adds the ones you have already accepted or rejected to the same list, showing your answer, in the same sort. Nothing is hidden because it is old.</li>
            <li><strong>Your answers stay put.</strong> A card you rate stays where it is for this visit, and new items wait behind a button until you ask for them.</li>
          </ol>
        </div>
      ) : null}
    </div>
  );
}

/** The nearest ancestor that scrolls vertically: the margin of an IntersectionObserver is measured from it, not from the window. */
function scrollParent(element: HTMLElement): HTMLElement | null {
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (/(auto|scroll|overlay)/.test(getComputedStyle(parent).overflowY)) return parent;
  }
  return null;
}

/**
 * The end of the loaded cards: an invisible marker the page watches, and a Load more button for anyone who prefers it or cannot scroll.
 * The marker asks for the next page when it comes within a screen of the viewport (an IntersectionObserver on the feed's scroll area), so
 * the next cards are usually there before they are reached. It re-arms after every page, so a tall screen keeps filling.
 */
function FeedLoadMore({ armKey, error, hasMore, loading, onLoadMore }: { armKey: number; error: string | null; hasMore: boolean; loading: boolean; onLoadMore: () => void }) {
  const marker = useRef<HTMLDivElement | null>(null);
  const request = useRef(onLoadMore);
  request.current = onLoadMore;
  useEffect(() => {
    const element = marker.current;
    if (!element || !hasMore || loading || error || typeof IntersectionObserver === "undefined") return;
    const root = scrollParent(element);
    const observer = new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) request.current(); }, { root, rootMargin: "0px 0px 900px 0px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [armKey, error, hasMore, loading]);
  return (
    <div className="space-y-4" data-feed-more>
      {loading ? <ReferenceFeedSkeleton count={3} row /> : null}
      <div aria-hidden="true" className="h-px" data-feed-sentinel ref={marker} />
      {error ? <p className="rounded-2xl bg-[var(--feed-card)] p-3 text-sm" data-feed-load-error role="alert">{error}</p> : null}
      {hasMore ? (
        <div className="flex justify-center">
          <button
            className={cn(PILL, "bg-[var(--feed-card)] text-foreground hover:bg-[var(--feed-control)] disabled:opacity-60")}
            data-feed-load-more
            disabled={loading}
            onClick={onLoadMore}
            type="button"
          >
            {error ? "Try again" : loading ? "Loading more" : "Load more"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function ReferenceFeed({
  disabledReason = null,
  loading = false,
  messageCounts,
  now,
  onOpen,
  onRate,
  onShowChange,
  onSortChange,
  onVisitRated,
  items,
  ratedCount,
  predictionLoading = false,
  previews,
  selectedLineageId = "",
  captures,
  leadId,
  ratings,
  scrollTarget = null,
  show,
  sort,
  stale = false,
  visitRated,
  hasMore = false,
  loadingMore = false,
  loadError = null,
  onLoadMore,
}: ReferenceFeedProps) {

  const renderCard = (item: FeedItem, lead: boolean) => (
    <FeedCard
      capture={captures?.get(item.lineageId)}
      decision={item.decision}
      disabledReason={disabledReason}
      item={item}
      key={item.lineageId}
      lead={lead}
      messageCount={messageCounts?.get(item.lineageId)}
      now={now}
      onOpen={() => onOpen(item.lineageId)}
      onRate={async (reference, choice, reasonCode) => { onVisitRated(item.lineageId); await onRate(reference, choice, reasonCode); }}
      predictionLoading={predictionLoading}
      preview={previews.get(item.lineageId)}
      ratings={ratings}
      selected={selectedLineageId === item.lineageId}
      visitRated={visitRated.has(item.lineageId)}
    />
  );

  const empty = (label: string) => (
    <div className="rounded-[20px] bg-[var(--feed-card)] p-10 text-center text-sm text-muted-foreground" data-feed-empty>{label}</div>
  );

  // Previous / Next in the detail pane scrolls the grid to the same card, smoothly. Selecting a card by clicking it never scrolls.
  useEffect(() => {
    if (!scrollTarget || typeof document === "undefined") return;
    document.querySelector(`[data-feed-card="${CSS.escape(scrollTarget.id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [scrollTarget]);


  return (
    <div className="@container space-y-5" data-reference-feed data-feed-sort={sort} data-feed-show={show} {...FEED_SURFACE_PROPS}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div aria-label="Sort" className="inline-flex rounded-full bg-[var(--feed-card)] p-1" data-feed-control="sort" role="group">
            {SORTS.map(({ key, label, Icon }) => (
              <button
                aria-pressed={sort === key}
                className={cn(PILL, "px-3.5", sort === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground")}
                data-feed-sort-button={key}
                key={key}
                onClick={() => onSortChange(key)}
                type="button"
              >
                <Icon aria-hidden="true" className="size-4" />{label}
              </button>
            ))}
          </div>
          <div aria-label="Show" className="inline-flex rounded-full bg-[var(--feed-card)] p-1" data-feed-control="show" role="group">
            {SHOWS.map(({ key, label, Icon }) => (
              <button
                aria-pressed={show === key}
                className={cn(PILL, "px-3.5", show === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground")}
                data-feed-show-button={key}
                key={key}
                onClick={() => onShowChange(key)}
                type="button"
              >
                <Icon aria-hidden="true" className="size-4" />{label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {stale ? (
            <span className="hidden items-center gap-1 text-xs text-muted-foreground sm:inline-flex" data-feed-stale role="status">
              <Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Showing your last view while it updates
            </span>
          ) : null}
          <RankingPopover />
        </div>
      </div>
      {stale ? <p className="text-xs text-muted-foreground sm:hidden" role="status"><Loader2Icon aria-hidden="true" className="mr-1 inline size-3.5 animate-spin" />Showing your last view while it updates</p> : null}

      {loading ? <ReferenceFeedSkeleton /> : (
        items.length ? (
          <>
            <div className={FEED_GRID} data-feed-grid>{items.map((item) => renderCard(item, item.lineageId === leadId))}</div>
            {onLoadMore && (hasMore || loadingMore || loadError) ? (
              <FeedLoadMore armKey={items.length} error={loadError} hasMore={hasMore} loading={loadingMore} onLoadMore={onLoadMore} />
            ) : null}
          </>
        ) : empty(ratedCount && show === "unrated" ? "You are all caught up. Choose Include rated to see your answers." : "No references yet.")
      )}
    </div>
  );
}
