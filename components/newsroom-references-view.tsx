"use client";

import type { PrimingPanelProps } from "cyclotron/components/priming-panel";
import { ReferenceAddEntry } from "./reference-add-entry";
import { ReferenceCurationControls, useReferenceImport } from "./reference-curation-controls";

import { ArrowLeftIcon, ExternalLinkIcon, LayoutGridIcon, ListIcon, PlusIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
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
import { isAutoAccepted, normalizeReferenceCurationStatus, referenceReasonCode, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import { newsroomListRowClassName } from "../lib/newsroom-list-selection";
import { ReferenceSourcePreview } from "./reference-source-preview";
import { ReferenceStories } from "./reference-stories";
import { useReferencePreviewAttachments } from "./use-reference-preview-attachments";
import { FEED_SURFACE_PROPS, FEED_SURFACE_STYLE, ReferenceFeed } from "./reference-feed";
import { useFeedPreferences } from "./use-feed-preferences";
import { ReferenceCapturePanel } from "./reference-capture-panel";
import { useReferenceCapture, type CorrectCaptureAction } from "./reference-capture-client";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import { ReferenceConversation } from "./reference-conversation";
import { useReferenceMessageCounts } from "./use-conversation";
import { captureStatusesByLineage } from "../lib/reference-capture";
import { buildFeedItems, scoreFeedItem, visibleFeedItems, type FeedItem } from "../lib/reference-feed-ranking";
import { FEED_PAGE_SIZE, createStaticFeedSource, isRated, type ReferenceFeedSource, type StaticFeedData } from "../lib/reference-feed-pages";
import { ratedFields } from "../lib/reference-feed-controller";
import { useReferenceFeedPages } from "./use-reference-feed-pages";
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
import type { PrimingFormInput } from "./reference-cyclotron-priming";
import { ReferenceCyclotronStatus, type ReviewRateChoice } from "./reference-cyclotron-status";
import type { PrimingRequestView } from "../lib/relevance-status";
import type { CyclotronStatus } from "cyclotron/cyclotron-status";
import { awaitsEditorReview, type RelevanceCuration, type RelevanceDecisionView } from "../lib/relevance-decisions";

type NewsroomReferencesViewProps = {
  /** Present only when the host has configured optional example priming. */
  priming?: PrimingPanelProps;
  /** The relevance cyclotron's status snapshot, shown above the list. */
  cyclotronStatus?: CyclotronStatus | null;
  /** Present for editors who may prime the running relevance cyclotron with a pasted URL. */
  cyclotronPriming?: {
    labels: readonly string[];
    requests: PrimingRequestView[];
    onRequest: (input: PrimingFormInput) => Promise<void> | void;
  };
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
  onRelevanceReview?: (reference: ReferenceRecord, curation: RelevanceCuration) => Promise<void> | void;
  initialReferenceLineageId?: string | null;
  onReview: (reference: ReferenceRecord, action: ReferenceCurationAction, options?: ReferenceReviewOptions) => Promise<void> | void;
  referenceAttachments?: ReferenceAttachmentRecord[];
  references: ReferenceRecord[];
  /** Saves an editor's pasted or corrected capture text and their verdict on it. Optional: without it the capture panel only reads. */
  onCorrectCapture?: CorrectCaptureAction;
  /** True while the References are still being read: the feed shows card skeletons instead of an empty page. */
  loading?: boolean;
  /** The last view this browser saved. Shown, read only, until the live read arrives. */
  savedCopy?: { references: ReferenceRecord[]; previews: Array<[string, ReferencePreview]>; decisions: Array<[string, RelevanceDecisionView]> } | null;
  /**
   * Where the feed reads its pages from (the two indexes on Reference). Without it the feed pages the `references` it was given, in
   * memory, the same way: that is the demo, and the harnesses that mount the view with a list.
   */
  source?: ReferenceFeedSource;
  /** Called once the first page and its decisions have loaded, so the host can keep a display copy for the next visit. */
  onFirstPage?: (snapshot: { references: ReferenceRecord[]; previews: ReadonlyMap<string, ReferencePreview>; decisions: ReadonlyMap<string, RelevanceDecisionView> }) => void;
};

type ReferenceView = "feed" | "list";

type ReferenceListFilter = ReferenceStatusFilter | "needs_review";

const NEEDS_REVIEW_FILTER: { key: ReferenceListFilter; label: string } = { key: "needs_review", label: "Needs review" };

const STATUS_FILTERS: Array<{ key: ReferenceListFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "accepted", label: "Accepted" },
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
          decided={status === "accepted" ? "accept" : status === "rejected" ? "reject" : null}
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
  cyclotronPriming,
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
  sections = [],
  sectionSuggestions,
  sectionAgreement = null,
  initialReferenceLineageId = null,
  onReview,
  referenceAttachments = [],
  references: liveReferences,
  loading = false,
  onCorrectCapture,
  savedCopy = null,
  source,
  onFirstPage,
}: NewsroomReferencesViewProps) {
  const pathname = usePathname();
  const sessionImport = useReferenceImport(disabled);
  const [importedCount, setImportedCount] = useState(0);
  const pathnameLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeLineageId = pathname ? pathnameLineageId ?? "" : initialReferenceLineageId ?? "";

  // Preview only: ?feedState=loading holds the page in its loading state, to review the card skeletons.
  const previewSkeleton = useMemo(
    () => typeof window !== "undefined" && isLocalPreviewEnabled() && new URLSearchParams(window.location.search).get("feedState") === "loading",
    [],
  );
  const [view, setView] = useState<ReferenceView>("feed");
  const [addOpen, setAddOpen] = useState(false);
  const { sort: feedSort, setSort: setFeedSort, show: feedShow, setShow: setFeedShow } = useFeedPreferences();

  // The feed is read one page at a time (lib/reference-feed-pages.ts). In the app `source` reads the two indexes. Without one the feed pages
  // the References it was given, in memory: the same keys, streams and page size, so there is one code path. The in-memory feed starts
  // once its list and predictions have arrived, because the order is fixed by the predictions at that moment.
  const staticData = useRef<StaticFeedData>({ references: liveReferences, decisions: liveDecisions, attachments: referenceAttachments });
  staticData.current = { references: liveReferences, decisions: liveDecisions, attachments: referenceAttachments };
  const staticStarted = useRef(false);
  const staticPredicted = useRef(false);
  if (!source && liveReferences.length > 0 && !loading) staticStarted.current = true;
  if (staticStarted.current && predictionState !== "loading") staticPredicted.current = true;
  // The list shows as soon as it has its References; the visit is taken once more when the first predictions arrive, so the order is theirs.
  const staticSource = useMemo(() => createStaticFeedSource(() => staticData.current), [staticStarted.current, staticPredicted.current]); // eslint-disable-line react-hooks/exhaustive-deps
  const feedSource = source ?? staticSource;
  // The List view has a tab for each answer, so it reads the rated stream as well as the unrated one.
  const pagedShow = view === "list" ? "all" : feedShow;
  const { controller, state: feed } = useReferenceFeedPages({
    source: feedSource,
    sort: feedSort,
    show: pagedShow,
    enabled: !previewSkeleton && (Boolean(source) || staticStarted.current),
  });
  useEffect(() => {
    if (!source) {
      controller.mergeRecords(liveReferences);
      void controller.refreshCompanions();
      // A list held in memory has no focus event to wait for: anything new in it is counted now, and waits behind the pill.
      void controller.checkNew();
    }
  }, [controller, liveDecisions, liveReferences, referenceAttachments, source]);

  const firstReadPending = previewSkeleton || (source ? feed.status === "idle" || feed.status === "loading" : loading || !staticStarted.current);
  // Until the live read arrives, a saved copy of the last view fills the page. It is display only.
  const showingSavedCopy = firstReadPending && !feed.records.length && Boolean(savedCopy?.references.length);
  const loadedReferences = useMemo(() => [...feed.records, ...feed.extra], [feed.extra, feed.records]);
  const references = showingSavedCopy ? savedCopy!.references : loadedReferences;
  const feedDecisions = useMemo(
    () => (source ? new Map([...feed.decisions, ...(liveDecisions ?? [])]) : liveDecisions),
    [feed.decisions, liveDecisions, source],
  );
  const baseDecisions = useMemo(
    () => (showingSavedCopy && !feedDecisions?.size ? new Map(savedCopy!.decisions) : feedDecisions),
    [feedDecisions, savedCopy, showingSavedCopy],
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
  const feedAttachments = source ? feed.attachments : referenceAttachments;
  const previews = useMemo(() => {
    const live = referencePreviewsByLineage(feedAttachments);
    return showingSavedCopy && !live.size ? new Map(savedCopy!.previews) : live;
  }, [feedAttachments, savedCopy, showingSavedCopy]);
  const { counts: messageCounts, setCount: setMessageCount } = useReferenceMessageCounts(!firstReadPending);
  const [mountedAt] = useState(() => Date.now());
  const visitRated = feed.visitRated;
  const markVisitRated = useCallback((lineageId: string) => controller.markVisitRated(lineageId), [controller]);

  const canonicalReferences = references;
  // Keep a display copy of the first page for the next visit, once, after its predictions have arrived.
  const savedFirstPage = useRef(false);
  useEffect(() => {
    if (!onFirstPage || !source || savedFirstPage.current || feed.status !== "ready" || feed.companionsPending || !feed.records.length) return;
    savedFirstPage.current = true;
    onFirstPage({ references: feed.records.slice(0, FEED_PAGE_SIZE), previews, decisions: decisions ?? new Map() });
  }, [decisions, feed.companionsPending, feed.records, feed.status, onFirstPage, previews, source]);
  // The cards, in the order the pages arrived. Rating a card changes the card, never its place; the lead was fixed with the first page.
  const feedItems = useMemo<FeedItem[]>(() => {
    if (showingSavedCopy) return visibleFeedItems(buildFeedItems(canonicalReferences, decisions), feedSort, feedShow).slice(0, FEED_PAGE_SIZE);
    return feed.records
      .filter((record) => normalizeReferenceCurationStatus(record.curationStatus) !== "archived")
      .map((record) => scoreFeedItem(record, decisions?.get(referenceLineageId(record))));
  }, [canonicalReferences, decisions, feed.records, feedShow, feedSort, showingSavedCopy]);
  const feedLead = showingSavedCopy ? feedItems.find((item) => !item.rated)?.lineageId : feed.leadId;
  const ratedCount = feed.hasRated ? 1 : feed.records.filter(isRated).length;
  const showNewItems = () => controller.showNew();
  const [scrollTarget, setScrollTarget] = useState<{ id: string; nonce: number } | null>(null);
  const feedOrderIds = useMemo(
    () => feedItems.map((item) => item.lineageId),
    [feedItems],
  );
  const statusCounts = useMemo(() => countReferencesByStatus(canonicalReferences), [canonicalReferences]);
  // Prediction state: the host's, for the open Reference, and the pages' own for the cards.
  const feedPredictionState: PredictionState = feed.companionsPending ? "loading" : feed.companionsError ? "error" : "ready";
  const effectivePredictionState: PredictionState = !source ? predictionState : routeLineageId && predictionState !== "ready" ? predictionState : feedPredictionState;
  const effectivePredictionError = source && feedPredictionState === "error" && !(routeLineageId && predictionState === "error") ? feed.companionsError : predictionError;
  const retryPredictions = source && feedPredictionState === "error" ? () => { void controller.refreshCompanions(); } : onRetryPredictions;

  const [statusFilter, setStatusFilter] = useState<ReferenceListFilter>(routeLineageId ? "all" : "pending");
  const needsReviewCount = useMemo(
    () => canonicalReferences.filter((reference) => needsReview(reference, decisions?.get(referenceLineageId(reference)))).length,
    [canonicalReferences, decisions],
  );
  const filters = decisions?.size ? [NEEDS_REVIEW_FILTER, ...STATUS_FILTERS] : STATUS_FILTERS;
  const [selectedLineageId, setSelectedLineageId] = useState(routeLineageId);

  const filteredReferences = useMemo(
    () => statusFilter === "needs_review"
      ? canonicalReferences.filter((reference) => needsReview(reference, decisions?.get(referenceLineageId(reference))))
      : filterReferencesByStatus(canonicalReferences, statusFilter),
    [canonicalReferences, decisions, statusFilter],
  );

  const selectedReference = useMemo(
    () => selectedReferenceRecordByLineage(filteredReferences, selectedLineageId)
      ?? selectedReferenceRecordByLineage(canonicalReferences, selectedLineageId)
      // A list held in memory has the Reference in hand before its first page is read (and in a server render).
      ?? (source ? null : selectedReferenceRecordByLineage(liveReferences, selectedLineageId)),
    [canonicalReferences, filteredReferences, liveReferences, selectedLineageId, source],
  );
  // A link to a Reference that is not in the loaded pages: read that one Reference, not the feed.
  const requestedDeepLinks = useRef(new Set<string>());
  useEffect(() => {
    if (!selectedLineageId || selectedReference || showingSavedCopy || requestedDeepLinks.current.has(selectedLineageId)) return;
    requestedDeepLinks.current.add(selectedLineageId);
    void controller.ensureReference(selectedLineageId).catch(() => requestedDeepLinks.current.delete(selectedLineageId));
  }, [controller, selectedLineageId, selectedReference, showingSavedCopy]);

  const previewAttachments = useReferencePreviewAttachments(selectedReference, feedAttachments);

  // The queue is what is loaded: the feed's cards, or the list's filtered rows. Rating a card leaves it where it is, so "3 of 24+" does not jump.
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
  const [caughtUp, setCaughtUp] = useState(false);
  const selectedIndex = selectedReference ? queue.indexOf(referenceLineageId(selectedReference)) : -1;
  const queuePosition = selectedIndex >= 0 ? selectedIndex + 1 : null;
  const previousLineageId = caughtUp ? queue[queue.length - 1] ?? null : selectedIndex > 0 ? queue[selectedIndex - 1] : null;
  const nextLineageId = selectedIndex >= 0 ? (selectedIndex < queue.length - 1 ? queue[selectedIndex + 1] : null) : selectedReference ? queue[0] ?? null : null;
  const nextReference = nextLineageId ? selectedReferenceRecordByLineage(canonicalReferences, nextLineageId) : null;

  const syncStatusUrl = useCallback((nextStatus: ReferenceListFilter) => {
    if (demo) return;
    const filters = {
      status: nextStatus === "all" ? "" : nextStatus,
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
      const nextPath = buildReferenceDetailPath(lineageId, demo);
      if (`${window.location.pathname}${window.location.search}` !== nextPath) {
        window.history.pushState(null, "", nextPath);
      }
    }
  };

  const goNext = async () => {
    if (nextLineageId) { selectReference(nextLineageId); setScrollTarget({ id: nextLineageId, nonce: Date.now() }); return; }
    if (feed.hasMore && !caughtUp && selectedReference) {
      // At the end of what is loaded: read the next page, then go on to its first card.
      const open = referenceLineageId(selectedReference);
      await controller.loadMore();
      const records = controller.getState().records.filter((record) => normalizeReferenceCurationStatus(record.curationStatus) !== "archived");
      const following = records[records.findIndex((record) => referenceLineageId(record) === open) + 1];
      if (following) { selectReference(referenceLineageId(following)); setScrollTarget({ id: referenceLineageId(following), nonce: Date.now() }); return; }
    }
    if (queue.length && !caughtUp) {
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
      const indexPath = getNewsroomNavHref("/newsroom/references", demo);
      window.history.replaceState(null, "", indexPath);
    }
  };

  // A saved answer changes the card in place: it keeps its place in the feed, and shows the answer, for the rest of the visit.
  const reviewAndPatch = async (reference: ReferenceRecord, action: ReferenceCurationAction, options?: ReferenceReviewOptions) => {
    await onReview(reference, action, options);
    controller.patch(referenceLineageId(reference), ratedFields(action, options?.note, new Date().toISOString()));
  };

  const runReview = (action: ReferenceCurationAction, options?: ReferenceReviewOptions) => {
    if (!selectedReference) return;
    if (action === "accept" || action === "reject") markVisitRated(referenceLineageId(selectedReference));
    return reviewAndPatch(selectedReference, action, options);
  };

  const rateFromFeed = async (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) => {
    const decision = decisions?.get(referenceLineageId(reference));
    await reviewAndPatch(reference, choice, {
      reasonCode: choice === "reject" ? reasonCode : null,
      ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
    });
  };
  // One rating store for the whole view: the grid cards and the detail pane read and write the same state, so a vote or a reason
  // entered in either shows in both. Reason then vote, or vote then reason, both end up on one decision.
  const sectionChoices = useRef<Map<string, string | null>>(new Map());
  const referenceById = (lineageId: string) => selectedReferenceRecordByLineage(canonicalReferences, lineageId)
    ?? (source ? null : selectedReferenceRecordByLineage(liveReferences, lineageId));
  const ratings = useRatingStore({
    save: async (lineageId, choice, detail) => {
      const reference = referenceById(lineageId);
      if (!reference) throw new Error("This reference is no longer in the list.");
      markVisitRated(lineageId);
      const decision = decisions?.get(lineageId);
      const sectionId = choice === "accept" ? sectionChoices.current.get(lineageId) : null;
      await reviewAndPatch(reference, choice, {
        note: detail.note || undefined,
        reasonCode: choice === "reject" ? detail.reasonCode : null,
        ...(sectionId ? { sectionId } : {}),
        ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
      });
    },
    saved: (lineageId) => {
      const status = normalizeReferenceCurationStatus(referenceById(lineageId)?.curationStatus);
      return status === "accepted" ? "accept" : status === "rejected" ? "reject" : null;
    },
    seed: (lineageId) => {
      const reference = referenceById(lineageId);
      const status = normalizeReferenceCurationStatus(reference?.curationStatus);
      return {
        note: reference && status !== "pending" ? reference.curationStatusReason ?? "" : "",
        reasonCode: reviewReasons?.get(lineageId) ?? (reference ? referenceReasonCode(reference) : null) ?? null,
      };
    },
  });
  const { statuses: captureStatuses, teaserLine } = useMemo(
    () => captureStatusesByLineage(feedAttachments, canonicalReferences.map(referenceLineageId)),
    [canonicalReferences, feedAttachments],
  );
  // Preview only: a fixture can carry captured text inline; say so, since production stores none for monitored References.
  const previewCapturedText = useMemo(
    () => isLocalPreviewEnabled() && feedAttachments.some((attachment) => attachment.role === "extracted_text" && String(attachment.storagePath ?? "").startsWith("preview://")),
    [feedAttachments],
  );
  const showCaptures = !showingSavedCopy && !firstReadPending && !previewSkeleton;
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
    <ReviewQueueBar anchored caughtUp={caughtUp} more={feed.hasMore} onNext={goNext} onPrevious={goPrevious} position={queuePosition} total={queue.length} />
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
      <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col gap-4 lg:flex lg:overflow-hidden", detailOpen && "max-lg:hidden")} data-reference-feed-column>
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
        {effectivePredictionState === "loading" && view === "list" ? <p role="status">Loading predictions…</p> : null}
        {effectivePredictionState === "error" ? (
          <div role="alert" className="space-y-2 rounded-2xl bg-[var(--feed-card)] p-4" {...FEED_SURFACE_PROPS}>
            <p>Predictions unavailable. {effectivePredictionError}</p>
            <p className="text-sm">You can still review references. Existing suggestions may be out of date.</p>
            {retryPredictions ? <Button onClick={retryPredictions} size="sm" type="button" variant="outline">Retry predictions</Button> : null}
          </div>
        ) : null}
        <div className="shrink-0 overflow-y-auto rounded-[20px] bg-[var(--feed-card)] p-4 text-sm" data-feed-flat="" data-feed-surface="" hidden={!addOpen} id="reference-add-panel" style={{ ...FEED_SURFACE_STYLE, maxHeight: "45dvh", overflowY: "auto" }}>
          <div className="space-y-4">
        <ReferenceLiveAgreement agreement={shadowAgreement} />
        <ReferenceAddEntry
          importOptions={disabled ? null : priming ?? sessionImport?.panel}
          key={sessionImport?.sessionKey ?? "no-session"}
          onImported={() => setImportedCount((count) => count + 1)}
          url={cyclotronPriming && !disabled
            ? { labels: cyclotronPriming.labels, onRequest: cyclotronPriming.onRequest, requests: cyclotronPriming.requests }
            : null}
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
          {feed.newCount > 0 ? (
            // Floats over the top of the grid, outside the scrolling content: announcing new items never moves a card.
            <div className="pointer-events-none absolute inset-x-0 top-2 z-20 flex justify-center">
              <button
                className="pointer-events-auto inline-flex min-h-9 items-center rounded-full bg-[var(--feed-control)] px-4 text-sm font-medium text-foreground shadow-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
                data-feed-new-items
                onClick={showNewItems}
                type="button"
              >
                {feed.newCount} new {feed.newCount === 1 ? "item" : "items"}: show
              </button>
            </div>
          ) : null}
          {/* 6px of room on every side, so a selected card's 4px ring (drawn outside the card) is never cut off by the scroller. */}
          <ScrollArea className="min-h-0 flex-1 [overflow-anchor:none]" data-reference-feed-scroll>
            <div className="px-1.5 pb-6 pt-1.5 pr-2.5">
              <ReferenceFeed
                disabledReason={feedDisabledReason}
                loading={previewSkeleton || (firstReadPending && !showingSavedCopy)}
                messageCounts={messageCounts}
                now={mountedAt}
                onOpen={selectReference}
                onRate={rateFromFeed}
                onShowChange={(next) => { setFeedShow(next); setCaughtUp(false); }}
                onSortChange={(next) => { setFeedSort(next); setCaughtUp(false); }}
                onVisitRated={markVisitRated}
                items={feedItems}
                ratedCount={ratedCount}
                predictionLoading={effectivePredictionState === "loading"}
                previews={previews}
                captures={showCaptures ? captureStatuses : undefined}
                leadId={feedLead}
                scrollTarget={scrollTarget}
                ratings={ratings}
                selectedLineageId={selectedLineageId}
                stale={showingSavedCopy || (!source && loading && references.length > 0)}
                show={feedShow}
                sort={feedSort}
                visitRated={visitRated}
                hasMore={!showingSavedCopy && feed.hasMore}
                loadingMore={feed.loadingMore}
                loadError={feed.status === "ready" ? feed.error : null}
                onLoadMore={() => { void (feed.error ? controller.retry() : controller.loadMore()); }}
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
              const count = filter.key === "all"
                ? canonicalReferences.length
                : filter.key === "needs_review"
                  ? needsReviewCount
                  : statusCounts[filter.key] ?? 0;
              return (
                <TabsTrigger className="text-xs sm:text-sm" key={filter.key} value={filter.key}>
                  {filter.label}
                  <Badge className="ml-1.5 min-w-5 px-1.5" variant="secondary">{count}{feed.hasMore ? "+" : ""}</Badge>
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>

        <ScrollArea className="min-h-0 flex-1">
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
                    <Badge variant={referenceStatusBadgeVariant(status)}>{referenceStatusLabel(status)}</Badge>
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
            {feed.hasMore || feed.loadingMore ? (
              <div className="flex justify-center py-2">
                <Button data-feed-load-more disabled={feed.loadingMore} onClick={() => { void controller.loadMore(); }} size="sm" type="button" variant="outline">
                  {feed.loadingMore ? "Loading more" : "Load more"}
                </Button>
              </div>
            ) : null}
          </div>
        </ScrollArea>
          </>
        )}
      </div>

      <div
        className={cn(
          "hidden min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-[20px] bg-[var(--feed-card)] lg:w-[min(100%,24rem)] lg:pb-16 xl:w-[min(100%,28rem)]",
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
        <ScrollArea className="min-h-0 flex-1">
          {selectedReference ? (
            <ReferenceDetailPanel
              key={referenceLineageId(selectedReference)}
              captureTeaserLine={teaserLine}
              correctCapture={onCorrectCapture}
              ratings={ratings}
              sectionChoices={sectionChoices}
              predictionState={effectivePredictionState}
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
