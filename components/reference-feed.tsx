"use client";

import { ArrowDownWideNarrowIcon, AwardIcon, CheckCheckIcon, CheckIcon, CircleDashedIcon, ClockIcon, FileCheckIcon, FileXIcon, FilesIcon, InfoIcon, ListChecksIcon, Loader2Icon, MessageSquareIcon, RefreshCwIcon, SearchIcon, SparklesIcon, StarIcon, StarOffIcon, VideoIcon, XIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import { REFERENCE_REJECTION_REASON_CODES, isAutoAccepted, normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import {
  referenceDisplayTime,
  type FeedItem,
  type FeedMinStars,
  type FeedCaptured,
  type FeedShow,
  type FeedSort,
} from "../lib/reference-feed-ranking";
import { dekAddsInformation, isCardStyleImage, referenceDek, referenceSourceHost, formatFeedAge, type ReferencePreview } from "../lib/reference-preview";
import { referenceDisplayTitle } from "../lib/newsroom-references";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import type { PredictionStatus, PredictionStatuses } from "../lib/reference-predictions";
import { cn } from "@/lib/utils";
import { predictionFromDecision, type ReviewChoice } from "./reference-review-card";
import { CreateStoryButton } from "./create-story-button";
import { CardSuggestions } from "./card-suggestions";
import { DecisionControl } from "./decision-control";
import { CaptureBadge } from "./reference-capture-panel";
import { AutoAcceptedBadge } from "./auto-accepted-badge";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import { displayedCaptureStatus, normalizeCaptureState, type CaptureStatus } from "../lib/reference-capture";
import { messageCountLabel } from "../lib/conversation";
import { referenceDatesText } from "../lib/reference-links";
import { FEED_MEDIUMS, MEDIUM_LABELS, MEDIUM_NOUNS, type FeedMedium } from "../lib/reference-medium-feed";

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

/** The Sort choices: while a search is open Predictions is Relevance (how well each Reference matches), which the search keeps for itself. */
export type FeedSortChoice = FeedSort | "relevance";
const SORTS: Array<{ key: FeedSortChoice; label: string; Icon: typeof SparklesIcon }> = [
  { key: "best", label: "Predictions", Icon: SparklesIcon },
  { key: "newest", label: "Newest", Icon: ClockIcon },
  { key: "quality", label: "Quality", Icon: AwardIcon },
];
const SEARCH_SORTS: typeof SORTS = [
  { key: "relevance", label: "Relevance", Icon: ArrowDownWideNarrowIcon },
  SORTS[1]!,
  SORTS[2]!,
];
/** Minimum stars: a floor, never "only 3" or "only 2". The icon and the number say it, not colour. */
const MIN_STARS: Array<{ key: FeedMinStars; label: string; spoken: string }> = [
  { key: 0, label: "Any", spoken: "" },
  { key: 3, label: "3+", spoken: " stars or more" },
  { key: 4, label: "4+", spoken: " stars or more" },
  { key: 5, label: "5", spoken: " stars" },
];
export function minStarsPhrase(minStars: FeedMinStars): string {
  return minStars === 5 ? "5 stars" : `${minStars} or more stars`;
}
/** What found nothing, in words, when Minimum stars or Captured is in force (`query` is null outside a search). */
export function emptyFilterSentence({ captured, minStars, query }: { captured: FeedCaptured; minStars: FeedMinStars; query: string | null }): string {
  const stars = minStars > 0 ? minStarsPhrase(minStars) : null;
  const held = captured === "yes" ? "has been captured" : captured === "no" ? "is missing its content" : null;
  if (query !== null) {
    const parts = [stars ? `with ${stars}` : null, held ? `that ${captured === "yes" ? "we have" : "we have not"} captured` : null].filter(Boolean);
    return `Nothing matches “${query}”${parts.length ? ` ${parts.join(" and ")}` : ""}.`;
  }
  const parts = [stars ? `has ${stars}` : null, held].filter(Boolean);
  return `Nothing here ${parts.join(" and ")}.`;
}
/**
 * Reviewed: whether a Reference has been accepted or rejected. The saved values keep their old names (`unrated`, `all`, `rated`) so nobody's
 * choice resets; only the words changed. Yes is `rated`, No is `unrated`.
 */
export const REVIEWED_LABELS: Record<FeedShow, string> = { all: "Any", accepted: "Accepted", rated: "Yes", unrated: "No" };
const SHOWS: Array<{ key: FeedShow; label: string; Icon: typeof SparklesIcon }> = [
  { key: "all", label: REVIEWED_LABELS.all, Icon: CheckCheckIcon },
  { key: "accepted", label: REVIEWED_LABELS.accepted, Icon: CheckIcon },
  { key: "rated", label: REVIEWED_LABELS.rated, Icon: ListChecksIcon },
  { key: "unrated", label: REVIEWED_LABELS.unrated, Icon: CircleDashedIcon },
];
/** Captured: whether the newsroom holds the content. No is every Reference we could not collect in full, including one still being captured. */
export const CAPTURED_LABELS: Record<FeedCaptured, string> = { any: "Any", yes: "Yes", no: "No" };
const CAPTUREDS: Array<{ key: FeedCaptured; label: string; Icon: typeof SparklesIcon }> = [
  { key: "any", label: CAPTURED_LABELS.any, Icon: FilesIcon },
  { key: "yes", label: CAPTURED_LABELS.yes, Icon: FileCheckIcon },
  { key: "no", label: CAPTURED_LABELS.no, Icon: FileXIcon },
];

/** Medium: what kind of thing the address is. The icon and the word say it, not colour. */
const MEDIUM_ICONS: Record<FeedMedium, typeof SparklesIcon> = { any: FilesIcon, video: VideoIcon };

export const PILL ="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-full px-3.5 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring";

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
  /** The preview workspace: Create Story builds its draft locally instead of calling the backend. */
  demo?: boolean;
  /** Saves a star rating (null clears it). Without it, and without a shared store that rates stars, the cards show no stars. */
  onSetStars?: (reference: ReferenceRecord, stars: number | null) => Promise<void> | void;
  onVisitRated: (lineageId: string) => void;
  onSortChange: (sort: FeedSortChoice) => void;
  onShowChange: (show: FeedShow) => void;
  /** The Minimum stars row. Without it the feed has no such row (a page that does not read by stars). */
  onMinStarsChange?: (minStars: FeedMinStars) => void;
  minStars?: FeedMinStars;
  /** The Captured row. Without `onCapturedChange` the feed has no such row. */
  captured?: FeedCaptured;
  onCapturedChange?: (captured: FeedCaptured) => void;
  /** The Medium row (All, Videos). Without `onMediumChange` the feed has no such row (a page whose source cannot read the medium index). It is hidden while a search is open. */
  medium?: FeedMedium;
  onMediumChange?: (medium: FeedMedium) => void;
  /** The visible list, already ordered by the chosen sort and filtered by the chosen Show. */
  items: FeedItem[];
  /** How many References already have an answer, for the empty text. */
  ratedCount: number;
  /** The chosen sort; while a search is open, the search's own (Relevance, Newest or Quality). */
  sort: FeedSortChoice;
  show: FeedShow;
  predictionLoading?: boolean;
  /** Each Reference's own prediction read. A failure shows on that card only, with a way to read it again. */
  predictionStatuses?: PredictionStatuses;
  onRetryPrediction?: (lineageId: string) => void;
  /** More References follow the last card: scrolling to the end asks for them. */
  hasMore?: boolean;
  /** The next page is being read; its cards join the feed when their predictions have arrived. */
  loadingMore?: boolean;
  onLoadMore?: () => void;
  /** The read failed: said in words with a Retry. With no cards it replaces the skeletons; with cards it sits under them. */
  error?: string | null;
  onRetry?: () => void;
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
  /** The search box. Without it the feed has none (the demo and the saved copy). While `search.query` is set the cards are search results. */
  search?: ReferenceFeedSearch;
};

export type ReferenceFeedSearch = {
  /** The query being searched ("" when not searching). */
  query: string;
  onSubmit: (query: string) => void;
  onClear: () => void;
  /** How each result matched, by lineage id ("title, author", "meaning"). */
  matches: ReadonlyMap<string, string>;
  /** Set when one lane could not run: said in words, with a way to run the search again. */
  notice?: string | null;
  onRetry?: () => void;
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
export function ReferenceFeedSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading references" className={cn("@container", GRID)} data-reference-feed-skeleton role="status" {...FEED_SURFACE_PROPS}>
      {Array.from({ length: count }, (_, index) => (
        <div className={cn("overflow-hidden rounded-[20px] bg-[var(--feed-card)]", index === 0 && LEAD_SPAN)} key={index}>
          <div className={cn("animate-pulse bg-[var(--feed-control)]", index === 0 ? "aspect-[2/1]" : "aspect-[16/10]")} />
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
export function ReferenceCardHeader({ capture, lead = false, matched, messageCount = 0, now, preview, reference, titleId }: {
  capture?: CaptureStatus | undefined;
  lead?: boolean;
  /** Search results only: how this Reference matched ("title, author", "meaning"), said in words on the card. */
  matched?: string | undefined;
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
          <span className="mt-auto text-xs text-muted-foreground" data-feed-dates>{referenceDatesText(reference)}</span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span>
              {age ? <time dateTime={new Date(time ?? now).toISOString()} title={new Date(time ?? now).toLocaleString()}>{age}</time> : null}
              {age && host ? <span aria-hidden="true"> · </span> : null}
              {host}
            </span>
            {matched ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--feed-control)] px-2 py-0.5 font-medium text-foreground" data-feed-matched>
                <SearchIcon aria-hidden="true" className="size-3" />Matched: {matched}
              </span>
            ) : null}
            {capture ? <CaptureBadge status={displayedCaptureStatus(capture)} /> : storedCaptureBadge(reference.captureState)}
            {reference.medium === "video" ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--feed-control)] px-2 py-0.5 font-medium text-foreground" data-feed-medium="video">
                <VideoIcon aria-hidden="true" className="size-3" />Video
              </span>
            ) : null}
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
  matched,
  now,
  onOpen,
  onRate,
  demo = false,
  onSetStars,
  predictionLoading,
  predictionStatus,
  onRetryPrediction,
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
  /** Search results only: how this Reference matched. */
  matched?: string | undefined;
  now: number;
  onOpen: () => void;
  onRate: ReferenceFeedProps["onRate"];
  demo?: boolean;
  onSetStars?: ReferenceFeedProps["onSetStars"];
  predictionLoading: boolean;
  predictionStatus?: PredictionStatus | undefined;
  onRetryPrediction?: (() => void) | undefined;
  preview: ReferencePreview | undefined;
  /** Optional: a shared rating store. Without it the card keeps its own. */
  ratings?: RatingController | undefined;
  selected: boolean;
  visitRated: boolean;
}) {
  const { reference } = item;
  const titleId = useId();
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const auto = isAutoAccepted(reference);
  // An automatic acceptance is not the editor's answer yet: Accept confirms it (and offers the reason box), Reject overturns it.
  const answer: ReviewChoice | null = status === "accepted" && !auto ? "accept" : status === "rejected" ? "reject" : null;
  // Rating state lives in a store: the shared one when given (so the detail pane and this card stay in step), else a private one.
  const local = useRatingStore({
    save: async (_id, choice, detail) => { await onRate(reference, choice, detail.reasonCode); },
    saved: () => answer,
    seed: () => ({ note: "", reasonCode: null }),
    confirms: () => auto,
    ...(onSetStars ? { saveStars: async (_id: string, next: number | null) => { await onSetStars(reference, next); }, savedStars: () => reference.starRating ?? null } : {}),
  });
  const store = ratings ?? local;
  const rating = store.get(item.lineageId);
  const starValue = store.stars(item.lineageId);
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
        <ReferenceCardHeader capture={capture} lead={lead} matched={matched} messageCount={messageCount} now={now} preview={preview} reference={reference} titleId={titleId} />
      </button>

      <div className="bg-[var(--feed-footer)] px-4 pt-3" data-feed-create-story>
        <CreateStoryButton
          demo={demo}
          disabled={Boolean(disabledReason)}
          automatic={auto}
          // A confirmation of an automatic acceptance waits for an optional reason first; Create Story asks none, so the second call records it.
          onAccept={() => { store.choose(item.lineageId, "accept"); if (auto) store.choose(item.lineageId, "accept"); }}
          preview={{ title, url: reference.sourceUri ?? null, summary: showDek ? dek : null, imageUrl: preview?.imageUrl ?? null, site: preview?.siteName ?? host ?? null }}
          referenceId={reference.id}
          stable
          status={status}
        />
      </div>

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
          onRetryPrediction={!decision && predictionStatus?.state === "error" ? onRetryPrediction : undefined}
          prediction={decision ? predictionFromDecision(decision)
            : predictionStatus?.state === "error" ? { state: "error" }
              : predictionLoading || predictionStatus?.state === "loading" ? { state: "loading" } : { state: "none" }}
          reason={rating.note ?? ""}
          reasonRequiredFor="reject"
          stars={starValue === undefined ? undefined : { value: starValue, onChange: (tapped) => { if (!disabledReason) store.setStars(item.lineageId, tapped); }, feedback: store.starsFeedback(item.lineageId) }}
          statusOverlay
        />
      </div>

      <CardSuggestions disabled={Boolean(disabledReason)} inset="bg-[var(--feed-footer)] px-4 pb-4" lineageId={item.lineageId} />
    </article>
  );
}

