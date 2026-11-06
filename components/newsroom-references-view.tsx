"use client";

import { CreateStoryButton } from "./create-story-button";
import { StarsMark } from "./star-rating";
import { DETAIL_PANE_WIDTH, LIST_HIDDEN_WHEN_DETAIL_OPEN } from "./list-detail-layout";
import type { PrimingPanelProps } from "cyclotron/components/priming-panel";
import { ReferenceAddEntry } from "./reference-add-entry";
import { ReferenceCurationControls, useReferenceImport } from "./reference-curation-controls";

import { ArrowLeftIcon, ExternalLinkIcon, LayoutGridIcon, ListIcon, Loader2Icon, PlusIcon, RefreshCwIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import {
  buildReferencesIndexQuery,
  parseReferenceLineageIdFromNewsroomPathname,
  syncBrowserNewsroomIndexUrl,
} from "../lib/newsroom-index-filters";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import {
  referenceListFilterFromSearch,
  referenceListFilterToUrlStatus,
  countReferencesByStatus,
  filterReferencesByStatus,
  formatReferenceListDate,
  referenceDisplayTitle,
  referenceLineageId,
  referenceStatusBadgeVariant,
  referenceStatusLabel,
  selectedReferenceRecordByLineage,
  selectCanonicalReferenceRecords,
  type ReferenceCurationAction,
  type ReferenceStatusFilter,
} from "../lib/newsroom-references";
import { AutoAcceptedBadge } from "./auto-accepted-badge";
import { AutoAcceptedList } from "./auto-accepted-list";
import { useAutoAcceptedReferences, type AutoAcceptedReader } from "./use-auto-accepted-references";
import { autoAcceptedFromRecords, laterVoteRecord } from "../lib/auto-accepted-references";
import { isAutoAccepted, normalizeReferenceCurationStatus, referenceReasonCode, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import { newsroomListRowClassName } from "../lib/newsroom-list-selection";
import { ReferenceSourcePreview } from "./reference-source-preview";
import { ReferenceStories } from "./reference-stories";
import { useReferencePreviewAttachments } from "./use-reference-preview-attachments";
import { FEED_SURFACE_PROPS, FEED_SURFACE_STYLE, ReferenceFeed } from "./reference-feed";
import { useFeedControls } from "./use-feed-controls";
import { ReferenceCapturePanel } from "./reference-capture-panel";
import { useReferenceCapture, type CorrectCaptureAction } from "./reference-capture-client";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import { ReferenceConversation } from "./reference-conversation";
import { RelatedSection } from "./related-section";
import { useReferenceMessageCounts } from "./use-conversation";
import { captureStatusesByLineage } from "../lib/reference-capture";
import { buildFeedItems, feedLeadId, referenceArrivalTime, scoreFeedItem, type FeedItem } from "../lib/reference-feed-ranking";
import type { PredictionStatuses } from "../lib/reference-predictions";
import { useFeedWindow } from "./use-feed-window";
import { useIndexedReferenceFeed, type IndexedFeedSource } from "./use-indexed-reference-feed";
import { pathWithSearch, type ReferenceSearchReader } from "../lib/reference-search";
import { referenceDek, referencePreviewsByLineage, type ReferencePreview } from "../lib/reference-preview";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { chooseSyntheticRejects, withSyntheticRejects } from "../lib/local-preview-synthetic-rejects";
import { cn } from "@/lib/utils";
import {
  ReviewCard,
  predictionFromDecision,
  ReviewQueueBar,
  useQueueGestures,
  type CardPrediction,
  type ReviewCardDecision,
  type ReviewChoice,
} from "./reference-review-card";
import {
  CountsAsTrainingLabelNote,
  DelegatedCurationNote,
  ReferenceSuggestionProvenance,
  ReferenceSuggestionRowLine,
} from "./reference-cyclotron-suggestion";
import { ReferenceLiveAgreement } from "./reference-live-agreement";
import { SectionPicker, SectionSuggestionBlock, type SectionChoice } from "./reference-section-suggestion";
import type { SectionSuggestion, SiteSectionAgreement } from "../lib/site-section-suggestions";

/** What an editor adds to an accept: the Section the reference belongs in, which becomes a training label. */
export type ReferenceReviewOptions = {
  sectionId?: string | null;
  note?: string;
  reasonCode?: ReferenceRejectionReasonCode | null;
  decisionRelationId?: string;
  shareable?: boolean;
};
type PredictionState = "loading" | "ready" | "error";
import type { DelegatedCuration, ShadowAgreement } from "../lib/cyclotron-suggestions";
import type { AddReferenceInput, AddReferenceOutcome } from "../lib/add-reference";
import { ReferenceCyclotronStatus, type ReviewRateChoice } from "./reference-cyclotron-status";
import type { CyclotronStatus } from "cyclotron/cyclotron-status";
import { awaitsEditorReview, type RelevanceCuration, type RelevanceDecisionView } from "../lib/relevance-decisions";

type NewsroomReferencesViewProps = {
  /** Present only when the host has configured optional example priming. */
  priming?: PrimingPanelProps;
  /** The relevance cyclotron's status snapshot, shown above the list. */
  cyclotronStatus?: CyclotronStatus | null;
  /** Present for editors who may add a Reference from a pasted address, optionally accepting and rating it there. */
  onAddReference?: (input: AddReferenceInput) => Promise<AddReferenceOutcome>;
  /** Present for editors who may ask for a manual review rate. */
  onRequestReviewRate?: (choice: ReviewRateChoice) => Promise<void> | void;
  demo?: boolean;
  /** The relevance cyclotron's current decisions, keyed by reference lineage. */
  decisions?: Map<string, RelevanceDecisionView>;
  /** Reference lineage ids whose latest curation Message was made by a person. */
  humanCuratedReferenceLineageIds?: Set<string>;
  /** Delegated curations by reference lineage. */
  delegatedCurations?: Map<string, DelegatedCuration>;
  /** The live-agreement payload; the strip is hidden without it. */
  shadowAgreement?: ShadowAgreement | null;
  disabled?: boolean;
  /** The enabled newsroom Sections an accepted reference can be placed in. */
  sections?: SectionChoice[];
  /** The site cyclotron's suggested Section per reference lineage. Advisory. */
  sectionSuggestions?: Map<string, SectionSuggestion>;
  /** How often the Section suggestions matched later editor decisions. */
  sectionAgreement?: SiteSectionAgreement | null;
  reviewReasons?: Map<string, ReferenceRejectionReasonCode>;
  reviewSectionIds?: Map<string, string>;
  predictionState?: PredictionState;
  predictionError?: string | null;
  onRetryPredictions?: () => void;
  /**
   * Each shown Reference's own prediction read. Present when the page reads predictions per Reference as the feed shows them: the feed
   * then asks for the ids on screen (`onRequestPredictions`), a failure appears on that card alone, and `onRetryPrediction` reads it again.
   */
  predictionStatuses?: PredictionStatuses;
  onRequestPredictions?: (lineageIds: string[]) => void;
  onRetryPrediction?: (lineageId: string) => void;
  onRelevanceReview?: (reference: ReferenceRecord, curation: RelevanceCuration) => Promise<void> | void;
  initialReferenceLineageId?: string | null;
  onReview: (reference: ReferenceRecord, action: ReferenceCurationAction, options?: ReferenceReviewOptions) => Promise<void> | void;
  /** Saves an editor's star rating (null clears it). Stars never change the vote. */
  onSetStars?: (reference: ReferenceRecord, stars: number | null) => Promise<void> | void;
  referenceAttachments?: ReferenceAttachmentRecord[];
  references: ReferenceRecord[];
  /** Saves an editor's pasted or corrected capture text and their verdict on it. Optional: without it the capture panel only reads. */
  onCorrectCapture?: CorrectCaptureAction;
  /** True while the References are still being read: the feed shows card skeletons instead of an empty page. */
  loading?: boolean;
  /** Reads one page of the "Accepted automatically" list from the database (newest first). Without it the list is built from the loaded References. */
  loadAutoAccepted?: AutoAcceptedReader;
  /** The search box's reader when the feed is not read from the indexes (the demo): it searches the page's own References. */
  searchReader?: ReferenceSearchReader;
  /**
   * Present when the feed reads itself from the feed-state indexes, a page at a time, as the reader scrolls. The view then ignores
   * `loading`, asks `onFeedRecords` to take each page's records into the page's own list, and says which Reference ids are shown
   * (`onShownIds`) so their attachments and predictions are read for those alone.
   */
  feedSource?: IndexedFeedSource;
  onFeedRecords?: (records: ReferenceRecord[]) => void;
  onShownIds?: (lineageIds: string[]) => void;
  /** How many References have an answer, from the summary: for the "all caught up" text without reading them. */
  ratedTotal?: number | null;
  /** The List view needs every Reference; it asks for them when opened (they are not read otherwise) and shows how that read is going. */
  onNeedAllReferences?: () => void;
  allReferences?: { status: "idle" | "loading" | "ready" | "error"; error: string | null; retry: () => void };
  /** The last view this browser saved. Shown, read only, until the live read arrives. */
  savedCopy?: { references: ReferenceRecord[]; previews: Array<[string, ReferencePreview]>; decisions: Array<[string, RelevanceDecisionView]> } | null;
};

type ReferenceView = "feed" | "list";

const NO_FEED_ITEMS: FeedItem[] = [];

type ReferenceListFilter = ReferenceStatusFilter | "auto_accepted" | "needs_review";

const NEEDS_REVIEW_FILTER: { key: ReferenceListFilter; label: string } = { key: "needs_review", label: "Needs review" };

const STATUS_FILTERS: Array<{ key: ReferenceListFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "accepted", label: "Accepted" },
  // No count: the Newsroom summary counts by status, not by who accepted, so a number here could not be kept right.
  { key: "auto_accepted", label: "Accepted automatically" },
  { key: "rejected", label: "Rejected" },
  { key: "archived", label: "Archived" },
];

function buildReferenceDetailPath(lineageId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo);
}

