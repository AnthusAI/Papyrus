"use client";

import {
  CheckIcon, ChevronDownIcon, CircleCheckBigIcon, CircleCheckIcon, CircleXIcon, ClipboardCheckIcon, FileWarningIcon, FlagIcon, InfoIcon, LayoutPanelLeftIcon, LightbulbIcon,
  Loader2Icon, LockIcon, MailIcon, NewspaperIcon, SlidersHorizontalIcon, Undo2Icon, type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { ReferenceAttachmentRecord } from "../lib/category-repository";
import type { MonitoringEmailDetails } from "../lib/monitoring-overview";
import {
  NEEDS_ME_FILTERS, NEEDS_ME_FILTER_LABELS, NEEDS_ME_TYPE_LABELS, applyNeedsMeSnapshot, countNeedsMe, matchesFilter, rankNeedsMe, takeNeedsMeSnapshot,
  type ConfidenceThreshold, type NeedsMeFilter, type NeedsMeSnapshot, type NeedsMeType, type ShapingStats,
} from "../lib/needs-me-ranking";
import { waitingTextFor, type NeedsMeEntry } from "../lib/needs-me-items";
import type { CyclotronEntry } from "../lib/review-requests";
import { referenceReasonCode, REFERENCE_REJECTION_REASON_CODES, normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import { formatFeedAge } from "../lib/reference-preview";
import { buildNeedsMeItemPath, parseNeedsMeItemIdFromNewsroomPathname } from "../lib/newsroom-index-filters";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { IDEA_STAGE, type RecentDecision } from "../lib/notification-feed";
import { getKanbusTheme, SITE_BRAND } from "../lib/site-brand";
import { NeedsMeDetail, type DecisionExtras } from "./needs-me-detail";
import { FlagFooter, decidedChoiceOf, isReferenceLike, recordedAnswer } from "./needs-me-shared";
import { NotificationSkeleton, RecentDecisions } from "./notification-cards";
import { FEED_GRID, FEED_SURFACE_PROPS, FeedImage, PILL, REASON_LABELS, SELECTED_RING, SourceMark } from "./reference-feed";
import { predictionFromDecision, ReviewQueueBar, useQueueGestures, type CardPrediction, type ReviewChoice } from "./reference-review-card";
import type { CorrectCaptureAction } from "./reference-capture-client";
import { DecisionControl } from "./decision-control";
import { useMediaQuery } from "./use-media-query";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";

/** What the editor chose and typed: the one shape every type's decision arrives in. */
export type NeedsMeDecision = { choice: ReviewChoice; reasonCode: ReferenceRejectionReasonCode | null; why: string; notThisKind: boolean };

const TYPE_ICON: Record<NeedsMeType, LucideIcon> = {
  reference: NewspaperIcon, idea_batch: LightbulbIcon, stage_review: ClipboardCheckIcon, held_email: MailIcon, incomplete_capture: FileWarningIcon, concept_proposal: LightbulbIcon, flag: FlagIcon,
};
const TYPE_HUE: Record<NeedsMeType, number> = { reference: 215, idea_batch: 150, stage_review: 270, held_email: 25, incomplete_capture: 45, concept_proposal: 330, flag: 190 };

function cardPrediction(item: NeedsMeEntry, predictionLoading: boolean): CardPrediction {
  if (item.payload.kind === "reference" && item.payload.decision) return predictionFromDecision(item.payload.decision);
  if (item.prediction) return { state: "ready", choice: item.prediction.label, confidence: item.prediction.confidence };
  return predictionLoading ? { state: "loading" } : { state: "none" };
}

/** Words for why an item cannot be decided right now, or null. */
export function disabledFor(item: NeedsMeEntry, session: string | null, referenceReason: string | null): string | null {
  if (session) return session;
  if (isReferenceLike(item)) return referenceReason;
  return null;
}

// --- the card -----------------------------------------------------------------------------------------------------

/** For an item with no picture: the type's own tile, an icon and its name, so a card is never just a colour. */
function TypeTile({ type }: { type: NeedsMeType }) {
  const Icon = TYPE_ICON[type];
  const hue = TYPE_HUE[type];
  return (
    <div
      className="relative flex aspect-[16/10] w-full flex-col items-center justify-center gap-2 overflow-hidden p-4 text-white"
      data-needs-me-tile={type}
      style={{ background: `linear-gradient(135deg, oklch(0.58 0.1 ${hue}), oklch(0.4 0.11 ${(hue + 45) % 360}))` }}
    >
      <Icon aria-hidden="true" className="size-12" />
      <span className="text-sm font-semibold tracking-wide opacity-90">{NEEDS_ME_TYPE_LABELS[type]}</span>
    </div>
  );
}

function TypeBadge({ item }: { item: NeedsMeEntry }) {
  const Icon = item.hardGate ? LockIcon : TYPE_ICON[item.type];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground" data-needs-me-badge={item.type}>
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {NEEDS_ME_TYPE_LABELS[item.type]}{item.hardGate ? " · Hard gate" : ""}
    </span>
  );
}

/** An idea batch is decided on the board, so its footer is a link to the Idea column and says how many of its ideas still wait there. */
function IdeaBatchFooter({ boardHref, count, total }: { boardHref: string; count: number; total: number }) {
  return (
    <div className="space-y-2" data-idea-batch-footer>
      <Link className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-[16px] bg-[var(--feed-control)] px-3 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-2 focus-visible:ring-ring" data-idea-batch-open href={boardHref}>
        <LayoutPanelLeftIcon aria-hidden="true" className="size-4" />Open the Idea column
      </Link>
      {total ? <p className="text-center text-xs text-muted-foreground" data-idea-batch-count>{count} of {total} still in the Idea column</p> : null}
    </div>
  );
}

export function NeedsMeCard({ item, now, onOpen, predictionLoading, ratings, selected, disabledReason }: {
  item: NeedsMeEntry;
  now: number;
  onOpen: () => void;
  predictionLoading: boolean;
  ratings: RatingController;
  selected: boolean;
  disabledReason: string | null;
}) {
  const titleId = useId();
  const refLike = isReferenceLike(item);
  const decided = decidedChoiceOf(item);
  const rating = ratings.get(item.id);
  const chosen = rating.pending ?? decided;
  const locked = !refLike && item.decisionState !== "open";
  const feedback = rating.feedback.phase === "idle" && decided ? { phase: "saved" as const } : rating.feedback;
  const reason = item.payload.kind === "reference" ? rating.reasonCode : null;
  const reasonLabel = decided === "reject" && reason ? REASON_LABELS[reason] : null;
  // A decided item shows the Why it was given (clipped; the whole text is edited in the detail pane).
  const why = !refLike && locked ? rating.note?.trim() ?? "" : "";
  const whyLine = why ? `Why: ${why.length > 90 ? `${why.slice(0, 89).trimEnd()}\u2026` : why}` : null;
  const time = item.payload.kind === "reference" ? item.payload.displayTime ?? item.createdAt : item.createdAt;
  const age = formatFeedAge(time, now);
  const picture = item.image || item.host ? <FeedImage host={item.host} lead={false} name={item.source} src={item.image} /> : <TypeTile type={item.type} />;
  const requestId = item.payload.kind === "ideas" || item.payload.kind === "request" ? item.payload.request.id : undefined;
  const flag = item.type === "flag";
  const ideaBatch = item.payload.kind === "ideas" ? item.payload : null;

  return (
    <article
      aria-current={selected ? "true" : undefined}
      aria-labelledby={titleId}
      className={cn(
        "relative flex flex-col overflow-hidden rounded-[20px] text-card-foreground transition-[background-color,box-shadow] duration-200",
        selected ? "bg-[var(--feed-control)]" : "bg-[var(--feed-card)]",
      )}
      data-feed-card={item.id}
      data-feed-rated={decided ?? undefined}
      data-feed-selected={selected || undefined}
      style={selected ? SELECTED_RING : undefined}
      data-needs-me-card={item.type}
      data-needs-me-state={item.decisionState}
      data-newsroom-card-id={item.id}
      data-review-request={requestId}
    >
      <button
        aria-label={`Open: ${item.title}`}
        className="flex flex-1 flex-col text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        data-feed-open
        onClick={onOpen}
        type="button"
      >
        {picture}
        <span className="flex flex-1 flex-col gap-2.5 p-5">
          <TypeBadge item={item} />
          <span className="flex items-center gap-2 text-xs font-medium text-muted-foreground" data-feed-source>
            <SourceMark host={item.host} />
            <span className="truncate">{item.source}</span>
          </span>
          <span className="line-clamp-3 break-words text-xl font-bold leading-[1.15] tracking-tight text-foreground" data-feed-title id={titleId}>{item.title}</span>
          {item.dek ? <span className="line-clamp-2 break-words text-sm text-muted-foreground" data-feed-dek>{item.dek}</span> : null}
          <span className="mt-auto flex flex-col gap-1 pt-1 text-xs text-muted-foreground">
            <span>
              {age ? <time dateTime={new Date(time ?? now).toISOString()}>{age}</time> : null}
              {age && item.host ? <span aria-hidden="true"> · </span> : null}
              {item.host}
            </span>
            {decided || item.decisionState === "acknowledged" ? null : (
              <span className="line-clamp-2 flex items-start gap-1.5" data-needs-me-default>
                <Undo2Icon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                <span>{item.defaultOutcome}</span>
              </span>
            )}
          </span>
        </span>
      </button>

      <div className="relative bg-[var(--feed-footer)] p-3" data-feed-actions>
        {ideaBatch ? (
          <IdeaBatchFooter boardHref={ideaBatch.boardHref} count={ideaBatch.ideas.filter((idea) => idea.stage === null || idea.stage === IDEA_STAGE).length} total={ideaBatch.ideas.length} />
        ) : flag ? (
          <FlagFooter busy={rating.feedback.phase === "saving"} disabledReason={disabledReason} done={item.decisionState === "acknowledged"} error={rating.feedback.phase === "error" ? rating.feedback.message ?? null : null} onAcknowledge={() => ratings.choose(item.id, "accept")} />
        ) : (
          <DecisionControl
            answer={chosen}
            decided={decided}
            disabled={Boolean(disabledReason) || locked}
            disabledReason={disabledReason}
            feedback={feedback}
            needsReason={refLike && rating.askReason}
            note={reasonLabel ? `Reason: ${reasonLabel}` : locked ? whyLine ?? "Decided here." : null}
            onChoose={(choice) => { if (!disabledReason && !locked) ratings.choose(item.id, choice); }}
            onReasonChange={(text) => ratings.setNote(item.id, text)}
            onReasonCommit={() => { if (!disabledReason && !locked) ratings.commitNote(item.id); }}
            prediction={cardPrediction(item, predictionLoading)}
            reason={rating.note ?? ""}
            reasonRequiredFor={refLike ? "reject" : null}
            showPrediction={refLike}
            showReason={refLike}
          />
        )}
      </div>
    </article>
  );
}

// --- the strip, the pills, the recipe -----------------------------------------------------------------------------------

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "You're shaping this": what you decided this week, and how it sat with the Cyclotron. Words and icons, never colour alone. */
export function ShapingStrip({ stats }: { stats: ShapingStats }) {
  const none = stats.decisions === 0;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-[20px] bg-[var(--feed-card)] px-4 py-3 text-sm" data-shaping-strip role="status">
      <span className="inline-flex items-center gap-1.5 font-semibold"><SlidersHorizontalIcon aria-hidden="true" className="size-4" />You&rsquo;re shaping this</span>
      {none ? (
        <span className="text-muted-foreground" data-shaping-empty>Nothing decided yet this week. Each answer teaches the Cyclotron and reorders what comes next.</span>
      ) : (
        <>
          <span className="text-muted-foreground">This week</span>
          <span className="inline-flex items-center gap-1.5" data-shaping-decisions><CheckIcon aria-hidden="true" className="size-4" /><b className="tabular-nums">{stats.decisions}</b> {stats.decisions === 1 ? "decision" : "decisions"}</span>
          <span className="inline-flex items-center gap-1.5" data-shaping-agreed><CircleCheckIcon aria-hidden="true" className="size-4" /><b className="tabular-nums">{stats.agreed}</b> agreed with the Cyclotron</span>
          <span className="inline-flex items-center gap-1.5" data-shaping-overruled><CircleXIcon aria-hidden="true" className="size-4" /><b className="tabular-nums">{stats.overruled}</b> overruled it</span>
        </>
      )}
    </div>
  );
}

