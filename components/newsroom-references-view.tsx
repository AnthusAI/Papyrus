"use client";

import type { PrimingPanelProps } from "cyclotron/components/priming-panel";
import { ReferenceAddEntry } from "./reference-add-entry";
import { ReferenceCurationControls, useReferenceImport } from "./reference-curation-controls";

import {
  ArchiveIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { normalizeReferenceCurationStatus, referenceReasonCode, REFERENCE_REJECTION_REASON_CODES, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import { newsroomListRowClassName } from "../lib/newsroom-list-selection";
import { ReferenceSourcePreview } from "./reference-source-preview";
import { ReferenceRelevanceReview } from "./reference-relevance-review";
import {
  CountsAsTrainingLabelNote,
  DelegatedCurationNote,
  ReferenceSuggestionBlock,
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
import type { RelevanceCuration, RelevanceDecisionView } from "../lib/relevance-decisions";
import {
  loadReferenceAttachmentsForLineageId,
  loadStoragePathUrl,
} from "./news-desk-taxonomy-client";

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
};

type ReferenceListFilter = ReferenceStatusFilter | "needs_review";

const NEEDS_REVIEW_FILTER: { key: ReferenceListFilter; label: string } = { key: "needs_review", label: "Needs review" };

const STATUS_FILTERS: Array<{ key: ReferenceListFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "accepted", label: "Accepted" },
  { key: "rejected", label: "Rejected" },
  { key: "archived", label: "Archived" },
];

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const update = () => setMatches(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, [query]);
  return matches;
}

function buildReferenceDetailPath(lineageId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo);
}