/** A card whose attachments are not loaded yet still says what the Reference itself records when it was not captured in full. */
function storedCaptureBadge(stored: string | null | undefined) {
  const state = normalizeCaptureState(stored);
  if (!stored || state === "full") return null;
  return <CaptureBadge status={{ state, words: null, estimated: false, source: "none" }} />;
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
            <li><strong>Predictions</strong> puts the items the Cyclotron is most sure you will Accept first. It goes by confidence alone: an Accept at 90% ranks above an Accept at 60%, and the ones it expects you to Reject most surely come last. Items with no prediction sit in the middle. Age does not change this order.</li>
            <li><strong>Newest</strong> puts the items that arrived most recently first.</li>
            <li><strong>Quality</strong> puts the items you gave the most stars first, newest first within each number of stars. Only items with stars are in it. <strong>Minimum stars</strong> keeps the items with at least 3, 4 or 5 stars in whichever sort you chose. Stars are your own interest: the Cyclotron never sees them.</li>
            <li><strong>Reviewed</strong> is whether someone has accepted or rejected an item. <strong>No</strong> shows items nobody has answered yet. <strong>Any</strong> adds the ones you have already accepted or rejected to the same list, showing your answer, in the same sort. <strong>Accepted</strong> lists just the ones you accepted, never a rejected one. <strong>Yes</strong> lists just those answered ones, in the same sort, so you can find one again; Predictions there still goes by the Cyclotron&apos;s original confidence, not by your answer. Nothing is hidden because it is old.</li>
            <li><strong>Medium</strong> is what kind of thing the address is. <strong>Videos</strong> lists only the videos, newest first, in whichever Reviewed you chose (Videos with Reviewed No are the videos waiting for an answer). It is in the page address, so a link to it opens the same list. Predictions cannot order a medium, so the list is Newest; choosing Predictions goes back to All. Quality and Minimum stars work with it.</li>
            <li><strong>Captured</strong> is whether we hold the item&apos;s content. <strong>Yes</strong> keeps the ones we collected in full. <strong>No</strong> keeps the ones we could not: a page that blocked us, a capture that came back cut off, or one still being collected. Choose Reviewed Accepted and Captured No to find the items you accepted that someone should paste or upload. It works in any sort, and it does not change the order.</li>
            <li><strong>Search</strong> looks for your words in titles, authors, links and ids, and for meaning in the summaries, at the same time, over every Reference whether or not it has been answered. Results are ordered by how well they match (Relevance) unless you choose Newest or Quality, and each says how it matched. Reviewed starts on Any for a search; clearing the search brings back your own Sort and Reviewed. Captured and Minimum stars apply to a search too.</li>
            <li><strong>Your answers stay put.</strong> A card you rate stays where it is for this visit, and new items wait behind a button until you ask for them.</li>
          </ol>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The end of the feed. When it scrolls near the view, the next page is asked for; the page's cards arrive once their predictions have.
 * It watches again after every change in the number of cards, so a short page that leaves it in view asks for the next one too.
 */
function FeedMoreSentinel({ hasMore, itemCount, loadingMore, onLoadMore }: { hasMore: boolean; itemCount: number; loadingMore: boolean; onLoadMore?: (() => void) | undefined }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || !hasMore || loadingMore || !onLoadMore || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) onLoadMore(); }, {
      root: element.closest("[data-radix-scroll-area-viewport]"),
      rootMargin: "0px 0px 800px 0px",
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasMore, itemCount, loadingMore, onLoadMore]);
  if (!hasMore && !loadingMore) return null;
  return (
    <div className="flex min-h-12 items-center justify-center gap-2 text-sm text-muted-foreground" data-feed-more ref={ref} role="status">
      <Loader2Icon aria-hidden="true" className={cn("size-4", loadingMore && "animate-spin")} />
      {loadingMore ? "Loading more items…" : (
        // The next page loads by itself as this row nears the screen; the button is the way to ask for it from a keyboard.
        <button className="rounded-full px-3 py-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring" data-feed-load-more onClick={onLoadMore} type="button">Load more items</button>
      )}
    </div>
  );
}

