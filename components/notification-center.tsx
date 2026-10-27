"use client";

import { CheckIcon, ChevronDownIcon, CircleCheckBigIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { proposalReceiptMessage, stateLabel, type ProposalReceipt } from "../lib/proposals-admin";
import type { DraftLoad, ReviewLoad } from "../lib/review-client";
import { acceptPath, batchAnswer, draftView, rejectPath, undecidedDraftIds, withDecision, draftDecisionUpdate, type DraftChoice, type DraftView } from "../lib/review-drafts";
import {
  FILTER_LABELS, NOTIFICATION_FILTERS, buildNotificationItems, filterCount, previewsBySourceAddress, recentDecisions, showsSection, waitingText,
  type NotificationFilter,
} from "../lib/notification-feed";
import { answerUpdate, cyclotronAutoDecided, draftIdsOf, isDraftReview, sectionReviews, type AnswerInput, type CyclotronEntry, type DraftDecision, type ReviewRequest } from "../lib/review-requests";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { partitionReferenceFeed } from "../lib/reference-feed-ranking";
import { normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import type { ReferencePreview } from "../lib/reference-preview";
import { loadNotificationSnapshot, saveNotificationSnapshot } from "../lib/reference-feed-cache";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { SITE_BRAND } from "../lib/site-brand";
import { FIXTURE_DRAFTS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { DraftCard, FlagCard, NotificationSkeleton, RecentDecisions, RequestCard, type DecisionExtras } from "./notification-cards";
import { FEED_SURFACE_PROPS, FeedCard, PILL, ReferenceFeedSkeleton } from "./reference-feed";
import type { ReviewChoice } from "./reference-review-card";

export type NotificationLoadState = "loading" | "ready" | "forbidden" | "unavailable";
export type DraftsLoadState = "loading" | "ready" | "failed";
export type DraftExtras = { why: string; notThisKind: boolean };

/** What a real-data preview shows instead of the invented sample (scripts/export-notification-center-fixture.py). */
export type NotificationFixture = { requests: ReviewRequest[]; drafts: Parameters<typeof draftView>[0][] };

const GRID = "grid gap-5 sm:grid-cols-2 xl:grid-cols-3";
/** References are shown a screenful at a time, ranked as in the References feed; the rest are one tap away. */
const REFERENCE_PAGE = 6;
const CONFIRMING = "Confirming your sign-in. You can answer in a moment.";
const NO_PREVIEWS: ReadonlyMap<string, ReferencePreview> = new Map();
const NO_VISIT: ReadonlySet<string> = new Set();

type ViewProps = {
  loadState: NotificationLoadState;
  requests: ReviewRequest[];
  /** Canonical References (any status) and the Cyclotron's decisions on them. */
  references?: ReferenceRecord[];
  decisions?: ReadonlyMap<string, RelevanceDecisionView>;
  previews?: ReadonlyMap<string, ReferencePreview>;
  referencesLoading?: boolean;
  predictionLoading?: boolean;
  referenceDisabledReason?: string | null;
  /** What the Cyclotron decided on its own confidence: read only, collapsed at the foot of the page. */
  autoDecided?: CyclotronEntry[];
  now?: number;
  visitRated?: ReadonlySet<string>;
  storyTitles?: Readonly<Record<string, string>>;
  deletedStories?: ReadonlySet<string>;
  demo?: boolean;
  /** True while the cards are a saved copy that is being refreshed. */
  stale?: boolean;
  busyId?: string | null;
  error?: string | null;
  /** The AI drafts that draft reviews are about, by proposal id, and which ids have no proposal on this site. */
  drafts?: Readonly<Record<string, DraftView>>;
  missingDrafts?: ReadonlySet<string>;
  draftsState?: DraftsLoadState;
  /** Keyed `<request id>#<draft id>`. */
  draftErrors?: Readonly<Record<string, string>>;
  draftBusyId?: string | null;
  /** Draft keys and request ids decided in this visit: their cards stay in place showing the answer. */
  stay?: ReadonlySet<string>;
  initialFilter?: NotificationFilter;
  onAnswer?: (request: ReviewRequest, input: AnswerInput) => void;
  onDecideDraft?: (request: ReviewRequest, draftId: string, choice: DraftChoice, extras: DraftExtras) => void;
  onRetryDrafts?: () => void;
  onMarkRead?: (requestId: string) => void;
  onOpenReference?: (lineageId: string) => void;
  onRateReference?: (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) => Promise<void> | void;
  onVisitRated?: (lineageId: string) => void;
};

function Section({ children, count, id, subtitle, title }: { children: ReactNode; count?: number; id: string; subtitle?: ReactNode; title: string }) {
  return (
    <section aria-labelledby={`notification-${id}`} data-notification-section={id}>
      <h2 className="mb-1 text-3xl font-bold tracking-tight text-primary sm:text-4xl" id={`notification-${id}`}>
        {title}{typeof count === "number" ? <span className="ml-2 text-xl font-semibold tabular-nums text-muted-foreground" data-section-count>{count}</span> : null}
      </h2>
      {subtitle ? <p className="mb-5 text-sm text-muted-foreground">{subtitle}</p> : <div className="mb-5" />}
      {children}
    </section>
  );
}

function Note({ children, ...rest }: { children: ReactNode } & Record<string, unknown>) {
  return <div className="rounded-[20px] bg-[var(--feed-card)] p-6 text-sm text-muted-foreground" {...rest}>{children}</div>;
}

/** The CMS console home. It answers one question, "What needs me?": cards for AI drafts, References and anything else, one tap to decide each. */
export function NotificationCenterView({
  loadState, requests, references = [], decisions, previews = NO_PREVIEWS, referencesLoading = false, predictionLoading = false, referenceDisabledReason = null,
  autoDecided = [], now = 0, visitRated = NO_VISIT, demo = false, stale = false, storyTitles = {}, deletedStories = new Set<string>(), busyId = null, error = null,
  drafts = {}, missingDrafts = new Set<string>(), draftsState = "ready", draftErrors = {}, draftBusyId = null, stay = new Set<string>(), initialFilter = "all",
  onAnswer, onDecideDraft, onRetryDrafts, onMarkRead, onOpenReference, onRateReference, onVisitRated,
}: ViewProps) {
  const [filter, setFilter] = useState<NotificationFilter>(initialFilter);
  const [shown, setShown] = useState(REFERENCE_PAGE);
  const session = stale ? CONFIRMING : null;

  const partition = useMemo(() => partitionReferenceFeed(references, decisions, { now, visitRated }), [references, decisions, now, visitRated]);
  const referenceItems = partition.feed;
  const waitingReferences = useMemo(() => referenceItems.filter((item) => normalizeReferenceCurationStatus(item.reference.curationStatus) === "pending").length, [referenceItems]);
  const items = useMemo(
    () => buildNotificationItems({ requests, drafts, missingDrafts, draftsState, stay, referenceCount: waitingReferences }),
    [requests, drafts, missingDrafts, draftsState, stay, waitingReferences],
  );
  const bySource = useMemo(() => previewsBySourceAddress(references, previews), [references, previews]);
  const recent = useMemo(() => recentDecisions(requests, references, demo), [requests, references, demo]);
  const openDraftRequests = useMemo(() => sectionReviews(requests).draftBatches, [requests]);
  const missingCount = openDraftRequests.reduce((total, request) => total + draftIdsOf(request).filter((id) => missingDrafts.has(id)).length, 0);

  if (loadState === "loading") return <NotificationSkeleton />;
  if (loadState === "forbidden") return <div data-notification-state="forbidden" role="alert"><strong>The Notification Center is for editors and admins</strong></div>;
  if (loadState === "unavailable") return <div data-notification-state="unavailable" role="alert"><strong>Review requests could not be read right now</strong><p>Try again in a minute. The current request state is unknown.</p></div>;

  const counts = items.counts;
  const nothing = counts.drafts + counts.references + counts.other === 0;
  const waitingText_ = waitingText(counts);
  const anyCards = items.drafts.length + items.reviews.length + items.flags.length + referenceItems.length > 0;
  const visibleReferences = referenceItems.slice(0, shown);
  const moreReferences = referenceItems.length - visibleReferences.length;
  const sectionGrid = (children: ReactNode, grid = GRID) => <div className={grid} data-notification-grid>{children}</div>;

  const draftCards = items.drafts.map((item) => (
    <DraftCard
      busy={draftBusyId === item.key} error={draftErrors[item.key] ?? null} item={item} key={item.key} previews={bySource} session={session}
      onDecide={(draftId, choice, extras) => onDecideDraft?.(item.request, draftId, choice, extras)}
    />
  ));
  const requestAnswer = (request: ReviewRequest, choice: DraftChoice, extras: DecisionExtras) =>
    onAnswer?.(request, choice === "accept" ? { decision: "approve", feedback: extras.why || null } : { decision: "reject", feedback: extras.why || null, steer: extras.notThisKind ? "not_this_kind" : null });

  return (
    <div className="space-y-10" data-notification-center {...FEED_SURFACE_PROPS}>
      <header className="space-y-4">
        <div className="space-y-1.5">
          <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl" data-notification-title>What needs me?</h1>
          <p className="text-lg text-muted-foreground" data-notification-summary role="status">{waitingText_}</p>
        </div>
        <div aria-label="Show" className="flex flex-wrap gap-1" data-notification-filters role="group">
          <div className="inline-flex max-w-full rounded-full bg-[var(--feed-card)] p-1">
            {NOTIFICATION_FILTERS.map((key) => {
              const on = filter === key;
              return (
                <button
                  aria-pressed={on}
                  className={cn(PILL, "min-h-9 gap-1 px-2 text-[0.8rem] sm:gap-1.5 sm:px-3.5 sm:text-sm", on ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "text-muted-foreground hover:text-foreground")}
                  data-notification-filter={key}
                  key={key}
                  onClick={() => setFilter(key)}
                  type="button"
                >
                  {on ? <CheckIcon aria-hidden="true" className="hidden size-3.5 sm:block" /> : null}
                  {FILTER_LABELS[key]}
                  <span className="text-xs tabular-nums opacity-70" data-notification-filter-count>{filterCount(key, counts)}</span>
                </button>
              );
            })}
          </div>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground" data-notification-ignore>
          Decide what you like and leave the rest. A draft you leave alone stays in Proposals, and nothing is published without an editor. Only a hard gate waits for you.
        </p>
        {stale ? <p className="text-xs text-muted-foreground" data-notification-stale role="status">Showing your last view while it updates.</p> : null}
        {demo ? <p className="text-xs text-muted-foreground" data-notification-demo>Preview: what you decide here is not saved.</p> : null}
        {error ? <p className="text-sm text-destructive" data-notification-error role="alert">{error}</p> : null}
      </header>

      {nothing && !anyCards && !referencesLoading ? (
        <div className="flex flex-col items-center gap-2 rounded-[20px] bg-[var(--feed-card)] px-6 py-12 text-center" data-notification-caught-up>
          <CircleCheckBigIcon aria-hidden="true" className="size-10 text-primary" />
          <h2 className="text-2xl font-bold tracking-tight">All caught up</h2>
          <p className="max-w-md text-sm text-muted-foreground">Nothing needs you right now. New drafts, references and reviews will appear here as they arrive.</p>
        </div>
      ) : null}

      {showsSection(filter, "drafts") && (items.drafts.length || draftsState === "failed" || missingCount > 0) ? (
        <Section count={counts.drafts} id="drafts" subtitle="AI story drafts. Accept sends one on to an editor in Proposals; Reject declines it." title="Drafts">
          {draftsState === "failed" ? (
            <Note role="alert">
              <p>The drafts could not be loaded right now.</p>
              <button className={cn(PILL, "mt-3 bg-[var(--feed-control)] text-foreground")} onClick={onRetryDrafts} type="button">Try again</button>
            </Note>
          ) : sectionGrid(draftCards)}
          {missingCount ? <p className="mt-4 text-sm text-muted-foreground">{missingCount} of these drafts {missingCount === 1 ? "is" : "are"} not in Proposals on this site, so they cannot be opened here.</p> : null}
        </Section>
      ) : null}

      {showsSection(filter, "references") && (referenceItems.length || referencesLoading) ? (
        <Section count={referencesLoading ? undefined : waitingReferences} id="references" subtitle="Sources the Cyclotron wants a person to rate. The same cards as the References feed, best bets first." title="References">
          {referencesLoading ? <ReferenceFeedSkeleton count={3} /> : (
            <>
              <div className={GRID} data-notification-grid data-notification-references>
                {visibleReferences.map((item) => (
                  <FeedCard
                    decision={item.decision} disabledReason={referenceDisabledReason} item={item} key={item.lineageId} lead={false} now={now}
                    onOpen={() => onOpenReference?.(item.lineageId)}
                    onRate={async (reference, choice, reasonCode) => { onVisitRated?.(item.lineageId); await onRateReference?.(reference, choice, reasonCode); }}
                    predictionLoading={predictionLoading} preview={previews.get(item.lineageId)} selected={false} visitRated={visitRated.has(item.lineageId)}
                  />
                ))}
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-2">
                {moreReferences > 0 ? (
                  <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-notification-more-references onClick={() => setShown((current) => current + REFERENCE_PAGE)} type="button">
                    Show {Math.min(moreReferences, REFERENCE_PAGE)} more
                  </button>
                ) : null}
                <Link className={cn(PILL, "text-muted-foreground hover:text-foreground")} href={getNewsroomNavHref("/newsroom/references", demo)}>
                  {partition.earlier.length ? `Open the References feed (${partition.earlier.length} earlier)` : "Open the References feed"}
                </Link>
              </div>
            </>
          )}
        </Section>
      ) : null}

      {showsSection(filter, "other") && items.reviews.length ? (
        <Section count={items.reviews.filter((item) => item.request.state === "open").length} id="reviews" subtitle="Reviews that are about more than one draft or one source." title="Reviews">
          {sectionGrid(items.reviews.map((item) => (
            <RequestCard
              busy={busyId === item.request.id} deleted={deletedStories} demo={demo} error={null} item={item} key={item.key}
              onAnswer={requestAnswer} onOpen={onMarkRead} session={session} titles={storyTitles}
            />
          )))}
        </Section>
      ) : null}

      {showsSection(filter, "other") && items.flags.length ? (
        <Section count={items.flags.filter((item) => item.request.state === "open").length} id="flags" subtitle="Nothing is waiting on these. Acknowledge them to clear them." title="For your information">
          {sectionGrid(items.flags.map((item) => (
            <FlagCard
              busy={busyId === item.request.id} deleted={deletedStories} demo={demo} error={null} item={item} key={item.key} onOpen={onMarkRead} session={session} titles={storyTitles}
              onAcknowledge={(request, note) => onAnswer?.(request, { decision: "acknowledge", feedback: note || null })}
            />
          )))}
        </Section>
      ) : null}

      {!nothing && filter !== "all" && filterCount(filter, counts) === 0 && !referencesLoading ? (
        <Note data-filter-empty>Nothing in {FILTER_LABELS[filter]} needs you right now.</Note>
      ) : null}

      {autoDecided.length ? (
        <details className="group rounded-[20px] bg-[var(--feed-card)] p-4" data-notification-section="auto-decided">
          <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronDownIcon aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
            Decided automatically ({autoDecided.length})
          </summary>
          <p className="mt-2 text-xs text-muted-foreground">Read only. The Cyclotron was confident enough to decide these without you. To correct one, open it in References.</p>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {autoDecided.map((entry) => (
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
        <Section id="decided" subtitle="The last few things you decided." title="Recently decided">
          <RecentDecisions entries={recent} />
        </Section>
      ) : null}
    </div>
  );
}

/** Everything the container reads and writes. The live one talks to the site's data API; tests pass a fake. */
export type NotificationApi = {
  loadReviews: () => Promise<ReviewLoad>;
  loadDrafts: (ids: string[]) => Promise<DraftLoad>;
  loadStoryTitles: (ids: string[]) => Promise<{ titles: Record<string, string>; deleted: string[] }>;
  answerReviewRequest: (request: ReviewRequest, input: AnswerInput, by: string) => Promise<ReviewRequest>;
  saveDraftDecision: (request: ReviewRequest, draftId: string, decision: DraftDecision) => Promise<ReviewRequest>;
  markReviewRead: (userKey: string, requestId: string) => Promise<void>;
  transitionProposalPath: (proposalId: string, path: readonly string[]) => Promise<ProposalReceipt>;
};

const liveApi: NotificationApi = {
  loadReviews: async () => (await import("../lib/review-client")).loadReviews(),
  loadDrafts: async (ids) => (await import("../lib/review-client")).loadDrafts(ids),
  loadStoryTitles: async (ids) => (await import("../lib/review-client")).loadStoryTitles(ids),
  answerReviewRequest: async (request, input, by) => (await import("../lib/review-client")).answerReviewRequest(request, input, by),
  saveDraftDecision: async (request, draftId, decision) => (await import("../lib/review-client")).saveDraftDecision(request, draftId, decision),
  markReviewRead: async (userKey, requestId) => (await import("../lib/review-client")).markReviewRead(userKey, requestId),
  transitionProposalPath: async (proposalId, path) => (await import("../lib/proposals-client")).transitionProposalPath(proposalId, path),
};

/** The demo and the real-data preview answer in memory with the same rules as the live data API; nothing leaves the page. */
const demoApi: NotificationApi = {
  loadReviews: async () => ({ state: "unavailable" }),
  loadDrafts: async () => ({ drafts: {}, missing: [], failed: [] }),
  loadStoryTitles: async () => ({ titles: {}, deleted: [] }),
  answerReviewRequest: async (request, input, by) => {
    const update = answerUpdate(request, input, by, new Date());
    return { ...request, state: "answered", answer: JSON.parse(String(update.answer)), links: update.links ? JSON.parse(String(update.links)) : request.links, history: JSON.parse(String(update.history)), updatedAt: String(update.updatedAt) };
  },
  saveDraftDecision: async (request, draftId, decision) => {
    const update = draftDecisionUpdate(request, draftId, decision);
    return { ...request, links: JSON.parse(String(update.links)), history: JSON.parse(String(update.history)), updatedAt: String(update.updatedAt) };
  },
  markReviewRead: async () => undefined,
  transitionProposalPath: async () => ({ status: "ok" }),
};

type ContainerProps = {
  references: ReferenceRecord[];
  decisions: ReadonlyMap<string, RelevanceDecisionView>;
  humanCuratedReferenceLineageIds?: ReadonlySet<string>;
  previews?: ReadonlyMap<string, ReferencePreview>;
  referencesLoading?: boolean;
  predictionLoading?: boolean;
  referenceDisabledReason?: string | null;
  onOpenReference?: (lineageId: string) => void;
  onRateReference?: (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) => Promise<void> | void;
  actorLabel: string;
  demo: boolean;
  /** A real-data preview (see scripts/export-notification-center-fixture.py); the invented sample otherwise. */
  fixture?: NotificationFixture | null;
  api?: NotificationApi;
};

const REFRESH_MILLISECONDS = 60_000;

/** Preview only: ?ncState=loading holds the skeleton, caught-up shows the empty state, sample swaps in the invented hard gate, flags and batches. */
function previewState(): "loading" | "caught-up" | "sample" | null {
  if (typeof window === "undefined" || !isLocalPreviewEnabled()) return null;
  const requested = new URLSearchParams(window.location.search).get("ncState");
  return requested === "loading" || requested === "caught-up" || requested === "sample" ? requested : null;
}

export function NotificationCenter({
  references, decisions, humanCuratedReferenceLineageIds = NO_VISIT, previews, referencesLoading, predictionLoading, referenceDisabledReason, onOpenReference, onRateReference, actorLabel, demo, fixture = null, api: liveOverride = liveApi,
}: ContainerProps) {
  const api = demo ? demoApi : liveOverride;
  const [loadState, setLoadState] = useState<NotificationLoadState>("loading");
  const [stale, setStale] = useState(false);
  const [requests, setRequests] = useState<ReviewRequest[]>([]);
  const [userKey, setUserKey] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storyTitles, setStoryTitles] = useState<Record<string, string>>({});
  const [deletedStories, setDeletedStories] = useState<ReadonlySet<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, DraftView>>({});
  const [missingDrafts, setMissingDrafts] = useState<ReadonlySet<string>>(new Set());
  const [draftsState, setDraftsState] = useState<DraftsLoadState>("loading");
  const [draftErrors, setDraftErrors] = useState<Record<string, string>>({});
  const [draftBusyId, setDraftBusyId] = useState<string | null>(null);
  const [stay, setStay] = useState<ReadonlySet<string>>(new Set());
  const [visitRated, setVisitRated] = useState<ReadonlySet<string>>(new Set());
  const [now] = useState(() => Date.now());
  const resolving = useRef(new Set<string>());
  const demoStarted = useRef(false);
  const preview = useMemo(() => previewState(), []);
  const sample = useMemo(() => {
    if (preview === "sample" || !fixture) return { requests: FIXTURE_REVIEW_REQUESTS, drafts: FIXTURE_DRAFTS };
    return { requests: preview === "caught-up" ? [] : fixture.requests, drafts: fixture.drafts };
  }, [fixture, preview]);

  const keep = useCallback((key: string) => setStay((current) => (current.has(key) ? current : new Set(current).add(key))), []);

  const loadDraftsFor = useCallback(async (list: ReviewRequest[]) => {
    const ids = list.filter((request) => request.state === "open" && isDraftReview(request)).flatMap(draftIdsOf);
    if (!ids.length) {
      setDraftsState("ready");
      return;
    }
    if (demo) {
      const known = sample.drafts.filter((row) => ids.includes(row.id));
      setDrafts((current) => ({ ...current, ...Object.fromEntries(known.map((row) => [row.id, draftView(row, true)])) }));
      setMissingDrafts(new Set(ids.filter((id) => !known.some((row) => row.id === id))));
      setDraftsState("ready");
      return;
    }
    try {
      const loaded = await api.loadDrafts(ids);
      setDrafts((current) => ({ ...current, ...loaded.drafts }));
      setMissingDrafts(new Set(loaded.missing));
      setDraftsState(loaded.failed.length ? "failed" : "ready");
    } catch {
      setDraftsState("failed");
    }
  }, [api, demo, sample]);

  // A return visit paints the last view at once, marked as such, while the real reads run.
  useEffect(() => {
    if (demo) return;
    const snapshot = loadNotificationSnapshot(SITE_BRAND.id);
    if (!snapshot) return;
    setRequests(snapshot.requests);
    setDrafts(snapshot.drafts);
    setMissingDrafts(new Set(snapshot.missing));
    setDraftsState("ready");
    setStale(true);
    setLoadState((current) => (current === "loading" ? "ready" : current));
  }, [demo]);

  const refresh = useCallback(async () => {
    if (demo) {
      // The sample is read once: answering in the preview must not be undone by the next refresh.
      if (demoStarted.current) return;
      demoStarted.current = true;
      setRequests(sample.requests);
      setLoadState("ready");
      void loadDraftsFor(sample.requests);
      return;
    }
    try {
      const loaded = await api.loadReviews();
      if (loaded.state !== "ready") {
        setStale(false);
        setLoadState(loaded.state);
        return;
      }
      setRequests(loaded.requests);
      setUserKey(loaded.userKey);
      setStale(false);
      setLoadState("ready");
      void loadDraftsFor(loaded.requests);
      const stories = await api.loadStoryTitles(loaded.requests.filter((request) => request.subject.type === "story").map((request) => request.subject.id)).catch(() => ({ titles: {}, deleted: [] as string[] }));
      setStoryTitles(stories.titles);
      setDeletedStories(new Set(stories.deleted));
    } catch {
      setStale(false);
      setLoadState("unavailable");
    }
  }, [api, demo, loadDraftsFor, sample]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Keep a display copy for the next visit once the live read and its drafts have arrived.
  useEffect(() => {
    if (demo || stale || loadState !== "ready" || draftsState !== "ready") return;
    const timer = window.setTimeout(() => saveNotificationSnapshot(SITE_BRAND.id, { requests, drafts, missing: missingDrafts }), 800);
    return () => window.clearTimeout(timer);
  }, [demo, draftsState, drafts, loadState, missingDrafts, requests, stale]);

  const markRead = useCallback(async (requestId: string) => {
    if (demo || !userKey) return;
    await api.markReviewRead(userKey, requestId).catch(() => undefined);
  }, [api, demo, userKey]);

  const answer = useCallback(async (request: ReviewRequest, input: AnswerInput) => {
    setError(null);
    setBusyId(request.id);
    try {
      const saved = await api.answerReviewRequest(request, input, actorLabel);
      keep(request.id);
      setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
      await markRead(request.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the answer.");
    } finally {
      setBusyId(null);
    }
  }, [actorLabel, api, keep, markRead]);

  /** Accept or Reject one draft: the Proposal moves to approved or declined, the decision is recorded on the request, and the request closes once every draft is decided. */
  const decideDraft = useCallback(async (request: ReviewRequest, draftId: string, choice: DraftChoice, extras: DraftExtras) => {
    const key = `${request.id}#${draftId}`;
    setDraftErrors(({ [key]: _gone, ...rest }) => rest);
    setDraftBusyId(key);
    resolving.current.add(request.id);
    try {
      const view = drafts[draftId];
      if (!view) throw new Error("This draft has not loaded yet.");
      const path = choice === "accept" ? acceptPath(view.state) : rejectPath(view.state);
      if (!path) throw new Error(`This draft is ${stateLabel(view.state, false).toLowerCase()} and cannot be ${choice === "accept" ? "accepted" : "rejected"} from here. Open it in Proposals.`);
      const receipt = await api.transitionProposalPath(draftId, path);
      if (receipt.status !== "ok") throw new Error(proposalReceiptMessage(receipt));
      const decided: DraftView = { ...view, state: choice === "accept" ? "approved" : "declined", decided: choice };
      const nextDrafts = { ...drafts, [draftId]: decided };
      setDrafts(nextDrafts);
      keep(key);
      const decision: DraftDecision = { choice, title: view.headline, why: extras.why || null, notThisKind: choice === "reject" && extras.notThisKind, by: actorLabel, at: new Date().toISOString() };
      const withDecisionRequest = { ...request, links: withDecision(request, draftId, decision) };
      const closing = batchAnswer(withDecisionRequest, nextDrafts, { by: actorLabel, at: decision.at });
      try {
        const saved = closing ? await api.answerReviewRequest(request, closing, actorLabel) : await api.saveDraftDecision(request, draftId, decision);
        setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
        if (closing) await markRead(request.id);
      } catch (failure) {
        throw new Error(`The draft was ${choice === "accept" ? "accepted" : "rejected"} in Proposals, but this request could not record it. ${failure instanceof Error ? failure.message : ""}`.trim());
      }
    } catch (failure) {
      setDraftErrors((current) => ({ ...current, [key]: failure instanceof Error ? failure.message : "Could not save the decision." }));
      if (!demo) void loadDraftsFor([request]);
    } finally {
      resolving.current.delete(request.id);
      setDraftBusyId(null);
    }
  }, [actorLabel, api, demo, drafts, keep, loadDraftsFor, markRead]);

  // Drafts decided in Proposals (not here) still close their request.
  useEffect(() => {
    if (demo || draftsState !== "ready" || stale) return;
    for (const request of requests) {
      if (request.state !== "open" || !isDraftReview(request) || resolving.current.has(request.id)) continue;
      if (undecidedDraftIds(request, drafts).length) continue;
      const closing = batchAnswer(request, drafts, { by: "an editor in Proposals", at: new Date().toISOString() });
      if (!closing) continue;
      resolving.current.add(request.id);
      void (async () => {
        try {
          const saved = await api.answerReviewRequest(request, closing, "an editor in Proposals");
          setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
        } catch {
          // The next refresh shows what became of it.
        } finally {
          resolving.current.delete(request.id);
        }
      })();
    }
  }, [api, demo, drafts, draftsState, requests, stale]);

  // Preview only: caught-up hides what is still pending; loading holds the skeleton.
  const autoDecided = useMemo(() => cyclotronAutoDecided(references, decisions, humanCuratedReferenceLineageIds, demo), [references, decisions, humanCuratedReferenceLineageIds, demo]);
  const shownReferences = preview === "caught-up" ? references.filter((reference) => normalizeReferenceCurationStatus(reference.curationStatus) !== "pending") : references;
  return (
    <NotificationCenterView
      autoDecided={autoDecided} busyId={busyId} decisions={decisions} deletedStories={deletedStories} demo={demo} draftBusyId={draftBusyId} draftErrors={draftErrors} drafts={drafts} draftsState={draftsState}
      error={error} loadState={preview === "loading" ? "loading" : loadState} missingDrafts={missingDrafts} now={now} onAnswer={(request, input) => void answer(request, input)}
      onDecideDraft={(request, draftId, choice, extras) => void decideDraft(request, draftId, choice, extras)} onMarkRead={(requestId) => void markRead(requestId)}
      onOpenReference={onOpenReference} onRateReference={onRateReference} onRetryDrafts={() => void loadDraftsFor(requests)}
      onVisitRated={(lineageId) => setVisitRated((current) => (current.has(lineageId) ? current : new Set(current).add(lineageId)))}
      predictionLoading={predictionLoading} previews={previews} referenceDisabledReason={referenceDisabledReason} references={shownReferences} referencesLoading={referencesLoading}
      requests={requests} stale={stale} stay={stay} storyTitles={storyTitles} visitRated={visitRated}
    />
  );
}