/** The plain-words recipe, with this site's learned numbers in it. */
export function NeedsMeRecipe({ threshold }: { threshold: ConfidenceThreshold }) {
  return (
    <div className="space-y-3 rounded-[20px] bg-[var(--feed-card)] p-5 text-sm" data-needs-me-recipe>
      <p className="text-base font-bold">A feed run by algorithms you control</p>
      <ol className="list-decimal space-y-2.5 pl-5">
        <li><strong>Hard gates first.</strong> Nothing continues until you decide one.</li>
        <li><strong>Then where your answer matters most.</strong> Each item is scored by how unsure the Cyclotron is, times how much it matters. Age does not change it. A coin toss scores highest; a sure thing scores lowest; no prediction counts as halfway.</li>
        <li><strong>A mix, not a run.</strong> Never more than two of one kind in a row while something else is waiting.</li>
        <li><strong>Confident items do not ask for you.</strong> {threshold.threshold !== null
          ? <>Items the Cyclotron is surer about than {Math.round((1 - threshold.threshold) * 100)}% (the median of the {threshold.examples} predictions you confirmed) wait under Decided automatically. You can overrule any of them.</>
          : <>Nothing is skipped yet. The line is learned from the predictions you confirm, and so far there are {threshold.examples} of the 10 needed.</>}</li>
        <li><strong>Your answers stay put.</strong> The order is taken once when you arrive. What you decide stays where it is for this visit.</li>
      </ol>
    </div>
  );
}