/** The search box above Sort and Show: Enter runs the search, the X clears it. A flat fill, no border. */
function FeedSearchBox({ onClear, onSubmit, query }: { onClear: () => void; onSubmit: (query: string) => void; query: string }) {
  const [draft, setDraft] = useState(query);
  useEffect(() => { setDraft(query); }, [query]);
  return (
    <form
      aria-label="Search References"
      className="relative flex w-full items-center"
      data-feed-search
      onSubmit={(event) => { event.preventDefault(); if (draft.trim()) onSubmit(draft); else onClear(); }}
      role="search"
    >
      <SearchIcon aria-hidden="true" className="pointer-events-none absolute left-4 size-4 text-muted-foreground" />
      <input
        aria-label="Search References"
        autoComplete="off"
        className="min-h-11 w-full rounded-full bg-[var(--feed-card)] pl-11 pr-12 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring sm:text-sm [&::-webkit-search-cancel-button]:appearance-none"
        data-feed-search-input
        enterKeyHint="search"
        onChange={(event) => setDraft(event.target.value)}
        placeholder="Search References by words or meaning"
        type="search"
        value={draft}
      />
      {draft || query ? (
        <button
          aria-label="Clear search"
          className="absolute right-1.5 inline-flex size-9 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-[var(--feed-control)] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          data-feed-search-clear
          onClick={() => { setDraft(""); onClear(); }}
          type="button"
        >
          <XIcon aria-hidden="true" className="size-4" />
        </button>
      ) : null}
    </form>
  );
}

