"use client";

import { referenceDisplayTitle, referenceLineageId, formatReferenceListDate } from "../lib/newsroom-references";
import { referenceMetadataField } from "../lib/reference-display";
import { referenceDek, referencePreviewsByLineage } from "../lib/reference-preview";
import { DEFAULT_TEASER_WORDS } from "../lib/reference-capture";
import { isAutoAccepted, referenceReasonCode, normalizeReferenceCurationStatus } from "../lib/reference-policy";
import { AutoAcceptedBadge } from "./auto-accepted-badge";
import type { ReferenceRecord } from "../lib/category-repository";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import { referenceDatesText } from "../lib/reference-links";
import { DefaultOutcome, Heading, type DetailProps } from "./needs-me-bodies";
import { decidedChoiceOf } from "./needs-me-shared";
import { predictionFromDecision, ReviewCard, type CardPrediction } from "./reference-review-card";
import { ReferenceConversation } from "./reference-conversation";
import { RelatedSection } from "./related-section";
import { ReferenceCapturePanel } from "./reference-capture-panel";
import { useReferenceCapture } from "./reference-capture-client";
import { ReferenceSourcePreview } from "./reference-source-preview";
import { ReferenceSuggestionProvenance } from "./reference-cyclotron-suggestion";
import { useReferencePreviewAttachments } from "./use-reference-preview-attachments";

function cardPrediction(item: NeedsMeEntry, predictionLoading: boolean): CardPrediction {
  if (item.payload.kind === "reference" && item.payload.decision) return predictionFromDecision(item.payload.decision);
  return predictionLoading ? { state: "loading" } : { state: "none" };
}

/**
 * A Reference, or a Reference whose capture may be cut off: the References detail's own pieces, in the same order. What the item is
 * comes first (title, blurb, link, badges, summary), then the rating, then what was captured and how well.
 */
export function ReferenceBody(props: DetailProps & { payload: Extract<NeedsMeEntry["payload"], { kind: "reference" }> }) {
  const { item, payload, ratings, disabledReason, attachments, captureTeaserLine = DEFAULT_TEASER_WORDS, onCorrectCapture, predictionLoading } = props;
  const reference: ReferenceRecord = payload.reference;
  const lineageId = referenceLineageId(reference);
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const previewAttachments = useReferencePreviewAttachments(reference, attachments);
  const capture = useReferenceCapture(reference, previewAttachments, captureTeaserLine, onCorrectCapture);
  const url = reference.sourceUri?.trim() && /^https?:\/\//i.test(reference.sourceUri.trim()) ? reference.sourceUri.trim() : null;
  const summary = capture.summary ?? referenceMetadataField(null, reference.metadata, "summary");
  const dek = referenceDek(reference, referencePreviewsByLineage(previewAttachments).get(lineageId));
  const incomplete = item.type === "incomplete_capture";
  const auto = isAutoAccepted(reference);
  return (
    <div className="space-y-4" data-reference-curation-status={status} data-news-desk-reference-detail={lineageId}>
      <ReviewCard
        decided={decidedChoiceOf(item)}
        disabledReason={disabledReason}
        initialNote={status === "pending" || auto ? "" : reference.curationStatusReason ?? ""}
        initialReason={referenceReasonCode(reference) ?? null}
        dek={dek}
        itemId={item.id}
        meta={<><Heading item={item} /><span className="text-xs text-muted-foreground" data-reference-dates>{referenceDatesText(reference)}</span>{auto ? <AutoAcceptedBadge actor={reference.curationStatusUpdatedBy} reason={reference.curationStatusReason} /> : null}</>}
        onDecide={async () => undefined}
        prediction={cardPrediction(item, predictionLoading)}
        ratings={ratings}
        sourcePreview={<ReferenceSourcePreview attachments={previewAttachments} sourceUri={reference.sourceUri} />}
        summary={summary}
        title={referenceDisplayTitle(reference)}
        titleHref={url}
      >
        {payload.decision ? <div data-reference-relevance-decision={lineageId}><ReferenceSuggestionProvenance decision={payload.decision} /></div> : null}
        <RelatedSection disabledReason={disabledReason ? "Editor access is required to change links." : null} lineageId={lineageId} referenceId={reference.id} />
        <ReferenceConversation disabledReason={disabledReason ? "Editor access is required to write messages." : null} lineageId={lineageId} referenceId={reference.id} title={referenceDisplayTitle(reference)} />
      </ReviewCard>
      <DefaultOutcome item={item} />
      {incomplete ? <p className="text-sm text-muted-foreground" data-needs-me-capture-note>The captured text looks cut off or missing. Read it below. If it is incomplete, choose Paste or correct the text and say whether the capture was complete, or rate the Reference as it is.</p> : null}
      <ReferenceCapturePanel capture={capture} showSummary={false} />
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Imported</dt>
          <dd className="mt-1 text-foreground">{formatReferenceListDate(reference)}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Media</dt>
          <dd className="mt-1 text-foreground">{reference.mediaType ?? "unknown"}</dd>
        </div>
      </dl>
    </div>
  );
}