function referenceUrl(reference: ReferenceRecord): string | null {
  const candidate = reference.sourceUri?.trim() || reference.storagePath?.trim() || null;
  if (!candidate) return null;
  if (/^https?:\/\//i.test(candidate)) return candidate;
  return null;
}

function normalizeReferenceDetailHttpUri(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return null;
}

function useReferencePreviewAttachments(
  reference: ReferenceRecord | null,
  referenceAttachments: ReferenceAttachmentRecord[],
) {
  const lineageId = reference ? referenceLineageId(reference) : "";
  const seededAttachments = useMemo(
    () => referenceAttachments.filter((attachment) => attachment.referenceLineageId === lineageId),
    [lineageId, referenceAttachments],
  );
  const [attachments, setAttachments] = useState<ReferenceAttachmentRecord[]>(seededAttachments);
  const [attachmentLinksById, setAttachmentLinksById] = useState<Record<string, string>>({});

  useEffect(() => {
    setAttachments(seededAttachments);
  }, [seededAttachments]);

  useEffect(() => {
    if (!lineageId) return;
    if (seededAttachments.length > 0) return;
    let active = true;
    void loadReferenceAttachmentsForLineageId(lineageId)
      .then((loaded) => {
        if (!active || !loaded.length) return;
        setAttachments(loaded);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [lineageId, seededAttachments.length]);

  useEffect(() => {
    if (!attachments.length) {
      setAttachmentLinksById({});
      return;
    }
    let active = true;
    const staticLinks = new Map<string, string>();
    const storageLookups: Array<{ id: string; storagePath: string }> = [];

    for (const attachment of attachments) {
      if (attachment.storagePath) {
        storageLookups.push({ id: attachment.id, storagePath: attachment.storagePath });
        continue;
      }
      const sourceHref = normalizeReferenceDetailHttpUri(attachment.sourceUri);
      if (sourceHref) staticLinks.set(attachment.id, sourceHref);
    }

    if (!storageLookups.length) {
      setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
      return () => {
        active = false;
      };
    }

    setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
    void Promise.all(storageLookups.map(async (lookup) => {
      const result = await loadStoragePathUrl(lookup.storagePath);
      return { id: lookup.id, url: result.url };
    }))
      .then((resolved) => {
        if (!active) return;
        const nextLinks = Object.fromEntries(staticLinks.entries());
        for (const entry of resolved) {
          if (entry.url) nextLinks[entry.id] = entry.url;
        }
        setAttachmentLinksById(nextLinks);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [attachments]);

  const previewAttachments = useMemo(
    () => attachments.map((attachment) => ({
      ...attachment,
      sourceUri: attachmentLinksById[attachment.id] ?? attachment.sourceUri,
    })),
    [attachmentLinksById, attachments],
  );

  return previewAttachments;
}

function needsReview(reference: ReferenceRecord, decision: RelevanceDecisionView | undefined): boolean {
  return Boolean(decision?.reviewRecommended)
    && normalizeReferenceCurationStatus(reference.curationStatus) === "pending";
}

function ReferenceDetailPanel({
  countsAsTrainingLabel,
  delegated,
  decision,
  demo,
  disabled,
  onRelevanceReview,
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
  const sourceNote = normalizeReferenceCurationStatus(reference.curationStatus) === "pending" ? "" : reference.curationStatusReason ?? "";
  const sourceReason = reviewReason ?? referenceReasonCode(reference) ?? "";
  const [note, setNote] = useState(sourceNote);
  const [reasonCode, setReasonCode] = useState<ReferenceRejectionReasonCode | "">(sourceReason);
  const [savedNote, setSavedNote] = useState(sourceNote);
  const [savedReason, setSavedReason] = useState<ReferenceRejectionReasonCode | "">(sourceReason);
  const [busy, setBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const saving = useRef(false);
  const noteEdited = useRef(false);
  const reasonEdited = useRef(false);
  useEffect(() => {
    setSavedNote(sourceNote);
    if (!noteEdited.current) setNote(sourceNote);
  }, [sourceNote]);
  useEffect(() => {
    setSavedReason(sourceReason);
    if (!reasonEdited.current) setReasonCode(sourceReason);
  }, [sourceReason]);
  const [chosenSectionId, setChosenSectionId] = useState<string | null>(reviewSectionId ?? null);
  const [savedSectionId, setSavedSectionId] = useState<string | null>(reviewSectionId ?? null);
  const sectionEdited = useRef(false);
  useEffect(() => {
    setSavedSectionId(reviewSectionId ?? null);
    if (!sectionEdited.current) setChosenSectionId(reviewSectionId ?? null);
  }, [reviewSectionId]);
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const url = referenceUrl(reference);
  const locked = disabled || busy;
  const acceptDisabled = locked || status === "accepted";
  const rejectDisabled = locked || status === "rejected";
  const archiveDisabled = locked || status === "archived";

  async function save(action: ReferenceCurationAction, review?: RelevanceCuration) {
    if (disabled || saving.current) return;
    const rejectionReason = review?.reasonCode ?? reasonCode;
    if (action === "reject" && !rejectionReason) {
      setReviewError("Choose a rejection reason before saving. An explanation is optional.");
      return;
    }
    saving.current = true;
    setBusy(true);
    setSaved(false);
    setReviewError(null);
    try {
      if (review && onRelevanceReview) await onRelevanceReview({ ...review, ...(action === "accept" && chosenSectionId ? { sectionId: chosenSectionId } : {}) });
      else await onReview(action, {
        note: note.trim(),
        reasonCode: action === "reject" ? reasonCode || null : null,
        ...(action === "accept" && chosenSectionId ? { sectionId: chosenSectionId } : {}),
        ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
      });
      if (review) {
        setNote(review.note ?? "");
        setReasonCode((review.reasonCode as ReferenceRejectionReasonCode) ?? "");
      }
      setSavedNote(review ? review.note ?? "" : note.trim());
      setSavedReason(action === "reject" ? rejectionReason as ReferenceRejectionReasonCode : "");
      setSavedSectionId(action === "accept" ? chosenSectionId : null);
      noteEdited.current = false;
      reasonEdited.current = false;
      sectionEdited.current = false;
      setSaved(true);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Review could not be saved. Try again.");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return (
    <div
      className="flex h-full flex-col font-sans"
      data-news-desk-reference-detail={lineageId}
    >
      <div className="space-y-4 p-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={referenceStatusBadgeVariant(status)}>{referenceStatusLabel(status)}</Badge>
            {reference.corpusId ? (
              <Badge variant="outline">{reference.corpusId}</Badge>
            ) : null}
          </div>
          <h2 className="text-lg font-semibold leading-snug text-foreground">{referenceDisplayTitle(reference)}</h2>
          {reference.externalItemId ? (
            <p className="text-sm text-muted-foreground">{reference.externalItemId}</p>
          ) : null}
        </div>

        {decision ? (
          <div className="space-y-3" data-reference-relevance-decision={lineageId}>
            <ReferenceSuggestionBlock
              decision={decision}
              disabled={locked}
              onCurate={onRelevanceReview ? (review) => { void save(review.action, { ...review, note: note.trim() || null, reasonCode: review.action === "reject" ? reasonCode || null : null }); } : undefined}
              referenceLineageId={lineageId}
              settled={status !== "pending"}
              statusLabel={referenceStatusLabel(status)}
            />
            <ReferenceSuggestionProvenance decision={decision} />
            {status === "pending" && onRelevanceReview ? (
              <details className="text-sm text-foreground">
                <summary className="cursor-pointer font-semibold underline-offset-4 hover:underline">Review with a reason</summary>
                <div className="mt-2">
                  <ReferenceRelevanceReview
                    decision={decision}
                    disabled={locked}
                    onCurate={(review) => save(review.action, review)}
                    referenceLineageId={lineageId}
                  />
                </div>
              </details>
            ) : null}
          </div>
        ) : predictionState === "ready" ? (
          <section aria-label="Publication prediction" className="space-y-1 rounded-md border p-3">
            <h3 className="text-sm font-semibold">No prediction recorded</h3>
            <p className="text-sm text-muted-foreground">No publication relevance prediction was returned for this reference. You can still review it. Pending is its editorial status, not a prediction status.</p>
          </section>
        ) : null}
        {sectionSuggestion || ((status === "pending" || status === "accepted") && sections.length) ? (
          <details className="rounded-md border p-3 text-sm">
            <summary className="cursor-pointer font-semibold">Section placement (optional)</summary>
            <div className="mt-3 space-y-3">
            {sectionSuggestion ? <SectionSuggestionBlock agreement={sectionAgreement} referenceLineageId={lineageId} sections={sections} suggestion={sectionSuggestion} /> : null}
            {(status === "pending" || status === "accepted") && sections.length ? <SectionPicker
            agreement={sectionAgreement}
            chosenSectionId={chosenSectionId}
            disabled={locked}
            onChoose={(sectionId) => { setChosenSectionId(sectionId); sectionEdited.current = true; setSaved(false); }}
            referenceLineageId={lineageId}
            sections={sections}
            suggestedSectionId={sectionSuggestion?.sectionId ?? null}
            /> : null}
            </div>
          </details>
        ) : null}
        {delegated ? <DelegatedCurationNote delegated={delegated} referenceLineageId={lineageId} /> : countsAsTrainingLabel ? <CountsAsTrainingLabelNote referenceLineageId={lineageId} /> : null}

        <section aria-label="Editor feedback" className="space-y-3">
          <h3 className="text-sm font-semibold">Editor feedback</h3>
          {disabled ? <p className="text-sm text-muted-foreground">Editor access is required to change this reference.</p> : null}
          <label className="block text-sm">
            Review explanation (optional)
            <textarea aria-label="Review explanation (optional)" className="mt-1 block min-h-20 w-full rounded-md border bg-background p-2" disabled={locked} value={note} onChange={(event) => { setNote(event.target.value); noteEdited.current = true; setSaved(false); }} />
          </label>
          <label className="block text-sm">
            Rejection reason
            <select aria-label="Rejection reason" className="mt-1 block w-full rounded-md border bg-background p-2" disabled={locked} value={reasonCode} onChange={(event) => { setReasonCode(event.target.value as ReferenceRejectionReasonCode | ""); reasonEdited.current = true; setSaved(false); }}>
              <option value="">Choose a reason when rejecting</option>
              {REFERENCE_REJECTION_REASON_CODES.map((code) => <option key={code} value={code}>{code.charAt(0).toUpperCase() + code.slice(1).replaceAll("_", " ")}</option>)}
            </select>
          </label>
          <p className="text-xs text-muted-foreground">Only out of scope and policy exclusion are negative relevance labels. Other rejection reasons do not teach relevance.</p>
        <div
          className="flex flex-wrap items-center gap-2"
          data-news-desk-reference-curation-cluster
          data-reference-curation-status={status}
        >
          <Button
            aria-label="Accept reference"
            aria-pressed={status === "accepted"}
            data-news-desk-reference-accept
            disabled={acceptDisabled}
            onClick={() => { void save("accept"); }}
            size="sm"
            type="button"
            variant={status === "accepted" ? "default" : "outline"}
          >
            <ThumbsUpIcon className="size-4" />
            Accept
          </Button>
          <Button
            aria-label="Reject reference"
            aria-pressed={status === "rejected"}
            data-news-desk-reference-reject
            disabled={rejectDisabled}
            onClick={() => { void save("reject"); }}
            size="sm"
            type="button"
            variant={status === "rejected" ? "destructive" : "outline"}
          >
            <ThumbsDownIcon className="size-4" />
            Reject
          </Button>
          <Button
            aria-label="Archive reference"
            disabled={archiveDisabled}
            onClick={() => { void save("archive"); }}
            size="sm"
            type="button"
            variant="outline"
          >
            <ArchiveIcon className="size-4" />
            Archive
          </Button>
          {status === "accepted" || status === "rejected" ? (
            <Button disabled={locked || predictionState !== "ready" || (note.trim() === savedNote.trim() && (status !== "rejected" || reasonCode === savedReason) && (status !== "accepted" || chosenSectionId === savedSectionId))} onClick={() => { void save(status === "accepted" ? "accept" : "reject"); }} size="sm" type="button" variant="outline">Save feedback</Button>
          ) : null}
        </div>
        {status !== "pending" && predictionState !== "ready" ? <p className="text-sm text-muted-foreground">Load the review details before revising saved feedback.</p> : null}
        {busy ? <p role="status" className="text-sm">Saving review…</p> : saved ? <p role="status" className="text-sm">Review saved.</p> : null}
        {reviewError ? <p role="alert" className="text-sm text-destructive">{reviewError}</p> : null}
        </section>

        <Separator />

        <section aria-label="Source preview" className="space-y-2">
          <h3 className="text-sm font-medium text-foreground">Source preview</h3>
          <ReferenceSourcePreview attachments={previewAttachments} sourceUri={reference.sourceUri} />
        </section>

        <dl className="grid gap-3 text-sm">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Why</dt>
            <dd className="mt-1 text-foreground">
              {reference.curationStatusReason?.trim()
                || "No explanation recorded."}
            </dd>
          </div>
          {url ? (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Source</dt>
              <dd className="mt-1">
                <a
                  className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                  href={url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {url}
                  <ExternalLinkIcon className="size-3.5" aria-hidden="true" />
                </a>
              </dd>
            </div>
          ) : null}
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
  decisions,
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
  references,
}: NewsroomReferencesViewProps) {
  const pathname = usePathname();
  const sessionImport = useReferenceImport(disabled);
  const [importedCount, setImportedCount] = useState(0);
  const isMobileDetail = useMediaQuery("(max-width: 767px)");
  const pathnameLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeLineageId = pathname ? pathnameLineageId ?? "" : initialReferenceLineageId ?? "";

  const canonicalReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  const statusCounts = useMemo(() => countReferencesByStatus(canonicalReferences), [canonicalReferences]);

  const [statusFilter, setStatusFilter] = useState<ReferenceListFilter>("all");
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

  const selectedIndex = selectedReference
    ? filteredReferences.findIndex((entry) => referenceLineageId(entry) === referenceLineageId(selectedReference))
    : -1;
  const previousReference = selectedIndex > 0 ? filteredReferences[selectedIndex - 1] : null;
  const nextReference = selectedIndex >= 0 && selectedIndex < filteredReferences.length - 1
    ? filteredReferences[selectedIndex + 1]
    : null;

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
    setSelectedLineageId(lineageId);
    if (isMobileDetail) setMobileDetailOpen(true);
    if (typeof window !== "undefined") {
      const nextPath = buildReferenceDetailPath(lineageId, demo);
      if (`${window.location.pathname}${window.location.search}` !== nextPath) {
        window.history.pushState(null, "", nextPath);
      }
    }
  };

  const closeDetail = () => {
    setMobileDetailOpen(false);
    setSelectedLineageId("");
    if (typeof window !== "undefined") {
      const indexPath = getNewsroomNavHref("/newsroom/references", demo);
      window.history.replaceState(null, "", indexPath);
    }
  };

  const runReview = (action: ReferenceCurationAction, options?: ReferenceReviewOptions) => {
    if (!selectedReference) return;
    return onReview(selectedReference, action, options);
  };

  const emptyLabel = canonicalReferences.length
    ? "No references match this filter."
    : "No private references imported yet.";

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 md:max-h-[calc(100dvh-8.5rem)] md:flex-row"
      data-news-desk-section="references"
      data-detail-open={selectedReference || routeLineageId ? "true" : "false"}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 md:overflow-hidden">
        <div className="shrink-0 space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">References</h2>
          <p className="text-sm text-muted-foreground">
            Review source intake before it becomes accepted evidence.
          </p>
        </div>
        {predictionState === "loading" ? <p role="status">Loading predictions…</p> : null}
        {predictionState === "error" ? (
          <div role="alert" className="space-y-2 rounded-md border p-3">
            <p>Predictions unavailable. {predictionError}</p>
            <p className="text-sm">You can still review references. Existing suggestions may be out of date.</p>
            {onRetryPredictions ? <Button onClick={onRetryPredictions} size="sm" type="button" variant="outline">Retry predictions</Button> : null}
          </div>
        ) : null}
        <details className="shrink-0 overflow-y-auto rounded-md border p-3 text-sm" style={{ maxHeight: "35dvh" }}>
          <summary className="cursor-pointer font-semibold">Add a reference and prediction activity</summary>
          <div className="mt-3 space-y-4">
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
        </details>

        <Tabs
          className="shrink-0"
          defaultValue="all"
          onValueChange={(value) => {
            const next = value as ReferenceListFilter;
            setStatusFilter(next);
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
      </div>

      <div
        className="hidden min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card md:flex md:w-[min(100%,24rem)] lg:w-[min(100%,28rem)]"
        data-newsroom-list-detail-shell
        data-news-desk-section="references"
        data-detail-open={selectedReference ? "true" : "false"}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="text-sm font-medium text-foreground">Detail</span>
          <div className="newsroom-list-detail-shell__detail-toolbar-trailing flex items-center gap-1">
            <Button
              aria-label="Previous"
              disabled={!previousReference}
              onClick={() => previousReference && selectReference(referenceLineageId(previousReference))}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
            <Button
              aria-label="Next"
              disabled={!nextReference}
              onClick={() => nextReference && selectReference(referenceLineageId(nextReference))}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronRightIcon className="size-4" />
            </Button>
          </div>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          {selectedReference ? (
            <ReferenceDetailPanel
              key={referenceLineageId(selectedReference)}
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
          ) : (
            <CardContent className="p-4 text-sm text-muted-foreground">
              Select a reference to inspect curation details.
            </CardContent>
          )}
        </ScrollArea>
      </div>

      {isMobileDetail ? (
        <Sheet
          onOpenChange={(open) => {
            if (!open) closeDetail();
            else setMobileDetailOpen(true);
          }}
          open={mobileDetailOpen && Boolean(selectedReference)}
        >
          <SheetContent className="gap-0 p-0" side="bottom">
            <SheetHeader className="border-b border-border px-4 py-3">
              <SheetTitle className="text-left text-base">Reference</SheetTitle>
            </SheetHeader>
            {selectedReference ? (
              <ScrollArea className="max-h-[75dvh]">
                <ReferenceDetailPanel
                  key={referenceLineageId(selectedReference)}
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
              </ScrollArea>
            ) : null}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