function FeedReadError({ error, onRetry }: { error: string; onRetry?: (() => void) | undefined }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[20px] bg-[var(--feed-card)] p-8 text-center text-sm" data-feed-error role="alert">
      <p className="font-medium text-foreground">The References could not be loaded.</p>
      <p className="text-muted-foreground">{error}</p>
      {onRetry ? (
        <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-feed-retry onClick={onRetry} type="button">
          <RefreshCwIcon aria-hidden="true" className="size-4" />Retry
        </button>
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
  demo,
  onSetStars,
  onShowChange,
  onSortChange,
  onMinStarsChange,
  minStars = 0,
  captured = "any",
  onCapturedChange,
  medium = "any",
  onMediumChange,
  onVisitRated,
  items,
  ratedCount,
  predictionLoading = false,
  predictionStatuses,
  onRetryPrediction,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  error = null,
  onRetry,
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
  search,
}: ReferenceFeedProps) {
  const searching = Boolean(search?.query);
  const minStarsLabelId = useId();
  const reviewedLabelId = useId();
  const capturedLabelId = useId();
  const mediumLabelId = useId();
  const mediumRow = Boolean(onMediumChange) && !searching;

  const renderCard = (item: FeedItem, lead: boolean) => (
    <FeedCard
      capture={captures?.get(item.lineageId)}
      decision={item.decision}
      disabledReason={disabledReason}
      item={item}
      key={item.lineageId}
      lead={lead}
      matched={searching ? search?.matches.get(item.lineageId) : undefined}
      messageCount={messageCounts?.get(item.lineageId)}
      now={now}
      onOpen={() => onOpen(item.lineageId)}
      demo={demo}
      onRate={async (reference, choice, reasonCode) => { onVisitRated(item.lineageId); await onRate(reference, choice, reasonCode); }}
      onRetryPrediction={onRetryPrediction ? () => onRetryPrediction(item.lineageId) : undefined}
      onSetStars={onSetStars}
      predictionLoading={predictionLoading}
      predictionStatus={predictionStatuses?.get(item.lineageId)}
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
    const card = document.querySelector(`[data-feed-card="${CSS.escape(scrollTarget.id)}"]`);
    const scroller = card?.closest<HTMLElement>("[data-reference-feed-scroll]");
    if (!card) return;
    if (!scroller || scroller.scrollHeight <= scroller.clientHeight) {
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    // Only the feed's own scroller moves: scrollIntoView would also move the page around it and shift the detail pane.
    const box = card.getBoundingClientRect();
    const view = scroller.getBoundingClientRect();
    const bottom = Math.min(view.bottom, window.innerHeight);
    const by = box.top < view.top ? box.top - view.top : box.bottom > bottom ? Math.min(box.bottom - bottom, box.top - view.top) : 0;
    if (by) scroller.scrollBy({ top: by, behavior: "smooth" });
  }, [scrollTarget]);


  return (
    <div className="@container space-y-5" data-reference-feed data-feed-sort={sort} data-feed-show={show} data-feed-min-stars={minStars} data-feed-captured={captured} data-feed-medium={medium} data-feed-searching={searching || undefined} {...FEED_SURFACE_PROPS}>
      {search ? <FeedSearchBox onClear={search.onClear} onSubmit={search.onSubmit} query={search.query} /> : null}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div aria-label="Sort" className="inline-flex rounded-full bg-[var(--feed-card)] p-1" data-feed-control="sort" role="group">
            {(searching ? SEARCH_SORTS : SORTS).map(({ key, label, Icon }) => (
              <button
                aria-pressed={sort === key}
                className={cn(PILL, "px-3.5", sort === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground")}
                data-feed-sort-button={key}
                {...(key === "relevance" ? { "data-feed-sort-relevance": true } : {})}
                key={key}
                onClick={() => onSortChange(key)}
                type="button"
              >
                <Icon aria-hidden="true" className="size-4" />{label}
              </button>
            ))}
          </div>
          {mediumRow ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1" data-feed-control="medium">
              <span className="whitespace-nowrap text-sm text-muted-foreground" id={mediumLabelId}>Medium</span>
              <div aria-labelledby={mediumLabelId} className="inline-flex rounded-full bg-[var(--feed-card)] p-1" role="group">
                {FEED_MEDIUMS.map((key) => {
                  const Icon = MEDIUM_ICONS[key];
                  return (
                    <button
                      aria-pressed={medium === key}
                      className={cn(PILL, "px-3.5", medium === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground")}
                      data-feed-medium-button={key}
                      key={key}
                      onClick={() => onMediumChange!(key)}
                      type="button"
                    >
                      <Icon aria-hidden="true" className="size-4" />{MEDIUM_LABELS[key]}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1" data-feed-control="show">
            <span className="whitespace-nowrap text-sm text-muted-foreground" id={reviewedLabelId}>Reviewed</span>
            <div aria-labelledby={reviewedLabelId} className="inline-flex rounded-full bg-[var(--feed-card)] p-1" role="group">
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
          {onMinStarsChange ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1" data-feed-control="min-stars">
              <span className="whitespace-nowrap text-sm text-muted-foreground" id={minStarsLabelId}>Minimum stars</span>
              <div aria-labelledby={minStarsLabelId} className="inline-flex rounded-full bg-[var(--feed-card)] p-1" role="group">
                {MIN_STARS.map(({ key, label, spoken }) => (
                  <button
                    aria-pressed={minStars === key}
                    className={cn(PILL, "px-3.5", minStars === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground")}
                    data-feed-min-stars-button={key}
                    key={key}
                    onClick={() => onMinStarsChange(key)}
                    type="button"
                  >
                    {key ? <StarIcon aria-hidden="true" className="size-4" /> : null}{label}<span className="sr-only">{spoken}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {onCapturedChange ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1" data-feed-control="captured">
              <span className="whitespace-nowrap text-sm text-muted-foreground" id={capturedLabelId}>Captured</span>
              <div aria-labelledby={capturedLabelId} className="inline-flex rounded-full bg-[var(--feed-card)] p-1" role="group">
                {CAPTUREDS.map(({ key, label, Icon }) => (
                  <button
                    aria-pressed={captured === key}
                    className={cn(PILL, "px-3.5", captured === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground")}
                    data-feed-captured-button={key}
                    key={key}
                    onClick={() => onCapturedChange(key)}
                    type="button"
                  >
                    <Icon aria-hidden="true" className="size-4" />{label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
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
      {searching && search?.notice ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[20px] bg-[var(--feed-card)] px-4 py-3 text-sm text-foreground" data-feed-search-notice role="status">
          <InfoIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span>{search.notice}</span>
          {search.onRetry ? (
            <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-feed-search-retry onClick={search.onRetry} type="button">
              <RefreshCwIcon aria-hidden="true" className="size-4" />Retry
            </button>
          ) : null}
        </div>
      ) : null}

      {error && !items.length ? <FeedReadError error={error} onRetry={onRetry} /> : loading ? <ReferenceFeedSkeleton /> : (
        items.length ? (
          <>
            <div className={FEED_GRID} data-feed-grid>{items.map((item) => renderCard(item, item.lineageId === leadId))}</div>
            {error ? <FeedReadError error={error} onRetry={onRetry} /> : null}
            <FeedMoreSentinel hasMore={hasMore && !error} itemCount={items.length} loadingMore={loadingMore} onLoadMore={onLoadMore} />
          </>
        ) : hasMore || loadingMore ? (
          <FeedMoreSentinel hasMore={hasMore} itemCount={0} loadingMore={loadingMore} onLoadMore={onLoadMore} />
        ) : mediumRow && medium !== "any" ? (
          <div className="flex flex-col items-center gap-3 rounded-[20px] bg-[var(--feed-card)] p-10 text-center text-sm text-muted-foreground" data-feed-empty data-feed-medium-empty>
            <p>{`No ${MEDIUM_NOUNS[medium]} with Reviewed ${REVIEWED_LABELS[show]}${minStars > 0 ? ` and ${minStarsPhrase(minStars)}` : ""}${captured !== "any" ? ` and Captured ${CAPTURED_LABELS[captured]}` : ""}.${minStars === 0 && captured === "any" ? " Older ones are listed here after the medium backfill has run." : ""}`}</p>
            <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-feed-medium-clear onClick={() => onMediumChange!("any")} type="button">
              <FilesIcon aria-hidden="true" className="size-4" />Show all media
            </button>
          </div>
        ) : (minStars > 0 && onMinStarsChange) || (captured !== "any" && onCapturedChange) ? (
          // A filter is the likeliest reason for an empty list, so each one in force is named, with a way to take it off.
          <div className="flex flex-col items-center gap-3 rounded-[20px] bg-[var(--feed-card)] p-10 text-center text-sm text-muted-foreground" data-feed-empty data-feed-filter-empty {...(minStars > 0 ? { "data-feed-min-stars-empty": true } : {})} {...(captured !== "any" ? { "data-feed-captured-empty": true } : {})}>
            <p>{emptyFilterSentence({ captured, minStars, query: searching ? search?.query ?? "" : null })}</p>
            <div className="flex flex-wrap justify-center gap-2">
              {minStars > 0 && onMinStarsChange ? (
                <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-feed-min-stars-clear onClick={() => onMinStarsChange(0)} type="button">
                  <StarOffIcon aria-hidden="true" className="size-4" />Show any stars
                </button>
              ) : null}
              {captured !== "any" && onCapturedChange ? (
                <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-feed-captured-clear onClick={() => onCapturedChange("any")} type="button">
                  <FilesIcon aria-hidden="true" className="size-4" />Show any Captured
                </button>
              ) : null}
            </div>
          </div>
        ) : searching ? (
          show === "all" ? empty(`No References match “${search?.query}”.`) : (
            <div className="flex flex-col items-center gap-3 rounded-[20px] bg-[var(--feed-card)] p-10 text-center text-sm text-muted-foreground" data-feed-empty data-feed-search-empty>
              <p>{`No matches with Reviewed ${REVIEWED_LABELS[show]}`}</p>
              <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-feed-show-all onClick={() => onShowChange("all")} type="button">
                <CheckCheckIcon aria-hidden="true" className="size-4" />Show Reviewed Any
              </button>
            </div>
          )
        ) : sort === "quality" ? empty("No References have stars yet. Rate a Reference with stars and it will be listed here.")
        : empty(show === "rated"
          ? "Nothing reviewed yet. Accept or reject a reference and it will be listed here."
          : ratedCount && show === "unrated" ? "You are all caught up. Choose Any under Reviewed to see your answers." : "No references yet.")
      )}
    </div>
  );
}