// --- the view -----------------------------------------------------------------------------------------------------------

export type NeedsMeLoadState = "loading" | "ready" | "forbidden" | "unavailable";
const NO_EXTRAS: DecisionExtras = { notThisKind: false };
const NO_ATTACHMENTS: ReferenceAttachmentRecord[] = [];

export type NeedsMeViewProps = {
  loadState: NeedsMeLoadState;
  entries: NeedsMeEntry[];
  threshold: ConfidenceThreshold;
  now: number;
  shaping: ShapingStats;
  recent: RecentDecision[];
  /** Read-only classifications the Cyclotron made on its own, other than the confident items above. */
  legacyAuto?: CyclotronEntry[];
  /** True once every source has been read: the order is taken then, and not before. */
  settled: boolean;
  demo?: boolean;
  /** True while the cards are a saved copy that is being refreshed. */
  stale?: boolean;
  error?: string | null;
  referencesLoading?: boolean;
  predictionLoading?: boolean;
  referenceDisabledReason?: string | null;
  initialFilter?: NeedsMeFilter;
  referenceAttachments?: ReferenceAttachmentRecord[];
  captureTeaserLine?: number;
  onCorrectCapture?: CorrectCaptureAction;
  onDecide: (item: NeedsMeEntry, decision: NeedsMeDecision) => Promise<void>;
  /** Changes only the Why of an item that is already decided (a review request, a held email). Throws a sentence when it cannot. */
  onEditReason?: (item: NeedsMeEntry, why: string) => Promise<void>;
  onOpened?: (item: NeedsMeEntry) => void;
  loadEmail?: (receiptId: string) => Promise<MonitoringEmailDetails>;
  /** Other sections of the page (open assignments, sections). They scroll inside the feed, below the cards, so the feed and the detail keep the viewport's full height. */
  below?: ReactNode;
};