function referenceUrl(reference: ReferenceRecord): string | null {
  const candidate = reference.sourceUri?.trim() || reference.storagePath?.trim() || null;
  if (!candidate) return null;
  if (/^https?:\/\//i.test(candidate)) return candidate;
  return null;
}

function needsReview(reference: ReferenceRecord, decision: RelevanceDecisionView | undefined): boolean {
  return awaitsEditorReview(reference.curationStatus, decision);
}

function summaryOf(reference: ReferenceRecord): string | null {
  const raw = reference.metadata;
  let metadata: Record<string, unknown> = {};
  if (raw && typeof raw === "object" && !Array.isArray(raw)) metadata = raw as Record<string, unknown>;
  else if (typeof raw === "string") {
    try { const parsed = JSON.parse(raw); if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) metadata = parsed; } catch { /* no summary */ }
  }
  for (const key of ["summary", "abstract", "description"]) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) return value.trim().length > 280 ? `${value.trim().slice(0, 277)}…` : value.trim();
  }
  return null;
}

function cardPrediction(decision: RelevanceDecisionView | undefined, predictionState: PredictionState): CardPrediction {
  if (decision) return predictionFromDecision(decision);
  if (predictionState === "loading") return { state: "loading" };
  if (predictionState === "error") return { state: "error" };
  return { state: "none" };
}

