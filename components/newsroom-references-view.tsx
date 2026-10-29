"use client";

import type { PrimingPanelProps } from "cyclotron/components/priming-panel";
import { ReferenceAddEntry } from "./reference-add-entry";
import { ReferenceCurationControls, useReferenceImport } from "./reference-curation-controls";

import { ExternalLinkIcon, LayoutGridIcon, ListIcon, PlusIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
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
import { normalizeReferenceCurationStatus, referenceReasonCode, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import { newsroomListRowClassName } from "../lib/newsroom-list-selection";
import { ReferenceSourcePreview } from "./reference-source-preview";
import { ReferenceStories } from "./reference-stories";
import { useReferencePreviewAttachments } from "./use-reference-preview-attachments";
import { useMediaQuery } from "./use-media-query";
import { FEED_SURFACE_PROPS, FEED_SURFACE_STYLE, ReferenceFeed } from "./reference-feed";
import { ReferenceCapturePanel } from "./reference-capture-panel";
import { useReferenceCapture, type CorrectCaptureAction } from "./reference-capture-client";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import { captureStatusesByLineage } from "../lib/reference-capture";
import { applyFeedOrderSnapshot, partitionReferenceFeed, takeFeedOrderSnapshot, type FeedOrderSnapshot, type ReferenceFeedTabKey } from "../lib/reference-feed-ranking";
import { referenceDek, referencePreviewsByLineage, type ReferencePreview } from "../lib/reference-preview";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { chooseSyntheticRejects, withSyntheticRejects } from "../lib/local-preview-synthetic-rejects";
import { cn } from "@/lib/utils";
import { getKanbusTheme, SITE_BRAND } from "../lib/site-brand";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";
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
  const sourceNote = status === "pending" ? "" : reference.curationStatusReason ?? "";
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
}: NewsroomReferencesViewProps) {
  const pathname = usePathname();
  // The portaled mobile sheet sits outside the newsroom root, so it carries the theme attributes itself (same as useNewsroomThemeAttributes).
  const themeMode = useResolvedPapyrusTheme();
  const themeAttributes = { "data-kanbus-theme": getKanbusTheme(SITE_BRAND), "data-color-mode": themeMode };
  const sessionImport = useReferenceImport(disabled);
  const [importedCount, setImportedCount] = useState(0);
  const isMobileDetail = useMediaQuery("(max-width: 767px)");
  const pathnameLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeLineageId = pathname ? pathnameLineageId ?? "" : initialReferenceLineageId ?? "";

  // Until the live read arrives, a saved copy of the last view fills the page. It is display only.
  const showingSavedCopy = loading && !liveReferences.length && Boolean(savedCopy?.references.length);
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
  const [feedTab, setFeedTab] = useState<ReferenceFeedTabKey>("feed");
  const [visitRated, setVisitRated] = useState<ReadonlySet<string>>(() => new Set());
  const [mountedAt] = useState(() => Date.now());
  const markVisitRated = useCallback((lineageId: string) => {
    setVisitRated((current) => (current.has(lineageId) ? current : new Set(current).add(lineageId)));
  }, []);
  // Preview only: ?feedTau=<days> stands in for the learned freshness period, to review the Earlier section on a young corpus.
  const tauDaysOverride = useMemo(() => {
    if (typeof window === "undefined" || !isLocalPreviewEnabled()) return null;
    const requested = Number(new URLSearchParams(window.location.search).get("feedTau"));
    return Number.isFinite(requested) && requested > 0 ? requested : null;
  }, []);

  // Preview only: ?feedState=loading holds the page in its loading state, to review the card skeletons.
  const previewSkeleton = useMemo(
    () => typeof window !== "undefined" && isLocalPreviewEnabled() && new URLSearchParams(window.location.search).get("feedState") === "loading",
    [],
  );

  const canonicalReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  const livePartition = useMemo(
    () => partitionReferenceFeed(canonicalReferences, decisions, { now: mountedAt, visitRated, tauDaysOverride }),
    [canonicalReferences, decisions, mountedAt, tauDaysOverride, visitRated],
  );
  // The feed's order is taken ONCE per visit, when the feed has loaded (References and predictions), and then left alone. Selecting an
  // item, rating one, a background refresh or a cache revalidation changes cards' content, never their places. Items that arrive later
  // wait behind a "N new items: show" pill. (The Rated tab is a live list: it is the one place a new answer is meant to appear.)
  const orderSnapshot = useRef<FeedOrderSnapshot | null>(null);
  const [, bumpOrder] = useState(0);
  const orderReady = !loading && !showingSavedCopy && !previewSkeleton && predictionState !== "loading" && canonicalReferences.length > 0;
  if (!orderSnapshot.current && orderReady) orderSnapshot.current = takeFeedOrderSnapshot(livePartition);
  const stable = orderSnapshot.current ? applyFeedOrderSnapshot(orderSnapshot.current, livePartition) : null;
  const partition = stable?.partition ?? livePartition;
  const showNewItems = () => { orderSnapshot.current = takeFeedOrderSnapshot(livePartition); bumpOrder((count) => count + 1); };
  const [scrollTarget, setScrollTarget] = useState<{ id: string; nonce: number } | null>(null);
  const feedOrderIds = useMemo(
    () => (feedTab === "feed" ? [...partition.feed, ...partition.earlier] : feedTab === "rated" ? partition.rated : partition.earlier).map((item) => item.lineageId),
    [feedTab, partition],
  );
  const statusCounts = useMemo(() => countReferencesByStatus(canonicalReferences), [canonicalReferences]);

  const [statusFilter, setStatusFilter] = useState<ReferenceListFilter>(routeLineageId ? "all" : "pending");
  const needsReviewCount = useMemo(
    () => canonicalReferences.filter((reference) => needsReview(reference, decisions?.get(referenceLineageId(reference)))).length,
    [canonicalReferences, decisions],
  );
  const filters = decisions?.size ? [NEEDS_REVIEW_FILTER, ...STATUS_FILTERS] : STATUS_FILTERS;
  const [selectedLineageId, setSelectedLineageId] = useState(routeLineageId);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(Boolean(routeLineageId) && isMobileDetail);

  const filteredReferences = useMemo(
    () => statusFilter === "needs_review"
      ? canonicalReferences.filter((reference) => needsReview(reference, decisions?.get(referenceLineageId(reference))))
      : filterReferencesByStatus(canonicalReferences, statusFilter),
    [canonicalReferences, decisions, statusFilter],
  );

  const selectedReference = useMemo(
    () => selectedReferenceRecordByLineage(filteredReferences, selectedLineageId)
      ?? selectedReferenceRecordByLineage(canonicalReferences, selectedLineageId),
    [canonicalReferences, filteredReferences, selectedLineageId],
  );

  const previewAttachments = useReferencePreviewAttachments(selectedReference, referenceAttachments);

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
  const [caughtUp, setCaughtUp] = useState(false);
  const selectedIndex = selectedReference ? queue.indexOf(referenceLineageId(selectedReference)) : -1;
  const queuePosition = selectedIndex >= 0 ? selectedIndex + 1 : null;
  const previousLineageId = caughtUp ? queue[queue.length - 1] ?? null : selectedIndex > 0 ? queue[selectedIndex - 1] : null;
  const nextLineageId = selectedIndex >= 0 && selectedIndex < queue.length - 1 ? queue[selectedIndex + 1] : null;
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
    if (isMobileDetail) setMobileDetailOpen(Boolean(routeLineageId));
  }, [isMobileDetail, routeLineageId]);

  useEffect(() => {
    if (isMobileDetail) return;
    setMobileDetailOpen(false);
  }, [isMobileDetail]);

  const selectReference = (lineageId: string) => {
    setCaughtUp(false);
    setSelectedLineageId(lineageId);
    if (isMobileDetail) setMobileDetailOpen(true);
    if (typeof window !== "undefined") {
      const nextPath = buildReferenceDetailPath(lineageId, demo);
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
    setMobileDetailOpen(false);
    setSelectedLineageId("");
    if (typeof window !== "undefined") {
      const indexPath = getNewsroomNavHref("/newsroom/references", demo);
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
  const referenceById = (lineageId: string) => selectedReferenceRecordByLineage(canonicalReferences, lineageId);
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

  // The grid must not move when a detail opens, so in the feed the detail pane's place is reserved all the time (from the md breakpoint
  // up): opening it changes nothing, and the grid's column count follows the width it has beside that place, never the selection. Below
  // md the detail is a sheet over the grid. There is no overlay mode: an overlay would hide the cards Previous / Next scrolls to.

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 md:max-h-[100dvh] md:flex-row"
      data-news-desk-section="references"
      data-detail-open={selectedReference || routeLineageId ? "true" : "false"}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 md:overflow-hidden">
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
          {stable && stable.newCount > 0 && feedTab === "feed" ? (
            // Floats over the top of the grid, outside the scrolling content: announcing new items never moves a card.
            <div className="pointer-events-none absolute inset-x-0 top-2 z-20 flex justify-center">
              <button
                className="pointer-events-auto inline-flex min-h-9 items-center rounded-full bg-[var(--feed-control)] px-4 text-sm font-medium text-foreground shadow-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
                data-feed-new-items
                onClick={showNewItems}
                type="button"
              >
                {stable.newCount} new {stable.newCount === 1 ? "item" : "items"}: show
              </button>
            </div>
          ) : null}
          {/* 6px of room on every side, so a selected card's 4px ring (drawn outside the card) is never cut off by the scroller. */}
          <ScrollArea className="min-h-0 flex-1 [overflow-anchor:none]" data-reference-feed-scroll>
            <div className="px-1.5 pb-6 pt-1.5 pr-2.5">
              <ReferenceFeed
                disabledReason={feedDisabledReason}
                loading={previewSkeleton || (loading && !references.length)}
                now={mountedAt}
                onOpen={selectReference}
                onRate={rateFromFeed}
                onTabChange={(next) => { setFeedTab(next); setCaughtUp(false); }}
                onVisitRated={markVisitRated}
                partition={partition}
                predictionLoading={predictionState === "loading"}
                previews={previews}
                captures={showCaptures ? captureStatuses : undefined}
                groups={stable?.groups}
                leadId={stable?.leadId}
                scrollTarget={scrollTarget}
                ratings={ratings}
                selectedLineageId={selectedLineageId}
                stale={showingSavedCopy || (loading && references.length > 0)}
                tab={feedTab}
                visitRated={visitRated}
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
                  <Badge className="ml-1.5 min-w-5 px-1.5" variant="secondary">{count}</Badge>
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
        </ScrollArea>
          </>
        )}
      </div>

      <div
        className={cn(
          "hidden min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-[20px] bg-[var(--feed-card)] md:w-[min(100%,24rem)] md:pb-16 lg:w-[min(100%,28rem)]",
          // The pane appears once a reference is selected (or when the queue is done); until then the feed has the whole width.
          (selectedReference || caughtUp) && "md:flex",
        )}
        data-newsroom-list-detail-shell
        data-news-desk-section="references"
        data-detail-open={selectedReference ? "true" : "false"}
        data-feed-flat=""
        {...FEED_SURFACE_PROPS}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 px-4 pt-3 pb-1">
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
              predictionState={predictionState}
              reviewReason={reviewReasons?.get(referenceLineageId(selectedReference))}
              reviewSectionId={reviewSectionIds?.get(referenceLineageId(selectedReference))}
              countsAsTrainingLabel={humanCuratedReferenceLineageIds?.has(referenceLineageId(selectedReference))}
              delegated={delegatedCurations?.get(referenceLineageId(selectedReference))}
              decision={decisions?.get(referenceLineageId(selectedReference))}
              demo={demo}
              disabled={disabled}
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

      {isMobileDetail ? (
        <Sheet
          onOpenChange={(open) => {
            if (!open) closeDetail();
            else setMobileDetailOpen(true);
          }}
          open={(mobileDetailOpen && Boolean(selectedReference)) || caughtUp}
        >
          <SheetContent className="gap-0 rounded-t-[length:var(--feed-radius-xl)] bg-[var(--feed-card)] p-0" data-feed-flat="" data-feed-surface="" side="bottom" {...themeAttributes}>
            <SheetHeader className="border-b border-border px-4 py-3">
              <SheetTitle className="text-left text-base">Reference</SheetTitle>
            </SheetHeader>
            {selectedReference ? (
              <div className="min-w-0" data-review-gestures onPointerDown={gestures.onPointerDown} onPointerUp={gestures.onPointerUp} style={gestures.style}><ScrollArea className="max-h-[70dvh]">
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
                  onClose={closeDetail}
                  onRelevanceReview={onRelevanceReview ? (curation) => onRelevanceReview(selectedReference, curation) : undefined}
                  onReview={runReview}
                  sectionAgreement={sectionAgreement}
                  sectionSuggestion={sectionSuggestions?.get(referenceLineageId(selectedReference))}
                  sections={sections}
                  previewAttachments={previewAttachments}
                  reference={selectedReference}
                />
              </ScrollArea></div>
            ) : caughtUp ? caughtUpPanel : null}
            {queueBar}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