function Note({ children, ...rest }: { children: ReactNode } & Record<string, unknown>) {
  return <div className="rounded-[20px] bg-[var(--feed-card)] p-6 text-sm text-muted-foreground" {...rest}>{children}</div>;
}

/** The CMS console home: one feed that mixes everything that may need a person, with the References feed's cards and detail pane. */
export function NeedsMeView({
  loadState, entries, threshold, now, shaping, recent, legacyAuto = [], settled, demo = false, stale = false, error = null, referencesLoading = false, predictionLoading = false,
  referenceDisabledReason = null, initialFilter = "all", referenceAttachments = NO_ATTACHMENTS, captureTeaserLine, onCorrectCapture, onDecide, onEditReason, onOpened, loadEmail, below,
}: NeedsMeViewProps) {
  const themeMode = useResolvedPapyrusTheme();
  const themeAttributes = { "data-kanbus-theme": getKanbusTheme(SITE_BRAND), "data-color-mode": themeMode };
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [filter, setFilter] = useState<NeedsMeFilter>(initialFilter);
  // The open item lives in the address (`/needs-me/<id>`), so it can be linked, bookmarked and reopened with Back.
  const pathname = usePathname() ?? (typeof window === "undefined" ? null : window.location.pathname);
  const routeId = useMemo(() => parseNeedsMeItemIdFromNewsroomPathname(pathname) ?? "", [pathname]);
  const [selectedId, setSelectedId] = useState(routeId);
  const [caughtUp, setCaughtUp] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [recipeOpen, setRecipeOpen] = useState(false);
  const [extras, setExtras] = useState<Record<string, DecisionExtras>>({});
  const [scrollTarget, setScrollTarget] = useState<{ id: string; nonce: number } | null>(null);
  const [, bumpOrder] = useState(0);
  const session = stale ? "Confirming your sign-in. You can answer in a moment." : null;

  // The order is taken ONCE per visit, when every source has been read, and then left alone: selecting, deciding, a refresh or a cache
  // revalidation changes what the cards say, never where they are. Items that arrive later wait behind a "N new items: show" pill.
  const live = useMemo(() => rankNeedsMe(entries, { threshold }), [entries, threshold]);
  const snapshot = useRef<NeedsMeSnapshot | null>(null);
  if (!snapshot.current && settled && entries.length > 0) snapshot.current = takeNeedsMeSnapshot(live);
  const placed = snapshot.current ? applyNeedsMeSnapshot(snapshot.current, live) : { feed: live.feed, auto: live.auto, newCount: 0 };
  const showNewItems = () => { snapshot.current = takeNeedsMeSnapshot(live); bumpOrder((count) => count + 1); };

  const byId = useMemo(() => new Map(entries.map((item) => [item.id, item])), [entries]);
  const latest = useRef({ byId, extras });
  latest.current = { byId, extras };
  const ratings = useRatingStore({
    save: async (id, choice, detail) => {
      const item = latest.current.byId.get(id);
      if (!item) throw new Error("This item is no longer in the list.");
      const typed = latest.current.extras[id] ?? NO_EXTRAS;
      await onDecide(item, { choice, reasonCode: detail.reasonCode, why: detail.note, notThisKind: choice === "reject" && typed.notThisKind });
    },
    // The Why of a review request or a held email is typed in either order and edited after the decision, onto that decision.
    sticky: (id) => { const item = latest.current.byId.get(id); return item ? !isReferenceLike(item) : false; },
    saveNote: async (id, note) => {
      const item = latest.current.byId.get(id);
      if (!item) throw new Error("This item is no longer in the list.");
      if (!onEditReason) throw new Error("A reason cannot be changed here.");
      await onEditReason(item, note);
    },
    // An acknowledged flag counts as an Accept: it is decided, and only its note can change.
    saved: (id) => { const item = latest.current.byId.get(id); return item ? decidedChoiceOf(item) ?? (item.decisionState === "acknowledged" ? "accept" : null) : null; },
    seed: (id) => {
      const item = latest.current.byId.get(id);
      if (!item) return { note: "", reasonCode: null };
      if (item.payload.kind !== "reference") return { note: recordedAnswer(item).why ?? "", reasonCode: null };
      const { reference } = item.payload;
      const pending = normalizeReferenceCurationStatus(reference.curationStatus) === "pending";
      return { note: pending ? "" : reference.curationStatusReason ?? "", reasonCode: referenceReasonCode(reference) ?? null };
    },
    needsReason: (id) => { const item = latest.current.byId.get(id); return item ? isReferenceLike(item) : true; },
  });

  const counts = useMemo(() => countNeedsMe(placed.feed), [placed.feed]);
  const visible = placed.feed.filter((item) => matchesFilter(item, filter));
  const queue = visible.map((item) => item.id);
  const selected = byId.get(selectedId) ?? null;
  const selectedIndex = selected ? queue.indexOf(selected.id) : -1;
  const previousId = caughtUp ? queue[queue.length - 1] ?? null : selectedIndex > 0 ? queue[selectedIndex - 1] : null;
  const nextId = selectedIndex >= 0 && selectedIndex < queue.length - 1 ? queue[selectedIndex + 1] : null;

  const showInAddress = (id: string, mode: "push" | "replace") => {
    if (demo || typeof window === "undefined") return;
    const next = id ? buildNeedsMeItemPath(id) : getNewsroomNavHref("/newsroom");
    if (`${window.location.pathname}${window.location.search}` === next) return;
    if (mode === "push") window.history.pushState(null, "", next);
    else window.history.replaceState(null, "", next);
  };
  const select = (item: NeedsMeEntry) => {
    setCaughtUp(false);
    setSelectedId(item.id);
    if (isMobile) setSheetOpen(true);
    showInAddress(item.id, "push");
    onOpened?.(item);
  };
  const goNext = () => {
    if (nextId) { setCaughtUp(false); setSelectedId(nextId); showInAddress(nextId, "replace"); setScrollTarget({ id: nextId, nonce: Date.now() }); const next = byId.get(nextId); if (next) onOpened?.(next); }
    else if (!caughtUp) { setCaughtUp(true); setSelectedId(""); showInAddress("", "replace"); }
  };
  const goPrevious = () => {
    if (previousId) { setCaughtUp(false); setSelectedId(previousId); showInAddress(previousId, "replace"); setScrollTarget({ id: previousId, nonce: Date.now() }); }
  };
  const gestures = useQueueGestures({ onNext: goNext, onPrevious: goPrevious });
  const closeDetail = () => { setCaughtUp(false); setSheetOpen(false); setSelectedId(""); showInAddress("", "replace"); };

  // Back and Forward (and a link opened in place) follow the address.
  useEffect(() => {
    setSelectedId(routeId);
    if (routeId) { setCaughtUp(false); if (isMobile) setSheetOpen(true); }
  }, [routeId, isMobile]);
  // A linked item that is not waiting any more (decided, or not yours) says so once everything is read, instead of an empty pane.
  const linkedGone = Boolean(routeId) && settled && !byId.has(routeId);

  // Previous / Next scrolls the feed to the same card, smoothly. Selecting a card by clicking it never scrolls.
  useEffect(() => {
    if (!scrollTarget || typeof document === "undefined") return;
    document.querySelector(`[data-feed-card="${CSS.escape(scrollTarget.id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [scrollTarget]);

  if (loadState === "loading") return <NotificationSkeleton />;
  if (loadState === "forbidden") return <div data-notification-state="forbidden" role="alert"><strong>The Notification Center is for editors and admins</strong></div>;
  if (loadState === "unavailable") return <div data-notification-state="unavailable" role="alert"><strong>Review requests could not be read right now</strong><p>Try again in a minute. The current request state is unknown.</p></div>;

  const waiting = counts.all;
  const autoCount = placed.auto.length + legacyAuto.length;
  const nothing = waiting === 0 && placed.feed.length === 0 && !referencesLoading;
  const detailBody = (item: NeedsMeEntry) => (
    <NeedsMeDetail
      attachments={referenceAttachments} captureTeaserLine={captureTeaserLine} demo={demo} disabledReason={disabledFor(item, session, referenceDisabledReason)} extras={extras[item.id] ?? NO_EXTRAS}
      item={item} loadEmail={loadEmail} onCorrectCapture={onCorrectCapture} onExtras={(next) => setExtras((current) => ({ ...current, [item.id]: next }))}
      predictionLoading={predictionLoading} ratings={ratings}
    />
  );
  const caughtUpPanel = (
    <div className="space-y-2 p-6 text-center" data-review-caught-up>
      <h3 className="text-lg font-semibold">All caught up</h3>
      <p className="text-sm text-muted-foreground">There is nothing more in this list. Use Previous to go back.</p>
    </div>
  );
  const queueBar = queue.length || caughtUp ? (
    <ReviewQueueBar anchored caughtUp={caughtUp} onNext={goNext} onPrevious={goPrevious} position={selectedIndex >= 0 ? selectedIndex + 1 : null} total={queue.length} />
  ) : null;

  return (
    <div className="flex flex-col gap-5 md:h-full md:flex-row md:items-stretch" data-notification-center {...FEED_SURFACE_PROPS}>
      <div className="@container min-w-0 flex-1 space-y-6 pb-6 md:min-h-0 md:overflow-y-auto px-1.5 pt-1.5 md:pr-2.5" data-needs-me-main data-needs-me-scroll>
        <header className="space-y-4">
          <div className="space-y-1.5">
            <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl" data-notification-title>What needs me?</h1>
            <p className="text-lg text-muted-foreground" data-notification-summary role="status">{waitingTextFor(counts)}</p>
          </div>
          <ShapingStrip stats={shaping} />
          {linkedGone ? <Note data-needs-me-link-gone role="status">The item in this link is not waiting for you any more: it was decided, or it is not yours to decide.</Note> : null}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div aria-label="Show" className="inline-flex max-w-full overflow-x-auto rounded-full bg-[var(--feed-card)] p-1" data-notification-filters role="group">
              {NEEDS_ME_FILTERS.map((key) => {
                const on = filter === key;
                return (
                  <button
                    aria-pressed={on}
                    className={cn(PILL, "min-h-9 shrink-0 gap-1 px-2 text-[0.8rem] sm:gap-1.5 sm:px-3.5 sm:text-sm", on ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "text-muted-foreground hover:text-foreground")}
                    data-notification-filter={key}
                    key={key}
                    onClick={() => setFilter(key)}
                    type="button"
                  >
                    {on ? <CheckIcon aria-hidden="true" className="hidden size-3.5 sm:block" /> : null}
                    {NEEDS_ME_FILTER_LABELS[key]}
                    <span className="text-xs tabular-nums opacity-70" data-notification-filter-count>{counts[key]}</span>
                  </button>
                );
              })}
            </div>
            <button
              aria-expanded={recipeOpen}
              className={cn(PILL, "text-muted-foreground hover:text-foreground", recipeOpen && "bg-[var(--feed-card)] text-foreground")}
              data-needs-me-recipe-toggle
              onClick={() => setRecipeOpen((open) => !open)}
              type="button"
            >
              <InfoIcon aria-hidden="true" className="size-4" />How this is ordered
            </button>
          </div>
          {recipeOpen ? <NeedsMeRecipe threshold={threshold} /> : null}
          <p className="max-w-3xl text-sm text-muted-foreground" data-notification-ignore>
            Decide what you like and leave the rest. Each item says what happens if you do nothing, and only a hard gate waits for you.
          </p>
          {stale ? <p className="text-xs text-muted-foreground" data-notification-stale role="status"><Loader2Icon aria-hidden="true" className="mr-1 inline size-3.5 animate-spin" />Showing your last view while it updates.</p> : null}
          {demo ? <p className="text-xs text-muted-foreground" data-notification-demo>Preview: what you decide here is not saved.</p> : null}
          {error ? <p className="text-sm text-destructive" data-notification-error role="alert">{error}</p> : null}
        </header>

        {placed.newCount > 0 ? (
          // Sits on top of the feed, outside its flow: announcing new items never moves a card.
          <div className="pointer-events-none sticky top-3 z-20 flex h-0 justify-center overflow-visible">
            <button
              className="pointer-events-auto inline-flex min-h-9 items-center rounded-full bg-[var(--feed-control)] px-4 text-sm font-medium text-foreground shadow-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-feed-new-items
              onClick={showNewItems}
              type="button"
            >
              {placed.newCount} new {placed.newCount === 1 ? "item" : "items"}: show
            </button>
          </div>
        ) : null}

        {nothing ? (
          <div className="flex flex-col items-center gap-2 rounded-[20px] bg-[var(--feed-card)] px-6 py-12 text-center" data-notification-caught-up>
            <CircleCheckBigIcon aria-hidden="true" className="size-10 text-primary" />
            <h2 className="text-2xl font-bold tracking-tight">All caught up</h2>
            <p className="max-w-md text-sm text-muted-foreground">Nothing needs you right now. New ideas, references, emails and reviews will appear here as they arrive.</p>
          </div>
        ) : null}

        {referencesLoading && !placed.feed.length ? (
          <NotificationSkeleton count={3} bare />
        ) : (
          <section aria-label="Needs you" data-needs-me-feed>
            <div className={FEED_GRID} data-feed-grid data-notification-grid>
              {visible.map((item) => (
                <NeedsMeCard
                  disabledReason={disabledFor(item, session, referenceDisabledReason)} item={item} key={item.id} now={now} onOpen={() => select(item)}
                  predictionLoading={predictionLoading} ratings={ratings} selected={selectedId === item.id}
                />
              ))}
            </div>
            {!nothing && visible.length === 0 && !referencesLoading ? <Note data-filter-empty>Nothing in {NEEDS_ME_FILTER_LABELS[filter]} needs you right now.</Note> : null}
          </section>
        )}

        {autoCount ? (
          <details className="group rounded-[20px] bg-[var(--feed-card)] p-4" data-notification-section="auto-decided">
            <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <ChevronDownIcon aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
              Decided automatically ({autoCount})
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">The Cyclotron was sure enough to go ahead without you, and its answer stands unless you overrule it. Overrule opens the item beside the feed.</p>
            <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {placed.auto.map((item) => (
                <li data-auto-decided={item.id} key={item.id}>
                  <div className="flex h-full flex-col gap-2 rounded-[16px] bg-[var(--feed-control)] p-3 text-sm">
                    <span className="block break-words font-medium leading-snug">{item.title}</span>
                    <span className="block text-xs text-muted-foreground" data-auto-decided-prediction>
                      Cyclotron: {item.prediction?.label === "reject" ? "Reject" : "Accept"}{item.prediction?.confidence != null ? ` ${Math.round(item.prediction.confidence * 100)}%` : ""} · {NEEDS_ME_TYPE_LABELS[item.type]}
                    </span>
                    <button className={cn(PILL, "mt-auto min-h-9 self-start bg-[var(--feed-card)] px-3 text-xs")} data-overrule onClick={() => select(item)} type="button">
                      <Undo2Icon aria-hidden="true" className="size-3.5" />Overrule
                    </button>
                  </div>
                </li>
              ))}
              {legacyAuto.map((entry) => (
                <li data-cyclotron-entry={entry.lineageId} key={entry.lineageId}>
                  <Link className="block rounded-[16px] bg-[var(--feed-control)] p-3 text-sm outline-none hover:bg-[var(--feed-control)]/70 focus-visible:ring-2 focus-visible:ring-ring" href={entry.href}>
                    <span className="block break-words font-medium leading-snug">{entry.title}</span>
                    <span className="block text-xs text-muted-foreground">
                      Classified as {entry.label} · {entry.confidence === null ? "confidence not recorded" : `confidence ${Math.round(entry.confidence * 100)}%`}{entry.reviewedByPerson ? " · reviewed by a person" : ""}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {recent.length ? (
          <section aria-labelledby="notification-decided" data-notification-section="decided">
            <h2 className="mb-1 text-3xl font-bold tracking-tight text-primary sm:text-4xl" id="notification-decided">Recently decided</h2>
            <p className="mb-5 text-sm text-muted-foreground">The last few things you decided.</p>
            <RecentDecisions entries={recent} />
          </section>
        ) : null}
        {below}
      </div>

      {/* The pane appears once something is selected (or when the queue is done); until then the feed has the whole width. */}
      <aside
        aria-label="Detail"
        className={cn("hidden min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-[20px] bg-[var(--feed-card)] md:h-full", (selected || caughtUp) && "md:flex", " md:w-[min(100%,24rem)] md:pb-16 lg:w-[min(100%,28rem)]")}
        data-feed-flat=""
        data-needs-me-detail-shell
        data-detail-open={selected ? "true" : "false"}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 px-4 pb-1 pt-3"><span className="text-sm font-medium text-foreground">Detail</span></div>
        <div className="flex min-h-0 flex-1 flex-col" data-review-gestures onPointerDown={gestures.onPointerDown} onPointerUp={gestures.onPointerUp} style={gestures.style}>
          <ScrollArea className="min-h-0 flex-1">
            {isMobile ? null : selected ? <div key={selected.id}>{detailBody(selected)}</div> : caughtUp ? caughtUpPanel : null}
          </ScrollArea>
        </div>
        {queueBar}
      </aside>

      {isMobile ? (
        <Sheet onOpenChange={(open) => { if (!open) closeDetail(); else setSheetOpen(true); }} open={(sheetOpen && Boolean(selected)) || caughtUp}>
          <SheetContent className="gap-0 rounded-t-[length:var(--feed-radius-xl)] bg-[var(--feed-card)] p-0" data-feed-flat="" data-feed-surface="" initialFocus={false} side="bottom" {...themeAttributes}>
            <SheetHeader className="px-4 py-3"><SheetTitle className="text-left text-base">{selected ? NEEDS_ME_TYPE_LABELS[selected.type] : "Detail"}</SheetTitle></SheetHeader>
            {selected ? (
              <div className="min-w-0" data-review-gestures onPointerDown={gestures.onPointerDown} onPointerUp={gestures.onPointerUp} style={gestures.style}>
                <ScrollArea className="max-h-[70dvh]"><div key={selected.id}>{detailBody(selected)}</div></ScrollArea>
              </div>
            ) : caughtUp ? caughtUpPanel : null}
            {queueBar}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