function ReferenceDetailPanel({
  captureTeaserLine,
  correctCapture,
  ratings,
  sectionChoices,
  countsAsTrainingLabel,
  delegated,
  decision,
  demo = false,
  disabled,
  onMessageCount,
  onReview,
  predictionState = "ready",
  reviewReason,
  reviewSectionId,
  previewAttachments,
  reference,
  onClose,
  sectionAgreement = null,
  sectionSuggestion,
  sections = [],
}: {
  captureTeaserLine: number;
  /** Saves a pasted or corrected capture (the `correctReferenceCapture` action). Without it the panel has no edit action. */
  correctCapture?: CorrectCaptureAction;
  /** The rating store shared with the grid cards. */
  ratings?: RatingController;
  /** Where this panel records the Section chosen for an accept, so the shared store's save can include it. */
  sectionChoices?: MutableRefObject<Map<string, string | null>>;
  countsAsTrainingLabel?: boolean;
  delegated?: DelegatedCuration;
  decision?: RelevanceDecisionView;
  demo?: boolean;
  disabled?: boolean;
  onMessageCount?: (lineageId: string, count: number) => void;
  onRelevanceReview?: (curation: RelevanceCuration) => Promise<void> | void;
  onReview: (action: ReferenceCurationAction, options?: ReferenceReviewOptions) => Promise<void> | void;
  predictionState?: PredictionState;
  reviewReason?: ReferenceRejectionReasonCode;
  reviewSectionId?: string;
  sectionAgreement?: SiteSectionAgreement | null;
  sectionSuggestion?: SectionSuggestion;
  sections?: SectionChoice[];
  previewAttachments: ReferenceAttachmentRecord[];
  reference: ReferenceRecord;
  onClose?: () => void;
}) {
  const lineageId = referenceLineageId(reference);
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const auto = isAutoAccepted(reference);
  const sourceNote = status === "pending" || auto ? "" : reference.curationStatusReason ?? "";
  const sourceReason = reviewReason ?? referenceReasonCode(reference) ?? null;
  const [chosenSectionId, setChosenSectionId] = useState<string | null>(reviewSectionId ?? null);
  const sectionEdited = useRef(false);
  useEffect(() => {
    if (!sectionEdited.current) setChosenSectionId(reviewSectionId ?? null);
  }, [reviewSectionId]);
  const url = referenceUrl(reference);
  useEffect(() => { sectionChoices?.current.set(lineageId, chosenSectionId); }, [chosenSectionId, lineageId, sectionChoices]);
  const capture = useReferenceCapture(reference, previewAttachments, captureTeaserLine, correctCapture);

  async function decide(choice: ReviewChoice, review: ReviewCardDecision) {
    const action: ReferenceCurationAction = choice;
    await onReview(action, {
      note: review.note,
      reasonCode: review.reasonCode,
      ...(choice === "accept" && chosenSectionId ? { sectionId: chosenSectionId } : {}),
      ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
    });
    sectionEdited.current = false;
  }

  return (
    <div
      className="flex h-full flex-col font-sans"
      data-news-desk-reference-detail={lineageId}
    >
      <div className="space-y-4 p-4" data-reference-curation-status={status}>
        <ReviewCard
          confirmsAutomatic={auto}
          createStory={(
            <CreateStoryButton
              demo={demo}
              disabled={disabled}
              automatic={auto}
              onAccept={() => { if (ratings) { ratings.choose(lineageId, "accept"); if (auto) ratings.choose(lineageId, "accept"); } else void onReview("accept"); }}
              preview={{ title: referenceDisplayTitle(reference), url: reference.sourceUri ?? null, summary: capture.summary ?? summaryOf(reference) ?? null, imageUrl: null, site: null }}
              referenceId={reference.id}
              size="large"
              status={status}
            />
          )}
          decided={status === "accepted" && !auto ? "accept" : status === "rejected" ? "reject" : null}
          dek={referenceDek(reference, referencePreviewsByLineage(previewAttachments).get(lineageId))}
          disabledReason={disabled ? "Editor access is required to change this reference." : null}
          initialNote={sourceNote}
          initialReason={sourceReason}
          itemId={lineageId}
          meta={(
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={referenceStatusBadgeVariant(status)}>{referenceStatusLabel(status)}</Badge>
              {auto ? <AutoAcceptedBadge actor={reference.curationStatusUpdatedBy} reason={reference.curationStatusReason} /> : null}
              {reference.corpusId ? <Badge variant="secondary">{reference.corpusId}</Badge> : null}
            </div>
          )}
          ratings={ratings}
          onArchive={status === "archived" ? undefined : async () => { await onReview("archive"); }}
          onDecide={decide}
          prediction={cardPrediction(decision, predictionState)}
          sourcePreview={<ReferenceSourcePreview attachments={previewAttachments} sourceUri={reference.sourceUri} />}
          summary={capture.summary ?? summaryOf(reference)}
          title={referenceDisplayTitle(reference)}
          titleHref={url}
        >
          {decision ? <div data-reference-relevance-decision={lineageId}><ReferenceSuggestionProvenance decision={decision} /></div> : null}
          {sectionSuggestion || ((status === "pending" || status === "accepted") && sections.length) ? (
            <details className="rounded-[var(--feed-radius-lg,10px)] bg-[var(--feed-control)] p-3 text-sm">
              <summary className="cursor-pointer font-semibold">Section placement (optional)</summary>
              <div className="mt-3 space-y-3">
                {sectionSuggestion ? <SectionSuggestionBlock agreement={sectionAgreement} referenceLineageId={lineageId} sections={sections} suggestion={sectionSuggestion} /> : null}
                {(status === "pending" || status === "accepted") && sections.length ? <SectionPicker
                  agreement={sectionAgreement}
                  chosenSectionId={chosenSectionId}
                  disabled={Boolean(disabled)}
                  onChoose={(sectionId) => { setChosenSectionId(sectionId); sectionEdited.current = true; }}
                  referenceLineageId={lineageId}
                  sections={sections}
                  suggestedSectionId={sectionSuggestion?.sectionId ?? null}
                /> : null}
              </div>
            </details>
          ) : null}
          {delegated ? <DelegatedCurationNote delegated={delegated} referenceLineageId={lineageId} /> : countsAsTrainingLabel ? <CountsAsTrainingLabelNote referenceLineageId={lineageId} /> : null}
          <RelatedSection disabledReason={disabled ? "Editor access is required to change links." : null} hrefForReference={(related) => buildReferenceDetailPath(related, demo)} lineageId={lineageId} referenceId={reference.id} />
          <ReferenceConversation disabledReason={disabled ? "Editor access is required to write messages." : null} lineageId={lineageId} onCount={onMessageCount} referenceId={reference.id} title={referenceDisplayTitle(reference)} />
        </ReviewCard>

        <Separator />

        <ReferenceStories demo={demo} referenceLineageId={lineageId} />

        <ReferenceCapturePanel capture={capture} showSummary={false} />

        <dl className="grid gap-3 text-sm">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Why</dt>
            <dd className="mt-1 text-foreground">
              {reference.curationStatusReason?.trim()
                || "No explanation recorded."}
            </dd>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Imported</dt>
              <dd className="mt-1 text-foreground">{formatReferenceListDate(reference)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Media</dt>
              <dd className="mt-1 text-foreground">{reference.mediaType ?? "unknown"}</dd>
            </div>
          </div>
        </dl>

        <section aria-label="Attachments">
          <h3 className="mb-2 text-sm font-medium text-foreground">Attachments</h3>
          {previewAttachments.length ? (
            <ul className="space-y-1 text-sm text-muted-foreground">
              {previewAttachments.map((attachment) => (
                <li key={attachment.id}>
                  {attachment.sourceUri ? (
                    <a className="text-primary underline-offset-4 hover:underline" href={attachment.sourceUri} rel="noreferrer" target="_blank">
                      {attachment.filename ?? attachment.role ?? attachment.id}
                    </a>
                  ) : (
                    <span>{attachment.filename ?? attachment.role ?? attachment.id}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              {reference.storagePath
                ? reference.storagePath
                : "No attachment metadata on this record."}
            </p>
          )}
        </section>

        {onClose ? (
          <Button className="w-full" onClick={onClose} type="button" variant="secondary">
            Close
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function NewsroomReferencesView({
  priming,
  cyclotronStatus,
  onAddReference,
  decisions: liveDecisions,
  humanCuratedReferenceLineageIds,
  delegatedCurations,
  shadowAgreement = null,
  onRequestReviewRate,
  demo = false,
  disabled = false,
  onRelevanceReview,
  predictionState = "ready",
  predictionError,
  reviewReasons,
  reviewSectionIds,
  onRetryPredictions,
  predictionStatuses,
  onRequestPredictions,
  onRetryPrediction,
  sections = [],
  sectionSuggestions,
  sectionAgreement = null,
  initialReferenceLineageId = null,
  onReview,
  onSetStars,
  referenceAttachments = [],
  references: liveReferences,
  loading: loadingProp = false,
  feedSource,
  onFeedRecords,
  onShownIds,
  ratedTotal = null,
  onNeedAllReferences,
  allReferences,
  onCorrectCapture,
  savedCopy = null,
  loadAutoAccepted,
  searchReader,
}: NewsroomReferencesViewProps) {
  const pathname = usePathname();
  const sessionImport = useReferenceImport(disabled);
  const [importedCount, setImportedCount] = useState(0);
  const pathnameLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeLineageId = pathname ? pathnameLineageId ?? "" : initialReferenceLineageId ?? "";

  const serverMode = Boolean(feedSource);
  // The search box (docs/reference-search.md). A search replaces the feed's pages with the site's ranked results; the saved Sort and Show are untouched
  // (a search opens on All, and clearing it brings the saved choices back).
  const [caughtUp, setCaughtUp] = useState(false);
  const stopCaughtUp = useCallback(() => setCaughtUp(false), []);
  const searchRead = feedSource?.search ?? searchReader;
  const controls = useFeedControls({ searchRead, onChange: stopCaughtUp });
  const { search, minStars } = controls;
  const { searching, query: searchQuery } = search;
  const searchFeed = search.feed;
  const { sort: feedSort, show: feedShow } = controls.saved;
  const { captured, medium } = controls;
  const indexedFeed = useIndexedReferenceFeed({ enabled: serverMode && !searching, source: feedSource, sort: feedSort, show: feedShow, minStars, captured, medium });
  const indexed = searching ? searchFeed : indexedFeed;
  // The cards come from the pages of a reader (the indexes, or a search) rather than from the page's own list.
  const resultsMode = serverMode || searching;
  const loading = resultsMode ? indexed.status === "loading" || indexed.status === "idle" : loadingProp;
  useEffect(() => {
    if (serverMode && indexed.status === "ready") onFeedRecords?.(indexed.records);
    // `onFeedRecords` is the host's setter; the records are what changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indexed.records, indexed.status, serverMode]);
  // Until the live read arrives, a saved copy of the last view fills the page. It is display only.
  const showingSavedCopy = !serverMode && loading && !liveReferences.length && Boolean(savedCopy?.references.length);
  const references = showingSavedCopy ? savedCopy!.references : liveReferences;
  const baseDecisions = useMemo(
    () => (showingSavedCopy && !liveDecisions?.size ? new Map(savedCopy!.decisions) : liveDecisions),
    [liveDecisions, savedCopy, showingSavedCopy],
  );
  // Preview only: ?feedSynthRejects=N makes the N weakest Accept predictions into made-up Rejects (the page says so).
  const synthRejectCount = useMemo(() => {
    if (typeof window === "undefined" || !isLocalPreviewEnabled()) return 0;
    const requested = Number(new URLSearchParams(window.location.search).get("feedSynthRejects"));
    return Number.isInteger(requested) && requested > 0 ? requested : 0;
  }, []);
  const syntheticChoice = useRef<string[] | null>(null);
  if (synthRejectCount && syntheticChoice.current === null && baseDecisions?.size && references.length) {
    syntheticChoice.current = chooseSyntheticRejects(
      baseDecisions,
      new Set(references.filter((reference) => normalizeReferenceCurationStatus(reference.curationStatus) === "pending").map(referenceLineageId)),
      synthRejectCount,
    );
  }
  const synthetic = useMemo(
    () => (synthRejectCount && syntheticChoice.current ? withSyntheticRejects(baseDecisions, syntheticChoice.current) : null),
    [baseDecisions, synthRejectCount],
  );
  const decisions = synthetic?.decisions ?? baseDecisions;
  const previews = useMemo(() => {
    const live = referencePreviewsByLineage(referenceAttachments);
    return showingSavedCopy && !live.size ? new Map(savedCopy!.previews) : live;
  }, [referenceAttachments, savedCopy, showingSavedCopy]);
  const [view, setView] = useState<ReferenceView>("feed");
  const [addOpen, setAddOpen] = useState(false);
  const { counts: messageCounts, setCount: setMessageCount } = useReferenceMessageCounts(!loading);
  const [visitRated, setVisitRated] = useState<ReadonlySet<string>>(() => new Set());
  const [mountedAt] = useState(() => Date.now());
  const markVisitRated = useCallback((lineageId: string) => {
    setVisitRated((current) => (current.has(lineageId) ? current : new Set(current).add(lineageId)));
  }, []);
  // Preview only: ?feedState=loading holds the page in its loading state, to review the card skeletons.
  const previewSkeleton = useMemo(
    () => typeof window !== "undefined" && isLocalPreviewEnabled() && new URLSearchParams(window.location.search).get("feedState") === "loading",
    [],
  );

  const canonicalReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  const allItems = useMemo(() => buildFeedItems(canonicalReferences, decisions), [canonicalReferences, decisions]);
  const managedPredictions = Boolean(predictionStatuses);
  const feedWindowState = useFeedWindow({
    allItems: resultsMode ? NO_FEED_ITEMS : allItems,
    blocked: resultsMode || loading || showingSavedCopy || previewSkeleton,
    predictionStatuses,
    predictionsPending: predictionState === "loading",
    onRequestPredictions,
    sort: feedSort,
    show: feedShow,
    minStars,
    captured,
    visitRated,
  });
  // Server mode: the feed is the index's own order, page by page. A Reference an editor rates stays where it is for the visit.
  const [revealed, setRevealed] = useState<string[]>([]);
  useEffect(() => { setRevealed([]); }, [feedSort, feedShow, minStars, captured, medium, searchQuery, search.show, search.sort]);
  const indexedLineages = useMemo(() => new Set(indexed.records.map(referenceLineageId)), [indexed.records]);
  const arrivals = useMemo(() => {
    // A new Reference has no stars, so it cannot belong in the Quality sort or under a minimum of stars, and it has no capture yet, so it is not Captured Yes.
    if (!serverMode || searching || indexed.status !== "ready" || feedSort === "quality" || minStars > 0 || captured === "yes" || medium !== "any") return [] as ReferenceRecord[];
    const shown = new Set(revealed);
    return canonicalReferences.filter((reference) => {
      const lineage = referenceLineageId(reference);
      return normalizeReferenceCurationStatus(reference.curationStatus) === "pending" && !indexedLineages.has(lineage) && !shown.has(lineage)
        && (referenceArrivalTime(reference) ?? 0) > indexed.readAt;
    }).sort((left, right) => (referenceArrivalTime(right) ?? 0) - (referenceArrivalTime(left) ?? 0));
  }, [canonicalReferences, captured, feedSort, indexed.readAt, indexed.status, indexedLineages, medium, minStars, revealed, searching, serverMode]);
  const serverItems = useMemo(() => {
    if (!resultsMode) return NO_FEED_ITEMS;
    const current = new Map(canonicalReferences.map((reference) => [referenceLineageId(reference), reference] as const));
    const seen = new Set<string>();
    const items: FeedItem[] = [];
    for (const lineage of [...revealed, ...indexed.records.map(referenceLineageId)]) {
      if (seen.has(lineage)) continue;
      seen.add(lineage);
      const record = current.get(lineage) ?? indexed.records.find((candidate) => referenceLineageId(candidate) === lineage);
      if (!record || normalizeReferenceCurationStatus(record.curationStatus) === "archived") continue;
      const item = scoreFeedItem(record, decisions?.get(lineage));
      const original = record.predictedAcceptProbability;
      items.push(typeof original === "number" ? { ...item, probability: original } : item);
    }
    return items;
  }, [canonicalReferences, decisions, indexed.records, resultsMode, revealed]);
  const shownIdsKey = serverItems.map((item) => item.lineageId).join("\u0000");
  useEffect(() => {
    if (!resultsMode || !serverItems.length) return;
    const ids = serverItems.map((item) => item.lineageId);
    onShownIds?.(ids);
    onRequestPredictions?.(ids);
    // `shownIdsKey` stands for the ids.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownIdsKey, resultsMode]);
  const feedItems = resultsMode ? serverItems : feedWindowState.items;
  // The large lead card is a pick among cards still to answer: Rated has none.
  const feedLead = searching || feedShow === "rated" || feedShow === "accepted" ? undefined : resultsMode ? feedLeadId(serverItems) : feedWindowState.leadId;   // a search has no lead card
  const hasMoreItems = resultsMode ? indexed.hasMore : feedWindowState.hasMore;
  const loadingMoreItems = resultsMode ? indexed.loadingMore : feedWindowState.loadingMore;
  const loadMoreItems = resultsMode ? () => { void indexed.loadMore(); } : feedWindowState.loadMore;
  const showNewItems = serverMode ? () => setRevealed((current) => [...arrivals.map(referenceLineageId), ...current]) : feedWindowState.showNewItems;
  const newItemCount = searching ? 0 : serverMode ? arrivals.length : feedWindowState.newCount;
  const ratedCount = useMemo(
    () => (serverMode ? ratedTotal ?? serverItems.filter((item) => item.rated).length : allItems.filter((item) => item.rated).length),
    [allItems, ratedTotal, serverItems, serverMode],
  );
  const [scrollTarget, setScrollTarget] = useState<{ id: string; nonce: number } | null>(null);
  const feedOrderIds = useMemo(
    () => feedItems.map((item) => item.lineageId),
    [feedItems],
  );
  const statusCounts = useMemo(() => countReferencesByStatus(canonicalReferences), [canonicalReferences]);

  const [statusFilter, setStatusFilter] = useState<ReferenceListFilter>(routeLineageId ? "all" : "pending");
  const needsEverything = serverMode && view === "list" && statusFilter !== "auto_accepted";
  useEffect(() => { if (needsEverything) onNeedAllReferences?.(); }, [needsEverything, onNeedAllReferences]);
  // `?status=` opens the list on that filter (the page writes it when a filter is chosen); "Accepted automatically" is `?status=auto-accepted`.
  useEffect(() => {
    const requested = typeof window === "undefined" ? null : referenceListFilterFromSearch(window.location.search);
    if (!requested) return;
    setView("list");
    setStatusFilter(requested);
  }, []);
  const needsReviewCount = useMemo(
    () => canonicalReferences.filter((reference) => needsReview(reference, decisions?.get(referenceLineageId(reference)))).length,
    [canonicalReferences, decisions],
  );
  const filters = decisions?.size ? [NEEDS_REVIEW_FILTER, ...STATUS_FILTERS] : STATUS_FILTERS;
  const [selectedLineageId, setSelectedLineageId] = useState(routeLineageId);

  // "Accepted automatically": a page at a time from the database, never a scan of every Reference. A card follows an editor's later vote
  // in this session (a Reject takes it out).
  const autoOpen = statusFilter === "auto_accepted";
  const liveReferencesRef = useRef(liveReferences);
  liveReferencesRef.current = liveReferences;
  const readAutoAccepted = useMemo<AutoAcceptedReader>(
    () => loadAutoAccepted ?? (async () => ({ items: autoAcceptedFromRecords(liveReferencesRef.current), nextToken: null, hasMore: false })),
    [loadAutoAccepted],
  );
  const autoRead = useAutoAcceptedReferences({ enabled: autoOpen && !showingSavedCopy, read: readAutoAccepted });
  // Lineages an editor has voted on from here: they leave the list as soon as the vote is saved, whatever the page's own copy says.
  const [votedHere, setVotedHere] = useState<ReadonlySet<string>>(() => new Set());
  const autoRecords = useMemo(() => {
    const held = new Map(canonicalReferences.map((reference) => [referenceLineageId(reference), reference] as const));
    return autoRead.items
      .map((read) => laterVoteRecord(read, held.get(referenceLineageId(read))))
      .filter((reference) => !votedHere.has(referenceLineageId(reference)) && isAutoAccepted(reference));   // an editor's vote (a Reject, a later Accept, an archive) ends the automatic acceptance, so the card leaves
  }, [autoRead.items, canonicalReferences, votedHere]);
  const autoLineageIds = useMemo(() => autoRecords.map(referenceLineageId), [autoRecords]);
  const autoIdsKey = autoLineageIds.join("\u0000");
  useEffect(() => {
    if (autoOpen && autoLineageIds.length) onRequestPredictions?.(autoLineageIds);
    // `autoIdsKey` stands for `autoLineageIds`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpen, autoIdsKey, onRequestPredictions]);
  const filteredReferences = useMemo(
    () => statusFilter === "auto_accepted"
      ? autoRecords
      : statusFilter === "needs_review"
      ? canonicalReferences.filter((reference) => needsReview(reference, decisions?.get(referenceLineageId(reference))))
      : filterReferencesByStatus(canonicalReferences, statusFilter),
    [autoRecords, canonicalReferences, decisions, statusFilter],
  );

  const selectedReference = useMemo(
    () => selectedReferenceRecordByLineage(filteredReferences, selectedLineageId)
      ?? selectedReferenceRecordByLineage(canonicalReferences, selectedLineageId),
    [canonicalReferences, filteredReferences, selectedLineageId],
  );

  const previewAttachments = useReferencePreviewAttachments(selectedReference, referenceAttachments);

  // Whatever way a reference is selected (card, Next, Previous, arrow keys, a deep link, the item after a vote), the detail opens at its top
  // with the headline in view. The scroller that actually scrolls depends on the layout: the detail pane's own scroll area from `lg`, and on a
  // phone the page's scroller (`.organizer-main`, or the window), because the pane is as tall as its content. So every scrolling ancestor of
  // the detail, and the pane's scroll area itself, goes back to the top. Keyed on the id, so re-rendering the same reference never moves it.
  const openLineageId = selectedReference ? referenceLineageId(selectedReference) : "";
  useLayoutEffect(() => {
    if (!openLineageId || typeof document === "undefined") return;
    const detail = document.querySelector<HTMLElement>("[data-reference-detail-scroll]");
    if (!detail) return;
    for (let node: HTMLElement | null = detail; node; node = node.parentElement) if (node.scrollTop !== 0) node.scrollTop = 0;
    const page = document.scrollingElement;
    if (page && page.scrollTop !== 0) page.scrollTop = 0;
  }, [openLineageId]);

  // The queue is the current list filter. A reference the editor has just decided leaves the filtered
  // list, but keeps its place in the queue until they move on, so "3 of 29" does not jump under them.
  const queueRef = useRef<string[]>([]);
  const queue = useMemo(() => {
    const ids = view === "feed" ? [...feedOrderIds] : filteredReferences.map(referenceLineageId);
    const open = selectedReference ? referenceLineageId(selectedReference) : "";
    if (open && !ids.includes(open)) {
      const before = queueRef.current.indexOf(open);
      if (before >= 0) ids.splice(Math.min(before, ids.length), 0, open);
    }
    return ids;
  }, [feedOrderIds, filteredReferences, selectedReference, view]);
  useEffect(() => { queueRef.current = queue; }, [queue]);
  const selectedIndex = selectedReference ? queue.indexOf(referenceLineageId(selectedReference)) : -1;
  const queuePosition = selectedIndex >= 0 ? selectedIndex + 1 : null;
  const previousLineageId = caughtUp ? queue[queue.length - 1] ?? null : selectedIndex > 0 ? queue[selectedIndex - 1] : null;
  const nextLineageId = selectedIndex >= 0 && selectedIndex < queue.length - 1 ? queue[selectedIndex + 1] : null;
  const nextReference = nextLineageId ? selectedReferenceRecordByLineage(canonicalReferences, nextLineageId) : null;

  const syncStatusUrl = useCallback((nextStatus: ReferenceListFilter) => {
    if (demo) return;
    const filters = {
      status: referenceListFilterToUrlStatus(nextStatus),
      processing: "",
      order: "published" as const,
    };
    if (selectedLineageId && typeof window !== "undefined") {
      window.history.replaceState(null, "", `${buildReferenceDetailPath(selectedLineageId)}${buildReferencesIndexQuery(filters)}`);
    } else {
      syncBrowserNewsroomIndexUrl("references", filters, { replace: true });
    }
  }, [demo, selectedLineageId]);

  useEffect(() => {
    setSelectedLineageId(routeLineageId);
  }, [routeLineageId]);

  const selectReference = (lineageId: string) => {
    setCaughtUp(false);
    setSelectedLineageId(lineageId);
    if (typeof window !== "undefined") {
      const nextPath = pathWithSearch(buildReferenceDetailPath(lineageId, demo), searchQuery);
      if (`${window.location.pathname}${window.location.search}` !== nextPath) {
        window.history.pushState(null, "", nextPath);
      }
    }
  };

  const goNext = () => {
    if (nextLineageId) { selectReference(nextLineageId); setScrollTarget({ id: nextLineageId, nonce: Date.now() }); }
    else if (queue.length && !caughtUp) {
      // Past the last item: say so, rather than showing an empty page.
      setCaughtUp(true);
      setSelectedLineageId("");
      if (typeof window !== "undefined") window.history.pushState(null, "", getNewsroomNavHref("/newsroom/references", demo));
    } else if (!queue.length) setCaughtUp(true);
  };
  const goPrevious = () => {
    if (previousLineageId) { selectReference(previousLineageId); setScrollTarget({ id: previousLineageId, nonce: Date.now() }); }
  };
  const gestures = useQueueGestures({ onNext: goNext, onPrevious: goPrevious });

  const closeDetail = () => {
    setCaughtUp(false);
    setSelectedLineageId("");
    if (typeof window !== "undefined") {
      const indexPath = pathWithSearch(getNewsroomNavHref("/newsroom/references", demo), searchQuery);
      window.history.replaceState(null, "", indexPath);
    }
  };

  const runReview = (action: ReferenceCurationAction, options?: ReferenceReviewOptions) => {
    if (!selectedReference) return;
    if (action === "accept" || action === "reject") markVisitRated(referenceLineageId(selectedReference));
    return onReview(selectedReference, action, options);
  };

  const rateFromFeed = async (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) => {
    const decision = decisions?.get(referenceLineageId(reference));
    await onReview(reference, choice, {
      reasonCode: choice === "reject" ? reasonCode : null,
      ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
    });
  };
  // One rating store for the whole view: the grid cards and the detail pane read and write the same state, so a vote or a reason
  // entered in either shows in both. Reason then vote, or vote then reason, both end up on one decision.
  const sectionChoices = useRef<Map<string, string | null>>(new Map());
  const referenceById = (lineageId: string) => selectedReferenceRecordByLineage(canonicalReferences, lineageId)
    ?? autoRead.items.find((item) => referenceLineageId(item) === lineageId) ?? null;
  const ratings = useRatingStore({
    save: async (lineageId, choice, detail) => {
      const reference = referenceById(lineageId);
      if (!reference) throw new Error("This reference is no longer in the list.");
      markVisitRated(lineageId);
      const decision = decisions?.get(lineageId);
      const sectionId = choice === "accept" ? sectionChoices.current.get(lineageId) : null;
      await onReview(reference, choice, {
        note: detail.note || undefined,
        reasonCode: choice === "reject" ? detail.reasonCode : null,
        ...(sectionId ? { sectionId } : {}),
        ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
      });
      setVotedHere((current) => new Set(current).add(lineageId));
    },
    saved: (lineageId) => {
      const reference = referenceById(lineageId);
      const status = normalizeReferenceCurationStatus(reference?.curationStatus);
      // An automatic acceptance is not an editor's answer: Accept on it is a confirmation, Reject an overturn.
      return status === "accepted" && !(reference && isAutoAccepted(reference)) ? "accept" : status === "rejected" ? "reject" : null;
    },
    confirms: (lineageId) => { const reference = referenceById(lineageId); return Boolean(reference && isAutoAccepted(reference)); },
    ...(onSetStars ? {
      saveStars: async (lineageId: string, next: number | null) => {
        const reference = referenceById(lineageId);
        if (!reference) throw new Error("This reference is no longer in the list.");
        await onSetStars(reference, next);
      },
      savedStars: (lineageId: string) => { const reference = referenceById(lineageId); return reference ? reference.starRating ?? null : undefined; },
    } : {}),
    seed: (lineageId) => {
      const reference = referenceById(lineageId);
      const status = normalizeReferenceCurationStatus(reference?.curationStatus);
      return {
        // An automatic acceptance's reason is the router's, not the editor's: it must not become the reason of an editor's Reject.
        note: reference && status !== "pending" && !isAutoAccepted(reference) ? reference.curationStatusReason ?? "" : "",
        reasonCode: reviewReasons?.get(lineageId) ?? (reference ? referenceReasonCode(reference) : null) ?? null,
      };
    },
  });
  const { statuses: captureStatuses, teaserLine } = useMemo(
    () => captureStatusesByLineage(referenceAttachments, canonicalReferences.map(referenceLineageId)),
    [canonicalReferences, referenceAttachments],
  );
  // Preview only: a fixture can carry captured text inline; say so, since production stores none for monitored References.
  const previewCapturedText = useMemo(
    () => isLocalPreviewEnabled() && referenceAttachments.some((attachment) => attachment.role === "extracted_text" && String(attachment.storagePath ?? "").startsWith("preview://")),
    [referenceAttachments],
  );
  const showCaptures = !showingSavedCopy && !loading && !previewSkeleton;
  const feedDisabledReason = disabled
    ? "Editor access is required to change this reference."
    : showingSavedCopy ? "Confirming your sign-in. You can answer in a moment." : null;

  const caughtUpPanel = (
    <div className="space-y-2 p-6 text-center" data-review-caught-up>
      <h3 className="text-lg font-semibold">All caught up</h3>
      <p className="text-sm text-muted-foreground">There is nothing more in this list. Use Previous to go back.</p>
    </div>
  );
  const queueBar = queue.length || caughtUp ? (
    <ReviewQueueBar anchored caughtUp={caughtUp} onNext={goNext} onPrevious={goPrevious} position={queuePosition} total={queue.length} />
  ) : null;

  const emptyLabel = canonicalReferences.length
    ? "No references match this filter."
    : "No private references imported yet.";

  // Two layouts, chosen by the viewport, never by the selection. From the `lg` breakpoint (1024px, an iPad in landscape) the detail is a
  // pane to the right of the feed, and the grid's column count follows the width it has beside that pane. Below it (phones and a tablet in
  // portrait) there is one column: the feed, or, once a reference is open, its detail in the feed's place at the full width with a Back
  // control. There is no overlay: an overlay would hide the cards Previous / Next scrolls to.
  const detailOpen = Boolean(selectedReference) || caughtUp;

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 lg:max-h-[100dvh] lg:flex-row"
      data-reference-layout={detailOpen ? "detail" : "feed"}
      data-news-desk-section="references"
      data-detail-open={selectedReference || routeLineageId ? "true" : "false"}
    >
      <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col gap-4 lg:flex lg:overflow-hidden", detailOpen && LIST_HIDDEN_WHEN_DETAIL_OPEN)} data-reference-feed-column>
        <div className="flex shrink-0 items-center justify-between gap-3" {...FEED_SURFACE_PROPS}>
          <div className="min-w-0 space-y-0.5">
            <h2 className="text-2xl font-bold tracking-tight">References</h2>
            <p className="hidden text-sm text-muted-foreground sm:block">
              {view === "feed" ? "A feed ranked by what you are most likely to accept." : "Review source intake before it becomes accepted evidence."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              aria-controls="reference-add-panel"
              aria-expanded={addOpen}
              aria-label="Add a reference and prediction activity"
              className={cn("inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring", addOpen ? "bg-[var(--feed-control)] text-foreground" : "bg-[var(--feed-card)] text-muted-foreground hover:text-foreground")}
              data-reference-add-toggle
              onClick={() => setAddOpen((open) => !open)}
              title="Add a reference and prediction activity"
              type="button"
            >
              <PlusIcon aria-hidden="true" className="size-4" />
              <span className="hidden sm:inline">Add</span>
            </button>
            <div aria-label="Reference view" className="inline-flex rounded-full bg-[var(--feed-card)] p-1" role="group">
              {([["feed", "Feed", LayoutGridIcon], ["list", "List", ListIcon]] as const).map(([key, label, Icon]) => (
                <button
                  aria-label={label}
                  aria-pressed={view === key}
                  className={cn(
                    "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-full px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    view === key ? "bg-[var(--feed-control)] text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                  data-reference-view={key}
                  key={key}
                  onClick={() => { setView(key); setCaughtUp(false); }}
                  title={label}
                  type="button"
                >
                  <Icon aria-hidden="true" className="size-4" />
                  <span className="hidden sm:inline">{label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
        {synthetic?.changed ? (
          <p className="rounded-2xl bg-[var(--feed-card)] p-3 text-sm" data-preview-synthetic role="status" {...FEED_SURFACE_PROPS}>
            Preview only: {synthetic.changed} of these predictions are made up to show the Reject end of the feed. Real data has none yet.
          </p>
        ) : null}
        {previewCapturedText ? (
          <p className="rounded-2xl bg-[var(--feed-card)] p-3 text-sm" data-preview-captured-text role="status" {...FEED_SURFACE_PROPS}>
            Preview only: the captured text here was fetched live for this preview. In the newsroom record none of these References has stored text yet.
          </p>
        ) : null}
        {predictionState === "loading" && view === "list" ? <p role="status">Loading predictions…</p> : null}
        {predictionState === "error" ? (
          <div role="alert" className="space-y-2 rounded-2xl bg-[var(--feed-card)] p-4" {...FEED_SURFACE_PROPS}>
            <p>Predictions unavailable. {predictionError}</p>
            <p className="text-sm">You can still review references. Existing suggestions may be out of date.</p>
            {onRetryPredictions ? <Button onClick={onRetryPredictions} size="sm" type="button" variant="outline">Retry predictions</Button> : null}
          </div>
        ) : null}
        <div className="shrink-0 overflow-y-auto rounded-[20px] bg-[var(--feed-card)] p-4 text-sm" data-feed-flat="" data-feed-surface="" hidden={!addOpen} id="reference-add-panel" style={{ ...FEED_SURFACE_STYLE, maxHeight: "45dvh", overflowY: "auto" }}>
          <div className="space-y-4">
        <ReferenceLiveAgreement agreement={shadowAgreement} />
        <ReferenceAddEntry
          importOptions={disabled ? null : priming ?? sessionImport?.panel}
          key={sessionImport?.sessionKey ?? "no-session"}
          onImported={() => setImportedCount((count) => count + 1)}
          url={onAddReference && !disabled ? { onAdd: onAddReference } : null}
        />
        <ReferenceCurationControls disabled={disabled} refreshSignal={importedCount} />
        {cyclotronStatus ? (
          <div className="shrink-0">
            <ReferenceCyclotronStatus onRequestRate={disabled ? undefined : onRequestReviewRate} status={cyclotronStatus} />
          </div>
        ) : null}
          </div>
        </div>

        {view === "feed" ? (
          <div className="relative flex min-h-0 flex-1 flex-col" {...FEED_SURFACE_PROPS}>
          {newItemCount > 0 ? (
            // Floats over the top of the grid, outside the scrolling content: announcing new items never moves a card.
            <div className="pointer-events-none absolute inset-x-0 top-2 z-20 flex justify-center">
              <button
                className="pointer-events-auto inline-flex min-h-9 items-center rounded-full bg-[var(--feed-control)] px-4 text-sm font-medium text-foreground shadow-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
                data-feed-new-items
                onClick={showNewItems}
                type="button"
              >
                {newItemCount} new {newItemCount === 1 ? "item" : "items"}: show
              </button>
            </div>
          ) : null}
          {/* 6px of room on every side, so a selected card's 4px ring (drawn outside the card) is never cut off by the scroller. */}
          <ScrollArea className="min-h-0 flex-1 [overflow-anchor:none]" data-reference-feed-scroll>
            <div className="px-1.5 pb-6 pt-1.5 pr-2.5">
              <ReferenceFeed
                disabledReason={feedDisabledReason}
                loading={previewSkeleton || (resultsMode ? loading : loading && !references.length)}
                messageCounts={messageCounts}
                now={mountedAt}
                onOpen={selectReference}
                onRate={rateFromFeed}
                demo={demo}
                onShowChange={(next) => { controls.setShow(next); setCaughtUp(false); }}
                onSortChange={(next) => { controls.setSort(next); setCaughtUp(false); }}
                onMinStarsChange={(next) => { controls.setMinStars(next); setCaughtUp(false); }}
                minStars={minStars}
                onCapturedChange={(next) => { controls.setCaptured(next); setCaughtUp(false); }}
                captured={captured}
                onMediumChange={serverMode && feedSource?.readMediumStream ? (next) => { controls.setMedium(next); setCaughtUp(false); } : undefined}
                medium={medium}
                onVisitRated={markVisitRated}
                items={feedItems}
                ratedCount={ratedCount}
                predictionLoading={!managedPredictions && predictionState === "loading"}
                predictionStatuses={predictionStatuses}
                onRetryPrediction={onRetryPrediction}
                hasMore={hasMoreItems}
                loadingMore={loadingMoreItems}
                onLoadMore={loadMoreItems}
                error={resultsMode ? indexed.error ?? indexed.moreError : null}
                onRetry={resultsMode ? indexed.retry : undefined}
                previews={previews}
                captures={showCaptures ? captureStatuses : undefined}
                leadId={feedLead}
                scrollTarget={scrollTarget}
                ratings={ratings}
                selectedLineageId={selectedLineageId}
                stale={!resultsMode && (showingSavedCopy || (loading && references.length > 0))}
                show={controls.show}
                sort={controls.sort}
                visitRated={visitRated}
                search={searchRead ? {
                  query: searchQuery,
                  onSubmit: search.submit,
                  onClear: search.clear,
                  matches: searchFeed.matches,
                  notice: searchFeed.notice,
                  onRetry: searchFeed.retry,
                } : undefined}
              />
            </div>
          </ScrollArea>
          </div>
        ) : (
          <>
        <Tabs
          className="shrink-0"
          defaultValue="pending"
          onValueChange={(value) => {
            const next = value as ReferenceListFilter;
            setStatusFilter(next);
            setCaughtUp(false);
            syncStatusUrl(next);
          }}
          value={statusFilter}
        >
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 bg-muted/40 p-1">
            {filters.map((filter) => {
              const everything = !serverMode || allReferences?.status === "ready";
              const count = filter.key === "all"
                ? canonicalReferences.length
                : filter.key === "needs_review"
                  ? needsReviewCount
                  : statusCounts[filter.key] ?? 0;
              return (
                <TabsTrigger className="text-xs sm:text-sm" key={filter.key} value={filter.key}>
                  {filter.label}
                  {filter.key === "auto_accepted" || !everything ? null : <Badge className="ml-1.5 min-w-5 px-1.5" variant="secondary">{count}</Badge>}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>

        {serverMode && statusFilter !== "auto_accepted" && allReferences && allReferences.status !== "ready" ? (
          allReferences.status === "error" ? (
            <div className="flex shrink-0 items-center gap-3 rounded-2xl bg-[var(--feed-card)] p-3 text-sm" data-list-all-error role="alert" {...FEED_SURFACE_PROPS}>
              <span className="min-w-0 flex-1">The full list could not be read. {allReferences.error}</span>
              <Button onClick={allReferences.retry} size="sm" type="button" variant="outline"><RefreshCwIcon aria-hidden="true" />Retry</Button>
            </div>
          ) : (
            <p className="flex shrink-0 items-center gap-2 text-sm text-muted-foreground" data-list-all-loading role="status">
              <Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Reading every reference. The counts appear when it is done.
            </p>
          )
        ) : null}
        <ScrollArea className="min-h-0 flex-1">
          {statusFilter === "auto_accepted" ? (
            <div className="px-1.5 pb-6 pt-1.5 pr-2.5" {...FEED_SURFACE_PROPS}>
              <AutoAcceptedList
                captures={showCaptures ? captureStatuses : undefined}
                decisions={decisions}
                disabledReason={feedDisabledReason}
                error={autoRead.error}
                hasMore={autoRead.hasMore}
                items={autoRecords}
                loading={autoRead.loading}
                loadingMore={autoRead.loadingMore}
                messageCounts={messageCounts}
                now={mountedAt}
                onLoadMore={autoRead.loadMore}
                onOpen={selectReference}
                onRate={rateFromFeed}
                onRetry={autoRead.retry}
                onRetryPrediction={onRetryPrediction}
                predictionStatuses={predictionStatuses}
                previews={previews}
                ratings={ratings}
                selectedLineageId={selectedLineageId}
              />
            </div>
          ) : (
          <div className="flex flex-col gap-2 pb-4" data-newsroom-card-grid>
            {filteredReferences.length ? filteredReferences.map((reference) => {
              const lineageId = referenceLineageId(reference);
              const status = normalizeReferenceCurationStatus(reference.curationStatus);
              const active = selectedLineageId === lineageId;
              const decision = decisions?.get(lineageId);
              return (
                <button
                  aria-current={active ? "true" : undefined}
                  className={newsroomListRowClassName(active)}
                  data-newsroom-list-row
                  data-selected={active || undefined}
                  data-newsroom-card
                  data-newsroom-card-id={lineageId}
                  key={lineageId}
                  onClick={() => selectReference(lineageId)}
                  type="button"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="truncate text-sm font-medium text-foreground">{referenceDisplayTitle(reference)}</p>
                      <p className="truncate text-xs text-muted-foreground">{reference.corpusId}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StarsMark stars={reference.starRating ?? null} />
                      <Badge variant={referenceStatusBadgeVariant(status)}>{referenceStatusLabel(status)}</Badge>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{formatReferenceListDate(reference)}</p>
                  {isAutoAccepted(reference) ? <AutoAcceptedBadge actor={reference.curationStatusUpdatedBy} className="mt-1" reason={reference.curationStatusReason} /> : null}
                  {decision ? (
                    <div className="flex flex-wrap items-center gap-2" data-reference-relevance-row={lineageId}>
                      <ReferenceSuggestionRowLine decision={decision} referenceLineageId={lineageId} />
                      {needsReview(reference, decision) ? (
                        <Badge variant="outline"><span aria-hidden="true">●</span> Needs review</Badge>
                      ) : null}
                    </div>
                  ) : null}
                </button>
              );
            }) : (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">No references</CardTitle>
                  <CardDescription>{emptyLabel}</CardDescription>
                </CardHeader>
              </Card>
            )}
          </div>
          )}
        </ScrollArea>
          </>
        )}
      </div>

      <div
        className={cn(
          "hidden min-h-0 w-full shrink-0 flex-col rounded-[20px] bg-[var(--feed-card)] lg:overflow-hidden lg:pb-16",
          DETAIL_PANE_WIDTH,
          // The detail appears once a reference is selected (or when the queue is done); until then the feed has the whole width.
          detailOpen && "flex",
        )}
        data-newsroom-list-detail-shell
        data-news-desk-section="references"
        data-detail-open={selectedReference ? "true" : "false"}
        data-feed-flat=""
        {...FEED_SURFACE_PROPS}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 px-4 pt-3 pb-1">
          <Button className="-ml-2 lg:hidden" data-reference-back onClick={closeDetail} size="sm" type="button" variant="ghost">
            <ArrowLeftIcon aria-hidden="true" />
            References
          </Button>
          <span className="text-sm font-medium text-foreground">Detail</span>
        </div>
        <div className="flex min-h-0 flex-1 flex-col" data-review-gestures onPointerDown={gestures.onPointerDown} onPointerUp={gestures.onPointerUp} style={gestures.style}>
        <ScrollArea className="min-h-0 flex-1" data-reference-detail-scroll>
          {selectedReference ? (
            <ReferenceDetailPanel
              key={referenceLineageId(selectedReference)}
              captureTeaserLine={teaserLine}
              correctCapture={onCorrectCapture}
              ratings={ratings}
              sectionChoices={sectionChoices}
              predictionState={predictionState}
              reviewReason={reviewReasons?.get(referenceLineageId(selectedReference))}
              reviewSectionId={reviewSectionIds?.get(referenceLineageId(selectedReference))}
              countsAsTrainingLabel={humanCuratedReferenceLineageIds?.has(referenceLineageId(selectedReference))}
              delegated={delegatedCurations?.get(referenceLineageId(selectedReference))}
              decision={decisions?.get(referenceLineageId(selectedReference))}
              demo={demo}
              disabled={disabled}
              onMessageCount={setMessageCount}
              onRelevanceReview={onRelevanceReview ? (curation) => onRelevanceReview(selectedReference, curation) : undefined}
              onReview={runReview}
              sectionAgreement={sectionAgreement}
              sectionSuggestion={sectionSuggestions?.get(referenceLineageId(selectedReference))}
              sections={sections}
              previewAttachments={previewAttachments}
              reference={selectedReference}
            />
          ) : caughtUp ? caughtUpPanel : null}
        </ScrollArea>
        </div>
        {queueBar}
      </div>

    </div>
  );
}
